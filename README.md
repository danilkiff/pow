# pow — single-machine SHA-256 Proof-of-Work benchmark

[![CI](https://github.com/danilkiff/pow/actions/workflows/ci.yml/badge.svg)](https://github.com/danilkiff/pow/actions/workflows/ci.yml)
[![License: MIT / Apache-2.0](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](#license)

How many leading hex zeros of `sha256(challenge_token || ascii(nonce))`
can a single machine find within one minute? This repository contains two
implementations, benchmark CLIs, reference JSON results, and a notebook that
reads those JSON files.

The comparison is deliberately narrow:

1. **A naïve Python baseline** — `hashlib.sha256` in a tight loop.
2. **An optimized Rust solver** — `sha2` crate (hardware **SHA-NI** when
   available) + `rayon` data parallelism.

## TL;DR

Reference data from **AMD Ryzen 9 5950X** (Zen 3, 16C/32T), Ubuntu 24.04,
rustc 1.95, 60-second target per solve, configured for 30 runs per N:

| Implementation                 | Calibrated H/s     | Max N in 60 s | Speedup vs Python |
| ------------------------------ | ------------------:| -------------:| -----------------:|
| Python (single thread)         |      ~1 730 000    |             6 |              1.0× |
| Rust + SHA-NI, single thread   |      ~56 000 000   |             — |               33× |
| **Rust + SHA-NI, 32 threads**  |  **~1 210 000 000**|         **8** |          **700×** |

Headline numbers use the median solve time from sweeps on the same host
(`oniguruma`). Each sweep is configured for 30 runs per N, but the per-N
wall-clock cap can stop high difficulties earlier. The raw JSON files in
[`results/`](results/) contain the actual run counts.

N counts **leading hex zeros** of the SHA-256 digest (one zero = 4 bits),
so each +1 to N is 16× more expected work. Going from N=7 to N=8 on the
same minute budget requires a real ~16× hashrate jump.

## Repository layout

```text
pow/
├── python/         # reference solver + benchmark (CPython, hashlib)
│   ├── README.md
│   ├── pow.py      # solve / verify
│   ├── benchmark.py
│   ├── main.py
│   ├── setup-analysis-env.sh  # bootstrap .venv + register notebook kernel
│   └── tests/
├── rust/           # production benchmark
│   ├── src/lib.rs           # SHA-NI + rayon solver
│   ├── src/main.rs          # `pow` CLI
│   ├── src/bin/bench.rs     # `pow-bench` CLI
│   └── tests/               # proptest invariants
├── analysis/
│   └── explore_results.ipynb  # loads JSON dumps, plots, summary tables
├── results/
│   └── bench-<host>-<stamp>[-backend].json  # raw timings + summary
├── repro.sh        # one-command env capture + build + benchmark + JSON dump
├── rust-toolchain.toml
├── LICENSE-MIT
└── LICENSE-APACHE
```

## Methodology

**Problem statement.** Given a fixed `challenge_token` (raw bytes) and a
difficulty `N`, find any `nonce: u64` such that

```text
hex(sha256(challenge_token || ascii_decimal(nonce)))[0..N] == "0" * N
```

The solver returns `(nonce, attempts, elapsed_secs, digest)`. `verify()`
recomputes the hash and checks the leading-zero count independently.

**Why ASCII-decimal nonces?** The benchmark models APIs that append a
decimal nonce to an opaque challenge token. Python and Rust use the same
wire format, so either implementation can verify the other's solution.

**Why N counts hex zeros, not bits?** The API boundary compares hex
prefixes. One hex zero = 4 bits, so the search space grows by 16× per N.

**What the benchmark actually measures.** For each N in `[--start, --max]`:

1. Generate a random 16-byte token and a random start nonce. Rust uses a
   random `u64`; the Python baseline currently uses a random 32-bit offset.
2. Solve, record `attempts` and wall-clock `elapsed`.
3. Repeat up to `--runs` times, but stop early if cumulative wall-clock
   for this N exceeds `--per-n-budget` (default = max(3 × target, 30 s)).
4. Report per-N: mean / median / p95 / max / stddev of elapsed; effective
   H/s; raw arrays of all runs.

**Statistical caveat.** Time-to-solve at fixed N follows a geometric
(approximately exponential) distribution. The mean has high variance;
the median is a much more stable estimator. We report both. For N where
mean ≈ target, only a handful of runs fit, so p95/p99 numbers there are
unstable.

**Headline metric.** `Max N such that median ≤ --target seconds`. Median,
not mean, because the long tail of the geometric distribution distorts
the mean enough to be misleading at small sample sizes.

**Wire format.** N counts **leading hex zeros** of the SHA-256 digest
(one zero = 4 bits, so +1 to N is 16× more expected work). Nonces are
encoded as ASCII decimal and appended directly to the raw
`challenge_token` bytes — both Python and Rust use the same framing, so
a solution from either verifies under the other.

**Reproducibility loop.** `repro.sh` writes `results/bench-*.json` and
`results/env-*.txt`; the notebook reads the JSON files. The checked-in
`.ipynb` is kept without execution outputs. Local HTML/PDF exports are
gitignored.

## Reproducing the numbers

```sh
git clone <repo> && cd pow
./repro.sh
```

`repro.sh` reproduces the Rust reference sweep. It will:

1. Snapshot CPU, OS, kernel, microcode, governor, turbo state, rustc
   version into `results/env-<host>-<stamp>.txt`.
2. Build the Rust benchmark in release mode.
3. Run `pow-bench --start 6 --max 10 --runs 30 --target 60
   --json results/bench-…json`.
4. Print where the artifacts went.

Override the `repro.sh` defaults:

```sh
RUNS=50 TARGET=120 ./repro.sh                       # tweak primary knobs
START=8 MAX=11 ./repro.sh                           # narrow / widen N sweep
```

The Python baseline is run separately:

```sh
cd python
uv run python benchmark.py --start 4 --max 7 --runs 30 --target 60 \
    --json ../results/bench-$(hostname -s)-$(date -u +%Y%m%dT%H%M%SZ)-python.json
```

For comparable cross-machine numbers, before running:

```sh
# Linux: pin governor to 'performance' (effect varies by platform):
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

Low-N throughput should be stable on an idle machine. High-N cells and p95
values have high variance because fewer trials fit into the per-N cap.

Dependency state: Python dependencies are locked by [`python/uv.lock`](python/uv.lock).
The Rust toolchain is pinned by [`rust-toolchain.toml`](rust-toolchain.toml);
`rust/Cargo.lock` is not tracked in this repository, so exact crate versions
are resolved by Cargo when dependencies are fetched.

## Analysing results

The notebook expects a kernel called **`pow-analysis`** that points to a
venv with `ipykernel`, `matplotlib`, `pandas`, `numpy` installed. Bootstrap
it once:

```sh
cd python
./setup-analysis-env.sh
```

This creates `python/.venv` via `uv sync --all-groups` and registers the
kernel user-wide. The notebook's `kernelspec.name` is pinned to
`pow-analysis`, so VS Code and `jupyter nbconvert` both pick it up
without prompting.

Open `analysis/explore_results.ipynb` directly — GitHub renders `.ipynb`
files natively, and VS Code auto-selects the `pow-analysis` kernel.

To verify the notebook executes end-to-end without producing any file
output (useful in CI):

```sh
cd python && uv run -- \
    jupyter execute --kernel_name=pow-analysis \
        ../analysis/explore_results.ipynb
```

The notebook reads every `results/bench-*.json` (local runs plus checked-in
reference runs), and shows:

- per-N summary table (median, p95, stddev, effective H/s);
- elapsed-time vs N on log-y with error bars;
- empirical CDF of solve times at a chosen N, with the theoretical
  exponential overlaid.

## Building manually

See [`rust/README.md`](rust/README.md) for build flags and CLI usage of
`pow` / `pow-bench`.

Python reference impl:

```sh
cd python
uv run python main.py demo 6       # solve at difficulty 6
uv run python benchmark.py         # baseline sweep
uv run pytest               # tests
```

## Editor setup

The repo ships a VS Code workspace under `.vscode/`. On first open VS Code
will prompt to install the recommended extensions (rust-analyzer, Pylance,
ruff, jupyter, shellcheck, even-better-toml, vscode-yaml, markdownlint,
editorconfig). The settings already wire up:

- `rust-analyzer` against `rust/Cargo.toml` and `clippy -D warnings` on save,
  so editor diagnostics match CI;
- pytest discovery rooted in `python/tests`, ruff format + lint on save;
- file/search/watcher excludes for `target/`, `results/`, `__pycache__/`;
- LLDB launch configs for `pow`, `pow-bench`, and the lib test suite;
- tasks for build / test / clippy / fmt / repro / notebook execution
  (Cmd-Shift-P → "Run Task").

`.editorconfig` covers other editors with the same indent / EOL / newline
rules.

## Tests

```sh
# rust: unit + integration + proptest
cd rust && cargo test --release

# python
cd python && uv run pytest
```

CI runs Rust format/clippy/tests, Python ruff/tests, and notebook execution.
The Python job prints a coverage report. Rust coverage is generated by the
separate `coverage` workflow, which runs manually or on the weekly schedule.

## License

Dual-licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or
  <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or
  <http://opensource.org/licenses/MIT>)

at your option.
