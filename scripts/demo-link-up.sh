#!/usr/bin/env bash
# demo-link-up.sh — restore the RHSI link between the satellite VM and OCP
# Starts skrouterd. The baked-in connector config reconnects automatically.

set -euo pipefail

VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim \
  | awk '/ipv4/ {print $4}' | cut -d/ -f1)

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM not found or not running" >&2
  exit 1
fi

echo "Satellite VM: $VM_IP"
echo "Restoring RHSI link..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo systemctl start skupper-satellite-vm.service"

echo ""
echo "skupper router started. Polling ground station for link recovery..."

GS_HOST=$(oc get route ground-station -n satellite-ground -o jsonpath='{.spec.host}' 2>/dev/null)
if [ -z "$GS_HOST" ]; then
  echo "Warning: could not resolve ground-station route — skipping link poll."
  exit 0
fi
GS_URL="https://${GS_HOST}"

for i in $(seq 1 20); do
  sleep 2
  STATUS=$(curl -sk --max-time 3 "$GS_URL/partials/linkstatus" 2>/dev/null | grep -c "link-online" || true)
  if [ "${STATUS:-0}" -ge 1 ]; then
    echo "LINK UP — ground station shows RHSI LINK ACTIVE."
    echo "Queued alerts will appear in the ground station UI within 5 seconds."
    exit 0
  fi
  echo "  ...waiting ($((i * 2))s)"
done

echo "Warning: link not confirmed after 40s — check the ground station UI directly."
