#!/usr/bin/env python3
"""Fake embedding server for testing ingestion without a real model.

Mimics Ollama's /api/embed. The vectors are random but the same text always
gives the same vector, so it's good for testing the database and re-runs, not
for real search results.   python3 tests/fake_ollama.py --port 11434
"""

import argparse
import hashlib
import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer

DIM = 768


def fake_vector(text):
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    vec = [rng.uniform(-1, 1) for _ in range(DIM)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # deploy-data-tier.sh probes /api/tags to see whether the service is up
        if self.path != "/api/tags":
            self.send_error(404)
            return
        out = b'{"models": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        if self.path != "/api/embed":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        inputs = body["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        out = json.dumps({"model": body.get("model"),
                          "embeddings": [fake_vector(t) for t in inputs]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11434)
    args = ap.parse_args()
    print(f"fake embedding server on 127.0.0.1:{args.port}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
