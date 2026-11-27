# Phase 5: VM boot, persistent volumes, and secrets

These scripts make a VM boot into a working Ada tier without manual steps, and
make a second boot change nothing. They are designed to be called from the
GCP startup-script metadata created by the Phase 6 Terraform configuration.

## Roles

| VM | Entry point | What it starts |
|---|---|---|
| `ada-edge` | `scripts/startup-edge.sh` | `/data/db` LVM, edge Compose stack, autoscaler |
| `ada-ai` | `scripts/startup-ai.sh` | `/models` LVM, staged models, inference Compose stack |

`scripts/startup.sh <edge|ai>` is the single dispatcher. It can read the role
from the instance metadata attribute `ada-role` or from the hostname, so a
startup-script metadata body only needs:

```sh
#!/bin/bash
cd /opt/ada && sudo ./scripts/startup.sh
```

Set these instance metadata attributes before first boot:

| Key | `ada-edge` | `ada-ai` |
|---|---|---|
| `ada-role` | `edge` | `ai` |
| `ada-ai-ip` | private IP of `ada-ai` | not needed |
| `startup-script` | the script above | the script above |

For example, after creating the startup-script body in a local file:

```sh
gcloud compute instances add-metadata ada-edge --zone=YOUR_ZONE \
  --metadata=ada-role=edge,ada-ai-ip=10.0.0.3 \
  --metadata-from-file=startup-script=/tmp/ada-startup.sh
gcloud compute instances add-metadata ada-ai --zone=YOUR_ZONE \
  --metadata=ada-role=ai \
  --metadata-from-file=startup-script=/tmp/ada-startup.sh
```

The edge script needs `ada-ai-ip` so HAProxy can reach the AI readiness shims;
it deliberately does not use the edge VM's own address.

## One-time secret setup

Run this once from a machine with Secret Manager Admin rights, before booting
the VMs. It creates secrets only if they do not already exist. If the API is not
enabled, `manage-secrets.sh` enables it for you and waits for it to propagate;
you can also do that manually:

```sh
gcloud services enable secretmanager.googleapis.com --project=YOUR_PROJECT_ID
```

Then create and grant access to the secrets:

```sh
./scripts/manage-secrets.sh ensure db-password
./scripts/manage-secrets.sh ensure grafana-admin-password
./scripts/manage-secrets.sh grant db-password MEMBER
./scripts/manage-secrets.sh grant grafana-admin-password MEMBER
```

Replace `MEMBER` with the real email of each VM's attached service account, or
with your own user email for local testing. The script detects the IAM member
type automatically: addresses ending in `.gserviceaccount.com` become
`serviceAccount:...`, other email addresses become `user:...`, and explicit
prefixes such as `user:`, `serviceAccount:`, `group:`, or `domain:` are kept as
written. List service accounts with:

```sh
gcloud iam service-accounts list --project=YOUR_PROJECT_ID
```

The default compute service account is only suitable for a test project; the
Terraform configuration creates a dedicated `ada-vm` service account.

`ensure` generates a random hex password when no value is supplied. To choose
one explicitly, set `SECRET_VALUE` in the environment rather than on the
command line. Both VMs use the attached service account, so only
`roles/secretmanager.secretAccessor` is needed at boot.

The VM-side reader is `scripts/get-secret.sh`. It uses the metadata service and
the Secret Manager REST API, which means gcloud does not have to be installed
on the VMs.

## What the edge script does

1. Installs Docker Engine and the Compose plugin if missing, creates the `ada`
   service user, and enables Docker.
2. Runs `setup-lvm.sh` with `SETUP_MODELS=0`, creating `/data/db` on the
   attached disk. The PostgreSQL data directory is `/data/db/pgdata` so that a
   fresh ext4 volume's `lost+found` does not block initialization.
3. Reads `db-password` and `grafana-admin-password` from Secret Manager and
   writes a mode-600 `.env` file next to the repository. `ADA_DATABASE_URL`
   points at the Compose service name `postgres` and uses `raguser`/`ragdb` to
   match `db/schema.sql` and `scripts/ingest.py`.
4. Runs `docker compose -f deploy/edge.compose.yml up -d --build --scale
   ada-web=3`. The `ingest` service runs `python -m ingest.ingest --if-empty`,
   so an already-populated `chunks` table is left alone.
5. Installs `deploy/ada-autoscaler.service` and copies the Compose environment
   to `/etc/ada/cloud.env` with mode 0640 so the `ada` user can scale replicas.

## What the AI script does

1. Installs Docker as above.
2. Runs `setup-lvm.sh` with `SETUP_DB=0`, creating and mounting `/models`.
3. If `PRESTAGE_MODELS=1` (the default), starts a short-lived Ollama container
   with `/models` mounted read/write and pulls any missing weights. The
   containers in `ai.compose.yml` mount `/models` read-only and never download
   models during image build. Set `PRESTAGE_MODELS=0` when the volume is already
   staged from an image or snapshot.
4. Starts `deploy/ai.compose.yml` with the shims bound to the VM's private IP.
   It then waits for both readiness shims to pass a real model prompt, but only
   warns if a model is still warming up.

## Safe disk setup

`setup-lvm.sh` is idempotent:

- It creates the PV/VG/LVs only when they are absent.
- It formats a logical volume only when `blkid` finds no existing filesystem.
- It adds one `UUID=... /mount ext4 defaults,nofail 0 2` line per volume to
  `/etc/fstab` only when that line is missing.
- It mounts only when `mountpoint -q` says the directory is not already mounted.

Before running `pvcreate`, it refuses to touch a disk that already has a
filesystem or partitions. This prevents an accidental re-run from reformatting
a disk that was mounted earlier. Only set `ALLOW_WIPE=1` when wiping is the
explicit goal.

Both scripts set `SETUP_DB` or `SETUP_MODELS` to `0` so each VM creates only
the volume it needs. The full-disk defaults are unchanged for a manual run.

## Snapshots

`scripts/lvm-snapshot.sh create [size]` takes a crash-consistent snapshot of
`lv_db`. It first runs a PostgreSQL `CHECKPOINT` when the database container is
running. `list`, `mount`, `umount`, and `remove` are read-only or cleanup
operations; `remove` refuses names that do not contain `_snap_`. Restoring is
deliberately manual and documented in
[docs/restore-from-snapshot.md](restore-from-snapshot.md).

## Checking a boot

```sh
sudo tail -n 80 /var/log/ada-startup-edge.log
sudo tail -n 80 /var/log/ada-startup-ai.log
lsblk
sudo pvs && sudo vgs && sudo lvs
df -h /data/db /models
findmnt /data/db
grep -E 'data/db|models' /etc/fstab
docker ps
curl -fsS http://127.0.0.1/healthz || true
```

Then reboot and run the same commands again. The logs should say
`already exists` / `already installed` and no data should be recreated.

## Local testing without GCP

The startup scripts are for VMs. On a development machine, set the passwords
yourself and use the existing data-tier helper:

```sh
export DB_PASSWORD='local-test-password'
sudo -E ./scripts/deploy-data-tier.sh
sudo ./scripts/lvm-snapshot.sh create
```
