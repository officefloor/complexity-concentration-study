"""Complexity-concentration metrics for the god-class/method comparison matrix. Pure
standard library.

Every metric here reads only the per-node complexity aggregates `extract.analyze_tree`
produces (the COMPLEXITY_FIELDS per function and their per-file sums). None of them
reconstructs the call graph, so they stay type-blind and snapshot-only.

Two reusable ideas:

  concentration : how unevenly a quantity is spread (Shannon entropy, Gini, Theil). Low
                  entropy / high Gini == piled up in a few units.

  evt           : is the quantity heavy-tailed? Hill tail index and a peaks-over-threshold
                  GPD shape xi (xi>0 == Pareto-type tail), plus calibrated "1-in-N"
                  severity of the top units. A heavy tail is what justifies an extreme-value
                  cutoff over the symmetric modified z-score.

`matrix_outliers()` turns each complexity definition into flagged sets under every outlier
algorithm; the enrichment of each against the study's god-class oracles (WMC>=47, the
method-level thresholds, PMD, CK) stays in study.analyse, which owns the oracle panels.
"""
from __future__ import annotations

import math

from . import extract


# ---------------------------------------------------------------------------
# distribution helpers (pure python, None when the sample is too small)
# ---------------------------------------------------------------------------
def median(xs: list[float]):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def entropy_norm(xs: list[float]):
    """Shannon entropy of the share distribution, normalised to [0,1]. 1 == perfectly even
    spread, 0 == one unit holds everything. The direct reading of "concentration"."""
    xs = [x for x in xs if x > 0]
    s = sum(xs)
    if s <= 0 or len(xs) < 2:
        return None
    ps = [x / s for x in xs]
    h = -sum(p * math.log(p) for p in ps)
    return h / math.log(len(ps))


def gini(xs: list[float]):
    """Gini coefficient. 0 == even, ->1 == one unit holds everything."""
    xs = sorted(x for x in xs if x >= 0)
    n = len(xs)
    if n < 2 or sum(xs) == 0:
        return None
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * sum(xs)) - (n + 1) / n


def theil(xs: list[float]):
    """Theil-T index (an entropy-based inequality measure). 0 == even, grows with pile-up."""
    xs = [x for x in xs if x > 0]
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    return sum((x / mean) * math.log(x / mean) for x in xs) / n


def hill_alpha(xs: list[float], frac: float = 0.10):
    """Hill tail-index estimate on the top `frac` of values. alpha < ~2 is a very heavy
    (infinite-variance) tail; large alpha is a light tail. None if too few values."""
    xs = sorted((x for x in xs if x > 0), reverse=True)
    k = max(5, int(len(xs) * frac))
    if len(xs) <= k + 1:
        return None
    logs = [math.log(x) for x in xs[:k + 1]]
    s = sum(logs[i] - logs[k] for i in range(k)) / k
    return round(1.0 / s, 3) if s > 0 else None


def gpd_shape_mom(xs: list[float], q: float = 0.90):
    """Peaks-over-threshold GPD shape xi by method of moments (xi>0 == Pareto-type heavy
    tail). Returns None when there are too few exceedances to estimate it."""
    xs = sorted(x for x in xs if x > 0)
    n = len(xs)
    if n < 20:
        return None
    u = xs[int(q * n)]
    ex = [x - u for x in xs if x > u]
    if len(ex) < 10:
        return None
    m = sum(ex) / len(ex)
    var = sum((e - m) ** 2 for e in ex) / len(ex)
    if var == 0:
        return None
    return round(0.5 * (1 - m * m / var), 3)


def concentration(values: list[float]) -> dict:
    xs = [v for v in values if v > 0]
    return {"entropy_norm": entropy_norm(xs), "gini": gini(xs), "theil": theil(xs),
            "n_units": len(xs)}


def evt(values: list[float]) -> dict:
    xs = sorted((v for v in values if v > 0), reverse=True)
    n = len(xs)
    med = median(xs)
    return {"n": n, "hill_alpha": hill_alpha(xs), "gpd_shape_xi": gpd_shape_mom(xs),
            "max_over_median": round(xs[0] / med, 1) if (med and n) else None,
            "top_severity_1_in_N": [round(n / (i + 1)) for i in range(min(3, n))]}


