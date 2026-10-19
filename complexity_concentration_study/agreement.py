"""Exploratory: do the tool definitions agree with MLCQ's reviewers, and are the relative rule's
"false positives" against PMD classes the reviewers called Blob?

    complexity-concentration-study agreement [--results results/mlcq] [--main results/<date>]

Written and committed on 2026-10-19 BEFORE the MLCQ run (step 5) had produced any data, after
the main run's confirmatory analysis.json was read; so it is exploratory, not part of PLAN.md,
and is written to a dated <results>/agreement.exploratory.<utc>.json, never in place of the
planned MLCQ analysis (analysis.json).

It reads the per-unit payload of the MLCQ run (study.units.jsonl) through analyse.Run, the same
code path the planned analysis uses, so the units, the reviewed universe and the relative rule
are exactly the analysis's. Over the REVIEWED class units of every usable repository that
carries both human_blob and PMD's GodClass, it reports:

  A. each fixed rule as a predictor of the reviewers' Blob (pooled precision, recall, MCC, with
     a repository bootstrap interval on the MCC): PMD's GodClass, DECOR's Blob, WMC >= 47, and
     the main study's two rules, the relative one (mad_z) and the tuned absolute cutoff, on the
     main study's chosen signal;
  B. the reviewers' Blob rate in three groups: the classes the relative rule flags that PMD
     does not (its "false positives" in the main study), the classes neither flags, and the
     classes PMD flags; with the paired difference (relative-not-PMD minus neither) and its
     repository bootstrap interval, and the same for the absolute rule for comparison.

Decisions, made on 2026-10-19 before any MLCQ data existed:
  - Signal, rule and cutoff are the MAIN study's (analysis.json: cognitive_max, mad_z at its
    default 3.5, absolute cutoff 22), not re-chosen on MLCQ: nothing here is tuned on MLCQ, so
    every usable MLCQ repository is used (both halves); the confirm half alone is reported
    beside it as a sensitivity. --main checks the constants against analysis.json and refuses
    on a mismatch.
  - Class level only. The question is the main study's primary (god classes); MLCQ's Long
    Method is a separate definition and is left to the planned analysis.
  - Only reviewed units are scored: a class no reviewer looked at is unknown, not clean (the
    same universe the planned analysis scores human_blob on).
  - The relative and absolute rules are fitted on the repository's whole Java class population
    (analyse.Run.block's fit set), as in the main study, then read on the reviewed units.
  - Intervals: percentile bootstrap over repositories, with PLAN's b and seed.
  - Readings, fixed here: for B, a lower bound above 0 reads "reviewers call the extra flags
    Blob more often than unflagged non-god classes"; an upper bound below 0 the reverse;
    otherwise "no difference resolved". No margin and no verdict: it is exploratory.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from . import analyse, stats

SIGNAL = "cognitive_max"
RULE = "mad_z"
CUT = 22.0
HUMAN = "human_blob"
PMD = "pmd_GodClass"
TOOLS = ("pmd_GodClass", "decor_blob", "wmc47")
LEVEL = "class"


def units(run: analyse.Run, rows) -> tuple[list, list]:
    """One item per repository: a list of reviewed units, each {human, rel, abs, <tool>...}.
    Returns (items, skipped repositories with the reason)."""
    rel_fn = run.rule_fn(RULE)
    abs_fn = run.cutoff_fn(CUT)
    items, skipped = [], []
    for r in rows:
        b = run.block(r["repo"], LEVEL, HUMAN)
        if b is None:
            skipped.append((r.get("full_name") or r["repo"], "no human_blob"))
            continue
        pl, fit, score, gods = b
        if PMD not in pl["god_idx"] or SIGNAL not in pl["values"]:
            skipped.append((r.get("full_name") or r["repo"], f"no {PMD} or {SIGNAL}"))
            continue
        vals = pl["values"][SIGNAL]
        vmap = {i: vals[i] for i in fit}
        rel, ab = rel_fn(vmap), abs_fn(vmap)
        tools = {t: set(pl["god_idx"].get(t) or ()) for t in TOOLS}
        if not score:
            skipped.append((r.get("full_name") or r["repo"], "no reviewed class unit"))
            continue
        items.append([dict({t: i in s for t, s in tools.items()},
                           human=i in gods, rel=i in rel, abs=i in ab) for i in score])
    return items, skipped


def _confusion(items, pred):
    tp = fp = fn = tn = 0
    for repo in items:
        for u in repo:
            if u[pred] and u["human"]:
                tp += 1
            elif u[pred]:
                fp += 1
            elif u["human"]:
                fn += 1
            else:
                tn += 1
    return tp, fp, fn, tn


def predictor(items, pred, boot) -> dict:
    tp, fp, fn, tn = _confusion(items, pred)
    ci = stats.bootstrap_paired(items, lambda its: stats.mcc(*_confusion(its, pred)), **boot)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "mcc": stats.mcc(tp, fp, fn, tn), "mcc_ci": ci}


GROUPS = {
    "rel_not_pmd": lambda u: u["rel"] and not u[PMD],
    "abs_not_pmd": lambda u: u["abs"] and not u[PMD],
    "neither_rel_nor_pmd": lambda u: not u["rel"] and not u[PMD],
    "neither_abs_nor_pmd": lambda u: not u["abs"] and not u[PMD],
    "pmd": lambda u: u[PMD],
}


def _rate(items, group):
    n = k = 0
    for repo in items:
        for u in repo:
            if GROUPS[group](u):
                n += 1
                k += u["human"]
    return (k / n if n else None), k, n


def _diff(items, a, b):
    ra, rb = _rate(items, a)[0], _rate(items, b)[0]
    return None if ra is None or rb is None else ra - rb


def _reading(ci) -> str:
    if not ci:
        return "not estimable"
    if ci["lo"] > 0:
        return "reviewers call the extra flags Blob more often than unflagged non-god classes"
    if ci["hi"] < 0:
        return "reviewers call the extra flags Blob less often than unflagged non-god classes"
    return "no difference resolved"


def compare(items, boot) -> dict:
    out = {"n_repos": len(items), "n_reviewed_units": sum(len(r) for r in items),
           "n_blob": sum(u["human"] for r in items for u in r),
           "predictors": {p: predictor(items, p, boot) for p in TOOLS + ("rel", "abs")},
           "groups": {}}
    for g in GROUPS:
        rate, k, n = _rate(items, g)
        out["groups"][g] = {"blob_rate": rate, "blob": k, "n": n}
    for rule in ("rel", "abs"):
        ci = stats.bootstrap_paired(
            items, lambda its, r=rule: _diff(its, f"{r}_not_pmd", f"neither_{r}_nor_pmd"), **boot)
        out[f"{rule}_extra_minus_neither"] = {"paired": ci, "reading": _reading(ci)}
    return out


def _print(p, title, res):
    p(f"\n{title}: {res['n_repos']} repositories, {res['n_reviewed_units']} reviewed class "
      f"units, {res['n_blob']} reviewer Blob")
    p("  A. as a predictor of the reviewers' Blob   precision  recall   MCC [95% CI]")
    names = {"rel": f"relative {RULE} on {SIGNAL}", "abs": f"absolute {SIGNAL} >= {CUT:g}"}
    for k, m in res["predictors"].items():
        ci = m["mcc_ci"]
        p(f"     {names.get(k, k):38} {analyse._f(m['precision'])}      {analyse._f(m['recall'])}"
          f"    {m['mcc']:+.3f}" + (f" [{ci['lo']:+.3f}, {ci['hi']:+.3f}]" if ci else ""))
    p("  B. reviewers' Blob rate by group")
    for g, v in res["groups"].items():
        p(f"     {g:22} {analyse._f(v['blob_rate'])}  ({v['blob']} of {v['n']})")
    for rule in ("rel", "abs"):
        d = res[f"{rule}_extra_minus_neither"]
        ci = d["paired"]
        p(f"     {rule}-not-PMD minus neither  "
          + (f"{ci['value']:+.3f} [{ci['lo']:+.3f}, {ci['hi']:+.3f}]" if ci else "n/a")
          + f"  -> {d['reading']}")


def check_main(main_dir: str) -> None:
    """Refuse if the main study's analysis.json chose other constants than the ones fixed here."""
    a = json.load(open(os.path.join(main_dir, "analysis.json")))
    prim = a["primary"]["pmd_GodClass"]
    got = (prim["chosen_signal"], prim["confirm"]["absolute_cutoff"]["cut"],
           a["plan"]["primary"]["rule"])
    if got != (SIGNAL, CUT, RULE):
        raise SystemExit(f"main analysis.json has {got}, this script fixes {(SIGNAL, CUT, RULE)}")


