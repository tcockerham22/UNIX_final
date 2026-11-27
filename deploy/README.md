# Ada cloud phases 2–4

These files implement the RAG application, container services, load balancing,
and web-tier scaling. The VM provisioning, LVM setup, firewall, and Secret
Manager wiring are now provided by `scripts/startup-*.sh` (see
`docs/startup.md`); do not expose Docker-published AI ports to the public
Internet.

## VM startup (phase 5)

`scripts/startup-edge.sh` installs Docker, creates `/data/db`, reads the
database and Grafana passwords from Secret Manager, writes an ignored `.env`,
and starts `edge.compose.yml` with three web replicas plus the autoscaler.
`scripts/startup-ai.sh` creates `/models`, stages missing weights, and starts
`ai.compose.yml`. Both are idempotent and can be invoked through
`scripts/startup.sh <edge|ai>` from GCP startup-script metadata.

## RAG application

The ingester reads Markdown from `corpus/` and `assets/skills/`, splits it near
headings into overlapping passages, embeds them with local Ollama
`nomic-embed-text`, and stores 768-dimensional vectors in PostgreSQL with
pgvector. `ON CONFLICT DO NOTHING` makes repeated ingestion safe. The current
repository corpus and skills produce at least 25 chunks.

For a local cloud-profile setup, ensure PostgreSQL has the pgvector extension,
Ollama is running, and both `ADA_CLOUD_MODEL` (default `qwen2.5:3b`) and
`nomic-embed-text` are available. Then set `ADA_PROFILE=cloud` and
`ADA_DATABASE_URL`, and run:

```sh
python -m ingest.ingest --if-empty
```

The chat UI sends `POST /api/rag/chat`. Its server-sent events stream retrieved
source metadata and answer tokens, and save source citations with the chat
history. `GET /api/rag/status` reports the number of indexed passages.

## Container topology

On `ada-ai`, pre-stage both required Ollama models under the model volume, set
`ADA_AI_BIND_IP` to the VM's private VPC address, and start:

```sh
docker compose -f deploy/ai.compose.yml up -d --build
```

Ollama itself has no published host ports. Each readiness shim publishes one
private-IP-bound port, proxies requests to its Ollama service, and reports
healthy only after a short chat prompt succeeds and the configured model is
loaded. The two shims use ports 11434 and 11435.

On `ada-edge`, provide values through the environment or an ignored local
environment file: `ADA_AI_PRIVATE_IP`, `ADA_DATABASE_URL`,
`POSTGRES_PASSWORD`, and `GRAFANA_ADMIN_PASSWORD`. Point `ADA_DB_DATA` at the
database logical volume (`/data/db`). Start the services with at least three
web replicas:

```sh
docker compose -f deploy/edge.compose.yml up -d --build --scale ada-web=3
```

Only HAProxy publishes port 80. The database is on an internal-only Compose
network and has no host port. HAProxy publishes its statistics endpoint,
Prometheus, and Grafana only on loopback. Restrict VPC ingress to the public
HTTP/HTTPS ports and the explicitly required private VM traffic; complete
firewall and TLS configuration in the Terraform phase.

All service images use explicit version tags. Compose applies CPU and memory
limits. Initial AI limits are two CPUs and 5 GiB per Ollama replica; tune them
from observed model memory, KV-cache size, and load-test results rather than
assuming these are final production values.

## HAProxy and autoscaling

HAProxy resolves up to six `ada-web` service addresses through Docker DNS,
actively checks `/healthz`, and routes internal inference requests to the two
private readiness-shim ports. Responses from the RAG endpoint are streamed
without proxy buffering. Requests to `/api/chat` and `/api/rag/chat` are
rate-limited per source address; excess requests receive HTTP 429.

`deploy/autoscaler.py` reads HAProxy's backend request rate and scales the web
service between three and six replicas. It scales up above 12 requests/second,
and scales down one replica only after the load remains below 2 requests per
second for five minutes. Install `deploy/ada-autoscaler.service` on `ada-edge`
as `/etc/systemd/system/ada-autoscaler.service`; the service expects the project
at `/opt/ada` and the `ada` user to have Docker Compose access. Start it with:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ada-autoscaler.service
```

Prometheus scrapes node-exporter, cAdvisor, and the HAProxy exporter. Detailed
application histograms, alert rules, and Grafana dashboards are completed in
the observability phase.
