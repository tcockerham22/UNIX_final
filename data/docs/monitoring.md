# Monitoring and Observability

Observability means being able to see what a system is doing from the outside. It rests on metrics, logs, and alerts.

## Metrics

A metric is a number measured over time, such as requests per second, memory in use, or disk space remaining. Prometheus is a monitoring system that works by pulling: it periodically requests a metrics page from each target and stores the values. Grafana connects to Prometheus and draws the stored values as dashboards.

## Exporters

An exporter is a small program that exposes metrics from something that does not produce them itself. The node exporter reports host statistics such as CPU, memory, and filesystem usage, and it listens on port 9100 by default. Because it reports usage per mount point, it can show how full each logical volume is.

## Latency percentiles

Averages hide slow requests, so latency is reported as percentiles. The p50 value is the median: half of requests are faster than it. The p95 value means ninety-five percent of requests are faster, so it shows how bad the slow tail is. For language models, two further measures matter: time to first token, which is how long the user waits before text starts to appear, and tokens per second, which is the generation speed.

## Alerts

An alert watches a metric and notifies people when a condition holds. Good examples are a logical volume more than eighty percent full or an inference replica that has stopped answering health checks. An alert should point to a problem a person can act on, otherwise it becomes noise.

## Logs

Logs record events in text form. The command journalctl reads logs collected by systemd, and docker logs shows the output of one container. Logs complement metrics: a metric tells you that errors increased, and a log tells you what the errors said.

## Health checks and readiness

A health check tests whether a service works, not only whether its port is open. A readiness check for an inference server confirms the model is loaded and can answer a small prompt, so a load balancer does not send traffic to a replica that is still starting.
