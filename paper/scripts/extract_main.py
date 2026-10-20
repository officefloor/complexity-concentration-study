#!/usr/bin/env python3
"""Extract what the paper's tables and figures need from the MAIN run's per-unit sidecar.

    paper/scripts/extract_main.py [--results results/<date>] [--out paper/data/main.json]

The sidecar is streamed one repository at a time and reduced to per-repository statistics:
for every Java repository and every class signal, the AUC against PMD GodClass and DECOR Blob
(as analyse.Run.auc computes it: rules fitted and scored on the Java units); for the signals
the analysis chose, the confusion counts under every relative rule at its default and under
the absolute cutoffs the analysis tuned on explore; and, for the primary signal, every Java
class unit's raw value, its per-repository modified z and its PMD GodClass membership (the
pooled distribution in the figures). Method level: the same for PMD NPath and brain_method.
Every number is computed with the harness's own metrics and stats modules.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import metrics, stats  # noqa: E402

# (level, oracle, scope) -> the signals whose rule/cutoff confusions are kept, with the absolute
# cutoffs analysis.json tuned on explore (read from it, below) plus a few descriptive ones.
CLASS_RULE_SIGNALS = ("cognitive_max", "nloc_max", "cc_max", "nloc_sum", "nom", "cc_mean", "mi_mean")
METHOD_RULE_SIGNALS = ("cc", "cognitive", "nloc", "mi", "cyc_density", "nesting")
DIST_SIGNAL = {"class": "cognitive_max", "method": "cc"}
DIST_ORACLE = {"class": "pmd_GodClass", "method": "pmd_method_NPath200"}


def cuts_from_analysis(results_dir: str) -> dict:
    """{(level, oracle): {signal: [cuts]}}: the absolute cutoffs the confirmatory analysis
    tuned on explore for each definition's chosen signal."""
    a = common.load_json(os.path.join(results_dir, "analysis.json"))
    out: dict = {}
    for sect in ("primary", "secondary"):
        for name, res in a.get(sect, {}).items():
            c = (res.get("confirm") or {}).get("absolute_cutoff") or {}
            if res.get("chosen_signal") and c.get("cut") is not None:
                out.setdefault((res["level"], name), {}).setdefault(res["chosen_signal"], []).append(c["cut"])
    return out, a


