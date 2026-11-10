#!/usr/bin/env python3
"""Check that everything Ada needs is installed and working.

    python -m ada.check          quick health check
    python -m ada.check --warm   also download/preload models

Or use ./start.sh --check.
"""

from __future__ import annotations

import importlib
import shutil
import sys

import httpx

from .config import ROOT, Config
from .skills import SkillStore

OK = "[ ok ]"
FAIL = "[fail]"
WARN = "[warn]"
problems = 0


def report(status: str, label: str, detail: str = "") -> None:
    global problems
    if status == FAIL:
        problems += 1
    suffix = f"  {detail}" if detail else ""
    print(f"{status} {label}{suffix}")


def check_python() -> None:
    if sys.version_info >= (3, 10):
        report(OK, "python", sys.version.split()[0])
    else:
        report(FAIL, "python", "3.10 or newer is required")


def check_packages() -> None:
    packages = ["ollama", "piper", "sounddevice", "numpy", "faster_whisper", "ddgs", "httpx"]
    for name in packages:
        try:
            importlib.import_module(name)
            report(OK, f"package {name}")
        except Exception as err:
            report(FAIL, f"package {name}", f"{type(err).__name__}: {err}")


def check_ollama(config: Config) -> None:
    if not shutil.which("ollama"):
        report(FAIL, "ollama installed", "get it from https://ollama.com")
        return
    report(OK, "ollama installed")
    try:
        import ollama

        listed = ollama.list()
        models = {m.model for m in listed.models}
    except Exception as err:
        report(FAIL, "ollama server", f"{type(err).__name__}: {err} (try: ollama serve)")
        return
    report(OK, "ollama server", f"{len(models)} model(s)")
    for label, name in (("quick model", config.fast_model), ("deep model", config.model)):
        if name in models:
            report(OK, label, name)
        elif label.startswith("deep"):
            report(WARN, label, f"{name} optional for /deep (ollama pull {name})")
        else:
            report(FAIL, label, f"{name} missing (ollama pull {name})")


def check_voices(config: Config) -> None:
    voices = ROOT / "assets" / "voices"
    model = voices / f"{config.voice}.onnx"
    if model.exists():
        report(OK, "tts voice", config.voice)
    else:
        report(FAIL, "tts voice", f"{model.name} missing (./scripts/get-voices.sh)")


def check_skills(config: Config) -> None:
    try:
        store = SkillStore(config.skills_dir)
        report(OK, "skills", f"{len(store)} saved")
    except Exception as err:
        report(WARN, "skills", f"{type(err).__name__}: {err}")


def check_web(config: Config) -> None:
    if not config.web_enabled:
        report(OK, "dashboard", "disabled")
        return
    if (ROOT / "web" / "index.html").exists():
        report(OK, "dashboard", f"http://{config.web_host}:{config.web_port}")
    else:
        report(WARN, "dashboard", "web/index.html missing")


def check_audio(config: Config) -> None:
    try:
        import sounddevice as sd
    except Exception as err:
        report(FAIL, "sounddevice", str(err))
        return
    try:
        default_in, default_out = sd.default.device
        devices = sd.query_devices()
        in_name = devices[default_in]["name"] if default_in is not None and default_in >= 0 else "?"
        out_name = devices[default_out]["name"] if default_out is not None and default_out >= 0 else "?"
        report(OK, "default output", out_name)
        report(OK, "default input", in_name)
        if "HDMI" in out_name:
            report(WARN, "audio output", "default looks like HDMI; set output_device in config.json")
    except Exception as err:
        report(WARN, "audio devices", f"{type(err).__name__}: {err}")


def check_internet() -> None:
    try:
        response = httpx.get("https://duckduckgo.com", timeout=10, follow_redirects=True)
        report(OK, "internet", f"HTTP {response.status_code}")
    except Exception as err:
        report(WARN, "internet", f"{type(err).__name__}: {err}")


def warm(config: Config) -> None:
    print("\nWarming up models (this may download several hundred MB)…")
    try:
        import ollama

        ollama.chat(
            model=config.fast_model,
            messages=[{"role": "user", "content": "Hello"}],
            options={"num_predict": 1, "num_ctx": 512},
            keep_alive=config.keep_alive,
        )
        report(OK, "warm quick model", config.fast_model)
    except Exception as err:
        report(FAIL, "warm quick model", f"{type(err).__name__}: {err}")

    try:
        from faster_whisper import WhisperModel

        WhisperModel(config.whisper_model, device="cpu", compute_type="int8")
        report(OK, "warm speech model", config.whisper_model)
    except Exception as err:
        report(FAIL, "warm speech model", f"{type(err).__name__}: {err}")


def main() -> int:
    config = Config.load()
    print(f"Ada health check — user={config.user_name}, voice={config.voice}\n")
    check_python()
    check_packages()
    check_ollama(config)
    check_voices(config)
    check_skills(config)
    check_web(config)
    check_audio(config)
    check_internet()
    if "--warm" in sys.argv:
        warm(config)
    print()
    if problems:
        print(f"{problems} problem(s) found.")
        return 1
    print("Everything looks good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
