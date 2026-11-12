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

MODERATE_HINTS = (
    "explain",
    "compare",
    "summarize",
    "summary",
    "help me",
    "how do i",
    "how to",
    "plan",
    "write",
    "draft",
    "debug",
    "fix",
    "code",
    "coding",
    "implement",
    "refactor",
    "create",
    "make",
    "build",
    "project",
    "app",
    "application",
    "server",
    "script",
    "program",
    "website",
    "webpage",
    "api",
    "compile",
    "setup",
    "configure",
    "install",
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

    # 3-tier models: light / moderate / deep
    light_model: str = "qwen2.5:4b-instruct"
    moderate_model: str = "qwen2.5:7b-instruct"
    deep_model: str = "qwen2.5:14b-instruct"
    # backward-compat aliases
    model: str = "qwen2.5:14b-instruct"
    fast_model: str = "qwen2.5:4b-instruct"
    auto_route: bool = False
    auto_tools: bool = False
    keep_alive: str = "10m"
    num_ctx: int = 4096
    temperature: float = 0.7
    light_max_tokens: int = 220
    moderate_max_tokens: int = 700
    quick_max_tokens: int = 220
    deep_max_tokens: int = 2048

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
    voice_length_scale: float = 1.02
    voice_noise_scale: float = 0.4
    voice_noise_w: float = 0.7
    voice_sentence_silence: float = 0.12

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

    # Auto memory
    auto_memory: bool = True
    auto_memory_max_items: int = 200

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

        # backward-compat mapping
        if "fast_model" in data and "light_model" not in data:
            data["light_model"] = data["fast_model"]
        if "model" in data and "deep_model" not in data:
            data["deep_model"] = data["model"]
        if "quick_max_tokens" in data and "light_max_tokens" not in data:
            data["light_max_tokens"] = data["quick_max_tokens"]

        clean = {}
        for key, value in data.items():
            if key not in defaults:
                continue
            if value is None and defaults[key] is not None:
                continue
            clean[key] = value
        cfg = cls(**clean)
        # keep aliases in sync
        cfg.fast_model = cfg.light_model
        cfg.model = cfg.deep_model
        cfg.quick_max_tokens = cfg.light_max_tokens
        return cfg

    @property
    def models(self) -> dict:
        return {"light": self.light_model, "moderate": self.moderate_model, "deep": self.deep_model}

    def choose_model(self, text: str) -> str:
        low = (text or "").lower()
        force_deep = any(hint in low for hint in DEEP_HINTS)
        wants_moderate = any(hint in low for hint in MODERATE_HINTS)
        if not self.auto_route:
            if force_deep:
                return self.deep_model
            if wants_moderate or len(text) > 180:
                return self.moderate_model
            return self.light_model
        # auto routing by complexity
        if force_deep or len(text) > 420 or low.count("?") >= 3:
            return self.deep_model
        if wants_moderate or len(text) > 140 or low.count("?") >= 2 or "\n" in text:
            return self.moderate_model
        return self.light_model

    def model_label(self, model: str) -> str:
        if model == self.deep_model:
            return "deep"
        if model == self.moderate_model:
            return "moderate"
        if model == self.light_model:
            return "light"
        # fallback by size hints
        m = (model or "").lower()
        if "14" in m or "deep" in m:
            return "deep"
        if "7" in m or "moderate" in m or "medium" in m:
            return "moderate"
        return "light"

    def max_tokens_for(self, model: str) -> int:
        label = self.model_label(model)
        if label == "deep":
            return self.deep_max_tokens
        if label == "moderate":
            return self.moderate_max_tokens
        return self.light_max_tokens
