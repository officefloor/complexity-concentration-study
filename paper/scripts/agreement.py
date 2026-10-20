#!/usr/bin/env python3
"""EXPLORATORY: the tool definitions and the main study's rules against MLCQ's reviewers, on
the REVIEWED units of every usable MLCQ repository.

    paper/scripts/agreement.py [--data paper/data/mlcq.json] [--main results/<date>]
                               [--out paper/data/agreement.json]

This computes the harness's step 5a (complexity_concentration_study/agreement.py) on the
reviewed units. That step read the per-unit payload through analyse.Run.block, whose
reviewed-unit restriction depends on the registry naming the human definitions;
results/mlcq/oracles.json does not (see extract_mlcq.py), so its output scored EVERY Java class
(218,896 units over 136 repositories) and held only the repositories with a Blob positive; it
is superseded by this one. Its questions, decisions and readings are kept unchanged; only the
universe differs, and god-free repositories are kept. Nothing is tuned on MLCQ: signal, rule and
cutoff are the main study's (cognitive_max, mad_z at 3.5, the explore-tuned absolute cutoff
from the main run's analysis.json; cc and its cutoff at method level), so every usable MLCQ
repository is used, with the confirm half beside it as a sensitivity.

  A. each fixed rule as a predictor of the reviewers' verdict (pooled precision, recall, MCC
     with a repository bootstrap interval): the tool definitions, the relative rule and the
     tuned absolute cutoff on the main study's chosen signal;
  C. the relative rule's MCC minus each other predictor's on the same units, paired over
     repositories, so a lead in A is read with its interval rather than from point estimates;
  B. the reviewers' positive rate in the classes the relative rule flags that the tool does
     not (its "false positives" in the main study), the classes neither flags, and the classes
     the tool flags; with the paired difference (relative-not-tool minus neither) and its
     repository bootstrap interval, and the same for the absolute rule.
Readings for B, as fixed in step 5a: lower bound above 0, reviewers call the extra flags
positive MORE often than unflagged non-god units; upper bound below 0, less often; otherwise
no difference resolved. No margin and no verdict: it is exploratory.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import stats, BOOT  # noqa: E402

LEVELS = {
    "class": {"human": "human_blob", "tool": "pmd_GodClass", "tools": ("pmd_GodClass", "decor_blob", "wmc47"),
              "signal": "cognitive_max", "primary": "pmd_GodClass"},
    "method": {"human": "human_method_long_method", "tool": "pmd_method_NPath200",
               "tools": ("pmd_method_NPath200", "cc14", "cognitive15", "loc50", "brain_method"),
               "signal": "cc", "primary": "pmd_method_NPath200"},
}
Z_CUT = 3.5


def main_cuts(main_dir: str) -> dict:
    """The main run's chosen signal and explore-tuned absolute cutoff per definition."""
    a = common.load_json(os.path.join(main_dir, "analysis.json"))
    out = {}
    for sect in ("primary", "secondary"):
        for name, res in a.get(sect, {}).items():
            c = (res.get("confirm") or {}).get("absolute_cutoff") or {}
            out[name] = {"signal": res.get("chosen_signal"), "cut": c.get("cut")}
    return out


def units_of(data, level, cfg, cut, rows):
    items = []
    for row in rows:
        rec = data[level].get(row["repo"])
        if not rec or not rec["units"]:
            continue
        sig = cfg["signal"]
        if sig not in rec["z"] or cfg["tool"] not in rec["tools"]:
            continue
        us = []
        for k in range(len(rec["units"])):
            u = {t: rec["tools"][t][k] for t in cfg["tools"] if t in rec["tools"]}
            u["human"] = rec["human"][k]
            u["rel"] = rec["z"][sig][k] >= Z_CUT
            u["abs"] = rec["raw"][sig][k] >= cut
            us.append(u)
        items.append(us)
    return items


def _confusion(items, pred):
    tp = fp = fn = tn = 0
    for repo in items:
        for u in repo:
            if pred not in u:
                continue
            if u[pred] and u["human"]:
                tp += 1
            elif u[pred]:
                fp += 1
            elif u["human"]:
                fn += 1
            else:
                tn += 1
    return tp, fp, fn, tn


def predictor(items, pred) -> dict:
    tp, fp, fn, tn = _confusion(items, pred)
    ci = stats.bootstrap_paired(items, lambda its: stats.mcc(*_confusion(its, pred)), **BOOT)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "mcc": stats.mcc(tp, fp, fn, tn), "mcc_ci": ci}


def groups_for(tool):
    return {"rel_not_tool": lambda u: u["rel"] and not u[tool],
            "abs_not_tool": lambda u: u["abs"] and not u[tool],
            "neither_rel_nor_tool": lambda u: not u["rel"] and not u[tool],
            "neither_abs_nor_tool": lambda u: not u["abs"] and not u[tool],
            "tool": lambda u: u[tool], "rel": lambda u: u["rel"], "abs": lambda u: u["abs"]}


def _rate(items, fn):
    n = k = 0
    for repo in items:
        for u in repo:
            if fn(u):
                n += 1
                k += u["human"]
    return (k / n if n else None), k, n


def _reading_mcc(ci):
    if not ci:
        return "not estimable"
    if ci["lo"] > 0:
        return "relative rule higher"
    if ci["hi"] < 0:
        return "relative rule lower"
    return "no difference resolved"


def _reading(ci):
    if not ci:
        return "not estimable"
    if ci["lo"] > 0:
        return "reviewers call the extra flags positive more often than unflagged non-god units"
    if ci["hi"] < 0:
        return "reviewers call the extra flags positive less often than unflagged non-god units"
    return "no difference resolved"


