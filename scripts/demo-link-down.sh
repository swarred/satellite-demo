#!/usr/bin/env bash
# demo-link-down.sh — cut the RHSI link between the satellite VM and OCP
# Stops skrouterd on the VM. SSH stays alive (KVM bridge, independent of skupper).
# No Restart= in the unit — link stays down until demo-link-up.sh is run.

set -euo pipefail

VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim \
  | awk '/ipv4/ {print $4}' | cut -d/ -f1)

if [ -z "$VM_IP" ]; then
  echo "ERROR: satellite-sim VM not found or not running" >&2
  exit 1
fi

echo "Satellite VM: $VM_IP"
echo "Cutting RHSI link..."

sshpass -p satellite ssh \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  demo@"$VM_IP" \
  "sudo systemctl stop skupper-satellite-vm.service"

echo ""
echo "LINK DOWN. Ground station will show SIGNAL LOST within 5 seconds."
echo ""
echo "To show the satellite still operating during the blackout, run:"
echo "  ./scripts/demo-watch-vm.sh"
echo ""
echo "To restore the link, run:"
echo "  ./scripts/demo-link-up.sh"
