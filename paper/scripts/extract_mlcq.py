#!/usr/bin/env python3
"""Extract the reviewed units of the MLCQ run from its per-unit sidecar.

    paper/scripts/extract_mlcq.py [--results results/mlcq] [--out paper/data/mlcq.json]

MLCQ's reviewers graded a handful of classes and methods per repository, so the human
definitions are scored only on those REVIEWED units (an unreviewed unit is unknown, not a
negative), while every relative rule is fitted on the repository's whole Java population, as
the harness fits it (analyse.Run.block). The sidecar is streamed once and reduced to, per
repository and level, the reviewed units with (and, for the cross-population transfer, every
Java class unit's cognitive_max, modified z and PMD GodClass membership, `pmd_dist`): their raw value and per-repository modified z
for every signal; whether each relative rule at its default flags them (every rule for a
small set of signals, the modified-z rule for all); the reviewers' verdict (human_blob /
human_method_long_method); and the tool definitions' verdicts on them. Nothing else of the
repository is kept, so the human-label analysis (human_readout.py) and the exploratory
agreement (agreement.py) run in seconds on the output.

Why this exists: the harness writes its definition registry (oracles.json) before the first
repository is measured and registers a human definition as its label is met, so
results/mlcq/oracles.json names no human definition and the harness's analysis.json carries no
human read-out. The registry written at the END of the run (results/mlcq/anc/oracles.json) has
them, and is what this script reads. Repositories whose reviewed units hold no positive are
KEPT (analyse.Run.block keys on the positive label and would drop them); README rule 4 says
they must be, and whether they are is reported as a sensitivity in human_readout.py.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import metrics, stats  # noqa: E402

CLASS_FULL_RULES = ("cognitive_max", "nloc_max", "cc_max", "nom", "nloc_sum", "tokens_max", "hvol_max",
                    "nesting_max", "mi_max", "exit_points_max", "cognitive_mean", "cc_mean", "mi_mean")
METHOD_FULL_RULES = ("cc", "cognitive", "nloc", "mi", "nesting", "cyc_density", "exit_points",
                     "params", "tokens", "hvol")
CLASS_TOOLS = ("pmd_GodClass", "decor_blob", "wmc47", "ck_LargeClass", "ck_LCOM", "ck_TCClow",
               "ck_CBOhigh", "pmd_TooManyMethods", "pmd_NcssCount")
METHOD_TOOLS = ("pmd_method_NPath200", "cc14", "cognitive15", "loc50", "params5", "nesting5",
                "brain_method", "pmd_method_CC10", "pmd_method_Cognitive15", "pmd_method_Ncss60")


def reduce_level(pl: dict, human: str, tools, full_rule_signals) -> dict | None:
    rev_key = human + "_reviewed"
    if rev_key not in pl["god_idx"]:
        return None
    units = pl["units"]
    fit = common.fit_indices(units, (".java",))
    fit_set = set(fit)
    reviewed = [i for i in pl["god_idx"][rev_key] if i in fit_set]
    reviewed = sorted(set(reviewed))
    gods = set(pl["god_idx"].get(human) or ())
    out = {"n_fit": len(fit), "n_reviewed_labelled": len(pl["god_idx"][rev_key]),
           "units": [units[i] for i in reviewed],
           "human": [i in gods for i in reviewed],
           "tools": {t: [i in set(pl["god_idx"].get(t) or ()) for i in reviewed] for t in tools
                     if t in pl["god_idx"]},
           "tool_counts": {t: len(pl["god_idx"][t]) for t in tools if t in pl["god_idx"]},
           "raw": {}, "z": {}, "flags": {}, "fit_flagged": {}}
    if not reviewed:
        return out
    for sig in pl["signals"]:
        v = pl["values"][sig]
        vmap = {i: v[i] for i in fit}
        zs = dict(zip(fit, stats.modified_z_values([v[i] for i in fit])))
        out["raw"][sig] = [v[i] for i in reviewed]
        out["z"][sig] = [round(zs[i], 4) for i in reviewed]
        if sig in full_rule_signals:
            fl = common.rule_flags(vmap)
            out["flags"][sig] = {rule: [i in s for i in reviewed] for rule, s in fl.items()}
            out["fit_flagged"][sig] = {rule: len(s) for rule, s in fl.items()}
    return out


def pmd_dist(pl: dict) -> dict | None:
    """Every Java class unit's raw cognitive_max, per-repository modified z and PMD GodClass
    membership, as data/main.json's dist: the cross-population transfer (transfer.py) reads
    the main plan's primary on MLCQ's population from it."""
    if "cognitive_max" not in pl["values"] or "pmd_GodClass" not in pl["god_idx"]:
        return None
    fit = common.fit_indices(pl["units"], (".java",))
    if not fit:
        return None
    v = pl["values"]["cognitive_max"]
    raw = [v[i] for i in fit]
    gods = set(pl["god_idx"]["pmd_GodClass"])
    return {"signal": "cognitive_max", "oracle": "pmd_GodClass", "raw": raw,
            "z": [round(z, 4) for z in stats.modified_z_values(raw)],
            "god": [k for k, i in enumerate(fit) if i in gods]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=common.MLCQ_RESULTS)
    ap.add_argument("--out", default=os.path.join(common.DATA, "mlcq.json"))
    args = ap.parse_args(argv)
    rows = common.usable_rows(args.results)
    reg_path = os.path.join(args.results, "anc", "oracles.json")
    registry = common.load_json(reg_path)["oracles"]
    missing = [h for h in ("human_blob", "human_blob_reviewed", "human_method_long_method",
                           "human_method_long_method_reviewed") if h not in registry]
    if missing:
        print(f"WARNING: {reg_path} lacks {missing}", file=sys.stderr)
    keep = {r["repo"] for r in rows}
    out = {"results_dir": os.path.abspath(args.results),
           "analysis_sha256": common.sha256(os.path.join(args.results, "analysis.json")),
           "harness_commits": sorted({(r.get("tools") or {}).get("harness_commit") for r in rows}),
           "registry_human": {k: v for k, v in registry.items() if k.startswith("human_")},
           "rows": rows, "class": {}, "method": {}, "pmd_dist": {}}
    n = 0
    for d in common.iter_sidecar(args.results, keep=keep):
        repo = d["repo"]
        if "class" in d:
            c = reduce_level(d["class"], "human_blob", CLASS_TOOLS, CLASS_FULL_RULES)
            if c is not None:
                out["class"][repo] = c
            pd = pmd_dist(d["class"])
            if pd is not None:
                out["pmd_dist"][repo] = pd
        if "method" in d:
            m = reduce_level(d["method"], "human_method_long_method", METHOD_TOOLS, METHOD_FULL_RULES)
            if m is not None:
                out["method"][repo] = m
        n += 1
        if n % 25 == 0:
            print(f"  {n} repositories reduced", file=sys.stderr, flush=True)
    common.dump_json(out, args.out)
    print(f"wrote {args.out}: {len(out['class'])} repositories with reviewed classes, "
          f"{len(out['method'])} with reviewed methods, of {len(rows)} usable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
