# Backups and LVM Snapshots

A backup is a copy of data that can be used to recover after a failure, a mistake, or an attack. Good backup practice asks three questions: how recent is the copy, where is it stored, and has the restore procedure ever been tested.

## LVM snapshots

An LVM snapshot is a point-in-time view of a logical volume. It is created with lvcreate and the snapshot option, for example lvcreate --snapshot --size 2G --name lv_db_snap /dev/vg_data/lv_db. The snapshot uses copy-on-write: when a block on the original volume changes, the old version of that block is first saved into the snapshot's reserved space. Creating a snapshot is nearly instant because nothing is copied up front.

## Sizing and lifetime

The size given to a snapshot is the amount of space reserved for changed blocks, not the size of the original volume. If more data changes than the snapshot can hold, the snapshot becomes invalid. For that reason snapshots are meant to be short-lived. The command lvs shows how full a snapshot is in the Data percentage column. A snapshot that is no longer needed is removed with lvremove.

## Reading and restoring

A snapshot can be mounted read-only to inspect or copy old files without touching the original. To roll the original volume back, the administrator stops the services using it, unmounts it, and runs lvconvert --merge on the snapshot. The merge returns the original volume to the state captured by the snapshot and consumes the snapshot.

## Databases and consistency

A snapshot of a running database is crash-consistent: it looks like the database after a sudden power loss. PostgreSQL can recover from that state using its write-ahead log. Running a CHECKPOINT just before the snapshot reduces recovery work. For a logical backup that does not depend on the storage layer, pg_dump exports the database contents as SQL or an archive file.

## Snapshots are not a full backup

A snapshot lives on the same disk as the original data. If the disk fails, both are lost. A complete strategy also copies data to a different location, such as a Cloud Storage bucket, and tests restoring from that copy.
