#!/usr/bin/env bash
# Sets up LVM on the extra data disk. Safe to run more than once: each step
# is skipped if it was already done.
#
#   lv_db      -> /data/db   (postgres data goes in /data/db/pgdata)
#   lv_models  -> /models
#
# Run as root. Override settings with env vars, e.g.
#   sudo DATA_DISK=/dev/sdb LV_DB_SIZE=8G ./scripts/setup-lvm.sh
#
# DATA_DISK defaults to the GCP disk with device name "data-disk".
# The LVs don't use the whole disk; the leftover space is for snapshots.

set -euo pipefail

DATA_DISK="${DATA_DISK:-/dev/disk/by-id/google-data-disk}"
VG_NAME="${VG_NAME:-vg_data}"
LV_DB_NAME="${LV_DB_NAME:-lv_db}"
LV_MODELS_NAME="${LV_MODELS_NAME:-lv_models}"
LV_DB_SIZE="${LV_DB_SIZE:-10G}"
LV_MODELS_SIZE="${LV_MODELS_SIZE:-15G}"
DB_MOUNT="${DB_MOUNT:-/data/db}"
MODELS_MOUNT="${MODELS_MOUNT:-/models}"

log() { echo "[setup-lvm] $*"; }
die() { echo "[setup-lvm] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)"

if ! command -v pvcreate >/dev/null 2>&1; then
    log "installing lvm2"
    apt-get update -y
    apt-get install -y lvm2
fi

[[ -b "$DATA_DISK" ]] || die "data disk not found at $DATA_DISK (check Terraform device_name or set DATA_DISK)"
REAL_DISK="$(readlink -f "$DATA_DISK")"

# 1. Physical volume
if pvs "$REAL_DISK" >/dev/null 2>&1; then
    log "physical volume on $REAL_DISK already exists"
else
    log "creating physical volume on $REAL_DISK"
    pvcreate "$REAL_DISK"
fi

# 2. Volume group
if vgs "$VG_NAME" >/dev/null 2>&1; then
    log "volume group $VG_NAME already exists"
else
    log "creating volume group $VG_NAME"
    vgcreate "$VG_NAME" "$REAL_DISK"
fi

# 3. Logical volumes
ensure_lv() {
    local name="$1" size="$2"
    if lvs "$VG_NAME/$name" >/dev/null 2>&1; then
        log "logical volume $name already exists"
    else
        log "creating logical volume $name ($size)"
        lvcreate -L "$size" -n "$name" "$VG_NAME"
    fi
}
ensure_lv "$LV_DB_NAME" "$LV_DB_SIZE"
ensure_lv "$LV_MODELS_NAME" "$LV_MODELS_SIZE"

# 4. Filesystem, fstab entry, and mount for each LV
ensure_mount() {
    local name="$1" mount_point="$2" label="$3"
    local dev="/dev/$VG_NAME/$name"

    if blkid "$dev" >/dev/null 2>&1; then
        log "$dev already has a filesystem"
    else
        log "formatting $dev as ext4"
        mkfs.ext4 -L "$label" "$dev"
    fi

    local uuid
    uuid="$(blkid -s UUID -o value "$dev")"
    if grep -qsE "[[:space:]]${mount_point}[[:space:]]" /etc/fstab; then
        log "/etc/fstab already has an entry for $mount_point"
    else
        log "adding /etc/fstab entry for $mount_point"
        echo "UUID=${uuid} ${mount_point} ext4 defaults,nofail 0 2" >> /etc/fstab
        systemctl daemon-reload 2>/dev/null || true
    fi

    mkdir -p "$mount_point"
    if mountpoint -q "$mount_point"; then
        log "$mount_point already mounted"
    else
        log "mounting $mount_point"
        mount "$mount_point"
    fi
}
ensure_mount "$LV_DB_NAME" "$DB_MOUNT" "rag_db"
ensure_mount "$LV_MODELS_NAME" "$MODELS_MOUNT" "rag_models"

# 5. PostgreSQL data directory (a subfolder, because a new ext4 root contains
#    lost+found and Postgres refuses to initialize in a non-empty directory)
mkdir -p "$DB_MOUNT/pgdata"

# 6. Report
log "done. Summary:"
vgs -o vg_name,vg_size,vg_free "$VG_NAME"
lvs -o lv_name,lv_size,lv_path "$VG_NAME"
df -h "$DB_MOUNT" "$MODELS_MOUNT"

free_bytes="$(vgs --noheadings --units b --nosuffix -o vg_free "$VG_NAME" | tr -d ' ')"
if (( free_bytes < 2147483648 )); then
    log "WARNING: less than 2 GiB free in $VG_NAME; snapshots need free space"
fi
