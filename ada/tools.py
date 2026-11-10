"""Tools Ada can call: web search, page reading, weather, and memory."""

from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import quote, urlparse

import httpx

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
    if content_type and not any(
        kind in content_type for kind in ("html", "text", "json", "xml")
    ):
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for current information. Use for news, prices, "
                "weather, sport, releases, or anything that may have changed recently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Download a web page and return its readable text. Use after web_search "
                "to read a promising result in full."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full http(s) URL to read."}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and today's forecast for a place.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City or place name."}
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save a lasting fact, preference, or routine about the user to long-term "
                "memory. Do not save secrets, passwords, or financial details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The fact to remember."}
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove remembered facts that match the given words.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words identifying the memory."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": (
                "Read the full instructions for one of Ada's saved skills. Use this when the "
                "user asks to use a skill, or when a task matches a skill in the skill index. "
                "Do not create a new skill in order to answer a request to use an existing one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to read."}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": (
                "Create or update a persistent skill: a reusable procedure or set of guidance "
                "Ada can consult later. Use only when the user explicitly asks Ada to learn, "
                "save, add, or update a skill. Do not use it to answer a question or to use an "
                "existing skill. If the skill already exists, new instructions are appended "
                "unless replace is true. Never store secrets or unsafe instructions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short skill name, e.g. Coding."},
                    "description": {
                        "type": "string",
                        "description": "One line describing when to use the skill.",
                    },
                    "instructions": {
                        "type": "string",
                        "description": (
                            "The actual skill content: concrete steps, rules, and examples. "
                            "Do not write a note telling a future reader to research it."
                        ),
                    },
                    "replace": {
                        "type": "boolean",
                        "description": (
                            "Replace the entire existing skill. Only set this when the user "
                            "explicitly asks to replace it."
                        ),
                    },
                },
                "required": ["name", "description", "instructions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def run_tool(name: str, args: dict, memory: "Memory", config: "Config") -> str:
    args = args or {}
    try:
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
            return "Saved to memory." if memory.add(fact) else "That is already in memory."
        if name == "forget":
            query = str(args.get("query", "")).strip()
            if not query:
                return "ERROR: no memory query provided."
            removed = memory.forget(query)
            if removed:
                return "Forgot: " + "; ".join(removed)
            return "No matching memory found."
        if name == "read_skill":
            found = SkillStore(config.skills_dir).get(str(args.get("name", "")))
            if not found:
                return "ERROR: no skill by that name. Use the skill index."
            title, body = found
            if len(body) > 6000:
                body = body[:6000].rstrip() + "\n[truncated]"
            return f"Skill: {title}\n\n{body}"
        if name == "save_skill":
            replace = args.get("replace", False)
            if isinstance(replace, str):
                replace = replace.strip().lower() in {"1", "true", "yes", "on"}
            return SkillStore(config.skills_dir).save(
                str(args.get("name", "")),
                str(args.get("description", "")),
                str(args.get("instructions", "")),
                bool(replace),
            )
        if name == "current_time":
            return current_time()
        return f"ERROR: unknown tool {name!r}."
    except Exception as err:
        return f"ERROR: {name} failed ({type(err).__name__}: {err})."
