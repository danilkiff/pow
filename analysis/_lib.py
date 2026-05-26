"""Shared helpers for explore_results.ipynb and explore_results_simple.ipynb.

Lives next to the notebooks so they can stay code-light: data loading,
summary table, plots, and formatting all live here; the notebooks just
narrate and call these functions.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from IPython.display import display
from scipy import stats

sns.set_theme(context="notebook", style="whitegrid")

# Tail/density stats are unreliable below this run count. Median stays.
MIN_RUNS_TAIL = 20

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"


# ---------------------------------------------------------------- utilities


def _fmt2(v: float) -> str:
    """Two significant figures, never scientific."""
    if v == 0 or not math.isfinite(v):
        return "0"
    digits = max(0, 1 - math.floor(math.log10(abs(v))))
    return f"{v:.{digits}f}"


def _fmt_hps(v: float) -> str:
    """Hashrate with space thousand-separators; never scientific."""
    return f"{round(v):,}".replace(",", " ")


def nearest_rank_percentile(xs, p: float) -> float:
    """Nearest-rank percentile; matches rust/python bench (no interpolation)."""
    arr = np.asarray(list(xs), dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return float("nan")
    s = np.sort(arr)
    rank = int(np.ceil(p * s.size))
    return float(s[max(0, min(rank, s.size) - 1)])


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score CI for a binomial proportion. Stable at k=0, k=n."""
    if n == 0:
        return (0.0, 1.0)
    z = stats.norm.ppf(1 - alpha / 2)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    halfw = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - halfw), min(1.0, centre + halfw))


# ----------------------------------------------------------------- loading


@dataclass
class Run:
    source: str  # filename
    host: str
    backend: str
    threads: int
    target_secs: float
    runs_per_n: int
    calibration: dict
    timestamp: str
    label: str
    group_key: tuple
    df: pd.DataFrame  # one row per (N, run_index)


def calib_for(r: Run) -> float:
    return float(r.calibration["parallel_hps" if r.threads > 1 else "single_hps"])


def _load_one(path: Path) -> Run:
    data = json.loads(path.read_text())
    parts = path.stem.split("-") if path.stem.startswith("bench-") else []
    host = parts[1] if len(parts) > 1 else "unknown"
    stamp = parts[2] if len(parts) > 2 else ""
    backend = (
        "-".join(parts[3:])
        if len(parts) > 3
        else str(data.get("config", {}).get("backend", "default")).lower()
    )
    threads = int(data["config"]["threads"])
    target_secs = float(data["config"]["target_secs"])
    rows = []
    for r in data["results"]:
        for i, (att, el) in enumerate(zip(r["attempts"], r["elapsed_secs"], strict=True)):
            rows.append(
                {
                    "n_zeros": r["n_zeros"],
                    "run": i,
                    "attempts": att,
                    "elapsed": el,
                    "hps": att / el if el > 0 else 0.0,
                }
            )
    return Run(
        source=path.name,
        host=host,
        backend=backend,
        threads=threads,
        target_secs=target_secs,
        runs_per_n=int(data["config"]["runs_per_n"]),
        calibration=data["calibration"],
        timestamp=stamp,
        label=f"{host}/{backend}",
        group_key=(path.name, host, backend, threads, target_secs, stamp),
        df=pd.DataFrame(rows),
    )


def load_runs() -> list[Run]:
    """Discover all bench-*.json, print a one-line summary per file, return list."""
    if not RESULTS_DIR.exists():
        print(f"no results dir: {RESULTS_DIR}")
        return []
    out = [_load_one(p) for p in sorted(RESULTS_DIR.glob("bench-*.json"))]
    seen: dict[str, list] = {}
    for r in out:
        seen.setdefault(r.label, []).append(r.group_key)
    for lbl, keys in seen.items():
        if len(keys) > 1:
            print(f"NOTE: label {lbl!r} maps to {len(keys)} distinct files")
    print(f"loaded {len(out)} file(s) from {RESULTS_DIR}")
    for r in out:
        n_min = int(r.df["n_zeros"].min())
        n_max = int(r.df["n_zeros"].max())
        print(
            f"  {r.source}: {r.label} threads={r.threads} "
            f"target={r.target_secs:.0f}s N={n_min}..{n_max} rows={len(r.df)}"
        )
    return out


# ---------------------------------------------------------------- tables


