"""Local web dashboard for Ada's live process telemetry."""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import ROOT, Config
from .events import bus, emit
from .memory import Memory
from .skills import SkillStore

WEB_DIR = ROOT / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/peppers": ("peppers.html", "text/html; charset=utf-8"),
    "/peppers.html": ("peppers.html", "text/html; charset=utf-8"),
    "/peppers-ghost": ("peppers.html", "text/html; charset=utf-8"),
}

UPLOAD_DIR = ROOT / "data" / "uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _safe_filename(name: str) -> str:
    name = os.path.basename((name or "").strip())
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name[:120] or f"upload_{int(time.time())}"


def _extract_text(path: Path) -> str | None:
    ext = path.suffix.lower()
    try:
        if ext in {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css", ".xml", ".log"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if ext == ".pdf":
            # try Python libs
            try:
                from pypdf import PdfReader  # type: ignore
                reader = PdfReader(str(path))
                parts = []
                for page in reader.pages:
                    parts.append(page.extract_text() or "")
                text = "\n".join(parts).strip()
                if text:
                    return text
            except Exception:
                pass
            try:
                import PyPDF2  # type: ignore
                reader = PyPDF2.PdfReader(str(path))
                text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
                if text:
                    return text
            except Exception:
                pass
            # fallback: pdftotext if available
            try:
                import subprocess
                proc = subprocess.run(
                    ["pdftotext", "-layout", str(path), "-"],
                    capture_output=True, text=True, timeout=60
                )
                if proc.returncode == 0:
                    out = (proc.stdout or "").strip()
                    if out:
                        return out
            except Exception:
                pass
            return None
        if ext == ".pptx":
            try:
                from pptx import Presentation  # type: ignore
                prs = Presentation(str(path))
                out = []
                for i, slide in enumerate(prs.slides, 1):
                    out.append(f"# Slide {i}")
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text:
                            out.append(shape.text)
                return "\n".join(out).strip() or None
            except Exception:
                return None
        if ext in {".docx"}:
            try:
                import docx  # type: ignore
                d = docx.Document(str(path))
                return "\n".join(p.text for p in d.paragraphs).strip() or None
            except Exception:
                return None
    except Exception:
        return None
    return None


def list_uploads() -> list[dict]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".extract.txt") or p.name.endswith(".json.meta"):
            continue
        if not p.is_file():
            continue
        meta = {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime, "path": str(p)}
        extp = p.with_suffix(p.suffix + ".extract.txt") if p.suffix else Path(str(p) + ".extract.txt")
        meta["extracted"] = extp.exists()
        items.append(meta)
    return items


def _json_from_text(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def ingest_upload(path: Path, extracted_path: Path | None) -> None:
    """Auto-ingest uploaded document into Ada's knowledge (skill + memory)."""
    try:
        config = Config.load()
        if not getattr(config, "auto_ingest_uploads", True):
            return
        memory = Memory(config.memory_file)
        skills = SkillStore(config.skills_dir)

        text = ""
        if extracted_path and extracted_path.exists():
            try:
                text = extracted_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
        if not text:
            # no extracted text available; record file for later
            memory.add(f"Uploaded document '{path.name}' saved at {path} (no extracted text yet).", "project")
            return

        snippet = text.strip()
        if len(snippet) > 12000:
            snippet = snippet[:12000] + "\n...[truncated]"

        model = getattr(config, "moderate_model", None) or getattr(config, "light_model", None) or getattr(config, "model", None)
        prompt = (
            "You are helping Ada (a local assistant) learn from an uploaded document.\n"
            "Read the document text and produce a useful knowledge artifact.\n"
            "Return ONLY valid JSON with keys: "
            '{"name":"short skill/topic name","description":"one sentence description",'
            '"instructions":"detailed learned content in markdown (summary, key concepts, important facts/details, procedures/steps if any, takeaways/applications, limitations/notes)",'
            '"memory":"one short durable fact worth remembering about this document or its key takeaway","category":"project|preference|person|home|routine|other"}.\n'
            "Rules:\n"
            "- instructions must be substantive and detailed (not meta instructions to search/research), at least several paragraphs or structured bullets.\n"
            "- Focus on the actual content learned from the document.\n"
            "- Keep name concise and relevant to the document/topic.\n\n"
            f"Document filename: {path.name}\n\n"
            f"Document text:\n{snippet}\n"
        )
        import ollama  # local import
        chat_kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 1200, "num_ctx": min(getattr(config, "num_ctx", 4096), 8192)},
            keep_alive=getattr(config, "keep_alive", None),
        )
        if "qwen3" in (model or "").lower():
            chat_kwargs["think"] = False
        resp = ollama.chat(**chat_kwargs)
        msg = resp.get("message", {}) if isinstance(resp, dict) else getattr(resp, "message", {})
        content = (msg.get("content") or "") if isinstance(msg, dict) else (getattr(msg, "content", "") or "")
        data = _json_from_text(content) or {}

        name = str(data.get("name") or path.stem.replace("_", " ").replace("-", " ").strip()[:64] or path.stem)
        description = str(data.get("description") or f"Knowledge learned from uploaded document {path.name}").strip()
        instructions = str(data.get("instructions") or "").strip()
        mem_fact = str(data.get("memory") or f"Learned from uploaded document '{path.name}' ({name}).").strip()
        category = str(data.get("category") or "project").strip().lower()
        if category not in {"preference", "person", "home", "project", "routine", "other"}:
            category = "project"

        if not instructions or len(instructions) < 120:
            # fallback: basic structured content from extracted text
            instructions = (
                f"# {name}\n\n"
                f"## Summary\nLearned content extracted from uploaded document `{path.name}`.\n\n"
                f"## Content\n{snippet[:6000]}\n"
            )

        try:
            skills.save(name, description, instructions, replace=True, sources=[str(path)])
            emit("memory", action="ingest_skill", name=name, source=str(path))
        except Exception as e:
            # if validation fails, save a simpler but substantive skill
            try:
                fallback = (
                    f"## Source\nUploaded document: {path.name}\n\n"
                    f"## Key Extracted Content\n{snippet[:4000]}\n\n"
                    f"## Notes\nThis skill contains extracted knowledge from the uploaded document for Ada to reference and learn from."
                )
                skills.save(name[:64] or path.stem[:64], description or f"Knowledge from {path.name}", fallback, replace=True, sources=[str(path)])
                emit("memory", action="ingest_skill", name=name, source=str(path), fallback=True)
            except Exception:
                emit("error", message=f"ingest_upload skill save failed: {type(e).__name__}: {e}")

        if mem_fact:
            memory.add(mem_fact[:300], category)
    except Exception as err:
        try:
            emit("error", message=f"ingest_upload failed: {type(err).__name__}: {err}")
        except Exception:
            pass


