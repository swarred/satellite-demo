# Satellite Demo — Runbook

Step-by-step guide for standing up the full demo from scratch.

**Assumed prerequisites:**
- OCP cluster running with RHSI (skupper operator) installed cluster-wide
- `oc` CLI logged in to the cluster
- KVM/libvirt on the local machine (`virsh`, `virt-install`)
- Active RHEL subscription on the build host (for `registry.redhat.io` base image)
- `podman`, `sshpass` installed on the build host

---

## Part 1 — OCP side setup

Run once per cluster. Skip if `satellite-ground` namespace already exists with a running skupper site.

### 1.1 Create the namespace and skupper site

```
oc new-project satellite-ground
```

```
oc apply -n satellite-ground -f - <<EOF
apiVersion: skupper.io/v2alpha1
kind: Site
metadata:
  name: ground-station
spec:
  linkAccess: default
EOF
```

Wait for the site to be ready:

```
oc wait --for=condition=Ready site/ground-station -n satellite-ground --timeout=120s
```

### 1.2 Create the Listener

This creates the virtual service that OCP pods will use to reach the satellite VM:

```
oc apply -n satellite-ground -f - <<EOF
apiVersion: skupper.io/v2alpha1
kind: Listener
metadata:
  name: satellite-alerts
spec:
  routingKey: satellite-alerts
  port: 8080
  host: satellite-alerts
EOF
```

### 1.3 Create the AccessGrant

```
oc apply -n satellite-ground -f - <<EOF
apiVersion: skupper.io/v2alpha1
kind: AccessGrant
metadata:
  name: satellite-vm-token
spec:
  redemptionsAllowed: 20
  expirationWindow: 168h
EOF
```

Wait for it to be ready, then extract the token fields:

```
oc wait --for=condition=Ready accessgrant/satellite-vm-token -n satellite-ground --timeout=30s
```

```
oc get accessgrant satellite-vm-token -n satellite-ground -o json | python3 -c "
import json, sys
s = json.load(sys.stdin)['status']
print('url:', s['url'])
print('code:', s['code'])
print('ca:', s['ca'][:60], '...')
"
```

### 1.4 Update the token in cloud-init/user-data

Edit `cloud-init/user-data` and replace the three fields under `spec:`:

```yaml
spec:
  url: <url from above>
  code: <code from above>
  ca: |
    <full CA cert from above>
```

Also write the token to `/tmp/token.yaml` on the host (used as a fallback if cloud-init fails):

```
oc get accessgrant satellite-vm-token -n satellite-ground -o json | python3 -c "
import json, sys
s = json.load(sys.stdin)['status']
ca = '\n'.join('    ' + l for l in s['ca'].strip().splitlines())
print(f'''apiVersion: skupper.io/v2alpha1
kind: AccessToken
metadata:
  name: ground-station-link
spec:
  url: {s[\"url\"]}
  code: {s[\"code\"]}
  ca: |
{ca}''')
" > /tmp/token.yaml
```

---

## Part 2 — Build the VM image

### 2.1 Build the container image (normal user terminal)

```
cd ~/satellite-demo
podman build \
  -v /etc/pki/entitlement:/etc/pki/entitlement:ro \
  -v /etc/pki/consumer:/etc/pki/consumer:ro \
  -v /etc/rhsm:/etc/rhsm:ro \
  -t satellite-sim:latest .
```

If subscription errors occur, re-register first:

```
sudo subscription-manager clean && sudo subscription-manager register && sudo subscription-manager attach --auto
```

### 2.2 Save the image for root (normal user terminal)

```
rm -f /tmp/satellite-sim.tar && podman save satellite-sim:latest -o /tmp/satellite-sim.tar
```

### 2.3 Load and build the qcow2 disk image (root terminal)

```
podman load -i /tmp/satellite-sim.tar && podman run --rm --privileged -v /home/swarren/satellite-demo/output:/output -v /var/lib/containers/storage:/var/lib/containers/storage ghcr.io/osbuild/bootc-image-builder:latest --type qcow2 localhost/satellite-sim:latest
```

This takes ~10 minutes on first run. Subsequent runs reuse cached layers and are faster.

---

## Part 3 — Deploy the VM

### 3.1 Deploy (root terminal, after qcow2 finishes)

```
virsh --connect qemu:///system destroy satellite-sim 2>/dev/null; virsh --connect qemu:///system undefine satellite-sim 2>/dev/null; cp /home/swarren/satellite-demo/output/qcow2/disk.qcow2 /var/lib/libvirt/images/satellite-sim.qcow2 && virt-install --connect qemu:///system --name satellite-sim --memory 2048 --vcpus 2 --disk /var/lib/libvirt/images/satellite-sim.qcow2,format=qcow2,bus=virtio --import --os-variant centos-stream10 --network network=default,model=virtio --graphics none --console pty,target_type=serial --noautoconsole --cloud-init user-data=/home/swarren/satellite-demo/cloud-init/user-data
```

### 3.2 Wait for boot (~30–60 seconds), then get the IP

```
virsh --connect qemu:///system domifaddr satellite-sim
```

### 3.3 SSH in

```
ssh demo@<ip>
# password: satellite
```

---

## Part 4 — Verify

### 4.1 Check all services on the VM

```
sudo systemctl status satellite-sim.service skupper-init.service skupper-satellite-vm.service --no-pager
```

Expected: `satellite-sim` active (running), `skupper-init` active (exited/oneshot), `skupper-satellite-vm` active (running).

### 4.2 Check OCP side

```
oc get site,listener -n satellite-ground
```

Expected: site shows **2 sites in network**, listener shows **Ready** with **HAS MATCHING CONNECTOR: true**.

### 4.3 Smoke test through the tunnel

```
oc run curl-test --rm -it --image=curlimages/curl -n satellite-ground --restart=Never -- curl -s http://satellite-alerts:8080/healthz
```

Expected: `{"status":"ok"}`

### 4.4 Trigger a detection (demo moment)

```
oc run curl-test --rm -it --image=curlimages/curl -n satellite-ground --restart=Never -- curl -s -X POST http://satellite-alerts:8080/demo/trigger
```

---

## Part 5 — Redeploying with a new token

The AccessGrant is consumed once per VM deploy. When redemptions run out:

```
oc delete accessgrant satellite-vm-token -n satellite-ground 2>/dev/null
oc apply -n satellite-ground -f - <<EOF
apiVersion: skupper.io/v2alpha1
kind: AccessGrant
metadata:
  name: satellite-vm-token
spec:
  redemptionsAllowed: 20
  expirationWindow: 168h
EOF
```

Then re-extract the token (Step 1.4) and redeploy the VM (Part 3 only — no image rebuild needed).

---

## Quick reference

| Item | Value |
|------|-------|
| VM credentials | `demo` / `satellite` |
| Satellite API port | 8080 |
| OCP namespace | `satellite-ground` |
| skupper routing key | `satellite-alerts` |
| Listener hostname (on OCP) | `satellite-alerts` |
| Cloud-init token file | `cloud-init/user-data` |
| Host token file | `/tmp/token.yaml` |
| Rebuild commands | `REBUILD-COMMANDS.md` |
