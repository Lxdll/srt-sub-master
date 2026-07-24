#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
if [[ ! -x server/.venv/bin/python ]]; then
  python3 -m venv server/.venv
  server/.venv/bin/pip install -r server/requirements-dev.txt
fi
exec server/.venv/bin/python -m uvicorn server.app.main:app --reload --port 8000
