"""PoW benchmark: measure solve time as n_zeros (hex zeros) grows and find
the maximum n_zeros whose solve still fits within one minute."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import secrets
import statistics
import sys
import time
from dataclasses import dataclass

from pow import solve


@dataclass
class TrialStats:
    n_zeros: int
    runs: int
    attempts: list[int]
    elapsed: list[float]

    @property
    def mean_attempts(self) -> float:
        return statistics.mean(self.attempts)

    @property
    def mean_elapsed(self) -> float:
        return statistics.mean(self.elapsed)

    @property
    def median_elapsed(self) -> float:
        return statistics.median(self.elapsed)

    @property
    def max_elapsed(self) -> float:
        return max(self.elapsed)

    @property
    def hashes_per_second(self) -> float:
        total_attempts = sum(self.attempts)
        total_elapsed = sum(self.elapsed)
        return total_attempts / total_elapsed if total_elapsed > 0 else 0.0


def measure_hashrate(duration: float = 2.0) -> float:
    """Calibration: how many sha256 calls per second on an unsolvable task."""
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


def run_trials(n_zeros: int, runs: int, time_budget: float) -> TrialStats:
    """Run several trials at the given n_zeros, stopping early if the
    cumulative wall-clock exceeds time_budget."""
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
    return TrialStats(
        n_zeros=n_zeros,
        runs=len(elapsed),
        attempts=attempts,
        elapsed=elapsed,
    )


def fmt_int(value: float) -> str:
    return f"{int(value):,}".replace(",", " ")


def print_env() -> None:
    print("=" * 76)
    print("ENVIRONMENT")
    print("=" * 76)
    print(f"  Python      : {platform.python_version()} ({sys.implementation.name})")
    print(f"  Platform    : {platform.platform()}")
    print(f"  Processor   : {platform.processor() or platform.machine()}")
    print(f"  CPU count   : {os.cpu_count()}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="PoW benchmark (hex zeros)")
    parser.add_argument("--start", type=int, default=1, help="starting n_zeros")
    parser.add_argument("--max", type=int, default=10, help="upper bound on n_zeros")
    parser.add_argument("--runs", type=int, default=5, help="trials per n_zeros")
    parser.add_argument("--target", type=float, default=60.0, help="target budget, seconds")
    parser.add_argument(
        "--calibrate-seconds",
        type=float,
        default=2.0,
        help="hashrate calibration duration in seconds",
    )
    args = parser.parse_args()

    print_env()

    print("=" * 76)
    print(f"CALIBRATION ({args.calibrate_seconds:.1f}s of empty sha256 loop)")
    print("=" * 76)
    hps = measure_hashrate(args.calibrate_seconds)
    print(f"  Hashrate    : {fmt_int(hps)} H/s")
    # Expected attempts for n_zeros leading hex zeros: 16^n_zeros
    predicted_n = 0
    while (16**predicted_n) / hps < args.target:
        predicted_n += 1
    predicted_n -= 1
    print(f"  Predicted N : ~{predicted_n} hex zeros should fit in {args.target:.0f}s")
    print()

    print("=" * 76)
    print(f"BENCHMARK (target budget = {args.target:.0f}s, runs per N = {args.runs})")
    print("=" * 76)
    header = (
        f"{'N':>3} | {'runs':>4} | {'mean attempts':>15} | "
        f"{'mean t,s':>10} | {'median t,s':>11} | {'max t,s':>9} | {'H/s':>14}"
    )
    print(header)
    print("-" * len(header))

    best_n = None
    per_n_budget = max(args.target * 1.5, 30.0)

    for n_zeros in range(args.start, args.max + 1):
        stats = run_trials(n_zeros, args.runs, per_n_budget)
        line = (
            f"{n_zeros:>3} | {stats.runs:>4} | {fmt_int(stats.mean_attempts):>15} | "
            f"{stats.mean_elapsed:>10.3f} | {stats.median_elapsed:>11.3f} | "
            f"{stats.max_elapsed:>9.3f} | {fmt_int(stats.hashes_per_second):>14}"
        )
        print(line, flush=True)

        if stats.mean_elapsed <= args.target:
            best_n = n_zeros

        if stats.mean_elapsed > args.target * 2:
            print(f"  (stop: mean elapsed {stats.mean_elapsed:.1f}s > 2 x target)")
            break

    print()
    print("=" * 76)
    print("RESULT")
    print("=" * 76)
    if best_n is None:
        print(f"  Even N={args.start} exceeds {args.target:.0f}s on average.")
    else:
        print(
            f"  Max N such that mean solve time <= {args.target:.0f}s: "
            f"N = {best_n} hex zeros (~{fmt_int(16**best_n)} expected attempts)"
        )


if __name__ == "__main__":
    main()
