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

# ── Classification function (mirrors local_analysis.py exactly) ──────────────
classify() {
  local confidence="$1"
  local lat="$2"
  local lon="$3"
  local alt_km="$4"
  local timestamp="$5"

  local prompt
  prompt="Classify a satellite sensor detection. Respond with ONLY a JSON object, no other text.

The \"classification\" value MUST be copied VERBATIM from this list — no other values are valid:
1. DIRECTED_ENERGY
2. RF_EMITTER
3. THERMAL_PLUME
4. THERMAL_ANOMALY
5. ORBITAL_DEBRIS
6. UNKNOWN_EMITTER

Example of correct output:
{\"classification\": \"RF_EMITTER\", \"confidence\": 0.85, \"summary\": \"Strong radio frequency signature consistent with active radar.\"}

Detection to classify:
- Sensor confidence: ${confidence}
- Location: ${lat}°N, ${lon}°E
- Altitude: ${alt_km} km
- Timestamp: ${timestamp}"

  curl -sf "$OLLAMA_URL" \
    -H 'Content-Type: application/json' \
    -d "{
      \"model\": \"$MODEL\",
      \"prompt\": $(echo "$prompt" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
      \"stream\": false,
      \"format\": \"json\"
    }" | python3 -c '
import json, sys
data = json.load(sys.stdin)
try:
    result = json.loads(data["response"])
    print(json.dumps(result, indent=2))
    valid = {"DIRECTED_ENERGY","RF_EMITTER","THERMAL_PLUME","THERMAL_ANOMALY","ORBITAL_DEBRIS","UNKNOWN_EMITTER"}
    c = result.get("classification","")
    if c not in valid:
        print(f"  ⚠ WARNING: \"{c}\" is not a valid classification", file=sys.stderr)
    else:
        print(f"  ✓ classification valid: {c}", file=sys.stderr)
except Exception as e:
    print(f"  ✗ Failed to parse response: {e}", file=sys.stderr)
    print(f"  Raw: {data.get(\"response\",\"\")}", file=sys.stderr)
'
}

# ── Test cases ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  phi4-mini classification validation — 3 test detections"
echo "  (uses Ollama API with format=json, same as the service)"
echo "═══════════════════════════════════════════════════════════"
echo ""

echo "── Test 1: High-confidence detection over Persian Gulf ──"
classify "0.94" "26.3142" "56.8821" "412.3" "2026-05-11T14:22:07Z"
echo ""

echo "── Test 2: Medium-confidence detection over Arabian Sea ──"
classify "0.78" "19.5500" "63.2100" "418.7" "2026-05-11T14:35:44Z"
echo ""

echo "── Test 3: Lower-confidence detection ──"
classify "0.73" "28.9100" "49.3300" "409.1" "2026-05-11T14:51:19Z"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  All 3 should show ✓ classification valid."
echo "  If any show ⚠, the prompt needs further tuning before"
echo "  building the offline satellite image."
echo "═══════════════════════════════════════════════════════════"
