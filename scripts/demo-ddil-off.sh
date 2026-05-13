#!/usr/bin/env bash
# demo-ddil-off.sh — Restore OCP connectivity on the satellite VM.
#
# Removes the /etc/hosts poison entry so the EDA reconnect rulebook detects
# the restored link within ~20s and switches back to the online image + reboots.
#
# Skupper does NOT need to be restarted manually — skupper-init.service runs
# automatically when the VM reboots into the online image and reconnects.
# The ground station will show LINK UP once Skupper re-establishes (~60-90s).
#
# Offline-classified alerts are loaded by satellite-sim on startup and appear
# in the ground station UI automatically.
set -euo pipefail

VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim \
  | awk '/ipv4/ {print $4}' | cut -d/ -f1)

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM not found or not running" >&2
  exit 1
fi

GS_HOST=$(oc get route ground-station -n satellite-ground \
  -o jsonpath='{.spec.host}' 2>/dev/null)
if [ -z "$GS_HOST" ]; then
  echo "ERROR: could not resolve ground-station route — is OCP logged in?" >&2
  exit 1
fi

echo "Satellite VM:    $VM_IP"
echo "Ground station:  $GS_HOST"
echo ""
echo "Restoring connectivity — removing /etc/hosts block..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo sed -i '/$GS_HOST/d' /etc/hosts"

echo ""
echo "Connectivity restored:"
echo "  - EDA reconnect rulebook will detect within ~20s"
echo "  - VM will reboot into online image (~90s)"
echo "  - Skupper reconnects automatically on boot"
echo "  - Ground station shows LINK UP once Skupper is established"
echo "  - Offline-classified alerts appear in the ground station UI"
echo ""
echo "Watch reconnect: sshpass -p satellite ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
