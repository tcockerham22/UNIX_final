"""Tools Ada can call: web, memory, skills, files, commands, HA, reminders, and project helpers."""

from __future__ import annotations

import fnmatch
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, urlparse

import httpx

from .events import emit
from .skills import SkillStore

if TYPE_CHECKING:
    from .config import Config
    from .memory import Memory

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
WIKI_AGENT = "AdaLocalAssistant/1.0 (https://github.com/local/ada; local use)"
TIMEOUT = 15.0

# --- simple reminders scheduler (in-process) ---
_REMINDERS_LOCK = threading.Lock()
_REMINDERS: list[dict] = []
_REMINDERS_PATH: Path | None = None
_REMINDER_THREAD: threading.Thread | None = None
_REMINDER_STOP = threading.Event()


def _load_reminders(path: Path) -> list[dict]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
    except Exception:
        pass
    return []


def _save_reminders(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _parse_when(when: str) -> float | None:
    s = (when or "").strip().lower()
    now = time.time()
    # relative: "in 10m", "in 2 hours", "30s"
    m = re.match(r"^(?:in\s+)?(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = 1
        if unit.startswith("m"):
            mult = 60
        elif unit.startswith("h"):
            mult = 3600
        elif unit.startswith("d"):
            mult = 86400
        return now + n * mult
    # absolute local formats
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%H:%M", "%H:%M:%S"):
        try:
            dt = datetime.strptime(when.strip(), fmt)
            if fmt.startswith("%H"):
                today = datetime.now()
                dt = dt.replace(year=today.year, month=today.month, day=today.day)
                if dt.timestamp() <= now:
                    dt += timedelta(days=1)
            return dt.timestamp()
        except Exception:
            continue
    return None


def _reminder_loop():
    while not _REMINDER_STOP.wait(5):
        due = []
        with _REMINDERS_LOCK:
            if _REMINDERS_PATH is None:
                continue
            now = time.time()
            remaining = []
            for r in _REMINDERS:
                try:
                    t = float(r.get("at", 0))
                except Exception:
                    t = 0
                if t and t <= now:
                    due.append(r)
                else:
                    remaining.append(r)
            if due:
                _REMINDERS[:] = remaining
                try:
                    _save_reminders(_REMINDERS_PATH, _REMINDERS)
                except Exception:
                    pass
        for r in due:
            msg = str(r.get("message", "Reminder"))
            emit("notification", kind="reminder", message=msg, at=r.get("at"))
            emit("assistant", text=f"Reminder: {msg}")


def _uploads_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "uploads"


def list_uploads_tool() -> str:
    try:
        up = _uploads_dir()
        up.mkdir(parents=True, exist_ok=True)
        items = []
        for p in sorted(up.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.name.endswith(".extract.txt") or p.name.endswith(".json.meta"):
                continue
            if not p.is_file():
                continue
            extp = p.with_suffix(p.suffix + ".extract.txt") if p.suffix else Path(str(p) + ".extract.txt")
            items.append({
                "name": p.name,
                "path": str(p),
                "size": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "extracted_text": str(extp) if extp.exists() else None,
            })
        if not items:
            return "No uploaded documents."
        return json.dumps(items, indent=2)
    except Exception as err:
        return f"ERROR: could not list uploads ({type(err).__name__}: {err})."


def read_upload(name_or_path: str, prefer_extracted: bool = True, config: "Config | None" = None) -> str:
    try:
        target = (name_or_path or "").strip()
        if not target:
            return "ERROR: no upload name/path provided."
        p = Path(target)
        if not p.is_absolute():
            # try uploads dir by name first
            cand = _uploads_dir() / target
            p = cand if cand.exists() else Path(target)
        if not p.exists():
            return f"ERROR: upload not found: {target}"
        # if it's an original file and extracted text exists, prefer it for readability/training
        if prefer_extracted and not p.name.endswith(".extract.txt"):
            extp = p.with_suffix(p.suffix + ".extract.txt") if p.suffix else Path(str(p) + ".extract.txt")
            if extp.exists():
                p = extp
        if config and not _is_path_allowed(p, config, for_write=False):
            return "ERROR: path is outside allowed paths."
        text = p.read_text(encoding="utf-8", errors="ignore")
        if len(text) > 20000:
            text = text[:20000] + "\n...[truncated]"
        return f"Path: {p}\n\n{text}"
    except Exception as err:
        return f"ERROR: could not read upload ({type(err).__name__}: {err})."


def ada_info(config: "Config") -> str:
    try:
        root = Path(__file__).resolve().parent.parent
        cwd = Path.cwd().resolve()
        info = {
            "cwd": str(cwd),
            "ada_root": str(root),
            "config_file": str(getattr(config, "config_path", "") or os.environ.get("ADA_CONFIG", root / "config.json")),
            "persona_file": str(getattr(config, "persona_file", root / "assets" / "persona.txt")),
            "skills_dir": str(getattr(config, "skills_dir", root / "assets" / "skills")),
            "memory_file": str(getattr(config, "memory_file", root / "data" / "memories.json")),
            "reminders_file": str(getattr(config, "reminders_file", root / "data" / "reminders.json")),
            "uploads_dir": str(root / "data" / "uploads"),
            "workspace": str(getattr(config, "workspace", None) or cwd),
            "allowed_paths": list(getattr(config, "allowed_paths", []) or []),
            "confirm_dangerous_commands": bool(getattr(config, "confirm_dangerous_commands", False)),
        }
        return json.dumps(info, indent=2)
    except Exception as err:
        return f"ERROR: could not get ada info ({type(err).__name__}: {err})."


def ensure_reminders(config: "Config") -> None:
    global _REMINDERS_PATH, _REMINDER_THREAD
    path = Path(config.reminders_file)
    if not path.is_absolute():
        path = Path(config.workspace or Path.cwd()) / path
    with _REMINDERS_LOCK:
        if _REMINDERS_PATH is None:
            _REMINDERS_PATH = path
            _REMINDERS.extend(_load_reminders(path))
    if _REMINDER_THREAD is None or not _REMINDER_THREAD.is_alive():
        _REMINDER_STOP.clear()
        _REMINDER_THREAD = threading.Thread(target=_reminder_loop, daemon=True)
        _REMINDER_THREAD.start()


# --- web helpers ---

def _headers_for(url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    agent = WIKI_AGENT if host.endswith("wikipedia.org") else USER_AGENT
    return {"User-Agent": agent}


class _PageText(HTMLParser):
    SKIP = {
        "script", "style", "noscript", "svg", "template", "head", "nav", "aside",
        "header", "footer", "form", "button", "select", "option",
    }
    BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._main = 0
        self._in_title = False

    def _add(self, text: str) -> None:
        self.all_parts.append(text)
        if self._main:
            self.main_parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"main", "article"}:
            self._main += 1
        elif tag in self.BREAK:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in {"main", "article"} and self._main:
            self._main -= 1
        elif tag in self.BREAK:
            self._add("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._add(data)


def _normalize(parts: list[str]) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parts))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _html_to_text(html: str) -> tuple[str, str]:
    parser = _PageText()
    parser.feed(html)
    main = _normalize(parser.main_parts)
    text = main if len(main) > 500 else _normalize(parser.all_parts)
    return parser.title.strip(), text


def _is_public_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").strip().lower().rstrip(".")
        if not host or host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        if "." not in host:
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        if not infos:
            return False
        for info in infos:
            address = info[4][0].split("%", 1)[0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                return False
            if not ip.is_global:
                return False
        return True
    except ValueError:
        return False


def _wikipedia_search(query: str, max_results: int) -> list[dict]:
    response = httpx.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
        },
        timeout=TIMEOUT,
        headers={"User-Agent": WIKI_AGENT},
    )
    response.raise_for_status()
    hits = response.json().get("query", {}).get("search", [])
    results = []
    for hit in hits:
        title = hit.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", hit.get("snippet", ""))
        results.append(
            {
                "title": title,
                "href": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe=""),
                "body": snippet,
            }
        )
    return results


