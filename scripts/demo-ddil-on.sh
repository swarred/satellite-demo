#!/usr/bin/env bash
# demo-ddil-on.sh — Simulate DDIL: break the ground station link and trigger
# autonomous bootc switch to offline mode.
#
# Two actions on the satellite VM:
#   1. Stop skupper — ground station immediately shows LINK DOWN
#   2. Poison /etc/hosts → 127.0.0.1 — EDA url_check gets instant ECONNREFUSED
#      (not a silent TCP timeout) and fires the DDIL rule within ~20s
#
# SSH over the KVM bridge (192.168.122.x) remains available throughout.
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
echo "Simulating DDIL..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" bash -s <<ENDSSH
# 1. Break the Skupper link — ground station shows LINK DOWN immediately
sudo systemctl stop skupper-satellite-vm.service 2>/dev/null || true

# 2. Poison the ground station hostname so url_check fails fast (ECONNREFUSED,
#    not a silent timeout to a black-hole IP)
sudo sed -i '/$GS_HOST/d' /etc/hosts
echo '127.0.0.1 $GS_HOST' | sudo tee -a /etc/hosts
ENDSSH

echo ""
echo "DDIL active:"
echo "  - Skupper stopped       → ground station shows LINK DOWN now"
echo "  - Hostname poisoned     → EDA url_check will fail within ~20s"
echo "  - EDA rule fires        → bootc switch to offline image + reboot (~90s)"
echo ""
echo "Watch EDA:             sshpass -p satellite ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
echo "Watch local analysis:  sshpass -p satellite ssh demo@$VM_IP 'sudo journalctl -fu satellite-local-analysis'"
echo ""
echo "When ready to restore: ./scripts/demo-ddil-off.sh"
