#!/usr/bin/env bash
# demo-watch-offline.sh — Live view of satellite autonomous offline operations.
#
# Run in a second terminal after demo-ddil.yml completes. Streams real-time
# alert classifications from phi4-mini directly from the satellite VM journal.
# Press Ctrl+C when ready to run demo-restore.yml.
set -euo pipefail

VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim \
  | awk '/ipv4/ {print $4}' | cut -d/ -f1)

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM not found or not running" >&2
  exit 1
fi

# Current offline queue depth
QUEUED=$(sshpass -p satellite ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "wc -l < /var/lib/satellite-sim/offline-queue.jsonl 2>/dev/null || echo 0" 2>/dev/null | tr -d '[:space:]')

echo ""
echo "  ╔═══════════════════════════════════════════════════════╗"
echo "  ║   SATELLITE SIM — AUTONOMOUS OFFLINE OPERATIONS       ║"
echo "  ║   Ground station uplink: SEVERED                      ║"
echo "  ║   Operating mode:        DDIL AUTONOMOUS              ║"
echo "  ║   Classification engine: phi4-mini (local LLM)        ║"
printf "  ║   Alerts queued so far:  %-30s║\n" "$QUEUED"
echo "  ║                                                       ║"
echo "  ║   Streaming live classifications — Ctrl+C to stop     ║"
echo "  ╚═══════════════════════════════════════════════════════╝"
echo ""

# Stream the classification journal in real-time.
# grep filters to only the lines worth showing the audience:
#   "Classifying alert..." — alert being picked up
#   "Classified X → TYPE" — classification result
sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  -t demo@"$VM_IP" \
  "sudo journalctl -fu satellite-local-analysis --no-hostname \
   | grep --line-buffered -E 'Classifying|Classified|ERROR'" 2>/dev/null
