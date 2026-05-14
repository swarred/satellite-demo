# Demo Guide

This guide covers how to run the full satellite demo end-to-end — from a standing deployment through all three demo phases.

---

## Overview

The demo tells a three-act story about mission continuity for an edge/space system:

1. **Connected operations** — satellite runs its online bootc image, streams telemetry and alerts to the ground station, AI classifies threats in real time.
2. **DDIL** — the uplink is severed. Event-Driven Ansible detects the outage autonomously, triggers a `bootc switch` to an offline image that includes a local LLM, and the satellite keeps classifying alerts with no human intervention.
3. **Restore** — connectivity is restored, EDA detects it, switches back to the online image, and all offline-classified alerts sync to the ground station UI automatically.

**Total runtime:** ~8–10 minutes including the two bootc switch cycles (each ~90 seconds).

---

## Prerequisites

- The demo environment is fully deployed (`ansible-playbook site.yml` completed successfully in the automation repo).
- You are logged in to the OCP cluster (`oc whoami` returns your user).
- `virsh` is accessible (`virsh --connect qemu:///system list` shows the `satellite-sim` VM running).
- A browser tab is open to the ground station URL.

To get the ground station URL:

```bash
oc get route ground-station -n satellite-ground -o jsonpath='{.spec.host}'
```

---

## Pre-demo checklist

Run these before your audience arrives:

```bash
# 1. Verify the VM is running
virsh --connect qemu:///system domstate satellite-sim
# Expected: running

# 2. Verify the ground station is reachable
curl -s https://$(oc get route ground-station -n satellite-ground -o jsonpath='{.spec.host}')/healthz
# Expected: {"status":"ok"}

# 3. Verify the satellite API is reachable through the RHSI tunnel
oc run curl-test --rm -it --image=curlimages/curl -n satellite-ground --restart=Never \
  -- curl -s http://satellite-alerts:8080/healthz
# Expected: {"status":"ok"}

# 4. Verify the ground station UI shows LINK ONLINE (green dot, top right)

# 5. Trigger one detection to confirm the full pipeline works
#    Use the TRIGGER DETECTION button in the UI and confirm an alert card appears
```

If the link indicator shows LINK DOWN, check Skupper:

```bash
VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1)
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "sudo systemctl status skupper-satellite-vm.service --no-pager"
```

---

## Phase 1 — Connected operations

**Open the ground station URL in a browser.**

### What to show

**Header bar (top)**
- `LINK ONLINE` — green dot confirming the RHSI tunnel between OCP and the satellite VM is active.
- UTC clock — all timestamps are Zulu, as used in space operations.

**Telemetry sidebar (left)**
- Live altitude, latitude/longitude, velocity, and angular rate from the satellite sim.
- Ground track canvas — blue dot moves across a regional map of the Persian Gulf / Arabian Peninsula AOI. The amber dashed box is the Area of Interest (AOI). The satellite's approach trajectory is the orbital corridor being monitored.

**Threat detection feed (main panel)**
- Alerts appear when the satellite's sensors detect a ground-based signature as it passes over the AOI.
- Each card shows confidence score, classification, and lat/lon of the detected emitter.

### Key talking points

- The satellite VM is running a **bootc (image-based) RHEL OS** — the entire OS, including all runtime dependencies, is baked into a container image. There is no package manager, no drift, no configuration mismatch between instances.
- The RHSI tunnel is **outbound-only from the VM** — no inbound firewall rules, no VPN concentrator, no static IP required. The satellite initiates the connection; OCP accepts it.

### Triggering a detection on demand

If the satellite isn't over the AOI yet, use the **TRIGGER DETECTION** button in the operator strip to inject a synthetic high-confidence detection immediately.

### Analyzing an alert

Click **ANALYZE** on any alert card. The ground station sends the alert data to the configured LLM endpoint (MaaS phi-4 if configured, otherwise the built-in confidence-tier stub). The response includes:
- Classification label (`DIRECTED_ENERGY`, `RF_EMITTER`, `THERMAL_PLUME`, `THERMAL_ANOMALY`, or `UNKNOWN_EMITTER`)
- Threat assessment narrative
- Recommended action
- Model and latency metadata

---

## Phase 2 — DDIL: autonomous offline mode

### Trigger the DDIL sequence

In the automation repo directory, run:

```bash
ansible-playbook demo-ddil.yml --ask-become-pass
```

**What Ansible does (narrated in task names as it runs):**

