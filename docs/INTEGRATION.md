# How the data tier fits together

For the VM boot sequence and Secret Manager wiring, see
[docs/startup.md](startup.md).

## Boot order

The Phase 5 startup scripts do this on every boot:

1. On `ada-ai`, `scripts/startup-ai.sh` installs Docker, mounts `/models` with
   `scripts/setup-lvm.sh`, stages missing model weights, and starts
   `deploy/ai.compose.yml`.
2. On `ada-edge`, `scripts/startup-edge.sh` installs Docker, mounts `/data/db`,
   reads `db-password` and `grafana-admin-password` from Secret Manager, writes
   an ignored `.env`, starts `deploy/edge.compose.yml` with three web replicas,
   and enables the autoscaler. The Compose `ingest` service runs
   `python -m ingest.ingest --if-empty`, so ingestion is conditional.

`scripts/deploy-data-tier.sh` is the local/test variant. It starts
`compose/docker-compose.db.yml` and waits for a host-side Ollama endpoint. The
edge startup script does not run it because `edge.compose.yml` owns PostgreSQL
on an internal Compose network.

Each step checks before acting, so a reboot doesn't rebuild anything.

## What the others need

**Member 2:** call `scripts/startup.sh edge` / `scripts/startup.sh ai` from
startup-script metadata. Attach a second disk of 40 GB or more with
`device_name = "data-disk"`. Create secrets named `db-password` and
`grafana-admin-password` with `scripts/manage-secrets.sh`, and let the VM's
service account read them (`roles/secretmanager.secretAccessor`).

**Member 3:** the web services already share the `database` network with the
`postgres` service in `deploy/edge.compose.yml`. Inside Docker the database is
`postgres:5432`, database `ragdb`, user `raguser`.

**Member 4:** run Ollama with its models on `/models` and pull the embedding
model before ingestion runs (default `nomic-embed-text`, 768 dimensions).
Questions must be embedded with the prefix `search_query: ` and searched
against the `chunks` table:

```sql
SELECT source, content
FROM chunks
ORDER BY embedding <=> '[...768 numbers...]'::vector
LIMIT 4;
```

If the embedding model changes, update the vector size in `db/schema.sql`,
set `EMBED_DIM`, and set `EMBED_DOC_PREFIX` to an empty string if the model
doesn't use prefixes.

## What Member 1 needs

- Member 2: the VM, the extra disk, Docker, Secret Manager access.
- Member 4: the embedding endpoint and the final model choice.
- Member 3: the load balancer address and the format of the question/answer
  endpoint (for the smoke test).

## Still to decide as a group

- The final document set (replace the files in `data/docs/` if wanted).
- The embedding model.
- A single Compose project name so the `backend` network is named the same
  for everyone.

## Running it by hand the first time

```
export DB_PASSWORD='something-for-testing'
sudo -E ./scripts/deploy-data-tier.sh      # first run creates everything
sudo -E ./scripts/deploy-data-tier.sh      # second run changes nothing
sudo -E ./tests/persistence-test.sh        # then reboot, then run it with: verify
sudo ./scripts/lvm-snapshot.sh create
```
