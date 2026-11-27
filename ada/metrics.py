"""Small in-process Prometheus metrics for the Ada web service.

The dashboard runs several stateless web replicas. Each replica exposes these
counters at ``/metrics`` on its internal port; Prometheus discovers the
containers and aggregates them for the cloud page's metrics tab and Grafana.
"""

from __future__ import annotations

import threading
from collections import defaultdict

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

def _empty_histogram() -> dict:
    return {"count": 0, "sum": 0.0, "buckets": [0] * len(BUCKETS)}


_lock = threading.Lock()
_request_counts: dict[tuple[str, str, str], int] = defaultdict(int)
_request_duration: dict[tuple[str, str], dict] = defaultdict(_empty_histogram)
_chat_first_token: dict[str, dict] = defaultdict(_empty_histogram)
_chat_tokens: dict[str, int] = defaultdict(int)
_chat_generation_seconds: dict[str, float] = defaultdict(float)
_chat_outcomes: dict[tuple[str, str], int] = defaultdict(int)


def _observe(histogram: dict, value: float) -> None:
    histogram["count"] += 1
    histogram["sum"] += value
    for index, upper in enumerate(BUCKETS):
        if value <= upper:
            histogram["buckets"][index] += 1


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**values: object) -> str:
    return "{" + ",".join(f'{name}="{_escape(value)}"' for name, value in values.items()) + "}"


def route_for(path: str) -> str:
    """Collapse request paths so a session identifier never becomes a label."""
    if path in {"/", "/index.html"}:
        return "root"
    if path in {"/health", "/healthz"}:
        return "health"
    if path.startswith("/api/"):
        return path
    if path.startswith("/cloud-orb"):
        return "cloud-orb"
    if path.startswith("/assets/"):
        return "assets"
    return "static"


def observe_request(method: str, path: str, status: int, seconds: float) -> None:
    """Record one HTTP request and its total handling time."""
    route = route_for(path)
    with _lock:
        _request_counts[(method, route, str(status))] += 1
        _observe(_request_duration[(method, route)], max(0.0, seconds))


def observe_chat(
    route: str,
    *,
    first_token_seconds: float | None,
    tokens: int,
    generation_seconds: float,
    success: bool,
) -> None:
    """Record streaming latency, output size, and generation outcome."""
    with _lock:
        if first_token_seconds is not None:
            _observe(_chat_first_token[route], max(0.0, first_token_seconds))
        _chat_tokens[route] += max(0, tokens)
        _chat_generation_seconds[route] += max(0.0, generation_seconds)
        _chat_outcomes[(route, "success" if success else "error")] += 1


def snapshot() -> dict:
    """Return a compact aggregate for local diagnostics and tests."""
    with _lock:
        return {
            "requests": sum(_request_counts.values()),
            "errors": sum(
                count for (_, _, status), count in _request_counts.items()
                if status.startswith("5")
            ),
            "chat_tokens": sum(_chat_tokens.values()),
            "chat_completed": sum(
                count for (_, status), count in _chat_outcomes.items()
                if status == "success"
            ),
            "chat_failed": sum(
                count for (_, status), count in _chat_outcomes.items()
                if status == "error"
            ),
        }


def reset() -> None:
    """Clear metrics; used by tests only."""
    with _lock:
        _request_counts.clear()
        _request_duration.clear()
        _chat_first_token.clear()
        _chat_tokens.clear()
        _chat_generation_seconds.clear()
        _chat_outcomes.clear()


def _render_histogram(
    lines: list[str],
    name: str,
    help_text: str,
    values: dict,
    label_names: tuple[str, ...],
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} histogram")
    for key, value in sorted(values.items(), key=lambda item: str(item[0])):
        labels = dict(zip(label_names, key if isinstance(key, tuple) else (key,)))
        for index, upper in enumerate(BUCKETS):
            lines.append(
                f"{name}_bucket{_labels(**labels, le=str(upper))} {value['buckets'][index]}"
            )
        lines.append(f"{name}_bucket{_labels(**labels, le='+Inf')} {value['count']}")
        lines.append(f"{name}_sum{_labels(**labels)} {value['sum']:.9f}")
        lines.append(f"{name}_count{_labels(**labels)} {value['count']}")


def render() -> str:
    """Render Prometheus text exposition format."""
    with _lock:
        requests = dict(_request_counts)
        durations = {labels: dict(value) for labels, value in _request_duration.items()}
        first_token = {labels: dict(value) for labels, value in _chat_first_token.items()}
        tokens = dict(_chat_tokens)
        generation = dict(_chat_generation_seconds)
        outcomes = dict(_chat_outcomes)

    lines = [
        "# HELP ada_http_requests_total HTTP requests handled by this Ada web replica.",
        "# TYPE ada_http_requests_total counter",
    ]
    for (method, route, status), value in sorted(requests.items()):
        lines.append(
            f"ada_http_requests_total{_labels(method=method, route=route, status=status)} {value}"
        )

    _render_histogram(
        lines,
        "ada_http_request_duration_seconds",
        "Total time spent handling an HTTP request.",
        durations,
        ("method", "route"),
    )
    _render_histogram(
        lines,
        "ada_chat_first_token_seconds",
        "Time from a streamed chat request to its first answer token.",
        first_token,
        ("route",),
    )

    lines.extend(
        [
            "# HELP ada_chat_output_tokens_total Answer tokens streamed by Ada.",
            "# TYPE ada_chat_output_tokens_total counter",
        ]
    )
    for route, value in sorted(tokens.items()):
        lines.append(f"ada_chat_output_tokens_total{_labels(route=route)} {value}")

    lines.extend(
        [
            "# HELP ada_chat_generation_seconds_total Time spent generating streamed answers.",
            "# TYPE ada_chat_generation_seconds_total counter",
        ]
    )
    for route, value in sorted(generation.items()):
        lines.append(
            f"ada_chat_generation_seconds_total{_labels(route=route)} {value:.9f}"
        )

    lines.extend(
        [
            "# HELP ada_chat_outcomes_total Completed chat generations by outcome.",
            "# TYPE ada_chat_outcomes_total counter",
        ]
    )
    for (route, outcome), value in sorted(outcomes.items()):
        lines.append(
            f"ada_chat_outcomes_total{_labels(route=route, outcome=outcome)} {value}"
        )

    return "\n".join(lines) + "\n"
