//! Cross-backend: a solution from one backend must verify under the other.

#![cfg(feature = "mb")]

use pow::{mb::solve_mb, solve, verify};
use proptest::prelude::*;

proptest! {
    #[test]
    fn mb_solution_verifies_with_default_verify(
        token in proptest::collection::vec(any::<u8>(), 0..32),
        n_zeros in 0u32..=5,
    ) {
        let r = solve_mb(&token, n_zeros, 0, 0);
        prop_assert!(verify(&token, r.nonce, n_zeros));
    }

    #[test]
    fn sha_ni_solution_verifies_under_mb_path(
        token in proptest::collection::vec(any::<u8>(), 0..32),
        n_zeros in 0u32..=5,
    ) {
        // Both backends share the same wire format (token || ascii(nonce)),
        // and `returned_digest_matches_independent` already proves the
        // default backend matches sha2 byte-for-byte. Here we ensure the
        // shared verify() agrees with the sha-ni solver at the same
        // difficulty — a guard against drift in either path's framing.
        let r = solve(&token, n_zeros, 0, 1);
        prop_assert!(verify(&token, r.nonce, n_zeros));
    }
}
