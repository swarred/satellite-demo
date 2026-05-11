#!/usr/bin/env bash
# demo-ddil-off.sh — Restore OCP ground station connectivity on the satellite VM.
#
# Removes the /etc/hosts poison entry added by demo-ddil-on.sh.
# The VM may have rebooted into the offline image since then — virsh domifaddr
# re-queries the current IP. SSH still works via the KVM bridge.
#
# The EDA reconnect rulebook detects the restored link within ~60s and
# switches back to the online image + reboots (~90s total). On restart,
# satellite-sim loads the offline-classified alert queue and flushes it to
# the ground station.
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
echo "Restoring OCP connectivity — removing /etc/hosts block..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo sed -i '/$GS_HOST/d' /etc/hosts"

echo ""
echo "Connectivity restored."
echo ""
echo "EDA rulebook will detect the restored link within ~60s."
echo "VM will automatically reboot into online mode (~90s total)."
echo "Offline-classified alerts will appear in the ground station UI after reboot."
echo ""
echo "Watch reconnect: ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
