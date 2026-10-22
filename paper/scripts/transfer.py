#!/usr/bin/env python3
"""EXPLORATORY: does the absolute constant transfer between populations, and does the relative
one? The one comparison the plan never made.

    paper/scripts/transfer.py [--main results/<date>] [--mlcq results/mlcq]
                              [--data paper/data] [--out paper/data/transfer.json]

Every comparison in the plan tunes the absolute cutoff on a population's explore half and reads
it on the SAME population's confirm half, the best case for a raw-scale constant. The paper's
motivating argument is that such constants have to be re-fitted when the population moves. This
script reads each population's confirm half three ways, on the primary signal (cognitive_max)
against PMD GodClass, all on the Java class units the plan fits on:

  rel        the relative rule at its literature default, modified z >= 3.5 (no tuning at all);
  rel_tuned  the relative rule at the z-cut tuned on THIS population's explore half (the plan's
             secondary), the one row that isolates the axis from the constant: tuned against tuned;
  abs_own    the absolute cutoff tuned on THIS population's explore half (the plan's competitor);
  abs_other  the absolute cutoff tuned on the OTHER population's explore half, carried across
             unchanged: what a constant shipped from one corpus does on another.

For each, the plan's three arms (micro MCC, macro MCC over repositories with a positive, macro
FPR over every repository carrying the definition), and two paired repository bootstraps per
population: rel minus abs_other (the relative rule against a constant that did not get to see
this population) and abs_other minus abs_own (the cost of carrying the constant across). Beside
them, rel_tuned minus abs_own (the standardised axis against the raw axis, both tuned the
same way on the same explore half). Beside them, how much a per-repository optimum moves: the cutoff that maximises each confirm
repository's own MCC (repositories with >= 3 positives), and the raw value at which the relative
rule's constant falls in each repository (its implied cutoff). The two tuned cutoffs are
re-derived from the explore pools and checked against the harness's analysis files.

Reads data/main.json (dist: every Java class unit's raw value, modified z and PMD membership,
written by extract_main.py) and data/mlcq.json (pmd_dist, the same, by extract_mlcq.py).
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import stats, BOOT  # noqa: E402

Z_CUT = 3.5
SIGNAL = "cognitive_max"
ORACLE = "pmd_GodClass"


def tuned_cut(results_dir: str) -> float:
    a = common.load_json(os.path.join(results_dir, "analysis.json"))
    return float(a["primary"][ORACLE]["confirm"]["absolute_cutoff"]["cut"])


def tuned_z(results_dir: str) -> float:
    """The relative cut tuned on the explore half, the plan's secondary (relative_tuned)."""
    a = common.load_json(os.path.join(results_dir, "analysis.json"))
    return float(a["primary"][ORACLE]["confirm"]["relative_tuned"]["z_cut"])


def dists(data: dict, key: str) -> dict:
    """{repo: dist} for every usable repository carrying the definition, with its half."""
    rows = {r["repo"]: r for r in data["rows"]}
    out = {}
    for repo, rec in data[key].items():
        d = rec.get("dist") if key == "class" else rec
        if not d or d.get("signal") != SIGNAL or d.get("oracle") != ORACLE or not d.get("raw"):
            continue
        out[repo] = {"half": rows[repo]["half"], "raw": d["raw"], "z": d["z"], "god": set(d["god"])}
    return out


def confusion(flagged: list[bool], god: set, n: int) -> dict:
    tp = sum(1 for k in range(n) if flagged[k] and k in god)
    fp = sum(1 for k in range(n) if flagged[k] and k not in god)
    fn = sum(1 for k in range(n) if not flagged[k] and k in god)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": n - tp - fp - fn,
            "n_univ": n, "n_out": tp + fp, "n_overlap": tp, "n_god_univ": tp + fn}


def item_of(d: dict, own_cut: float, other_cut: float, own_z: float) -> dict:
    n = len(d["raw"])
    return {"n_pos": len(d["god"]),
            "rel": confusion([z >= Z_CUT for z in d["z"]], d["god"], n),
            # the extractors store z to four decimals, and a tuned cut is an observed z, so a unit
            # that ties the cut exactly can round below it: flag within half a rounding unit
            "rel_tuned": confusion([z >= own_z - 0.00005 for z in d["z"]], d["god"], n),
            "abs_own": confusion([x >= own_cut for x in d["raw"]], d["god"], n),
            "abs_other": confusion([x >= other_cut for x in d["raw"]], d["god"], n)}


def micro(items, key):
    c = stats.pooled_confusion([it[key] for it in items])
    return c


def macro_mcc(items, key):
    vals = [stats.mcc(it[key]["tp"], it[key]["fp"], it[key]["fn"], it[key]["tn"]) for it in items if it["n_pos"] >= 1]
    return sum(vals) / len(vals) if vals else None


def macro_fpr(items, key):
    vals = [stats.fpr(it[key]["fp"], it[key]["tn"]) for it in items]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def summary(items, key) -> dict:
    c = micro(items, key)
    return {"micro_mcc": c["mcc"], "precision": c["precision"], "recall": c["recall"], "micro_fpr": c["fpr"],
            "flagged": c["tp"] + c["fp"], "tp": c["tp"], "fp": c["fp"],
            "macro_mcc": macro_mcc(items, key), "macro_fpr": macro_fpr(items, key)}


def paired(items, a: str, b: str) -> dict:
    out = {}
    for arm, fn in (("macro_mcc", macro_mcc), ("micro_mcc", lambda its, k: micro(its, k)["mcc"]), ("macro_fpr", macro_fpr)):
        def diff(its, fn=fn):
            x, y = fn(its, a), fn(its, b)
            return None if x is None or y is None else x - y
        out[arm] = stats.bootstrap_paired(items, diff, **BOOT)
    return out