def web_search(query: str, max_results: int = 5) -> str:
    query = query.strip()
    if not query:
        return "ERROR: empty search query."
    results: list[dict] = []
    error = None
    try:
        from ddgs import DDGS

        with DDGS(timeout=TIMEOUT) as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as err:
        error = err

    if not results:
        try:
            results = _wikipedia_search(query, max_results)
        except Exception:
            if error is not None:
                return f"ERROR: web search failed ({type(error).__name__}: {error})."

    if results:
        lines = []
        for i, result in enumerate(results, 1):
            title = (result.get("title") or "").strip()
            url = (result.get("href") or result.get("url") or "").strip()
            body = " ".join((result.get("body") or "").split())
            if len(body) > 500:
                body = body[:500].rstrip() + "…"
            lines.append(f"{i}. {title}\n   {url}\n   {body}")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000].rstrip() + "\n[truncated]"
        return text
    return f"No web results found for {query!r}."


def web_fetch(url: str, max_chars: int = 6000) -> str:
    url = url.strip()
    if not url:
        return "ERROR: empty URL."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not _is_public_url(url):
        return "ERROR: that address is not a public web URL."
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=TIMEOUT,
            headers=_headers_for(url),
        )
        response.raise_for_status()
    except Exception as err:
        return f"ERROR: could not fetch {url} ({type(err).__name__}: {err})."

    if not _is_public_url(str(response.url)):
        return "ERROR: that address is not a public web URL."

    content_type = response.headers.get("content-type", "").lower()
    if content_type and not any(kind in content_type for kind in ("html", "text", "json", "xml")):
        return f"ERROR: unsupported content type {content_type!r}."

    if "html" in content_type or "<html" in response.text[:500].lower():
        title, text = _html_to_text(response.text)
        if title:
            text = f"{title}\n\n{text}"
    else:
        text = response.text

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[truncated]"
    return f"Source: {response.url}\n\n{text or '(no readable text)'}"