| Step | What happens | Time |
|------|-------------|------|
| Break ground station link | Stops Skupper on the VM → UI shows LINK DOWN immediately | ~5s |
| Block ground station hostname | Poisons `/etc/hosts` → EDA `url_check` gets instant failure | ~5s |
| Wait for EDA detection | EDA rulebook fires within ~20s of the first failed check | ~20s |
| bootc switch triggered | VM runs `bootc switch` to the offline image and reboots | ~5s |
| Wait for reboot cycle | VM goes down, KVM restarts it, SSH comes back up | ~90s |
| Confirm offline image | Reads `bootc status` to confirm offline image is booted | ~5s |
| Watch first classifications | Streams `journalctl` until 2 autonomous classifications appear | ~60s |

**Watch the ground station UI while Ansible runs:**
- LINK DOWN indicator appears immediately when Skupper stops.
- Ground track trail clears within 2 seconds (satellite telemetry is no longer reachable).

### Monitor autonomous operations (second terminal)

While Ansible is running (or after it completes), open a second terminal and run from the `satellite-demo` directory:

```bash
./scripts/demo-watch-offline.sh
```

This SSHs into the satellite VM and streams live classifications from `satellite-local-analysis.service`:

```
  ╔═══════════════════════════════════════════════════════╗
  ║   SATELLITE SIM — AUTONOMOUS OFFLINE OPERATIONS       ║
  ║   Ground station uplink: SEVERED                      ║
  ║   Operating mode:        DDIL AUTONOMOUS              ║
  ║   Classification engine: llama3.2:1b (local LLM)      ║
  ║   Alerts queued so far:  3                            ║
  ╚═══════════════════════════════════════════════════════╝

  ... Classifying alert abc123 (confidence=0.923) ...
  ... Classified abc123 → DIRECTED_ENERGY ...
```

### Key talking points

