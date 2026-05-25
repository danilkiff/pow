use clap::Parser;
use pow::{calibrate_parallel, calibrate_single_thread, solve, PowResult};
use rand::RngCore;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

#[derive(Parser, Debug)]
#[command(about = "PoW benchmark — find max N (hex zeros) that fits the target budget")]
struct Args {
    #[arg(long, default_value_t = 4)]
    start: u32,
    #[arg(long, default_value_t = 12)]
    max: u32,
    /// Target number of runs per N. May be cut short by --per-n-budget.
    #[arg(long, default_value_t = 30)]
    runs: usize,
    /// Per-run budget in seconds — the headline figure we report against.
    #[arg(long, default_value_t = 60.0)]
    target: f64,
    /// Wall-clock cap for ALL runs at a given N. Default = 3 × target.
    #[arg(long)]
    per_n_budget: Option<f64>,
    #[arg(long, default_value_t = 2.0)]
    calibrate_seconds: f64,
    /// Worker threads (0 = all logical cores).
    #[arg(short = 'j', long, default_value_t = 0)]
    threads: usize,
    /// Dump structured results (env + per-N raw runs + summary) here.
    #[arg(long)]
    json: Option<PathBuf>,
}

fn solve_with(token: &[u8], n: u32, start_nonce: u64, threads: usize) -> PowResult {
    solve(token, n, start_nonce, threads)
}

struct NSummary {
    n_zeros: u32,
    runs: usize,
    attempts: Vec<u64>,
    elapsed: Vec<f64>,
}

impl NSummary {
    fn mean_elapsed(&self) -> f64 {
        mean(&self.elapsed)
    }
    fn median_elapsed(&self) -> f64 {
        percentile(&self.elapsed, 0.50)
    }
    fn p95_elapsed(&self) -> f64 {
        percentile(&self.elapsed, 0.95)
    }
    fn p99_elapsed(&self) -> f64 {
        percentile(&self.elapsed, 0.99)
    }
    fn min_elapsed(&self) -> f64 {
        self.elapsed.iter().cloned().fold(f64::INFINITY, f64::min)
    }
    fn max_elapsed(&self) -> f64 {
        self.elapsed.iter().cloned().fold(0.0_f64, f64::max)
    }
    fn stddev_elapsed(&self) -> f64 {
        sample_stddev(&self.elapsed)
    }
    fn mean_attempts(&self) -> f64 {
        mean(&self.attempts.iter().map(|&x| x as f64).collect::<Vec<_>>())
    }
    fn effective_hps(&self) -> f64 {
        let s: u64 = self.attempts.iter().sum();
        let t: f64 = self.elapsed.iter().sum();
        if t > 0.0 {
            s as f64 / t
        } else {
            0.0
        }
    }
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
    let sha_ni_single = calibrate_single_thread(args.calibrate_seconds);
    let (sha_ni_par, _) = calibrate_parallel(args.calibrate_seconds);
    println!(
        "  sha-ni single-thread H/s : {}",
        fmt_int(sha_ni_single as u64)
    );
    println!(
        "  sha-ni parallel   H/s    : {}",
        fmt_int(sha_ni_par as u64)
    );
    let calib_hps = sha_ni_par;
    let predicted_n = predict_n(calib_hps, args.target);
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
    let per_n_budget = args.per_n_budget.unwrap_or(args.target * 3.0).max(30.0);
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
            let r = solve_with(&token, n_zeros, start_nonce, 0);
            let dt = t.elapsed().as_secs_f64();
            attempts_vec.push(r.attempts);
            elapsed_vec.push(dt);
            spent += dt;
            if spent > per_n_budget {
                break;
            }
        }

        let s = NSummary {
            n_zeros,
            runs: elapsed_vec.len(),
            attempts: attempts_vec,
            elapsed: elapsed_vec,
        };

        println!(
            "{:>3} | {:>4} | {:>9.3} | {:>10.3} | {:>8.3} | {:>8.3} | {:>8.3} | {:>8}",
            s.n_zeros,
            s.runs,
            s.mean_elapsed(),
            s.median_elapsed(),
            s.p95_elapsed(),
            s.max_elapsed(),
            s.stddev_elapsed(),
            fmt_int(s.effective_hps() as u64),
        );

        if s.median_elapsed() <= args.target {
            best_n = Some(s.n_zeros);
        }
        let me = s.mean_elapsed();
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
        let report = JsonReport {
            path,
            args: &args,
            threads,
            sha_ni_single,
            sha_ni_par,
            best_n,
            summaries: &summaries,
        };
        match write_json(&report) {
            Ok(()) => println!("  JSON written to {}", path.display()),
            Err(e) => eprintln!("  failed to write JSON: {}", e),
        }
    }
}