def summary_table(runs: list[Run]) -> pd.DataFrame:
    frames = []
    for r in runs:
        g = r.df.groupby("n_zeros")
        s = pd.DataFrame(
            {
                "runs": g.size(),
                "median_s": g["elapsed"].median(),
                "mean_s": g["elapsed"].mean(),
                "p95_s": g["elapsed"].apply(lambda x: nearest_rank_percentile(x, 0.95)),
                "max_s": g["elapsed"].max(),
                "stddev_s": g["elapsed"].std(),
                "eff_hps": g.apply(
                    lambda x: (
                        x["attempts"].sum() / x["elapsed"].sum() if x["elapsed"].sum() > 0 else 0.0
                    )
                ),
            }
        )
        small = s["runs"] < MIN_RUNS_TAIL
        s.loc[small, ["p95_s", "stddev_s"]] = float("nan")
        s["label"] = r.label
        frames.append(s.reset_index())
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out[
        [
            "label",
            "n_zeros",
            "runs",
            "median_s",
            "mean_s",
            "p95_s",
            "max_s",
            "stddev_s",
            "eff_hps",
        ]
    ]


def show_table(df: pd.DataFrame):
    """Format the summary table: 3 decimals for time, space-separated integers for eff_hps."""
    return df.style.format(
        {
            "median_s": "{:.3f}",
            "mean_s": "{:.3f}",
            "p95_s": "{:.3f}",
            "max_s": "{:.3f}",
            "stddev_s": "{:.3f}",
            "eff_hps": _fmt_hps,
        },
        na_rep="—",
    )


def headline_table(runs: list[Run]) -> pd.DataFrame:
    rows = []
    for r in runs:
        median_per_n = r.df.groupby("n_zeros")["elapsed"].median()
        passing = median_per_n[median_per_n <= r.target_secs]
        max_n = int(passing.index.max()) if not passing.empty else None
        rows.append(
            {
                "label": r.label,
                "target_s": r.target_secs,
                "max_n_median_under_target": max_n,
            }
        )
    return pd.DataFrame(rows)


def hit_rate_table(runs: list[Run]) -> pd.DataFrame:
    rows = []
    for r in runs:
        for n_zeros, g in r.df.groupby("n_zeros"):
            n = len(g)
            k = int((g["elapsed"] <= r.target_secs).sum())
            lo, hi = wilson_ci(k, n)
            rows.append(
                {
                    "label": r.label,
                    "n_zeros": int(n_zeros),
                    "target_s": r.target_secs,
                    "runs": n,
                    "hits": k,
                    "p_hit": k / n if n else float("nan"),
                    "p_hit_lo": lo,
                    "p_hit_hi": hi,
                }
            )
    return pd.DataFrame(rows)


def show_headline(runs: list[Run]) -> None:
    display(headline_table(runs))
    display(
        hit_rate_table(runs).style.format(
            {"p_hit": "{:.3f}", "p_hit_lo": "{:.3f}", "p_hit_hi": "{:.3f}"}
        )
    )


def diagnostics_table(runs: list[Run]) -> pd.DataFrame:
    rows = []
    for r in runs:
        calib = calib_for(r)
        for n_zeros, g in r.df.groupby("n_zeros"):
            attempts = g["attempts"].to_numpy(dtype=float)
            elapsed = g["elapsed"].to_numpy(dtype=float)
            theo_median = math.log(2) * (16**n_zeros) / calib
            rows.append(
                {
                    "label": r.label,
                    "n_zeros": int(n_zeros),
                    "runs": len(g),
                    "attempts_mean_over_16N": float(np.mean(attempts) / (16**n_zeros)),
                    "elapsed_median_over_theo": float(np.median(elapsed) / theo_median),
                    "eff_over_calib": float((attempts.sum() / elapsed.sum()) / calib),
                }
            )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- plots


def _palette_for(labels):
    return dict(zip(labels, sns.color_palette(n_colors=len(labels)), strict=True))


def _df_all(runs: list[Run]) -> pd.DataFrame:
    return pd.concat(
        [
            r.df.assign(
                label=r.label,
                target_secs=r.target_secs,
                threads=r.threads,
                calib_hps=calib_for(r),
            )
            for r in runs
        ],
        ignore_index=True,
    )


