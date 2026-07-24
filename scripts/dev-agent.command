#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
python_cmd="python3"
if command -v python3.12 >/dev/null 2>&1; then
  python_cmd="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  python_cmd="python3.11"
fi
if [[ ! -x agent/.venv/bin/python ]]; then
  "$python_cmd" -m venv agent/.venv
  agent/.venv/bin/pip install -r agent/requirements-macos.txt
fi
export SRT_AGENT_ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
exec agent/.venv/bin/python -m agent.app
