"""Statistics the analysis of a run must use, kept in the harness (tested, pure standard
library) so the paper's report cannot re-introduce the shortcuts an earlier draft had:

  * pooled_confusion   -- micro-averaged confusion over MANY (repo, definition) blocks, which
                          INCLUDES blocks where the definition found no god. A relative rule
                          is fitted to each repository's own distribution, so it can flag
                          units in a repository where the oracle finds nothing (the top
                          percentile always does; the modified z and the fences usually do),
                          and those repositories are exactly where its false positives live;
                          dropping them biases every pooled number in the relative rule's
                          favour.
  * mcc                -- Matthews correlation from the four counts (Chicco & Jurman 2020).
  * friedman           -- Friedman chi-square AND the Iman-Davenport F correction Demsar (2006)
                          recommends, with exact p-values (regularised gamma / beta).
  * nemenyi_cd         -- the Nemenyi critical difference with the studentized-range quantile
                          COMPUTED for any k (numerical integration), not looked up from a
                          short table with a fallback.
  * chi2_sf, f_sf      -- exact survival functions used above.
  * auc, pooled_auc    -- Mann-Whitney AUC, and the AUC POOLED over repositories of either the
                          raw value or the per-repository STANDARDISED value (modified z). The
                          within-repository AUC is invariant to any monotone per-repository
                          transform, so it cannot tell a relative rule from an absolute one; the
                          pooled standardised-vs-raw AUC is the threshold-free form of that
                          comparison.
  * bootstrap_mean     -- percentile bootstrap CI of a mean over repositories (macro
                          averaging: one repository, one vote, unlike the size-weighted micro
                          average pooled_confusion gives).
  * bootstrap_paired   -- percentile bootstrap CI of ANY statistic of a list of per-repository
                          items, resampling repositories: the PAIRED comparison of two rules
                          read on the same repositories (the difference of their macro MCCs,
                          of their micro MCCs, of their false-positive rates), which is far
                          more powerful than two separate intervals and is what the
                          pre-registered decision rule reads.
  * fpr                -- the false-positive rate from the four counts. Unlike the MCC it is
                          DEFINED in a repository where the definition marks nothing (the MCC
                          is 0 there whether a rule flagged nothing or everything), so the
                          macro average of the FPR sees the false positives in god-free
                          repositories that the macro MCC cannot.
  * assign_halves      -- the explore/confirm split, STRATIFIED: within each (language, tier)
                          stratum repositories are ordered by a hash of their URL and
                          alternated, so each half holds half of every stratum.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# confusion counts
# ---------------------------------------------------------------------------
def mcc(tp: int, fp: int, fn: int, tn: int) -> float:
    """Matthews correlation coefficient; 0.0 when any marginal is empty (undefined)."""
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    return 0.0 if den <= 0 else (tp * tn - fp * fn) / math.sqrt(den)


def fpr(fp: int, tn: int) -> float | None:
    """False-positive rate fp / (fp + tn); None when there are no negatives. Defined in a
    god-free repository (where the MCC is 0 by convention whatever was flagged)."""
    return fp / (fp + tn) if (fp + tn) > 0 else None


def pooled_confusion(cells) -> dict:
    """Sum the lean per-cell counts {n_univ, n_out, n_overlap, n_god_univ} over an iterable of
    cells and derive precision, recall, MCC and the false-positive rate. EVERY cell with a
    non-empty universe counts, including those with n_god_univ == 0 (they contribute false
    positives and true negatives only). `n_blocks_no_god` says how many such cells there were,
    and `fp_in_no_god` how many flags fell in them, so the report can show them."""
    tp = pp = ap = n = k = k0 = fp0 = 0
    for c in cells:
        if not isinstance(c, dict) or not c.get("n_univ"):
            continue
        k += 1
        tp += c.get("n_overlap", 0)
        pp += c.get("n_out", 0)
        ap += c.get("n_god_univ", 0)
        n += c["n_univ"]
        if not c.get("n_god_univ"):
            k0 += 1
            fp0 += c.get("n_out", 0)
    fp, fn = pp - tp, ap - tp
    tn = n - pp - ap + tp
    return {"n_blocks": k, "n_blocks_no_god": k0, "fp_in_no_god": fp0,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "n_god": ap, "n_univ": n,
            "precision": tp / pp if pp else None, "recall": tp / ap if ap else None,
            "fpr": fp / (fp + tn) if (fp + tn) else None,
            "mcc": mcc(tp, fp, fn, tn) if k else None}


# ---------------------------------------------------------------------------
# special functions (exact, pure python)
# ---------------------------------------------------------------------------
def _gammainc_upper_reg(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (series for x < a+1, continued fraction
    otherwise; Numerical Recipes 6.2)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        term = total = 1.0 / a
        ap = a
        for _ in range(10000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    # Lentz continued fraction
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def _betainc_reg(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) (continued fraction, Numerical Recipes 6.4)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc_reg(b, a, 1 - x)
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x)) / a
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = tiny if abs(d) < tiny else d
    d = 1 / d
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return front * h


def chi2_sf(x: float, df: int) -> float:
    """P(Chi2_df > x), exact via the regularised upper incomplete gamma."""
    if x <= 0 or df <= 0:
        return 1.0
    return _gammainc_upper_reg(df / 2.0, x / 2.0)


def f_sf(x: float, d1: float, d2: float) -> float:
    """P(F_{d1,d2} > x), exact via the regularised incomplete beta."""
    if x <= 0:
        return 1.0
    return _betainc_reg(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * x))


def _norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


def studentized_range_cdf(q: float, k: int) -> float:
    """P(range of k iid standard normals <= q) = k * Integral phi(z) [Phi(z) - Phi(z-q)]^(k-1) dz
    (the studentized range with infinite degrees of freedom, as the Nemenyi test uses).
    Composite Simpson on [-12, 12]."""
    if q <= 0:
        return 0.0
    lo, hi, n = -12.0, 12.0, 4000
    h = (hi - lo) / n

    def f(z):
        return _norm_pdf(z) * (_norm_cdf(z) - _norm_cdf(z - q)) ** (k - 1)
    s = f(lo) + f(hi)
    for i in range(1, n):
        s += (4 if i % 2 else 2) * f(lo + i * h)
    return min(1.0, k * s * h / 3)


def studentized_range_q(k: int, alpha: float = 0.05) -> float:
    """The upper alpha quantile q_alpha of the studentized range of k means (infinite df), by
    bisection on studentized_range_cdf. Demsar's Table 5 is q_alpha / sqrt(2)."""
    if k < 2:
        raise ValueError("k >= 2")
    lo, hi = 0.0, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if studentized_range_cdf(mid, k) < 1 - alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def nemenyi_cd(k: int, n: int, alpha: float = 0.05) -> float:
    """Nemenyi critical difference for k methods over n blocks:
    CD = (q_alpha / sqrt(2)) * sqrt(k (k+1) / (6 n)), with q_alpha computed for THIS k."""
    if k < 2 or n < 1:
        raise ValueError("k >= 2 and n >= 1")
    return (studentized_range_q(k, alpha) / math.sqrt(2)) * math.sqrt(k * (k + 1) / (6.0 * n))


