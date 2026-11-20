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

More detail in [docs/roles.md](docs/roles.md).

## Layout

- `terraform/` - infrastructure code
- `compose/` - Docker Compose files
- `scripts/` - LVM, snapshot, ingestion and deploy scripts
- `db/` - database schema
- `data/docs/` - documents the RAG app searches
- `tests/` - test scripts; logs go in `tests/results/`
- `docs/` - roles, integration notes, report material

## Secrets

Nothing secret is committed. Passwords come from Secret Manager at deploy
time and `.env` files are ignored by Git. `compose/.env.example` only lists
the variable names.
