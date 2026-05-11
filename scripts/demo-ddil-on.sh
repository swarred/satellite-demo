#!/usr/bin/env bash
# demo-ddil-on.sh — Simulate DDIL by making the OCP ground station unreachable
# from the satellite VM.
#
# Adds the ground station hostname to /etc/hosts on the VM pointing to a
# black-hole address (192.0.2.1 — TEST-NET, RFC 5737, guaranteed unreachable).
# This blocks all resolved IPs regardless of CDN load-balancing or IP rotation.
# SSH/KVM bridge access (192.168.122.0/24) is unaffected.
#
# The EDA DDIL rulebook on the VM detects the connectivity loss within ~60s
# and automatically stages the offline image then reboots (~90s total).
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
echo "Simulating DDIL — poisoning ground station hostname on satellite VM..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo sed -i '/$GS_HOST/d' /etc/hosts && \
   echo '192.0.2.1 $GS_HOST' | sudo tee -a /etc/hosts"

echo ""
echo "DDIL active. Ground station hostname blocked on satellite VM."
echo ""
echo "EDA rulebook will detect connectivity loss within ~60s."
echo "VM will automatically reboot into offline autonomous mode (~90s total)."
echo ""
echo "Watch EDA:             ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
echo "Watch local analysis:  ssh demo@$VM_IP 'sudo journalctl -fu satellite-local-analysis'"
echo ""
echo "When ready to restore: ./scripts/demo-ddil-off.sh"
