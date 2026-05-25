//! Multi-buffer SHA-256 backed by ISA-L Crypto. AVX2 → 8 lanes per core.
//!
//! Each worker owns a private mgr and a pool of 8 contexts. At any point a
//! ctx is either in-flight (submitted to the mgr) or free. Each submit
//! returns NULL (when the lane set isn't full yet) or a pointer to a
//! completed ctx — we then read its digest, check the difficulty
//! condition, and resubmit with the next nonce.

use std::alloc::{alloc_zeroed, dealloc, Layout};
use std::ffi::c_void;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use crate::{PowResult, Solution};

#[link(name = "pow_mb", kind = "static")]
extern "C" {
    fn pow_mb_mgr_size() -> usize;
    fn pow_mb_mgr_align() -> usize;
    fn pow_mb_ctx_size() -> usize;
    fn pow_mb_ctx_align() -> usize;
    fn pow_mb_mgr_init(mgr: *mut c_void) -> i32;
    fn pow_mb_ctx_reset(ctx: *mut c_void);
    fn pow_mb_submit_entire(
        mgr: *mut c_void,
        ctx: *mut c_void,
        completed_out: *mut *mut c_void,
        buf: *const u8,
        len: u32,
    ) -> i32;
    fn pow_mb_flush(mgr: *mut c_void, completed_out: *mut *mut c_void) -> i32;
    fn pow_mb_ctx_digest(ctx: *const c_void, out: *mut u8);
    fn pow_mb_ctx_set_user(ctx: *mut c_void, v: u64);
    fn pow_mb_ctx_get_user(ctx: *const c_void) -> u64;
}

const LANES: usize = 8;

struct Mgr {
    ptr: *mut c_void,
    layout: Layout,
}

impl Mgr {
    fn new() -> Self {
        unsafe {
            let layout = Layout::from_size_align(pow_mb_mgr_size(), pow_mb_mgr_align())
                .expect("invalid mgr layout");
            let ptr = alloc_zeroed(layout) as *mut c_void;
            assert!(!ptr.is_null(), "mgr alloc failed");
            let rc = pow_mb_mgr_init(ptr);
            assert!(rc == 0, "isal_sha256_ctx_mgr_init returned {}", rc);
            Mgr { ptr, layout }
        }
    }
}
impl Drop for Mgr {
    fn drop(&mut self) {
        unsafe { dealloc(self.ptr as *mut u8, self.layout) };
    }
}
unsafe impl Send for Mgr {}

struct Ctx {
    ptr: *mut c_void,
    layout: Layout,
    /// Per-ctx message buffer (token || nonce). Must outlive the pointer
    /// ISA-L holds onto, i.e. until mgr returns this ctx as completed —
    /// so we keep `buf` co-located with the ctx itself.
    buf: Vec<u8>,
}
impl Ctx {
    fn new() -> Self {
        unsafe {
            let layout = Layout::from_size_align(pow_mb_ctx_size(), pow_mb_ctx_align())
                .expect("invalid ctx layout");
            let ptr = alloc_zeroed(layout) as *mut c_void;
            assert!(!ptr.is_null(), "ctx alloc failed");
            pow_mb_ctx_reset(ptr);
            Ctx {
                ptr,
                layout,
                buf: Vec::with_capacity(64),
            }
        }
    }
}
impl Drop for Ctx {
    fn drop(&mut self) {
        unsafe { dealloc(self.ptr as *mut u8, self.layout) };
    }
}
unsafe impl Send for Ctx {}

