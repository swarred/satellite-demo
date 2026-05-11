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
MODEL = "phi4-mini:latest"
POLL_INTERVAL = 10  # seconds between queue checks

VALID_CLASSIFICATIONS = {
    "DIRECTED_ENERGY", "RF_EMITTER", "THERMAL_PLUME",
    "THERMAL_ANOMALY", "ORBITAL_DEBRIS", "UNKNOWN_EMITTER",
}

PROMPT_TEMPLATE = (
    "You are an autonomous satellite threat assessment system.\n"
    "Sensor: thermal IR multi-spectral imager aboard a LEO reconnaissance satellite.\n"
    "The sensor detected a high-intensity point-source emitter — a tight thermal signature "
    "significantly above background, consistent with an active radar, directed-energy weapon, "
    "rocket plume, or industrial thermal anomaly.\n"
    "Area of interest: Persian Gulf / Arabian Peninsula corridor (18-32N, 42-75E).\n\n"
    "Classify this detection using confidence as the primary discriminator:\n"
    "- confidence >= 0.90  -> DIRECTED_ENERGY  (very high SNR, tight emitter cluster, active weapon/system signature)\n"
    "- confidence 0.80-0.89 -> RF_EMITTER      (strong coherent signal, likely active radar or jammer)\n"
    "- confidence 0.75-0.79 -> THERMAL_PLUME   (elevated thermal signature, probable propulsion or industrial)\n"
    "- confidence < 0.75   -> THERMAL_ANOMALY  (moderate contrast, ambiguous source, warrants monitoring)\n\n"
    'The "classification" value MUST be one of these exact strings:\n'
    "DIRECTED_ENERGY, RF_EMITTER, THERMAL_PLUME, THERMAL_ANOMALY, ORBITAL_DEBRIS, UNKNOWN_EMITTER\n\n"
    "Respond with ONLY a JSON object. Example:\n"
    '{{"classification": "RF_EMITTER", "confidence": 0.85, "summary": "Strong coherent RF signature at low altitude consistent with surface-based radar system."}}\n\n'
    "Detection:\n"
    "- Sensor confidence: {confidence}\n"
    "- Location: {lat:.4f}N, {lon:.4f}E\n"
    "- Altitude: {alt_km:.1f} km\n"
    "- Timestamp: {timestamp}"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _analyzed_ids() -> set:
    if not os.path.exists(OFFLINE_QUEUE):
        return set()
    ids = set()
    with open(OFFLINE_QUEUE) as f:
        for line in f:
            try:
                ids.add(json.loads(line)["alert_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def _classify(alert: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        confidence=alert.get("confidence", 0.0),
        lat=alert.get("lat", 0.0),
        lon=alert.get("lon", 0.0),
        alt_km=alert.get("alt_km", 0.0),
        timestamp=alert.get("timestamp", ""),
    )
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        result = json.loads(resp.json().get("response", "{}"))
        classification = result.get("classification", "UNKNOWN_EMITTER")
        if classification not in VALID_CLASSIFICATIONS:
            classification = "UNKNOWN_EMITTER"
        return {
            "alert_id": alert["alert_id"],
            "classification": classification,
            "confidence": float(result.get("confidence", alert.get("confidence", 0.0))),
            "summary": result.get("summary", "Analyzed autonomously during DDIL."),
            "source": "local_llm",
            "model": MODEL,
            "offline": True,
        }
    except Exception as exc:
        log.error("Ollama classification failed for %s: %s", alert.get("alert_id"), exc)
        return {
            "alert_id": alert["alert_id"],
            "classification": alert.get("classification", "UNKNOWN_EMITTER"),
            "confidence": float(alert.get("confidence", 0.0)),
            "summary": f"Offline analysis error — stored for ground station review.",
            "source": "local_llm_error",
            "model": MODEL,
            "offline": True,
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
