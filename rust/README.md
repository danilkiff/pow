# pow (Rust)

Parallel Proof-of-Work solver. SHA-256 via the `sha2` crate
(autodetects **SHA-NI** on x86_64) plus a `rayon` worker pool.

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

`-C target-cpu=native` is hard-coded in `.cargo/config.toml`, so the
compiler enables SHA-NI and other native CPU features for whatever host you build on.
For cross-host deployment swap to a specific name (`znver3`, `znver4`,
`icelake-server`, …).

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
          [--calibrate-seconds SECS] [-j THREADS] \
          [--json PATH]
```

Defaults: `--start 4 --max 12 --runs 30 --target 60`.

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

Ubuntu 24.04, rustc 1.95, 32 rayon threads, 60-second target, 30 runs per N.
Source data: [`../results/bench-oniguruma-…-shani.json`](../results/).

```text
sha-ni single-thread H/s :     56 297 719
sha-ni parallel   H/s    :  1 206 885 002
```

### 30 runs per N

| N | runs |  median, s | mean, s |   p95, s | σ, s   | effective H/s |
| -:| ----:| ----------:| -------:| --------:| ------:| -------------:|
| 6 |   30 |      0.032 |   0.046 |    0.119 |  0.041 |   397 072 739 |
| 7 |   30 |      0.502 |   0.717 |    2.544 |  0.784 |   398 671 101 |
| 8 |   20 |      6.023 |  10.031 |   34.735 | 11.189 |   403 035 881 |
| 9 |    1 |    255.184 | 255.184 |  255.184 |    —   |   405 896 765 |

Max N that fits the 60-second median budget: **N = 8**.
The Python reference on the same machine reaches **N = 6** (single-thread
`hashlib` at ~1.7 MH/s; see [`../results/bench-…-python.json`](../results/)).

A few things worth noting from the raw distributions:

- **Variance at the edge dominates the mean.** At N = 8 the SHA-NI median
  is 6.0 s but p95 reaches 34.7 s and the mean is 10.0 s — the long tail
  of the geometric distribution stretches things. The earlier 5-run
  numbers under-reported variance significantly.
- **`runs` drops near the edge.** `pow-bench` caps total time per N at
  `3 × target`, so by N = 8 only 20 trials fit. p95 there is still noisy.
- **N = 9 has runs = 1** — one sample is statistically
  meaningless; we keep the cell so the cliff is visible, not to claim
  the 255-second figure is repeatable.
