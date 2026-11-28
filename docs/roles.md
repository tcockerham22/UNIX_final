# Roles

The spec has five roles. With four people, project lead is combined with data
management.

| Member | Owns |
|---|---|
| Ty: Lead + data | Repo and task tracking, budget alert, database, ingestion, LVM and snapshot, persistence proof, smoke test, test logs, report and video |
| Frank: Infrastructure | GCP project, VPC, firewall, IAP SSH, IAM, Terraform, Secret Manager, startup script, Prometheus/Grafana, alert |
| Tal: Application | Web app, web-tier Compose, 3-6 replicas and autoscaling, load balancer, rate limiting (429), graceful degradation, front-end load test |
| Connor: AI | Model choice, inference replicas, readiness checks, embeddings, RAG query service, memory sizing, OOM demo, AI metrics, AI load and failover tests, log triage (extra credit) |

Everyone writes their own report sections (problems and lessons learned),
commits under their own name, and should be able to explain any part of the
repo.

## What members need from each other

- Ty provides `scripts/setup-lvm.sh` (the `/data/db` and `/models` volumes),
  `scripts/lvm-snapshot.sh`, the persistence and smoke tests, and the test logs.
- Frank's Terraform and startup scripts call `setup-lvm.sh`, attach the data
  disks, and wire Secret Manager (see `docs/startup.md`).
- Tal's web tier, HAProxy, and autoscaler live in `deploy/edge.compose.yml`
  and share the `database` network with the `postgres` service.
- Connor provides the embedding and chat models, the inference replicas, and
  the RAG code used for ingestion and retrieval (`ada/rag.py`, `ingest/ingest.py`).