struct JsonReport<'a> {
    path: &'a PathBuf,
    args: &'a Args,
    threads: usize,
    sha_ni_single: f64,
    sha_ni_par: f64,
    best_n: Option<u32>,
    summaries: &'a [NSummary],
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

fn write_json(r: &JsonReport) -> std::io::Result<()> {
    if let Some(parent) = r.path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let f = File::create(r.path)?;
    let mut w = BufWriter::new(f);

    writeln!(w, "{{")?;
    writeln!(w, "  \"schema_version\": 1,")?;
    writeln!(w, "  \"timestamp_unix\": {},", now_unix())?;
    writeln!(w, "  \"env\": {{")?;
    writeln!(w, "    \"os\": \"{}\",", std::env::consts::OS)?;
    writeln!(w, "    \"arch\": \"{}\",", std::env::consts::ARCH)?;
    writeln!(w, "    \"rayon_threads\": {},", r.threads)?;
    writeln!(w, "    \"pow_version\": \"{}\"", env!("CARGO_PKG_VERSION"))?;
    writeln!(w, "  }},")?;
    writeln!(w, "  \"config\": {{")?;
    writeln!(w, "    \"target_secs\": {},", r.args.target)?;
    writeln!(w, "    \"runs_per_n\": {},", r.args.runs)?;
    writeln!(w, "    \"threads\": {},", r.threads)?;
    writeln!(w, "    \"start\": {},", r.args.start)?;
    writeln!(w, "    \"max\": {},", r.args.max)?;
    writeln!(w, "    \"calibrate_seconds\": {}", r.args.calibrate_seconds)?;
    writeln!(w, "  }},")?;
    writeln!(w, "  \"calibration\": {{")?;
    writeln!(w, "    \"sha_ni_single_hps\": {},", r.sha_ni_single as u64)?;
    writeln!(w, "    \"sha_ni_parallel_hps\": {}", r.sha_ni_par as u64)?;
    writeln!(w, "  }},")?;

    writeln!(w, "  \"results\": [")?;
    for (i, s) in r.summaries.iter().enumerate() {
        writeln!(w, "    {{")?;
        writeln!(w, "      \"n_zeros\": {},", s.n_zeros)?;
        writeln!(w, "      \"runs\": {},", s.runs)?;
        writeln!(w, "      \"elapsed_secs\": [{}],", join_f64(&s.elapsed))?;
        writeln!(w, "      \"attempts\": [{}],", join_u64(&s.attempts))?;
        writeln!(w, "      \"stats\": {{")?;
        writeln!(w, "        \"mean_elapsed\": {},", s.mean_elapsed())?;
        writeln!(w, "        \"median_elapsed\": {},", s.median_elapsed())?;
        writeln!(w, "        \"p95_elapsed\": {},", s.p95_elapsed())?;
        writeln!(w, "        \"p99_elapsed\": {},", s.p99_elapsed())?;
        writeln!(w, "        \"min_elapsed\": {},", s.min_elapsed())?;
        writeln!(w, "        \"max_elapsed\": {},", s.max_elapsed())?;
        writeln!(w, "        \"stddev_elapsed\": {},", s.stddev_elapsed())?;
        writeln!(w, "        \"mean_attempts\": {},", s.mean_attempts())?;
        writeln!(w, "        \"effective_hps\": {}", s.effective_hps())?;
        writeln!(w, "      }}")?;
        let sep = if i + 1 < r.summaries.len() { "," } else { "" };
        writeln!(w, "    }}{}", sep)?;
    }
    writeln!(w, "  ],")?;
    match r.best_n {
        Some(n) => writeln!(w, "  \"max_n_under_target\": {}", n)?,
        None => writeln!(w, "  \"max_n_under_target\": null")?,
    }
    writeln!(w, "}}")?;
    w.flush()?;
    Ok(())
}

fn join_f64(xs: &[f64]) -> String {
    xs.iter()
        .map(|x| format!("{}", x))
        .collect::<Vec<_>>()
        .join(", ")
}
fn join_u64(xs: &[u64]) -> String {
    xs.iter()
        .map(|x| x.to_string())
        .collect::<Vec<_>>()
        .join(", ")
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
        // population variance of [2,4,4,4,5,5,7,9] is 4, so population σ = 2.
        let xs = vec![2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0];
        let s = sample_stddev(&xs);
        // Sample σ is slightly higher than population σ; for n=8 it is ~2.138.
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
