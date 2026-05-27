use clap::Parser;
use pow::{solve, verify};

#[derive(Parser, Debug)]
#[command(about = "Proof-of-Work solver (SHA-NI + rayon)")]
struct Args {
    /// challenge string (utf-8). Defaults to "demo".
    #[arg(default_value = "demo")]
    challenge_token: String,

    /// required number of leading hex zeros
    n_zeros: u32,

    /// worker thread count (0 = all logical cores)
    #[arg(short = 'j', long, default_value_t = 0)]
    threads: usize,

    /// starting nonce value (for reproducibility)
    #[arg(long, default_value_t = 0)]
    start_nonce: u64,

    /// if set, only verify that this nonce solves the task; exit 0 on
    /// success, 1 on failure. Used by the Python parity-oracle test to
    /// confirm Rust accepts a Python-produced solution.
    #[arg(long = "verify", value_name = "NONCE",
          conflicts_with_all = ["threads", "start_nonce"])]
    verify_nonce: Option<u64>,
}

fn main() {
    let args = Args::parse();

    if let Some(nonce) = args.verify_nonce {
        let ok = verify(args.challenge_token.as_bytes(), nonce, args.n_zeros);
        println!("verify: {}", if ok { "ok" } else { "fail" });
        std::process::exit(if ok { 0 } else { 1 });
    }

    println!("challenge_token : {}", args.challenge_token);
    println!("n_zeros (hex)   : {}", args.n_zeros);
    let threads = if args.threads == 0 {
        rayon::current_num_threads()
    } else {
        args.threads
    };
    println!("threads         : {}", threads);
    println!("solving ...");

    let token = args.challenge_token.as_bytes();
    let r = solve(token, args.n_zeros, args.start_nonce, args.threads);

    println!("nonce           : {}", r.nonce);
    println!("attempts        : {}", fmt_int(r.attempts));
    println!("elapsed         : {:.3} s", r.elapsed_secs);
    println!(
        "hashrate        : {} H/s",
        fmt_int(r.hashes_per_second() as u64)
    );
    println!("digest (hex)    : {}", r.hex_digest());
    println!("verify          : {}", verify(token, r.nonce, args.n_zeros));
}

fn fmt_int(n: u64) -> String {
    let s = n.to_string();
    let bytes = s.as_bytes();
    let mut out = String::with_capacity(s.len() + s.len() / 3);
    for (i, &b) in bytes.iter().enumerate() {
        if i > 0 && (bytes.len() - i).is_multiple_of(3) {
            out.push(' ');
        }
        out.push(b as char);
    }
    out
}
