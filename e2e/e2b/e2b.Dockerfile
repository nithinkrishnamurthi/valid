FROM ubuntu:22.04

# Install Docker + compose via the official convenience script, plus
# a few extras we need.
# E2B sandboxes are Firecracker microVMs, so dockerd runs natively
# inside — no DinD / nested virt needed.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ca-certificates curl git sudo \
    && curl -fsSL https://get.docker.com | sh \
    && rm -rf /var/lib/apt/lists/*

# E2B's default sandbox user is "user" (not root). Add it to the docker
# group so it can talk to dockerd's socket without sudo.
RUN usermod -aG docker user 2>/dev/null || true

# Workdir for the deployed app. Owned by `user` so tar extract + compose
# don't need sudo for file ops.
RUN mkdir -p /home/user/app && chown user:user /home/user/app
WORKDIR /home/user/app

# dockerd is launched by `set_start_cmd` in template.py (runtime config),
# not at image-build time.