def report(run: analyse.Run, print_fn=print) -> dict:
    p = print_fn
    boot = {"b": run.plan["bootstrap"]["b"], "seed": run.plan["bootstrap"]["seed"]}
    p(f"EXPLORATORY (not in PLAN.md): tool definitions and the main study's rules against "
      f"MLCQ's reviewers, {run.dir}")
    items, skipped = units(run, run.rows)
    p(f"  repositories skipped: {len(skipped)} "
      + str(sorted({why for _, why in skipped})))
    out = {"exploratory": True, "signal": SIGNAL, "rule": RULE, "absolute_cut": CUT,
           "human": HUMAN, "skipped": skipped, "bootstrap": boot,
           "all": compare(items, boot)}
    _print(p, "ALL usable MLCQ repositories", out["all"])
    co = run.by_half["confirm"]
    c_items, _ = units(run, co)
    out["confirm_only"] = compare(c_items, boot)
    _print(p, "SENSITIVITY: confirm half only", out["confirm_only"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study agreement",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--results", default="results/mlcq", help="the MLCQ run (default results/mlcq)")
    ap.add_argument("--main", default=None,
                    help="the main run's results directory; its analysis.json is checked to "
                         "have chosen the constants this script fixes")
    args = ap.parse_args(argv)
    if not os.path.exists(os.path.join(args.results, "study.units.jsonl")):
        print(f"no study.units.jsonl in {args.results}: run ./step5_mlcq.sh first", file=sys.stderr)
        return 2
    if args.main:
        check_main(args.main)
    out = report(analyse.Run(args.results))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(args.results, f"agreement.exploratory.{stamp}.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    digest = analyse._sha256(path)
    with open(path + ".sha256", "w") as fh:
        fh.write(f"{digest}  {os.path.basename(path)}\n")
    print(f"\nwrote {path}\nsha256 {digest}  (also in {path}.sha256)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
