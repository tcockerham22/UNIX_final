#!/usr/bin/env bash
# Checks that database data survives a container re-create and a reboot.
#
#   sudo -E ./tests/persistence-test.sh          (down/up test)
#   sudo -E ./tests/persistence-test.sh verify   (run after rebooting the VM)
#
# Run from the repo root with DB_PASSWORD exported. The output is also saved
# in tests/results/ (commit it).
#
# It checks that /data/db is an LVM mount, then that a test row written to the
# database is still there after `docker compose down` + `up`, and after a reboot.

set -uo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose/docker-compose.db.yml}"
DB_CONTAINER="${DB_CONTAINER:-rag-db}"
DB_MOUNT="${DB_MOUNT:-/data/db}"
MARKER_FILE="${MARKER_FILE:-/var/tmp/persistence_probe_marker}"
MODE="${1:-run}"

mkdir -p tests/results
LOG="tests/results/persistence-$(date +%Y%m%d-%H%M%S)-${MODE}.log"
exec > >(tee -a "$LOG") 2>&1

FAILED=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILED=1; }
psql_q() { docker exec "$DB_CONTAINER" psql -U raguser -d ragdb -tAc "$1"; }

wait_healthy() {
    for _ in $(seq 1 60); do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null || echo missing)"
        [[ "$status" == "healthy" ]] && return 0
        sleep 2
    done
    return 1
}

echo "=== Persistence test ($MODE) ==="
echo "date:     $(date -Is)"
echo "host:     $(hostname)"
echo

[[ -n "${DB_PASSWORD:-}" ]] || { echo "DB_PASSWORD must be exported"; exit 2; }

echo "--- 1. Storage ---"
findmnt -no SOURCE,FSTYPE,TARGET "$DB_MOUNT" || true
if findmnt -n "$DB_MOUNT" | grep -q "/dev/mapper/vg_data"; then
    pass "$DB_MOUNT is mounted from an LVM logical volume"
else
    fail "$DB_MOUNT is not an LVM mount"
fi

if [[ "$MODE" == "verify" ]]; then
    echo "--- 2. After reboot ---"
    wait_healthy && pass "database container is healthy (restart policy worked)" \
                 || fail "database container did not become healthy"
    marker="$(cat "$MARKER_FILE" 2>/dev/null || true)"
    [[ -n "$marker" ]] || { fail "no marker file at $MARKER_FILE; run the default test first"; exit 1; }
    found="$(psql_q "SELECT count(*) FROM persistence_probe WHERE note = '$marker'")"
    [[ "$found" == "1" ]] && pass "probe row '$marker' survived the reboot" \
                          || fail "probe row '$marker' missing after reboot"
    echo "chunks rows: $(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo 'n/a')"
    echo
    [[ $FAILED -eq 0 ]] && echo "RESULT: PASS" || echo "RESULT: FAIL"
    exit $FAILED
fi

echo "--- 2. Write a probe row ---"
wait_healthy || { fail "database not healthy before test"; exit 1; }
marker="probe-$(date +%s)"
psql_q "CREATE TABLE IF NOT EXISTS persistence_probe (note text, created timestamptz DEFAULT now())" >/dev/null
psql_q "INSERT INTO persistence_probe (note) VALUES ('$marker')" >/dev/null
echo "$marker" > "$MARKER_FILE"
echo "wrote $marker"
before_chunks="$(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo 0)"
echo "chunks rows before: $before_chunks"

echo "--- 3. Remove and re-create the container ---"
docker compose -f "$COMPOSE_FILE" down
docker ps -a --format '{{.Names}}' | grep -qx "$DB_CONTAINER" && fail "container still exists after down" || pass "container removed"
docker compose -f "$COMPOSE_FILE" up -d
wait_healthy && pass "new container is healthy" || fail "new container did not become healthy"

echo "--- 4. Check the data ---"
found="$(psql_q "SELECT count(*) FROM persistence_probe WHERE note = '$marker'")"
[[ "$found" == "1" ]] && pass "probe row survived container re-creation" || fail "probe row lost"
after_chunks="$(psql_q 'SELECT count(*) FROM chunks' 2>/dev/null || echo 0)"
echo "chunks rows after: $after_chunks"
[[ "$before_chunks" == "$after_chunks" ]] && pass "chunk count unchanged" || fail "chunk count changed"

echo
if [[ $FAILED -eq 0 ]]; then
    echo "RESULT: PASS"
    echo "Next: sudo reboot, then run:  sudo -E ./tests/persistence-test.sh verify"
fi
[[ $FAILED -eq 0 ]] || echo "RESULT: FAIL"
exit $FAILED
