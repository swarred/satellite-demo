import json
import os
import time

import requests
from flask import Flask, render_template, request, Response

app = Flask(__name__)

SATELLITE_URL = os.environ.get("SATELLITE_URL", "http://satellite-alerts:8080")
MAAS_URL = os.environ.get("MAAS_URL", "")
MAAS_KEY = os.environ.get("MAAS_KEY", "")

# Link state — updated on every satellite API call
_link_up: bool = False
_last_contact: float = 0.0

# Assessments keyed by alert_id — persists across polls so cards survive re-renders
_assessments: dict = {}

# Last successful alert fetch — served stale while satellite is unreachable so
# offline alerts remain visible during Skupper reconnect after bootc switch
_cached_alerts: list = []


def _get(path, timeout=3):
    global _link_up, _last_contact
    try:
        r = requests.get(f"{SATELLITE_URL}{path}", timeout=timeout)
        r.raise_for_status()
        _link_up = True
        _last_contact = time.monotonic()
        return r.json()
    except Exception:
        _link_up = False
        return None


def _link_status():
    return {
        "up": _link_up,
        "elapsed": int(time.monotonic() - _last_contact) if _last_contact else None,
    }


def _alerts():
    global _cached_alerts
    result = _get("/alerts")
    if result is not None:
        _cached_alerts = result
    return _cached_alerts


def _alerts_annotated():
    alerts = _alerts()
    for a in alerts:
        if a.get("alert_id") in _assessments:
            a["assessment"] = _assessments[a["alert_id"]]
    return sorted(alerts, key=lambda a: a.get("timestamp", ""), reverse=True)


def _telemetry():
    return _get("/telemetry") or {}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    alerts, telemetry = _alerts_annotated(), _telemetry()
    return render_template("index.html", alerts=alerts, telemetry=telemetry, link=_link_status())


# ── HTMX partials ─────────────────────────────────────────────────────────────

@app.get("/api/telemetry")
def api_telemetry():
    from flask import jsonify
    return jsonify(_get("/telemetry") or {})


@app.get("/partials/alerts")
def partial_alerts():
    return render_template("_alerts.html", alerts=_alerts_annotated())


@app.get("/partials/telemetry")
def partial_telemetry():
    return render_template("_telemetry.html", telemetry=_telemetry())


@app.get("/partials/linkstatus")
def partial_linkstatus():
    return render_template("_linkstatus.html", link=_link_status())


# ── Actions ───────────────────────────────────────────────────────────────────

@app.post("/alerts/<alert_id>/ack")
def ack_alert(alert_id):
    try:
        requests.post(f"{SATELLITE_URL}/alerts/{alert_id}/ack", timeout=3)
    except Exception:
        pass
    alert = next((a for a in _alerts_annotated() if a["alert_id"] == alert_id), None)
    if not alert:
        return "", 204
    return render_template("_alert_card.html", alert=alert)


@app.post("/alerts/<alert_id>/analyze")
def analyze_alert(alert_id):
    alert = next((a for a in _alerts() if a["alert_id"] == alert_id), None)
    if not alert:
        return "<div class='assessment'><span class='assessment-header'>ERROR</span> Alert not found.</div>", 404
    assessment = _run_analysis(alert)
    _assessments[alert_id] = assessment
    try:
        requests.post(
            f"{SATELLITE_URL}/alerts/{alert_id}/classify",
            json={"classification": assessment["classification"]},
            timeout=3,
        )
    except Exception:
        pass
    updated = next((a for a in _alerts_annotated() if a["alert_id"] == alert_id), alert)
    return render_template("_alert_card.html", alert=updated)


@app.post("/alerts/<alert_id>/dismiss")
def dismiss_assessment(alert_id):
    _assessments.pop(alert_id, None)
    alert = next((a for a in _alerts_annotated() if a["alert_id"] == alert_id), None)
    if not alert:
        return "", 204
    return render_template("_alert_card.html", alert=alert)


@app.get("/frames/<alert_id>")
def get_frame(alert_id):
    try:
        r = requests.get(f"{SATELLITE_URL}/alerts/{alert_id}/frame", timeout=5)
        if r.status_code == 404:
            abort(404)
        r.raise_for_status()
        return Response(r.content, mimetype="image/png")
    except Exception:
        abort(503)


@app.post("/demo/clear-alerts")
def demo_clear_alerts():
    _assessments.clear()
    try:
        requests.post(f"{SATELLITE_URL}/alerts/clear", timeout=3)
    except Exception:
        pass
    return render_template("_alerts.html", alerts=[])


@app.post("/demo/reset-orbit")
def demo_reset_orbit():
    try:
        requests.post(f"{SATELLITE_URL}/orbit/reset", timeout=3)
    except Exception:
        pass
    return "", 204


@app.post("/demo/trigger")
def demo_trigger():
    try:
        requests.post(f"{SATELLITE_URL}/demo/trigger", timeout=3)
    except Exception:
        pass
    return render_template("_alerts.html", alerts=_alerts())


