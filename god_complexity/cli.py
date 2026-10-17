"""god-complexity command line.

  god-complexity study  [--repos f]        multi-language god-class/method identification study
  god-complexity sample [--k N --seed S]   seeded stratified GitHub sample -> repos + manifest
  god-complexity grow   [--target N ...]   adaptive sample: top up until each language hits target

The study measures a per-repo (level x complexity signal x outlier algorithm x god
definition) matrix; analyse it with paper/god_complexity.py.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import study, sample, grow


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="god-complexity", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("study", help="multi-language god-class/method identification study "
                        "(clones latest default branch, records the commit, deletes clone)")
    st.add_argument("-o", "--out", default="god_complexity_study.json")
    st.add_argument("--repos", default=None, help="file with one `URL [COMMIT]` per line; a "
                    "commit pins the exact revision measured")
    st.add_argument("--pmd", default=None, help="PMD binary, for the Java design panel")
    st.add_argument("--ck", default=None, help="CK jar (mauricioaniche/ck), for the Java "
                    "LCOM/TCC/CBO cohesion-and-coupling god definitions")
    st.add_argument("--anc", default=None, help="write the ancillary-data package here "
                    "(results.csv + README.txt)")
    st.add_argument("--keep", action="store_true", help="do not delete clones")
    sm = sub.add_parser("sample", help="seeded stratified GitHub sample (needs the gh CLI) "
                        "-> repos list + auditable manifest")
    sm.add_argument("-o", "--out", default="repos.txt")
    sm.add_argument("-m", "--manifest", default="sampling-manifest.json")
    sm.add_argument("--k", type=int, default=3, help="repos per (language, tier) stratum")
    sm.add_argument("--seed", type=int, default=1)
    sm.add_argument("--pool", type=int, default=100, help="candidates fetched per stratum")
    sm.add_argument("--langs", default=",".join(sample.LANGS))
    sm.add_argument("--tiers", default="high,mid,low")
    sub.add_parser("grow", add_help=False, help="adaptive seeded sample: keep topping up "
                   "until each language reaches a usable-repo target. Run with no arguments "
                   "to reproduce the published study (needs the gh CLI). `grow -h` for options.")
    # `grow` owns all its defaults in grow.STUDY (single source of truth), so it is delegated
    # the raw argv rather than re-declaring every option here where the two could drift.
    if argv_list and argv_list[0] == "grow":
        return grow.main(argv_list[1:])
    args = ap.parse_args(argv)

    if args.cmd == "study":
        repos = study.DEFAULT_REPOS
        if args.repos:
            repos = study.read_repo_pins(args.repos)
        manifest = os.path.join(os.path.dirname(args.repos or "."), "sampling-manifest.json")
        study.run(repos, args.out, args.pmd, args.keep, manifest, args.ck)
        if args.anc:
            import json as _json
            rows = list({r["repo"]: r for r in _json.load(open(args.out))}.values())
            study.write_anc(rows, args.anc, frame_files=[args.repos, manifest])
        return 0
    if args.cmd == "sample":
        return sample.main(["-o", args.out, "-m", args.manifest, "--k", str(args.k),
                            "--seed", str(args.seed), "--pool", str(args.pool),
                            "--langs", args.langs, "--tiers", args.tiers])
    return 2


if __name__ == "__main__":
    sys.exit(main())