- **No human intervention.** The satellite detected the outage, decided to switch operating modes, executed an atomic OS image swap, rebooted, and resumed classifying threats — all autonomously, driven by the on-board EDA rulebook.
- **The OS itself changed.** `bootc switch` swaps the entire immutable OS image. The offline image is a different container image from the online one — it includes Ollama and llama3.2:1b, which are not present in the online image at all. This is not a config change or a service restart.
- **Persistent storage bridges the images.** `/var/lib/satellite-sim/` is not managed by bootc (it's in `/var/`, which persists across switches). Alerts logged during online operations are still there. New offline-classified alerts are written to the same volume and will be available when the online image boots.
- **Local LLM, fully embedded.** llama3.2:1b and the Ollama binary are baked into the offline bootc image at build time. No internet access is needed. Classification quality is lower than the ground-connected phi-4 endpoint, but classification continues — mission data is not lost.

---

## Phase 3 — Restore: reconnect and sync

### Restore the uplink

In the automation repo directory, run:

```bash
ansible-playbook demo-restore.yml --ask-become-pass
```

**What Ansible does:**

| Step | What happens | Time |
|------|-------------|------|
| Remove hostname block | Removes `/etc/hosts` poison entry → EDA url_check succeeds | ~5s |
| Wait for EDA detection | Reconnect rulebook fires within ~20s | ~20s |
| bootc switch triggered | VM runs `bootc switch` to online image and reboots | ~5s |
| Wait for reboot cycle | VM comes back up on the online image | ~90s |
| Confirm online image | Reads `bootc status` | ~5s |
| Report offline alert count | Shows how many alerts were classified during DDIL | ~5s |
| Wait for Skupper link | Monitors until RHSI tunnel re-establishes | ~30s |

### What appears in the ground station UI

Once Skupper reconnects:
- LINK ONLINE indicator returns.
- Ground track resumes (blue dot reappears).
- **Offline-classified alerts appear automatically** — the satellite sim loads them from `/var/lib/satellite-sim/offline-queue.jsonl` on startup and pushes them to the ground station via the restored RHSI link.

Offline alerts display an **OFFLINE** badge. Click **ANALYZE** on one to see its classification:
- The assessment text comes from the local llama3.2:1b analysis stored during DDIL.
- Model shown as `llama3.2:1b (offline local LLM)`.
- If Ollama had insufficient time to classify an alert, the assessment notes "re-analysis recommended" — click ANALYZE again to classify it now via MaaS.

### Key talking points

- **No data loss.** Every alert detected during the DDIL window is accounted for — either classified offline and synced, or flagged for re-analysis.
- **The same process in reverse.** EDA detects connectivity recovery and triggers the switch back to the online image. Same mechanism, same guarantees.
- **Ground station never needed updating.** The ground station has been polling for alerts the entire time — once the tunnel comes back, the new alerts flow through automatically.

---

## Operator controls reference

The operator strip runs along the bottom of the ground station UI.

| Control | What it does |
|---------|-------------|
| **SIMULATE DDIL** | Stops Skupper and poisons `/etc/hosts` on the satellite VM (same as the first two steps of `demo-ddil.yml`). Does not wait for EDA or the bootc switch — use `demo-watch-offline.sh` to monitor. Useful for a faster demo that skips the Ansible terminal. |
| **TRIGGER DETECTION** | Injects a synthetic detection at the satellite's current position. Useful when the satellite isn't over the AOI. |
| **RESET APPROACH** | Resets the satellite's orbital position back to the beginning of the AOI approach corridor. Use this to restart the ground track animation. |
| **CLEAR ALERTS** | Clears all alerts from both the UI and the satellite's in-memory store. Does not affect persisted `.jsonl` files. |

Per-alert controls (on each alert card):

| Control | What it does |
|---------|-------------|
| **ANALYZE** | Sends the alert to the LLM for classification. Online mode uses MaaS phi-4 (or stub). Offline alerts show their stored llama3.2:1b assessment. |
| **ACK** | Marks the alert as acknowledged (changes badge colour). |
| **DISMISS** | Removes the LLM assessment from the card without deleting the alert. |

---

## Manual DDIL control (alternative to Ansible playbooks)

If you prefer shell scripts over Ansible, the `scripts/` directory has equivalents:

```bash
# Trigger DDIL
./scripts/demo-ddil-on.sh

# Monitor autonomous operations (second terminal)
./scripts/demo-watch-offline.sh

# Restore connectivity
./scripts/demo-ddil-off.sh
```

The scripts do the same SSH operations as the Ansible playbooks but without the wait-and-narrate loop. Use the Ansible playbooks for live demos (the task names serve as a running commentary for the audience); use the scripts for faster iteration during development.

---

## Timing guide

| Phase | Duration | Notes |
|-------|----------|-------|
| `ansible-playbook demo-ddil.yml` | ~4–5 min | Includes 90s for bootc reboot cycle |
| Autonomous operations window | As long as needed | Satellite classifies every alert that passes over the AOI |
| `ansible-playbook demo-restore.yml` | ~3–4 min | Includes 90s for bootc reboot cycle |
| Skupper reconnect after reboot | ~30–60s | Depends on cluster load |
| **Total demo (active)** | ~8–10 min | Plus however long you narrate each phase |

---

## Resetting for another run

To run the demo again without a full teardown/redeploy:

```bash
# In the ground station UI: CLEAR ALERTS, then RESET APPROACH

# Reset the satellite orbital position (also available in the UI)
oc run curl-test --rm -it --image=curlimages/curl -n satellite-ground --restart=Never \
  -- curl -s -X POST http://satellite-alerts:8080/orbit/reset

# Clear the persistent offline queue on the VM (so offline alerts don't re-appear)
VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1)
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "sudo rm -f /var/lib/satellite-sim/offline-queue.jsonl \
              /var/lib/satellite-sim/offline-queue.jsonl.loaded \
              /var/lib/satellite-sim/alerts.jsonl"
```

---

## Troubleshooting

**LINK DOWN on startup / after redeploy**

Skupper needs ~30–60 seconds to establish after the VM boots. Wait and refresh. If it doesn't come up after 2 minutes:

```bash
VM_IP=$(virsh --connect qemu:///system domifaddr satellite-sim | awk '/ipv4/ {print $4}' | cut -d/ -f1)
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "sudo journalctl -u skupper-init.service -u skupper-satellite-vm.service --no-pager | tail -30"
```

**EDA doesn't detect the DDIL / reconnect within expected time**

Check the EDA service on the VM:

```bash
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "sudo journalctl -fu satellite-eda --no-pager | tail -20"
```

**Ollama takes too long to classify alerts**

llama3.2:1b should classify each alert in under 30 seconds on the 5 GB VM. If it's slower, check whether the model is resident in memory:

```bash
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "sudo systemctl status ollama.service --no-pager"
```

The `OLLAMA_KEEP_ALIVE=-1` environment variable keeps the model loaded indefinitely — it should not need to reload between AOI passes.

**Offline alerts don't appear after reconnect**

The satellite sim loads `offline-queue.jsonl` at startup. If the file was already processed (`.loaded` suffix), it won't re-import. Check:

```bash
sshpass -p satellite ssh -o StrictHostKeyChecking=no demo@$VM_IP \
  "ls -la /var/lib/satellite-sim/"
```

If `offline-queue.jsonl.loaded` exists but alerts aren't in the UI, the queue may have been empty at boot. Verify with:

```bash
cat /var/lib/satellite-sim/offline-queue.jsonl.loaded 2>/dev/null | wc -l
```
