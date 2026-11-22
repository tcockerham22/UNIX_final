# How the data tier fits together

## Boot order

The startup script (Member 2) should do, on every boot:

1. Install Docker if it's missing.
2. Run `scripts/deploy-data-tier.sh`, which does:
   1. `scripts/setup-lvm.sh` to create and mount `/data/db` and `/models`
   2. get `DB_PASSWORD` from Secret Manager (secret name `db-password`)
   3. `docker compose -f compose/docker-compose.db.yml up -d`
   4. wait for the database health check
   5. `scripts/ingest.py --if-empty` once the embedding service answers
3. Start the inference, web and load balancer containers.

Each step checks before acting, so a reboot doesn't rebuild anything.

## What the others need

**Member 2:** call the deploy script. Attach a second disk of 40 GB or more
with `device_name = "data-disk"`. Create a secret named `db-password` and let
the VM's service account read it (`roles/secretmanager.secretAccessor`).

**Member 3:** put the web services on the same Docker network as the
database. Either merge the `db` service into the main Compose file or use
Compose `include:` with the same network name. Inside Docker the database is
`db:5432`, database `ragdb`, user `raguser`.

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
