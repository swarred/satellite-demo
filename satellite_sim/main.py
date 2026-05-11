"""
Satellite simulation service — main entry point.

Runs two things:
  1. A background thread that ticks the orbital + imagery simulation loop
  2. A Flask HTTP API exposing telemetry, status, and alerts to RHSI / OCP

Endpoints:
  GET  /telemetry          current orbital state
  GET  /status             simulation state and counters
  GET  /alerts             list of all detection alerts (newest first)
  POST /alerts/<id>/ack    mark an alert as routed (called by the ground station)
  GET  /healthz            liveness probe
"""

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import asdict

import numpy as np
from flask import Flask, jsonify, abort, request, Response

from satellite_sim.orbital import SatelliteTracker
from satellite_sim import imagery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# How many seconds between simulation ticks
TICK_INTERVAL = 2.0

# Keep the last N alerts in memory
MAX_ALERTS = 200

# Alert cooldown — don't fire again for this many seconds after a detection
ALERT_COOLDOWN = 60

# Persistent state directory (created by StateDirectory= in the systemd unit)
STATE_DIR = "/var/lib/satellite-sim"
ALERTS_FILE = os.path.join(STATE_DIR, "alerts.jsonl")
OFFLINE_QUEUE = os.path.join(STATE_DIR, "offline-queue.jsonl")

app = Flask(__name__)

# Shared state — written by sim thread, read by Flask handlers
_lock = threading.Lock()
_telemetry: dict = {}
_status: dict = {"state": "initializing", "frame_count": 0, "alert_count": 0}
_alerts: deque = deque(maxlen=MAX_ALERTS)
_frames: dict = {}   # alert_id → PNG bytes; evicted in step with _alerts

# Set by /orbit/reset to trigger a SatelliteTracker reinit on next sim tick
_orbit_reset = threading.Event()


def _load_offline_queue():
    """On startup, inject any alerts classified during DDIL offline mode."""
    if not os.path.exists(OFFLINE_QUEUE):
        return
    try:
        with open(OFFLINE_QUEUE) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        if not entries:
            return
        log.info("Loading %d offline-classified alerts from %s", len(entries), OFFLINE_QUEUE)
        # Reconstruct alert dicts merging offline analysis metadata
        with _lock:
            for entry in reversed(entries):  # reversed so newest ends up at front
                alert = {
                    "alert_id": entry["alert_id"],
                    "timestamp": entry.get("timestamp", ""),
                    "confidence": entry["confidence"],
                    "lat": entry.get("lat", 0.0),
                    "lon": entry.get("lon", 0.0),
                    "alt_km": entry.get("alt_km", 0.0),
                    "frame_id": entry.get("frame_id", -1),
                    "classification": entry["classification"],
                    "routed": False,
                    "offline": True,
                    "offline_summary": entry.get("summary", "Analyzed autonomously during DDIL."),
                    "offline_model": entry.get("model", "phi4-mini"),
                }
                _alerts.appendleft(alert)
                _status["alert_count"] += 1
        # Archive the queue so it isn't reloaded on next restart
        os.rename(OFFLINE_QUEUE, OFFLINE_QUEUE + ".loaded")
        log.info("Offline queue loaded and archived — alerts will be forwarded to ground station")
    except Exception:
        log.exception("Failed to load offline queue")


