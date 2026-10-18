"""complexity-concentration-study command line.

  complexity-concentration-study deps                         download the non-pip tools (PMD, CK) into ./lib
  complexity-concentration-study study [--sample f] [--out-dir d]   measure every repository of a sample

The sample (open-source-repository-sample.csv) is drawn by open-source-repository-sampler
(./step2_sample.sh), which also runs the loop: each usable repository is shallow-cloned at its
pinned commit, measured here, then deleted. Typical replication: ./step1_setup.sh,
./step2_sample.sh (or reuse an existing sample), ./step3_run.sh, ./step4_analyse.sh. The study
measures a per-repo (level x complexity signal x outlier algorithm x god definition) matrix;
analyse it with paper/analyse.py.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

from . import study, deps

DEFAULT_SAMPLE = os.path.join(deps.PROJECT_ROOT, "sample", "open-source-repository-sample.csv")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    dp = sub.add_parser("deps", help="download the non-pip tools (PMD, CK) into ./lib, each "
                        "verified against its pinned sha256 (needs network)")
    dp.add_argument("--lib", default=None, help="install into this dir instead of ./lib "
                    "(or $CCS_LIB)")
    dp.add_argument("--force", action="store_true", help="re-download even if already present")
    st = sub.add_parser("study", help="measure every usable repository of a sample, each at its "
                        "pinned commit (shallow-cloned by the sampler, then deleted)")
    st.add_argument("--sample", default=DEFAULT_SAMPLE,
                    help="the sample CSV (default sample/open-source-repository-sample.csv)")
    st.add_argument("--out-dir", default=None,
                    help="results directory (default results/<date>); resumable")
    st.add_argument("--pmd", default=None, help="PMD binary (default: ./lib PMD from `deps`)")
    st.add_argument("--ck", default=None, help="CK jar (default: ./lib CK from `deps`), for the "
                    "Java LCOM/TCC/CBO cohesion-and-coupling god definitions")
    st.add_argument("--lib", default=None, help="dependency dir to default --pmd/--ck from "
                    "(or $CCS_LIB; default ./lib)")
    st.add_argument("--anc", default=None, help="write the ancillary-data package here "
                    "(results.csv + README.txt + the sample's two files; default <out-dir>/anc)")
    args = ap.parse_args(argv)

    if args.cmd == "deps":
        deps.fetch(args.lib, args.force)
        return 0
    if args.cmd == "study":
        if not os.path.isfile(args.sample):
            print(f"no sample at {args.sample}: draw one with ./step2_sample.sh, or pass "
                  f"--sample", file=sys.stderr)
            return 2
        out_dir = args.out_dir or os.path.join(deps.default_results(),
                                               datetime.date.today().isoformat())
        pmd = args.pmd or deps.default_pmd(args.lib)   # default to the ./lib tools from `deps`
        ck = args.ck or deps.default_ck(args.lib)
        rows = study.run(args.sample, out_dir, pmd, ck)
        derivation = args.sample[:-len(".csv")] + ".derivation.json"
        study.write_anc(rows, args.anc or os.path.join(out_dir, "anc"),
                        frame_files=[args.sample, derivation])
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
