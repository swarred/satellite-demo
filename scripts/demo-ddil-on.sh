#!/usr/bin/env bash
# demo-ddil-on.sh — Simulate DDIL by blocking OCP cluster connectivity from the satellite VM.
#
# Resolves the OCP ingress IP from the ground station route, then SSHes into
# the satellite VM and adds an iptables rule dropping OUTPUT traffic to that IP.
# The satellite VM retains SSH/KVM bridge access (192.168.122.0/24 is not blocked).
#
# The EDA rulebook on the VM detects the connectivity loss within ~60s and
# automatically triggers: bootc switch → offline image → reboot (~90s total).
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
echo "Simulating DDIL — blocking OCP ingress from satellite VM..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo iptables -I OUTPUT -d $GS_IP -j DROP"

echo ""
echo "DDIL active. OCP traffic blocked on satellite VM."
echo ""
echo "EDA rulebook will detect connectivity loss within ~60s."
echo "VM will automatically reboot into offline autonomous mode (~90s total)."
echo ""
echo "Watch satellite journal:  ssh demo@$VM_IP 'sudo journalctl -fu satellite-eda'"
echo "Watch local analysis:     ssh demo@$VM_IP 'sudo journalctl -fu satellite-local-analysis'"
echo ""
echo "When ready to restore: ./scripts/demo-ddil-off.sh"
