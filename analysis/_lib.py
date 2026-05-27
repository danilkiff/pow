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
# ECDFs remain useful at smaller n, but density plots below this are too sparse.
MIN_RUNS_DISTRIBUTION = 10

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


def nearest_rank_median(xs) -> float:
    """Median under the same nearest-rank rule as the benchmark JSON."""
    return nearest_rank_percentile(xs, 0.50)


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
                "median_s": g["elapsed"].apply(nearest_rank_median),
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
        median_per_n = r.df.groupby("n_zeros")["elapsed"].apply(nearest_rank_median)
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
                    "target_runs": r.runs_per_n,
                    "attempts_mean_over_16N": float(np.mean(attempts) / (16**n_zeros)),
                    "elapsed_median_over_theo": float(nearest_rank_median(elapsed) / theo_median),
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
                source=r.source,
                label=r.label,
                target_secs=r.target_secs,
                runs_per_n=r.runs_per_n,
                threads=r.threads,
                calib_hps=calib_for(r),
            )
            for r in runs
        ],
        ignore_index=True,
    )


def _sample_text(count: int, target: int | None) -> str:
    run_text = f"n={count}/{target}" if target and count < target else f"n={count}"
    if count < MIN_RUNS_TAIL:
        run_text += ", low-n"
    return run_text


def _group_summary_rows(df_all, order_labels, dodge_width=0.6):
    rows = []
    k = len(order_labels)
    for i, label in enumerate(order_labels):
        off = dodge_width * (i - (k - 1) / 2) / k
        sub = df_all[df_all["label"] == label]
        for n_zeros, g in sub.groupby("n_zeros", sort=True):
            elapsed = g["elapsed"].to_numpy(dtype=float)
            count = len(elapsed)
            target_runs = int(g["runs_per_n"].max()) if "runs_per_n" in g else count
            rows.append(
                {
                    "label": label,
                    "n_zeros": int(n_zeros),
                    "x": float(n_zeros) + off,
                    "runs": count,
                    "target_runs": target_runs,
                    "median": nearest_rank_median(elapsed),
                    "lo": nearest_rank_percentile(elapsed, 0.025),
                    "hi": nearest_rank_percentile(elapsed, 0.975),
                    "low_sample": count < MIN_RUNS_TAIL,
                }
            )
    return rows


