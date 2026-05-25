//! PoW: find a nonce such that the hex representation of
//! sha256(challenge_token || ascii(nonce)) starts with n_zeros zeros.
//!
//! Parallel search: each thread walks its own arithmetic progression
//! (start + tid, step = num_threads) and periodically checks a shared
//! atomic "found" flag.

use sha2::{Digest, Sha256};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// Shared state between solver workers and the main thread.
type Solution = Arc<Mutex<Option<(u64, [u8; 32])>>>;

#[derive(Debug, Clone)]
pub struct PowResult {
    pub nonce: u64,
    pub attempts: u64,
    pub elapsed_secs: f64,
    pub digest: [u8; 32],
    pub n_zeros: u32,
    pub threads: usize,
}

impl PowResult {
    pub fn hashes_per_second(&self) -> f64 {
        if self.elapsed_secs > 0.0 {
            self.attempts as f64 / self.elapsed_secs
        } else {
            0.0
        }
    }
    pub fn hex_digest(&self) -> String {
        hex::encode(self.digest)
    }
}

/// Number of leading hex zeros in `digest`.
pub fn leading_hex_zeros(digest: &[u8; 32]) -> u32 {
    let mut zeros = 0u32;
    for &b in digest {
        if b == 0 {
            zeros += 2;
        } else if b < 0x10 {
            zeros += 1;
            break;
        } else {
            break;
        }
    }
    zeros
}

pub fn verify(token: &[u8], nonce: u64, n_zeros: u32) -> bool {
    let mut hasher = Sha256::new();
    hasher.update(token);
    let mut buf = itoa::Buffer::new();
    hasher.update(buf.format(nonce).as_bytes());
    let digest: [u8; 32] = hasher.finalize().into();
    leading_hex_zeros(&digest) >= n_zeros
}

/// Parallel PoW solver. `threads = 0` means use `rayon::current_num_threads()`.
pub fn solve(token: &[u8], n_zeros: u32, start_nonce: u64, threads: usize) -> PowResult {
    assert!(n_zeros <= 64, "n_zeros must be in [0, 64]");

    let threads = if threads == 0 {
        rayon::current_num_threads()
    } else {
        threads
    };

    let full_zero_bytes = (n_zeros / 2) as usize;
    let odd_nibble = n_zeros % 2 == 1;

    let found = Arc::new(AtomicBool::new(false));
    let total_attempts = Arc::new(AtomicU64::new(0));
    let solution: Solution = Arc::new(Mutex::new(None));

    let t0 = Instant::now();

    rayon::scope(|s| {
        for tid in 0..threads {
            let found = found.clone();
            let total_attempts = total_attempts.clone();
            let solution = solution.clone();
            let token = token.to_vec();

            s.spawn(move |_| {
                let mut local_attempts: u64 = 0;
                let mut nonce: u64 = start_nonce.wrapping_add(tid as u64);
                let stride: u64 = threads as u64;
                let mut itoa_buf = itoa::Buffer::new();

                // hashes per inner loop before consulting the shared flag
                const BATCH: u32 = 4096;

                loop {
                    for _ in 0..BATCH {
                        let mut hasher = Sha256::new();
                        hasher.update(&token);
                        hasher.update(itoa_buf.format(nonce).as_bytes());
                        let digest: [u8; 32] = hasher.finalize().into();
                        local_attempts += 1;

                        let ok_full = digest[..full_zero_bytes].iter().all(|&b| b == 0);
                        let ok_nibble = !odd_nibble || (digest[full_zero_bytes] & 0xF0) == 0;

                        if ok_full && ok_nibble {
                            total_attempts.fetch_add(local_attempts, Ordering::Relaxed);
                            let mut g = solution.lock().unwrap();
                            if g.is_none() {
                                *g = Some((nonce, digest));
                                found.store(true, Ordering::Release);
                            }
                            return;
                        }

                        nonce = nonce.wrapping_add(stride);
                    }

                    if found.load(Ordering::Acquire) {
                        total_attempts.fetch_add(local_attempts, Ordering::Relaxed);
                        return;
                    }
                }
            });
        }
    });

    let elapsed = t0.elapsed().as_secs_f64();
    let attempts = total_attempts.load(Ordering::Relaxed);
    let (nonce, digest) = solution
        .lock()
        .unwrap()
        .take()
        .expect("solver must produce a solution");

    PowResult {
        nonce,
        attempts,
        elapsed_secs: elapsed,
        digest,
        n_zeros,
        threads,
    }
}

/// Single-thread calibration: run an unsolvable task for `duration_secs`
/// and count completed hashes. Used as the H/s baseline.
pub fn calibrate_single_thread(duration_secs: f64) -> f64 {
    let token = b"calibration-token";
    let mut attempts: u64 = 0;
    let mut itoa_buf = itoa::Buffer::new();
    let t0 = Instant::now();
    let deadline = t0 + std::time::Duration::from_secs_f64(duration_secs);
    let mut nonce: u64 = 0;
    while Instant::now() < deadline {
        for _ in 0..10_000u32 {
            let mut hasher = Sha256::new();
            hasher.update(token);
            hasher.update(itoa_buf.format(nonce).as_bytes());
            let _: [u8; 32] = hasher.finalize().into();
            nonce += 1;
        }
        attempts += 10_000;
    }
    attempts as f64 / t0.elapsed().as_secs_f64()
}

/// Parallel calibration across all rayon worker threads.
pub fn calibrate_parallel(duration_secs: f64) -> (f64, usize) {
    let threads = rayon::current_num_threads();
    let total = Arc::new(AtomicU64::new(0));
    let t0 = Instant::now();
    let deadline = t0 + std::time::Duration::from_secs_f64(duration_secs);

    rayon::scope(|s| {
        for tid in 0..threads {
            let total = total.clone();
            s.spawn(move |_| {
                let token = b"calibration-token";
                let mut itoa_buf = itoa::Buffer::new();
                let mut nonce: u64 = (tid as u64) << 40;
                let mut local: u64 = 0;
                while Instant::now() < deadline {
                    for _ in 0..10_000u32 {
                        let mut hasher = Sha256::new();
                        hasher.update(token);
                        hasher.update(itoa_buf.format(nonce).as_bytes());
                        let _: [u8; 32] = hasher.finalize().into();
                        nonce += 1;
                    }
                    local += 10_000;
                }
                total.fetch_add(local, Ordering::Relaxed);
            });
        }
    });

    let elapsed = t0.elapsed().as_secs_f64();
    (total.load(Ordering::Relaxed) as f64 / elapsed, threads)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn solve_and_verify_low_difficulty() {
        let result = solve(b"demo", 4, 0, 1);
        assert!(verify(b"demo", result.nonce, 4));
        assert!(result.digest[0] == 0 && result.digest[1] == 0);
    }

    #[test]
    fn leading_zeros_count() {
        let mut d = [0u8; 32];
        d[0] = 0x00;
        d[1] = 0x0a;
        assert_eq!(leading_hex_zeros(&d), 3);
        d[1] = 0xa0;
        assert_eq!(leading_hex_zeros(&d), 2);
        d[0] = 0xa0;
        assert_eq!(leading_hex_zeros(&d), 0);
    }
}