def knowledge_snapshot() -> dict:
    try:
        config = Config.load()
        mem_count = 0
        skill_count = 0
        try:
            memory = Memory(config.memory_file)
            mem_count = len(getattr(memory, "facts", []) or [])
        except Exception:
            mem_count = 0
        try:
            skills = SkillStore(config.skills_dir)
            skill_count = len(skills.list())
        except Exception:
            skill_count = 0
        try:
            uploads = [u for u in list_uploads() if not str(u.get("name", "")).endswith(".extract.txt")]
            up_count = len(uploads)
        except Exception:
            up_count = 0
        return {"memories": mem_count, "skills": skill_count, "uploads": up_count}
    except Exception:
        return {"memories": 0, "skills": 0, "uploads": 0}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AdaDashboard/1.0"

    def log_message(self, *args) -> None:
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
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
        elif path == "/api/uploads":
            self._send_json({"uploads": list_uploads()})
        elif path == "/api/knowledge":
            self._send_json(knowledge_snapshot())
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
        elif path == "/api/uploads":
            self._send_json({"uploads": list_uploads()}, head=True)
        elif path == "/api/knowledge":
            self._send_json(knowledge_snapshot(), head=True)
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

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/upload":
            self._handle_upload()
        else:
            self.send_error(404)

    def _handle_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                self._send_json({"ok": False, "error": "invalid or too-large upload"}, status=400)
                return
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            filename = _safe_filename(str(payload.get("name", "upload")))
            b64 = payload.get("data", "")
            if isinstance(b64, str) and "," in b64 and b64.strip().startswith("data:"):
                b64 = b64.split(",", 1)[1]
            data = base64.b64decode(b64, validate=False)
            if not data or len(data) > MAX_UPLOAD_BYTES:
                self._send_json({"ok": False, "error": "invalid or too-large file data"}, status=400)
                return
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / filename
            stem = dest.stem
            suffix = dest.suffix
            i = 1
            while dest.exists():
                dest = UPLOAD_DIR / f"{stem}_{i}{suffix}"
                i += 1
            dest.write_bytes(data)
            text = _extract_text(dest)
            extracted_path = None
            if text:
                extracted_path = dest.with_suffix(dest.suffix + ".extract.txt") if dest.suffix else Path(str(dest) + ".extract.txt")
                extracted_path.write_text(text, encoding="utf-8")
            emit("memory", action="upload", name=dest.name, extracted=bool(text), size=len(data))
            # auto-ingest in background (summarize -> skill/memory)
            try:
                threading.Thread(target=ingest_upload, args=(dest, extracted_path), daemon=True).start()
            except Exception:
                pass
            self._send_json({
                "ok": True,
                "file": {
                    "name": dest.name,
                    "path": str(dest),
                    "size": len(data),
                    "extracted": bool(text),
                    "extract_path": str(extracted_path) if extracted_path else None,
                    "ingest_started": True,
                }
            })
        except Exception as err:
            self._send_json({"ok": False, "error": f"{type(err).__name__}: {err}"}, status=500)

    def _send_json(self, payload: dict, head: bool = False, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
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
