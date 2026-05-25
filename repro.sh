#!/usr/bin/env bash
# Reproducible PoW benchmark: capture environment, build, run, dump JSON.
#
# Usage:
#   ./repro.sh                  # default: --start 6 --max 10 --runs 30 --target 60
#   ./repro.sh --runs 50        # any pow-bench flag after --
#   OUT_DIR=/tmp/results ./repro.sh
#
# Writes:
#   results/env-<host>-<stamp>.txt   — full hardware + OS + toolchain snapshot
#   results/bench-<host>-<stamp>.json — raw per-run timings + summary stats
#
# Re-run on the same hardware after changes to verify reproducibility.

set -euo pipefail

# Pull rustup's cargo into PATH if installed (non-login shells skip ~/.profile).
if [[ -f "$HOME/.cargo/env" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/.cargo/env"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUST_DIR="$REPO_ROOT/rust"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/results}"
mkdir -p "$OUT_DIR"

HOST="$(hostname -s 2>/dev/null || hostname)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTFILE="$OUT_DIR/bench-${HOST}-${STAMP}.json"
ENVFILE="$OUT_DIR/env-${HOST}-${STAMP}.txt"

echo "============================================================"
echo " Capturing environment → $ENVFILE"
echo "============================================================"
{
  echo "# date"
  date -u +%Y-%m-%dT%H:%M:%SZ
  echo
  echo "# uname"
  uname -a
  echo
  if [[ -f /etc/os-release ]]; then
    echo "# /etc/os-release"
    cat /etc/os-release
    echo
  fi
  echo "# CPU"
  case "$(uname)" in
    Linux)
      lscpu 2>/dev/null || cat /proc/cpuinfo | head -30
      echo
      echo "# Scaling governor (per-CPU)"
      for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        [[ -r $f ]] && echo "$f = $(cat "$f")"
      done | sort -u || true
      echo
      echo "# Turbo / boost state"
      if [[ -r /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
        echo "intel_pstate/no_turbo = $(cat /sys/devices/system/cpu/intel_pstate/no_turbo)"
      fi
      if [[ -r /sys/devices/system/cpu/cpufreq/boost ]]; then
        echo "cpufreq/boost = $(cat /sys/devices/system/cpu/cpufreq/boost)"
      fi
      echo
      echo "# Microcode"
      grep -m1 microcode /proc/cpuinfo || true
      echo
      echo "# Memory"
      free -h 2>/dev/null || true
      ;;
    Darwin)
      sysctl -n machdep.cpu.brand_string
      sysctl hw.model hw.ncpu hw.physicalcpu hw.logicalcpu 2>/dev/null
      sysctl hw.memsize 2>/dev/null
      ;;
    *)
      echo "unknown OS, skipping CPU details"
      ;;
  esac
  echo
  echo "# rustc"
  rustc --version --verbose 2>/dev/null || echo "rustc not found"
  echo
  echo "# cargo"
  cargo --version 2>/dev/null || echo "cargo not found"
} | tee "$ENVFILE"

echo
echo "============================================================"
echo " Building (release)"
echo "============================================================"
cd "$RUST_DIR"

cargo build --release

echo
echo "============================================================"
echo " Running benchmark → $OUTFILE"
echo "============================================================"
# Forward any extra args. Defaults are conservative for a 30-min run.
./target/release/pow-bench \
  --start "${START:-6}" \
  --max   "${MAX:-10}" \
  --runs  "${RUNS:-30}" \
  --target "${TARGET:-60}" \
  --json  "$OUTFILE" \
  "$@"

echo
echo "============================================================"
echo " Done."
echo "  Environment : $ENVFILE"
echo "  Raw results : $OUTFILE"
echo
echo " Analyse in the notebook:"
echo "   jupyter notebook analysis/explore_results.ipynb"
echo "============================================================"
