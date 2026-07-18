"""Figures for Paper 2 (IEEEtran, single-column width ~3.5in).

fig_scale.pdf — admission-latency medians vs loaded-policy count, per engine,
computed from latency_scale.csv (at the 15-policy level the median of the five
run medians is plotted and the min-max of run medians shown as an error bar).
Grayscale-safe: identity is carried by linestyle + marker, colors are Okabe-Ito.
"""

import csv
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SERIES = {  # engine -> (label, color, linestyle, marker)
    "vap": ("VAP (in-tree CEL)", "#0072B2", "-", "o"),
    "kyverno": ("Kyverno", "#009E73", "--", "s"),
    "gatekeeper": ("Gatekeeper", "#D55E00", "-.", "^"),
}


def load():
    groups = defaultdict(list)  # (engine, n, run) -> samples
    with open("latency_scale.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups[(r["engine"], int(r["n_policies"]), int(r["run"]))].append(
                float(r["sample_ms"]))
    return groups


def main():
    groups = load()
    run_medians = {k: statistics.median(v) for k, v in groups.items()}

    def pooled(eng, n):
        """Median over all samples at a level (pooled across runs)."""
        allsamp = [s for (e, nn, r), v in groups.items()
                   if e == eng and nn == n for s in v]
        return statistics.median(allsamp)

    fig, ax = plt.subplots(figsize=(3.5, 2.4), dpi=300)

    base_med = pooled("baseline", 0)
    ax.axhline(base_med, color="0.45", lw=1, ls=":")
    ax.annotate(f"baseline (no engines): {base_med:.1f}",
                xy=(0.2, base_med), fontsize=6.5, color="0.35", va="bottom")

    for eng, (label, color, ls, marker) in SERIES.items():
        xs, ys, spread = [], [], []
        for n in (0, 5, 10, 15):
            meds = [m for (e, nn, r), m in run_medians.items()
                    if e == eng and nn == n]
            y = pooled(eng, n)
            xs.append(n)
            ys.append(y)
            spread.append((y - min(meds), max(meds) - y))
        yerr = list(zip(*spread))
        ax.errorbar(xs, ys, yerr=yerr, color=color, ls=ls, marker=marker,
                    ms=3.5, lw=1.2, capsize=2, elinewidth=0.8)
        ax.annotate(label, xy=(xs[-1], ys[-1]), xytext=(4, 0),
                    textcoords="offset points", fontsize=6.5, color=color,
                    va="center")

    ax.set_xlabel("Loaded policies", fontsize=7.5)
    ax.set_ylabel("Median admission latency (ms)", fontsize=7.5)
    ax.set_xticks([0, 5, 10, 15])
    ax.set_xlim(-0.7, 24)
    ax.tick_params(labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=0.3)
    fig.savefig("fig_scale.pdf")
    print("fig_scale.pdf written")


def drift_figure():
    """fig_drift.pdf — per-trial drift-detection times; VAP shown as N/A."""
    trials = {}
    with open("drift_detection.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            trials.setdefault(r["engine"], []).append(float(r["detect_s"]))

    fig, ax = plt.subplots(figsize=(3.5, 2.0), dpi=300)
    engines = ["kyverno", "gatekeeper"]
    colors = {"kyverno": "#009E73", "gatekeeper": "#D55E00"}
    width = 0.22
    for gi, eng in enumerate(engines):
        for ti, v in enumerate(trials[eng]):
            ax.bar(gi + (ti - 1) * width, v, width * 0.9,
                   color=colors[eng], edgecolor="white", linewidth=0.5)
        ax.annotate(f"median {sorted(trials[eng])[1]:.1f}s",
                    xy=(gi, max(trials[eng])), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=6.5)
    ax.axhline(60, color="0.45", lw=0.8, ls=":")
    ax.annotate("Gatekeeper default audit interval (60 s)", xy=(0.02, 60),
                xytext=(0, 2), textcoords="offset points", fontsize=6,
                color="0.35")
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(["Kyverno\n(3 trials)", "Gatekeeper\n(3 trials)",
                        "VAP"], fontsize=7)
    ax.text(2, 3, "no mechanism\n(N/A)", ha="center", fontsize=6.5,
            color="0.35", style="italic")
    ax.set_ylabel("Detection time (s)", fontsize=7.5)
    ax.set_ylim(0, 70)
    ax.tick_params(labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=0.3)
    fig.savefig("fig_drift.pdf")
    print("fig_drift.pdf written")


def cloud_figure():
    """fig_cloud_delta.pdf — per-engine median delta vs same-environment
    baseline: local kind (run 2, pooled) vs managed EKS (cloud leg)."""
    def med(path):
        with open(path, encoding="utf-8") as f:
            return statistics.median(float(r["sample_ms"])
                                     for r in csv.DictReader(f))

    local = {}  # engine -> delta from latency_scale.csv at n=15 (pooled)
    groups = load()
    def pooled(eng, n):
        allsamp = [s for (e, nn, r), v in groups.items()
                   if e == eng and nn == n for s in v]
        return statistics.median(allsamp)
    base_local = pooled("baseline", 0)
    for eng in ("vap", "kyverno", "gatekeeper"):
        local[eng] = pooled(eng, 15) - base_local

    base_cloud = med("cloud-eks_latency_baseline.csv")
    cloud = {eng: med(f"cloud-eks_latency_{eng}.csv") - base_cloud
             for eng in ("vap", "kyverno", "gatekeeper")}

    fig, ax = plt.subplots(figsize=(3.5, 2.0), dpi=300)
    engines = ["vap", "kyverno", "gatekeeper"]
    labels = ["VAP", "Kyverno", "Gatekeeper"]
    w = 0.32
    for i, eng in enumerate(engines):
        color = SERIES[eng][1]
        ax.bar(i - w / 2, local[eng], w * 0.92, color=color,
               edgecolor="white", linewidth=0.5)
        ax.bar(i + w / 2, cloud[eng], w * 0.92, color=color, alpha=0.45,
               edgecolor="white", linewidth=0.5, hatch="//")
        for x, v in ((i - w / 2, local[eng]), (i + w / 2, cloud[eng])):
            ax.annotate(f"+{v:.1f}", xy=(x, v), xytext=(0, 2),
                        textcoords="offset points", ha="center", fontsize=6.5)
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("Median $\\Delta$ vs baseline (ms)", fontsize=7.5)
    solid = plt.Rectangle((0, 0), 1, 1, color="0.35")
    hatched = plt.Rectangle((0, 0), 1, 1, color="0.35", alpha=0.45, hatch="//")
    ax.legend([solid, hatched],
              ["local kind (15 policies)", "managed EKS (15 policies)"],
              fontsize=6, frameon=False, loc="upper left")
    ax.set_ylim(0, 16.5)
    ax.tick_params(labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=0.3)
    fig.savefig("fig_cloud_delta.pdf")
    print("fig_cloud_delta.pdf written")


if __name__ == "__main__":
    main()
    drift_figure()
    cloud_figure()
