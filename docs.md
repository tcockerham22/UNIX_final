# Ada cloud edition: project guide and implementation status

This document records the current project architecture, the work completed so
far, how to run the local cloud profile, and what remains from the university
assignment. It is written for teammates who need to understand and explain the
system.

## Project goal and constraints

Ada began as a local Python assistant with Ollama chat, a dashboard, memories,
skills, tools, and optional voice and smart-home integrations. The cloud edition
is being developed as a separate profile for a university sysadmin project:

- Keep the existing local profile as the default.
- Run cloud web, database, inference, and operations components in containers.
- Use a self-hosted CPU Ollama model and local Ollama embeddings; do not call
  external LLM APIs.
- Store RAG passages and embeddings in PostgreSQL with pgvector.
- Show the retrieved sources with each RAG answer.
- Put the public web load balancer on an edge VM and Ollama on a separate AI VM.
- Keep inference and PostgreSQL ports private, and never commit real secrets.
- Use readable, straightforward code that teammates can explain.

Work was initially requested in phases with approval between phases. The owner
has since asked to proceed through phases 2, 3, and 4 together, and Phase 5 has
now been added. The status below reflects that scope. Phase 6 Terraform code
has been added; Phases 7–9 have not been implemented.

## Current status

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit the existing local application and plan the conversion | Completed earlier |
| 1 | Cloud profile, PostgreSQL state, cloud chat page, health endpoint | Implemented earlier; locally tested |
| 2 | Corpus, chunking, Ollama embeddings, pgvector retrieval, cited streaming chat | Implemented in this work |
| 3 | Web, database, inference, readiness shim, and monitoring containers | Implemented and deployed manually |
| 4 | HAProxy, rate limiting, Prometheus exporter, web autoscaler | Implemented and running on the edge VM |
| 5 | LVM, startup scripts, Secret Manager retrieval, snapshots | Implemented and running; Terraform apply pending |
| 6 | Terraform network, firewalls, VMs, disks, service account, secrets | Terraform code added; apply pending |
| 7 | Application metrics, alert rules, production Grafana dashboards | Partial infrastructure only; not complete |
| 8 | Smoke, load, failover, and rate-limit test harness | Not implemented |
| 9 | Demo, full deployment guide, memory worksheet, citations | Not implemented; this file is a status/engineering guide, not the final assignment README |

## Phase 0 findings

- The existing dashboard is served by Python's standard-library
  `ThreadingHTTPServer` in `ada/web.py`.
- The original dashboard is a local telemetry/orb interface, not the cloud chat
  UI. The cloud profile has its own files in `web/cloud.html`, `web/cloud.css`,
  and `web/cloud.js`.
- The original local assistant streams process events to the browser with
  server-sent events. Local CLI chat also consumes Ollama output directly. The
  cloud chat has a JSON API for its older chat route and now has a distinct
  server-sent-events route for RAG answers.
- Local memories and uploads historically used JSON/files. The cloud profile
  stores chat history, memories, and uploaded files in PostgreSQL.
- Local model tiers, voice, microphone, wake word, Piper, Home Assistant,
  display modes, shell/command/file tools, and sub-agents are machine-specific
  or unsafe to expose in the cloud web tier. Cloud config disables the local
  integrations and limits tools to safe memory/time functions.
- `Config.load()` reads `config.json` when it exists, applies `ADA_*`
  environment overrides, then applies the cloud profile restrictions. The
  profile remains `local` unless `ADA_PROFILE=cloud` is set.
- `start.sh` remains the local assistant CLI launcher. `start-cloud.sh` is a
  separate web-only launcher for a local development setup.

## Phase 1 behavior carried forward

`ADA_PROFILE=cloud`:

- Uses one configured Ollama chat model for the model tiers.
- Disables local-only voice, wake-word, Home Assistant, sub-agent, and unsafe
  tool integrations.
- Uses PostgreSQL for shared chat history, memories, and session uploads.
- Serves the cloud chat UI and same-origin upload/chat APIs.
- Serves `/healthz` and adds `X-Served-By` to responses.
- Leaves the local profile as the default.

