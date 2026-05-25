# pow — Python reference implementation

A straightforward `hashlib.sha256` solver and benchmark. Lives here as the
methodology reference and the parity oracle for the Rust port: both
implementations share the wire format (`token || ascii_decimal(nonce)`),
so a solution found by either verifies under the other. The parity check
is enforced in [`tests/test_pow.py`](tests/test_pow.py).

The Python version is the slow baseline against which the Rust numbers in
the top-level [`README.md`](../README.md) are compared. On the reference
machine (`oniguruma`, AMD Ryzen 9 5950X, no CPU boost), the single-thread
`hashlib` calibration sustains **~1.7 MH/s** and reaches **N = 6** within
a 60-second median target.

The checked-in reference file is
[`../results/bench-oniguruma-20260525T132118Z-python.json`](../results/bench-oniguruma-20260525T132118Z-python.json).
It was configured for 30 runs per N; the per-N wall-clock cap stopped the
harder cells early, so the actual run counts are lower at N = 6 and N = 7.

Run the baseline benchmark and dump its JSON yourself:

```sh
uv run python benchmark.py --start 4 --max 7 --runs 30 --target 60 \
    --json ../results/bench-$(hostname -s)-$(date -u +%Y%m%dT%H%M%SZ)-python.json
```

## Setup

```sh
# all groups (test + lint + analysis kernel for the notebook)
uv sync --all-groups

# or just what you need
uv sync --group test --group lint
uv sync --group analysis    # ipykernel, jupyter, matplotlib, pandas, numpy
```

The notebook at [`../analysis/explore_results.ipynb`](../analysis/) pins
its kernel to `pow-analysis`. Register it once:

```sh
./setup-analysis-env.sh
```

## Usage

```sh
# Solve once
uv run python main.py demo 6

# Sweep N=4..8 with the reference single-thread baseline
uv run python benchmark.py --start 4 --max 8 --target 60
```

## Lint + tests

```sh
uv run -- ruff check . ../analysis
uv run -- ruff format --check . ../analysis
uv run -- pytest -q
```

CI runs the same ruff checks and pytest with a coverage report. The
`test_parity_with_rust` test skips automatically if
`../rust/target/release/pow` does not exist; run `cargo build --release`
in `../rust/` first to enable it locally.

## Layout

```
python/
├── pow.py                # solve() / verify() — the reference
├── main.py               # CLI: solve a single challenge
├── benchmark.py          # baseline sweep, prints summary
├── setup-analysis-env.sh # bootstrap .venv + register pow-analysis kernel
├── pyproject.toml        # ruff + pytest config, dependency groups
├── uv.lock               # locked Python dependencies
└── tests/
    └── test_pow.py       # 10 tests including Rust parity check
```
