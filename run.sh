#!/usr/bin/env bash
# InEra All-in-One Plugins — start on Linux / macOS
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d "$HOME/.inera-venv" ]; then
  echo "Creating virtual environment in ~/.inera-venv ..."
  "$PY" -m venv "$HOME/.inera-venv"
fi
. "$HOME/.inera-venv/bin/activate"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Optional system tools: ffmpeg (video/audio), espeak-ng (voices), tesseract-ocr (OCR), libreoffice (Office->PDF)."
echo "Starting InEra on http://localhost:${INERA_PORT:-8000}"
exec python main.py
