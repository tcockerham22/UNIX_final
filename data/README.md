# Knowledge base documents

These six short documents (system administration topics matching the project)
are the RAG source material loaded by `scripts/ingest.py`. They are original
text written for this project. To use a different document set, replace the
`.md` or `.txt` files here and re-run ingestion; stale chunks are pruned
automatically.

Known-answer questions for testing:

| Question | Expected answer contains |
|---|---|
| Which command creates a logical volume in LVM? | lvcreate |
| Why use UUID instead of a device name in /etc/fstab? | device names can change between boots |
| What does the nofail mount option do? | system keeps booting if the device is missing |
| What does the p95 latency value mean? | ninety-five percent of requests are faster |
| Which port does the node exporter use by default? | 9100 |