pub fn solve_mb(token: &[u8], n_zeros: u32, start_nonce: u64, threads: usize) -> PowResult {
    assert!(n_zeros <= 64);
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
                let mgr = Mgr::new();
                let mut ctxs: Vec<Ctx> = (0..LANES).map(|_| Ctx::new()).collect();
                let mut itoa_buf = itoa::Buffer::new();
                let mut local_attempts: u64 = 0;
                let mut next_nonce: u64 = start_nonce.wrapping_add(tid as u64);
                let stride: u64 = threads as u64;

                // helper: refill the ctx buffer with a fresh nonce
                let prepare =
                    |ctx: &mut Ctx, token: &[u8], nonce: u64, itoa_buf: &mut itoa::Buffer| {
                        ctx.buf.clear();
                        ctx.buf.extend_from_slice(token);
                        ctx.buf.extend_from_slice(itoa_buf.format(nonce).as_bytes());
                        unsafe {
                            pow_mb_ctx_set_user(ctx.ptr, nonce);
                        }
                    };

                // prime all 8 lanes
                let mut completed_idxs: Vec<usize> = Vec::with_capacity(LANES);
                for i in 0..LANES {
                    let nonce = next_nonce;
                    next_nonce = next_nonce.wrapping_add(stride);
                    prepare(&mut ctxs[i], &token, nonce, &mut itoa_buf);

                    let mut completed: *mut c_void = std::ptr::null_mut();
                    let len = ctxs[i].buf.len() as u32;
                    let buf_ptr = ctxs[i].buf.as_ptr();
                    let rc = unsafe {
                        pow_mb_submit_entire(mgr.ptr, ctxs[i].ptr, &mut completed, buf_ptr, len)
                    };
                    debug_assert_eq!(rc, 0);
                    if !completed.is_null() {
                        // found a completed ctx — resolve it back to a pool index
                        let idx = ctxs
                            .iter()
                            .position(|c| c.ptr == completed)
                            .expect("completed not in pool");
                        completed_idxs.push(idx);
                    }
                }

                let mut digest_buf = [0u8; 32];
                // poll the shared flag once per 512 completed hashes (~50 us)
                const FLAG_CHECK_EVERY: u32 = 512;
                let mut since_check: u32 = 0;

                loop {
                    let idx = if let Some(i) = completed_idxs.pop() {
                        i
                    } else {
                        // nothing ready — flush to drain half-filled lanes
                        let mut completed: *mut c_void = std::ptr::null_mut();
                        let rc = unsafe { pow_mb_flush(mgr.ptr, &mut completed) };
                        debug_assert_eq!(rc, 0);
                        if completed.is_null() {
                            // entirely empty — someone else won; exit
                            break;
                        }
                        ctxs.iter()
                            .position(|c| c.ptr == completed)
                            .expect("completed not in pool")
                    };

                    local_attempts += 1;
                    unsafe { pow_mb_ctx_digest(ctxs[idx].ptr, digest_buf.as_mut_ptr()) };
                    let nonce = unsafe { pow_mb_ctx_get_user(ctxs[idx].ptr) };

                    let ok_full = digest_buf[..full_zero_bytes].iter().all(|&b| b == 0);
                    let ok_nibble = !odd_nibble || (digest_buf[full_zero_bytes] & 0xF0) == 0;

                    if ok_full && ok_nibble {
                        let mut g = solution.lock().unwrap();
                        if g.is_none() {
                            *g = Some((nonce, digest_buf));
                            found.store(true, Ordering::Release);
                        }
                        break;
                    }

                    since_check += 1;
                    if since_check >= FLAG_CHECK_EVERY {
                        since_check = 0;
                        if found.load(Ordering::Acquire) {
                            break;
                        }
                    }

                    // resubmit this ctx with a fresh nonce
                    let new_nonce = next_nonce;
                    next_nonce = next_nonce.wrapping_add(stride);
                    unsafe { pow_mb_ctx_reset(ctxs[idx].ptr) };
                    prepare(&mut ctxs[idx], &token, new_nonce, &mut itoa_buf);
                    let mut completed: *mut c_void = std::ptr::null_mut();
                    let len = ctxs[idx].buf.len() as u32;
                    let buf_ptr = ctxs[idx].buf.as_ptr();
                    let rc = unsafe {
                        pow_mb_submit_entire(mgr.ptr, ctxs[idx].ptr, &mut completed, buf_ptr, len)
                    };
                    debug_assert_eq!(rc, 0);
                    if !completed.is_null() {
                        let i2 = ctxs
                            .iter()
                            .position(|c| c.ptr == completed)
                            .expect("completed not in pool");
                        completed_idxs.push(i2);
                    }
                }

                total_attempts.fetch_add(local_attempts, Ordering::Relaxed);
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

/// Parallel multi-buffer calibration (unsolvable task).
pub fn calibrate_mb(duration_secs: f64) -> (f64, usize) {
    let threads = rayon::current_num_threads();
    let total = Arc::new(AtomicU64::new(0));
    let t0 = Instant::now();
    let deadline = t0 + std::time::Duration::from_secs_f64(duration_secs);

    rayon::scope(|s| {
        for tid in 0..threads {
            let total = total.clone();
            s.spawn(move |_| {
                let mgr = Mgr::new();
                let mut ctxs: Vec<Ctx> = (0..LANES).map(|_| Ctx::new()).collect();
                let token = b"calibration-token";
                let mut itoa_buf = itoa::Buffer::new();
                let mut nonce: u64 = (tid as u64) << 40;
                let mut local: u64 = 0;
                let mut completed_idxs: Vec<usize> = Vec::with_capacity(LANES);

                // prime
                for i in 0..LANES {
                    ctxs[i].buf.clear();
                    ctxs[i].buf.extend_from_slice(token);
                    ctxs[i]
                        .buf
                        .extend_from_slice(itoa_buf.format(nonce).as_bytes());
                    nonce += 1;
                    let mut completed: *mut c_void = std::ptr::null_mut();
                    let len = ctxs[i].buf.len() as u32;
                    let buf_ptr = ctxs[i].buf.as_ptr();
                    unsafe {
                        pow_mb_submit_entire(mgr.ptr, ctxs[i].ptr, &mut completed, buf_ptr, len);
                    }
                    if !completed.is_null() {
                        let idx = ctxs.iter().position(|c| c.ptr == completed).unwrap();
                        completed_idxs.push(idx);
                    }
                }

                // Don't poll the deadline on every iteration: Instant::now()
                // costs ~30 ns, which would eat half the per-hash time.
                // Once every 1024 completed hashes is granular enough.
                const DEADLINE_CHECK_EVERY: u32 = 1024;
                let mut since_check: u32 = 0;
                loop {
                    let idx = if let Some(i) = completed_idxs.pop() {
                        i
                    } else {
                        let mut completed: *mut c_void = std::ptr::null_mut();
                        unsafe { pow_mb_flush(mgr.ptr, &mut completed) };
                        if completed.is_null() {
                            break;
                        }
                        ctxs.iter().position(|c| c.ptr == completed).unwrap()
                    };
                    local += 1;
                    since_check += 1;
                    if since_check >= DEADLINE_CHECK_EVERY {
                        since_check = 0;
                        if Instant::now() >= deadline {
                            break;
                        }
                    }
                    unsafe { pow_mb_ctx_reset(ctxs[idx].ptr) };
                    ctxs[idx].buf.clear();
                    ctxs[idx].buf.extend_from_slice(token);
                    ctxs[idx]
                        .buf
                        .extend_from_slice(itoa_buf.format(nonce).as_bytes());
                    nonce += 1;
                    let mut completed: *mut c_void = std::ptr::null_mut();
                    let len = ctxs[idx].buf.len() as u32;
                    let buf_ptr = ctxs[idx].buf.as_ptr();
                    unsafe {
                        pow_mb_submit_entire(mgr.ptr, ctxs[idx].ptr, &mut completed, buf_ptr, len);
                    }
                    if !completed.is_null() {
                        let i2 = ctxs.iter().position(|c| c.ptr == completed).unwrap();
                        completed_idxs.push(i2);
                    }
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
    use crate::verify;

    #[test]
    fn solve_mb_matches_verify_low_n() {
        let r = solve_mb(b"demo", 5, 0, 0);
        assert!(
            verify(b"demo", r.nonce, 5),
            "mb-solver produced nonce that fails verify"
        );
        // 5 leading hex zeros → bytes 0-1 are 0x00 and high nibble of byte 2 is 0
        assert_eq!(r.digest[0], 0);
        assert_eq!(r.digest[1], 0);
        assert!(r.digest[2] < 0x10);
    }
}
