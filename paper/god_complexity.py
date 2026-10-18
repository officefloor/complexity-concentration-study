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
import os
import random
import sys

MIN_FUNCS = 50          # the study's substance floor, mirrored from study.MIN_FUNCS/MIN_UNIV
MIN_UNIV = 15
# The signal pool is read from the study (matrix.signals_{level}): at method level the raw
# complexity fields; at class level each field aggregated {base}_sum/_mean/_max, plus nom.
# The independent god-class/method targets, per level: composite tool definitions at class
# level; the composite Brain Method at method level.
GOD = {"class": ["pmd_GodClass", "decor_blob"], "method": ["brain_method"]}
# oracles that are a single complexity signal restated as a threshold -> tautological for that
# signal, so reported apart and never in the headline.
SELFREF = {"class": ["wmc47"],
           "method": ["cc14", "cognitive15", "loc50", "params5", "nesting5"]}
# a composite oracle's INGREDIENT signals: their AUC on it is partly built in, so they are
# flagged (*) and the clean cross-signal tests are the other measures. brain_method is the
# conjunction of the long-method, high-CC and deep-nesting thresholds.
INGREDIENTS = {"brain_method": {"nloc", "cc", "nesting"}}
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
    "composite": ["pmd_GodClass", "decor_blob", "brain_method"],
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


