# pow — single-machine SHA-256 Proof-of-Work benchmark

[![CI](https://github.com/danilkiff/pow/actions/workflows/ci.yml/badge.svg)](https://github.com/danilkiff/pow/actions/workflows/ci.yml)
[![License: MIT / Apache-2.0](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](#license)

Two implementations of the same SHA-256 proof-of-work task:

- Python reference (`hashlib`, single thread) — [`python/`](python/).
- Rust solver (`sha2` with SHA-NI, parallel via `rayon`) — [`rust/`](rust/).

Methodology, statistical model, and plots live in
[`analysis/explore_results.ipynb`](analysis/explore_results.ipynb). This
README is a file and command reference.

## Protocol

- Hash input: `sha256(challenge_token || ascii_decimal(nonce))`.
- Difficulty: `N` leading hex zero digits in the SHA-256 digest.
- Nonce type: unsigned integer, encoded as ASCII decimal.
- Solver result: `(nonce, attempts, elapsed_secs, digest)`.
- Verification: recompute the digest and count leading hex zeros.

Both implementations share the wire format; a solution found by either
verifies under the other (enforced by `python/tests/test_pow.py`).

## Reference results

AMD Ryzen 9 5950X (Zen 3, 16C/32T), Ubuntu 24.04, rustc 1.95, 60-second
target per solve, 30 runs per N (some cells stop early on the per-N cap):

| Implementation                | Calibrated H/s     | Max N in 60 s | Speedup |
| ----------------------------- | ------------------:| -------------:| -------:|
| Python (single thread)        |      ~1 730 000    |             6 |    1.0× |
| Rust + SHA-NI, 32 threads     |  ~1 210 000 000    |             8 |    700× |

Raw data: [`results/bench-*.json`](results/). Detailed per-N tables and
distribution plots are in the notebook.

## Reproducing the numbers

`repro.sh` runs the Rust reference sweep and snapshots the host:

```sh
./repro.sh                     # defaults: --start 6 --max 10 --runs 30 --target 60
RUNS=50 TARGET=120 ./repro.sh  # override knobs
START=8 MAX=11   ./repro.sh    # narrow / widen N sweep
```

Outputs land in `results/`: `bench-<host>-<stamp>.json` (per-run timings +
summary stats) and `env-<host>-<stamp>.txt` (CPU/OS/microcode/governor/turbo
state, rustc version).

Python baseline (separate; the single-thread reference):

```sh
cd python
uv run python benchmark.py --start 4 --max 7 --runs 30 --target 60 \
    --json ../results/bench-$(hostname -s)-$(date -u +%Y%m%dT%H%M%SZ)-python.json
```

For comparable cross-machine numbers on Linux, pin the governor before
running (effect varies by platform):

```sh
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

Dependencies are locked by [`python/uv.lock`](python/uv.lock) and pinned by
[`rust-toolchain.toml`](rust-toolchain.toml). `rust/Cargo.lock` is not
tracked; Cargo resolves on first fetch.

## Analysis notebooks

Two views sharing the same code in `analysis/_lib.py`:

- [`analysis/explore_results.ipynb`](analysis/explore_results.ipynb) — full
  walkthrough: methodology, summary table, headline + per-N `P(elapsed ≤ target)`
  with Wilson 95% CI, elapsed-time plot with bootstrap 95% CI of the median
  and both calibrated-bound and pooled-effective theoretical curves, ECDF
  and density at the best shared N, normalized diagnostics
  (`mean A / 16^N`, `median T / theoretical`, `r_eff / r_calib`) that
  separate probabilistic-model issues from solver overhead, and
  cross-implementation relative-time / speedup matrices.
- [`analysis/explore_results_simple.ipynb`](analysis/explore_results_simple.ipynb) —
  compact view: summary table + single-panel elapsed-time plot. Nothing more.

```sh
cd python
uv sync --group analysis
uv run -- jupyter notebook ../analysis/explore_results.ipynb        # or _simple
```

Both checked-in `.ipynb` files carry execution outputs so figures and tables
render directly on GitHub. To re-execute in place after dropping new
`results/bench-*.json` files:

```sh
cd python && uv run -- jupyter execute --inplace \
    ../analysis/explore_results.ipynb ../analysis/explore_results_simple.ipynb
```

CI runs the same `jupyter execute` without `--inplace` as a smoke test, so
broken notebooks fail the build even when the outputs are not refreshed.

## Tests

```sh
cd rust   && cargo test --release    # unit + integration + proptest
cd python && uv run -- pytest -q     # parity oracle against the Rust binary
```

CI runs Rust fmt/clippy/tests, Python ruff/tests, and the notebook
execution smoke.

## License

Dual-licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or
  <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or
  <http://opensource.org/licenses/MIT>)

at your option.
