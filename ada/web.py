"""Local web dashboard for Ada's live process telemetry."""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import ROOT, Config
from .events import bus

WEB_DIR = ROOT / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AdaDashboard/1.0"

    def log_message(self, *args) -> None:
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Last-Event-ID")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/events":
            self._stream_events()
        elif path == "/api/state":
            self._send_json(bus.snapshot())
        elif path == "/health":
            self._send_json({"ok": True})
        elif path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            self._send_file(WEB_DIR / name, content_type)
        else:
            self.send_error(404)

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(bus.snapshot(), head=True)
        elif path == "/health":
            self._send_json({"ok": True}, head=True)
        elif path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            self._send_file(WEB_DIR / name, content_type, head=True)
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
        else:
            self.send_error(404)

    def _send_json(self, payload: dict, head: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, head: bool = False) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _stream_events(self) -> None:
        subscriber = bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                data = json.dumps(event, separators=(",", ":"), default=str)
                self.wfile.write(f"id: {event['id']}\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(subscriber)
            self.close_connection = True


class Dashboard:
    def __init__(self, config: Config):
        self.config = config
        self.server = ThreadingHTTPServer(
            (config.web_host, config.web_port), DashboardHandler
        )
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "Dashboard":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        host = self.config.web_host
        shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{shown}:{self.config.web_port}"


def start_dashboard(config: Config) -> Dashboard:
    return Dashboard(config).start()