def get_weather(location: str) -> str:
    location = location.strip()
    if not location:
        return "ERROR: please provide a location."
    try:
        response = httpx.get(
            f"https://wttr.in/{quote(location, safe='')}?format=j1",
            timeout=TIMEOUT,
            headers={"User-Agent": "curl/8"},
        )
        response.raise_for_status()
        data = response.json()
        current = data["current_condition"][0]
        today = data["weather"][0]
        description = current["weatherDesc"][0]["value"].strip().lower()
        lines = [
            f"Weather for {location} right now: {description}, {current['temp_C']} degrees "
            f"(feels like {current['FeelsLikeC']}), humidity {current['humidity']} percent, "
            f"wind {current['windspeedKmph']} kilometres per hour."
        ]
        lines.append(
            f"Today: {today['mintempC']} to {today['maxtempC']} degrees, "
            f"chance of rain {today.get('hourly', [{}])[0].get('chanceofrain', '?')} percent."
        )
        return " ".join(lines)
    except Exception as err:
        return f"ERROR: could not get weather for {location} ({type(err).__name__}: {err})."


def current_time() -> str:
    return datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")


# --- sandbox/path helpers ---

def _get_allowed_roots(config: "Config") -> list[Path]:
    roots = []
    for p in getattr(config, "allowed_paths", []) or []:
        try:
            rp = Path(p).expanduser().resolve()
            roots.append(rp)
        except Exception:
            continue
    # also allow configured workspace
    ws = getattr(config, "workspace", None)
    if ws:
        try:
            roots.append(Path(ws).expanduser().resolve())
        except Exception:
            pass
    return roots


def _path_allowed(p: Path, config: "Config") -> bool:
    roots = _get_allowed_roots(config)
    if not roots:
        return True
    try:
        rp = p.resolve()
    except Exception:
        rp = p
    for root in roots:
        try:
            rp.relative_to(root)
            return True
        except Exception:
            continue
    return False


