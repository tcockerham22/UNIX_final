"""Static and unit checks for the Phase 7 metrics tab and monitoring stack."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from ada import metrics, monitoring
from ada.config import Config

ROOT = Path(__file__).resolve().parent.parent


class AppMetricsTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_request_metrics_and_histogram_are_rendered(self):
        metrics.observe_request("GET", "/api/metrics", 200, 0.12)
        metrics.observe_request("GET", "/api/metrics", 500, 0.4)

        text = metrics.render()
        self.assertIn('ada_http_requests_total{method="GET",route="/api/metrics",status="200"} 1', text)
        self.assertIn('ada_http_requests_total{method="GET",route="/api/metrics",status="500"} 1', text)
        self.assertIn("# TYPE ada_http_request_duration_seconds histogram", text)
        self.assertIn('ada_http_request_duration_seconds_bucket{method="GET",route="/api/metrics",le="0.25"} 1', text)
        self.assertEqual(metrics.snapshot()["errors"], 1)

    def test_chat_metrics_record_first_token_tokens_and_outcome(self):
        metrics.observe_chat(
            "rag",
            first_token_seconds=0.8,
            tokens=42,
            generation_seconds=2.4,
            success=True,
        )

        text = metrics.render()
        self.assertIn('ada_chat_first_token_seconds_bucket{route="rag",le="1.0"} 1', text)
        self.assertIn('ada_chat_output_tokens_total{route="rag"} 42', text)
        self.assertIn('ada_chat_outcomes_total{route="rag",outcome="success"} 1', text)
        self.assertEqual(metrics.snapshot()["chat_tokens"], 42)


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class MonitoringTests(unittest.TestCase):
    def test_collect_builds_a_safe_summary_from_prometheus(self):
        def fake_urlopen(url: str, timeout=None):
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if parsed.path == "/api/v1/alerts":
                payload = {
                    "status": "success",
                    "data": {
                        "alerts": [
                            {
                                "state": "firing",
                                "labels": {"alertname": "AdaVolumeAbove80"},
                                "annotations": {"summary": "Volume is full."},
                            }
                        ]
                    },
                }
            elif parsed.path == "/api/v1/query":
                query = params.get("query", [""])[0]
                if query == "up":
                    results = [
                        {"metric": {"job": "haproxy", "instance": "haproxy-exporter:9101"}, "value": [1, "1"]}
                    ]
                elif query == monitoring.DISK_USED_EXPRESSION:
                    results = [
                        {"metric": {"mountpoint": "/data/db"}, "value": [1, "83"]}
                    ]
                elif query == monitoring.DISK_AVAILABLE_EXPRESSION:
                    results = [
                        {"metric": {"mountpoint": "/data/db"}, "value": [1, "1000"]}
                    ]
                else:
                    results = [{"metric": {}, "value": [1, "2.5"]}]
                payload = {"status": "success", "data": {"result": results}}
            else:
                raise AssertionError(f"unexpected URL: {url}")
            return FakeResponse(payload)

        config = Config(profile="cloud", prometheus_url="http://prometheus:9090")
        with patch("ada.monitoring.urlopen", side_effect=fake_urlopen):
            result = monitoring.collect(config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["web_replicas"], 2.5)
        self.assertEqual(result["services"][0]["name"], "haproxy")
        self.assertEqual(result["disks"][0]["mountpoint"], "/data/db")
        self.assertEqual(result["alerts"][0]["name"], "AdaVolumeAbove80")


class ConfigTests(unittest.TestCase):
    def test_prometheus_url_can_be_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"ADA_CONFIG": str(config_path), "ADA_PROMETHEUS_URL": "http://prometheus:9090"},
                clear=False,
            ):
                config = Config.load()
        self.assertEqual(config.prometheus_url, "http://prometheus:9090")


class Phase7DeploymentTests(unittest.TestCase):
    def test_cloud_page_has_a_metrics_tab(self):
        html = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "cloud.css").read_text(encoding="utf-8")
        script = (ROOT / "web" / "cloud.js").read_text(encoding="utf-8")
        for needle in (
            'id="chat-tab"',
            'id="metrics-tab"',
            'id="metrics-view"',
            'id="metric-first-token"',
            'id="metric-tokens"',
            'id="service-list"',
            'id="disk-list"',
            'id="alert-list"',
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, html)
        self.assertIn(".metrics-grid", css)
        self.assertIn('fetch("/api/metrics"', script)
        self.assertIn("window.setInterval(loadMetrics, 15000)", script)

    def test_compose_exposes_app_metrics_only_inside_the_monitoring_network(self):
        compose = (ROOT / "deploy" / "edge.compose.yml").read_text(encoding="utf-8")
        haproxy = (ROOT / "deploy" / "haproxy" / "haproxy.cfg.template").read_text(encoding="utf-8")
        self.assertIn("ADA_PROMETHEUS_URL: ${ADA_PROMETHEUS_URL:-http://prometheus:9090}", compose)
        self.assertIn("./prometheus/rules:/etc/prometheus/rules:ro", compose)
        self.assertIn("./grafana/dashboards:/var/lib/grafana/dashboards:ro", compose)
        self.assertIn("acl raw_metrics path_eq /metrics", haproxy)
        self.assertIn("http-request deny deny_status 403 if raw_metrics", haproxy)

        ada_web = compose.split("\n  ada-web:", 1)[1].split("\n  postgres:", 1)[0]
        self.assertIn("- monitoring", ada_web)

    def test_prometheus_rules_and_grafana_dashboard_are_provisioned(self):
        prometheus = (ROOT / "deploy" / "prometheus.yml").read_text(encoding="utf-8")
        rules = (ROOT / "deploy" / "prometheus" / "rules" / "ada.rules.yml").read_text(encoding="utf-8")
        dashboard = json.loads(
            (ROOT / "deploy" / "grafana" / "dashboards" / "ada-cloud.json").read_text(encoding="utf-8")
        )
        provider = (ROOT / "deploy" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml").read_text(encoding="utf-8")
        self.assertIn("/etc/prometheus/rules/ada.rules.yml", prometheus)
        self.assertIn("- job_name: ada-web", prometheus)
        self.assertIn("alert: AdaWebReplicasDown", rules)
        self.assertIn("alert: AdaVolumeAbove80", rules)
        self.assertIn("alert: AdaHighErrorRate", rules)
        self.assertIn("/var/lib/grafana/dashboards", provider)
        self.assertEqual(dashboard["uid"], "ada-cloud")
        self.assertTrue(dashboard["panels"])


if __name__ == "__main__":
    unittest.main()
