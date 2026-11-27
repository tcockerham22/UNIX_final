#!/usr/bin/env bash
# Write the running Docker container count where node-exporter can scrape it.
# cAdvisor cannot see Docker layers on this host, so this small textfile
# exporter gives the metrics tab an accurate container count instead.

set -euo pipefail

OUTPUT="${ADA_CONTAINER_METRICS_FILE:-/var/lib/node-exporter/textfile_collector/ada.prom}"
DIRECTORY="$(dirname "$OUTPUT")"

install -d -m 0755 "$DIRECTORY"
count="$(docker ps --format '{{.Names}}' | wc -l)"
temporary="$(mktemp "$DIRECTORY/.ada.prom.XXXXXX")"
printf '# HELP ada_containers_running Docker containers running on the edge VM.\n# TYPE ada_containers_running gauge\nada_containers_running %s\n' "$count" > "$temporary"
chmod 0644 "$temporary"
mv "$temporary" "$OUTPUT"
