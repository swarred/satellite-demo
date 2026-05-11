#!/usr/bin/env bash
# demo-ddil-off.sh — Restore OCP connectivity to the satellite VM.
#
# Removes the iptables rule added by demo-ddil-on.sh. The satellite VM may
# have rebooted into the offline image since then — virsh domifaddr re-queries
# the current IP. The EDA reconnect rulebook detects the restored link within
# ~60s and switches back to the online image + reboots (~90s total).
#
# Once back online, satellite-sim loads the offline-classified alert queue
# and the ground station displays them with the offline analysis results.
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

GS_IP=$(dig +short "$GS_HOST" | grep -E '^[0-9]+\.' | head -1)
if [ -z "$GS_IP" ]; then
  echo "ERROR: could not resolve IP for $GS_HOST" >&2
  exit 1
fi

echo "Satellite VM:    $VM_IP"
echo "Ground station:  $GS_HOST ($GS_IP)"
echo ""
echo "Restoring OCP connectivity..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo iptables -D OUTPUT -d $GS_IP -j DROP 2>/dev/null || true"

echo ""
echo "Connectivity restored."
echo ""
echo "EDA rulebook will detect the restored link within ~60s."
echo "VM will automatically reboot into online mode (~90s total)."
echo "Offline-classified alerts will appear in the ground station UI after reboot."
echo ""
echo "Watch reconnect: ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