# ---------------------------------------------------------------------------
# Friedman + Iman-Davenport (Demsar 2006, Sec. 3.2.2)
# ---------------------------------------------------------------------------
def friedman_from_mean_ranks(mean_ranks: dict, n: int) -> dict:
    """Friedman chi2_F and the Iman-Davenport F_F from per-method mean ranks over n blocks."""
    k = len(mean_ranks)
    if k < 2 or n < 2:
        raise ValueError("need k >= 2 methods and n >= 2 blocks")
    chi = (12.0 * n) / (k * (k + 1)) * (sum(r * r for r in mean_ranks.values())
                                        - k * (k + 1) ** 2 / 4.0)
    chi = max(chi, 0.0)
    den = n * (k - 1) - chi
    ff = ((n - 1) * chi / den) if den > 0 else float("inf")
    return {"n": n, "k": k, "mean_rank": dict(mean_ranks),
            "chi2": chi, "p_chi2": chi2_sf(chi, k - 1),
            "F": ff, "p_F": f_sf(ff, k - 1, (k - 1) * (n - 1)) if math.isfinite(ff) else 0.0,
            "cd_05": nemenyi_cd(k, n, 0.05)}


def ranks(scores: dict) -> dict:
    """Average ranks (1 = best = highest score), ties share the mean rank."""
    items = sorted(scores.items(), key=lambda kv: -kv[1])
    out, i, n = {}, 0, len(items)
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        for t in range(i, j + 1):
            out[items[t][0]] = (i + j) / 2 + 1
        i = j + 1
    return out


