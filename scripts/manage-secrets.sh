#!/usr/bin/env bash
# Small Secret Manager helper used by the VM startup scripts.
#
#   ./scripts/manage-secrets.sh get NAME                 print the latest value
#   ./scripts/manage-secrets.sh ensure NAME [VALUE]      create a secret once
#   ./scripts/manage-secrets.sh grant NAME MEMBER
#
# `ensure` is an operator/setup step: it needs an account that can enable the
# Secret Manager API and create secrets. `get` only needs
# roles/secretmanager.secretAccessor. Values are never written to this
# repository. Set SECRET_VALUE instead of passing a password on the command
# line when creating a known value.

set -euo pipefail

log() { echo "[secrets] $*" >&2; }
die() { echo "[secrets] ERROR: $*" >&2; exit 1; }

command -v gcloud >/dev/null 2>&1 || die "gcloud is not installed or not on PATH"

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-${GCLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
[[ -n "$PROJECT_ID" && "$PROJECT_ID" != "(unset)" ]] \
    || die "no GCP project is set; run 'gcloud config set project PROJECT_ID' or set GOOGLE_CLOUD_PROJECT"

ensure_api() {
    if gcloud services list --enabled --project="$PROJECT_ID" \
        --filter='config.name=secretmanager.googleapis.com' \
        --format='value(config.name)' 2>/dev/null | grep -qx 'secretmanager.googleapis.com'; then
        return 0
    fi
    log "Secret Manager API is not enabled in '$PROJECT_ID'; enabling it"
    gcloud services enable secretmanager.googleapis.com \
        --project="$PROJECT_ID" --quiet \
        || die "could not enable the API; enable it manually at https://console.cloud.google.com/apis/library/secretmanager.googleapis.com?project=$PROJECT_ID"
    for _ in $(seq 1 12); do
        if gcloud services list --enabled --project="$PROJECT_ID" \
            --filter='config.name=secretmanager.googleapis.com' \
            --format='value(config.name)' 2>/dev/null | grep -qx 'secretmanager.googleapis.com'; then
            log "Secret Manager API is enabled"
            return 0
        fi
        sleep 5
    done
    die "the API was enabled but has not propagated yet; wait a minute and retry"
}

ensure_api

cmd="${1:-}"
case "$cmd" in
    get)
        name="${2:-}"
        [[ -n "$name" ]] || die "usage: get NAME"
        value="$(gcloud secrets versions access latest --project="$PROJECT_ID" --secret="$name" 2>/dev/null)" \
            || die "could not read secret '$name' (check the name and IAM access)"
        [[ -n "$value" ]] || die "secret '$name' has an empty latest version"
        printf '%s' "$value"
        ;;
    ensure)
        name="${2:-}"
        [[ -n "$name" ]] || die "usage: ensure NAME [VALUE]"
        if gcloud secrets describe "$name" --project="$PROJECT_ID" >/dev/null 2>&1; then
            log "secret '$name' already exists; leaving it unchanged"
            exit 0
        fi
        value="${SECRET_VALUE:-${3:-}}"
        if [[ -z "$value" ]]; then
            if command -v openssl >/dev/null 2>&1; then
                value="$(openssl rand -hex 24)"
            else
                value="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
            fi
            log "generated a random value for '$name'"
        fi
        printf '%s' "$value" | gcloud secrets create "$name" \
            --project="$PROJECT_ID" --data-file=- \
            --replication-policy=automatic --quiet
        log "created secret '$name'"
        ;;
    grant)
        name="${2:-}"
        member="${3:-}"
        [[ -n "$name" && -n "$member" ]] || die "usage: grant NAME MEMBER"
        case "$member" in
            user:*|serviceAccount:*|group:*|domain:*|deleted:*) ;;
            *@*.gserviceaccount.com) member="serviceAccount:$member" ;;
            *@*) member="user:$member" ;;
            *) die "member must be an email or a prefixed IAM member (user:, serviceAccount:, group:, domain:)" ;;
        esac
        gcloud secrets add-iam-policy-binding "$name" \
            --project="$PROJECT_ID" --member="$member" \
            --role=roles/secretmanager.secretAccessor --quiet
        log "granted $member access to '$name'"
        ;;
    *)
        sed -n '2,10p' "$0"
        exit 1
        ;;
esac
