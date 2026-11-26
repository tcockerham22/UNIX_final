# Restoring the database volume from a snapshot

This overwrites everything written after the snapshot was taken. Try it on a
test VM first.

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
   sudo -E docker compose -f compose/docker-compose.db.yml stop db
   sudo umount /data/db
   sudo lvconvert --merge /dev/vg_data/lv_db_snap_YYYYMMDD_HHMMSS
   sudo mount /data/db
   sudo -E docker compose -f compose/docker-compose.db.yml start db
   ```
   If the merge is delayed because the volume is in use, make sure
   `findmnt /data/db` prints nothing and try again. Otherwise it finishes the
   next time the volume group is activated (for example after a reboot).

4. Check:
   ```
   docker ps
   docker exec rag-db psql -U raguser -d ragdb -c "SELECT count(*) FROM chunks;"
   ```

Notes:
- The merge uses up the snapshot.
- A snapshot is crash-consistent, so Postgres replays its log on the first
  start. A recovery message in `docker logs rag-db` is normal.
- Snapshots live on the same disk as the original, so this is a rollback
  point, not a backup. Check the `Snap%` column in the list output and remove
  old snapshots before they fill up.
