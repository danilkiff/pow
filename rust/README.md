# pow (Rust)

Parallel Proof-of-Work solver. SHA-256 is provided by the `sha2` crate
(uses **SHA-NI** on supported x86_64 targets) and the search is distributed
over a `rayon` worker pool.

Problem statement and methodology live in the [top-level README](../README.md).

## Requirements

- Linux, macOS, or Windows
- Rust **stable** (1.95+ tested; pinned in `rust-toolchain.toml`)
- For hardware SHA-NI: x86_64 CPU with the `sha_ni` flag
  (Intel Ice Lake and later, all AMD Zen generations)

Check for SHA-NI on Linux:

```sh
lscpu | grep -o sha_ni
```

## Install

### Ubuntu / Debian

```sh
sudo apt update
sudo apt install -y build-essential curl pkg-config
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal
source "$HOME/.cargo/env"
```

### Build

Release build:

```sh
cargo build --release
```

`-C target-cpu=native` is set in `.cargo/config.toml`, so the compiler
optimizes for the host that builds the binary. For cross-host deployment,
replace it with a specific target CPU name (`znver3`, `znver4`,
`icelake-server`, ...).

Binaries: `target/release/pow`, `target/release/pow-bench`.

## CLI

### `pow` — solve once

```sh
pow [challenge_token] <n_zeros> [-j THREADS] [--start-nonce N]
```

- `challenge_token` — utf-8 string; defaults to `"demo"`
- `n_zeros` — required leading-hex-zero count (0..=64)
- `-j, --threads` — worker threads (0 = all logical cores)
- `--start-nonce` — reproducibility knob

Example:

```sh
$ ./target/release/pow demo 7
challenge_token : demo
n_zeros (hex)   : 7
threads         : 32
solving ...
nonce           : 1264819
attempts        : 11 743 088
elapsed         : 0.523 s
hashrate        : 22 449 786 H/s
digest (hex)    : 0000000a48f3b...
verify          : true
```

### `pow-bench` — benchmark sweep

```sh
pow-bench [--start N] [--max N] [--runs N] [--target SECS] \
          [--per-n-budget SECS] [--calibrate-seconds SECS] [-j THREADS] \
          [--json PATH]
```

Binary defaults: `--start 4 --max 12 --runs 30 --target 60`,
`--calibrate-seconds 2`, and `--per-n-budget max(3 × target, 30 s)`.
The top-level `repro.sh` script overrides the sweep to `--start 6 --max 10`.

`--json` dumps raw per-run arrays + summary stats for downstream analysis
(see `analysis/explore_results.ipynb`).

## Compatibility with the Python reference

Wire format matches: nonce is encoded as ASCII decimal and appended to
the raw `challenge_token` bytes. A solution found by either implementation
verifies under the other.

## Tests

```sh
# library + integration tests + property tests
cargo test --release
```

What's covered:

- `tests/invariants.rs` — `proptest` over random tokens / N: every
  `solve()` result passes `verify()`; returned digest matches an
  independently-computed sha2 digest; `verify()` rejects unrelated nonces.
- `src/lib.rs` and `src/bin/bench.rs` — unit tests for leading-zero
  counting, percentile/stddev helpers, and the N-prediction formula.

## Reference numbers on AMD Ryzen 9 5950X

Ubuntu 24.04, rustc 1.95, 32 rayon threads, 60-second target, configured
for 30 runs per N. Source data:
[`../results/bench-oniguruma-20260525T120719Z-shani.json`](../results/bench-oniguruma-20260525T120719Z-shani.json).

```text
sha-ni single-thread H/s :     56 297 719
sha-ni parallel   H/s    :  1 206 885 002
```

### Reference sweep

| N | runs |  median, s | mean, s |   p95, s | σ, s   | effective H/s |
| -:| ----:| ----------:| -------:| --------:| ------:| -------------:|
| 6 |   30 |      0.032 |   0.046 |    0.119 |  0.041 |   397 072 739 |
| 7 |   30 |      0.502 |   0.717 |    2.544 |  0.784 |   398 671 101 |
| 8 |   20 |      6.023 |  10.031 |   34.735 | 11.189 |   403 035 881 |
| 9 |    1 |    255.184 | 255.184 |  255.184 |    —   |   405 896 765 |

Max N whose median solve time fits the 60-second target: **N = 8**.
The Python reference on the same machine reaches **N = 6** (single-thread
`hashlib` calibration at ~1.7 MH/s; see
[`../results/bench-oniguruma-20260525T132118Z-python.json`](../results/bench-oniguruma-20260525T132118Z-python.json)).

A few things worth noting from the raw distributions:

- **Variance at the edge dominates the mean.** At N = 8 the SHA-NI median
  is 6.0 s but p95 reaches 34.7 s and the mean is 10.0 s — the long tail
  of the geometric distribution stretches things. The earlier 5-run
  numbers under-reported variance significantly.
- **`runs` drops near the edge.** `pow-bench` caps total time per N at
  `max(3 × target, 30 s)`, so by N = 8 only 20 trials fit. p95 there is
  still noisy.
- **N = 9 has runs = 1** — one sample is statistically
  meaningless; we keep the cell so the cliff is visible, not to claim
  the 255-second figure is repeatable.
