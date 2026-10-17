#!/usr/bin/env python3
"""Can an unsupervised, relative COMPLEXITY outlier reproduce a tool-defined god class?

    python god_complexity.py <study.json> [--level class|method]

The self-contained detector question: given only a per-unit complexity definition and a
relative-outlier rule, how well does the flagged set agree with a textbook god-class
definition -- which complexity definition is best, and which outlier rule?

Two questions are kept separate (the fix for the threshold confound):

  WHICH SIGNAL ranks gods best?   -> AUC of the RAW signal value, threshold-free, no outlier
                                     algorithm involved (Mann-Whitney, tie-corrected).
  WHICH ALGORITHM makes the best  -> MCC of the flagged set at the algorithm's threshold
  flag set from a signal?            (Matthews correlation, the balanced rare-class choice).

One honesty guard: oracles are split into INDEPENDENT targets and SELF-REFERENTIAL ones.
`wmc47` is Sum(cc) and at method level `cc14`/`cognitive15`/`loc50`/`params5`/`nesting5` ARE a
signal thresholded -- so a matching signal scoring AUC~1 on them is a tautology, not a
result. Those are reported separately and never drive the headline.

The real god-class targets are the composite tool definitions pmd_GodClass and decor_blob;
CK cohesion/coupling and the PMD size panel are supporting, tool-derived (Java-only) targets.
The explore/confirm split is kept: the best signal is chosen on EXPLORE and its AUC is then
read on the held-out CONFIRM half, so the headline number is out of sample. Standard library
only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

MIN_FUNCS = 50          # the study's substance floor, mirrored from study.MIN_FUNCS/MIN_UNIV
MIN_UNIV = 15
PURE = ["cc", "cognitive", "nloc", "tokens", "params", "nesting", "nom"]
GOD = ["pmd_GodClass", "decor_blob"]            # the actual god-class definitions
# oracles that are a complexity signal restated as a threshold -> tautological for that signal
SELFREF = {"class": ["wmc47"],
           "method": ["cc14", "cognitive15", "loc50", "params5", "nesting5"]}
DEGENERATE_AUC = 0.52
ALGOS = ["mad_z", "double_mad", "iqr", "adj_boxplot", "evt_pot", "pct_top1", "zscore"]
# god DEFINITIONS grouped by what they actually measure, so several size restatements do not
# drown the two cohesion / two coupling definitions in any "overall" average.
GROUPS = {
    "size/complexity": ["wmc47", "cc14", "cognitive15", "nesting5", "loc50", "params5",
                        "pmd_TooManyMethods", "pmd_NcssCount", "pmd_ExcessiveClassLength",
                        "pmd_TooManyFields", "pmd_ExcessivePublicCount", "pmd_ExcessiveImports"],
    "cohesion": ["ck_LCOM", "ck_TCClow"],
    "coupling": ["pmd_CouplingBetweenObjects", "ck_CBOhigh"],
    "composite": ["pmd_GodClass", "decor_blob"],
}
_NEMENYI_Q = {2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102,
              10: 3.164, 11: 3.219, 12: 3.268, 13: 3.313, 14: 3.354, 15: 3.391, 16: 3.426}


# ---- threshold-free / rank statistics (self-contained, pure stdlib) --------------------
def _dig(d, path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def mcc(c):
    if not isinstance(c, dict) or not c.get("n_univ"):
        return None
    tp, pp, ap, n = c.get("n_overlap", 0), c.get("n_out", 0), c.get("n_god_univ", 0), c["n_univ"]
    fp, fn = pp - tp, ap - tp
    tn = n - pp - ap + tp
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    return 0.0 if den <= 0 else (tp * tn - fp * fn) / math.sqrt(den)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ranks(scores: dict):
    items = sorted(scores.items(), key=lambda kv: -kv[1])
    out, i, n = {}, 0, len(items)
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[items[k][0]] = (i + j) / 2 + 1
        i = j + 1
    return out


def half_of(repo_url: str) -> str:
    """Deterministic explore/confirm assignment from the URL alone (no seed to tune)."""
    import hashlib
    return "confirm" if hashlib.sha256(repo_url.encode()).digest()[0] & 1 else "explore"


def chi2_sf(x, df):
    if x <= 0 or df <= 0:
        return 1.0
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 0.5 * math.erfc(z / math.sqrt(2))


def friedman(rank_rows, methods):
    n, k = len(rank_rows), len(methods)
    if n < 2 or k < 2:
        return None
    mr = {m: sum(r[m] for r in rank_rows) / n for m in methods}
    chi = (12 * n) / (k * (k + 1)) * sum((mr[m] - (k + 1) / 2) ** 2 for m in methods)
    cd = _NEMENYI_Q.get(k, 3.4) * math.sqrt(k * (k + 1) / (6 * n))
    return {"chi2": round(chi, 2), "p": round(chi2_sf(chi, k - 1), 5), "n": n,
            "mean_rank": mr, "cd": round(cd, 3)}


def _cell(r, lvl, s, a, o):
    return _dig(r, ["matrix", lvl, "cells", s, a, o])


def pooled(rows, lvl, s, a, defs):
    """Micro-averaged confusion for (signal s, algorithm a) over definitions `defs`, summed
    across repositories: returns (precision, recall, mcc, n_repodef_blocks, n_gods, n_univ)."""
    tp = pp = ap = n = k = 0
    for r in rows:
        for o in defs:
            c = _cell(r, lvl, s, a, o)
            if isinstance(c, dict) and c.get("n_univ") and c.get("n_god_univ"):
                tp += c.get("n_overlap", 0); pp += c.get("n_out", 0)
                ap += c.get("n_god_univ", 0); n += c["n_univ"]; k += 1
    if not k:
        return (None, None, None, 0, 0, 0)
    fp, fn = pp - tp, ap - tp
    tn = n - pp - ap + tp
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    m = 0.0 if den <= 0 else (tp * tn - fp * fn) / math.sqrt(den)
    return (tp / pp if pp else None, tp / ap if ap else None, m, k, ap, n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("study")
    ap.add_argument("--level", choices=["class", "method"], default="class")
    args = ap.parse_args(argv)
    lvl = args.level
    rows = [r for r in json.load(open(args.study))
            if not r.get("error") and not r.get("excluded_min_substance")
            and (r.get("n_funcs") or 0) >= MIN_FUNCS
            and (_dig(r, ["matrix", "class", "n_univ"]) or 0) >= MIN_UNIV
            and "matrix" in r]
    if not rows:
        print("No usable rows with a 'matrix' block.", file=sys.stderr)
        return 1
    explore = [r for r in rows if half_of(r["repo"]) == "explore"]
    confirm = [r for r in rows if half_of(r["repo"]) == "confirm"]
    allsignals = rows[0]["matrix"][f"signals_{lvl}"]
    signals = [s for s in PURE if s in allsignals]
    # every signal's AUC block lists the same oracles; use cc (always present) to enumerate
    oracles = sorted({o for r in rows
                      for o in (_dig(r, ["matrix", lvl, "auc", "cc"]) or {})})
    selfref = [o for o in SELFREF[lvl] if o in oracles]
    god = [o for o in GOD if o in oracles]
    grp_of = {o: g for g, lst in GROUPS.items() for o in lst}

    def auc(r, s, o):
        b = _dig(r, ["matrix", lvl, "auc", s, o])
        return b.get("auc") if isinstance(b, dict) else None

    def has_gods(r, o):
        b = _dig(r, ["matrix", lvl, "auc", "cc", o])
        return bool(b and b.get("n_god"))

    def repo_auc(r, s, defs):
        return mean([auc(r, s, o) for o in defs if has_gods(r, o)])

    # drop a signal that never beats chance on EXPLORE (e.g. nesting), decided out of sample
    def best_auc(s, rs):
        vals = [v for v in (mean([auc(r, s, o) for r in rs]) for o in oracles) if v is not None]
        return max(vals) if vals else None
    excluded = [s for s in signals if (best_auc(s, explore) or 0) <= DEGENERATE_AUC]
    active = [s for s in signals if s not in excluded]

    print(f"=== COMPLEXITY outliers as god-class detectors | {len(rows)} usable repos "
          f"({len(explore)} explore / {len(confirm)} confirm) | level={lvl} ===")
    print(f"    signal pool: {active}"
          + (f"   excluded on explore: {excluded}" if excluded else ""))
    print(f"    independent god targets: {god or '(none in this run)'}"
          f"   self-referential (reported apart): {selfref or '(none)'}")

    # ---- 1. THE god-class headline: the composite tool definitions, chosen out of sample ----
    if god:
        print(f"\n1. GOD-CLASS DETECTION vs {god}  (the composite tool definitions)")
        ex = {s: mean([repo_auc(r, s, god) for r in explore]) for s in active}
        co = {s: mean([repo_auc(r, s, god) for r in confirm]) for s in active}
        al = {s: mean([repo_auc(r, s, god) for r in rows]) for s in active}
        order = sorted((s for s in active if ex[s] is not None), key=lambda s: -ex[s])
        print("   signal          AUC(all) AUC(explore) AUC(confirm)   [signal chosen on explore]")
        for s in order:
            print(f"   {s:14}  {al[s]:.3f}      {ex[s]:.3f}        "
                  f"{(co[s] if co[s] is not None else float('nan')):.3f}")
        best = order[0]
        print(f"\n   -> best complexity signal on explore: '{best}'  "
              f"(held-out confirm AUC={co[best]:.3f})")
        print("   operating point of that signal, by algorithm (micro-avg over repos x the two "
              "defs, all repos):")
        print("     algorithm     precision  recall   MCC")
        for a in sorted(ALGOS, key=lambda a: -(pooled(rows, lvl, best, a, god)[2] or -9)):
            p, rc, m, k, ng, n = pooled(rows, lvl, best, a, god)
            if m is None:
                continue
            pr = f"{p:.2f}" if p is not None else " n/a"
            rcs = f"{rc:.2f}" if rc is not None else " n/a"
            print(f"     {a:12}    {pr}     {rcs}   {m:.3f}")

    # ---- 2. which complexity definition separates best, per independent group ----
    print("\n2. BEST COMPLEXITY DEFINITION by AUC, per INDEPENDENT definition group")
    for g in GROUPS:
        gor = [o for o in oracles if grp_of.get(o) == g and o not in selfref]
        if not gor:
            continue
        per_repo = {s: [repo_auc(r, s, gor) for r in rows] for s in active}
        sig_mean = {s: mean(v) for s, v in per_repo.items()}
        rrows = [ranks({s: per_repo[s][k] for s in active}) for k in range(len(rows))
                 if all(per_repo[s][k] is not None for s in active)]
        fr = friedman(rrows, active)
        order = sorted((s for s in active if sig_mean[s] is not None), key=lambda s: -sig_mean[s])
        taut = " [NOTE: wmc47=Sum(cc), size-correlated]" if g == "size/complexity" and \
               "wmc47" in GROUPS[g] else ""
        print(f"\n   [{g}] defs={gor}{taut}")
        for s in order[:6]:
            mr = f" rank {fr['mean_rank'][s]:.1f}" if fr else ""
            print(f"     {s:12} AUC={sig_mean[s]:.3f}{mr}")
        if fr:
            print(f"     Friedman p~{fr['p']} (N={fr['n']}); Nemenyi CD={fr['cd']}")

    # ---- 3. which outlier rule is best ----
    print("\n3. OUTLIER RULE RANKING by mean MCC  (all complexity signals; all independent defs)")
    indep = [o for o in oracles if o not in selfref]
    amean = {a: [] for a in ALGOS}
    arows = []
    for r in rows:
        aa = {}
        for a in ALGOS:
            vs = [mcc(_cell(r, lvl, s, a, o)) for s in active for o in indep if has_gods(r, o)]
            v = mean(vs)
            if v is not None:
                aa[a] = v; amean[a].append(v)
        if len(aa) == len(ALGOS):
            arows.append(ranks(aa))
    fra = friedman(arows, ALGOS)
    for a in sorted(ALGOS, key=lambda a: -(mean(amean[a]) or -9)):
        mr = f" rank {fra['mean_rank'][a]:.2f}" if fra else ""
        print(f"   {a:12} MCC={(mean(amean[a]) or 0):.3f}{mr}")
    if fra:
        print(f"   Friedman p~{fra['p']} (N={fra['n']}); Nemenyi CD={fra['cd']}")

    # ---- 4. per definition: best signal and best signal+rule, independent then self-ref ----
    def per_def(defs, header):
        if not defs:
            return
        print(f"\n   {header}")
        for o in defs:
            sm = {s: mean([auc(r, s, o) for r in rows]) for s in signals}
            sm = {s: v for s, v in sm.items() if v is not None}
            if not sm:
                continue
            bs = max(sm, key=sm.get)
            cm = {(s, a): mean([mcc(_cell(r, lvl, s, a, o)) for r in rows])
                  for s in signals for a in ALGOS}
            cm = {k: v for k, v in cm.items() if v is not None}
            bc = max(cm, key=cm.get) if cm else (None, None)
            print(f"     {o:28} AUC: {bs}={sm[bs]:.3f}   MCC: {bc[0]}/{bc[1]}={cm.get(bc, 0):.3f}")
    print("\n4. BEST SIGNAL + RULE PER DEFINITION   (exploratory; best-of-many is upward-biased)")
    per_def([o for o in oracles if o not in selfref], "INDEPENDENT definitions:")
    per_def(selfref, "SELF-REFERENTIAL definitions (AUC~1 for the matching signal is tautology):")

    print("\n(Oracles are tool-derived, not human truth; PMD/CK/DECOR are Java-only, so "
          "non-size targets are a Java result. Sections 2-4 are exploratory; section 1's best "
          "signal is chosen on explore and its AUC read on the held-out confirm half.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
