"""Tests for the AI readiness proxy and HAProxy-driven web autoscaler."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from deploy import autoscaler, ready_shim


class AutoscalerTests(unittest.TestCase):
    def test_parse_web_backend_rate_and_healthy_replica_count(self):
        stats = (
            "# pxname,svname,status,rate\n"
            "web_pool,web1,UP,2\n"
            "web_pool,web2,UP,2\n"
            "web_pool,web3,UP,2\n"
            "web_pool,BACKEND,UP,6\n"
        )

        self.assertEqual(autoscaler.parse_web_backend_stats(stats), (6.0, 3))

    def test_scale_up_is_one_replica_and_never_exceeds_six(self):
        self.assertEqual(
            autoscaler.choose_replica_count(13, 3),
            (4, None),
        )
        self.assertEqual(
            autoscaler.choose_replica_count(13, 6),
            (6, None),
        )

    def test_scale_down_waits_for_five_minutes_of_low_load(self):
        self.assertEqual(
            autoscaler.choose_replica_count(1, 4, now=100),
            (4, 100),
        )
        self.assertEqual(
            autoscaler.choose_replica_count(1, 4, low_load_seconds=100, now=399),
            (4, 100),
        )
        self.assertEqual(
            autoscaler.choose_replica_count(1, 4, low_load_seconds=100, now=400),
            (3, None),
        )

    def test_replica_bounds_are_validated(self):
        with self.assertRaisesRegex(ValueError, "Replica limits"):
            autoscaler.choose_replica_count(0, 1, minimum=6, maximum=3)


class ReadyShimTests(unittest.TestCase):
    def test_readiness_probe_runs_prompt_and_requires_loaded_model(self):
        received_paths = []
        probed_models = []

        class FakeOllamaHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                pass

            def do_POST(self):
                received_paths.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                probed_models.append(payload["model"])
                body = json.dumps({"message": {"content": "OK"}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                received_paths.append(self.path)
                body = json.dumps({"models": [{"name": ready_shim.MODEL}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        upstream = HTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(
                ready_shim,
                "OLLAMA_URL",
                f"http://127.0.0.1:{upstream.server_port}",
            ):
                ready_shim.last_success = 0.0
                ready_shim.probe_error = "not ready"
                ready_shim._probe_model()

            self.assertGreater(ready_shim.last_success, 0)
            self.assertEqual(received_paths, ["/api/chat", "/api/ps"])
            self.assertEqual(probed_models, [ready_shim.MODEL])
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
