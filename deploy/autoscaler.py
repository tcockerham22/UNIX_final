"""Scale the ada-web Compose service between three and six containers."""

from __future__ import annotations

import csv
import io
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

LOGGER = logging.getLogger("ada.autoscaler")


def parse_web_backend_stats(csv_text: str) -> tuple[float, int]:
    """Return HAProxy's requests/second and the number of healthy web servers."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = [
        {key.lstrip("# ").strip(): (value or "").strip() for key, value in row.items()}
        for row in reader
    ]
    backend = next(
        (
            row
            for row in rows
            if row.get("pxname") == "web_pool" and row.get("svname") == "BACKEND"
        ),
        None,
    )
    if backend is None:
        raise ValueError("HAProxy stats did not include the web_pool BACKEND row.")
    try:
        rate = float(backend["rate"])
    except (KeyError, ValueError) as error:
        raise ValueError("HAProxy web_pool stats did not include a valid request rate.") from error

    active = sum(
        1
        for row in rows
        if row.get("pxname") == "web_pool"
        and row.get("svname") != "BACKEND"
        and row.get("status", "").upper().startswith("UP")
    )
    return rate, active


def choose_replica_count(
    request_rate: float,
    active_replicas: int,
    *,
    minimum: int = 3,
    maximum: int = 6,
    scale_up_rate: float = 12.0,
    scale_down_rate: float = 2.0,
    low_load_seconds: float = 0.0,
    now: float | None = None,
    scale_down_delay: float = 300.0,
) -> tuple[int, float | None]:
    """Scale up on sustained current pressure and down only after low load persists."""
    if minimum < 1 or maximum < minimum:
        raise ValueError("Replica limits must satisfy 1 <= minimum <= maximum.")
    current = min(max(active_replicas, minimum), maximum)
    if request_rate >= scale_up_rate:
        return min(current + 1, maximum), None
    if request_rate > scale_down_rate or current <= minimum:
        return current, None

    timestamp = time.monotonic() if now is None else now
    low_since = low_load_seconds or timestamp
    if timestamp - low_since >= scale_down_delay:
        return max(current - 1, minimum), None
    return current, low_since


def fetch_stats(url: str) -> str:
    """Fetch the private HAProxy CSV endpoint."""
    with urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"HAProxy stats returned HTTP {response.status}.")
        return response.read().decode("utf-8")


def scale_service(project_dir: Path, compose_file: Path, replicas: int) -> None:
    """Apply one Compose scale change without restarting existing web workers."""
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "up",
        "-d",
        "--no-deps",
        "--no-recreate",
        "--scale",
        f"ada-web={replicas}",
        "ada-web",
    ]
    subprocess.run(command, cwd=project_dir, check=True)


def run() -> None:
    """Poll HAProxy continuously and scale the web tier when load warrants it."""
    project_dir = Path(os.environ.get("ADA_PROJECT_DIR", "/opt/ada")).resolve()
    compose_file = Path(
        os.environ.get("ADA_COMPOSE_FILE", project_dir / "deploy/edge.compose.yml")
    ).resolve()
    stats_url = os.environ.get(
        "ADA_HAPROXY_STATS_URL",
        "http://127.0.0.1:8401/stats?stats;csv",
    )
    minimum = int(os.environ.get("ADA_WEB_MIN_REPLICAS", "3"))
    maximum = int(os.environ.get("ADA_WEB_MAX_REPLICAS", "6"))
    poll_seconds = float(os.environ.get("ADA_AUTOSCALE_POLL_SECONDS", "30"))
    low_since = None

    while True:
        try:
            rate, active = parse_web_backend_stats(fetch_stats(stats_url))
            desired, low_since = choose_replica_count(
                rate,
                active,
                minimum=minimum,
                maximum=maximum,
                scale_up_rate=float(os.environ.get("ADA_SCALE_UP_RPS", "12")),
                scale_down_rate=float(os.environ.get("ADA_SCALE_DOWN_RPS", "2")),
                low_load_seconds=low_since or 0.0,
                scale_down_delay=float(os.environ.get("ADA_SCALE_DOWN_DELAY", "300")),
            )
            if desired != active:
                LOGGER.info(
                    "Web load is %.1f requests/s; scaling %d -> %d replicas.",
                    rate,
                    active,
                    desired,
                )
                scale_service(project_dir, compose_file, desired)
            else:
                LOGGER.info(
                    "Web load is %.1f requests/s with %d healthy replicas.",
                    rate,
                    active,
                )
        except Exception:
            LOGGER.exception("Autoscaler could not read stats or apply scaling.")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("ADA_AUTOSCALER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run()
