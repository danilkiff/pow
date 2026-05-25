"""CLI: solve PoW once.

Usage:
    python main.py <challenge_token> <n_zeros>
    python main.py demo 5
"""

from __future__ import annotations

import argparse
import secrets

from pow import solve, verify


def main() -> None:
    parser = argparse.ArgumentParser(description="Proof-of-Work solver")
    parser.add_argument(
        "challenge_token",
        nargs="?",
        default=None,
        help="challenge string; if omitted, a random 16-byte token is generated",
    )
    parser.add_argument("n_zeros", type=int, help="required leading hex zeros in the digest")
    args = parser.parse_args()

    if args.challenge_token is None:
        token = secrets.token_bytes(16)
        token_repr = token.hex()
    else:
        token = args.challenge_token.encode("utf-8")
        token_repr = args.challenge_token

    print(f"challenge_token : {token_repr}")
    print(f"n_zeros (hex)   : {args.n_zeros}")
    print("solving ...")

    result = solve(token, args.n_zeros)

    print(f"nonce           : {result.nonce}")
    print(f"attempts        : {result.attempts:,}".replace(",", " "))
    print(f"elapsed         : {result.elapsed:.3f} s")
    print(f"hashrate        : {int(result.hashes_per_second):,} H/s".replace(",", " "))
    print(f"digest (hex)    : {result.hex_digest}")
    print(f"verify          : {verify(token, result.nonce, args.n_zeros)}")


if __name__ == "__main__":
    main()
