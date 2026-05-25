"""Proof-of-Work: find a nonce such that the hex representation of
sha256(challenge_token + nonce) starts with n_zeros zeros."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class PowResult:
    nonce: int
    attempts: int
    elapsed: float
    digest: bytes
    n_zeros: int

    @property
    def hashes_per_second(self) -> float:
        return self.attempts / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def hex_digest(self) -> str:
        return self.digest.hex()


def _leading_hex_zeros(digest: bytes) -> int:
    zeros = 0
    for byte in digest:
        if byte == 0:
            zeros += 2
            continue
        if byte < 0x10:
            zeros += 1
        break
    return zeros


def solve(
    challenge_token: bytes,
    n_zeros: int,
    start_nonce: int = 0,
    max_attempts: int | None = None,
) -> PowResult:
    """Find the smallest nonce >= start_nonce for which the hex string
    sha256(challenge_token + str(nonce)) starts with n_zeros zeros.

    nonce is encoded as an ASCII decimal string."""
    if n_zeros < 0 or n_zeros > 64:
        raise ValueError("n_zeros must be in [0, 64] (sha256 hex length is 64)")

    # In bytes: the first `full_zero_bytes` bytes must equal 0; if n_zeros
    # is odd, the high nibble of the next byte must also be 0.
    full_zero_bytes, odd_nibble = divmod(n_zeros, 2)
    zero_prefix = b"\x00" * full_zero_bytes

    nonce = start_nonce
    attempts = 0
    t0 = time.perf_counter()

    while True:
        attempts += 1
        digest = hashlib.sha256(challenge_token + str(nonce).encode("ascii")).digest()

        if digest.startswith(zero_prefix) and (not odd_nibble or digest[full_zero_bytes] < 0x10):
            elapsed = time.perf_counter() - t0
            return PowResult(
                nonce=nonce,
                attempts=attempts,
                elapsed=elapsed,
                digest=digest,
                n_zeros=n_zeros,
            )

        if max_attempts is not None and attempts >= max_attempts:
            elapsed = time.perf_counter() - t0
            raise TimeoutError(f"no solution after {attempts} attempts in {elapsed:.2f}s")

        nonce += 1


def verify(challenge_token: bytes, nonce: int, n_zeros: int) -> bool:
    digest = hashlib.sha256(challenge_token + str(nonce).encode("ascii")).digest()
    return _leading_hex_zeros(digest) >= n_zeros
