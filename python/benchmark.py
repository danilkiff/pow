"""PoW benchmark for the Python reference. Sweeps n_zeros, records raw
per-run timings, and optionally dumps the result in the same JSON schema
as the Rust `pow-bench` so both feed the analysis notebook.

Headline metric: max N whose median solve time fits the --target budget."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pow import solve


@dataclass
class NSummary:
    n_zeros: int
    runs: int
    attempts: list[int]
    elapsed: list[float]

    @property
    def mean_elapsed(self) -> float:
        return statistics.mean(self.elapsed)

    @property
    def median_elapsed(self) -> float:
        return percentile(self.elapsed, 0.50)

    @property
    def p95_elapsed(self) -> float:
        return percentile(self.elapsed, 0.95)

    @property
    def p99_elapsed(self) -> float:
        return percentile(self.elapsed, 0.99)

    @property
    def min_elapsed(self) -> float:
        return min(self.elapsed) if self.elapsed else 0.0

    @property
    def max_elapsed(self) -> float:
        return max(self.elapsed) if self.elapsed else 0.0

    @property
    def stddev_elapsed(self) -> float:
        return statistics.stdev(self.elapsed) if len(self.elapsed) > 1 else 0.0

    @property
    def mean_attempts(self) -> float:
        return statistics.mean(self.attempts) if self.attempts else 0.0

    @property
    def effective_hps(self) -> float:
        total_attempts = sum(self.attempts)
        total_elapsed = sum(self.elapsed)
        return total_attempts / total_elapsed if total_elapsed > 0 else 0.0


def percentile(xs: list[float], p: float) -> float:
    """Nearest-rank percentile — matches the Rust benchmark implementation."""
    if not xs:
        return 0.0
    s = sorted(xs)
    rank = max(1, int(-(-p * len(s) // 1)))  # ceil(p * n), at least 1
    return s[min(rank, len(s)) - 1]


def measure_hashrate(duration: float = 2.0) -> float:
    """Single-thread sha256 throughput on an unsolvable task."""
    token = secrets.token_bytes(16)
    attempts = 0
    t0 = time.perf_counter()
    deadline = t0 + duration
    nonce = 0
    while time.perf_counter() < deadline:
        for _ in range(10_000):
            hashlib.sha256(token + str(nonce).encode("ascii")).digest()
            nonce += 1
        attempts += 10_000
    elapsed = time.perf_counter() - t0
    return attempts / elapsed


def run_trials(n_zeros: int, runs: int, time_budget: float) -> NSummary:
    attempts: list[int] = []
    elapsed: list[float] = []
    spent = 0.0
    for _ in range(runs):
        token = secrets.token_bytes(16)
        result = solve(token, n_zeros, start_nonce=secrets.randbits(32))
        attempts.append(result.attempts)
        elapsed.append(result.elapsed)
        spent += result.elapsed
        if spent > time_budget:
            break
    return NSummary(n_zeros=n_zeros, runs=len(elapsed), attempts=attempts, elapsed=elapsed)


def fmt_int(value: float) -> str:
    return f"{int(value):,}".replace(",", " ")


def print_env() -> None:
    print("=" * 80)
    print("ENVIRONMENT")
    print("=" * 80)
    print(f"  Python      : {platform.python_version()} ({sys.implementation.name})")
    print(f"  Platform    : {platform.platform()}")
    print(f"  Processor   : {platform.processor() or platform.machine()}")
    print(f"  CPU count   : {os.cpu_count()}  (Python baseline uses 1)")
    print()


def predict_n(hps: float, target: float) -> int:
    n = 0
    while (16 ** (n + 1)) / hps < target:
        n += 1
        if n >= 16:
            break
    return n


def write_json(
    path: Path,
    args: argparse.Namespace,
    hashrate_hps: float,
    summaries: list[NSummary],
    best_n: int | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": 1,
        "timestamp_unix": int(time.time()),
        "env": {
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "rayon_threads": 1,
            "pow_version": "0.1.0",
            "python_version": platform.python_version(),
            "python_impl": sys.implementation.name,
        },
        "config": {
            "backend": "Python",
            "target_secs": float(args.target),
            "runs_per_n": int(args.runs),
            "threads": 1,
            "start": int(args.start),
            "max": int(args.max),
            "calibrate_seconds": float(args.calibrate_seconds),
        },
        "calibration": {
            "python_single_hps": int(hashrate_hps),
        },
        "results": [
            {
                "n_zeros": s.n_zeros,
                "runs": s.runs,
                "elapsed_secs": s.elapsed,
                "attempts": s.attempts,
                "stats": {
                    "mean_elapsed": s.mean_elapsed,
                    "median_elapsed": s.median_elapsed,
                    "p95_elapsed": s.p95_elapsed,
                    "p99_elapsed": s.p99_elapsed,
                    "min_elapsed": s.min_elapsed,
                    "max_elapsed": s.max_elapsed,
                    "stddev_elapsed": s.stddev_elapsed,
                    "mean_attempts": s.mean_attempts,
                    "effective_hps": s.effective_hps,
                },
            }
            for s in summaries
        ],
        "max_n_under_target": best_n,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="PoW benchmark (Python baseline)")
    parser.add_argument("--start", type=int, default=4, help="starting n_zeros")
    parser.add_argument("--max", type=int, default=7, help="upper bound on n_zeros")
    parser.add_argument("--runs", type=int, default=30, help="trials per n_zeros")
    parser.add_argument(
        "--target", type=float, default=60.0, help="target budget per solve, seconds"
    )
    parser.add_argument(
        "--per-n-budget",
        type=float,
        default=None,
        help="wall-clock cap for all runs at one N (default = max(3 x target, 30s))",
    )
    parser.add_argument(
        "--calibrate-seconds",
        type=float,
        default=2.0,
        help="hashrate calibration duration in seconds",
    )
    parser.add_argument("--json", type=Path, default=None, help="dump structured results here")
    args = parser.parse_args()

    print_env()

    print("=" * 80)
    print(f"CALIBRATION ({args.calibrate_seconds:.1f}s of empty sha256 loop)")
    print("=" * 80)
    hps = measure_hashrate(args.calibrate_seconds)
    print(f"  python single-thread H/s : {fmt_int(hps)}")
    predicted_n = predict_n(hps, args.target)
    print(f"  Predicted N              : ~{predicted_n} hex zeros should fit in {args.target:.0f}s")
    print()

    print("=" * 80)
    print(f"BENCHMARK (Python, target = {args.target:.0f}s, runs per N = {args.runs})")
    print("=" * 80)
    header = (
        f"{'N':>3} | {'runs':>4} | {'mean t,s':>9} | {'median t,s':>10} | "
        f"{'p95 t,s':>8} | {'max t,s':>8} | {'sigma':>8} | {'H/s':>14}"
    )
    print(header)
    print("-" * len(header))

    best_n: int | None = None
    per_n_budget = (
        args.per_n_budget if args.per_n_budget is not None else max(args.target * 3.0, 30.0)
    )
    summaries: list[NSummary] = []

    for n_zeros in range(args.start, args.max + 1):
        s = run_trials(n_zeros, args.runs, per_n_budget)
        summaries.append(s)
        print(
            f"{s.n_zeros:>3} | {s.runs:>4} | {s.mean_elapsed:>9.3f} | "
            f"{s.median_elapsed:>10.3f} | {s.p95_elapsed:>8.3f} | "
            f"{s.max_elapsed:>8.3f} | {s.stddev_elapsed:>8.3f} | "
            f"{fmt_int(s.effective_hps):>14}",
            flush=True,
        )
        if s.median_elapsed <= args.target:
            best_n = s.n_zeros
        if s.mean_elapsed > args.target * 2:
            print(f"  (stop: mean elapsed {s.mean_elapsed:.1f}s > 2 x target)")
            break

    print()
    print("=" * 80)
    print("RESULT")
    print("=" * 80)
    if best_n is None:
        print(f"  Even N={args.start} exceeds {args.target:.0f}s median.")
    else:
        print(
            f"  Max N such that median solve time <= {args.target:.0f}s: "
            f"N = {best_n} hex zeros (~{fmt_int(16**best_n)} expected attempts)"
        )

    if args.json is not None:
        write_json(args.json, args, hps, summaries, best_n)
        print(f"  JSON written to {args.json}")


if __name__ == "__main__":
    main()
