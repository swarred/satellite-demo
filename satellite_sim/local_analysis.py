"""
Offline local LLM alert analysis service.

Runs in the satellite's offline bootc image (no OCP connectivity).
Watches /var/lib/satellite-sim/alerts.jsonl for new detections,
classifies each via Ollama (phi4-mini), and appends results to
/var/lib/satellite-sim/offline-queue.jsonl.

Results persist across bootc switches — the online image loads this
file on startup and flushes the analyzed alerts to the ground station.
"""

import json
import logging
import os
import time

import requests

STATE_DIR = "/var/lib/satellite-sim"
ALERTS_FILE = os.path.join(STATE_DIR, "alerts.jsonl")
OFFLINE_QUEUE = os.path.join(STATE_DIR, "offline-queue.jsonl")
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:1b"
POLL_INTERVAL = 10  # seconds between queue checks

VALID_CLASSIFICATIONS = {
    "DIRECTED_ENERGY", "RF_EMITTER", "THERMAL_PLUME",
    "THERMAL_ANOMALY", "ORBITAL_DEBRIS", "UNKNOWN_EMITTER",
}

SUMMARY_PROMPT = (
    "You are analyzing a satellite thermal IR sensor alert from a LEO reconnaissance satellite "
    "monitoring the Persian Gulf / Arabian Peninsula corridor for ground-based military activity.\n\n"
    "Classification definitions:\n"
    "- DIRECTED_ENERGY: high-energy laser, high-powered microwave, or electronic warfare emitter\n"
    "- RF_EMITTER: active radar, communications jammer, or electronic warfare system\n"
    "- THERMAL_PLUME: rocket motor, missile exhaust, or jet propulsion heat signature\n"
    "- THERMAL_ANOMALY: vehicle engine heat, industrial activity, or unclassified heat source\n\n"
    "This detection was classified as: {classification}\n"
    "Location: {lat:.4f}N {lon:.4f}E (Persian Gulf region)\n\n"
    "Write ONE sentence for a military operator describing what specific ground-based activity "
    "this signature is consistent with, given the classification. Be concise and operational. "
    "Do not mention confidence or satellite altitude.\n\n"
    'Return ONLY: {{"summary": "your one sentence here"}}'
)

# Classification is determined by sensor confidence — not the LLM.
# Small models are unreliable at following conditional rules; Python is not.
def _classify_by_confidence(confidence: float) -> str:
    if confidence >= 0.90:
        return "DIRECTED_ENERGY"
    elif confidence >= 0.80:
        return "RF_EMITTER"
    elif confidence >= 0.75:
        return "THERMAL_PLUME"
    else:
        return "THERMAL_ANOMALY"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _analyzed_ids() -> set:
    ids = set()
    for path in (OFFLINE_QUEUE, OFFLINE_QUEUE + ".loaded"):
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    ids.add(json.loads(line)["alert_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


def _classify(alert: dict) -> dict:
    confidence = float(alert.get("confidence", 0.0))
    # Classification is deterministic — confidence bands, not LLM judgment.
    classification = _classify_by_confidence(confidence)

    prompt = SUMMARY_PROMPT.format(
        classification=classification,
        lat=alert.get("lat", 0.0),
        lon=alert.get("lon", 0.0),
        alt_km=alert.get("alt_km", 0.0),
    )
    base = {
        "alert_id": alert["alert_id"],
        "timestamp": alert.get("timestamp", ""),
        "lat": alert.get("lat", 0.0),
        "lon": alert.get("lon", 0.0),
        "alt_km": alert.get("alt_km", 0.0),
        "frame_id": alert.get("frame_id", -1),
        "confidence": confidence,
        "classification": classification,
        "offline": True,
        "model": MODEL,
    }
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json",
                  "options": {"num_predict": 80}},
            timeout=120,
        )
        resp.raise_for_status()
        result = json.loads(resp.json().get("response", "{}"))
        return {
            **base,
            "summary": result.get("summary", "Analyzed autonomously during DDIL."),
            "source": "local_llm",
        }
    except Exception as exc:
        log.error("Ollama summary failed for %s: %s", alert.get("alert_id"), exc)
        return {
            **base,
            "summary": "Offline analysis complete — classification stored for ground station review.",
            "source": "local_llm_error",
        }


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    log.info("Local analysis service started — watching %s", ALERTS_FILE)

    while True:
        try:
            if os.path.exists(ALERTS_FILE):
                analyzed = _analyzed_ids()
                with open(ALERTS_FILE) as f:
                    alerts = [json.loads(line) for line in f if line.strip()]

                for alert in alerts:
                    aid = alert.get("alert_id")
                    if not aid or aid in analyzed:
                        continue
                    if alert.get("satellite_mode", "offline") != "offline":
                        continue
                    log.info("Classifying alert %s (confidence=%.3f)", aid, alert.get("confidence", 0))
                    result = _classify(alert)
                    with open(OFFLINE_QUEUE, "a") as qf:
                        qf.write(json.dumps(result) + "\n")
                    log.info("Classified %s → %s", aid, result["classification"])
                    analyzed.add(aid)
        except Exception:
            log.exception("Error in analysis loop")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
