# Satellite Demo — Narrative Script

A presenter's guide for the USSF Software-defined Warfighting demo. Read this alongside BUILD-LOG.md (technical state) and the "Software-defined Warfighting: Integrated Mission Architecture" slide deck.

---

## The through-line

Every moment in this demo is answering one question the audience already has:

> *"How do you actually run and update software on a satellite payload — reliably, securely, without touching it?"*

The Containerfile answers it. The detection pipeline proves it works. RHSI shows what happens when the data needs to get home. The AI pod closes the kill chain.

---

## Act 1 — The payload computer (bootc + Containerfile)

### Setup

Before showing anything, frame what they're looking at:

> "What you're about to see running on screen is the payload computer of a simulated satellite. It's processing synthetic infrared imagery in real time, running a point-source anomaly detector, and logging threat detections — exactly as it would on orbit.
>
> But before we watch it run, I want to show you how it was built — because that's actually the more important part of the story."

Open the Containerfile.

---

### Walking the Containerfile — line by line

The goal is to make each section feel like a decision with consequences, not a list of commands.

---

**The FROM line**

```dockerfile
FROM quay.io/centos-bootc/centos-bootc:stream10
```

> "This single line is the root of trust for everything that runs on this payload computer. It declares the exact OS image — cryptographically pinned, supply-chain verified — that the software sits on top of.
>
> In the actual demo environment this becomes `registry.redhat.io/rhel10/rhel-bootc` — a FIPS-validated, STIG-aligned base that Red Hat ships and maintains. When we change this line, we're making a deliberate, auditable decision about what OS we trust. There's no ambiguity."

*Why this resonates:* RMF/ATO reviewers need a software bill of materials. This line IS the top of that bill. It's reviewable, version-controllable, and reproducible.

---

**The dependencies**

```dockerfile
RUN pip3 install --no-cache-dir --prefix=/usr/local -r /tmp/requirements.txt
```

> "Mission software dependencies — locked to exact versions in requirements.txt. Every build produces the same result. There's no 'it worked on my machine' — there's only the image."

Keep this brief. It's not the main event.

---

**The demo user**

```dockerfile
RUN useradd -m -s /bin/bash demo && echo 'demo:satellite' | chpasswd
```

Skip narrating this line — it's a demo convenience, not part of the story.

---

**The systemd service**

```dockerfile
COPY systemd/satellite-sim.service /usr/lib/systemd/system/satellite-sim.service
RUN systemctl enable satellite-sim.service
```

> "This is how the mission starts. The moment this node boots — whether it's coming up for the first time after launch, recovering from a power fault, or restarting after an anomaly — the simulation service starts automatically. No operator command. No manual step. No contact window required.
>
> The software knows what it's supposed to do. It just does it."

*Why this resonates:* DDIL environments. The node has to be autonomous. This is that autonomy baked into the image.

---

**The LABEL**

```dockerfile
LABEL io.redhat.component="satellite-sim" \
      io.redhat.version="0.1.0"
```

> "Version-stamped, component-labeled. Every image we push is traceable — you know exactly what's running on every node in your constellation without having to ask the node."

---

### The immutability moment — the most important beat

After walking the file, say:

> "Here's what makes this different from traditional satellite software management.
>
> Once this image is built and deployed, `/opt/satellite-sim` — where all the mission software lives — is **read-only**. I cannot SSH into this node and edit a file. I cannot patch it in place. I cannot make a 'quick fix' at 2am that nobody documented.
>
> If I need to change the software, I change this file, build a new image, and push it. The node pulls the update, verifies its integrity, and boots into the new image — or rolls back automatically if something's wrong.
>
> That's not a limitation. That's the guarantee. What passed your security review is exactly what's running. No drift. No surprises. No undocumented changes accumulating over a five-year orbital lifespan."

*Pause here.* Let it land.

> "For a program with a 10-to-15-year orbital lifespan, that guarantee is worth more than almost anything else I can show you today."

---

### The OTA update story (optional — if time allows)

> "Updating this satellite's software is — literally — editing this file, running one build command, and pushing the image. The node pulls it on next contact, verifies the cryptographic signature, and atomically switches over. No contact window ceremony. No manual procedure document. No configuration management ticket.
>
> And if the update fails validation on the node, it boots back into the previous image automatically. The mission continues."

---

### Connecting to STIG and PQC (plant the seed)

At the end of the Containerfile walkthrough, point to where the future lines will go:

