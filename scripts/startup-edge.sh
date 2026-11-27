#!/usr/bin/env bash
# Idempotent boot script for the ada-edge VM (Members 2 and 3).
# It builds the Compose environment from Secret Manager, then starts the edge
# stack. Safe to call again on every boot; Compose reconciles existing services.
#
#   sudo ./scripts/startup-edge.sh
#
# Optional env vars:
#   REPO_DIR               checkout location (default /opt/ada)
#   DB_PASSWORD            override Secret Manager for local testing
#   GRAFANA_ADMIN_PASSWORD override Secret Manager for local testing
#   ADA_AI_PRIVATE_IP      AI VM private IP; read from metadata if unset
#   DB_SECRET_NAME         default db-password
#   GRAFANA_SECRET_NAME    default grafana-admin-password
#   ADA_WEB_REPLICAS       initial replica count (default 3)

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/ada}"
LOG_FILE="${LOG_FILE:-/var/log/ada-startup-edge.log}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"
SYSTEMD_ENV_FILE="${SYSTEMD_ENV_FILE:-/etc/ada/cloud.env}"
DB_SECRET_NAME="${DB_SECRET_NAME:-db-password}"
GRAFANA_SECRET_NAME="${GRAFANA_SECRET_NAME:-grafana-admin-password}"
ADA_CLOUD_MODEL="${ADA_CLOUD_MODEL:-qwen3.5:4b}"
ADA_WEB_REPLICAS="${ADA_WEB_REPLICAS:-3}"
COMPOSE_FILE="deploy/edge.compose.yml"

log() { echo "[startup-edge] $*"; }
die() { echo "[startup-edge] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)"
[[ -d "$REPO_DIR" ]] || die "repository not found at $REPO_DIR (set REPO_DIR)"
cd "$REPO_DIR"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log "starting edge VM setup"
bash "$REPO_DIR/scripts/install-docker.sh"

if ! command -v python3 >/dev/null 2>&1; then
    log "installing python3"
    apt-get update -y
    apt-get install -y python3
fi

ADA_AI_PRIVATE_IP="${ADA_AI_PRIVATE_IP:-$(bash "$REPO_DIR/scripts/gcp-metadata.sh" instance/network-interfaces/0/ip 2>/dev/null || true)}"
[[ -n "$ADA_AI_PRIVATE_IP" ]] || die "set ADA_AI_PRIVATE_IP (metadata server did not provide a private IP)"
log "inference traffic will go to $ADA_AI_PRIVATE_IP"

log "step 1/4: storage (database only)"
SETUP_DB=1 SETUP_MODELS=0 bash "$REPO_DIR/scripts/setup-lvm.sh"

log "step 2/4: reading secrets"
db_password="${DB_PASSWORD:-$(bash "$REPO_DIR/scripts/get-secret.sh" "$DB_SECRET_NAME")}"
grafana_password="${GRAFANA_ADMIN_PASSWORD:-$(bash "$REPO_DIR/scripts/get-secret.sh" "$GRAFANA_SECRET_NAME")}"
[[ -n "$db_password" ]] || die "database password is empty"
[[ -n "$grafana_password" ]] || die "Grafana admin password is empty"

db_url="$(DB_PASSWORD="$db_password" python3 - <<'PY'
import os
import urllib.parse
password = urllib.parse.quote(os.environ["DB_PASSWORD"], safe="")
print(f"postgresql://raguser:{password}@postgres:5432/ragdb")
PY
)"
env_value() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# The .env file is ignored by Git and is also read by the autoscaler's Compose
# calls, so it must contain everything edge.compose.yml interpolates.
umask 077
{
    printf 'ADA_AI_PRIVATE_IP=%s\n' "$(env_value "$ADA_AI_PRIVATE_IP")"
    printf 'ADA_CLOUD_MODEL=%s\n' "$(env_value "$ADA_CLOUD_MODEL")"
    printf 'POSTGRES_DB=ragdb\n'
    printf 'POSTGRES_USER=raguser\n'
    printf 'POSTGRES_PASSWORD=%s\n' "$(env_value "$db_password")"
    printf 'ADA_DATABASE_URL=%s\n' "$(env_value "$db_url")"
    printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(env_value "$grafana_password")"
    printf 'ADA_DB_DATA=%s\n' "$(env_value "${ADA_DB_DATA:-/data/db/pgdata}")"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
log "wrote $ENV_FILE (mode 600)"

log "step 3/4: starting edge containers (ingestion runs conditionally in Compose)"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build \
    --scale "ada-web=$ADA_WEB_REPLICAS"

log "step 4/4: installing the autoscaler service"
install -d -m 0755 /etc/ada
install -m 0640 -o root -g ada "$ENV_FILE" "$SYSTEMD_ENV_FILE"
install -m 0644 "$REPO_DIR/deploy/ada-autoscaler.service" \
    /etc/systemd/system/ada-autoscaler.service
systemctl daemon-reload
systemctl enable --now ada-autoscaler.service || log "WARNING: autoscaler did not start"
log "edge VM setup complete"