def compare(items, cfg) -> dict:
    tool = cfg["tool"]
    G = groups_for(tool)
    out = {"n_repos": len(items), "n_reviewed_units": sum(len(r) for r in items),
           "n_positive": sum(u["human"] for r in items for u in r),
           "base_rate": None, "predictors": {}, "groups": {}}
    out["base_rate"] = out["n_positive"] / out["n_reviewed_units"] if out["n_reviewed_units"] else None
    for pr in cfg["tools"] + ("rel", "abs"):
        if any(pr in u for r in items for u in r):
            out["predictors"][pr] = predictor(items, pr)
    # C. the relative rule's MCC minus each other predictor's, on the same units, paired over
    # repositories: whether its lead (or lag) in the table above is resolved
    out["rel_minus"] = {}
    if "rel" in out["predictors"]:
        for pr in out["predictors"]:
            if pr == "rel":
                continue

            def dmcc(its, pr=pr):
                return stats.mcc(*_confusion(its, "rel")) - stats.mcc(*_confusion(its, pr))
            ci = stats.bootstrap_paired(items, dmcc, **BOOT)
            out["rel_minus"][pr] = {"paired": ci, "reading": _reading_mcc(ci)}
    for g, fn in G.items():
        rate, k, n = _rate(items, fn)
        out["groups"][g] = {"rate": rate, "positive": k, "n": n}
    for rule in ("rel", "abs"):
        def diff(its, r=rule):
            a = _rate(its, G[f"{r}_not_tool"])[0]
            b = _rate(its, G[f"neither_{r}_nor_tool"])[0]
            return None if a is None or b is None else a - b
        ci = stats.bootstrap_paired(items, diff, **BOOT)
        out[f"{rule}_extra_minus_neither"] = {"paired": ci, "reading": _reading(ci)}
    return out


def _print(p, title, res, cfg, cut):
    p(f"\n{title}: {res['n_repos']} repositories, {res['n_reviewed_units']} reviewed units, "
      f"{res['n_positive']} reviewer positives (base rate {res['base_rate']:.3f})")
    p("  A. as a predictor of the reviewers' verdict      precision  recall   MCC [95% CI]")
    names = {"rel": f"relative mad_z on {cfg['signal']}", "abs": f"absolute {cfg['signal']} >= {cut:g}"}
    for k, m in res["predictors"].items():
        ci = m["mcc_ci"]
        p(f"     {names.get(k, k):40} {m['precision'] if m['precision'] is None else round(m['precision'], 3):>8}  "
          f"{round(m['recall'], 3):>6}    {m['mcc']:+.3f}" + (f" [{ci['lo']:+.3f}, {ci['hi']:+.3f}]" if ci else ""))
    p("  C. relative rule's MCC minus each predictor's, paired over repositories")
    for k, d in res.get("rel_minus", {}).items():
        ci = d["paired"]
        p(f"     rel - {names.get(k, k):34} " + (f"{ci['value']:+.3f} [{ci['lo']:+.3f}, {ci['hi']:+.3f}]" if ci else "n/a")
          + f"  -> {d['reading']}")
    p(f"  B. reviewers' positive rate by group (tool = {cfg['tool']})")
    for g, v in res["groups"].items():
        p(f"     {g:24} {v['rate'] if v['rate'] is None else round(v['rate'], 3):>6}  ({v['positive']} of {v['n']})")
    for rule in ("rel", "abs"):
        d = res[f"{rule}_extra_minus_neither"]
        ci = d["paired"]
        p(f"     {rule}-not-tool minus neither  " + (f"{ci['value']:+.3f} [{ci['lo']:+.3f}, {ci['hi']:+.3f}]" if ci else "n/a")
          + f"  -> {d['reading']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.path.join(common.DATA, "mlcq.json"))
    ap.add_argument("--main", default=common.MAIN_RESULTS)
    ap.add_argument("--out", default=os.path.join(common.DATA, "agreement.json"))
    args = ap.parse_args(argv)
    data = common.load_json(args.data)
    cuts = main_cuts(args.main)
    p = print
    p(f"EXPLORATORY (not in PLAN.md): tool definitions and the main study's rules against MLCQ's "
      f"reviewers, on the reviewed units of {data['results_dir']}; constants from {args.main}")
    out = {"exploratory": True, "source": args.data, "main_results": os.path.abspath(args.main),
           "computed_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "bootstrap": BOOT, "levels": {}}
    for level, cfg in LEVELS.items():
        mc = cuts.get(cfg["primary"]) or {}
        if mc.get("signal") != cfg["signal"] or mc.get("cut") is None:
            raise SystemExit(f"main analysis.json chose {mc} for {cfg['primary']}; this script fixes {cfg['signal']}")
        cut = float(mc["cut"])
        rows = data["rows"]
        items = units_of(data, level, cfg, cut, rows)
        res = {"signal": cfg["signal"], "rule": "mad_z", "z_cut": Z_CUT, "absolute_cut": cut, "human": cfg["human"],
               "tool": cfg["tool"], "all": compare(items, cfg)}
        _print(p, f"[{level}] ALL usable MLCQ repositories with reviewed units", res["all"], cfg, cut)
        co = units_of(data, level, cfg, cut, [r for r in rows if r["half"] == "confirm"])
        res["confirm_only"] = compare(co, cfg)
        _print(p, f"[{level}] SENSITIVITY: confirm half only", res["confirm_only"], cfg, cut)
        out["levels"][level] = res
    common.dump_json(out, args.out)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
