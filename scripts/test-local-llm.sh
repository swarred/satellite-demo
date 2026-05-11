#!/usr/bin/env bash
# test-local-llm.sh — Validate that phi4-mini produces usable classification output
# Run this on the build host before building the offline satellite image.
# Installs Ollama if not present, pulls phi4-mini, sends 3 test prompts.
set -euo pipefail

MODEL="phi4-mini:latest"

# ── Install Ollama if needed ──────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo "Ollama not found — installing..."
  curl -fsSL https://ollama.com/install.sh | sh
  echo "Ollama installed."
fi

# ── Start Ollama if not running ───────────────────────────────────────────────
if ! ollama list &>/dev/null; then
  echo "Starting Ollama server..."
  ollama serve &>/tmp/ollama-test.log &
  OLLAMA_PID=$!
  sleep 5
  trap "kill $OLLAMA_PID 2>/dev/null || true" EXIT
fi

# ── Pull model if needed ──────────────────────────────────────────────────────
if ! ollama list 2>/dev/null | grep -q "phi4-mini"; then
  echo "Pulling $MODEL (this downloads ~2.5 GB — first run only)..."
  ollama pull "$MODEL"
fi

# ── Classification function ───────────────────────────────────────────────────
classify() {
  local label="$1"
  local confidence="$2"
  local lat="$3"
  local lon="$4"
  local alt_km="$5"
  local timestamp="$6"

  local prompt
  prompt="You are an autonomous satellite threat assessment system operating without ground station connectivity.
Analyze this sensor detection and return ONLY a valid JSON object — no explanation, no markdown, no extra text.

Detection:
- Sensor confidence: ${confidence}
- Location: ${lat}°N, ${lon}°E
- Altitude: ${alt_km} km
- Timestamp: ${timestamp}

Valid classifications: DIRECTED_ENERGY, RF_EMITTER, THERMAL_PLUME, THERMAL_ANOMALY, ORBITAL_DEBRIS, UNKNOWN_EMITTER

Required JSON format:
{\"classification\": \"<one of the valid classifications>\", \"confidence\": <0.0-1.0>, \"summary\": \"<one sentence>\"}
"

  ollama run "$MODEL" "$prompt" 2>/dev/null
}

# ── Test cases ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  phi4-mini classification validation — 3 test detections"
echo "═══════════════════════════════════════════════════════════"
echo ""

echo "── Test 1: High-confidence detection over Persian Gulf ──"
classify "UNKNOWN_EMITTER" "0.94" "26.3142" "56.8821" "412.3" "2026-05-11T14:22:07Z"
echo ""

echo "── Test 2: Medium-confidence detection over Arabian Sea ──"
classify "UNKNOWN_EMITTER" "0.78" "19.5500" "63.2100" "418.7" "2026-05-11T14:35:44Z"
echo ""

echo "── Test 3: Lower-confidence detection ──"
classify "UNKNOWN_EMITTER" "0.73" "28.9100" "49.3300" "409.1" "2026-05-11T14:51:19Z"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  Validation complete — confirm output is valid JSON"
echo "  with classification from the approved list before"
echo "  building the offline satellite image."
echo "═══════════════════════════════════════════════════════════"