def spearman(xs, ys):
    """Rank correlation of two equal-length per-unit vectors (tie-aware). None if degenerate."""
    n = len(xs)
    if n < 3 or len(ys) != n:
        return None

    def rank(a):
        order = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and a[order[j + 1]] == a[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def _mcc_counts(tp, fp, fn, tn):
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    return 0.0 if den <= 0 else (tp * tn - fp * fn) / math.sqrt(den)


def best_global_cutoff(pairs):
    """Over pooled (value, is_god) pairs from many repos, the SINGLE absolute cutoff k (flag
    value >= k) that maximises the pooled MCC -- i.e. the best a one-size-fits-all constant can
    do, tuned with full hindsight. Returns (mcc, k, precision, recall) or None."""
    P = sum(g for _, g in pairs)
    N = len(pairs) - P
    if P == 0 or N == 0:
        return None
    by = {}
    for v, g in pairs:
        t = by.setdefault(v, [0, 0])
        t[0] += 1
        t[1] += g
    tp = fp = 0
    best = None
    for v in sorted(by, reverse=True):             # lower the cutoff, flagging more
        cnt, gc = by[v]
        tp += gc
        fp += cnt - gc
        m = _mcc_counts(tp, fp, P - tp, N - fp)
        if best is None or m > best[0]:
            best = (m, v, tp / (tp + fp) if tp + fp else 0.0, tp / P)
    return best


def bootstrap_ci(values, b=2000, seed=12345):
    """95% percentile bootstrap CI of the MEAN of per-repo values (resampling repos)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 5:
        return None
    rnd = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(b))
    return means[int(0.025 * b)], means[int(0.975 * b)]


def load_units(path, lvl, repos):
    """Per-unit payloads for `repos` at one level, from the append-only `*.units.jsonl` sidecar.
    {} if the sidecar is absent (older runs) -- the sidecar-based sections then quietly skip."""
    out = {}
    try:
        fh = open(path)
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("repo") in repos and lvl in d:
                out[d["repo"]] = d[lvl]
    return out


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
    ap.add_argument("--units", default=None,
                    help="per-unit sidecar (default: <study>.units.jsonl); enables the "
                         "conservation and relative-vs-absolute sections")
    args = ap.parse_args(argv)
    lvl = args.level
    units_path = args.units or (os.path.splitext(args.study)[0] + ".units.jsonl")
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
    signals = list(rows[0]["matrix"][f"signals_{lvl}"])   # the full pool, read from the study
    ref_sig = signals[0]                                  # a signal present in every row's blocks
    # every signal's AUC block lists the same oracles; use a reference signal to enumerate them
    oracles = sorted({o for r in rows
                      for o in (_dig(r, ["matrix", lvl, "auc", ref_sig]) or {})})
    selfref = [o for o in SELFREF[lvl] if o in oracles]
    god = [o for o in GOD[lvl] if o in oracles]
    ingred = {o: INGREDIENTS.get(o, set()) for o in god}
    grp_of = {o: g for g, lst in GROUPS.items() for o in lst}

    def auc(r, s, o):
        b = _dig(r, ["matrix", lvl, "auc", s, o])
        return b.get("auc") if isinstance(b, dict) else None

    def has_gods(r, o):
        b = _dig(r, ["matrix", lvl, "auc", ref_sig, o])
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

    # ---- 1. THE god headline: the composite definition(s), chosen out of sample ----
    if god:
        ing_all = set().union(*ingred.values()) if ingred else set()
        kind = "composite tool definitions" if lvl == "class" else "composite Brain Method"
        print(f"\n1. GOD DETECTION vs {god}  (the {kind})")
        ex = {s: mean([repo_auc(r, s, god) for r in explore]) for s in active}
        co = {s: mean([repo_auc(r, s, god) for r in confirm]) for s in active}
        al = {s: mean([repo_auc(r, s, god) for r in rows]) for s in active}
        order = sorted((s for s in active if ex[s] is not None), key=lambda s: -ex[s])
        print("   signal              AUC(all) AUC(explore) AUC(confirm)   (* = ingredient of "
              "the oracle)")
        for s in order:
            star = "*" if s in ing_all else " "
            print(f"   {s:18}{star} {al[s]:.3f}      {ex[s]:.3f}        "
                  f"{(co[s] if co[s] is not None else float('nan')):.3f}")
        # the out-of-sample headline is the best CLEAN (non-ingredient) signal
        clean = [s for s in order if s not in ing_all]
        best = clean[0] if clean else order[0]
        if ing_all:
            print(f"   (* {sorted(ing_all)} are ingredients of {god}, so their AUC is partly "
                  f"built in; the headline uses the best non-ingredient signal.)")
        ci = bootstrap_ci([repo_auc(r, best, god) for r in confirm])
        ci_s = f", 95% CI [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else ""
        print(f"\n   -> best complexity signal on explore: '{best}'  "
              f"(held-out confirm AUC={co[best]:.3f}{ci_s})")
        print(f"   operating point of that signal, by algorithm (micro-avg over repos x "
              f"{len(god)} def(s), all repos):")
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

    # ---- 5 & 6. sidecar-based: conservation and the no-calibration head-to-head ----
    units = load_units(units_path, lvl, {r["repo"] for r in rows})
    base = best if god else (active[0] if active else None)
    if units and base:
        # 5. do different complexity measures rank the same units? (conservation of complexity)
        print(f"\n5. CONSERVATION: do the complexity measures agree? (mean within-repo Spearman "
              f"to '{base}', over {len(units)} repos)")
        corr = {}
        for s in active:
            rs = []
            for pl in units.values():
                vb, vs = pl["values"].get(base), pl["values"].get(s)
                if vb and vs:
                    rho = spearman(vs, vb)
                    if rho is not None:
                        rs.append(rho)
            corr[s] = mean(rs)
        pairwise = mean([corr[s] for s in active if s != base and corr[s] is not None])
        for s in sorted((s for s in active if s != base and corr[s] is not None),
                        key=lambda s: -corr[s]):
            print(f"     rho(->{base}) {corr[s]:+.2f}   {s}")
        if pairwise is not None:
            print(f"   -> mean correlation of the measures to '{base}' = {pairwise:+.2f}  "
                  f"(high => they measure one concentrated thing; the measure matters less than "
                  f"the outlier)")

        # 6. the hypothesis test: a self-calibrating per-repo rule vs the best tuned constant
        if god:
            print("\n6. NO CALIBRATION NEEDED: per-repo RELATIVE outlier vs the best GLOBAL "
                  "ABSOLUTE cutoff")
            print(f"   signal '{base}', pooled MCC over all repos where the oracle has gods:")
            for o in god:
                _, _, rel, _, _, _ = pooled(rows, lvl, base, "mad_z", [o])
                pairs = []
                for pl in units.values():
                    vals, gi = pl["values"].get(base), pl["god_idx"].get(o)
                    if not vals or not gi:
                        continue
                    gods = set(gi)
                    pairs.extend((v, 1 if i in gods else 0) for i, v in enumerate(vals))
                bg = best_global_cutoff(pairs)
                if rel is None or bg is None:
                    continue
                verdict = ("relative matches/beats the tuned constant"
                           if rel >= bg[0] - 1e-9 else "the tuned constant is ahead here")
                print(f"     [{o:14}] relative mad_z (NO tuning) MCC={rel:.3f}   vs   best single "
                      f"cutoff {base}>={bg[1]:g} (tuned on all data) MCC={bg[0]:.3f}  -> {verdict}")
            print("   (the relative rule picks its own threshold per repo from the local "
                  "distribution; the absolute cutoff is one constant for every repo, chosen with "
                  "full hindsight -- yet cannot adapt to per-repo scale.)")

    note = ("PMD/CK/DECOR are Java-only, so non-size targets are a Java result"
            if lvl == "class" else
            "brain_method is language-neutral (built from the lexical signals), so this is a "
            "cross-language result; nloc/cc/nesting are its ingredients")
    print(f"\n(Oracles are tool-derived, not human truth; {note}. Sections 2-4 are exploratory; "
          "section 1's best signal is chosen on explore and its AUC read on the held-out "
          "confirm half.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
