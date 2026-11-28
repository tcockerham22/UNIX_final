#!/usr/bin/env bash
# Checks that the deployed database keeps its data when the container is
# re-created and when the VM reboots. Run it on the edge VM (ada-edge) as root.
#
#   sudo ./tests/persistence-test.sh           (re-create test)
#   sudo ./tests/persistence-test.sh verify    (run after rebooting the VM)
#
# It works on the edge Compose stack that the startup script builds
# (/opt/ada/.env and deploy/edge.compose.yml). The web containers lose the
# database for a few seconds during the test and then reconnect. The output
# is saved in tests/results/ (commit it).
#
# The test writes one row into a table called persistence_probe. It is harmless,
# and you can drop it afterwards with: DROP TABLE persistence_probe;

set -uo pipefail

REPO_DIR="${REPO_DIR:-/opt/ada}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_DIR/deploy/edge.compose.yml}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"
SERVICE="${SERVICE:-postgres}"
DB_MOUNT="${DB_MOUNT:-/data/db}"
MARKER_FILE="${MARKER_FILE:-/var/tmp/persistence_probe_marker}"
RESULTS_DIR="${RESULTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results}"
MODE="${1:-run}"

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 2; }
[[ -r "$ENV_FILE" ]] || { echo "cannot read $ENV_FILE (set REPO_DIR or ENV_FILE)"; exit 2; }

mkdir -p "$RESULTS_DIR"
LOG="$RESULTS_DIR/persistence-$(date +%Y%m%d-%H%M%S)-${MODE}.log"
exec > >(tee -a "$LOG") 2>&1

FAILED=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILED=1; }

dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
cid() { dc ps -q "$SERVICE" 2>/dev/null | head -n 1; }
# The database user and name come from the container's own environment.
psql_q() { docker exec "$(cid)" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$0"' "$1"; }

wait_healthy() {
    local id status
    for _ in $(seq 1 60); do
        id="$(cid)"
        if [[ -n "$id" ]]; then
            status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)"
            [[ "$status" == "healthy" ]] && return 0
        fi
        sleep 2
    done
    return 1
}

echo "=== Persistence test ($MODE) ==="
echo "date:     $(date -Is)"
echo "host:     $(hostname)"
echo "AI tool:  Claude (helped write this script; prompts are in the test record)"
echo

echo "--- 1. Storage ---"
src="$(findmnt -n -o SOURCE "$DB_MOUNT" 2>/dev/null || true)"
echo "$DB_MOUNT is mounted from: ${src:-nothing}"
if [[ "$src" == /dev/mapper/vg_data-* ]]; then
    pass "$DB_MOUNT is an LVM logical volume"
else
    fail "$DB_MOUNT is not an LVM mount"
fi

if [[ "$MODE" == "verify" ]]; then
    echo "--- 2. After the reboot ---"
    uptime -s | sed 's/^/boot time: /'
    if wait_healthy; then
        pass "database container is healthy again (restart policy worked)"
    else
        fail "database container did not become healthy"
    fi
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    marker="$(cat "$MARKER_FILE" 2>/dev/null || true)"
    if [[ -z "$marker" ]]; then
        fail "no marker file at $MARKER_FILE; run the test without 'verify' first"
        exit 1
    fi
    found="$(psql_q "SELECT count(*) FROM persistence_probe WHERE note = '$marker'")"
    if [[ "$found" == "1" ]]; then
        pass "probe row '$marker' survived the reboot"
    else
        fail "probe row '$marker' is missing after the reboot"
    fi
    echo "chunks rows: $(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo n/a)"
    echo
    if [[ $FAILED -eq 0 ]]; then echo "RESULT: PASS"; else echo "RESULT: FAIL"; fi
    exit $FAILED
fi

echo "--- 2. The database files live on the volume ---"
wait_healthy || { fail "database is not healthy before the test"; exit 1; }
mounts="$(docker inspect -f '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' "$(cid)")"
echo "$mounts"
if echo "$mounts" | grep -q "^$DB_MOUNT.* -> /var/lib/postgresql/data"; then
    pass "PostgreSQL data directory is bind-mounted from $DB_MOUNT"
else
    fail "PostgreSQL data directory is not mounted from $DB_MOUNT"
fi

echo "--- 3. Write a probe row ---"
marker="probe-$(date +%s)"
psql_q "CREATE TABLE IF NOT EXISTS persistence_probe (note text, created timestamptz DEFAULT now())" >/dev/null
psql_q "INSERT INTO persistence_probe (note) VALUES ('$marker')" >/dev/null
echo "$marker" > "$MARKER_FILE"
echo "wrote $marker"
before="$(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo 0)"
echo "chunks rows before: $before"

echo "--- 4. Remove and re-create the database container ---"
dc rm -sf "$SERVICE"
if [[ -z "$(cid)" ]]; then
    pass "container removed"
else
    fail "container still exists after removal"
fi
dc up -d "$SERVICE"
if wait_healthy; then
    pass "new container is healthy"
else
    fail "new container did not become healthy"
fi

echo "--- 5. Check the data ---"
found="$(psql_q "SELECT count(*) FROM persistence_probe WHERE note = '$marker'")"
if [[ "$found" == "1" ]]; then
    pass "probe row survived container re-creation"
else
    fail "probe row was lost"
fi
after="$(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo 0)"
echo "chunks rows after: $after"
if [[ "$before" == "$after" ]]; then
    pass "chunk count unchanged"
else
    fail "chunk count changed"
fi

echo
if [[ $FAILED -eq 0 ]]; then
    echo "RESULT: PASS"
    echo "Next: sudo reboot, then run:  sudo ./tests/persistence-test.sh verify"
else
    echo "RESULT: FAIL"
fi
exit $FAILED