def friedman(score_rows: list[dict]) -> dict | None:
    """Friedman/Iman-Davenport over blocks: `score_rows` is one {method: score} per block
    (repository), every row holding the same methods. Higher score = better. None if fewer than
    two complete blocks."""
    complete = [r for r in score_rows if r and all(v is not None for v in r.values())]
    # A block in which every method ties (every rule scores MCC 0 in a god-free repository)
    # carries no ranking information: keeping it pulls every mean rank toward the centre
    # while inflating N, which makes the critical difference too small. Such blocks are
    # dropped and counted.
    rows = [r for r in complete if len(set(r.values())) > 1]
    if len(rows) < 2:
        return None
    methods = sorted(rows[0])
    if any(sorted(r) != methods for r in rows):
        raise ValueError("every block must score the same methods")
    rk = [ranks(r) for r in rows]
    mr = {m: sum(r[m] for r in rk) / len(rk) for m in methods}
    out = friedman_from_mean_ranks(mr, len(rk))
    out["n_tied_dropped"] = len(complete) - len(rows)
    return out


# ---------------------------------------------------------------------------
# threshold-free: AUC within and pooled over repositories
# ---------------------------------------------------------------------------
def auc(pos: list[float], neg: list[float]) -> float | None:
    """P(a random positive scores above a random negative), Mann-Whitney with average ranks
    for ties. None when either class is empty."""
    ng, nn = len(pos), len(neg)
    if ng == 0 or nn == 0:
        return None
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
    return (sum_pos - ng * (ng + 1) / 2) / (ng * nn)


def modified_z_values(values: list[float]) -> list[float]:
    """Each value standardised by its own population's median and MAD (Iglewicz-Hoaglin; the
    mean absolute deviation when the MAD is zero), the per-repository relative axis."""
    from .extract import modified_z_scale
    _, z = modified_z_scale(values)
    return [z(v) for v in values]


def pooled_auc(blocks, standardise: bool = False) -> dict:
    """AUC over the units of MANY repositories pooled into one ranking. `blocks` is an iterable
    of (values, god_positions): one repository's per-unit values (the sidecar's
    `values[signal]`, in unit order) and the positions of its positives (`god_idx[oracle]`).
    With `standardise`, each repository's values are first replaced by their modified z, so the
    pooled ranking is the RELATIVE one; without it the pooled ranking is the raw ABSOLUTE one.
    Blocks with no positives are kept: their units are negatives in the pool, exactly where a
    relative rule's false positives live. Returns the AUC and the counts behind it."""
    pos: list = []
    neg: list = []
    k = k0 = 0
    for values, gods in blocks:
        if not values:
            continue
        k += 1
        vals = modified_z_values(list(values)) if standardise else list(values)
        gset = set(gods or ())
        if not gset:
            k0 += 1
        for i, v in enumerate(vals):
            (pos if i in gset else neg).append(v)
    return {"auc": auc(pos, neg), "n_pos": len(pos), "n_neg": len(neg),
            "n_blocks": k, "n_blocks_no_god": k0, "standardised": standardise}


# ---------------------------------------------------------------------------
# macro averaging over repositories
# ---------------------------------------------------------------------------
def bootstrap_mean(values, b: int = 2000, seed: int = 12345, min_n: int = 5):
    """{"mean", "lo", "hi", "n"}: the mean of per-repository values and its 95% percentile
    bootstrap interval, resampling REPOSITORIES (the unit of independence). None values are
    dropped; None is returned when fewer than `min_n` remain."""
    import random
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < min_n:
        return None
    rnd = random.Random(seed)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(b))
    return {"mean": sum(vals) / n, "lo": means[int(0.025 * b)], "hi": means[int(0.975 * b)],
            "n": n}


