"""Ada configuration.

Defaults live here. Override any value in config.json or with an ADA_* environment
variable (for example ADA_MODEL, ADA_FAST_MODEL, ADA_VOICE, ADA_USER_NAME).
"""

from __future__ import annotations

import json
import os
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"

DEEP_HINTS = (
    "think hard",
    "think carefully",
    "deep dive",
    "deeply",
    "take your time",
    "use the deep model",
    "reason carefully",
    "analyze carefully",
    "work through",
    "step by step",
    "learn",
    "research",
    "study",
    "everything you can",
    "all you can",
    "in depth",
    "in-depth",
    "comprehensive",
    "teach me",
)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value, default: list[str]) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                value = parsed
        if isinstance(value, str):
            value = text.split(",")
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return list(default)


def _cast(value, default):
    if isinstance(default, bool):
        return _as_bool(value)
    if isinstance(default, int):
        return _as_int(value, default)
    if isinstance(default, float):
        return _as_float(value, default)
    if isinstance(default, list):
        return _as_list(value, default)
    return value


@dataclass
class Config:
    user_name: str = "Sam"
    sensitive_note: str = "This includes the garage door."

    model: str = "llama3.1:8b"
    fast_model: str = "qwen2.5:3b"
    auto_route: bool = False
    auto_tools: bool = False
    keep_alive: str = "10m"
    num_ctx: int = 4096
    temperature: float = 0.7
    quick_max_tokens: int = 160
    deep_max_tokens: int = 350

    persona_file: str = str(ASSETS_DIR / "persona.md")
    memory_file: str = str(DATA_DIR / "memories.json")
    skills_dir: str = str(ASSETS_DIR / "skills")
    coding_tools: bool = True

    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8765

    speak: bool = True
    voice: str = "en_GB-cori-medium"
    output_device: str | None = None

    stt_enabled: bool = True
    voice_input: bool = False
    hands_free: bool = False
    flow_mode: bool = False
    barge_in: bool = True
    require_wake_word: bool = True
    wake_words: list[str] = field(
        default_factory=lambda: [
            "hey ada",
            "hi ada",
            "okay ada",
            "ada",
            "hey lovelace",
            "lovelace",
        ]
    )
    whisper_model: str = "base.en"
    stt_beam_size: int = 5
    stt_vad_filter: bool = True
    stt_silence_seconds: float = 1.2
    stt_max_seconds: float = 20.0
    input_device: str | None = None

    search_results: int = 5

    # Home Assistant integration
    ha_url: str | None = None
    ha_token: str | None = None
    ha_verify_ssl: bool = True
    ha_notify_service: str | None = None  # e.g. notify.mobile_app_phone
    ha_context_entity: str | None = None  # e.g. sensor.current_room or input_text.ada_location

    # System / guardrails
    reminders_file: str = str(DATA_DIR / "reminders.json")
    allowed_paths: list[str] = field(default_factory=list)  # if set, restrict file/command cwd to these roots
    confirm_dangerous_commands: bool = False
    command_allowlist: list[str] = field(default_factory=list)

    # Learning
    learn_depth: str = "deep"  # quick | deep

    # Workspace
    workspace: str | None = None

    @classmethod
    def load(cls) -> "Config":
        data: dict = {}
        path = Path(os.environ.get("ADA_CONFIG", ROOT / "config.json"))
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, json.JSONDecodeError) as err:
                print(f"[config] could not read {path}: {err}")

        if "wake_word" in data:
            legacy = data.pop("wake_word")
            if "wake_words" not in data and legacy:
                data["wake_words"] = [legacy] if isinstance(legacy, str) else legacy

        defaults = {}
        for item in fields(cls):
            if item.default is not MISSING:
                defaults[item.name] = item.default
            elif item.default_factory is not MISSING:
                defaults[item.name] = item.default_factory()

        for name in list(data):
            if name in defaults:
                data[name] = _cast(data[name], defaults[name])

        for name, default in defaults.items():
            env = os.environ.get(f"ADA_{name.upper()}")
            if env is not None:
                data[name] = _cast(env, default)
        legacy_wake = os.environ.get("ADA_WAKE_WORD")
        if legacy_wake and "ADA_WAKE_WORDS" not in os.environ:
            data["wake_words"] = _as_list(legacy_wake, defaults["wake_words"])

        clean = {}
        for key, value in data.items():
            if key not in defaults:
                continue
            if value is None and defaults[key] is not None:
                continue
            clean[key] = value
        return cls(**clean)

    def choose_model(self, text: str) -> str:
        if self.fast_model == self.model:
            return self.fast_model
        low = text.lower()
        force_deep = any(hint in low for hint in DEEP_HINTS)
        if not self.auto_route:
            return self.model if force_deep else self.fast_model
        if len(text) > 320 or low.count("?") >= 2 or force_deep:
            return self.model
        return self.fast_model

    def model_label(self, model: str) -> str:
        if model == self.fast_model:
            return "quick"
        return "deep"
