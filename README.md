# pow — single-machine SHA-256 Proof-of-Work benchmark

[![CI](https://github.com/danilkiff/pow/actions/workflows/ci.yml/badge.svg)](https://github.com/danilkiff/pow/actions/workflows/ci.yml)
[![License: MIT / Apache-2.0](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](#license)

How many leading hex zeros of `sha256(challenge_token || ascii(nonce))`
can your CPU find within one minute? This repository measures it, end
to end, with reproducible numbers and an analysis notebook.

The benchmark exists to compare three concrete things on the same problem
shape:

1. **A naïve Python baseline** — `hashlib.sha256` in a tight loop.
2. **An optimised Rust solver** — `sha2` crate (hardware **SHA-NI** when
   available) + `rayon` data parallelism.
3. **A multi-buffer Rust backend** — Intel **ISA-L Crypto**'s AVX2 8-lane
   `sha256_mb` via a small FFI shim, to see whether SIMD-batched SHA-256
   beats hardware SHA-NI on short messages (spoiler for Zen 3: it does not).

## TL;DR

Reference numbers on **AMD Ryzen 9 5950X** (Zen 3, 16C/32T), Ubuntu 24.04,
rustc 1.95, 60-second per-run budget, 30 runs per N:

| Implementation                 | Calibrated H/s     | Max N in 60 s | Speedup vs Python |
| ------------------------------ | ------------------:| -------------:| -----------------:|
| Python (single thread)         |      ~3 300 000    |             7 |              1.0× |
| Rust + SHA-NI, single thread   |      ~56 000 000   |             — |               17× |
| **Rust + SHA-NI, 32 threads**  |  **~1 210 000 000**|         **8** |          **367×** |
| Rust + ISA-L MB AVX2, 32 thr.  |       178 000 000  |             8 |               54× |

Headline numbers are medians from 30-run sweeps; raw per-run JSONs live
in [`results/`](results/) and feed the analysis notebook directly.

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
│   ├── src/mb.rs            # ISA-L Crypto multi-buffer backend (feature `mb`)
│   ├── src/pow_mb.c         # tiny C shim over ISA-L
│   ├── src/main.rs          # `pow` CLI
│   ├── src/bin/bench.rs     # `pow-bench` CLI
│   └── tests/               # proptest invariants, cross-backend checks
├── analysis/
│   └── explore_results.ipynb  # loads JSON dumps, plots, summary tables
├── results/
│   ├── bench-<host>-<stamp>-<backend>.json  # raw per-run timings + summary
│   └── env-<host>-<stamp>.txt               # CPU / OS / governor / rustc snapshot
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

**Why ASCII-decimal nonces?** It matches the convention used by
HashCash-derived schemes (PoW captchas, AT Protocol, …) and keeps the
Python and Rust implementations bit-identical at the wire level, so
either can verify the other's solution.

**Why N counts hex zeros, not bits?** Asked for by analytics — hex zeros
are what gets compared at the API boundary in the systems this benchmark
was extracted from. One hex zero = 4 bits, so the search space grows
by 16× per N.

**What the benchmark actually measures.** For each N in `[--start, --max]`:

1. Generate a random 16-byte token and a random `u64` start nonce.
2. Solve, record `attempts` and wall-clock `elapsed`.
3. Repeat up to `--runs` times, but stop early if cumulative wall-clock
   for this N exceeds `--per-n-budget` (default = 3 × target).
4. Report per-N: mean / median / p95 / max / stddev of elapsed; effective
   H/s; raw arrays of all runs.

**Statistical caveat.** Time-to-solve at fixed N follows a geometric
(approximately exponential) distribution. The mean has high variance;
the median is a much more stable estimator. We report both. For N where
mean ≈ target, only a handful of runs fit, so p95/p99 numbers there are
noise — treat with caution.

**Headline metric.** `Max N such that median ≤ --target seconds`. Median,
not mean, because the long tail of the geometric distribution distorts
the mean enough to be misleading at small sample sizes.

**Wire format.** N counts **leading hex zeros** of the SHA-256 digest
(one zero = 4 bits, so +1 to N is 16× more expected work). Nonces are
encoded as ASCII decimal and appended directly to the raw
`challenge_token` bytes — both Python and Rust use the same framing, so
a solution from either verifies under the other.

**Reproducibility loop.** `repro.sh` → `results/*.json` → notebook /
`jupyter execute`. The notebook is checked in *without* outputs (GitHub
renders the source directly); local HTML exports are gitignored.

## Reproducing the numbers

```sh
git clone <repo> && cd pow
./repro.sh
```

`repro.sh` will:

1. Snapshot CPU, OS, kernel, microcode, governor, turbo state, rustc
   version into `results/env-<host>-<stamp>.txt`.
2. Detect ISA-L Crypto and build with `--features mb` if present
   (default backend is plain SHA-NI, which has no system deps beyond rust).
3. Run `pow-bench --runs 30 --target 60 --json results/bench-…json`.
4. Print where the artifacts went.

Override defaults:

```sh
RUNS=50 TARGET=120 ./repro.sh                       # tweak primary knobs
./repro.sh -- --backend mb                          # extra pow-bench flags
START=8 MAX=11 ./repro.sh                           # narrow / widen N sweep
```

For comparable cross-machine numbers, before running:

```sh
# Linux: pin governor to 'performance' (effect varies by platform):
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

Re-running on the same hardware should match within ~5% per cell.

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

The notebook reads every `results/bench-*.json` (your own runs + any
shared by others), shows:

- per-N summary table (median, p50, p95, stddev, effective H/s);
- elapsed-time vs N on log-y with error bars (one curve per backend / host);
- empirical CDF of solve times at a chosen N, with the theoretical
  exponential overlaid;
- relative speedups across backends and hosts.

## Building manually

See [`rust/README.md`](rust/README.md) for build flags, the `mb` feature
prerequisite (ISA-L Crypto from source), and CLI usage of `pow` /
`pow-bench`.

Python reference impl:

```sh
cd python
python main.py demo 6       # solve at difficulty 6
python benchmark.py         # baseline sweep
uv run pytest               # tests
```

## Editor setup

The repo ships a VS Code workspace under `.vscode/`. On first open VS Code
will prompt to install the recommended extensions (rust-analyzer, Pylance,
ruff, jupyter, clangd, shellcheck, even-better-toml, vscode-yaml,
markdownlint, editorconfig). The settings already wire up:

- `rust-analyzer` against `rust/Cargo.toml` with `--features mb` enabled and
  `clippy -D warnings` on save, so editor diagnostics match CI;
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
cd rust && cargo test --release --features mb

# python
cd python && uv run pytest
```

Coverage is gated in CI via `cargo-llvm-cov`.

## License

Dual-licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or
  <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or
  <http://opensource.org/licenses/MIT>)

at your option.
