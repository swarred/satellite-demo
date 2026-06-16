# Satellite Demo

**[Live demo preview →](https://swarred.github.io/satellite-demo/)**

A Red Hat Image Mode (bootc) demonstration built around a simulated LEO reconnaissance satellite. The satellite VM runs an immutable, image-based RHEL OS, connects to an OpenShift ground station over an encrypted tunnel via Red Hat Service Interconnect (RHSI), and autonomously switches to a local-LLM offline image when the uplink is lost — then switches back and syncs alerts when connectivity is restored.

## What it demonstrates

- **RHEL Image Mode (bootc)** — immutable, image-based OS for edge and space infrastructure. Updates, rollbacks, and DDIL mode switches are atomic bootc operations, not package installs.
- **DDIL resilience** — when the uplink drops, Event-Driven Ansible detects the outage and triggers a `bootc switch` to an offline image that includes a local LLM (llama3.2:1b via Ollama) for autonomous alert classification. Alerts queue to persistent storage and sync to the ground station on reconnect.
- **Red Hat Service Interconnect (RHSI)** — encrypted, mTLS tunnel between the KVM satellite VM and OpenShift. Outbound-only from the VM — no inbound ports, NAT-friendly, works across network boundaries.
- **Event-Driven Ansible** — on-satellite rulebook that monitors ground station reachability and drives the bootc switch cycle autonomously, with no operator intervention required.
- **AI-assisted threat classification** — connected mode uses an external LLM endpoint (MaaS/phi-4). Offline mode uses llama3.2:1b running on the satellite VM. Both paths produce the same structured assessment visible in the ground station UI.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Satellite VM  (KVM / RHEL bootc)                       │
│                                                         │
│  satellite-sim       Flask API, orbital sim, alerts     │
│  satellite-eda       Event-Driven Ansible, DDIL monitor │
│  skupper-router      RHSI agent (outbound link only)    │
│                                                         │
│  ── offline image adds ──────────────────────────────── │
│  ollama              llama3.2:1b local inference        │
│  satellite-local-analysis  classifies alerts offline    │
└─────────────────────────┬───────────────────────────────┘
                          │  RHSI encrypted tunnel (443 outbound)
┌─────────────────────────▼───────────────────────────────┐
│  OpenShift Cluster                                      │
│                                                         │
│  skupper-router      OCP-side RHSI router               │
│  satellite-alerts    virtual service → VM :8080         │
│  ground-station      Flask + HTMX UI                    │
└─────────────────────────────────────────────────────────┘
                          │
                       Browser
```

## Quick start

Deployment is fully automated. Clone both repos as siblings, then run one playbook:

```bash
git clone https://github.com/swarred/satellite-demo
git clone https://github.com/swarred/satellite-demo-automation
cd satellite-demo-automation
./setup-creds.sh          # configure MaaS credentials (optional — demo works without)
ansible-playbook site.yml --ask-become-pass
```

See the [automation repo README](https://github.com/swarred/satellite-demo-automation) for full prerequisites and configuration.

## Running the demo

See **[DEMO.md](DEMO.md)** for the complete demo guide — pre-demo checklist, all three phases, UI controls reference, and timing.

## MaaS / AI classification

The ground station uses an external LLM endpoint (OpenAI-compatible) for alert classification in connected mode. If no MaaS credentials are configured, classification falls back to a confidence-tier stub automatically — the demo works fully without MaaS.

To configure credentials:

```bash
cd satellite-demo-automation
./setup-creds.sh
```

Or set them directly in the OCP namespace:

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

Intentional demo credentials baked into the bootc image for local KVM access.

## Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/demo-ddil-on.sh` | Break the uplink and trigger EDA detection manually (alternative to the Ansible playbook) |
| `scripts/demo-ddil-off.sh` | Restore the uplink (alternative to the Ansible playbook) |
| `scripts/demo-watch-offline.sh` | Stream live LLM classifications from the satellite VM during DDIL |
| `scripts/test-local-llm.sh` | Validate llama3.2:1b output before building the offline image |
