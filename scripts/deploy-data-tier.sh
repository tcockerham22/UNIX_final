#!/usr/bin/env bash
# Starts the data tier in order. Safe to run on every boot, so the startup
# script can call it.
#
#   sudo -E ./scripts/deploy-data-tier.sh
#
#   1. LVM setup           (scripts/setup-lvm.sh)
#   2. get DB password     (DB_PASSWORD env var, else Secret Manager via metadata)
#   3. start the database  (compose/docker-compose.db.yml)
#   4. wait for it to be healthy
#   5. load documents      (scripts/ingest.py --if-empty)
#
# Optional env vars:
#   DB_SECRET_NAME   Secret Manager secret name (default db-password)
#   SKIP_INGEST=1    skip step 5
#   OLLAMA_URL       embedding service (default http://127.0.0.1:11434)
#   WAIT_OLLAMA      seconds to wait for it (default 120)
#   REQUIRE_OLLAMA=1 fail instead of skipping if it never comes up

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-compose/docker-compose.db.yml}"
DB_CONTAINER="${DB_CONTAINER:-rag-db}"
VENV_DIR="${VENV_DIR:-/opt/rag-ingest-venv}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
WAIT_OLLAMA="${WAIT_OLLAMA:-120}"

log() { echo "[deploy-data-tier] $*"; }
die() { echo "[deploy-data-tier] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo -E)"

# 1. Storage
log "step 1/5: LVM storage"
bash "$REPO_ROOT/scripts/setup-lvm.sh"

# 2. Password
log "step 2/5: database password"
if [[ -z "${DB_PASSWORD:-}" ]]; then
    DB_PASSWORD="$(bash "$REPO_DIR/scripts/get-secret.sh" "${DB_SECRET_NAME:-db-password}")" \
        || die "could not read the database password from Secret Manager"
    [[ -n "$DB_PASSWORD" ]] || die "Secret Manager returned an empty password"
fi
export DB_PASSWORD

# 3. Database container
log "step 3/5: starting database container"
docker compose -f "$COMPOSE_FILE" up -d

# 4. Health
log "step 4/5: waiting for the database to be healthy"
healthy=0
for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null || echo missing)"
    if [[ "$status" == "healthy" ]]; then healthy=1; break; fi
    sleep 2
done
[[ $healthy -eq 1 ]] || die "database did not become healthy (docker logs $DB_CONTAINER)"
log "database is healthy"

# 5. Ingestion
if [[ "${SKIP_INGEST:-0}" == "1" ]]; then
    log "step 5/5: SKIP_INGEST=1, skipping ingestion"
    exit 0
fi

log "step 5/5: ingestion"
ollama_up=0
for _ in $(seq 1 $((WAIT_OLLAMA / 5))); do
    if curl -fsS -o /dev/null "$OLLAMA_URL/api/tags"; then ollama_up=1; break; fi
    sleep 5
done
if [[ $ollama_up -eq 0 ]]; then
    if [[ "${REQUIRE_OLLAMA:-0}" == "1" ]]; then
        die "embedding service not reachable at $OLLAMA_URL"
    fi
    log "WARNING: embedding service not reachable at $OLLAMA_URL; skipping ingestion"
    log "re-run this script once the embedding model is running"
    exit 0
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    log "creating Python environment at $VENV_DIR"
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
        apt-get update -y
        apt-get install -y python3-venv python3-pip
        python3 -m venv "$VENV_DIR"
    fi
    "$VENV_DIR/bin/pip" install --quiet -r "$REPO_ROOT/scripts/requirements.txt"
fi

"$VENV_DIR/bin/python" "$REPO_ROOT/scripts/ingest.py" --if-empty
log "data tier is up"