def _persist_alert(alert: dict):
    """Append a detection alert to the persistent JSONL log."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(ALERTS_FILE, "a") as f:
            f.write(json.dumps(alert) + "\n")
    except Exception:
        log.exception("Failed to persist alert %s", alert.get("alert_id"))


# ── Simulation loop ────────────────────────────────────────────────────────────

def _sim_loop():
    tracker = SatelliteTracker()
    rng = np.random.default_rng()
    frame_id = 0
    last_alert_time = 0.0

    log.info("Simulation loop started")

    while True:
        if _orbit_reset.is_set():
            log.info("Orbit reset requested — reinitializing tracker")
            tracker = SatelliteTracker()
            _orbit_reset.clear()
            log.info("Tracker reinitialized: warp=%.0f s", tracker._warp_s)

        try:
            state = tracker.current_state()
            frame = imagery.generate_frame(state.lat, state.lon, rng)
            frame_id += 1

            over_target = imagery._over_target(state.lat, state.lon)
            sim_state = "scanning" if over_target else "idle"

            detection = None
            now = time.time()
            if over_target and (now - last_alert_time) > ALERT_COOLDOWN:
                detection = imagery.detect(frame, state.lat, state.lon, state.alt_km, frame_id)

            with _lock:
                _telemetry.update({
                    **asdict(state),
                    "over_target": over_target,
                    "target_area": {
                        "lat_min": imagery.TARGET_LAT_MIN,
                        "lat_max": imagery.TARGET_LAT_MAX,
                        "lon_min": imagery.TARGET_LON_MIN,
                        "lon_max": imagery.TARGET_LON_MAX,
                    },
                })
                _status["state"] = sim_state
                _status["frame_count"] = frame_id
                _status["last_detection"] = (
                    asdict(detection) if detection else _status.get("last_detection")
                )

                if detection:
                    alert_dict = asdict(detection)
                    _alerts.appendleft(alert_dict)
                    _frames[detection.alert_id] = imagery.frame_to_png(
                        frame, detection.frame_id,
                        detection.lat, detection.lon, detection.timestamp,
                    )
                    # Evict frames that have rolled off the alert deque
                    if len(_frames) > MAX_ALERTS:
                        _frames.pop(next(iter(_frames)))
                    _status["alert_count"] += 1
                    last_alert_time = now
                    log.info(
                        "THREAT DETECTED — confidence=%.3f lat=%.4f lon=%.4f",
                        detection.confidence, detection.lat, detection.lon,
                    )
                    _persist_alert(alert_dict)

        except Exception:
            log.exception("Error in simulation tick")

        time.sleep(TICK_INTERVAL)


# ── Flask API ─────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.get("/telemetry")
def get_telemetry():
    with _lock:
        return jsonify(dict(_telemetry))


@app.get("/status")
def get_status():
    with _lock:
        return jsonify(dict(_status))


@app.get("/alerts")
def get_alerts():
    with _lock:
        return jsonify(list(_alerts))


@app.post("/alerts/<alert_id>/ack")
def ack_alert(alert_id: str):
    with _lock:
        for alert in _alerts:
            if alert["alert_id"] == alert_id:
                alert["routed"] = True
                return jsonify({"acknowledged": alert_id})
    abort(404)


@app.get("/alerts/<alert_id>/frame")
def get_frame(alert_id: str):
    with _lock:
        png = _frames.get(alert_id)
    if not png:
        abort(404)
    return Response(png, mimetype="image/png")


@app.post("/alerts/<alert_id>/classify")
def classify_alert(alert_id: str):
    data = request.get_json(silent=True) or {}
    classification = data.get("classification", "UNKNOWN_EMITTER")
    with _lock:
        for alert in _alerts:
            if alert["alert_id"] == alert_id:
                alert["classification"] = classification
                return jsonify({"classified": alert_id, "classification": classification})
    abort(404)


@app.post("/alerts/clear")
def clear_alerts():
    with _lock:
        _alerts.clear()
        _frames.clear()
        _status["alert_count"] = 0
        _status["last_detection"] = None
    log.info("Alerts cleared by operator")
    return jsonify({"status": "cleared"})


@app.post("/orbit/reset")
def orbit_reset():
    """Queue a SatelliteTracker reinit so the warp is recomputed from now."""
    _orbit_reset.set()
    return jsonify({"status": "reset queued"})


@app.post("/demo/trigger")
def demo_trigger():
    """Force a detection event at the satellite's current position.
    Useful during demos when the orbital track hasn't reached the AOI yet.
    """
    import uuid
    from datetime import datetime, timezone
    with _lock:
        current = dict(_telemetry)
    if not current:
        abort(503)
    alert = {
        "alert_id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.91,
        "lat": current.get("lat", 0.0),
        "lon": current.get("lon", 0.0),
        "alt_km": current.get("alt_km", 0.0),
        "frame_id": -1,
        "classification": "UNKNOWN_EMITTER",
        "routed": False,
        "demo_triggered": True,
    }
    # Generate a synthetic frame with the emitter injected regardless of position
    rng = np.random.default_rng()
    frame = imagery.generate_frame(alert["lat"], alert["lon"], rng, force_emitter=True)
    png = imagery.frame_to_png(frame, -1, alert["lat"], alert["lon"], alert["timestamp"])
    with _lock:
        _alerts.appendleft(alert)
        _frames[alert["alert_id"]] = png
        _status["alert_count"] += 1
        _status["last_detection"] = alert
    log.info("DEMO TRIGGER — synthetic detection at lat=%.4f lon=%.4f", alert["lat"], alert["lon"])
    return jsonify(alert), 201


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_offline_queue()

    sim_thread = threading.Thread(target=_sim_loop, daemon=True, name="sim-loop")
    sim_thread.start()

    # Give the first tick a moment to populate state before serving
    time.sleep(TICK_INTERVAL + 0.5)

    log.info("Starting API server on 0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, threaded=True)