The cloud chat session is identified by an opaque `ada_session` cookie. It is
HTTP-only and same-site. Do not copy session cookies into logs or reports.

## Phase 2: RAG implementation

### Corpus and chunking

- `corpus/` contains reference documents with known facts for smoke testing.
- `assets/skills/*.md` are ingested alongside the new corpus.
- `ada/rag.py` splits Markdown near headings, carries heading context into
  chunks, and uses an approximate 450-token ceiling with about 60 tokens of
  overlap. A lightweight word-and-punctuation token counter avoids adding a
  tokenizer dependency.
- Each chunk has a SHA-256 ID derived from source, chunk index, and content,
  plus a separate SHA-256 content hash.
- The current corpus and skills produce at least 25 chunks; the current test
  run measures 89 chunks.

### Embedding database and retrieval

- Embeddings use the local Ollama model `nomic-embed-text`; each vector is
  validated to contain 768 dimensions.
- PostgreSQL installs the `vector` extension and stores passages in a
  `chunks` table with an HNSW cosine-distance index.
- Inserts use `ON CONFLICT (id) DO NOTHING`, so a repeated ingestion does not
  create duplicate rows.
- Retrieval embeds the question locally and selects the nearest four passages
  by cosine distance (with a hard maximum of ten).
- `ingest/ingest.py` reads `corpus/` and `assets/skills/`. Run it manually with
  `python -m ingest.ingest`; `--if-empty` skips the initial corpus load when
  any chunk already exists.

### Chat, streaming, and citations

- `POST /api/rag/chat` retrieves passages, builds a prompt that treats
  retrieved text as untrusted data, and streams answer tokens as server-sent
  events.
- The stream includes source metadata and an end event containing the answer
  and source list.
- The UI displays corpus filenames and chunk numbers and stores citations with
  assistant history so they remain visible after reload.
- Readable uploaded text, `.docx`, and text-bearing `.pdf` content is included
  as session context. When an upload is present it becomes the primary source
  for that session, so unrelated corpus chunks are not mixed into the answer;
  the source is shown as `Uploaded session documents`.
- `GET /api/rag/status` reports the number of indexed passages.
- The legacy `POST /api/chat` endpoint remains available for compatibility.
  The cloud chat UI uses the RAG endpoint.

The RAG route requires the pgvector schema and locally available embedding and
chat models. For an empty database, ingest the corpus before asking questions.

## Phase 3: container definitions

### Web image

- The root `Dockerfile` uses a version-tagged Python base image.
- Web dependencies are separately pinned in `requirements-web.txt`; audio and
  local desktop packages are not installed into the web image.
- The application runs as an unprivileged `ada` user.
- `.dockerignore` excludes `.env`, Git state, local environments, uploads,
  generated data, Terraform state, and key files from the build context.

### Edge Compose file

`deploy/edge.compose.yml` defines:

- HAProxy for public HTTP, internal Ollama proxying, and stats.
- The `ada-web` service, scaled from three to six containers by the operator
  or autoscaler.
- A `pgvector/pgvector` PostgreSQL container with no published database port
  and data bind-mounted at `/data/db` by default.
- An idempotent initial corpus-ingestion service.
- Prometheus, Grafana, node-exporter, cAdvisor, and the HAProxy exporter.

PostgreSQL is attached to a Docker `internal: true` network. The web service is
attached to both that database network and the application network. Grafana
and Prometheus host ports are bound to loopback; only HAProxy publishes public
HTTP port 80. TLS/public port 443 still needs to be configured in a later
deployment phase.

### AI Compose file and readiness shim

`deploy/ai.compose.yml` defines two Ollama containers and one readiness proxy
per model replica:

- Ollama containers have no published ports and share a read-only mount of the
  pre-staged `/models` directory.
- Each replica is limited to two CPUs and 5 GiB of memory.
- `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_KEEP_ALIVE=-1` are set.
- The readiness shim proxies API traffic and publishes only 11434/11435 on
  the configured AI VM private address.