# ---------------------------------------------------------------------------
# outlier sets and the combined signal
# ---------------------------------------------------------------------------
def z_outliers(value_map: dict) -> set:
    """Keys whose positive value is a modified-z outlier (>= OUTLIER_Z). The generic
    relative-outlier form, shared by the complexity spikes."""
    xs = [v for v in value_map.values() if v > 0]
    if not xs:
        return set()
    z = extract.modified_z(xs)
    return {k for k, v in value_map.items() if v > 0 and z(v) >= extract.OUTLIER_Z}


def jaccard(a: set, b: set):
    u = a | b
    return round(len(a & b) / len(u), 4) if u else None


def auc_ap(values: dict, gods: set, universe):
    """Threshold-free quality of a continuous signal as a god detector over `universe`,
    independent of any outlier algorithm: this separates "which signal ranks gods best"
    from "which threshold an algorithm picked".
      AUC = P(a random god scores above a random non-god), Mann-Whitney, tie-corrected.
      AP  = average precision (area under the precision-recall curve).
    Returns (auc, ap, n_god, n_universe); auc/ap are None when a class is empty."""
    universe = list(universe)
    pos = [values.get(k, 0) for k in universe if k in gods]
    neg = [values.get(k, 0) for k in universe if k not in gods]
    ng, nn = len(pos), len(neg)
    if ng == 0 or nn == 0:
        return None, None, ng, ng + nn
    # AUC via rank-sum with average ranks for ties
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda t: t[0])
    n = len(allv)
    rk = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and allv[j + 1][0] == allv[i][0]:
            j += 1
        for t in range(i, j + 1):
            rk[t] = (i + j) / 2 + 1
        i = j + 1
    sum_pos = sum(rk[t] for t in range(n) if allv[t][1] == 1)
    auc = (sum_pos - ng * (ng + 1) / 2) / (ng * nn)
    # average precision, tie-aware: step through DISTINCT score thresholds (descending), so
    # a block of tied units is taken as a whole -- AP = sum over thresholds of
    # (recall gained) x (precision at that threshold). Walking unit by unit would order a
    # tie by set iteration, i.e. by the process hash seed, and AP would not reproduce.
    by_v: dict = {}
    for v, is_god in allv:
        t = by_v.setdefault(v, [0, 0])
        t[0] += 1
        t[1] += is_god
    tp = seen = 0
    ap = 0.0
    for v in sorted(by_v, reverse=True):
        cnt, pos_here = by_v[v]
        seen += cnt
        tp += pos_here
        if pos_here:
            ap += (pos_here / ng) * (tp / seen)
    return auc, ap, ng, ng + nn


# ---------------------------------------------------------------------------
# outlier/spike ALGORITHMS  (each: {key: value} -> set of flagged keys)
# All are relative / threshold-free so they transfer across repos and languages,
# following the paper's design principle. They run on the positive values only (the
# universe of generators / complex units), matching the enrichment universe.
# Literature: Iglewicz-Hoaglin (modified z); Rosenmai / Brys-Hubert (double MAD, adjusted
# outlyingness); Tukey (boxplot fence); Hubert-Vandervieren 2008 (skew-adjusted boxplot via
# the medcouple); Bhattacharya 2023 and classical EVT (peaks-over-threshold GPD).
# ---------------------------------------------------------------------------
def _pos(vmap: dict) -> dict:
    return {k: v for k, v in vmap.items() if v > 0}


def _quantile(xs: list[float], q: float) -> float:
    n = len(xs)
    if n == 1:
        return xs[0]
    pos = q * (n - 1)
    lo = int(pos)
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[lo + 1] * frac if lo + 1 < n else xs[lo]


