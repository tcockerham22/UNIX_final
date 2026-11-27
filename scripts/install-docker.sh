#!/usr/bin/env bash
# Idempotent Docker Engine + Compose plugin installation for Debian/Ubuntu.
# Safe to call from a VM startup script on every boot.
#
#   sudo ./scripts/install-docker.sh

set -euo pipefail

DOCKER_USER="${DOCKER_USER:-ada}"
log() { echo "[install-docker] $*"; }
die() { echo "[install-docker] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "docker and the compose plugin are already installed"
else
    [[ -f /etc/os-release ]] || die "/etc/os-release is missing; unsupported distribution"
    # shellcheck disable=SC1091
    . /etc/os-release
    case "$ID" in
        debian|ubuntu) ;;
        *) die "unsupported distribution: $ID (install Docker manually)" ;;
    esac

    log "installing Docker dependencies"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
        | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    arch="$(dpkg --print-architecture)"
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    log "Docker installed"
fi

systemctl enable --now docker

# The autoscaler systemd unit runs as this user and needs Compose access.
if ! id -u "$DOCKER_USER" >/dev/null 2>&1; then
    log "creating system user $DOCKER_USER"
    useradd --create-home --shell /bin/bash "$DOCKER_USER"
fi
usermod -aG docker "$DOCKER_USER"
log "user $DOCKER_USER can run docker"
