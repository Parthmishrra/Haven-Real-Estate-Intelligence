#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  if command -v python3.12 >/dev/null; then
    python3.12 -m venv .venv
  elif command -v python3.11 >/dev/null; then
    python3.11 -m venv .venv
  else
    echo 'Install Python 3.11 or 3.12 from python.org, then run this script again.'
    exit 1
  fi
fi
[[ -f .env ]] || cp .env.example .env
.venv/bin/python -m pip install -r requirements.txt
printf '%s\n' 'Open http://127.0.0.1:8000 in your browser. Keep this terminal open.' 'Make sure Ollama is running and you have run: ollama pull llama3.2:3b'
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