def _medcouple(sorted_xs: list[float]) -> float:
    """Robust skewness in [-1,1] (Brys, Hubert & Struyf 2004). Naive O(n^2) kernel with the
    tie-at-median rule, capped to <=1500 order statistics so it stays cheap on large repos
    (an estimate on the empirical quantiles, adequate for a whisker adjustment)."""
    xs = sorted_xs
    n = len(xs)
    if n < 3:
        return 0.0
    if n > 1500:
        step = n / 1500.0
        xs = [xs[min(n - 1, int(i * step))] for i in range(1500)]
        n = len(xs)
    med = median(xs)
    U = [x for x in xs if x >= med]      # ascending
    L = [x for x in xs if x <= med]
    nu, nl = len(U), len(L)
    hs = []
    for i, a in enumerate(U):            # a >= med
        for j, b in enumerate(L):        # b <= med
            if a == med and b == med:    # tie block: signum of position difference
                k = (nu - 1 - i) - j
                hs.append(1.0 if k > 0 else (-1.0 if k < 0 else 0.0))
            else:
                hs.append(((a - med) - (med - b)) / (a - b))
    return median(sorted(hs)) or 0.0


def mad_z(vmap: dict, cut: float = extract.OUTLIER_Z) -> set:
    """Iglewicz-Hoaglin modified z-score (MAD-based). The paper's baseline detector."""
    vmap = _pos(vmap)
    if not vmap:
        return set()
    z = extract.modified_z(list(vmap.values()))
    return {k for k, v in vmap.items() if z(v) >= cut}


def double_mad(vmap: dict, cut: float = extract.OUTLIER_Z) -> set:
    """Upper (one-sided) MAD: deviation scale taken from the right half only, for the
    right-skewed flow/complexity distributions (double-MAD / adjusted-outlyingness family)."""
    vmap = _pos(vmap)
    xs = sorted(vmap.values())
    n = len(xs)
    if n < 3:
        return set()
    med = median(xs)
    upper = sorted(x - med for x in xs if x >= med)
    mad_u = median(upper) if upper else 0
    if not mad_u or mad_u <= 0:
        return mad_z(vmap, cut)
    return {k for k, v in vmap.items() if v > med and 0.6745 * (v - med) / mad_u >= cut}


def iqr_fence(vmap: dict, k: float = 1.5) -> set:
    """Tukey boxplot upper fence Q3 + k*IQR."""
    vmap = _pos(vmap)
    xs = sorted(vmap.values())
    if len(xs) < 4:
        return set()
    q1, q3 = _quantile(xs, 0.25), _quantile(xs, 0.75)
    fence = q3 + k * (q3 - q1)
    return {kk for kk, v in vmap.items() if v > fence}


def adjusted_boxplot(vmap: dict, k: float = 1.5) -> set:
    """Hubert-Vandervieren (2008) skew-adjusted boxplot: upper whisker
    Q3 + k*exp(c*MC)*IQR with the medcouple MC (c=3 for the upper fence, MC>=0)."""
    vmap = _pos(vmap)
    xs = sorted(vmap.values())
    if len(xs) < 5:
        return set()
    q1, q3 = _quantile(xs, 0.25), _quantile(xs, 0.75)
    mc = _medcouple(xs)
    coef = math.exp(3 * mc) if mc >= 0 else math.exp(4 * mc)
    fence = q3 + k * coef * (q3 - q1)
    return {kk for kk, v in vmap.items() if v > fence}


def evt_pot(vmap: dict, p: float | None = None, q: float = 0.90) -> set:
    """Peaks-over-threshold GPD: flag values whose fitted upper-tail survival is below p
    (default 1/n -- 'not expected even once in a sample this size')."""
    vmap = _pos(vmap)
    xs = sorted(vmap.values())
    n = len(xs)
    if n < 20:
        return set()
    p = p if p is not None else 1.0 / n
    u = xs[int(q * n)]
    ex = [x - u for x in xs if x > u]
    if len(ex) < 10:
        return set()
    m = sum(ex) / len(ex)
    var = sum((e - m) ** 2 for e in ex) / len(ex)
    if var <= 0:
        return set()
    xi = 0.5 * (1 - m * m / var)
    sigma = 0.5 * m * (1 + m * m / var)
    pu = len(ex) / n
    if sigma <= 0:
        return set()

    def surv(x):
        y = x - u
        if y <= 0:
            return pu
        if abs(xi) < 1e-6:
            return pu * math.exp(-y / sigma)
        base = 1 + xi * y / sigma
        return pu * base ** (-1.0 / xi) if base > 0 else 0.0
    return {kk for kk, v in vmap.items() if surv(v) < p}


