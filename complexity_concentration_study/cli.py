"""complexity-concentration-study command line.

  complexity-concentration-study deps                      download the non-pip tools (PMD, CK) into ./lib
  complexity-concentration-study study  [--repos f]        multi-language god-class/method identification study
  complexity-concentration-study sample [--k N --seed S]   seeded stratified GitHub sample -> repos + manifest
  complexity-concentration-study grow   [--target N ...]   adaptive sample: top up until each language hits target

Typical replication: `./setup.sh` once (venv + pip + deps), then `grow --seed 1` -- PMD/CK
default to ./lib and output defaults to results/<date>. The study measures a per-repo
(level x complexity signal x outlier algorithm x god definition) matrix; analyse it with
paper/analyse.py.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import study, sample, grow, deps


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="complexity-concentration-study", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    dp = sub.add_parser("deps", help="download the non-pip tools (PMD, CK) into ./lib, each "
                        "verified against its pinned sha256 (needs network)")
    dp.add_argument("--lib", default=None, help="install into this dir instead of ./lib "
                    "(or $CCS_LIB)")
    dp.add_argument("--force", action="store_true", help="re-download even if already present")
    st = sub.add_parser("study", help="multi-language god-class/method identification study "
                        "(clones latest default branch, records the commit, deletes clone)")
    st.add_argument("-o", "--out", default="study.json")
    st.add_argument("--repos", default=None, help="file with one `URL [COMMIT]` per line; a "
                    "commit pins the exact revision measured")
    st.add_argument("--pmd", default=None, help="PMD binary (default: ./lib PMD from `deps`)")
    st.add_argument("--ck", default=None, help="CK jar (default: ./lib CK from `deps`), for the "
                    "Java LCOM/TCC/CBO cohesion-and-coupling god definitions")
    st.add_argument("--lib", default=None, help="dependency dir to default --pmd/--ck from "
                    "(or $CCS_LIB; default ./lib)")
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
                   "for the default configuration (needs the gh CLI). `grow -h` for options.")
    # `grow` owns all its defaults in grow.STUDY (single source of truth), so it is delegated
    # the raw argv rather than re-declaring every option here where the two could drift.
    if argv_list and argv_list[0] == "grow":
        return grow.main(argv_list[1:])
    args = ap.parse_args(argv)

    if args.cmd == "deps":
        deps.fetch(args.lib, args.force)
        return 0
    if args.cmd == "study":
        repos = study.DEFAULT_REPOS
        if args.repos:
            repos = study.read_repo_pins(args.repos)
        manifest = os.path.join(os.path.dirname(args.repos or "."), "sampling-manifest.json")
        pmd = args.pmd or deps.default_pmd(args.lib)   # default to the ./lib tools from `deps`
        ck = args.ck or deps.default_ck(args.lib)
        study.run(repos, args.out, pmd, args.keep, manifest, ck)
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
