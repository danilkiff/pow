"""Tests for the reference Python PoW solver."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

# import the solver from the parent directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pow import _leading_hex_zeros, solve, verify  # type: ignore


def test_leading_hex_zeros_edges() -> None:
    assert _leading_hex_zeros(b"\x00" * 32) == 64
    assert _leading_hex_zeros(b"\xff" + b"\x00" * 31) == 0
    assert _leading_hex_zeros(b"\x0f" + b"\x00" * 31) == 1
    assert _leading_hex_zeros(b"\xf0" + b"\x00" * 31) == 0
    assert _leading_hex_zeros(b"\x00\x01" + b"\x00" * 30) == 3


@pytest.mark.parametrize("n_zeros", [0, 1, 2, 3, 4, 5])
def test_solve_then_verify(n_zeros: int) -> None:
    token = os.urandom(8)
    r = solve(token, n_zeros)
    assert verify(token, r.nonce, n_zeros)
    assert r.digest[: n_zeros // 2] == b"\x00" * (n_zeros // 2)
    if n_zeros % 2 == 1:
        assert r.digest[n_zeros // 2] < 0x10


def test_digest_matches_hashlib() -> None:
    token = b"demo"
    r = solve(token, 4)
    expected = hashlib.sha256(token + str(r.nonce).encode("ascii")).digest()
    assert r.digest == expected


def test_verify_rejects_random_nonce() -> None:
    # Random hit probability at 8 hex zeros is 16^-8 ~ 2e-10.
    assert not verify(b"demo", 12345, 8)


RUST_BIN = Path(__file__).resolve().parents[2] / "rust" / "target" / "release" / "pow"
_needs_rust = pytest.mark.skipif(
    not RUST_BIN.exists(),
    reason="rust binary not built — run `cargo build --release` first",
)


@_needs_rust
def test_python_verifies_rust_solution() -> None:
    """A Rust solver solution must pass the Python verifier.
    Catches divergences in nonce encoding, token format, or n_zeros
    interpretation between the implementations."""
    token = "parity-check"
    n_zeros = 4
    out = subprocess.run(
        [str(RUST_BIN), token, str(n_zeros)],
        capture_output=True,
        text=True,
        check=True,
    )
    nonce_line = [ln for ln in out.stdout.splitlines() if ln.startswith("nonce")]
    assert nonce_line, f"no nonce in rust output: {out.stdout}"
    rust_nonce = int(nonce_line[0].split(":")[1].strip())
    assert verify(token.encode("utf-8"), rust_nonce, n_zeros)


@_needs_rust
def test_rust_verifies_python_solution() -> None:
    """Reverse parity: Rust's `--verify` must accept a Python-found nonce.
    Closes the loop on the cross-implementation oracle."""
    token = "parity-check"
    n_zeros = 4
    r = solve(token.encode("utf-8"), n_zeros)
    out = subprocess.run(
        [str(RUST_BIN), token, str(n_zeros), "--verify", str(r.nonce)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, (
        f"rust rejected python solution nonce={r.nonce}: "
        f"stdout={out.stdout!r} stderr={out.stderr!r}"
    )