> "Two things we're adding in the next phase: STIG hardening — `oscap` remediation baked directly into the build — and post-quantum crypto policy. One line: `update-crypto-policies --set DEFAULT:MLKEM`. That's it. Every node built from this image gets ML-KEM key exchange. For satellites with 10-to-15-year lifespans, quantum-safe comms aren't a future concern — they're a present one."

---

## Act 2 — The detection pipeline

### Showing the live telemetry

Pull up the telemetry endpoint:

```sh
watch -n 2 "curl -s localhost:8080/telemetry | python3 -m json.tool"
```

> "This is the satellite's current position — computed from real orbital mechanics using a Two-Line Element set. Latitude, longitude, altitude, velocity. Two-second cadence. The payload computer is continuously scanning its field of view."

Let it run for 30–60 seconds so the audience sees the position changing.

---

### Triggering the detection

See BUILD-LOG.md → *Demo talking points — detection trigger* for the full script.

Short version:

1. Narrate the operator commanding the payload to focus on a region of interest
2. Run `curl -s -X POST localhost:8080/demo/trigger | python3 -m json.tool`
3. Show the detection result — confidence 91%, coordinates, autonomous flag
4. Land on: *"No human initiated this. The software closed the detect-decide loop on its own."*
5. Transition: *"Now — this alert is sitting on a satellite at 420 kilometers altitude..."*

---

## Act 3 — Getting the data home (RHSI)

Switch to the ground station browser tab. Alerts are flowing, telemetry is live, header shows **● RHSI LINK ACTIVE**.

> "The satellite is currently over [read lat/lon from sidebar] at [alt_km] kilometers, scanning its field of view in real time. The ground station is receiving telemetry and alerts continuously through the RHSI tunnel — no contact window required, no firewall rules opened, no VPN.
>
> Now I'm going to simulate what happens in a denied or degraded environment."

**Run in a terminal:**
```sh
cd ~/satellite-demo && ./scripts/demo-link-down.sh
```

> "Communications disrupted. The ground station has lost contact — you can see the header flip to LINK LOST. The elapsed counter is running. The link has been denied."

**Immediately open a second terminal and run:**
```sh
cd ~/satellite-demo && ./scripts/demo-watch-vm.sh
```

Point at the VM terminal output.

> "But look at the payload computer. It has no idea the ground station is dark. It is still scanning. Still detecting. Still logging alerts autonomously — because that behavior is baked into the image, not dependent on a network connection.
>
> This is the edge autonomy story: the node keeps operating during DDIL. The data doesn't disappear — it accumulates on-board, waiting for connectivity to return."

Let the blackout run for 30–60 seconds. The audience should see new alerts appearing in the VM terminal while the ground station remains dark.

> "Contact window restored."

**Run in the first terminal:**
```sh
./scripts/demo-link-up.sh
```

Watch the ground station header flip back to **● RHSI LINK ACTIVE**. The queued alerts flood the feed simultaneously.

> "The moment the link came back up, every alert that accumulated during the blackout flowed through the tunnel to the ground station — in order, intact, no manual intervention. The satellite didn't need to know the ground station was gone. The ground station didn't need to poll or retry. RHSI handled the reconnection automatically.
>
> That is what a resilient space-to-ground architecture looks like."

*Pause.*

---

## Act 4 — The ground station and AI assessment

With alerts now in the feed, point to one:

> "The ground station operator sees the alert, reviews the coordinates and confidence score."

Click **ANALYZE**.

> "One button. That triggers an inference call — which returns a commander's assessment in plain language: what the anomaly likely is, what the confidence level means operationally, and recommended next action.
>
> The operator didn't write a report. They didn't wait for an analyst. The software closed the loop — from sensor to assessment — autonomously."

Click **ACK** on the alert.

> "Acknowledged and logged. The satellite's own record is updated through the same tunnel."

---

## Closing frame

> "What you just saw isn't a prototype of a future capability. Every component running here — RHEL Image Mode, OpenShift, Service Interconnect, OpenShift AI — is in production today across federal and commercial customers.
>
> The question for your program isn't whether this architecture works. It's whether your current software supply chain can make the same guarantees this Containerfile makes."

---

## Pacing notes

- **Don't rush the Containerfile.** It's the highest-signal moment in the demo. Audiences expect to be impressed by the flashy detection animation — they don't expect to find meaning in a text file. That surprise is the hook.
- **The immutability beat needs a pause after it.** Don't fill the silence.
- **Telemetry screen time:** 30–45 seconds is enough. More than that and the audience starts wondering if something's wrong.
- **Recovery if the VM isn't running:** rebuild takes ~15 minutes. Have a screen recording as backup. The Containerfile walkthrough can carry the full Act 1 without a live demo if needed.
