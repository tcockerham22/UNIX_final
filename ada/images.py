"""Image and diagram generation for Ada.

Two backends:
  * Stable Diffusion WebUI-compatible HTTP API (set image_api_url) for raster images.
  * The local Ollama model writing self-contained SVG, rendered to PNG with headless
    Chromium. This is the offline default and works well for diagrams and vector art.
"""

from __future__ import annotations

import base64
import re
import subprocess
import time
from pathlib import Path
from shutil import which

import httpx
import ollama

from .config import Config
from .events import emit

# Reject anything that could execute code or pull remote resources into the renderer.
_UNSAFE_SVG = re.compile(
    r"(?is)<\s*(script|foreignObject|iframe|object|embed)\b"
    r"|\son[a-z]+\s*="
    r"|javascript:|data:text/html|@import|<![dD][oO][cC][tT][yY][pP][eE]"
)


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48]
    return value or "image"


def _output_dir(config: Config) -> Path:
    path = Path(getattr(config, "image_dir", "") or "data/generated").expanduser()
    if not path.is_absolute():
        path = Path(getattr(config, "workspace", None) or Path.cwd()) / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _svg_prompt(prompt: str, kind: str, size: int) -> str:
    if kind == "diagram":
        return (
            "Create a clear, well-structured diagram as ONE self-contained SVG.\n"
            f"Subject: {prompt}\n\n"
            "Requirements:\n"
            "- Return only the SVG markup. No markdown, no commentary, no XML declaration.\n"
            f'- Use width="{size}" height="{size}" viewBox="0 0 {size} {size}".\n'
            "- Dark background (#0b1013), light text (#eaf7ff), cyan (#7ff5d8) and "
            "amber (#ffc86a) accents.\n"
            "- Use rects with rounded corners, lines, arrowheads, circles and text. "
            "Include a title, readable labels and a small legend.\n"
            "- Lay elements out without overlapping. Center the composition.\n"
            "- No scripts, no external images, no foreignObject, no CSS imports."
        )
    return (
        "Act as an expert illustrator and create a polished, self-contained vector "
        "illustration as ONE SVG.\n"
        f"Subject: {prompt}\n\n"
        "Requirements:\n"
        "- Return only the SVG markup. No markdown, no commentary, no XML declaration.\n"
        f'- Use width="{size}" height="{size}" viewBox="0 0 {size} {size}".\n'
        "- Preserve the requested subject and details; do not add unrelated objects or labels.\n"
        "- Build a deliberate composition with one clear focal point, balanced negative "
        "space, and a readable silhouette.\n"
        "- Choose a cohesive palette and background suited to the subject; do not default "
        "to a dark background.\n"
        "- Create depth with layered shapes, considered lighting, highlights, shadows, "
        "gradients, and restrained texture where useful.\n"
        "- Make shapes and details specific to the subject rather than relying on generic "
        "decorative filler. Keep fine details crisp and the overall image visually legible.\n"
        "- No text unless the subject explicitly asks for it.\n"
        "- Use valid SVG elements and attributes. No scripts, external images, "
        "foreignObject, or CSS imports."
    )


def _clean_svg(text: str, size: int) -> str | None:
    match = re.search(r"(?is)<svg[\s\S]*?</svg>", text or "")
    if not match:
        return None
    svg = match.group(0).strip()
    if _UNSAFE_SVG.search(svg):
        return None
    closing = svg.find(">")
    if closing < 0:
        return None
    tag = svg[: closing + 1]
    additions = ""
    if not re.search(r"(?i)\bviewBox\s*=", tag):
        additions += f' viewBox="0 0 {size} {size}"'
    if not re.search(r"(?i)\bwidth\s*=", tag):
        additions += f' width="{size}"'
    if not re.search(r"(?i)\bheight\s*=", tag):
        additions += f' height="{size}"'
    if additions:
        svg = tag[:-1] + additions + ">" + svg[closing + 1 :]
    return svg


def _model_svg(prompt: str, config: Config, kind: str) -> str:
    model = (getattr(config, "image_model", "") or "").strip() or config.deep_model
    size = max(256, min(2048, int(getattr(config, "image_size", 1024) or 1024)))
    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": _svg_prompt(prompt, kind, size)}],
        options={
            "temperature": 0.35,
            "num_ctx": min(getattr(config, "num_ctx", 4096), 8192),
            "num_predict": int(getattr(config, "image_max_tokens", 4096) or 4096),
        },
        keep_alive=config.keep_alive,
    )
    if "qwen3" in (model or "").lower():
        kwargs["think"] = False
    response = ollama.chat(**kwargs)
    message = response.get("message", {}) if isinstance(response, dict) else getattr(response, "message", {})
    if isinstance(message, dict):
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""
    else:
        content = getattr(message, "content", "") or ""
        thinking = getattr(message, "thinking", "") or ""
    if not isinstance(content, str):
        content = ""
    if not content.strip() and isinstance(thinking, str):
        content = thinking
    return content


