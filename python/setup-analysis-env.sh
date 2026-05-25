#!/usr/bin/env bash
# Bootstrap the Python analysis environment used by:
#   - analysis/explore_results.ipynb
#   - jupyter nbconvert --execute
#   - VS Code's Jupyter / pytest integration
#
# Creates python/.venv via uv, installs the `analysis` and `test`
# dependency groups, and registers the kernel under the name
# `pow-analysis` (matches kernelspec.name in the notebook).
#
# Usage:
#   ./python/setup-analysis-env.sh
#
# Re-run any time pyproject.toml or uv.lock changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found. Install: https://docs.astral.sh/uv/"
  exit 1
fi

echo "→ uv sync --all-groups"
uv sync --all-groups

VENV_PY="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x $VENV_PY ]]; then
  echo "error: $VENV_PY missing after uv sync"
  exit 1
fi

echo "→ registering kernel 'pow-analysis' (user-scope)"
"$VENV_PY" -m ipykernel install \
  --user \
  --name pow-analysis \
  --display-name "Python (pow .venv)"

echo
echo "Done."
echo "  Interpreter : $VENV_PY"
echo "  Kernel name : pow-analysis"
echo
echo "  Verify : jupyter kernelspec list | grep pow-analysis"
echo "  Smoke  : uv run -- jupyter execute --kernel_name=pow-analysis \\"
echo "             ../analysis/explore_results.ipynb"
