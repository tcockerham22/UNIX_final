"""Collect a compact operational snapshot for the cloud metrics tab."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from datetime import datetime, timezone
from urllib.request import urlopen
from typing import Any

from .config import Config
from .rag import PostgresRAG

LOGGER = logging.getLogger(__name__)
TIMEOUT_SECONDS = 3.0

EXPRESSIONS = {
    "web_replicas": 'sum(haproxy_server_up{backend="web_pool"})',
    "ai_shims": 'sum(haproxy_server_up{backend="ollama_pool"})',
    "requests_per_second": 'sum(rate(haproxy_frontend_http_requests_total{frontend="public_http"}[5m]))',
    "errors_per_second": 'sum(rate(haproxy_frontend_http_responses_total{frontend="public_http",code="5xx"}[5m]))',
    "average_response_seconds": 'haproxy_backend_http_response_time_average_seconds{backend="web_pool"}',
    "cpu_percent": '100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100',
    "memory_percent": '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)',
    "containers_running": "ada_containers_running",
    "app_requests_per_second": "sum(rate(ada_http_requests_total[5m]))",
    "app_error_rate": (
        'sum(rate(ada_http_requests_total{status=~"5.."}[5m])) '
        "/ clamp_min(sum(rate(ada_http_requests_total[5m])), 0.001)"
    ),
    "app_latency_p95_seconds": (
        "histogram_quantile(0.95, "
        "sum by (le) (rate(ada_http_request_duration_seconds_bucket[5m])))"
    ),
    "first_token_p95_seconds": (
        "histogram_quantile(0.95, "
        "sum by (le) (rate(ada_chat_first_token_seconds_bucket[5m])))"
    ),
    "tokens_per_second": (
        "sum(rate(ada_chat_output_tokens_total[5m])) "
        "/ clamp_min(sum(rate(ada_chat_generation_seconds_total[5m])), 0.001)"
    ),
}
DISK_USED_EXPRESSION = (
    '100 * (1 - node_filesystem_avail_bytes{fstype=~"ext4|xfs",mountpoint!~"/boot.*"} '
    '/ node_filesystem_size_bytes{fstype=~"ext4|xfs",mountpoint!~"/boot.*"})'
)
DISK_AVAILABLE_EXPRESSION = (
    'node_filesystem_avail_bytes{fstype=~"ext4|xfs",mountpoint!~"/boot.*"}'
)


def _fetch_json(base_url: str, path: str, params: dict[str, str] | None = None) -> dict:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def query_series(base_url: str, expression: str) -> list[dict]:
    """Run one instant PromQL query and return its result series."""
    payload = _fetch_json(base_url, "/api/v1/query", {"query": expression})
    if payload.get("status") != "success":
        raise ValueError(str(payload.get("error", "Prometheus query failed")))
    return list(payload.get("data", {}).get("result", []))


def query_number(base_url: str, expression: str) -> float | None:
    """Return the first value from an instant PromQL query."""
    series = query_series(base_url, expression)
    return _number(series[0].get("value", [None, None])[1]) if series else None


def _rag_chunks(config: Config) -> int | None:
    if not config.database_url:
        return None
    try:
        rag = PostgresRAG(config.database_url, config.ollama_host)
        rag.ensure_schema()
        with rag._connect() as connection:
            return int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
    except Exception:
        LOGGER.debug("Could not read the RAG chunk count", exc_info=True)
        return None


def collect(config: Config) -> dict:
    """Build the safe, summary-only payload consumed by the metrics tab."""
    base_url = config.prometheus_url or "http://127.0.0.1:9090"
    snapshot: dict[str, Any] = {
        "ok": False,
        "available": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": base_url,
        "services": [],
        "disks": [],
        "alerts": [],
        "rag_chunks": _rag_chunks(config),
    }

    values: dict[str, float | None] = {}
    try:
        for name, expression in EXPRESSIONS.items():
            try:
                values[name] = query_number(base_url, expression)
            except Exception:
                LOGGER.debug("Prometheus query failed for %s", name, exc_info=True)
                values[name] = None

        up_series = query_series(base_url, "up")
        snapshot["services"] = sorted(
            [
                {
                    "name": series["metric"].get("job", "service"),
                    "instance": series["metric"].get("instance", ""),
                    "up": _number(series.get("value", [None, 0])[1]) == 1,
                }
                for series in up_series
            ],
            key=lambda item: (item["name"], item["instance"]),
        )

        used_series = query_series(base_url, DISK_USED_EXPRESSION)
        available_series = query_series(base_url, DISK_AVAILABLE_EXPRESSION)
        available = {
            item["metric"].get("mountpoint"): _number(item.get("value", [None, None])[1])
            for item in available_series
        }
        snapshot["disks"] = sorted(
            [
                {
                    "mountpoint": series["metric"].get("mountpoint", "unknown"),
                    "used_percent": _number(series.get("value", [None, None])[1]),
                    "available_bytes": available.get(series["metric"].get("mountpoint")),
                }
                for series in used_series
            ],
            key=lambda item: item["mountpoint"],
        )

        alert_payload = _fetch_json(base_url, "/api/v1/alerts")
        snapshot["alerts"] = [
            {
                "name": alert.get("labels", {}).get("alertname", "Alert"),
                "summary": alert.get("annotations", {}).get("summary", alert.get("labels", {}).get("alertname", "")),
                "state": alert.get("state", "inactive"),
            }
            for alert in alert_payload.get("data", {}).get("alerts", [])
            if alert.get("state") == "firing"
        ]
        snapshot["available"] = True
        snapshot["ok"] = True
    except Exception as err:
        LOGGER.warning("Could not collect the Prometheus snapshot: %s", err)
        snapshot["error"] = "Metrics are temporarily unavailable."

    snapshot.update(values)
    snapshot["collected_at"] = time.time()
    return snapshot
