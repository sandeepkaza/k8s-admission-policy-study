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


if __name__ == "__main__":
    main()
