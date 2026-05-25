//! End-to-end invariants checked across random inputs.
//!
//! PoW is hard to observe directly; the one inescapable invariant is
//! `verify(token, solve(token, n).nonce, n) == true`. It is also
//! exhaustive: any error in nonce encoding, digest endianness, or
//! zero-nibble boundary handling breaks it.

use pow::{leading_hex_zeros, solve, verify};
use proptest::prelude::*;
use sha2::{Digest, Sha256};

proptest! {
    /// Every solution from the sha-ni solver must pass an independent verify.
    #[test]
    fn sha_ni_solution_verifies(
        token in proptest::collection::vec(any::<u8>(), 0..40),
        n_zeros in 0u32..=4,
    ) {
        let r = solve(&token, n_zeros, 0, 1);
        prop_assert!(verify(&token, r.nonce, n_zeros),
                     "verify failed for token={:?} n={} nonce={}", token, n_zeros, r.nonce);
        prop_assert!(leading_hex_zeros(&r.digest) >= n_zeros);
    }

    /// The returned digest equals an independently-computed sha2 digest.
    #[test]
    fn returned_digest_matches_independent(
        token in proptest::collection::vec(any::<u8>(), 0..40),
        n_zeros in 0u32..=4,
    ) {
        let r = solve(&token, n_zeros, 0, 1);
        let mut h = Sha256::new();
        h.update(&token);
        h.update(r.nonce.to_string().as_bytes());
        let expected: [u8; 32] = h.finalize().into();
        prop_assert_eq!(r.digest, expected);
    }

    /// verify() rejects an unrelated nonce.
    #[test]
    fn verify_rejects_wrong_nonce(
        token in proptest::collection::vec(any::<u8>(), 1..16),
        nonce in any::<u64>(),
        n_zeros in 8u32..=16,
    ) {
        // 8+ leading hex zeros: passes by chance with probability 16^-8 ~ 2e-10.
        prop_assert!(!verify(&token, nonce, n_zeros));
    }
}

/// Edge cases for `leading_hex_zeros`.
#[test]
fn leading_hex_zeros_edges() {
    let zero = [0u8; 32];
    assert_eq!(leading_hex_zeros(&zero), 64);

    let mut d = [0u8; 32];
    d[0] = 0xff;
    assert_eq!(leading_hex_zeros(&d), 0);

    d[0] = 0x0f;
    assert_eq!(leading_hex_zeros(&d), 1);

    d[0] = 0xf0;
    assert_eq!(leading_hex_zeros(&d), 0);

    d[0] = 0x00;
    d[1] = 0x01;
    assert_eq!(leading_hex_zeros(&d), 3);
}
