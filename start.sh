#!/usr/bin/env bash
# Starts Ada: sets up a virtual environment, checks Ollama, pulls models if needed, then runs her.
#
# Usage:
#   ./start.sh                    text chat with spoken replies
#   ./start.sh --voice            press Enter to talk instead of typing
#   ./start.sh --hands-free       say "Ada, ..." to talk hands-free
#   ./start.sh --hands-free --any hands-free without the wake word
#   ./start.sh --check            run the health check
#   ./start.sh --warmup           preload models and speech recognition, then exit
#   ./start.sh --no-web           disable the local dashboard
#
# Dashboard: http://127.0.0.1:8765 (web_host / web_port in config.json)
# Skills are Markdown files in assets/skills. Ask Ada to learn or update one, or edit them directly.
#
# Environment overrides:
#   ADA_MODEL=...  ADA_FAST_MODEL=...  ADA_VOICE=...  ADA_USER_NAME=...
#   ADA_WAKE_WORDS="ada,lovelace"  ADA_SKILLS_DIR=...
#   ADA_PULL_DEEP=1  also download the deep model at startup

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR=".venv"

# 1. Python
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Python 3 is not installed. Please install it and try again." >&2
  exit 1
fi

# 2. Virtual environment and dependencies
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Reinstall only when requirements.txt has changed
STAMP="$VENV_DIR/.requirements.stamp"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "Installing dependencies (first run may take a few minutes)..."
  pip install --quiet --upgrade pip || true
  pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

# 3. Ollama installed?
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Get it from https://ollama.com and run this again." >&2
  exit 1
fi

# 4. Ollama running? Try to start it in the background if not.
if ! ollama list >/dev/null 2>&1; then
  echo "Starting Ollama..."
  nohup ollama serve >/dev/null 2>&1 &
  for _ in $(seq 1 20); do
    sleep 1
    if ollama list >/dev/null 2>&1; then break; fi
  done
  if ! ollama list >/dev/null 2>&1; then
    echo "Could not reach Ollama. Try starting it manually with: ollama serve" >&2
    exit 1
  fi
fi

# 5. Models downloaded? Read model names from config.json unless the env overrides them.
config_value() {
  python -c "from ada.config import Config; print(Config.load().$1)" 2>/dev/null || true
}

export ADA_FAST_MODEL="${ADA_FAST_MODEL:-$(config_value fast_model)}"
export ADA_MODEL="${ADA_MODEL:-$(config_value model)}"

pull_model() {
  local name="$1"
  if [ -z "$name" ]; then
    return
  fi
  if ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$name"; then
    echo "Downloading model $name (first run only)..."
    ollama pull "$name"
  fi
}

# The health check does not need to pull models.
if [ "${1:-}" = "--check" ]; then
  shift
  exec python -m ada.check "$@"
fi

# The quick model is used every day; the deep model only for /deep, so pull it on demand.
pull_model "$ADA_FAST_MODEL"
if [ "$ADA_MODEL" = "$ADA_FAST_MODEL" ] || [ "${ADA_PULL_DEEP:-0}" = "1" ]; then
  pull_model "$ADA_MODEL"
elif ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$ADA_MODEL"; then
  echo "Note: deep model $ADA_MODEL is not downloaded. To use /deep later: ollama pull $ADA_MODEL"
fi

# 6. Launch Ada
exec python -m ada "$@"