def _resolve_path(path: str, config: "Config | None" = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        base = None
        if config and getattr(config, "workspace", None):
            try:
                base = Path(config.workspace).expanduser().resolve()
            except Exception:
                base = None
        p = (base or Path.cwd()) / p
    return p.resolve()


# --- file & project tools ---

def read_file(path: str, max_chars: int = 12000, config: "Config | None" = None) -> str:
    try:
        p = _resolve_path(path, config)
        if config and not _path_allowed(p, config):
            return f"ERROR: path not allowed by sandbox: {p}"
        if not p.exists():
            return f"ERROR: file not found: {p}"
        if p.is_dir():
            return f"ERROR: path is a directory: {p}"
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n[truncated]"
        return f"Path: {p}\n\n{text}"
    except Exception as err:
        return f"ERROR: could not read file ({type(err).__name__}: {err})."


def write_file(path: str, content: str, config: "Config | None" = None) -> str:
    try:
        p = _resolve_path(path, config)
        if config and not _path_allowed(p, config):
            return f"ERROR: path not allowed by sandbox: {p}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        emit("action", kind="file_write", path=str(p), bytes=len(content))
        return f"Wrote {len(content)} characters to {p}."
    except Exception as err:
        return f"ERROR: could not write file ({type(err).__name__}: {err})."


def edit_file(path: str, old: str, new: str, replace_all: bool = False, config: "Config | None" = None) -> str:
    try:
        p = _resolve_path(path, config)
        if config and not _path_allowed(p, config):
            return f"ERROR: path not allowed by sandbox: {p}"
        if not p.exists() or p.is_dir():
            return f"ERROR: file not found: {p}"
        text = p.read_text(encoding="utf-8", errors="replace")
        if old == new:
            return "ERROR: old and new strings must differ."
        count = text.count(old)
        if count == 0:
            return "ERROR: old string not found in file."
        if count > 1 and not replace_all:
            return f"ERROR: old string found {count} times; provide more context or set replace_all."
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        p.write_text(updated, encoding="utf-8")
        emit("action", kind="file_edit", path=str(p), replacements=count if replace_all else 1)
        return f"Edited {p} ({count if replace_all else 1} replacement(s))."
    except Exception as err:
        return f"ERROR: could not edit file ({type(err).__name__}: {err})."


def list_directory(path: str = ".", max_entries: int = 200, config: "Config | None" = None) -> str:
    try:
        p = _resolve_path(path, config)
        if config and not _path_allowed(p, config):
            return f"ERROR: path not allowed by sandbox: {p}"
        if not p.exists():
            return f"ERROR: path not found: {p}"
        if not p.is_dir():
            return f"ERROR: not a directory: {p}"
        entries = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            kind = "dir" if child.is_dir() else "file"
            entries.append(f"{kind}\t{child.name}")
            if len(entries) >= max_entries:
                entries.append("...[truncated]")
                break
        return f"Path: {p}\n" + ("\n".join(entries) if entries else "(empty)")
    except Exception as err:
        return f"ERROR: could not list directory ({type(err).__name__}: {err})."


def make_directory(path: str, config: "Config | None" = None) -> str:
    try:
        if not path.strip():
            return "ERROR: empty path."
        p = _resolve_path(path, config)
        if config and not _path_allowed(p, config):
            return f"ERROR: path not allowed by sandbox: {p}"
        p.mkdir(parents=True, exist_ok=True)
        emit("action", kind="mkdir", path=str(p))
        return f"Created directory: {p}"
    except Exception as err:
        return f"ERROR: could not create directory ({type(err).__name__}: {err})."


def search_files(query: str, path: str = ".", glob: str = "", max_results: int = 50, config: "Config | None" = None) -> str:
    if not query.strip():
        return "ERROR: empty search query."
    try:
        root = _resolve_path(path, config)
        if config and not _path_allowed(root, config):
            return f"ERROR: path not allowed by sandbox: {root}"
        if not root.exists():
            return f"ERROR: path not found: {root}"
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results = []
        # prefer rg if available
        rg = shutil_which("rg")
        if rg and root.is_dir():
            cmd = [rg, "-n", "--no-heading", "-S", "--max-count", "200", query, str(root)]
            if glob:
                cmd[1:1] = ["-g", glob]
            try:
                proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
                out = (proc.stdout or "").strip().splitlines()
                for line in out[:max_results]:
                    results.append(line)
            except Exception:
                results = []
        if not results:
            if root.is_file():
                files = [root]
            else:
                files = []
                for p in root.rglob("*"):
                    if len(files) > 2000:
                        break
                    if not p.is_file():
                        continue
                    if glob and not fnmatch.fnmatch(p.name, glob):
                        continue
                    # skip big/binary-ish by extension/size
                    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".onnx", ".pyc"}:
                        continue
                    try:
                        if p.stat().st_size > 1_000_000:
                            continue
                    except OSError:
                        continue
                    files.append(p)
            for p in files:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        results.append(f"{p}:{i}:{line.strip()[:200]}")
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
        if not results:
            return f"No matches for {query!r} in {root}."
        body = "\n".join(results[:max_results])
        if len(body) > 8000:
            body = body[:8000] + "\n[truncated]"
        return body
    except Exception as err:
        return f"ERROR: search failed ({type(err).__name__}: {err})."


def shutil_which(cmd: str) -> str | None:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(p) / cmd
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def workspace_info(path: str = ".", config: "Config | None" = None) -> str:
    try:
        root = _resolve_path(path, config)
        if config and not _path_allowed(root, config):
            return f"ERROR: path not allowed by sandbox: {root}"
        lines = [f"Path: {root}"]
        # git info
        git = shutil_which("git")
        if git:
            try:
                inside = subprocess.run([git, "-C", str(root), "rev-parse", "--is-inside-work-tree"], text=True, capture_output=True, timeout=10)
                if inside.returncode == 0 and inside.stdout.strip() == "true":
                    top = subprocess.run([git, "-C", str(root), "rev-parse", "--show-toplevel"], text=True, capture_output=True, timeout=10).stdout.strip()
                    branch = subprocess.run([git, "-C", str(root), "branch", "--show-current"], text=True, capture_output=True, timeout=10).stdout.strip()
                    status = subprocess.run([git, "-C", str(root), "status", "--short"], text=True, capture_output=True, timeout=10).stdout.strip()
                    lines.append(f"Git: yes ({top})")
                    lines.append(f"Branch: {branch or '(detached)'}")
                    lines.append("Status:\n" + (status if status else "(clean)"))
                else:
                    lines.append("Git: no")
            except Exception:
                lines.append("Git: unknown")
        # project hints
        hints = []
        for name, kind in [
            ("package.json", "node"),
            ("pyproject.toml", "python"),
            ("requirements.txt", "python"),
            ("Cargo.toml", "rust"),
            ("go.mod", "go"),
            ("CMakeLists.txt", "cmake"),
            ("Makefile", "make"),
            ("pom.xml", "maven"),
            ("build.gradle", "gradle"),
        ]:
            if (root / name).exists() or (root.is_dir() and any(root.glob(f"**/{name}"))):
                hints.append(kind)
        if hints:
            lines.append("Detected: " + ", ".join(sorted(set(hints))))
        return "\n".join(lines)
    except Exception as err:
        return f"ERROR: could not get workspace info ({type(err).__name__}: {err})."


