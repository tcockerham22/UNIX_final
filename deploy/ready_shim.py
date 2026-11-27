"""Proxy Ollama requests and expose a model-aware readiness check."""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

OLLAMA_URL = os.environ.get("OLLAMA_UPSTREAM", "http://ollama:11434")
MODEL = os.environ.get("ADA_CLOUD_MODEL", "qwen2.5:3b")
POLL_SECONDS = 10
MAX_REQUEST_BYTES = 32 * 1024 * 1024
readiness_lock = threading.Lock()
last_success = 0.0
probe_error = "model availability has not been checked yet"


def _probe_model() -> None:
    """Confirm Ollama is reachable and the requested model is available."""
    global last_success, probe_error
    connection = None
    try:
        upstream = urlsplit(OLLAMA_URL)
        connection = http.client.HTTPConnection(
            upstream.hostname, upstream.port or 80, timeout=5
        )
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"Ollama model listing returned HTTP {response.status}")

        models = json.loads(body).get("models", [])
        available = any(
            item.get("name") == MODEL or item.get("model") == MODEL
            for item in models
        )
        if not available:
            raise RuntimeError(f"model {MODEL!r} is not available")

        with readiness_lock:
            last_success = time.monotonic()
            probe_error = ""
    except Exception as error:
        with readiness_lock:
            probe_error = str(error)
    finally:
        if connection is not None:
            connection.close()


def _readiness_loop() -> None:
    """Refresh model availability without sending inference requests."""
    while True:
        _probe_model()
        time.sleep(POLL_SECONDS)


def _chunked_write(handler: BaseHTTPRequestHandler, data: bytes) -> None:
    if data:
        handler.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")


class ReadyProxyHandler(BaseHTTPRequestHandler):
    """Forward Ollama HTTP API calls while retaining streaming responses."""

    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/ready":
            with readiness_lock:
                ready = last_success > 0
                detail = probe_error
            body = json.dumps({"ready": ready, "detail": detail}).encode("utf-8")
            self.send_response(200 if ready else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._proxy_request("GET")

    def do_POST(self) -> None:
        self._proxy_request("POST")

    def _proxy_request(self, method: str) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                self.send_error(413, "Request body is too large.")
                return
            body = self.rfile.read(length) if length else None
            upstream = urlsplit(OLLAMA_URL)
            connection = http.client.HTTPConnection(
                upstream.hostname, upstream.port or 80, timeout=3600
            )
            headers = {}
            for name in ("Content-Type", "Accept"):
                if self.headers.get(name):
                    headers[name] = self.headers[name]
            connection.request(method, self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Cache-Control"):
                if response.getheader(name):
                    self.send_header(name, response.getheader(name))
            has_length = response.getheader("Content-Length") is not None
            if not has_length:
                self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                data = response.read1(65536)
                if not data:
                    break
                if has_length:
                    self.wfile.write(data)
                else:
                    _chunked_write(self, data)
                self.wfile.flush()
            if not has_length:
                self.wfile.write(b"0\r\n\r\n")
            connection.close()
        except (BrokenPipeError, ConnectionResetError, OSError, http.client.HTTPException):
            self.close_connection = True


if __name__ == "__main__":
    threading.Thread(target=_readiness_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), ReadyProxyHandler)
    server.serve_forever()
