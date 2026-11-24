# Report outline

Follows the structure in the project spec. Items marked [screenshot] should be
captured while doing the work.

## Cover page
Title, GitHub URL, date, course section, member names.

## 1. Introduction
One paragraph on what we built and why.

## 2. Architecture
Diagram that includes the AI tier and the RAG data flow (question, embedding,
vector search, prompt, LLM, answer with sources), plus a short description of
each tier.

## 3. AI architecture and model selection (Member 4)
Model comparison table, memory calculation, licenses, model card citations.

## 4. Implementation notes

### 4.1 Database and storage (Member 1)
- Why pgvector. [compose file]
- Schema and chunking: 90-word chunks with 15 words of overlap, and why.
- Ingestion: deterministic ids and upsert. [screenshot: run twice, same row count]
- LVM layout. [screenshot: lsblk, lvs, df -h, /etc/fstab]
- Snapshot and restore. [screenshot: snapshot list, restore result]
- Persistence after container re-create and reboot. [screenshot: test log]

### 4.2 Infrastructure, automation, secrets, network security (Member 2)
### 4.3 Web tier, load balancing, high availability (Member 3)
### 4.4 Inference, resource limits, OOM demo (Member 4)
### 4.5 Monitoring (Members 2, 3, 4)

## 5. Testing
Smoke, front-end load, AI load, failover and rate-limit tests. For each: AI
tool and prompt used, commands, date, output, pass/fail, and what we had to
fix in the generated test. Logs are in `tests/results/`.

## 6. Problems and lessons learned
One or two paragraphs per member.

## 7. Contribution table

| Member | What they did | Share |
|---|---|---|
| | | |

## 8. Conclusions and future work
