# How the data tier fits together

For the VM boot sequence and Secret Manager wiring, see
[docs/startup.md](startup.md).

## Boot order

The startup scripts do this on every boot:

1. On `ada-ai`, `scripts/startup-ai.sh` installs Docker, mounts `/models` with
   `scripts/setup-lvm.sh`, stages missing model weights, and starts
   `deploy/ai.compose.yml`.
2. On `ada-edge`, `scripts/startup-edge.sh` installs Docker, mounts `/data/db`,
   reads `db-password` and `grafana-admin-password` from Secret Manager, writes
   an ignored `.env`, starts `deploy/edge.compose.yml` with three web replicas,
   and enables the autoscaler. The Compose `ingest` service runs
   `python -m ingest.ingest --if-empty`, so ingestion is conditional.

Each step checks before acting, so a reboot doesn't rebuild anything.

## Which files are for the deployed system

The deployed database is the `postgres` service in `deploy/edge.compose.yml`.
The app creates and fills its own `chunks` table (`ada/rag.py`,
`ingest/ingest.py`) from `corpus/` and `assets/skills/`.

`compose/docker-compose.db.yml`, `db/schema.sql`, `scripts/ingest.py`,
`scripts/deploy-data-tier.sh`, and `data/docs/` were built for a standalone
test VM before the app existed. They are not used by the startup scripts and
use a different table layout, so don't run them against the deployed database.

## What the others need

**Frank (infrastructure):** call `scripts/startup.sh edge` / `scripts/startup.sh ai`
from startup-script metadata. Attach a second disk with
`device_name = "data-disk"` (40 GB or more on the edge VM). Create the secrets
`db-password` and `grafana-admin-password` with `scripts/manage-secrets.sh`,
and let the VM's service account read them
(`roles/secretmanager.secretAccessor`).

**Tal (application):** the web services share the `database` network with the
`postgres` service in `deploy/edge.compose.yml`. Inside Docker the database is
`postgres:5432`, database `ragdb`, user `raguser`.

**Connor (AI):** run Ollama with its models on `/models` and have the
embedding model (`nomic-embed-text`, 768 dimensions) available before
ingestion runs.

## What Ty needs

- Frank: the VM names, zone, and project, so the evidence can be collected on
  the real stack.
- Connor and Tal: the final endpoint and model, so the smoke test matches.

## Collecting the evidence on the edge VM

Run these on `ada-edge` from `/opt/ada` (see `docs/startup.md` for how to
connect). Take a screenshot of each.

```
lsblk
sudo pvs; sudo vgs; sudo lvs
df -h /data/db
grep data/db /etc/fstab
sudo ./tests/persistence-test.sh           # then: sudo reboot
sudo ./tests/persistence-test.sh verify
sudo ./scripts/lvm-snapshot.sh create
sudo ./scripts/lvm-snapshot.sh list
sudo docker stats --no-stream
```

The smoke test runs from outside the VPC (Cloud Shell):

```
LB_URL=http://<edge-external-ip> ./tests/smoke-test.sh
```
