"""Ada's small, human-readable long-term memory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .events import emit


import time

CATEGORIES = {"preference", "person", "home", "project", "routine", "other"}


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.items: list[dict] = []
        self._load()

    @staticmethod
    def _normalize_item(item) -> dict | None:
        if isinstance(item, str):
            text = " ".join(item.split()).strip()
            if not text:
                return None
            return {"text": text, "category": "other", "ts": 0}
        if isinstance(item, dict):
            text = " ".join(str(item.get("text", "")).split()).strip()
            if not text:
                return None
            cat = str(item.get("category", "other")).strip().lower() or "other"
            if cat not in CATEGORIES:
                cat = "other"
            try:
                ts = float(item.get("ts", 0) or 0)
            except (TypeError, ValueError):
                ts = 0
            return {"text": text, "category": cat, "ts": ts}
        return None

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, list):
            items = []
            seen = set()
            for raw in data:
                item = self._normalize_item(raw)
                if not item:
                    continue
                key = item["text"].lower()
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
            self.items = items

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.items, indent=2)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            try:
                dir_fd = os.open(
                    self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
            except OSError:
                dir_fd = None
            if dir_fd is not None:
                try:
                    os.fsync(dir_fd)
                except OSError:
                    pass
                finally:
                    os.close(dir_fd)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def add(self, fact: str, category: str = "other") -> bool:
        fact = " ".join(fact.split())
        if not fact:
            return False
        category = (category or "other").strip().lower()
        if category not in CATEGORIES:
            category = "other"
        for item in self.items:
            if fact.lower() == item["text"].lower():
                # upgrade category if more specific provided
                if item.get("category", "other") == "other" and category != "other":
                    item["category"] = category
                    self._save()
                return False
        self.items.append({"text": fact, "category": category, "ts": time.time()})
        self._save()
        emit("memory", action="add", fact=fact, category=category, count=len(self.items))
        return True

    def forget(self, query: str) -> list[str]:
        needle = query.strip().lower()
        removed = [item["text"] for item in self.items if needle and needle in item["text"].lower()]
        if removed:
            removed_set = set(removed)
            self.items = [item for item in self.items if item["text"] not in removed_set]
            self._save()
            emit("memory", action="forget", facts=removed, count=len(self.items))
        return removed

    def prompt(self) -> str:
        lines = []
        for item in self.items:
            cat = item.get("category", "other")
            if cat and cat != "other":
                lines.append(f"- [{cat}] {item['text']}")
            else:
                lines.append(f"- {item['text']}")
        return "\n".join(lines)

    def all(self) -> list[dict]:
        return list(self.items)

    def suggest_category(self, fact: str) -> str:
        f = fact.lower()
        if any(k in f for k in ["prefer", "likes", "like ", "favorite", "favourite", "wants", "dislikes"]):
            return "preference"
        if any(k in f for k in ["name is", "sister", "brother", "wife", "husband", "friend", "colleague", "mother", "father", "daughter", "son"]):
            return "person"
        if any(k in f for k in ["home", "house", "garage", "room", "light", "thermostat", "door", "sensor", "ha", "home assistant"]):
            return "home"
        if any(k in f for k in ["project", "repo", "codebase", "working on", "building"]):
            return "project"
        if any(k in f for k in ["every day", "routine", "usually", "every morning", "every night", "schedule"]):
            return "routine"
        return "other"

    def __iter__(self):
        return (item["text"] for item in self.items)

    def __len__(self) -> int:
        return len(self.items)
