#!/usr/bin/env bash
# demo-watch-offline.sh — Live view of satellite autonomous offline operations.
#
# Run in a second terminal after demo-ddil.yml completes. Streams real-time
# alert classifications from phi4-mini directly from the satellite VM journal.
# Press Ctrl+C when ready to run demo-restore.yml.
set -euo pipefail

echo "  Waiting for satellite VM to come up (playbook handles virsh start)..."
VM_IP=""
for i in $(seq 1 24); do
  VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim 2>/dev/null \
    | awk '/ipv4/ {print $4}' | cut -d/ -f1)
  [ -n "$VM_IP" ] && break
  sleep 5
done

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM did not come up after 2 minutes" >&2
  exit 1
fi

# Wait for SSH
for i in $(seq 1 12); do
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=3 -o LogLevel=ERROR \
      demo@"$VM_IP" true 2>/dev/null && break
  sleep 5
done

# Current offline queue depth
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5"
QUEUED=$(sshpass -p satellite ssh $SSH_OPTS demo@"$VM_IP" \
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
ssh-keygen -R "$VM_IP" 2>/dev/null || true
sshpass -p satellite ssh $SSH_OPTS -t demo@"$VM_IP" \
  "sudo journalctl -fu satellite-local-analysis --no-hostname \
   | grep --line-buffered -E 'Classifying|Classified|ERROR'" 2>/dev/null
