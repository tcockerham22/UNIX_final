#!/usr/bin/env bash
# Idempotent boot script for the ada-ai VM (Member 4).
# GCP startup-script metadata can call this on every boot; repeated runs only
# fill in what is missing.
#
#   sudo ADA_AI_BIND_IP=10.0.0.3 ./scripts/startup-ai.sh
#
# Optional env vars:
#   REPO_DIR          checkout location (default /opt/ada)
#   ADA_CLOUD_MODEL   chat model (default qwen2.5:1.5b)
#   EMBED_MODEL       embedding model (default nomic-embed-text)
#   PRESTAGE_MODELS   set to 0 to skip pulling missing weights (default 1)
#   ADA_AI_BIND_IP    private IP for the readiness shims; read from metadata if unset

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/ada}"
LOG_FILE="${LOG_FILE:-/var/log/ada-startup-ai.log}"
ADA_CLOUD_MODEL="${ADA_CLOUD_MODEL:-qwen2.5:1.5b}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
PRESTAGE_MODELS="${PRESTAGE_MODELS:-1}"
COMPOSE_FILE="deploy/ai.compose.yml"

log() { echo "[startup-ai] $*"; }
die() { echo "[startup-ai] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)"
[[ -d "$REPO_DIR" ]] || die "repository not found at $REPO_DIR (set REPO_DIR)"
cd "$REPO_DIR"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log "starting AI VM setup"
bash "$REPO_DIR/scripts/install-docker.sh"

ADA_AI_BIND_IP="${ADA_AI_BIND_IP:-$(bash "$REPO_DIR/scripts/gcp-metadata.sh" instance/network-interfaces/0/ip 2>/dev/null || true)}"
[[ -n "$ADA_AI_BIND_IP" ]] || die "set ADA_AI_BIND_IP (metadata server did not provide a private IP)"
log "readiness shims will bind to $ADA_AI_BIND_IP"

log "step 1/3: storage (models only)"
SETUP_DB=0 SETUP_MODELS=1 bash "$REPO_DIR/scripts/setup-lvm.sh"

if [[ "$PRESTAGE_MODELS" == "1" ]]; then
    log "step 2/3: pre-staging models under /models"
    stage_script="$(cat <<'SH'
set -e
ollama serve >/tmp/ollama-stage.log 2>&1 &
server_pid=$!
trap 'kill $server_pid 2>/dev/null || true' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    ollama list >/dev/null 2>&1 && break
    sleep 1
done
for model in $ADA_MODELS; do
    if ollama list | awk '{print $1}' | grep -Fxq "$model"; then
        echo "model $model is already staged"
    else
        echo "pulling model $model"
        ollama pull "$model"
    fi
done
SH
)"
    docker run --rm \
        -e OLLAMA_MODELS=/models \
        -e ADA_MODELS="$ADA_CLOUD_MODEL $EMBED_MODEL" \
        -v /models:/models \
        --entrypoint /bin/sh ollama/ollama:0.40.18 -c "$stage_script"
else
    log "step 2/3: PRESTAGE_MODELS=0, skipping model download"
fi

log "step 3/3: starting inference containers"
ADA_AI_BIND_IP="$ADA_AI_BIND_IP" ADA_CLOUD_MODEL="$ADA_CLOUD_MODEL" ADA_MODELS_PATH=/models \
    docker compose -f "$COMPOSE_FILE" up -d --build

# Readiness shims run a real prompt before reporting healthy. Do not fail the
# boot if a model is still warming up; HAProxy will keep checking them.
for service in ready-shim-a ready-shim-b; do
    cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null || true)"
    [[ -n "$cid" ]] || continue
    healthy=0
    for _ in $(seq 1 60); do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo missing)"
        if [[ "$status" == "healthy" ]]; then healthy=1; break; fi
        sleep 3
    done
    if [[ "$healthy" == "1" ]]; then
        log "$service is ready"
    else
        log "WARNING: $service has not passed its readiness probe yet"
    fi
done

log "AI VM setup complete"