def detect_project_tasks(path: str = ".", config: "Config | None" = None) -> str:
    try:
        root = _resolve_path(path, config)
        if config and not _path_allowed(root, config):
            return f"ERROR: path not allowed by sandbox: {root}"
        tasks = []
        if (root / "package.json").exists():
            tasks.append("node: npm test | npm run build | npm start (check package.json scripts)")
        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").exists():
            tasks.append("python: pytest | python -m pytest")
        if (root / "requirements.txt").exists():
            tasks.append("python: pip install -r requirements.txt")
        if (root / "Cargo.toml").exists():
            tasks.append("rust: cargo test | cargo build | cargo run")
        if (root / "go.mod").exists():
            tasks.append("go: go test ./... | go build ./...")
        if (root / "CMakeLists.txt").exists():
            tasks.append("cmake: cmake -S . -B build && cmake --build build")
        if (root / "Makefile").exists():
            tasks.append("make: make test | make | make build (see Makefile targets)")
        if not tasks:
            return f"No common project tasks detected in {root}."
        return "Suggested tasks:\n- " + "\n- ".join(tasks)
    except Exception as err:
        return f"ERROR: could not detect tasks ({type(err).__name__}: {err})."


DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b", r"\brm\s+-fr\b", r"\bsudo\b", r"\bmkfs\b", r"\bdd\b\s+if=",
    r":\(\)\s*\{\s*:\|:&\s*\};:", r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b",
    r">\s*/dev/sd", r"\bchmod\s+-R\s+777\s+/\b",
]


def _command_is_dangerous(command: str) -> str | None:
    c = command.strip()
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, c):
            return pat
    return None


def run_command(command: str, cwd: str | None = None, timeout: int = 60, config: "Config | None" = None) -> str:
    if not command.strip():
        return "ERROR: empty command."
    try:
        if config and getattr(config, "command_allowlist", None):
            allowed = config.command_allowlist
            if not any(command.strip().startswith(a) or command.strip() == a for a in allowed):
                return "ERROR: command not in allowlist."
        danger = _command_is_dangerous(command)
        if danger and config and getattr(config, "confirm_dangerous_commands", False):
            return f"ERROR: potentially dangerous command blocked (matched {danger}). Set confirm_dangerous_commands=false to allow, or run manually."
        if danger:
            emit("action", kind="dangerous_command", command=command, matched=danger)

        workdir = str(_resolve_path(cwd, config)) if cwd else str(Path(getattr(config, "workspace", None) or Path.cwd()))
        if config and not _path_allowed(Path(workdir), config):
            return f"ERROR: working directory not allowed by sandbox: {workdir}"
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 300)),
        )
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        out = out.strip()
        if len(out) > 12000:
            out = out[:12000].rstrip() + "\n[truncated]"
        status = f"exit {proc.returncode}"
        emit("action", kind="command", command=command, cwd=workdir, exit=proc.returncode)
        return f"{status} (cwd: {workdir})\n\n{out or '(no output)'}"
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s."
    except Exception as err:
        return f"ERROR: could not run command ({type(err).__name__}: {err})."


# --- Home Assistant ---

def _ha_request(config: "Config", method: str, path: str, payload: dict | None = None):
    base = (getattr(config, "ha_url", None) or "").strip().rstrip("/")
    token = (getattr(config, "ha_token", None) or "").strip()
    if not base or not token:
        return None, "ERROR: Home Assistant is not configured (set ha_url and ha_token)."
    url = base + path
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    verify = bool(getattr(config, "ha_verify_ssl", True))
    try:
        resp = httpx.request(method, url, headers=headers, json=payload, timeout=15.0, verify=verify)
        resp.raise_for_status()
        if resp.content:
            try:
                return resp.json(), None
            except Exception:
                return resp.text, None
        return {"ok": True}, None
    except Exception as err:
        return None, f"ERROR: Home Assistant request failed ({type(err).__name__}: {err})."