def _draw_distribution(ax, df_all, order_labels, palette, dodge_width=0.6):
    """Strip + point overlay shared by simple and full plots."""
    sns.stripplot(
        data=df_all,
        x="n_zeros",
        y="elapsed",
        hue="label",
        hue_order=order_labels,
        palette=palette,
        dodge=True,
        jitter=0.2,
        alpha=0.35,
        size=4,
        native_scale=True,
        ax=ax,
        legend=False,
    )
    sns.pointplot(
        data=df_all,
        x="n_zeros",
        y="elapsed",
        hue="label",
        hue_order=order_labels,
        palette=palette,
        estimator="median",
        errorbar=("pi", 95),
        dodge=dodge_width,
        linestyle="none",
        markers="_",
        markersize=14,
        err_kws={"linewidth": 1.5},
        native_scale=True,
        ax=ax,
    )
    k = len(order_labels)
    for i, label in enumerate(order_labels):
        off = dodge_width * (i - (k - 1) / 2) / k
        sub = df_all[df_all["label"] == label]
        med = sub.groupby("n_zeros")["elapsed"].median()
        cnt = sub.groupby("n_zeros").size()
        for n, v in med.items():
            ax.annotate(
                f"N={int(n)}: {_fmt2(v)}s · n={int(cnt[n])}",
                (n + off, v),
                textcoords="offset points",
                xytext=(6, 4),
                fontsize=7,
                color=palette[label],
            )


def _annotate_x(ax, df_all):
    n_levels = sorted(int(n) for n in df_all["n_zeros"].unique())
    ax.set_xticks(n_levels)
    for n in n_levels:
        ax.axvline(n, color="lightgrey", linestyle=":", linewidth=0.8, alpha=0.7, zorder=0)
    return n_levels


def plot_solve_times(runs: list[Run]) -> None:
    """Single-panel solve-time plot — for the compact notebook."""
    if not runs:
        print("no data — run ./repro.sh")
        return
    df_all = _df_all(runs)
    order_labels = sorted(df_all["label"].unique())
    palette = _palette_for(order_labels)
    targets = sorted({float(r.target_secs) for r in runs})

    _fig, ax = plt.subplots(figsize=(10, 6))
    _draw_distribution(ax, df_all, order_labels, palette)
    _annotate_x(ax, df_all)
    for tgt in targets:
        ax.axhline(tgt, color="grey", linestyle="--", linewidth=1, label=f"target {tgt:.0f}s")
    ax.set_yscale("log")
    ax.set_xlabel("N (leading hex zeros)")
    ax.set_ylabel("elapsed, s (log)")
    ax.set_title("Per-run dots; median ± raw p2.5-p97.5 spread (not a CI)")
    ax.legend(loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.show()


def plot_solve_times_full(runs: list[Run]) -> None:
    """Two-panel plot: distribution on top, bootstrap-CI median with theory below."""
    if not runs:
        print("no data — run ./repro.sh")
        return
    df_all = _df_all(runs)
    order_labels = sorted(df_all["label"].unique())
    palette = _palette_for(order_labels)
    targets = sorted({float(r.target_secs) for r in runs})

    _fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(10, 9), sharex=True, gridspec_kw={"height_ratios": [3, 2]}
    )
    _draw_distribution(ax_top, df_all, order_labels, palette)
    n_levels = _annotate_x(ax_top, df_all)
    ax_top.tick_params(axis="x", labelbottom=True)
    for tgt in targets:
        ax_top.axhline(tgt, color="grey", linestyle="--", linewidth=1, label=f"target {tgt:.0f}s")
    ax_top.set_yscale("log")
    ax_top.set_ylabel("elapsed, s (log)")
    ax_top.set_xlabel("")
    ax_top.set_title("Per-run dots; median ± raw p2.5-p97.5 spread (not a CI)")
    ax_top.legend(loc="upper left", fontsize=8)

    sns.lineplot(
        data=df_all,
        x="n_zeros",
        y="elapsed",
        hue="label",
        hue_order=order_labels,
        palette=palette,
        estimator="median",
        errorbar=("ci", 95),
        n_boot=2000,
        seed=0,
        marker="o",
        ax=ax_bot,
        legend=False,
    )
    _annotate_x(ax_bot, df_all)
    ns_smooth = np.linspace(min(n_levels), max(n_levels), 100)
    ln2 = np.log(2)
    for label in order_labels:
        sub = df_all[df_all["label"] == label]
        calib = float(sub["calib_hps"].iloc[0])
        eff_pool = float(sub["attempts"].sum() / sub["elapsed"].sum())
        ax_bot.plot(
            ns_smooth,
            ln2 * (16**ns_smooth) / calib,
            color=palette[label],
            linewidth=1.3,
            linestyle=":",
            alpha=0.8,
            label=rf"{label}: calib bound, $r={_fmt2(calib / 1e6)}\,\mathrm{{MH/s}}$",
        )
        ax_bot.plot(
            ns_smooth,
            ln2 * (16**ns_smooth) / eff_pool,
            color=palette[label],
            linewidth=1.5,
            linestyle="--",
            alpha=0.9,
            label=rf"{label}: pooled effective, $r={_fmt2(eff_pool / 1e6)}\,\mathrm{{MH/s}}$",
        )
    for tgt in targets:
        ax_bot.axhline(tgt, color="grey", linestyle="--", linewidth=1)
    ax_bot.set_yscale("log")
    ax_bot.set_xlabel("N (leading hex zeros)")
    ax_bot.set_ylabel("elapsed, s (log)")
    ax_bot.set_title(
        r"Empirical median + bootstrap 95% CI vs $\ln 2 \cdot 16^N / r$ "
        r"for calibrated and pooled effective $r$"
    )
    ax_bot.legend(loc="upper left", fontsize=7)
    plt.tight_layout()
    plt.show()