- The shim periodically sends a short local prompt and verifies the configured
  model is loaded. It answers `/ready` with 200 only after a successful check
  within the last 30 seconds; otherwise it returns 503.

The default model directory is `/models`; the Phase 5 AI startup script creates
that LVM mount and stages any missing model weights. Neither model is
downloaded during image build.

### Container limits and unverified operations

Every defined Compose service has CPU and memory resource limits. Ollama's
initial limit is 2 CPUs and 5 GiB per replica; these are starting values, not
measured production sizing. Tune them using model weights, context/KV cache,
system overhead, and measured load.

The Docker daemon is unavailable in the current development environment, so
images have not been built or started. Compose syntax/configuration was
validated with dummy values, but image pulls, startup, actual Postgres/vector
integration, and inter-VM connectivity remain unverified.

## Phase 4: load balancing and scaling

- The HAProxy frontend resolves up to six web containers through Docker DNS
  and actively health-checks `/healthz`.
- Inference traffic from web and ingestion containers goes through HAProxy to
  the AI VM's two private readiness-shim ports.
- Server and client timeouts are long enough for inference responses. The RAG
  handler emits SSE events and HAProxy is not configured to buffer responses.
- `/api/chat` and `/api/rag/chat` requests are rate-limited per source address;
  excess traffic receives HTTP 429.
- HAProxy exposes a private stats page and the HAProxy Prometheus exporter.
- `deploy/autoscaler.py` polls HAProxy backend request rate, scales up one
  replica above 12 requests/second, and scales down one replica only after
  load remains below 2 requests/second for five minutes. Limits are three to
  six replicas.
- `deploy/ada-autoscaler.service` runs the scaler as a systemd service. Its
  expected project path is `/opt/ada`; the `ada` system user must have Docker
  Compose access.

This scaler uses HTTP request rate as its initial load signal. Production
tuning should combine request rate, backend queue/latency, CPU, and inference
capacity after collecting real measurements.

## Running a local cloud profile

The project has two distinct entry points:

- Local assistant: `./start.sh`
- Local cloud-profile web server: `./start-cloud.sh`

For the local cloud profile:

1. Start a PostgreSQL server that has the pgvector extension available. The
   standard `postgres` image does not include that extension; use the pinned
   `pgvector/pgvector` image or install pgvector in your PostgreSQL server.
2. Ensure Ollama is running and has the configured chat model plus
   `nomic-embed-text`. For a local-only development machine, these can be
   fetched with `ollama pull <model>`; cloud deployment must pre-stage model
   weights instead of downloading them during image build.
3. Copy `.env.example` to `.env` and set `ADA_DATABASE_URL` to your own local
   PostgreSQL URL. `.env` is ignored by Git and must never be committed.
4. Run `./start-cloud.sh`. It checks PostgreSQL and Ollama, ingests the corpus
   if the vector table is empty, then starts the web server at
   `http://127.0.0.1:8765/`.

The local script's PostgreSQL URL uses the database's local connection
credentials. The edge Compose stack instead needs a URL whose database host
is the Compose service name `postgres`, as well as `POSTGRES_PASSWORD` and
`GRAFANA_ADMIN_PASSWORD`. The Phase 5 edge startup script reads these from GCP
Secret Manager and writes an ignored `.env` file at boot; do not commit them to
`.env`, Compose files, or this documentation.

If `nomic-embed-text` or the chat model is missing, the launcher exits and
prints the relevant `ollama pull` command. If PostgreSQL is unreachable, fix
the URL or start the server before retrying. If the vector extension is not
installed, the ingestion error will identify that database prerequisite.

## Important files