@app.post("/demo/ddil-on")
def demo_ddil_on():
    """Operator control: simulate DDIL by signalling the satellite to enter autonomous mode."""
    try:
        r = requests.post(f"{SATELLITE_URL}/demo/ddil-on", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}, 502


# ── Analysis ──────────────────────────────────────────────────────────────────

def _run_analysis(alert):
    # Alerts classified autonomously during DDIL carry their analysis inline
    if alert.get("offline"):
        source = alert.get("offline_source", "local_llm")
        classification = alert.get("classification", "UNKNOWN_EMITTER")
        if source == "local_llm_error" or classification == "UNKNOWN_EMITTER":
            text = (
                "Alert was captured and stored during DDIL autonomous mode. "
                "Local LLM classification was unsuccessful — insufficient onboard resources. "
                "Re-analysis recommended now that ground station connectivity is restored."
            )
        else:
            text = alert.get("offline_summary", "Analyzed autonomously during DDIL — no ground station connectivity.")
        return {
            "text": text,
            "classification": classification,
            "model": f"{alert.get('offline_model', 'phi4-mini')} (offline local LLM)",
            "latency": "0.0s",
            "source": source,
        }
    if MAAS_URL and MAAS_KEY:
        result = _maas_analysis(alert)
        if result:
            return result
    return _stub_analysis(alert)


_VALID_CLASSIFICATIONS = {
    "RF_EMITTER", "DIRECTED_ENERGY", "THERMAL_PLUME",
    "RADAR_EMITTER", "THERMAL_ANOMALY", "UNKNOWN_EMITTER",
}


def _parse_classification(text):
    """Extract CLASSIFICATION: <label> from the first line of an LLM response."""
    for line in text.splitlines():
        if line.upper().startswith("CLASSIFICATION:"):
            label = line.split(":", 1)[1].strip().upper()
            if label in _VALID_CLASSIFICATIONS:
                return label
    return "UNKNOWN_EMITTER"


def _strip_classification_line(text):
    return "\n".join(
        line for line in text.splitlines()
        if not line.upper().startswith("CLASSIFICATION:")
    ).strip()


def _maas_analysis(alert):
    prompt = (
        "You are a military threat assessment AI supporting space domain awareness. "
        "Analyze the following satellite detection alert and produce a structured commander's assessment. "
        "Be direct, specific, and use military brevity.\n\n"
        "Your response MUST begin with a classification line in this exact format:\n"
        "CLASSIFICATION: <label>\n"
        "where <label> is exactly one of: RF_EMITTER, DIRECTED_ENERGY, THERMAL_PLUME, "
        "RADAR_EMITTER, THERMAL_ANOMALY, UNKNOWN_EMITTER\n\n"
        "After the classification line, include: (1) confidence interpretation, "
        "(2) threat likelihood, (3) recommended immediate action. "
        "Maximum 120 words total.\n\n"
        f"Alert:\n{json.dumps(alert, indent=2)}"
    )
    try:
        t0 = time.monotonic()
        r = requests.post(
            f"{MAAS_URL}/chat/completions",
            headers={"Authorization": f"Bearer {MAAS_KEY}", "Content-Type": "application/json"},
            json={
                "model": "microsoft/phi-4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.3,
            },
            timeout=20,
        )
        r.raise_for_status()
        latency = time.monotonic() - t0
        raw = r.json()["choices"][0]["message"]["content"].strip()
        classification = _parse_classification(raw)
        text = _strip_classification_line(raw)
        return {"text": text, "classification": classification, "model": "microsoft/phi-4", "latency": f"{latency:.1f}s", "source": "MaaS"}
    except Exception:
        return None


def _stub_analysis(alert):
    conf = alert.get("confidence", 0.0)
    lat = alert.get("lat", 0.0)
    lon = alert.get("lon", 0.0)

    if conf >= 0.90:
        classification = "DIRECTED_ENERGY"
        threat = "HIGH"
        action = "Notify theater commander immediately. Initiate secondary sensor tasking. Do not dismiss."
    elif conf >= 0.75:
        classification = "RF_EMITTER"
        threat = "HIGH"
        action = "Notify theater commander immediately. Initiate secondary sensor tasking. Do not dismiss."
    elif conf >= 0.60:
        classification = "THERMAL_PLUME"
        threat = "MODERATE"
        action = "Queue for secondary sensor correlation. Maintain heightened awareness on subsequent passes."
    else:
        classification = "THERMAL_ANOMALY"
        threat = "LOW"
        action = "Log and monitor. Flag for analyst review on next contact window."

    text = (
        f"Detection at {lat:.3f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.3f}°{'E' if lon >= 0 else 'W'}. "
        f"Confidence {conf * 100:.0f}% — assessed threat level {threat}. "
        f"Signal persistence and spectral characteristics are inconsistent with known benign background sources. "
        f"Pattern is consistent with a ground-based active RF emitter or directed-energy system. "
        f"RECOMMENDED ACTION: {action}"
    )
    return {"text": text, "classification": classification, "model": "stub", "latency": "0.0s", "source": "local"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