def _best_shared_n(runs: list[Run], min_runs: int = 10) -> int | None:
    counts = (
        pd.concat([r.df.assign(label=r.label) for r in runs]).groupby(["label", "n_zeros"]).size()
    )
    by_n: dict[int, int] = {}
    for (_, n), c in counts.items():
        if c >= min_runs:
            by_n[int(n)] = by_n.get(int(n), 0) + 1
    if not by_n:
        return None
    max_share = max(by_n.values())
    return max(n for n, c in by_n.items() if c == max_share)


def plot_ecdf(runs: list[Run], n: int | None = None) -> None:
    if not runs:
        print("no data")
        return
    if n is None:
        n = _best_shared_n(runs)
        if n is None:
            print("no implementation has >= 10 runs at any N")
            return
    rows = []
    for r in runs:
        sub = r.df[r.df["n_zeros"] == n]
        if len(sub) < 2:
            continue
        rows.append(sub.assign(label=r.label, calib_hps=calib_for(r)))
    if not rows:
        print(f"no implementation has enough samples at N={n}")
        return
    df_n = pd.concat(rows, ignore_index=True)
    labels = sorted(df_n["label"].unique())
    palette = _palette_for(labels)

    _fig, ax = plt.subplots(figsize=(9, 5))
    sns.ecdfplot(data=df_n, x="elapsed", hue="label", hue_order=labels, palette=palette, ax=ax)
    t_max = df_n["elapsed"].max() * 1.2
    ts = np.linspace(0, t_max, 300)
    for label in labels:
        sub = df_n[df_n["label"] == label]
        rate_eff = (sub["attempts"].sum() / sub["elapsed"].sum()) / (16**n)
        rate_calib = sub["calib_hps"].iloc[0] / (16**n)
        ax.plot(
            ts,
            stats.expon.cdf(ts, scale=1.0 / rate_eff),
            color=palette[label],
            linestyle="--",
            linewidth=1.4,
            alpha=0.85,
            label=f"{label} — Exp(λ_eff≈{_fmt2(rate_eff)}/s)",
        )
        ax.plot(
            ts,
            stats.expon.cdf(ts, scale=1.0 / rate_calib),
            color=palette[label],
            linestyle=":",
            linewidth=1.2,
            alpha=0.6,
            label=f"{label} — Exp(λ_calib≈{_fmt2(rate_calib)}/s) [bound]",
        )
    ax.set_xlabel("elapsed, s")
    ax.set_ylabel("CDF")
    ax.set_title(
        f"Solve-time distribution at N={n}: empirical vs theoretical (effective and calibrated)"
    )
    ax.legend(loc="lower right", fontsize=7)
    plt.tight_layout()
    plt.show()


