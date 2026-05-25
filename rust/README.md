# pow (Rust)

Parallel Proof-of-Work solver. SHA-256 via `sha2` (uses **SHA-NI** on
supported x86_64 targets); search is spread across a `rayon` worker pool.

Problem statement and reference results: [top-level README](../README.md).
Methodology and plots: [`analysis/explore_results.ipynb`](../analysis/explore_results.ipynb).

## Build

```sh
cargo build --release
```

`-C target-cpu=native` is set in `.cargo/config.toml`, so the compiler
optimizes for the host. For cross-host deployment replace with a specific
target CPU (`znver3`, `znver4`, `icelake-server`, ...).

Binaries: `target/release/pow`, `target/release/pow-bench`.

Check for SHA-NI on Linux: `lscpu | grep -o sha_ni`. Available on Intel
Ice Lake and later, and all AMD Zen generations.

## `pow` — solve once

```sh
pow [challenge_token] <n_zeros> [-j THREADS] [--start-nonce N]
```

- `challenge_token` — utf-8 string; defaults to `"demo"`.
- `n_zeros` — required leading hex-zero count (0..=64).
- `-j, --threads` — worker threads (0 = all logical cores).
- `--start-nonce` — reproducibility knob.

```text
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

## `pow-bench` — benchmark sweep

```sh
pow-bench [--start N] [--max N] [--runs N] [--target SECS] \
          [--calibrate-seconds SECS] [-j THREADS] [--json PATH]
```

Defaults: `--start 4 --max 12 --runs 30 --target 60 --calibrate-seconds 2`.
Per-N wall-clock is capped at `max(3 × target, 30 s)`, which can cut runs
short near the cliff. `--json` dumps the schema-v2 report consumed by the
notebook.

## Tests

```sh
cargo test --release
```

`tests/invariants.rs` runs proptest: every `solve()` result passes
`verify()`, the returned digest matches an independently-computed sha2
digest, and `verify()` rejects unrelated nonces. Unit tests cover
leading-zero counting, percentile/stddev helpers, and the N-prediction
formula.
