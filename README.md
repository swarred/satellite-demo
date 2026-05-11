# Satellite Demo

A Red Hat Image Mode (bootc) demonstration built around a simulated satellite system.

A satellite VM runs an immutable, image-based RHEL OS (bootc). It collects synthetic sensor detections and connects to an OpenShift ground station over an encrypted tunnel via Red Hat Service Interconnect (RHSI/Skupper). The ground station UI displays live telemetry and alerts, supports AI-assisted threat classification, and lets you break and restore the uplink to demonstrate DDIL resilience.

## What it demonstrates

- **RHEL Image Mode (bootc)** — immutable OS for edge/space infrastructure; updates and rollbacks without reprovisioning
- **DDIL resilience** — satellite continues operating and queuing alerts when the uplink is down; data syncs on reconnect
- **Red Hat Service Interconnect** — encrypted, pull-based tunnel between the VM and OCP; works through NAT and firewalls without inbound ports
- **AI-assisted threat detection** — alert classification via a connected LLM (MaaS/phi-4); falls back to a local stub when disconnected

## Architecture

```
[ Satellite VM (bootc / KVM) ]
  satellite-sim (Flask API, orbital mechanics, alert generation)
  skupper-router (RHSI agent — outbound link only)
        |
        | RHSI encrypted tunnel (port 443 outbound)
        |
[ OpenShift Cluster ]
  skupper-router (OCP-side router)
  satellite-alerts service (virtual endpoint — routes to VM)
  ground-station pod (Flask + HTMX UI)
        |
  [ Browser ]  ← ground station UI
```

## Prerequisites

- Fedora/RHEL host with KVM (`virsh`, `virt-install`, `podman`)
- Active Red Hat subscription (for `registry.redhat.io` base image)
- OpenShift cluster with RHSI operator installed
- `oc` CLI logged in to the cluster
- `sshpass`, `bootc-image-builder`

## Quickstart

See **[RUNBOOK.md](RUNBOOK.md)** for full step-by-step setup.

For subsequent rebuilds after the first deploy, see **[REBUILD-COMMANDS.md](REBUILD-COMMANDS.md)**.

## Demo flow

Once running, open the ground station URL in a browser.

| Action | Command |
|--------|---------|
| Break the uplink | `./scripts/demo-link-down.sh` |
| Watch satellite accumulate alerts | `./scripts/demo-watch-vm.sh` |
| Restore the uplink | `./scripts/demo-link-up.sh` |

Use the **DEMO TRIGGER** button in the UI to inject a high-confidence detection on demand.

## MaaS / AI classification

The ground station uses an external LLM endpoint for alert classification. Credentials are injected at deploy time via an OpenShift Secret. If no MaaS credentials are configured, classification falls back to a confidence-tier stub automatically.

To configure MaaS credentials, create the secret in your namespace:

```bash
oc create secret generic maas-credentials \
  --from-literal=url=https://your-litellm-endpoint/v1 \
  --from-literal=key=your-api-key \
  -n satellite-ground
```

## VM credentials

| Field | Value |
|-------|-------|
| User | `demo` |
| Password | `satellite` |

These are intentional demo credentials baked into the bootc image for local KVM access. Do not use in production images.
