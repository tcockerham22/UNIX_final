#!/usr/bin/env bash
# Snapshots of the database volume.
#
#   sudo ./scripts/lvm-snapshot.sh create [size]   (default 2G)
#   sudo ./scripts/lvm-snapshot.sh list
#   sudo ./scripts/lvm-snapshot.sh mount <snap>    (read-only, /mnt/snap)
#   sudo ./scripts/lvm-snapshot.sh umount
#   sudo ./scripts/lvm-snapshot.sh remove <snap>
#
# Restoring is not scripted because it overwrites data. See
# docs/restore-from-snapshot.md.

set -euo pipefail

VG_NAME="${VG_NAME:-vg_data}"
LV_DB_NAME="${LV_DB_NAME:-lv_db}"
SNAP_MOUNT="${SNAP_MOUNT:-/mnt/snap}"
DB_CONTAINER="${DB_CONTAINER:-rag-db}"

die() { echo "[lvm-snapshot] ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "run as root (sudo)"

cmd="${1:-}"
case "$cmd" in
    create)
        size="${2:-2G}"
        name="${LV_DB_NAME}_snap_$(date +%Y%m%d_%H%M%S)"
        # Best effort: flush PostgreSQL's dirty buffers so recovery is minimal.
        if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
            docker exec "$DB_CONTAINER" psql -U raguser -d ragdb -c "CHECKPOINT;" >/dev/null || true
        fi
        lvcreate --snapshot --size "$size" --name "$name" "/dev/$VG_NAME/$LV_DB_NAME"
        echo "created snapshot $name"
        ;;
    list)
        lvs -o lv_name,lv_size,origin,snap_percent,lv_time "$VG_NAME"
        ;;
    mount)
        snap="${2:-}"
        [[ -n "$snap" ]] || die "usage: mount <snapshot-name>"
        mkdir -p "$SNAP_MOUNT"
        mount -o ro "/dev/$VG_NAME/$snap" "$SNAP_MOUNT"
        echo "mounted $snap read-only at $SNAP_MOUNT"
        ;;
    umount)
        umount "$SNAP_MOUNT"
        ;;
    remove)
        snap="${2:-}"
        [[ "$snap" == *_snap_* ]] || die "refusing: '$snap' does not look like a snapshot name"
        lvremove -f "/dev/$VG_NAME/$snap"
        ;;
    *)
        sed -n '2,12p' "$0"
        exit 1
        ;;
esac
