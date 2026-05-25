# pow (Rust)

Parallel Proof-of-Work solver. SHA-256 via the `sha2` crate
(autodetects **SHA-NI** on x86_64) plus a `rayon` worker pool.
Optionally, an Intel **ISA-L Crypto** multi-buffer backend for
AVX2/AVX-512 8/16-lane SHA-256.

Problem statement and methodology live in the [top-level README](../README.md).

## Requirements

- Linux, macOS, or Windows
- Rust **stable** (1.95+ tested; pinned in `rust-toolchain.toml`)
- For hardware SHA-NI: x86_64 CPU with the `sha_ni` flag
  (Intel Ice Lake and later, all AMD Zen generations)
- For the `mb` feature: Intel ISA-L Crypto v2.26+

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

### ISA-L Crypto (only needed for the multi-buffer backend)

Not packaged by Ubuntu; build from source:

```sh
sudo apt install -y nasm autoconf automake libtool make pkg-config git
git clone --depth 1 https://github.com/intel/isa-l_crypto.git
cd isa-l_crypto
./autogen.sh && ./configure && make -j$(nproc) && sudo make install
sudo ldconfig
```

Headers land in `/usr/include/isa-l_crypto/`, library in `/usr/lib/`.

### Build

Default (SHA-NI + rayon, no external system deps):

```sh
cargo build --release
```

With multi-buffer:

```sh
cargo build --release --features mb
```

`-C target-cpu=native` is hard-coded in `.cargo/config.toml`, so the
compiler enables SHA-NI / AVX2 / AVX-512 for whatever host you build on.
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
pow-bench [--backend sha-ni|mb] \
          [--start N] [--max N] [--runs N] [--target SECS] \
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
# include the mb backend
cargo test --release --features mb
```

What's covered:

- `tests/invariants.rs` — `proptest` over random tokens / N: every
  `solve()` result passes `verify()`; returned digest matches an
  independently-computed sha2 digest; `verify()` rejects unrelated nonces.
- `tests/cross_backend.rs` — mb-found nonces verify under the default
  backend and vice versa (feature-gated).
- `src/lib.rs` and `src/bin/bench.rs` — unit tests for leading-zero
  counting, percentile/stddev helpers, and the N-prediction formula.

## Reference numbers on AMD Ryzen 9 5950X

Ubuntu 24.04, rustc 1.95, 32 rayon threads, 60-second target, 30 runs per N.
Source data: [`../results/bench-oniguruma-…-shani.json`](../results/) and
the matching `-mb.json`.

```text
sha-ni single-thread H/s :     56 297 719
sha-ni parallel   H/s    :  1 206 885 002
mb     parallel   H/s    :    177 999 234
```

### SHA-NI backend (30 runs per N)

| N | runs |  median, s | mean, s |   p95, s | σ, s   | effective H/s |
| -:| ----:| ----------:| -------:| --------:| ------:| -------------:|
| 6 |   30 |      0.032 |   0.046 |    0.119 |  0.041 |   397 072 739 |
| 7 |   30 |      0.502 |   0.717 |    2.544 |  0.784 |   398 671 101 |
| 8 |   20 |      6.023 |  10.031 |   34.735 | 11.189 |   403 035 881 |
| 9 |    1 |    255.184 | 255.184 |  255.184 |    —   |   405 896 765 |

### Multi-buffer backend (ISA-L AVX2, 30 runs per N)

| N | runs |  median, s | mean, s |   p95, s | σ, s   | effective H/s |
| -:| ----:| ----------:| -------:| --------:| ------:| -------------:|
| 6 |   30 |      0.053 |   0.083 |    0.313 |  0.085 |   172 493 796 |
| 7 |   30 |      1.124 |   1.642 |    5.160 |  1.414 |   172 626 110 |
| 8 |    5 |     27.603 |  40.088 |  106.363 | 40.424 |   174 473 994 |
| 9 |    1 |    413.070 | 413.070 |  413.070 |    —   |   171 285 705 |

Max N that fits the 60-second median budget: **N = 8** for both backends.
The Python reference reaches N = 7.

A few things worth noting from the raw distributions:

- **Variance at the edge dominates the mean.** At N = 8 the SHA-NI median
  is 6.0 s but p95 reaches 34.7 s and the mean is 10.0 s — the long tail
  of the geometric distribution stretches things. The earlier 5-run
  numbers under-reported variance significantly.
- **`runs` drops near the edge.** `pow-bench` caps total time per N at
  `3 × target`, so by N = 8 only 20 (sha-ni) or 5 (mb) trials fit. p95
  there is best-of-five noise, not a real percentile.
- **N = 9 has runs = 1** in both columns — one sample is statistically
  meaningless; we keep the cell so the cliff is visible, not to claim
  the 255-second figure is repeatable.

### Why multi-buffer doesn't beat SHA-NI on Zen 3

ISA-L `sha256_mb` (AVX2, 8 lanes) computes SHA-256 with SIMD integer ops,
running 8 independent message streams in parallel. Zen 3 has the
hardware `SHA256RNDS2` instruction, which dispatches two compression
rounds per instruction. For short single-block messages, the hardware
path wins by roughly **7× on raw H/s**, and that gap shows up cleanly in
median solve time at every N. Multi-buffer pays off:

- on CPUs without SHA-NI (Sandy/Ivy/Haswell, Zen 1);
- on long messages, where batch dispatch amortises better;
- on AVX-512 (Zen 4/5, Ice Lake-X) — 16 lanes, ~2× the SIMD width.

(An earlier 5-run sweep appeared to show mb winning on N = 6, 7 wall-clock.
That was small-sample noise; the 30-run medians put SHA-NI ahead at
every difficulty.)
