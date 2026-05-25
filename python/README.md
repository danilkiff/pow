# pow — Python reference implementation

A straightforward `hashlib.sha256` solver and benchmark. Lives here as the
methodology reference and the parity oracle for the Rust port: both
implementations share the wire format (`token || ascii_decimal(nonce)`),
so a solution found by either verifies under the other. The parity check
is enforced in [`tests/test_pow.py`](tests/test_pow.py).

The Python version is also the slow baseline against which the Rust
numbers in the top-level [`README.md`](../README.md) are compared
(currently ~3.3 MH/s, max N = 7 within a 60-second median budget).

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
python main.py demo 6

# Sweep N=1..10 with the reference single-thread baseline
python benchmark.py --start 4 --max 8 --target 60
```

## Lint + tests

```sh
uv run -- ruff check . ../analysis
uv run -- ruff format --check . ../analysis
uv run -- pytest -q
```

CI mirrors these three commands exactly; passing locally means passing in
GitHub Actions. The `test_parity_with_rust` test skips automatically if
`../rust/target/release/pow` doesn't exist — run `cargo build --release`
in `../rust/` first to enable it.

## Layout

```
python/
├── pow.py                # solve() / verify() — the reference
├── main.py               # CLI: solve a single challenge
├── benchmark.py          # baseline sweep, prints summary
├── setup-analysis-env.sh # bootstrap .venv + register pow-analysis kernel
├── pyproject.toml        # ruff + pytest config, dependency groups
└── tests/
    └── test_pow.py       # 10 tests including Rust parity check
```