def quantiles(xs: list[float]) -> dict | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)

    def q(p):
        k = (n - 1) * p
        lo, hi = int(k), min(int(k) + 1, n - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)
    return {"n": n, "min": s[0], "q1": q(0.25), "median": q(0.5), "q3": q(0.75), "max": s[-1]}


def implied_cut(d: dict) -> float | None:
    """The raw value at which the modified z reaches 3.5 in this repository: the relative rule's
    constant translated onto the raw axis. z is affine in x, so two units with different values
    give the line; None when every unit ties."""
    pts = {}
    for x, z in zip(d["raw"], d["z"]):
        pts.setdefault(x, z)
        if len(pts) >= 2:
            break
    if len(pts) < 2:
        return None
    (x1, z1), (x2, z2) = list(pts.items())[:2]
    if z2 == z1:
        return None
    return x1 + (Z_CUT - z1) * (x2 - x1) / (z2 - z1)


def analyse(name: str, D: dict, own_cut: float, other_cut: float, own_z: float, p) -> dict:
    explore = [(x, k in d["god"]) for d in D.values() if d["half"] == "explore" for k, x in enumerate(d["raw"])]
    rederived = stats.best_cutoff(explore)
    confirm = {repo: d for repo, d in D.items() if d["half"] == "confirm"}
    items = [item_of(d, own_cut, other_cut, own_z) for d in confirm.values()]
    res = {"own_cut": own_cut, "other_cut": other_cut, "own_z_cut": own_z,
           "rederived_cut": rederived["cut"] if rederived else None,
           "n_confirm_repos": len(items), "n_confirm_repos_with_positive": sum(1 for it in items if it["n_pos"] >= 1),
           "rules": {k: summary(items, k) for k in ("rel", "rel_tuned", "abs_own", "abs_other")},
           "rel_minus_abs_other": paired(items, "rel", "abs_other"),
           "rel_tuned_minus_abs_own": paired(items, "rel_tuned", "abs_own"),
           "abs_other_minus_abs_own": paired(items, "abs_other", "abs_own"),
           "per_repo_optimal_cut": None, "implied_cut_of_z35": None}
    opt = []
    for d in confirm.values():
        if len(d["god"]) >= 3:
            b = stats.best_cutoff([(x, k in d["god"]) for k, x in enumerate(d["raw"])])
            if b:
                opt.append(b["cut"])
    res["per_repo_optimal_cut"] = quantiles(opt)
    res["implied_cut_of_z35"] = quantiles([c for c in (implied_cut(d) for d in confirm.values()) if c is not None])
    p(f"\n[{name}] confirm: {len(items)} repositories carrying PMD GodClass, own cut {own_cut:g} "
      f"(re-derived from the explore pool: {res['rederived_cut']}), other population's cut {other_cut:g}, "
      f"tuned relative cut z >= {own_z:.3f}")
    for k in ("rel", "rel_tuned", "abs_own", "abs_other"):
        m = res["rules"][k]
        p(f"   {k:10} micro MCC {m['micro_mcc']:.3f}  macro MCC {m['macro_mcc']:.3f}  macro FPR {m['macro_fpr']:.3f}  "
          f"precision {m['precision']:.2f} recall {m['recall']:.2f}  flagged {m['flagged']}")
    for lab in ("rel_minus_abs_other", "abs_other_minus_abs_own", "rel_tuned_minus_abs_own"):
        for arm, b in res[lab].items():
            p(f"   {lab:24} {arm:9} {b['value']:+.3f} [{b['lo']:+.3f}, {b['hi']:+.3f}]" if b else f"   {lab} {arm} n/a")
    for lab in ("per_repo_optimal_cut", "implied_cut_of_z35"):
        q = res[lab]
        if q:
            p(f"   {lab:24} n={q['n']} min {q['min']:g} q1 {q['q1']:g} median {q['median']:g} q3 {q['q3']:g} max {q['max']:g}")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--main", default=common.MAIN_RESULTS)
    ap.add_argument("--mlcq", default=common.MLCQ_RESULTS)
    ap.add_argument("--data", default=common.DATA)
    ap.add_argument("--out", default=os.path.join(common.DATA, "transfer.json"))
    args = ap.parse_args(argv)
    main_data = common.load_json(os.path.join(args.data, "main.json"))
    mlcq_data = common.load_json(os.path.join(args.data, "mlcq.json"))
    if "pmd_dist" not in mlcq_data:
        raise SystemExit("data/mlcq.json has no pmd_dist: re-run extract_mlcq.py")
    main_cut, mlcq_cut = tuned_cut(args.main), tuned_cut(args.mlcq)
    main_z, mlcq_z = tuned_z(args.main), tuned_z(args.mlcq)
    p = print
    p("EXPLORATORY (not in PLAN.md): the absolute cutoff carried between populations, against the "
      f"relative rule at its default; signal {SIGNAL}, oracle {ORACLE}")
    out = {"exploratory": True, "signal": SIGNAL, "oracle": ORACLE, "z_cut": Z_CUT, "bootstrap": BOOT,
           "computed_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "runs": {"main": analyse("main run", dists(main_data, "class"), main_cut, mlcq_cut, main_z, p),
                    "mlcq": analyse("MLCQ", dists(mlcq_data, "pmd_dist"), mlcq_cut, main_cut, mlcq_z, p)}}
    for name, r in out["runs"].items():
        if r["rederived_cut"] is not None and abs(r["rederived_cut"] - r["own_cut"]) > 1e-9:
            print(f"WARNING: {name}: re-derived explore cutoff {r['rederived_cut']} != analysis.json's {r['own_cut']}",
                  file=sys.stderr)
    common.dump_json(out, args.out)
    p(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