def ha_get_states(config: "Config", domain: str = "") -> str:
    data, err = _ha_request(config, "GET", "/api/states")
    if err:
        return err
    if not isinstance(data, list):
        return "ERROR: unexpected response from Home Assistant."
    domain = (domain or "").strip().lower()
    lines = []
    for item in data:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("entity_id", ""))
        if domain and not eid.startswith(domain + "."):
            continue
        state = str(item.get("state", ""))
        name = (item.get("attributes") or {}).get("friendly_name") or eid
        lines.append(f"{eid}\t{state}\t{name}")
    if not lines:
        return "No matching Home Assistant entities."
    text = "\n".join(lines[:200])
    if len(lines) > 200:
        text += f"\n...[+{len(lines)-200} more]"
    return text


def ha_get_state(config: "Config", entity_id: str) -> str:
    entity_id = (entity_id or "").strip()
    if not entity_id:
        return "ERROR: entity_id is required."
    data, err = _ha_request(config, "GET", f"/api/states/{quote(entity_id, safe='._-')}")
    if err:
        return err
    try:
        name = (data.get("attributes") or {}).get("friendly_name") or entity_id
        state = data.get("state")
        attrs = data.get("attributes") or {}
        interesting = {k: attrs[k] for k in list(attrs)[:12] if k not in {"friendly_name", "icon", "supported_features"}}
        return json.dumps({"entity_id": entity_id, "name": name, "state": state, "attributes": interesting}, indent=2, default=str)
    except Exception:
        return json.dumps(data, indent=2, default=str)


def ha_call_service(config: "Config", domain: str, service: str, entity_id: str = "", data: dict | None = None) -> str:
    domain = (domain or "").strip()
    service = (service or "").strip()
    if not domain or not service:
        return "ERROR: domain and service are required."
    payload = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id
    resp, err = _ha_request(config, "POST", f"/api/services/{quote(domain)}/{quote(service)}", payload)
    if err:
        return err
    emit("action", kind="ha_service", domain=domain, service=service, entity_id=entity_id)
    return f"Called Home Assistant service {domain}.{service}." + (f" Response: {json.dumps(resp, default=str)[:500]}" if resp else "")


def ha_context(config: "Config") -> str:
    entity = (getattr(config, "ha_context_entity", None) or "").strip()
    parts = []
    if entity:
        parts.append(ha_get_state(config, entity))
    # basic summary
    data, err = _ha_request(config, "GET", "/api/")
    if not err and isinstance(data, dict):
        parts.append(f"HA: {data.get('message','ok')}")
    return "\n".join(parts) if parts else "No Home Assistant context configured."


# --- reminders & notifications ---

def add_reminder(message: str, when: str, config: "Config") -> str:
    ensure_reminders(config)
    at = _parse_when(when)
    if at is None:
        return "ERROR: could not parse time. Use 'in 10m', 'in 2h', 'YYYY-MM-DD HH:MM', or 'HH:MM'."
    item = {"id": f"r{int(time.time()*1000)}", "message": message.strip(), "at": at, "created": time.time()}
    with _REMINDERS_LOCK:
        _REMINDERS.append(item)
        if _REMINDERS_PATH:
            _save_reminders(_REMINDERS_PATH, _REMINDERS)
    when_str = datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M:%S")
    emit("action", kind="reminder_add", message=message, at=when_str)
    return f"Reminder set for {when_str}: {message}"


def list_reminders(config: "Config") -> str:
    ensure_reminders(config)
    with _REMINDERS_LOCK:
        items = sorted(list(_REMINDERS), key=lambda r: r.get("at", 0))
    if not items:
        return "No reminders."
    lines = []
    for r in items:
        when_str = datetime.fromtimestamp(float(r.get("at", 0))).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"- [{r.get('id')}] {when_str}: {r.get('message')}")
    return "\n".join(lines)


def remove_reminder(reminder_id: str, config: "Config") -> str:
    ensure_reminders(config)
    rid = (reminder_id or "").strip()
    with _REMINDERS_LOCK:
        before = len(_REMINDERS)
        _REMINDERS[:] = [r for r in _REMINDERS if str(r.get("id")) != rid and rid.lower() not in str(r.get("message","")).lower()]
        removed = before - len(_REMINDERS)
        if removed and _REMINDERS_PATH:
            _save_reminders(_REMINDERS_PATH, _REMINDERS)
    return f"Removed {removed} reminder(s)." if removed else "No matching reminder."


def send_notification(message: str, config: "Config", title: str = "Ada") -> str:
    emit("notification", kind="notify", title=title, message=message)
    svc = (getattr(config, "ha_notify_service", None) or "").strip()
    if svc and "." in svc:
        domain, service = svc.split(".", 1)
        res = ha_call_service(config, domain, service, data={"title": title, "message": message})
        return f"Notification emitted. {res}"
    return "Notification emitted locally (no HA notify service configured)."


