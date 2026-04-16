FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Docker (Docker Engine + Compose v2 plugin).
# E2B sandboxes are Firecracker microVMs, so the Docker daemon runs
# natively inside — no DinD / nested virt needed.
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu jammy stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Start dockerd at sandbox boot.
RUN echo '#!/bin/sh\nnohup dockerd > /var/log/dockerd.log 2>&1 &\n' > /usr/local/bin/start-docker.sh \
    && chmod +x /usr/local/bin/start-docker.sh

WORKDIR /app
