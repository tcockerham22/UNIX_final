#!/usr/bin/env bash
# Single entry point for GCP startup-script metadata. Call it with a role, or
# set the instance metadata attribute ada-role to "edge" or "ai".
#
#   sudo /opt/ada/scripts/startup.sh edge
#   sudo /opt/ada/scripts/startup.sh ai
#
# Terraform (phase 6) can put that command in startup-script metadata after it
# clones the repository into /opt/ada. The role-specific scripts are idempotent,
# so the metadata script can run on every boot.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
die() { echo "[startup] ERROR: $*" >&2; exit 1; }

role="${1:-}"
if [[ -z "$role" ]]; then
    role="$(bash "$here/gcp-metadata.sh" instance/attributes/ada-role 2>/dev/null || true)"
fi
if [[ -z "$role" ]]; then
    role="$(hostname)"
fi

case "$role" in
    *edge*) exec bash "$here/startup-edge.sh" ;;
    *ai*)   exec bash "$here/startup-ai.sh" ;;
    *) die "unknown role '$role'; pass 'edge' or 'ai' (or set metadata ada-role)" ;;
esac
