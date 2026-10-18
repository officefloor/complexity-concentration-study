"""complexity-concentration-study command line.

  complexity-concentration-study deps                              download the non-pip tools (PMD, CK) into ./lib
  complexity-concentration-study study [--sample f ...] [--out-dir d] [--labels csv]
                                                                   measure every repository of the sample(s)
  complexity-concentration-study analyse [--results d]             the report, to the README rules and PLAN.md
  complexity-concentration-study classpath-check --repo p ...      the classpath validation on one Java checkout
  complexity-concentration-study mlcq --input csv --out-dir d      convert MLCQ into --labels and --sample files

The sample(s) (open-source-repository-sample*.csv) are drawn by open-source-repository-sampler
(./step2_sample.sh: the main all-language sample and the Java supplement), which also runs the
loop: each usable repository is shallow-cloned at its pinned commit, measured here, then deleted.
Typical replication: ./step1_setup.sh, ./step2_sample.sh (or reuse existing samples),
./step3_run.sh, then the analysis. The study measures a per-repo (level x complexity signal x
outlier rule x god definition) matrix and writes the definition registry (oracles.json) with it.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

from . import study, deps

SAMPLE_DIR = os.path.join(deps.PROJECT_ROOT, "sample")
DEFAULT_SAMPLES = [os.path.join(SAMPLE_DIR, "open-source-repository-sample.csv"),
                   os.path.join(SAMPLE_DIR, "open-source-repository-sample.java-supplement.csv")]


def _derivation(sample: str) -> str:
    return sample[:-len(".csv")] + ".derivation.json" if sample.endswith(".csv") else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    dp = sub.add_parser("deps", help="download the non-pip tools (PMD, CK) into ./lib, each "
                        "verified against its pinned sha256 (needs network)")
    dp.add_argument("--lib", default=None, help="install into this dir instead of ./lib "
                    "(or $CCS_LIB)")
    dp.add_argument("--force", action="store_true", help="re-download even if already present")
    st = sub.add_parser("study", help="measure every usable repository of the sample(s), each at "
                        "its pinned commit (shallow-cloned by the sampler, then deleted)")
    st.add_argument("--sample", action="append", default=None,
                    help="a sample CSV; repeat for several (default: sample/open-source-repository-"
                         "sample.csv plus the Java supplement if present). A repository in two "
                         "samples is measured once")
    st.add_argument("--out-dir", default=None,
                    help="results directory (default results/<date>); resumable")
    st.add_argument("--pmd", default=None, help="PMD binary (default: ./lib PMD from `deps`)")
    st.add_argument("--ck", default=None, help="CK jar (default: ./lib CK from `deps`), for the "
                    "Java LCOM/TCC/CBO cohesion-and-coupling definitions and DECOR Blob")
    st.add_argument("--lib", default=None, help="dependency dir to default --pmd/--ck from "
                    "(or $CCS_LIB; default ./lib)")
    st.add_argument("--labels", default=None,
                    help="CSV of expert labels (repo, commit, path, label) added as class-level "
                         "human_<label> definitions where repo AND commit match the sample")
    st.add_argument("--anc", default=None, help="write the ancillary-data package here "
                    "(results.csv + oracles.json + README.txt + the sample files; default "
                    "<out-dir>/anc)")
    for name, mod in (("analyse", "analyse"), ("classpath-check", "classpath_check"),
                      ("mlcq", "mlcq")):
        sub.add_parser(name, add_help=False, help=f"see `{name} --help`")
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in ("analyse", "classpath-check", "mlcq"):
        import importlib
        mod = importlib.import_module(f".{argv[0].replace('-', '_')}", __package__)
        return mod.main(argv[1:])
    args = ap.parse_args(argv)

    if args.cmd == "deps":
        deps.fetch(args.lib, args.force)
        return 0
    if args.cmd == "study":
        samples = args.sample or [p for p in DEFAULT_SAMPLES if os.path.isfile(p)]
        if not samples:
            print(f"no sample in {SAMPLE_DIR}: draw one with ./step2_sample.sh, or pass --sample",
                  file=sys.stderr)
            return 2
        missing = [p for p in samples if not os.path.isfile(p)]
        if missing:
            print(f"no sample at {missing}", file=sys.stderr)
            return 2
        if args.labels and not os.path.isfile(args.labels):
            print(f"no labels file at {args.labels}", file=sys.stderr)
            return 2
        out_dir = args.out_dir or os.path.join(deps.default_results(),
                                               datetime.date.today().isoformat())
        pmd = args.pmd or deps.default_pmd(args.lib)   # default to the ./lib tools from `deps`
        ck = args.ck or deps.default_ck(args.lib)
        rows = study.run(samples, out_dir, pmd, ck, labels_path=args.labels)
        frame = [f for s in samples for f in (s, _derivation(s))] + ([args.labels] if args.labels else [])
        study.write_anc(rows, args.anc or os.path.join(out_dir, "anc"), frame_files=frame)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