def plot_pdf(runs: list[Run], n: int | None = None) -> None:
    if not runs:
        print("no data")
        return
    if n is None:
        n = _best_shared_n(runs)
        if n is None:
            return
    rows = []
    for r in runs:
        sub = r.df[r.df["n_zeros"] == n]
        if len(sub) < MIN_RUNS_TAIL:
            continue
        rows.append(sub.assign(label=r.label, calib_hps=calib_for(r)))
    if not rows:
        print(f"no implementation has >= {MIN_RUNS_TAIL} samples at N={n}; density view skipped")
        return
    df_n = pd.concat(rows, ignore_index=True)
    labels = sorted(df_n["label"].unique())
    palette = _palette_for(labels)

    _fig, axes = plt.subplots(1, len(labels), figsize=(5 * len(labels), 4), sharey=False)
    if len(labels) == 1:
        axes = [axes]
    for ax, label in zip(axes, labels, strict=True):
        sub = df_n[df_n["label"] == label]
        sns.histplot(
            sub["elapsed"],
            bins="auto",
            stat="density",
            color=palette[label],
            ax=ax,
            alpha=0.5,
            edgecolor="none",
        )
        rate_eff = (sub["attempts"].sum() / sub["elapsed"].sum()) / (16**n)
        rate_calib = sub["calib_hps"].iloc[0] / (16**n)
        ts = np.linspace(1e-9, sub["elapsed"].max() * 1.2, 300)
        ax.plot(
            ts,
            stats.expon.pdf(ts, scale=1.0 / rate_eff),
            color=palette[label],
            linewidth=1.6,
            label=f"Exp(λ_eff≈{_fmt2(rate_eff)}/s)",
        )
        ax.plot(
            ts,
            stats.expon.pdf(ts, scale=1.0 / rate_calib),
            color=palette[label],
            linewidth=1.2,
            linestyle=":",
            alpha=0.7,
            label=f"Exp(λ_calib≈{_fmt2(rate_calib)}/s)",
        )
        ax.set_title(f"{label} — N={n}, n_runs={len(sub)}")
        ax.set_xlabel("elapsed, s")
        ax.set_ylabel("density")
        ax.legend(loc="upper right", fontsize=8)
    plt.tight_layout()
    plt.show()


def plot_diagnostics(runs: list[Run]) -> None:
    if not runs:
        return
    diag = diagnostics_table(runs)
    labels = sorted(diag["label"].unique())
    palette = _palette_for(labels)

    _fig, axes = plt.subplots(1, 3, figsize=(15, 4), sharex=True)
    panels = [
        ("attempts_mean_over_16N", r"mean $A / 16^N$ (prob. model; ref=1)"),
        (
            "elapsed_median_over_theo",
            r"median $T / (\ln 2 \cdot 16^N / r_{\mathrm{calib}})$ (overhead; ref=1)",
        ),
        ("eff_over_calib", r"$r_{\mathrm{eff}} / r_{\mathrm{calib}}$ (rate ratio; ref=1)"),
    ]
    for ax, (col, title) in zip(axes, panels, strict=True):
        sns.lineplot(
            data=diag,
            x="n_zeros",
            y=col,
            hue="label",
            hue_order=labels,
            palette=palette,
            marker="o",
            ax=ax,
        )
        ax.axhline(1.0, color="grey", linestyle=":", linewidth=1)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("N")
        ax.set_ylabel(col)
        ax.legend(fontsize=7)
    plt.tight_layout()
    plt.show()
    display(diag.style.format({col: "{:.3f}" for col, _ in panels}, na_rep="—"))


def show_comparison(runs: list[Run]) -> None:
    if not runs:
        return
    pivot = summary_table(runs).pivot_table(index="n_zeros", columns="label", values="median_s")
    display(pivot.style.format("{:.3f}", na_rep="—"))
    if pivot.shape[1] >= 2:
        baseline = pivot.iloc[:, 0]
        rel_time = pivot.div(baseline, axis=0)
        speedup = pd.DataFrame(
            baseline.to_numpy().reshape(-1, 1) / pivot.to_numpy(),
            index=pivot.index,
            columns=pivot.columns,
        )
        print(f"relative time vs {pivot.columns[0]} (lower = faster):")
        display(rel_time.style.format("{:.3f}", na_rep="—"))
        print(f"speedup vs {pivot.columns[0]} (baseline / this; higher = faster):")
        display(speedup.style.format("{:.2f}", na_rep="—"))
