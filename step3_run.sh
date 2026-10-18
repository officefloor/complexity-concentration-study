#!/usr/bin/env bash
#
# Step 3 of 4 — run the study on a sample.
#
#   ./step3_run.sh [--sample FILE] [--out-dir DIR] [--pmd P --ck C --lib L]
#       --sample FILE   default sample/open-source-repository-sample.csv (from step 2, or any other)
#       --out-dir DIR   default results/<date>
#
# The sample is verified against its derivation first. Then open-source-repository-sampler's run
# loop shallow-clones each usable repository at its pinned commit, the study measures it, and the
# clone is deleted, so disk use stays at one repository. PMD/CK default to ./lib (from step 1).
# Resumable: re-run with the same --out-dir to continue. Also writes the ancillary package
# (results.csv, README.txt and the sample's two files) to <out-dir>/anc.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
SAMPLE="sample/open-source-repository-sample.csv"
OUTDIR="results/$(date +%Y-%m-%d)"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --sample) SAMPLE="$2"; shift 2 ;;
    --sample=*) SAMPLE="${1#*=}"; shift ;;
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
[ -f "$SAMPLE" ] || { echo "ERROR: no sample at $SAMPLE — run ./step2_sample.sh, or pass --sample"; exit 1; }

echo "=== STEP 3/4: run the study on $SAMPLE -> $OUTDIR ==="
"$VENV/bin/open-source-repository-sampler" verify "$SAMPLE"
"$VENV/bin/python" -m complexity_concentration_study.cli study --sample "$SAMPLE" \
    --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 3 complete. ==="
echo "Next — analyse this run:"
echo
echo "    ./step4_analyse.sh --results $OUTDIR"
echo
