#!/usr/bin/env bash
# test-local-llm.sh — Validate that phi4-mini produces usable classification output
# Uses the Ollama HTTP API directly (same path as local_analysis.py) with
# format=json enforced, so output matches exactly what the service will produce.
set -euo pipefail

MODEL="phi4-mini:latest"
OLLAMA_URL="http://localhost:11434/api/generate"

# ── Install Ollama if needed ──────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo "Ollama not found — installing..."
  curl -fsSL https://ollama.com/install.sh | sh
  echo "Ollama installed."
fi

# ── Start Ollama if not running ───────────────────────────────────────────────
if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
  echo "Starting Ollama server..."
  ollama serve &>/tmp/ollama-test.log &
  sleep 8
fi

# ── Pull model if needed ──────────────────────────────────────────────────────
if ! ollama list 2>/dev/null | grep -q "phi4-mini"; then
  echo "Pulling $MODEL (this downloads ~2.5 GB — first run only)..."
  ollama pull "$MODEL"
fi

# ── Classification function ───────────────────────────────────────────────────
# Uses a Python heredoc to avoid all bash/Python quoting conflicts.
classify() {
  local confidence="$1" lat="$2" lon="$3" alt_km="$4" timestamp="$5"

  python3 - "$MODEL" "$OLLAMA_URL" "$confidence" "$lat" "$lon" "$alt_km" "$timestamp" <<'PYEOF'
import json, sys, urllib.request, urllib.error

model, url, confidence, lat, lon, alt_km, timestamp = sys.argv[1:]

prompt = (
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
    "You MUST return all three fields: classification, confidence, and summary.\n"
    "Respond with ONLY a JSON object. Example:\n"
    '{"classification": "RF_EMITTER", "confidence": 0.85, "summary": "Strong coherent RF signature at low altitude consistent with surface-based radar system."}\n\n'
    "Detection:\n"
    f"- Sensor confidence: {confidence}\n"
    f"- Location: {lat}N, {lon}E\n"
    f"- Altitude: {alt_km} km\n"
    f"- Timestamp: {timestamp}"
)

payload = json.dumps({
    "model": model,
    "prompt": prompt,
    "stream": False,
    "format": "json",
}).encode()

try:
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
except urllib.error.URLError as e:
    print(f"  ERROR: could not reach Ollama at {url}: {e}", file=sys.stderr)
    sys.exit(1)

try:
    result = json.loads(data["response"])
except (json.JSONDecodeError, KeyError) as e:
    print(f"  ERROR: could not parse model response: {e}", file=sys.stderr)
    print(f"  Raw: {data.get('response', '')}", file=sys.stderr)
    sys.exit(1)

print(json.dumps(result, indent=2))

valid = {
    "DIRECTED_ENERGY", "RF_EMITTER", "THERMAL_PLUME",
    "THERMAL_ANOMALY", "ORBITAL_DEBRIS", "UNKNOWN_EMITTER",
}
c = result.get("classification", "")
if c in valid:
    print(f"  [OK] classification: {c}", file=sys.stderr)
else:
    print(f"  [FAIL] invalid classification: {repr(c)}", file=sys.stderr)
    sys.exit(1)
PYEOF
}

# ── Test cases ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  phi4-mini classification validation — 3 test detections"
echo "  (uses Ollama API with format=json, same as the service)"
echo "═══════════════════════════════════════════════════════════"
echo ""

PASS=0; FAIL=0

run_test() {
  local label="$1"; shift
  echo "── $label ──"
  if classify "$@"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
  fi
  echo ""
}

run_test "Test 1: High-confidence, Persian Gulf"   "0.94" "26.3142" "56.8821" "412.3" "2026-05-11T14:22:07Z"
run_test "Test 2: Medium-confidence, Arabian Sea"  "0.78" "19.5500" "63.2100" "418.7" "2026-05-11T14:35:44Z"
run_test "Test 3: Lower-confidence detection"      "0.73" "28.9100" "49.3300" "409.1" "2026-05-11T14:51:19Z"

echo "═══════════════════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
  echo "  Model is ready — safe to build the offline image."
else
  echo "  Fix prompt issues before building the offline image."
fi
echo "═══════════════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ]
