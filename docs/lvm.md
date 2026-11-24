# LVM layout

`scripts/setup-lvm.sh` builds this on the extra GCP disk:

| Layer | Name | Notes |
|---|---|---|
| Physical volume | the extra disk (`/dev/disk/by-id/google-data-disk`) | `pvcreate` |
| Volume group | `vg_data` | `vgcreate` |
| Logical volume | `lv_db` (10G), mounted at `/data/db` | postgres files in `/data/db/pgdata` |
| Logical volume | `lv_models` (15G), mounted at `/models` | LLM model files |
| Free space | the rest of the disk | for snapshots and growth |

Make the disk at least 40 GB so the volume group has free space left.

For Member 2 (Terraform): attach the disk with `device_name = "data-disk"` so
the path above exists. If you use a different name, run the script with
`DATA_DISK=<path>`.

## Checking it (screenshots for the report)

```
lsblk
sudo pvs && sudo vgs && sudo lvs
df -h /data/db /models
findmnt /data/db
grep -E 'data/db|models' /etc/fstab
```

Run the script a second time. Every step should say "already exists". Then
reboot and run the commands again; both volumes should still be mounted.

## Careful

`pvcreate` wipes the device it's given. Check `lsblk` first if the machine
isn't brand new.