def _sdwebui_image(prompt: str, config: Config) -> bytes | None:
    base = (getattr(config, "image_api_url", "") or "").strip().rstrip("/")
    if not base:
        return None
    size = max(256, min(2048, int(getattr(config, "image_size", 1024) or 1024)))
    payload = {
        "prompt": prompt,
        "negative_prompt": getattr(config, "image_negative_prompt", ""),
        "width": size,
        "height": size,
        "steps": max(1, min(150, int(getattr(config, "image_steps", 30) or 30))),
        "cfg_scale": 7,
        "sampler_index": (getattr(config, "image_sampler", "") or "DPM++ 2M Karras").strip(),
    }
    response = httpx.post(base + "/sdapi/v1/txt2img", json=payload, timeout=180.0)
    response.raise_for_status()
    images = (response.json() or {}).get("images") or []
    if not images:
        return None
    return base64.b64decode(images[0])


def render_svg(svg_path: Path, png_path: Path, config: Config) -> bool:
    """Render SVG to PNG with headless Chromium. Returns False if unavailable."""
    browser = which("chromium") or which("chromium-browser") or which("google-chrome")
    if not browser:
        return False
    size = max(256, min(2048, int(getattr(config, "image_size", 1024) or 1024)))
    try:
        subprocess.run(
            [
                browser,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={size},{size}",
                f"--screenshot={png_path}",
                svg_path.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except Exception:
        return False
    return png_path.exists() and png_path.stat().st_size > 0


def generate_image(prompt: str, config: Config, kind: str = "image") -> str:
    """Generate an image/diagram, save it under image_dir, and return the path."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "ERROR: no image description provided."
    kind = "diagram" if kind == "diagram" else "image"
    # The local model writes SVG, which cannot be photorealistic. Fail clearly
    # instead of silently returning a flat vector sketch for a photo request.
    wants_photo = bool(re.search(
        r"(?i)\b(photorealistic|photo-realistic|photograph|realistic[ -]?render|studio render|render of)\b",
        prompt,
    ))
    has_api = bool(getattr(config, "image_api_url", None))
    if wants_photo and not has_api:
        return (
            "ERROR: photorealistic rendering needs an image API. Set image_api_url "
            "in config.json (e.g. http://127.0.0.1:7860 for Stable Diffusion WebUI). "
            "Without it I can only create vector art and diagrams locally."
        )
    directory = _output_dir(config)
    stamp = int(time.time() * 1000)
    name = f"{kind}-{_slug(prompt)}-{stamp}"
    png_path = directory / f"{name}.png"
    svg_path = directory / f"{name}.svg"

    if getattr(config, "image_api_url", None):
        try:
            data = _sdwebui_image(prompt, config)
            if data:
                png_path.write_bytes(data)
                emit("image", path=str(png_path), kind=kind, prompt=prompt, backend="sdwebui")
                return f"Created {kind}: {png_path}"
            if wants_photo:
                return "ERROR: the image API returned no image for this photorealistic request."
        except Exception as err:
            emit("error", message=f"image backend: {type(err).__name__}: {err}")
            if wants_photo:
                api_url = str(getattr(config, "image_api_url", "") or "").rstrip("/")
                return (
                    f"ERROR: could not generate the photorealistic image using the API at "
                    f"{api_url}. Make sure Stable Diffusion WebUI is running with its API "
                    f"enabled (for example, with --api), then try again. "
                    f"Details: {type(err).__name__}: {err}."
                )
        if not getattr(config, "image_svg_fallback", True):
            return "ERROR: image backend failed and SVG fallback is disabled."

    try:
        raw = _model_svg(prompt, config, kind)
        svg = _clean_svg(raw, int(getattr(config, "image_size", 1024) or 1024))
    except Exception as err:
        return f"ERROR: image generation failed ({type(err).__name__}: {err})."
    if not svg:
        return "ERROR: the model did not return a usable SVG. Try a simpler description."

    svg_path.write_text(svg, encoding="utf-8")
    rendered = render_svg(svg_path, png_path, config)
    final = png_path if rendered else svg_path
    emit("image", path=str(final), kind=kind, prompt=prompt, backend="svg")
    note = "" if rendered else " (PNG rendering unavailable; SVG kept)"
    return f"Created {kind}: {final}{note}"


def generate_diagram(spec: str, config: Config) -> str:
    """Generate a labelled diagram from a text specification."""
    return generate_image(spec, config, kind="diagram")
