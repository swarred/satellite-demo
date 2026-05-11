# Pull skrouterd from the skupper-router image — copied into the final image so
# the VM never needs to pull a container image at runtime to run skupper.
FROM quay.io/skupper/skupper-router:latest AS skupper-router

FROM registry.redhat.io/rhel10/rhel-bootc:latest

# Install Python and pip dependencies in a single layer
RUN dnf -y install python3 python3-pip cloud-init && \
    dnf clean all

# Install Python dependencies before copying app code so this layer caches
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --prefix=/usr/local -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install application
COPY satellite_sim/ /opt/satellite-sim/satellite_sim/

# Demo user — local VM access only, not for production images
RUN useradd -m -G wheel demo && \
    echo 'demo:satellite' | chpasswd && \
    echo '%wheel ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/wheel-nopasswd

# Install skupper CLI for non-Kubernetes (VM) site management
RUN curl -fsSL https://github.com/skupperproject/skupper/releases/download/2.1.4/skupper-cli-2.1.4-linux-amd64.tgz \
      | tar -xz -C /usr/local/bin skupper && \
    chmod +x /usr/local/bin/skupper

# Copy skrouterd and its full runtime from skupper-router image.
# skrouterd needs its Python scripts at /usr/lib/skupper-router/python (hardcoded path)
# and three shared libs not present in RHEL 10 (built against UBI9/Python 3.9).
# Place the binary in /usr/sbin so it's on root's default PATH.
COPY --from=skupper-router /usr/sbin/skrouterd /usr/sbin/skrouterd
COPY --from=skupper-router /usr/lib/skupper-router /usr/lib/skupper-router
COPY --from=skupper-router /lib64/libpython3.9.so.1.0 /lib64/libpython3.9.so.1.0
COPY --from=skupper-router /usr/local/lib/libunwind.so.8 /usr/local/lib/libunwind.so.8
COPY --from=skupper-router /usr/local/lib/libwebsockets.so.19 /usr/local/lib/libwebsockets.so.19
COPY --from=skupper-router /usr/lib64/python3.9 /usr/lib64/python3.9

# Skupper static config (site + connector) baked in; token dropped by cloud-init at boot
RUN mkdir -p /etc/skupper /var/lib/skupper
COPY skupper/site.yaml      /etc/skupper/site.yaml
COPY skupper/connector.yaml /etc/skupper/connector.yaml

# Install systemd units and enable them
COPY systemd/satellite-sim.service /usr/lib/systemd/system/satellite-sim.service
COPY systemd/skupper-init.service  /usr/lib/systemd/system/skupper-init.service

# ── Event-Driven Ansible (DDIL detection) ────────────────────────────────────
# ansible-rulebook watches the ground station health endpoint; on connectivity
# loss it stages the offline image and reboots into autonomous DDIL mode.
RUN dnf -y install java-21-openjdk-headless ansible-core && \
    pip3 install --no-cache-dir ansible-rulebook ansible-runner && \
    ansible-galaxy collection install ansible.eda && \
    dnf clean all

ARG GROUND_STATION_URL=https://ground-station-satellite-ground.apps.example.com

RUN mkdir -p /etc/satellite-eda
COPY eda/ddil-detect.yml         /etc/satellite-eda/ddil-detect.yml
COPY eda/bootc-switch-offline.yml /etc/satellite-eda/bootc-switch-offline.yml
COPY eda/inventory               /etc/satellite-eda/inventory

# Bake the ground station URL so EDA knows what to probe (no runtime config needed)
RUN echo "ground_station_url: \"${GROUND_STATION_URL}\"" > /etc/satellite-eda/vars.yml

# Allow insecure pulls from the build host's local registry over KVM bridge
COPY containers/local-registry.conf /etc/containers/registries.conf.d/local-registry.conf

COPY systemd/satellite-eda-online.service \
     /usr/lib/systemd/system/satellite-eda.service

RUN systemctl enable satellite-sim.service skupper-init.service \
                    satellite-eda.service \
                    cloud-init-local.service cloud-init.service \
                    cloud-config.service cloud-final.service

# Expose the telemetry API port (RHSI will route this externally)
EXPOSE 8080

# Metadata labels — used by Edge Manager / flightctl for tracking
LABEL io.redhat.component="satellite-sim" \
      io.redhat.version="0.1.1" \
      description="USSF satellite simulation — imagery analysis and threat detection demo"
