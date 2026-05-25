# pow — single-machine SHA-256 Proof-of-Work benchmark

[![CI](https://github.com/danilkiff/pow/actions/workflows/ci.yml/badge.svg)](https://github.com/danilkiff/pow/actions/workflows/ci.yml)
[![License: MIT / Apache-2.0](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](#license)

This repository contains two implementations of the same SHA-256
proof-of-work task:

- Python reference solver and benchmark (`hashlib`, single thread).
- Rust solver and benchmark (`sha2`, SHA-NI when available, `rayon`).

The analysis source of truth is
[`analysis/explore_results.ipynb`](analysis/explore_results.ipynb). The
top-level README is a file and command reference.

## Reference Results

Reference data from **AMD Ryzen 9 5950X** (Zen 3, 16C/32T), Ubuntu 24.04,
rustc 1.95, 60-second target per solve, configured for 30 runs per N:

| Implementation                 | Calibrated H/s     | Max N in 60 s | Speedup vs Python |
| ------------------------------ | ------------------:| -------------:| -----------------:|
| Python (single thread)         |      ~1 730 000    |             6 |              1.0× |
| Rust + SHA-NI, single thread   |      ~56 000 000   |         —[^1] |               33× |
| **Rust + SHA-NI, 32 threads**  |  **~1 210 000 000**|         **8** |          **700×** |

[^1]: The single-thread Rust row is a calibration result only. There is no
    separate 60-second per-N sweep for this mode in `results/`, so the table
    does not report a measured max N.

The raw JSON files in [`results/`](results/) contain the per-run data and
actual run counts.

## Protocol

- Hash input: `sha256(challenge_token || ascii_decimal(nonce))`.
- Difficulty: `N` leading hex zero digits in the SHA-256 digest.
- Nonce type: unsigned integer, encoded as ASCII decimal.
- Solver result: `(nonce, attempts, elapsed_secs, digest)`.
- Verification: recompute the digest and count leading hex zeros.

Benchmark methodology, statistical model, estimator choice, and plots are
documented in [`analysis/explore_results.ipynb`](analysis/explore_results.ipynb).

`repro.sh` writes `results/bench-*.json` and `results/env-*.txt`. The
notebook reads the JSON files. The checked-in `.ipynb` is kept without
execution outputs. Local HTML/PDF exports are gitignored.

## Reproducing the numbers

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

Dependency state: Python dependencies are locked by [`python/uv.lock`](python/uv.lock).
The Rust toolchain is pinned by [`rust-toolchain.toml`](rust-toolchain.toml);
`rust/Cargo.lock` is not tracked in this repository, so exact crate versions
are resolved by Cargo when dependencies are fetched.

## Analysis notebook

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

The notebook is the methodology and analysis document. It reads every
`results/bench-*.json` (local runs plus checked-in reference runs), and
shows:

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