def bootstrap_paired(items, stat_fn, b: int = 2000, seed: int = 12345, min_n: int = 5):
    """{"value", "lo", "hi", "n"}: `stat_fn(items)` on the items given (one per repository,
    each item holding BOTH competitors' results on that repository) and its 95% percentile
    bootstrap interval, resampling the items. Because each item carries both sides, any
    statistic of the list is paired: the difference of macro means, the difference of pooled
    (micro) values, a difference of rates. `stat_fn` may return None for a degenerate
    resample; such resamples are dropped and `n_dropped` says how many. None when fewer than
    `min_n` items."""
    import random
    items = list(items)
    n = len(items)
    if n < min_n:
        return None
    value = stat_fn(items)
    if value is None:
        return None
    rnd = random.Random(seed)
    vals = []
    for _ in range(b):
        v = stat_fn([items[rnd.randrange(n)] for _ in range(n)])
        if v is not None:
            vals.append(v)
    if len(vals) < max(2, b // 2):
        return None
    vals.sort()
    k = len(vals)
    return {"value": value, "lo": vals[int(0.025 * k)], "hi": vals[min(k - 1, int(0.975 * k))],
            "n": n, "n_dropped": b - k}


# ---------------------------------------------------------------------------
# the explore / confirm split
# ---------------------------------------------------------------------------
def assign_halves(items, stratum_of=lambda item: None, key_of=lambda item: item) -> dict:
    """{key: "explore" | "confirm"} for every item, stratified and deterministic. Within each
    stratum (e.g. (language, tier)) the items are ordered by the sha256 of their key and
    alternated explore, confirm, explore, ..., so every stratum is split as evenly as its size
    allows and no seed exists to tune. An unstratified hash-parity split can leave a
    30-repository language 10/20; this cannot."""
    import hashlib
    by: dict = {}
    for it in items:
        by.setdefault(stratum_of(it), []).append(key_of(it))
    out: dict = {}
    for stratum in sorted(by, key=lambda s: str(s)):
        keys = sorted(set(by[stratum]), key=lambda k: hashlib.sha256(str(k).encode()).hexdigest())
        for i, k in enumerate(keys):
            out[k] = "explore" if i % 2 == 0 else "confirm"
    return out


# ---------------------------------------------------------------------------
# calibration and the tuned absolute competitor
# ---------------------------------------------------------------------------
def _avg_ranks(a: list[float]) -> list[float]:
    n = len(a)
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


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Tie-aware rank correlation of two aligned per-unit vectors (the continuous calibration
    of a lexical estimator against PMD's value). None if degenerate."""
    n = len(xs)
    if n < 3 or len(ys) != n:
        return None
    rx, ry = _avg_ranks(list(xs)), _avg_ranks(list(ys))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def best_cutoff(pairs) -> dict | None:
    """Over pooled (value, is_positive) pairs from many repositories, the single cutoff k
    (flag value >= k) that maximises the pooled MCC: the best a one-size-fits-all constant can
    do, tuned with full hindsight on the data given (so: tune on EXPLORE, read on CONFIRM).
    Returns {"mcc", "cut", "precision", "recall"} or None."""
    pairs = list(pairs)
    P = sum(1 for _, g in pairs if g)
    N = len(pairs) - P
    if P == 0 or N == 0:
        return None
    by: dict = {}
    for v, g in pairs:
        t = by.setdefault(v, [0, 0])
        t[0] += 1
        t[1] += 1 if g else 0
    tp = fp = 0
    best = None
    for v in sorted(by, reverse=True):              # lower the cutoff, flagging more
        cnt, gc = by[v]
        tp += gc
        fp += cnt - gc
        m = mcc(tp, fp, P - tp, N - fp)
        if best is None or m > best["mcc"]:
            best = {"mcc": m, "cut": v, "precision": tp / (tp + fp), "recall": tp / P}
    return best
