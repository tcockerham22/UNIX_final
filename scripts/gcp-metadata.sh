#!/usr/bin/env bash
# Read one value from the GCE metadata server, with a short timeout so the
# scripts also work on a non-GCP development machine.
#
#   ./scripts/gcp-metadata.sh instance/attributes/ada-role [default]

set -euo pipefail

path="${1:-}"
[[ -n "$path" ]] || { echo "[metadata] ERROR: path is required" >&2; exit 1; }
default="${2-}"

value="$(curl -fsS --max-time 3 -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/${path}" 2>/dev/null || true)"
if [[ -n "$value" ]]; then
    printf '%s' "$value"
elif [[ -n "$default" ]]; then
    printf '%s' "$default"
else
    echo "[metadata] ERROR: no value for $path" >&2
    exit 1
fi
