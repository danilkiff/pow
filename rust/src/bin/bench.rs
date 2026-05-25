use clap::Parser;
use pow::{calibrate_parallel, calibrate_single_thread, solve};
use rand::RngCore;
use serde::Serialize;
use std::fs::File;
use std::io::BufWriter;
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

#[derive(Parser, Debug)]
#[command(about = "PoW benchmark — find max N (hex zeros) that fits the target budget")]
struct Args {
    #[arg(long, default_value_t = 4)]
    start: u32,
    #[arg(long, default_value_t = 12)]
    max: u32,
    /// Target number of runs per N. Cumulative wall-clock at one N is
    /// capped at max(3 × target, 30 s), which can cut runs short.
    #[arg(long, default_value_t = 30)]
    runs: usize,
    /// Per-run budget in seconds — the headline figure we report against.
    #[arg(long, default_value_t = 60.0)]
    target: f64,
    #[arg(long, default_value_t = 2.0)]
    calibrate_seconds: f64,
    /// Worker threads (0 = all logical cores).
    #[arg(short = 'j', long, default_value_t = 0)]
    threads: usize,
    /// Dump structured results (env + per-N raw runs + summary) here.
    #[arg(long)]
    json: Option<PathBuf>,
}

#[derive(Serialize)]
struct NSummary {
    n_zeros: u32,
    runs: usize,
    elapsed_secs: Vec<f64>,
    attempts: Vec<u64>,
    stats: Stats,
}

#[derive(Serialize)]
struct Stats {
    mean_elapsed: f64,
    median_elapsed: f64,
    p95_elapsed: f64,
    p99_elapsed: f64,
    min_elapsed: f64,
    max_elapsed: f64,
    stddev_elapsed: f64,
    mean_attempts: f64,
    effective_hps: f64,
}

impl Stats {
    fn from(elapsed: &[f64], attempts: &[u64]) -> Self {
        let attempts_f: Vec<f64> = attempts.iter().map(|&x| x as f64).collect();
        let total_a: u64 = attempts.iter().sum();
        let total_t: f64 = elapsed.iter().sum();
        Self {
            mean_elapsed: mean(elapsed),
            median_elapsed: percentile(elapsed, 0.50),
            p95_elapsed: percentile(elapsed, 0.95),
            p99_elapsed: percentile(elapsed, 0.99),
            min_elapsed: elapsed.iter().cloned().fold(f64::INFINITY, f64::min),
            max_elapsed: elapsed.iter().cloned().fold(0.0_f64, f64::max),
            stddev_elapsed: sample_stddev(elapsed),
            mean_attempts: mean(&attempts_f),
            effective_hps: if total_t > 0.0 {
                total_a as f64 / total_t
            } else {
                0.0
            },
        }
    }
}

#[derive(Serialize)]
struct Env {
    os: &'static str,
    arch: &'static str,
    rayon_threads: usize,
    pow_version: &'static str,
}

#[derive(Serialize)]
struct Config {
    backend: &'static str,
    target_secs: f64,
    runs_per_n: usize,
    threads: usize,
    start: u32,
    max: u32,
    calibrate_seconds: f64,
}

#[derive(Serialize)]
struct Calibration {
    single_hps: u64,
    parallel_hps: u64,
}

#[derive(Serialize)]
struct Report<'a> {
    schema_version: u32,
    timestamp_unix: u64,
    env: Env,
    config: Config,
    calibration: Calibration,
    results: &'a [NSummary],
    max_n_under_target: Option<u32>,
}

