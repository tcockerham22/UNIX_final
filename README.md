# UNIX_final

COP 3604 final project: a containerized RAG app on Google Cloud. A load-balanced
web tier, CPU-only LLM inference, and a PostgreSQL + pgvector database, all
deployed with one command.

## Team

| Member | Role |
|---|---|
| Ty | Project lead + data management (database, ingestion, LVM, tests, report) |
| _name_ | Infrastructure and automation (Terraform, firewall, secrets, startup script, monitoring) |
| _name_ | Application deployment (web tier, load balancer, autoscaling, rate limiting) |
| Connor | AI platform (model, inference replicas, embeddings, AI tests) |

More detail in [docs/roles.md](docs/roles.md). Frank helped with the Phase 6
Terraform code.

## Layout

- `terraform/` - Phase 6 infrastructure code
- `deploy/` - Docker Compose and load balancer files
- `scripts/` - LVM, snapshot, ingestion and deploy scripts
- `db/` - database schema
- `data/docs/` - documents the RAG app searches
- `tests/` - test scripts; logs go in `tests/results/`
- `docs/` - roles, integration notes, report material

## Secrets

Nothing secret is committed. Passwords come from Secret Manager at deploy
time and `.env` files are ignored by Git. `terraform/terraform.tfvars.example`
contains only non-secret infrastructure settings.

## Deploy

See [terraform/README.md](terraform/README.md) for the Phase 6 apply sequence
and [docs/startup.md](docs/startup.md) for the VM boot behavior. The cloud page's
Metrics tab shows live replica, traffic, latency, resource, volume, and alert
data from Prometheus.
