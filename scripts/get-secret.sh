#!/usr/bin/env bash
# Fetch the latest Secret Manager value using the VM's attached service account.
# This avoids installing the gcloud CLI on every VM: it only needs curl and the
# GCE metadata server.
#
#   ./scripts/get-secret.sh db-password

set -euo pipefail

die() { echo "[get-secret] ERROR: $*" >&2; exit 1; }
name="${1:-}"
[[ -n "$name" ]] || die "usage: get-secret.sh SECRET_NAME"

metadata() {
    curl -fsS --max-time 5 -H 'Metadata-Flavor: Google' \
        "http://metadata.google.internal/computeMetadata/v1/$1"
}

project="${GOOGLE_CLOUD_PROJECT:-$(metadata project/project-id 2>/dev/null || true)}"
[[ -n "$project" ]] || die "no project ID in metadata; set GOOGLE_CLOUD_PROJECT"

token="$(metadata instance/service-accounts/default/token 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' 2>/dev/null)" \
    || die "could not get an access token from the metadata server"

payload="$(curl -fsS --max-time 10 -H "Authorization: Bearer $token" \
    "https://secretmanager.googleapis.com/v1/projects/${project}/secrets/${name}/versions/latest:access" 2>/dev/null)" \
    || die "could not read secret '$name' (check the name and secretAccessor IAM role)"

printf '%s' "$payload" | python3 -c '
import base64, json, sys
data = json.load(sys.stdin)["payload"]["data"]
sys.stdout.write(base64.b64decode(data).decode("utf-8"))
' || die "secret '$name' had an unreadable payload"