fn main() {
    let args = Args::parse();
    if args.threads > 0 {
        rayon::ThreadPoolBuilder::new()
            .num_threads(args.threads)
            .build_global()
            .expect("failed to set rayon thread count");
    }
    let threads = rayon::current_num_threads();

    print_env(threads);

    println!("{}", "=".repeat(80));
    println!("CALIBRATION ({:.1}s)", args.calibrate_seconds);
    println!("{}", "=".repeat(80));
    let single_hps = calibrate_single_thread(args.calibrate_seconds);
    let (parallel_hps, _) = calibrate_parallel(args.calibrate_seconds);
    println!(
        "  sha-ni single-thread H/s : {}",
        fmt_int(single_hps as u64)
    );
    println!(
        "  sha-ni parallel   H/s    : {}",
        fmt_int(parallel_hps as u64)
    );
    let predicted_n = predict_n(parallel_hps, args.target);
    println!(
        "  Predicted N : ~{} hex zeros should fit in {:.0}s",
        predicted_n, args.target
    );
    println!();

    println!("{}", "=".repeat(80));
    println!(
        "BENCHMARK (target = {:.0}s, runs per N = {}, threads = {})",
        args.target, args.runs, threads
    );
    println!("{}", "=".repeat(80));
    println!(
        "{:>3} | {:>4} | {:>9} | {:>10} | {:>8} | {:>8} | {:>8} | {:>8}",
        "N", "runs", "mean t,s", "median t,s", "p95 t,s", "max t,s", "σ t,s", "H/s"
    );
    println!("{}", "-".repeat(80));

    let mut best_n: Option<u32> = None;
    let per_n_budget = (args.target * 3.0).max(30.0);
    let mut rng = rand::thread_rng();
    let mut summaries: Vec<NSummary> = Vec::new();

    for n_zeros in args.start..=args.max {
        let mut attempts_vec = vec![];
        let mut elapsed_vec = vec![];
        let mut spent = 0.0;

        for _ in 0..args.runs {
            let mut token = [0u8; 16];
            rng.fill_bytes(&mut token);
            let start_nonce = rng.next_u64();
            let t = Instant::now();
            let r = solve(&token, n_zeros, start_nonce, 0);
            let dt = t.elapsed().as_secs_f64();
            attempts_vec.push(r.attempts);
            elapsed_vec.push(dt);
            spent += dt;
            if spent > per_n_budget {
                break;
            }
        }

        let stats = Stats::from(&elapsed_vec, &attempts_vec);
        let s = NSummary {
            n_zeros,
            runs: elapsed_vec.len(),
            elapsed_secs: elapsed_vec,
            attempts: attempts_vec,
            stats,
        };

        println!(
            "{:>3} | {:>4} | {:>9.3} | {:>10.3} | {:>8.3} | {:>8.3} | {:>8.3} | {:>8}",
            s.n_zeros,
            s.runs,
            s.stats.mean_elapsed,
            s.stats.median_elapsed,
            s.stats.p95_elapsed,
            s.stats.max_elapsed,
            s.stats.stddev_elapsed,
            fmt_int(s.stats.effective_hps as u64),
        );

        if s.stats.median_elapsed <= args.target {
            best_n = Some(s.n_zeros);
        }
        let me = s.stats.mean_elapsed;
        summaries.push(s);
        if me > args.target * 2.0 {
            println!("  (stop: mean elapsed {:.1}s > 2 × target)", me);
            break;
        }
    }

    println!();
    println!("{}", "=".repeat(80));
    println!("RESULT");
    println!("{}", "=".repeat(80));
    match best_n {
        Some(n) => println!(
            "  Max N such that median solve time <= {:.0}s: N = {} hex zeros \
             (~{} expected attempts)",
            args.target,
            n,
            fmt_int(16u64.pow(n))
        ),
        None => println!(
            "  Even N={} exceeds {:.0}s on average.",
            args.start, args.target
        ),
    }

    if let Some(path) = &args.json {
        let report = Report {
            schema_version: 2,
            timestamp_unix: now_unix(),
            env: Env {
                os: std::env::consts::OS,
                arch: std::env::consts::ARCH,
                rayon_threads: threads,
                pow_version: env!("CARGO_PKG_VERSION"),
            },
            config: Config {
                backend: "Rust",
                target_secs: args.target,
                runs_per_n: args.runs,
                threads,
                start: args.start,
                max: args.max,
                calibrate_seconds: args.calibrate_seconds,
            },
            calibration: Calibration {
                single_hps: single_hps as u64,
                parallel_hps: parallel_hps as u64,
            },
            results: &summaries,
            max_n_under_target: best_n,
        };
        match write_json(path, &report) {
            Ok(()) => println!("  JSON written to {}", path.display()),
            Err(e) => eprintln!("  failed to write JSON: {}", e),
        }
    }
}

fn write_json(path: &PathBuf, report: &Report) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let f = File::create(path)?;
    let mut w = BufWriter::new(f);
    serde_json::to_writer_pretty(&mut w, report)?;
    use std::io::Write;
    writeln!(w)?;
    Ok(())
}

fn predict_n(hps: f64, target: f64) -> u32 {
    let mut n: u32 = 0;
    while (16u64.pow(n + 1) as f64) / hps < target {
        n += 1;
        if n >= 16 {
            break;
        }
    }
    n
}

fn mean(xs: &[f64]) -> f64 {
    if xs.is_empty() {
        0.0
    } else {
        xs.iter().sum::<f64>() / xs.len() as f64
    }
}

fn sample_stddev(xs: &[f64]) -> f64 {
    if xs.len() < 2 {
        return 0.0;
    }
    let m = mean(xs);
    let var = xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (xs.len() - 1) as f64;
    var.sqrt()
}

/// Nearest-rank percentile. The simplest definition that doesn't lie via
/// interpolation on small samples.
fn percentile(xs: &[f64], p: f64) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    let mut v = xs.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    let rank = (p * n as f64).ceil() as usize;
    let idx = rank.saturating_sub(1).min(n - 1);
    v[idx]
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

fn print_env(threads: usize) {
    println!("{}", "=".repeat(80));
    println!("ENVIRONMENT");
    println!("{}", "=".repeat(80));
    println!("  pow version  : {}", env!("CARGO_PKG_VERSION"));
    println!("  OS           : {}", std::env::consts::OS);
    println!("  Arch         : {}", std::env::consts::ARCH);
    println!("  rayon threads: {}", threads);
    println!();
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentile_basic() {
        let xs = vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0];
        assert_eq!(percentile(&xs, 0.50), 5.0);
        assert_eq!(percentile(&xs, 0.95), 10.0);
        assert_eq!(percentile(&xs, 0.99), 10.0);
        assert_eq!(percentile(&[], 0.5), 0.0);
        assert_eq!(percentile(&[42.0], 0.5), 42.0);
    }

    #[test]
    fn stddev_basic() {
        let xs = vec![2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0];
        let s = sample_stddev(&xs);
        assert!((s - 2.138).abs() < 0.01, "got {}", s);
        assert_eq!(sample_stddev(&[1.0]), 0.0);
    }

    #[test]
    fn predict_n_sanity() {
        // 1 GH/s, 60 s budget → 60 GH available.
        // 16^9 = 68.7G > 60G, 16^8 = 4.3G < 60G → answer is 8.
        assert_eq!(predict_n(1_000_000_000.0, 60.0), 8);
    }
}
