#!/usr/bin/env bash
# Launch JupyterLab for the pow analysis notebooks.
#
# Pairs with .mcp.json so jupyter-mcp-server can attach to this instance.
# Override JUPYTER_TOKEN / JUPYTER_PORT via env; defaults match .mcp.json.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/jupyter ]]; then
  echo "error: .venv/bin/jupyter missing. Run 'uv sync --all-groups' in python/ first." >&2
  exit 1
fi

PORT="${JUPYTER_PORT:-8888}"
TOKEN="${JUPYTER_TOKEN:-pow-local}"

exec .venv/bin/jupyter lab \
  --port "$PORT" \
  --no-browser \
  --ServerApp.token="$TOKEN" \
  --ServerApp.password='' \
  --ServerApp.root_dir="$(pwd)" \
  --ServerApp.ip=127.0.0.1