| Path | Purpose |
|---|---|
| `ada/config.py` | Profile, local defaults, and environment-driven cloud settings |
| `ada/web.py` | Local and cloud HTTP handlers, chat routes, streaming SSE, uploads |
| `ada/cloud_state.py` | PostgreSQL chat history, memories, uploads, and citations |
| `ada/documents.py` | Readable-text, `.docx`, and `.pdf` extraction (pypdf with `pdftotext` fallback) |
| `ada/rag.py` | Markdown chunking, Ollama embeddings, pgvector schema and retrieval |
| `corpus/` | Smoke-test facts and reference material |
| `assets/skills/` | Existing Ada Markdown skills included in ingestion |
| `ingest/ingest.py` | Idempotent corpus loader |
| `scripts/setup-lvm.sh` | Idempotent PV/VG/LV, fstab, and mount setup |
| `scripts/install-docker.sh` | Idempotent Docker and Compose installation |
| `scripts/manage-secrets.sh`, `scripts/get-secret.sh` | One-time secret creation and VM-side retrieval |
| `scripts/startup.sh`, `scripts/startup-edge.sh`, `scripts/startup-ai.sh` | Role-based VM boot scripts |
| `scripts/lvm-snapshot.sh` | Database snapshot helper |
| `docs/startup.md` | Phase 5 boot, storage, and secret guide |
| `web/cloud.html`, `web/cloud.css`, `web/cloud.js` | Cloud chat page, sources, file upload, and SSE client |
| `Dockerfile`, `requirements-web.txt` | Non-root web image and pinned web dependencies |
| `deploy/edge.compose.yml` | Edge VM services and monitoring |
| `deploy/ai.compose.yml` | Two-replica AI VM services |
| `deploy/ready_shim.py` | Model-aware readiness and streaming Ollama proxy |
| `deploy/haproxy/` | Public web and private inference routing |
| `deploy/autoscaler.py` | HAProxy-driven 3–6 web replica scaling |
| `deploy/ada-autoscaler.service` | systemd unit for the autoscaler |
| `deploy/prometheus.yml` | Initial host/container/HAProxy scrape targets |
| `tests/test_rag.py`, `tests/test_deploy.py`, `tests/test_phase5.py` | RAG, deployment, and boot-script checks |

## Validation and repository state

The project test suite covers the existing local behavior and the cloud profile,
RAG chunking/IDs/embeddings/retrieval, source-stream persistence, the readiness
probe, autoscaler decisions, and static checks for the Phase 5 boot scripts. The
Compose files are checked with `docker compose config`; Python, JavaScript, and
shell syntax are checked separately.

The repository already had unrelated uncommitted changes before phases 2–4.
Those changes have been preserved. No GitHub push has been made, and no
commit has been created because staging shared dirty files would risk bundling
unrelated work.

## Phase 6 Terraform

`terraform/` now declares the dedicated VPC and subnet, Cloud NAT, public HTTP
and IAP SSH firewalls, two VMs with LVM-ready data disks, a least-privilege
service account, Secret Manager secrets and access grants, and startup-script
metadata. `terraform/terraform.tfvars.example` is safe to commit; real passwords
are generated into Secret Manager and never written into tracked files. Frank
helped with this Phase 6 code.

The configuration has not been applied yet. The existing manual deployment
still uses the default VPC and the default compute service account, so a
Terraform apply creates a parallel stack with the `-tf` names in the example
tfvars. See [terraform/README.md](terraform/README.md) for import notes and the
apply sequence.

## Remaining phases

### Phase 7: observability

The initial Prometheus, Grafana, node-exporter, cAdvisor, and HAProxy exporter
containers exist. Still needed: Ada application request/error/latency metrics,
time-to-first-token and tokens-per-second metrics, per-volume metrics and
dashboards, provisioning improvements, and alerts for replica health and
volumes above 80%.

### Phase 8: test harness

Still needed: `tests/run_tests.sh`, timestamped logs, smoke/load/failover/rate
limit tests, result charts, and explicit opt-in flags for disruptive tests.

### Phase 9: demos and final hand-in documentation

Still needed: the OOM demonstration and recovery, final README architecture and
single-command Terraform guide, model memory-sizing worksheet, model/image
citations and licenses, and optional local-only read-only log triage.
