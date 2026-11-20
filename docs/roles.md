# Roles

The spec has five roles. With four people, project lead is combined with data
management.

| Member | Owns |
|---|---|
| 1: Lead + data | Repo and task tracking, budget alert, database, ingestion, LVM and snapshot, persistence proof, smoke test, test logs, report and video |
| 2: Infrastructure | GCP project, VPC, firewall, IAP SSH, IAM, Terraform, Secret Manager, startup script, Prometheus/Grafana, alert |
| 3: Application | Web app, web-tier Compose, 3-6 replicas and autoscaling, load balancer, rate limiting (429), graceful degradation, front-end load test |
| 4: AI | Model choice, inference replicas, readiness checks, embeddings, RAG query service, memory sizing, OOM demo, AI metrics, AI load and failover tests, log triage (extra credit) |

Everyone writes their own report sections (problems and lessons learned),
commits under their own name, and should be able to explain any part of the
repo.

## What members need from each other

- Member 1 provides `scripts/setup-lvm.sh`, the database Compose service,
  `scripts/ingest.py`, and the `/data/db` and `/models` volumes.
- Member 2 calls Member 1's deploy script from the startup script (see
  `docs/INTEGRATION.md`).
- Member 4 provides the embedding endpoint used by ingestion and the RAG
  query service.
- Member 3 puts the web services on the same Docker network as the database.