# --- tool schema & dispatch ---

TOOLS = [
    {"type": "function", "function": {"name": "web_search", "description": "Search the public web for current information.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "What to search for."}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "Download a web page and return its readable text.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "Full http(s) URL to read."}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "get_weather", "description": "Get current weather and today's forecast for a place.", "parameters": {"type": "object", "properties": {"location": {"type": "string", "description": "City or place name."}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "remember", "description": "Save a lasting fact, preference, routine, or project note to memory. Optionally set category: preference, person, home, project, routine, other.", "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "The fact to remember."}, "category": {"type": "string", "description": "Category (optional)."}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "forget", "description": "Remove remembered facts that match the given words.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Words identifying the memory."}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "list_memories", "description": "List saved memories, optionally filtered by category.", "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "Optional category filter."}}}}},
    {"type": "function", "function": {"name": "read_skill", "description": "Read the full instructions for a saved skill.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name."}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "save_skill", "description": "Create or update a persistent skill with concrete, detailed instructions. Use when asked to learn/save/update a skill.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "instructions": {"type": "string"}, "replace": {"type": "boolean"}, "sources": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "description", "instructions"]}}},
    {"type": "function", "function": {"name": "list_skills", "description": "List saved skills with metadata.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "current_time", "description": "Get the current local date and time.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a shell command on the user's system. Use for coding, builds, tests, git, package management, project setup. Respects sandbox/guardrails if configured.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file from the filesystem.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a text file. Use to save code/scripts/projects.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Edit a text file by replacing an exact string (preferred for targeted changes).", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {"name": "list_directory", "description": "List files and folders in a directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "make_directory", "description": "Create a directory (and parents) for projects/folders.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search_files", "description": "Search for text in files within a path (grep-like).", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "workspace_info", "description": "Get workspace/project info including git status and detected project type.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "project_tasks", "description": "Detect common test/build/run tasks for a project.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "ha_get_states", "description": "List Home Assistant entity states (optionally by domain).", "parameters": {"type": "object", "properties": {"domain": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "ha_get_state", "description": "Get one Home Assistant entity's state and attributes.", "parameters": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}}},
    {"type": "function", "function": {"name": "ha_call_service", "description": "Call a Home Assistant service (e.g. turn on a light, trigger automation).", "parameters": {"type": "object", "properties": {"domain": {"type": "string"}, "service": {"type": "string"}, "entity_id": {"type": "string"}, "data": {"type": "object"}}, "required": ["domain", "service"]}}},
    {"type": "function", "function": {"name": "ha_context", "description": "Get Home Assistant context/presence info if configured.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "add_reminder", "description": "Add a local reminder. 'when' can be like 'in 10m', 'in 2h', 'HH:MM', or 'YYYY-MM-DD HH:MM'.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "when": {"type": "string"}}, "required": ["message", "when"]}}},
    {"type": "function", "function": {"name": "list_reminders", "description": "List pending reminders.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "remove_reminder", "description": "Remove a reminder by id or matching text.", "parameters": {"type": "object", "properties": {"reminder_id": {"type": "string"}}, "required": ["reminder_id"]}}},
    {"type": "function", "function": {"name": "send_notification", "description": "Send a notification (locally and via Home Assistant notify service if configured).", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "title": {"type": "string"}}, "required": ["message"]}}},
    {"type": "function", "function": {"name": "ada_info", "description": "Get information about Ada's own environment and paths (project root, config, persona, skills, memory, uploads, workspace). Use this when asked to improve/modify Ada itself or to understand where Ada runs.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "list_uploads", "description": "List documents uploaded by the user (papers, slides, notes, etc.) available for Ada to read and learn from.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_upload", "description": "Read an uploaded document's content by name (prefers extracted text when available). Use to learn from or answer questions about uploaded papers/slides/files.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Upload filename or path."}, "prefer_extracted": {"type": "boolean", "description": "Prefer extracted text sidecar when available (default true)."}}, "required": ["name"]}}},
]


def run_tool(name: str, args: dict, memory: "Memory", config: "Config") -> str:
    args = args or {}
    try:
        ensure_reminders(config)
        if name == "web_search":
            return web_search(str(args.get("query", "")), max_results=config.search_results)
        if name == "web_fetch":
            return web_fetch(str(args.get("url", "")))
        if name == "get_weather":
            return get_weather(str(args.get("location", "")))
        if name == "remember":
            fact = str(args.get("fact", "")).strip()
            if not fact:
                return "ERROR: no fact provided."
            cat = str(args.get("category", "") or "").strip().lower()
            if not cat or cat == "auto":
                cat = memory.suggest_category(fact)
            saved = memory.add(fact, cat)
            return f"Saved to memory [{cat}]." if saved else "That is already in memory."
        if name == "forget":
            query = str(args.get("query", "")).strip()
            if not query:
                return "ERROR: no memory query provided."
            removed = memory.forget(query)
            return ("Forgot: " + "; ".join(removed)) if removed else "No matching memory found."
        if name == "list_memories":
            cat = str(args.get("category", "") or "").strip().lower()
            items = memory.all()
            if cat:
                items = [i for i in items if i.get("category") == cat]
            if not items:
                return "No memories."
            return "\n".join(f"- [{i.get('category','other')}] {i['text']}" for i in items)
        if name == "read_skill":
            found = SkillStore(config.skills_dir).get(str(args.get("name", "")))
            if not found:
                return "ERROR: no skill by that name. Use list_skills."
            title, body = found
            if len(body) > 8000:
                body = body[:8000].rstrip() + "\n[truncated]"
            return f"Skill: {title}\n\n{body}"
        if name == "save_skill":
            replace = args.get("replace", False)
            if isinstance(replace, str):
                replace = replace.strip().lower() in {"1", "true", "yes", "on"}
            sources = args.get("sources")
            if isinstance(sources, str):
                sources = [s.strip() for s in re.split(r"[\n,]", sources) if s.strip()]
            return SkillStore(config.skills_dir).save(
                str(args.get("name", "")),
                str(args.get("description", "")),
                str(args.get("instructions", "")),
                bool(replace),
                sources=sources if isinstance(sources, list) else None,
            )
        if name == "list_skills":
            items = SkillStore(config.skills_dir).list_info()
            if not items:
                return "No skills saved."
            lines = []
            for s in items:
                ts = s.get("updated") or 0
                when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
                lines.append(f"- {s['name']} ({when}): {s.get('description','')}")
            return "\n".join(lines)
        if name == "current_time":
            return current_time()
        if name == "run_command":
            timeout = args.get("timeout", 60)
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                timeout = 60
            return run_command(str(args.get("command", "")), args.get("cwd"), timeout, config)
        if name == "read_file":
            return read_file(str(args.get("path", "")), config=config)
        if name == "write_file":
            return write_file(str(args.get("path", "")), str(args.get("content", "")), config=config)
        if name == "edit_file":
            ra = args.get("replace_all", False)
            if isinstance(ra, str):
                ra = ra.strip().lower() in {"1", "true", "yes", "on"}
            return edit_file(str(args.get("path", "")), str(args.get("old", "")), str(args.get("new", "")), bool(ra), config=config)
        if name == "list_directory":
            return list_directory(str(args.get("path", ".")), config=config)
        if name == "make_directory":
            return make_directory(str(args.get("path", "")), config=config)
        if name == "search_files":
            mr = args.get("max_results", 50)
            try:
                mr = int(mr)
            except Exception:
                mr = 50
            return search_files(str(args.get("query", "")), str(args.get("path", ".")), str(args.get("glob", "")), mr, config=config)
        if name == "workspace_info":
            return workspace_info(str(args.get("path", ".")), config=config)
        if name == "project_tasks":
            return detect_project_tasks(str(args.get("path", ".")), config=config)
        if name == "ha_get_states":
            return ha_get_states(config, str(args.get("domain", "")))
        if name == "ha_get_state":
            return ha_get_state(config, str(args.get("entity_id", "")))
        if name == "ha_call_service":
            data = args.get("data") if isinstance(args.get("data"), dict) else None
            return ha_call_service(config, str(args.get("domain", "")), str(args.get("service", "")), str(args.get("entity_id", "")), data)
        if name == "ha_context":
            return ha_context(config)
        if name == "add_reminder":
            return add_reminder(str(args.get("message", "")), str(args.get("when", "")), config)
        if name == "list_reminders":
            return list_reminders(config)
        if name == "remove_reminder":
            return remove_reminder(str(args.get("reminder_id", "")), config)
        if name == "send_notification":
            return send_notification(str(args.get("message", "")), config, str(args.get("title", "Ada")))
        if name == "ada_info":
            return ada_info(config)
        if name == "list_uploads":
            return list_uploads_tool()
        if name == "read_upload":
            pe = args.get("prefer_extracted", True)
            if isinstance(pe, str):
                pe = pe.strip().lower() in {"1", "true", "yes", "on"}
            return read_upload(str(args.get("name", "")), bool(pe), config=config)
        return f"ERROR: unknown tool {name!r}."
    except Exception as err:
        return f"ERROR: {name} failed ({type(err).__name__}: {err})."