def percentile_top(vmap: dict, q: float = 0.99) -> set:
    """Flag the top (1-q) fraction by value -- a trivial relative baseline / floor."""
    vmap = _pos(vmap)
    xs = sorted(vmap.values())
    n = len(xs)
    if n < 2:
        return set()
    thr = xs[min(n - 1, int(q * n))]
    return {kk for kk, v in vmap.items() if v >= thr and v > xs[0]}


def zscore_classic(vmap: dict, k: float = 3.0) -> set:
    """Classic mean/SD z-score (parametric CONTROL; expected to fail on heavy tails because
    one extreme inflates the SD and masks the next -- included to show robustness matters)."""
    vmap = _pos(vmap)
    xs = list(vmap.values())
    n = len(xs)
    if n < 3:
        return set()
    mean = sum(xs) / n
    sd = (sum((x - mean) ** 2 for x in xs) / (n - 1)) ** 0.5
    if sd <= 0:
        return set()
    return {kk for kk, v in vmap.items() if (v - mean) / sd >= k}


# name -> detector. The order is the reporting order (baseline first, control last).
ALGORITHMS = {
    "mad_z": mad_z,                 # Iglewicz-Hoaglin modified z (paper baseline)
    "double_mad": double_mad,       # skew-aware one-sided MAD
    "iqr": iqr_fence,               # Tukey boxplot fence
    "adj_boxplot": adjusted_boxplot,  # Hubert-Vandervieren skew-adjusted fence
    "evt_pot": evt_pot,             # peaks-over-threshold GPD tail
    "pct_top1": percentile_top,     # top 1% (relative floor)
    "zscore": zscore_classic,       # classic mean/SD (parametric control)
}


# The SIGNALS we compare: each complexity definition on its own. Each is a per-function
# field (COMPLEXITY_FIELDS from extract), summed per file at class level; "nom" (methods per
# class) is a class-level-only signal.
from .extract import COMPLEXITY_FIELDS

METHOD_SIGNALS = COMPLEXITY_FIELDS
CLASS_SIGNALS = METHOD_SIGNALS + ("nom",)


def signal_value(signal: str, r: dict) -> float:
    """Per-function value of a signal from an extract record (a plain complexity field)."""
    return r.get(signal, 0)


def matrix_outliers(funcs: dict, wmc: dict) -> dict:
    """Outlier sets for every (level, signal, algorithm) cell, plus the per-level universe.
    Signals: each complexity definition; plus nom at class level. Class-level value of a
    signal is the per-file sum of its per-method values. Enrichment against the oracles is
    left to study.analyse (which owns the PMD / CK panels)."""
    def run(vmap):
        return {name: algo(_pos(vmap)) for name, algo in ALGORITHMS.items()}

    method_vals = {sig: {fid: signal_value(sig, r) for fid, r in funcs.items()}
                   for sig in METHOD_SIGNALS}

    # class level: per-file sum of each signal's per-method value (nom = method count)
    byfile: dict = {}
    for fid, r in funcs.items():
        d = byfile.setdefault(fid[0], {})
        for sig in METHOD_SIGNALS:
            d[sig] = d.get(sig, 0) + signal_value(sig, r)
        d["nom"] = d.get("nom", 0) + 1
    class_vals = {sig: {f: d.get(sig, 0) for f, d in byfile.items()} for sig in CLASS_SIGNALS}

    method = {sig: run(method_vals[sig]) for sig in METHOD_SIGNALS}
    cls = {sig: run(class_vals[sig]) for sig in CLASS_SIGNALS}
    m_univ = {fid for fid, r in funcs.items() if r.get("cc", 0) > 0}
    c_univ = {f for f in wmc if wmc[f] > 0}
    # "_vals" holds the raw per-unit signal values for threshold-free AUC/AP (not serialised)
    return {"method": {**method, "universe": m_univ, "_vals": method_vals},
            "class": {**cls, "universe": c_univ, "_vals": class_vals}}
