#!/usr/bin/env bash
# Start Ada's cloud-profile web dashboard without changing the local launcher.
#
# Configure ADA_DATABASE_URL in the environment or in a local, ignored .env file.
# See .env.example for the expected settings.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -f .env ]]; then
  # .env is a trusted, local shell-style config file and is ignored by Git.
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export ADA_PROFILE=cloud
export ADA_OLLAMA_HOST="${ADA_OLLAMA_HOST:-${OLLAMA_HOST:-http://127.0.0.1:11434}}"

if [[ -z "${ADA_DATABASE_URL:-${DATABASE_URL:-}}" ]]; then
  cat >&2 <<'EOF'
Cloud mode needs a PostgreSQL connection URL.

Set ADA_DATABASE_URL before starting, or copy .env.example to .env and edit it.
Example format:
  postgresql://ada:YOUR_PASSWORD@127.0.0.1:5432/ada
EOF
  exit 1
fi
export ADA_DATABASE_URL="${ADA_DATABASE_URL:-$DATABASE_URL}"

if [[ ! -x .venv/bin/python ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required. Install it, then run this script again." >&2
    exit 1
  fi
  echo "Creating the project virtual environment..."
  python3 -m venv .venv
fi

STAMP=".venv/.requirements.stamp"
if [[ ! -f "$STAMP" || requirements.txt -nt "$STAMP" ]]; then
  echo "Installing Ada dependencies..."
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

if ! .venv/bin/python - <<'PY'
import json
import os
import sys
from urllib.error import URLError
from urllib.request import urlopen

try:
    import psycopg
except ImportError as error:
    print(f"PostgreSQL support is missing: {error}", file=sys.stderr)
    sys.exit(1)

try:
    with psycopg.connect(os.environ["ADA_DATABASE_URL"], connect_timeout=3) as connection:
        connection.execute("SELECT 1")
except psycopg.Error as error:
    print(f"PostgreSQL connection failed: {error}", file=sys.stderr)
    print("Check that the server is running and ADA_DATABASE_URL is correct.", file=sys.stderr)
    sys.exit(1)

ollama_url = os.environ["ADA_OLLAMA_HOST"].rstrip("/") + "/api/tags"
try:
    with urlopen(ollama_url, timeout=3) as response:
        models = json.load(response).get("models", [])
except (OSError, URLError, ValueError) as error:
    print(f"Ollama is unavailable at the configured ADA_OLLAMA_HOST: {error}", file=sys.stderr)
    print("Start Ollama or set ADA_OLLAMA_HOST to a reachable Ollama server.", file=sys.stderr)
    sys.exit(1)

from ada.config import Config
from ada.rag import EMBEDDING_MODEL

required_models = [Config.load().cloud_model, EMBEDDING_MODEL]
available_models = {
    item.get("name") or item.get("model")
    for item in models
}
for model in tuple(available_models):
    if model and model.endswith(":latest"):
        available_models.add(model.removesuffix(":latest"))
missing_models = [model for model in required_models if model not in available_models]
if missing_models:
    for model in missing_models:
        print(f"Required model {model!r} is not available in Ollama.", file=sys.stderr)
        print(f"Download it with: ollama pull {model}", file=sys.stderr)
    sys.exit(1)
PY
then
  exit 1
fi

echo "Checking and, if needed, ingesting the local Markdown corpus..."
.venv/bin/python -m ingest.ingest --if-empty

echo "Starting Ada Cloud at http://127.0.0.1:${ADA_WEB_PORT:-8765}/"
exec .venv/bin/python -m ada.web
