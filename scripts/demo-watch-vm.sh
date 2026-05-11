#!/usr/bin/env bash
# demo-watch-vm.sh — live view of alerts accumulating on the satellite VM.
# Run this in a second terminal while the link is down to show the satellite
# is still operating autonomously while the ground station is dark.

set -euo pipefail

VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim \
  | awk '/ipv4/ {print $4}' | cut -d/ -f1)

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM not found or not running" >&2
  exit 1
fi

echo "Connecting to satellite VM ($VM_IP) — Ctrl+C to exit"
echo ""

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" 'bash -s' << 'ENDSSH'
cat > /tmp/fmt_alerts.py << 'ENDPY'
import json, sys, datetime
alerts = json.load(sys.stdin)
now = datetime.datetime.utcnow().strftime("%H:%M:%SZ")
print(f"SATELLITE PAYLOAD COMPUTER  [{now}]  {len(alerts)} alert(s) on-board\n")
for a in alerts[:10]:
    status = "ROUTED " if a.get("routed") else "PENDING"
    demo   = " [DEMO]" if a.get("demo_triggered") else ""
    print(f"  [{status}] {a['alert_id']}  conf={a['confidence']:.0%}"
          f"  {a['lat']:+.3f} {a['lon']:+.3f}  {a['timestamp'][11:19]}Z{demo}")
ENDPY
while true; do
  printf '\033[2J\033[H'
  curl -s localhost:8080/alerts | python3 /tmp/fmt_alerts.py
  sleep 2
done
ENDSSH