def _bootstrap_ci_nearest_rank_median(
    xs, rng: np.random.Generator, n_boot: int = 2000
) -> tuple[float, float]:
    arr = np.asarray(xs, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return (float("nan"), float("nan"))
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    samples = np.sort(arr[idx], axis=1)
    rank = max(0, int(np.ceil(0.50 * arr.size)) - 1)
    boots = samples[:, rank]
    return tuple(float(x) for x in np.percentile(boots, [2.5, 97.5]))


def _draw_distribution(ax, df_all, order_labels, palette, dodge_width=0.6):
    """Strip + explicit nearest-rank median overlay shared by plots."""
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
    rows = _group_summary_rows(df_all, order_labels, dodge_width=dodge_width)
    for label in order_labels:
        ax.plot(
            [], [], color=palette[label], marker="_", linestyle="none", markersize=14, label=label
        )
    if any(row["low_sample"] for row in rows):
        ax.plot(
            [],
            [],
            marker="o",
            linestyle="none",
            markerfacecolor="none",
            markeredgecolor="0.35",
            markersize=6,
            label=f"<{MIN_RUNS_TAIL} runs: median only",
        )

    for row in rows:
        color = palette[row["label"]]
        if row["low_sample"]:
            ax.scatter(
                [row["x"]],
                [row["median"]],
                marker="o",
                s=42,
                facecolors="none",
                edgecolors=color,
                linewidths=1.4,
                zorder=4,
            )
        else:
            ax.vlines(
                row["x"],
                row["lo"],
                row["hi"],
                color=color,
                linewidth=1.5,
                alpha=0.9,
                zorder=3,
            )
            ax.plot(
                row["x"],
                row["median"],
                color=color,
                marker="_",
                linestyle="none",
                markersize=14,
                markeredgewidth=2,
                zorder=4,
            )
        ax.annotate(
            f"N={row['n_zeros']}: {_fmt2(row['median'])}s · "
            f"{_sample_text(row['runs'], row['target_runs'])}",
            (row["x"], row["median"]),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=7,
            color="0.35" if row["low_sample"] else color,
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
    ax.set_title("Per-run dots; nearest-rank median ± raw p2.5-p97.5 spread (not a CI)")
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
    ax_top.set_title("Per-run dots; nearest-rank median ± raw p2.5-p97.5 spread (not a CI)")
    ax_top.legend(loc="upper left", fontsize=8)

    rng = np.random.default_rng(0)
    rows = _group_summary_rows(df_all, order_labels, dodge_width=0.0)
    for label in order_labels:
        label_rows = [row for row in rows if row["label"] == label]
        reliable = [row for row in label_rows if not row["low_sample"]]
        previous = None
        for row in reliable:
            if previous and row["n_zeros"] == previous["n_zeros"] + 1:
                ax_bot.plot(
                    [previous["n_zeros"], row["n_zeros"]],
                    [previous["median"], row["median"]],
                    color=palette[label],
                    linewidth=1.6,
                    alpha=0.9,
                )
            previous = row
            group = df_all[(df_all["label"] == label) & (df_all["n_zeros"] == row["n_zeros"])][
                "elapsed"
            ]
            lo, hi = _bootstrap_ci_nearest_rank_median(group, rng)
            ax_bot.errorbar(
                row["n_zeros"],
                row["median"],
                yerr=[[max(0.0, row["median"] - lo)], [max(0.0, hi - row["median"])]],
                color=palette[label],
                marker="o",
                linestyle="none",
                linewidth=1.4,
                capsize=0,
                zorder=4,
            )
        low = [row for row in label_rows if row["low_sample"]]
        if low:
            ax_bot.scatter(
                [row["n_zeros"] for row in low],
                [row["median"] for row in low],
                marker="o",
                s=42,
                facecolors="none",
                edgecolors=palette[label],
                linewidths=1.4,
                zorder=4,
            )
    if any(row["low_sample"] for row in rows):
        ax_bot.scatter(
            [],
            [],
            marker="o",
            facecolors="none",
            edgecolors="0.35",
            label=f"<{MIN_RUNS_TAIL} runs: median only",
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
        r"Nearest-rank median + bootstrap 95% CI vs $\ln 2 \cdot 16^N / r$ "
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


def _normalized_distribution_df(runs: list[Run], n: int, min_runs: int) -> pd.DataFrame:
    rows = []
    for r in runs:
        sub = r.df[r.df["n_zeros"] == n]
        if len(sub) < min_runs:
            continue
        sub = sub.copy()
        rate_eff = (sub["attempts"].sum() / sub["elapsed"].sum()) / (16**n)
        rate_calib = calib_for(r) / (16**n)
        sub["rate_eff"] = rate_eff
        sub["rate_calib"] = rate_calib
        sub["calib_ratio"] = rate_calib / rate_eff if rate_eff > 0 else float("nan")
        sub["elapsed_eff_units"] = sub["elapsed"] * rate_eff
        sub["plot_label"] = f"{r.label} ({_sample_text(len(sub), r.runs_per_n)})"
        rows.append(sub)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def plot_ecdf(runs: list[Run], n: int | None = None) -> None:
    if not runs:
        print("no data")
        return
    if n is None:
        n = _best_shared_n(runs)
        if n is None:
            print("no implementation has >= 10 runs at any N")
            return
    df_n = _normalized_distribution_df(runs, n, min_runs=2)
    if df_n.empty:
        print(f"no implementation has enough samples at N={n}")
        return
    labels = sorted(df_n["plot_label"].unique())
    palette = _palette_for(labels)

    _fig, ax = plt.subplots(figsize=(9, 5))
    sns.ecdfplot(
        data=df_n,
        x="elapsed_eff_units",
        hue="plot_label",
        hue_order=labels,
        palette=palette,
        ax=ax,
    )
    for label in labels:
        ax.plot([], [], color=palette[label], linestyle="-", label=f"{label} empirical ECDF")
    x_max = max(5.0, float(df_n["elapsed_eff_units"].max()) * 1.15)
    xs = np.linspace(0, x_max, 300)
    ax.plot(
        xs,
        stats.expon.cdf(xs, scale=1.0),
        color="black",
        linestyle="--",
        linewidth=1.4,
        label="Exp(1) via pooled effective rate",
    )
    for label in labels:
        sub = df_n[df_n["plot_label"] == label]
        ratio = float(sub["calib_ratio"].iloc[0])
        ax.plot(
            xs,
            stats.expon.cdf(xs, scale=1.0 / ratio),
            color=palette[label],
            linestyle=":",
            linewidth=1.2,
            alpha=0.75,
            label=f"{label} — calibrated bound (rate x{_fmt2(ratio)})",
        )
    ax.set_xlim(left=0, right=x_max)
    ax.set_xlabel(r"normalized elapsed, $\lambda_{\mathrm{eff}} \cdot t$")
    ax.set_ylabel("CDF")
    ax.set_title(f"Normalized solve-time distribution at N={n}: empirical vs Exp(1)")
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
    df_n = _normalized_distribution_df(runs, n, min_runs=MIN_RUNS_DISTRIBUTION)
    if df_n.empty:
        print(
            f"no implementation has >= {MIN_RUNS_DISTRIBUTION} samples at N={n}; "
            "density view skipped"
        )
        return
    labels = sorted(df_n["plot_label"].unique())
    palette = _palette_for(labels)

    _fig, axes = plt.subplots(
        1, len(labels), figsize=(5 * len(labels), 4), sharex=True, sharey=True
    )
    if len(labels) == 1:
        axes = [axes]
    x_max = max(5.0, float(df_n["elapsed_eff_units"].max()) * 1.15)
    xs = np.linspace(1e-9, x_max, 300)
    for ax, label in zip(axes, labels, strict=True):
        sub = df_n[df_n["plot_label"] == label]
        sns.histplot(
            sub["elapsed_eff_units"],
            bins="auto",
            stat="density",
            color=palette[label],
            ax=ax,
            alpha=0.5,
            edgecolor="none",
        )
        ratio = float(sub["calib_ratio"].iloc[0])
        ax.plot(
            xs,
            stats.expon.pdf(xs, scale=1.0),
            color="black",
            linewidth=1.6,
            label="Exp(1) via r_eff",
        )
        ax.plot(
            xs,
            stats.expon.pdf(xs, scale=1.0 / ratio),
            color=palette[label],
            linewidth=1.2,
            linestyle=":",
            alpha=0.7,
            label=f"calibrated bound (rate x{_fmt2(ratio)})",
        )
        ax.set_xlim(left=0, right=x_max)
        ax.set_title(f"{label} — N={n}")
        ax.set_xlabel(r"normalized elapsed, $\lambda_{\mathrm{eff}} \cdot t$")
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
        has_low = False
        for label in labels:
            sub = diag[diag["label"] == label].sort_values("n_zeros")
            reliable = sub[sub["runs"] >= MIN_RUNS_TAIL]
            low = sub[sub["runs"] < MIN_RUNS_TAIL]
            drew_label = False
            if not reliable.empty:
                segment_ns: list[int] = []
                segment_vals: list[float] = []
                prev_n: int | None = None
                for row in reliable.itertuples(index=False):
                    n = int(row.n_zeros)
                    val = float(getattr(row, col))
                    if prev_n is not None and n != prev_n + 1:
                        ax.plot(
                            segment_ns,
                            segment_vals,
                            color=palette[label],
                            marker="o",
                            label=label if not drew_label else None,
                        )
                        drew_label = True
                        segment_ns = []
                        segment_vals = []
                    segment_ns.append(n)
                    segment_vals.append(val)
                    prev_n = n
                ax.plot(
                    segment_ns,
                    segment_vals,
                    color=palette[label],
                    marker="o",
                    label=label if not drew_label else None,
                )
                drew_label = True
            if not low.empty:
                has_low = True
                ax.scatter(
                    low["n_zeros"],
                    low[col],
                    marker="o",
                    s=38,
                    facecolors="none",
                    edgecolors=palette[label],
                    linewidths=1.3,
                    label=label if not drew_label else None,
                )
        ax.axhline(1.0, color="grey", linestyle=":", linewidth=1)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("N")
        ax.set_ylabel(col)
        if has_low:
            ax.scatter(
                [],
                [],
                marker="o",
                facecolors="none",
                edgecolors="0.35",
                label=f"<{MIN_RUNS_TAIL} runs",
            )
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
