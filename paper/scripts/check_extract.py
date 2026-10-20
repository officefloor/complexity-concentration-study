#!/usr/bin/env python3
"""Consistency check: the per-repository reductions in paper/data/main.json reproduce the
numbers the harness's confirmatory analysis.json reports for the primary definition.

    paper/scripts/check_extract.py [--data paper/data/main.json] [--results results/<date>]

Checks the confirm-half macro per-repository AUC (mean and n), the pooled MCC, precision, recall
and FPR of the modified-z rule at its default and of the tuned absolute cutoff, and the macro
MCC, each to 1e-9, so a drift between the paper's extraction and the harness's one code path
fails loudly here rather than in a table. Exit 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import stats  # noqa: E402


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.path.join(common.DATA, "main.json"))
    ap.add_argument("--results", default=common.MAIN_RESULTS)
    args = ap.parse_args(argv)
    data = common.load_json(args.data)
    a = common.load_json(os.path.join(args.results, "analysis.json"))
    ok = True
    checks = [("class", "pmd_GodClass", a["primary"]["pmd_GodClass"]),
              ("class", "decor_blob", a["secondary"]["decor_blob"]),
              ("method", "pmd_method_NPath200", a["secondary"]["pmd_method_NPath200"]),
              ("method", "brain_method", a["secondary"]["brain_method"])]
    rows = {r["repo"]: r for r in data["rows"]}
    for level, oracle, res in checks:
        sig = res["chosen_signal"]
        cut = res["confirm"]["absolute_cutoff"]["cut"]
        if oracle == "brain_method":
            # read on the MAIN sample in every language; the extract keeps Java in `method` and
            # the rest in `method_other` (AUC only)
            co = [(r, data["method"].get(r["repo"]) or {}) for r in data["rows"]
                  if r["half"] == "confirm" and "supplement" not in (r.get("sample") or "")]
            aucs = []
            for r, rec in co:
                o = (rec.get("oracles") or {}).get("brain_method")
                if o is None:
                    o = data["method_other"].get(r["repo"])
                if o and o["n_pos"] >= 3:
                    aucs.append(o["auc"][sig])
            got = stats.bootstrap_mean(aucs, min_n=2)
            want = res["confirm"]["auc_macro"]
            same = close(got["mean"], want["mean"]) and got["n"] == want["n"]
            print(f"{oracle:22} macro AUC {got['mean']:.4f} n={got['n']} vs {want['mean']:.4f} n={want['n']} -> {'ok' if same else 'MISMATCH'}")
            ok &= same
            continue
        recs = [(rows[repo], rec) for repo, rec in data[level].items() if rows[repo]["half"] == "confirm"]
        aucs, rel, absd = [], [], []
        for r, rec in recs:
            o = rec["oracles"].get(oracle)
            if not o:
                continue
            if o["n_pos"] >= 3:
                aucs.append(o["auc"][sig])
            rel.append(o["cells"][sig]["mad_z"])
            absd.append(o["abs"][sig][str(cut)])
        got_auc = stats.bootstrap_mean(aucs, min_n=2)
        want = res["confirm"]
        same = close(got_auc["mean"], want["auc_macro"]["mean"]) and got_auc["n"] == want["auc_macro"]["n"]
        print(f"{oracle:22} macro AUC {got_auc['mean']:.4f} n={got_auc['n']} vs {want['auc_macro']['mean']:.4f} "
              f"n={want['auc_macro']['n']} -> {'ok' if same else 'MISMATCH'}")
        ok &= same
        for name, cells, want_m in (("mad_z", rel, want["relative_default"]),
                                    ("absolute", absd, want["absolute_cutoff"]["confirm"])):
            mi = stats.pooled_confusion(cells)
            per = [stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"]) for c in cells]
            mac = sum(per) / len(per)
            same = (close(mi["mcc"], want_m["micro"]["mcc"]) and close(mi["precision"], want_m["micro"]["precision"])
                    and close(mi["recall"], want_m["micro"]["recall"]) and close(mac, want_m["macro"]["mean"])
                    and mi["n_blocks"] == want_m["micro"]["n_blocks"])
            print(f"{'':22} {name:9} micro MCC {mi['mcc']:.4f} macro {mac:.4f} n={mi['n_blocks']} vs "
                  f"{want_m['micro']['mcc']:.4f} / {want_m['macro']['mean']:.4f} n={want_m['micro']['n_blocks']} -> {'ok' if same else 'MISMATCH'}")
            ok &= same
    print("ALL OK" if ok else "MISMATCHES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
