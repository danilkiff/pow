# pow — Python reference implementation

Straightforward `hashlib.sha256` solver and benchmark. The slow baseline
against which the Rust numbers are measured, and the parity oracle for the
Rust port (both share the wire format `token || ascii_decimal(nonce)`).

Problem statement and reference numbers: [top-level README](../README.md).

## Setup

```sh
uv sync --group test --group lint   # minimal: tests + linter
uv sync --group analysis            # adds the notebook stack
uv sync --all-groups                # everything
```

## Usage

```sh
uv run python main.py demo 6                                     # solve once
uv run python benchmark.py --start 4 --max 7 --target 60         # baseline sweep
uv run -- ruff check . ../analysis && uv run -- pytest -q        # lint + tests
```

`test_python_verifies_rust_solution` runs the compiled `pow` binary and
checks its solution under the Python verifier; `test_rust_verifies_python_solution`
closes the loop in the other direction via `pow ... --verify <nonce>`. Both
skip if `../rust/target/release/pow` is missing — `cargo build --release` in
`../rust/` enables them.
