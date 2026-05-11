# VM Rebuild Commands

Run these in order. Steps 2–3 require a root terminal.

---

## Step 1 — Save image (normal user terminal)

```
rm -f /tmp/satellite-sim.tar && podman save satellite-sim:latest -o /tmp/satellite-sim.tar
```

---

## Step 2 — Load image into root storage + build qcow2 (root terminal)

```
podman load -i /tmp/satellite-sim.tar && podman run --rm --privileged -v /home/swarren/satellite-demo/output:/output -v /var/lib/containers/storage:/var/lib/containers/storage ghcr.io/osbuild/bootc-image-builder:latest --type qcow2 localhost/satellite-sim:latest
```

---

## Step 3 — Deploy VM (root terminal, after qcow2 finishes)

```
virsh --connect qemu:///system destroy satellite-sim 2>/dev/null; virsh --connect qemu:///system undefine satellite-sim 2>/dev/null; cp /home/swarren/satellite-demo/output/qcow2/disk.qcow2 /var/lib/libvirt/images/satellite-sim.qcow2 && virt-install --connect qemu:///system --name satellite-sim --memory 2048 --vcpus 2 --disk /var/lib/libvirt/images/satellite-sim.qcow2,format=qcow2,bus=virtio --import --os-variant centos-stream10 --network network=default,model=virtio --graphics none --console pty,target_type=serial --noautoconsole --cloud-init user-data=/home/swarren/satellite-demo/cloud-init/user-data
```

> Note: undefine without `--remove-all-storage` so the disk file stays; cp overwrites it with the new image before virt-install runs.

---

## Step 4 — Drop skupper token (cloud-init not installed — must do this every rebuild)

Get the VM IP, then push the token from the host:

```
sshpass -p satellite scp -o StrictHostKeyChecking=no /tmp/token.yaml demo@$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1):/tmp/token.yaml
```

Then install it and start skupper on the VM:

```
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1) "sudo cp /tmp/token.yaml /etc/skupper/token.yaml && sudo chmod 600 /etc/skupper/token.yaml && sudo systemctl start skupper-init.service && sudo journalctl -u skupper-init.service --no-pager -n 20"
```

> `/tmp/token.yaml` on the host is kept up to date. When the AccessGrant expires or is exhausted, regenerate it on OCP and update `/tmp/token.yaml` and `cloud-init/user-data`.

### Regenerate AccessGrant (when needed)

```
oc delete accessgrant satellite-vm-token -n satellite-ground 2>/dev/null; oc apply -n satellite-ground -f - <<EOF
apiVersion: skupper.io/v2alpha1
kind: AccessGrant
metadata:
  name: satellite-vm-token
spec:
  redemptionsAllowed: 3
  expirationWindow: 168h
EOF
```

Then fetch the new url/code and update `/tmp/token.yaml` and `cloud-init/user-data` manually.

---

## Step 5 — Verify skupper router is running (SSH into VM)

```
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1) "sudo systemctl status skupper-satellite-vm.service --no-pager"
```

---

## Step 6 — Smoke test from OCP (satellite-ground namespace)

```
oc run curl-test --rm -it --image=curlimages/curl -n satellite-ground -- curl -s http://satellite-alerts:8080/healthz
```

---

## Phase 3 — Ground station web app

**Deployed:** 2026-05-07
**URL:** `https://ground-station-satellite-ground.apps.cluster-h4pqc.h4pqc.sandbox2789.opentlc.com`

> Note: This cluster has no external route on the image registry. Use `oc start-build` (in-cluster build) instead of local podman push.

### First deploy (one-time per cluster)

```sh
cd ~/satellite-demo/ground-station

# Create the BuildConfig + ImageStream (once)
oc new-build --name=ground-station --binary --strategy=docker -n satellite-ground
oc patch bc/ground-station -n satellite-ground \
  --patch '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"Containerfile"}}}}' \
  --type=merge

# Build image in-cluster and push to internal registry
oc start-build ground-station --from-dir=. --follow -n satellite-ground

# Deploy
oc apply -f k8s/ -n satellite-ground
```

### Get the route URL

```sh
oc get route ground-station -n satellite-ground --template='https://{{ .spec.host }}'
```

### Re-deploy after code changes

```sh
cd ~/satellite-demo/ground-station
oc start-build ground-station --from-dir=. --follow -n satellite-ground
oc rollout restart deployment/ground-station -n satellite-ground
oc rollout status deployment/ground-station -n satellite-ground
```
