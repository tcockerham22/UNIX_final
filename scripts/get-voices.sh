#!/usr/bin/env bash
# Downloads a few British English female Piper voices into assets/voices so you can audition them.
# Safe to re-run: files you already have are skipped.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p assets/voices

BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB"

# folder/quality/voice-name
VOICES=(
  "southern_english_female/low/en_GB-southern_english_female-low"
  "alba/medium/en_GB-alba-medium"
  "cori/medium/en_GB-cori-medium"
  "jenny_dioco/medium/en_GB-jenny_dioco-medium"
)

for path in "${VOICES[@]}"; do
  name="$(basename "$path")"
  for ext in onnx onnx.json; do
    target="assets/voices/$name.$ext"
    if [ -f "$target" ]; then
      echo "Have $target"
      continue
    fi
    echo "Downloading $target ..."
    curl -L --fail --progress-bar -o "$target.part" "$BASE/$path.$ext"
    mv "$target.part" "$target"
  done
done

echo
echo "Done. Audition them with:  source .venv/bin/activate && python -m ada.voice"
