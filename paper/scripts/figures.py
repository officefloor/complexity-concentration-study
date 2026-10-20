#!/usr/bin/env python3
"""Draw the paper's figures from the analyses and the paper's reductions.

    paper/.venv/bin/python paper/scripts/figures.py [--main results/<date>] [--mlcq results/mlcq]
                                                     [--data paper/data] [--out paper/figures]

Needs matplotlib (paper/requirements.txt). Reads only JSON: the harness's analysis.json files and
paper/data/{main,human,agreement}.json. Writes PDF figures into paper/figures/.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
ROOT = os.path.dirname(PAPER)

# one categorical palette, fixed order, never cycled (dataviz reference palette, light surface)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d9d9d6"
plt.rcParams.update({"font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 8,
                     "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.spines.top": False,
                     "axes.spines.right": False, "grid.color": GRID, "grid.linewidth": 0.6,
                     "legend.frameon": False, "pdf.fonttype": 42})

DEF_NAMES = {"pmd_GodClass": "PMD GodClass", "pmd_method_NPath200": "PMD NPath ≥ 200", "decor_blob": "DECOR Blob (approx.)",
             "brain_method": "Brain Method (internal)", "human_blob": "MLCQ Blob (human)",
             "human_method_long_method": "MLCQ Long Method (human)"}


def load(p):
    with open(p) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
def fig_decisions(a, b, h, out):
    rows = []  # (label, decision)
    P = a["primary"]["pmd_GodClass"]
    rows.append((f"PMD GodClass ({P['chosen_signal']}), main run", P["decision"]))
    for name in ("pmd_method_NPath200", "decor_blob", "brain_method"):
        r = a["secondary"][name]
        rows.append((f"{DEF_NAMES[name]} ({r['chosen_signal']}), main run", r["decision"]))
    Q = b["primary"]["pmd_GodClass"]
    rows.append((f"PMD GodClass ({Q['chosen_signal']}), MLCQ repositories", Q["decision"]))
    if h:
        for level, name in (("class", "human_blob"), ("method", "human_method_long_method")):
            r = h["readouts"][f"{level}:all"]
            if r.get("decision"):
                rows.append((f"{DEF_NAMES[name]} ({r['chosen_signal']}), MLCQ reviewed units", r["decision"]))
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 0.45 * len(rows) + 1.5), sharey=True)
    titles = {"macro_mcc": "Macro MCC", "micro_mcc": "Micro (pooled) MCC", "macro_fpr": "Macro FPR"}
    y = np.arange(len(rows))[::-1]
    for ax, arm in zip(axes, ("macro_mcc", "micro_mcc", "macro_fpr")):
        ax.axvline(0, color=INK2, lw=0.8)
        for yi, (label, d) in zip(y, rows):
            bb = d["paired"].get(arm)
            decided = arm in d["arms"]
            col = BLUE if decided else INK2
            if bb:
                ax.plot([bb["lo"], bb["hi"]], [yi, yi], color=col, lw=1.6, solid_capstyle="butt")
                ax.plot([bb["value"]], [yi], "o", color=col, ms=4.5, mec="white", mew=0.6)
            m = d["fpr_margin"] if arm == "macro_fpr" else d["margin"]
            mx = m if arm == "macro_fpr" else -m
            ax.plot([mx, mx], [yi - 0.32, yi + 0.32], color=ORANGE, lw=1.0)
        ax.set_title(titles[arm], loc="left")
        ax.grid(axis="x")
        ax.set_yticks(y)
        if arm == "macro_fpr":
            ax.set_xlabel("relative − absolute\n(lower is better)")
        else:
            ax.set_xlabel("relative − absolute\n(higher is better)")
    axes[0].set_yticklabels([r[0] for r in rows])
    fig.text(0.01, 0.008, "Point: paired difference, modified z ≥ 3.5 minus the absolute cutoff tuned on explore; bar: 95% repository bootstrap.\n"
             "Orange tick: the margin (non-inferiority on the MCC arms, +0.05 on the FPR arm). Grey: reported, not decided on.",
             fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(out, "decisions.pdf"))
    plt.close(fig)


def fig_pooled_distribution(main, out):
    rows = {r["repo"]: r for r in main["rows"]}
    z_g, z_n, r_g, r_n = [], [], [], []
    for repo, rec in main["class"].items():
        if rows[repo]["half"] != "confirm" or "dist" not in rec:
            continue
        d = rec["dist"]
        gods = set(d["god"])
        for k, (z, raw) in enumerate(zip(d["z"], d["raw"])):
            (z_g if k in gods else z_n).append(z)
            (r_g if k in gods else r_n).append(raw)
    cut_raw = main["cuts"]["class:pmd_GodClass"]["cognitive_max"][0]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))

    def survival(ax, g, n, cut, xlabel, logx):
        for vals, col, label in ((n, BLUE, f"other classes (n={len(n):,})"), (g, ORANGE, f"PMD god classes (n={len(g):,})")):
            v = np.sort(np.asarray(vals, dtype=float))
            s = 1.0 - np.arange(len(v)) / len(v)
            if logx:
                v = np.maximum(v, 0.5)
            ax.step(v, s, where="post", color=col, lw=1.6, label=label)
        ax.axvline(cut, color=INK2, lw=0.8, ls="--")
        ax.set_yscale("log")
        if logx:
            ax.set_xscale("log")
        ax.set_ylim(1e-5, 1.05)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("share of units at or above x")
        ax.grid(True, which="major")
        ax.legend(loc="lower left")
        # the share above the cut, labelled directly
        for vals, col, dy in ((n, BLUE, 0.55), (g, ORANGE, 0.3)):
            share = sum(1 for v in vals if v >= cut) / len(vals)
            ax.annotate(f"{100 * share:.1f}% ≥ cut", xy=(cut, share), xytext=(8, 0), textcoords="offset points",
                        color=col, fontsize=7.5, va="center")

    survival(axes[0], z_g, z_n, 3.5, "modified z of cognitive_max (per repository)", False)
    axes[0].set_xlim(-2, max(z_g + z_n) * 1.02)
    axes[0].set_title("Relative axis: the rule's constant is 3.5", loc="left")
    survival(axes[1], r_g, r_n, cut_raw, "cognitive_max (raw)", True)
    axes[1].set_title(f"Absolute axis: the cutoff tuned on explore is {cut_raw:g}", loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "pooled_distribution.pdf"))
    plt.close(fig)


def fig_auc_by_signal(main, a, out):
    rows = {r["repo"]: r for r in main["rows"]}
    chosen = a["primary"]["pmd_GodClass"]["chosen_signal"]
    fam = {"size": [], "peak": [], "density": []}
    for s in main["class"][next(iter(main["class"]))]["oracles"]["pmd_GodClass"]["auc"]:
        if s == "nom" or s.endswith("_sum"):
            fam["size"].append(s)
        elif s.endswith("_max"):
            fam["peak"].append(s)
        else:
            fam["density"].append(s)
    per = defaultdict(list)
    for repo, rec in main["class"].items():
        if rows[repo]["half"] != "confirm":
            continue
        o = rec["oracles"].get("pmd_GodClass")
        if not o or o["n_pos"] < 3:
            continue
        for s, v in o["auc"].items():
            if v is not None:
                per[s].append(v)
    order, labels, colors = [], [], []
    for fname in ("size", "peak", "density"):
        sigs = sorted(fam[fname], key=lambda s: -np.median(per[s]))
        for s in sigs:
            order.append(s)
            labels.append(s)
            colors.append(ORANGE if s == chosen else (BLUE if fname != "size" else INK2))
    fig, ax = plt.subplots(figsize=(7.2, 7.6))
    y = np.arange(len(order))[::-1]
    data = [per[s] for s in order]
    bp = ax.boxplot(data, positions=y, orientation="horizontal", widths=0.6, showfliers=False, patch_artist=True,
                    medianprops={"color": INK, "lw": 1.2}, whiskerprops={"color": INK2, "lw": 0.8},
                    capprops={"color": INK2, "lw": 0.8}, boxprops={"lw": 0.6})
    for patch, col in zip(bp["boxes"], colors):
        patch.set_facecolor(col)
        patch.set_alpha(0.35)
        patch.set_edgecolor(col)
    rng = np.random.default_rng(12345)
    for yi, s, col in zip(y, order, colors):
        v = np.asarray(per[s])
        ax.plot(v, yi + rng.uniform(-0.18, 0.18, len(v)), "o", ms=2.2, color=col, alpha=0.55, mec="none")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, family="monospace")
    ax.set_xlabel(f"per-repository AUC against PMD GodClass, confirm half (n={len(per[chosen])} repositories with ≥ 3 god classes)")
    ax.grid(axis="x")
    ax.axvline(0.5, color=INK2, lw=0.8, ls=":")
    # family bands
    starts = {}
    i = 0
    for fname in ("size", "peak", "density"):
        n = len(fam[fname])
        ax.axhline(y[i] + 0.5, color=GRID, lw=0.8)
        ax.text(0.303, y[i] + 0.5, fname + " family", fontsize=7.5, color=INK2, va="center", ha="left",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})
        i += n
    ax.set_xlim(0.3, 1.0)
    ax.set_ylim(-0.8, len(order) + 0.2)
    ax.set_title("Orange: the signal chosen on explore (cognitive_max). Grey: size signals, never eligible for the primary.", loc="left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "auc_by_signal.pdf"))
    plt.close(fig)


def fig_flag_rates(main, out):
    langs = ["java", "python", "javascript", "typescript", "go", "c", "c++", "c#", "php", "rust"]
    names = {"c#": "C#", "c++": "C++", "c": "C", "php": "PHP", "go": "Go", "javascript": "JavaScript", "typescript": "TypeScript"}
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
    for ax, key, title in zip(axes, ("class:cognitive_max:mad_z", "method:cognitive:mad_z"),
                              ("Class level, cognitive_max", "Method level, cognitive")):
        data = []
        for lang in langs:
            data.append([100 * r["flag_rates"][key] for r in main["rows"] if r["lang"] == lang and key in r["flag_rates"]])
        x = np.arange(len(langs))
        bp = ax.boxplot(data, positions=x, widths=0.6, showfliers=False, patch_artist=True,
                        medianprops={"color": INK, "lw": 1.2}, whiskerprops={"color": INK2, "lw": 0.8}, capprops={"color": INK2, "lw": 0.8},
                        boxprops={"lw": 0.6, "facecolor": BLUE, "alpha": 0.35, "edgecolor": BLUE})
        rng = np.random.default_rng(12345)
        for xi, v in zip(x, data):
            ax.plot(xi + rng.uniform(-0.18, 0.18, len(v)), v, "o", ms=2, color=BLUE, alpha=0.5, mec="none")
        ax.set_xticks(x)
        ax.set_xticklabels([names.get(l, l.capitalize()) for l in langs], rotation=40, ha="right")
        ax.set_title(title, loc="left")
        ax.grid(axis="y")
    axes[0].set_ylabel("units flagged by modified z ≥ 3.5 (%)")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "flag_rates.pdf"))
    plt.close(fig)


def fig_agreement(g, out):
    names = {"pmd_GodClass": "PMD GodClass", "decor_blob": "DECOR Blob (approx.)", "wmc47": "WMC ≥ 47",
             "pmd_method_NPath200": "PMD NPath ≥ 200", "cc14": "CC ≥ 14", "cognitive15": "cognitive ≥ 15",
             "loc50": "NLOC ≥ 50", "brain_method": "Brain Method (internal)"}
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.2))
    for ax, level, title in zip(axes, ("class", "method"), ("Blob: reviewed classes", "Long Method: reviewed methods")):
        L = g["levels"][level]
        res = L["all"]
        keys = list(res["predictors"])
        y = np.arange(len(keys))[::-1]
        for yi, k in zip(y, keys):
            m = res["predictors"][k]
            col = ORANGE if k == "rel" else (AQUA if k == "abs" else BLUE)
            c = m["mcc_ci"]
            if c:
                ax.plot([c["lo"], c["hi"]], [yi, yi], color=col, lw=1.6)
            ax.plot([m["mcc"]], [yi], "o", color=col, ms=4.5, mec="white", mew=0.6)
        labels = []
        for k in keys:
            if k == "rel":
                labels.append(f"relative: z ≥ 3.5 on {L['signal']}")
            elif k == "abs":
                labels.append(f"absolute: {L['signal']} ≥ {L['absolute_cut']:g}")
            else:
                labels.append(names.get(k, k))
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_xlabel("MCC against the reviewers' verdict")
        ax.set_title(f"{title}\n{res['n_repos']} repos, {res['n_reviewed_units']:,} units, {res['n_positive']} positive", loc="left", fontsize=8)
        ax.grid(axis="x")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "human_agreement.pdf"))
    plt.close(fig)


def fig_paired_mcc(main, a, out):
    rows = {r["repo"]: r for r in main["rows"]}
    sig = a["primary"]["pmd_GodClass"]["chosen_signal"]
    cut = str(a["primary"]["pmd_GodClass"]["confirm"]["absolute_cutoff"]["cut"])
    xs, ys, ns, gf = [], [], [], []
    for repo, rec in main["class"].items():
        if rows[repo]["half"] != "confirm":
            continue
        o = rec["oracles"].get("pmd_GodClass")
        if not o:
            continue
        r = o["cells"][sig]["mad_z"]
        ab = o["abs"][sig][cut]
        def mcc(c):
            den = (c["tp"] + c["fp"]) * (c["tp"] + c["fn"]) * (c["tn"] + c["fp"]) * (c["tn"] + c["fn"])
            return 0.0 if den <= 0 else (c["tp"] * c["tn"] - c["fp"] * c["fn"]) / den ** 0.5
        xs.append(mcc(ab))
        ys.append(mcc(r))
        ns.append(o["n_pos"])
        gf.append(o["n_pos"] == 0)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3))
    ax = axes[0]
    xs, ys, ns, gf = map(np.asarray, (xs, ys, ns, gf))
    ax.plot([-0.05, 1], [-0.05, 1], color=INK2, lw=0.8, ls=":")
    sizes = 8 + 3 * np.sqrt(ns)
    ax.scatter(xs[~gf], ys[~gf], s=sizes[~gf], color=BLUE, alpha=0.6, edgecolors="white", linewidths=0.5,
               label="repositories with ≥ 1 PMD god class")
    ax.scatter(xs[gf], ys[gf], s=18, color=ORANGE, marker="s", alpha=0.8, edgecolors="white", linewidths=0.5,
               label=f"god-free repositories (MCC 0 by convention, n={gf.sum()})")
    ax.set_xlabel(f"per-repository MCC, absolute {sig} ≥ {float(cut):g}")
    ax.set_ylabel("per-repository MCC, modified z ≥ 3.5")
    ax.grid(True)
    ax.legend(loc="lower right", fontsize=7)
    ax.set_title("Paired per-repository MCC, confirm half", loc="left")
    # right: flags in god-free repositories and FPR per repo
    ax = axes[1]
    fr, fa = [], []
    for repo, rec in main["class"].items():
        if rows[repo]["half"] != "confirm":
            continue
        o = rec["oracles"].get("pmd_GodClass")
        if not o:
            continue
        r = o["cells"][sig]["mad_z"]
        ab = o["abs"][sig][cut]
        fr.append(100 * r["fp"] / (r["fp"] + r["tn"]) if r["fp"] + r["tn"] else 0)
        fa.append(100 * ab["fp"] / (ab["fp"] + ab["tn"]) if ab["fp"] + ab["tn"] else 0)
    fr, fa = np.asarray(fr), np.asarray(fa)
    ax.plot([0, max(fr.max(), fa.max()) * 1.05], [0, max(fr.max(), fa.max()) * 1.05], color=INK2, lw=0.8, ls=":")
    ax.scatter(fa, fr, s=14, color=BLUE, alpha=0.6, edgecolors="white", linewidths=0.5)
    ax.set_xlabel(f"false-positive rate (%), absolute {sig} ≥ {float(cut):g}")
    ax.set_ylabel("false-positive rate (%), modified z ≥ 3.5")
    ax.grid(True)
    ax.set_title("Paired per-repository false-positive rate", loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "paired_mcc.pdf"))
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--main", default=os.environ.get("CCS_MAIN_RESULTS", os.path.join(ROOT, "results", "2026-10-19")))
    ap.add_argument("--mlcq", default=os.environ.get("CCS_MLCQ_RESULTS", os.path.join(ROOT, "results", "mlcq")))
    ap.add_argument("--data", default=os.path.join(PAPER, "data"))
    ap.add_argument("--out", default=os.path.join(PAPER, "figures"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    a = load(os.path.join(args.main, "analysis.json"))
    b = load(os.path.join(args.mlcq, "analysis.json"))
    main_data = load(os.path.join(args.data, "main.json"))
    hp = os.path.join(args.data, "human.json")
    h = load(hp) if os.path.exists(hp) else None
    gp = os.path.join(args.data, "agreement.json")
    g = load(gp) if os.path.exists(gp) else None
    fig_decisions(a, b, h, args.out)
    fig_pooled_distribution(main_data, args.out)
    fig_auc_by_signal(main_data, a, args.out)
    fig_flag_rates(main_data, args.out)
    fig_paired_mcc(main_data, a, args.out)
    if g:
        fig_agreement(g, args.out)
    print(f"wrote figures to {args.out}: {sorted(os.listdir(args.out))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
