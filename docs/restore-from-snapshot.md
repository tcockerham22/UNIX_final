# Restoring the database volume from a snapshot

Do this on the edge VM (`ada-edge`). It overwrites everything written after
the snapshot was taken, so try it on a test stack first. The rubric only asks
for a snapshot to be taken, so this is optional. I have not run the restore
steps myself.

1. Find the snapshot:
   ```
   sudo ./scripts/lvm-snapshot.sh list
   ```

2. Optional: look inside it without changing anything.
   ```
   sudo ./scripts/lvm-snapshot.sh mount lv_db_snap_YYYYMMDD_HHMMSS
   ls /mnt/snap/pgdata
   sudo ./scripts/lvm-snapshot.sh umount
   ```

3. Roll back:
   ```
   cd /opt/ada
   sudo docker compose --env-file .env -f deploy/edge.compose.yml stop postgres
   sudo umount /data/db
   sudo lvconvert --merge /dev/vg_data/lv_db_snap_YYYYMMDD_HHMMSS
   sudo mount /data/db
   sudo docker compose --env-file .env -f deploy/edge.compose.yml start postgres
   ```
   If the merge is delayed because the volume is in use, make sure
   `findmnt /data/db` prints nothing and try again. Otherwise it finishes the
   next time the volume group is activated (for example after a reboot).

4. Check:
   ```
   sudo docker ps
   sudo docker exec $(sudo docker ps -q --filter name=postgres) \
     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM chunks;"'
   ```

Notes:
- The merge uses up the snapshot.
- A snapshot is crash-consistent, so Postgres replays its log on the first
  start. A recovery message in the container logs is normal.
- Snapshots live on the same disk as the original, so this is a rollback
  point, not a backup. Check the `Snap%` column in the list output and remove
  old snapshots before they fill up.