def collect(pl: dict, exts, oracles: list[str], rule_signals, abs_cuts: dict, dist_signal: str,
            dist_oracle: str) -> dict:
    units = pl["units"]
    fit = common.fit_indices(units, exts)
    out = {"n_fit": len(fit), "oracles": {}}
    if not fit:
        return out
    vals_cache = {}

    def vals(sig):
        if sig not in vals_cache:
            v = pl["values"][sig]
            vals_cache[sig] = {i: v[i] for i in fit}
        return vals_cache[sig]

    flags_cache = {}

    def flags(sig):
        if sig not in flags_cache:
            flags_cache[sig] = common.rule_flags(vals(sig))
        return flags_cache[sig]

    for oracle in oracles:
        if oracle not in pl["god_idx"]:
            continue
        gods = set(pl["god_idx"][oracle])
        score = fit
        o = {"n_pos": sum(1 for i in score if i in gods), "auc": {}, "cells": {}, "abs": {}}
        for sig in pl["signals"] if "signals" in pl else pl["values"]:
            v = vals(sig)
            pos = [v[i] for i in score if i in gods]
            neg = [v[i] for i in score if i not in gods]
            o["auc"][sig] = stats.auc(pos, neg) if pos and neg else None
        for sig in rule_signals:
            if sig not in pl["values"]:
                continue
            o["cells"][sig] = {rule: common.confusion(fl, gods, score) for rule, fl in flags(sig).items()}
            for cut in abs_cuts.get(oracle, {}).get(sig, []):
                v = vals(sig)
                flagged = {i for i in fit if v[i] >= cut}
                o["abs"].setdefault(sig, {})[str(cut)] = common.confusion(flagged, gods, score)
        out["oracles"][oracle] = o
    if dist_signal in pl["values"] and dist_oracle in pl["god_idx"]:
        v = vals(dist_signal)
        zs = stats.modified_z_values([v[i] for i in fit])
        gods = set(pl["god_idx"][dist_oracle])
        out["dist"] = {"signal": dist_signal, "oracle": dist_oracle,
                       "raw": [v[i] for i in fit], "z": [round(z, 4) for z in zs],
                       "god": [k for k, i in enumerate(fit) if i in gods]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=common.MAIN_RESULTS)
    ap.add_argument("--out", default=os.path.join(common.DATA, "main.json"))
    args = ap.parse_args(argv)
    rows = common.usable_rows(args.results)
    cuts, analysis = cuts_from_analysis(args.results)
    registry = common.load_json(os.path.join(args.results, "oracles.json"))["oracles"]
    by_repo = {r["repo"]: r for r in rows}
    java = {r["repo"] for r in rows if r.get("lang") == "java"}
    out = {"results_dir": os.path.abspath(args.results),
           "analysis_sha256": common.sha256(os.path.join(args.results, "analysis.json")),
           "study_sha256": analysis.get("study_sha256"),
           "harness_commits": sorted({(r.get("tools") or {}).get("harness_commit") for r in rows}),
           "cuts": {f"{k[0]}:{k[1]}": v for k, v in cuts.items()},
           "rows": rows, "class": {}, "method": {}}
    class_oracles = ["pmd_GodClass", "decor_blob", "wmc47"]
    method_oracles = ["pmd_method_NPath200", "brain_method"]
    n = 0
    for d in common.iter_sidecar(args.results, keep=java):
        repo = d["repo"]
        if "class" in d:
            out["class"][repo] = collect(d["class"], (".java",), class_oracles, CLASS_RULE_SIGNALS,
                                         {o: cuts.get(("class", o), {}) for o in class_oracles},
                                         DIST_SIGNAL["class"], DIST_ORACLE["class"])
        if "method" in d:
            # Java-scoped definitions fit on the Java units; brain_method (scope all) on every unit
            m_java = collect(d["method"], (".java",), ["pmd_method_NPath200"], METHOD_RULE_SIGNALS,
                             {"pmd_method_NPath200": cuts.get(("method", "pmd_method_NPath200"), {})},
                             DIST_SIGNAL["method"], DIST_ORACLE["method"])
            m_all = collect(d["method"], None, ["brain_method"], ("cognitive", "cc"),
                            {"brain_method": cuts.get(("method", "brain_method"), {})}, "", "")
            m_java["oracles"].update(m_all["oracles"])
            m_java["n_fit_all"] = m_all["n_fit"]
            out["method"][repo] = m_java
        n += 1
        if n % 20 == 0:
            print(f"  {n} Java repositories reduced", file=sys.stderr, flush=True)
    # brain_method is read on the MAIN sample in every language: per-repository AUC of its
    # candidate signals from the sidecar for the non-Java rows too (small: one pass, AUC only)
    others = {r["repo"] for r in rows if r.get("lang") != "java" and "supplement" not in (r.get("sample") or "")}
    out["method_other"] = {}
    for d in common.iter_sidecar(args.results, keep=others):
        if "method" in d:
            pl = d["method"]
            if "brain_method" not in pl["god_idx"]:
                continue
            gods = set(pl["god_idx"]["brain_method"])
            res = {"n_fit": len(pl["units"]), "n_pos": len(gods), "auc": {}}
            for sig in ("cognitive", "exit_points", "params", "cc", "nloc", "nesting", "mi", "cyc_density"):
                v = pl["values"][sig]
                pos = [v[i] for i in gods]
                neg = [v[i] for i in range(len(v)) if i not in gods]
                res["auc"][sig] = stats.auc(pos, neg) if pos and neg else None
            out["method_other"][d["repo"]] = res
    common.dump_json(out, args.out)
    print(f"wrote {args.out}: {len(out['class'])} Java repositories at class level, "
          f"{len(out['method'])} at method level, {len(out['method_other'])} other-language rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
