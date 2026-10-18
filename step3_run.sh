#!/usr/bin/env bash
#
# Step 3 of 4 — run the study on the sample(s).
#
#   ./step3_run.sh [--sample FILE ...] [--out-dir DIR] [--labels CSV] [--pmd P --ck C --lib L]
#       --sample FILE   repeatable; default: sample/open-source-repository-sample.csv plus
#                       sample/open-source-repository-sample.java-supplement.csv when present
#       --out-dir DIR   default results/<date>
#       --labels CSV    expert labels (repo, commit, path, label) -> human_<label> definitions
#
# Each sample is verified against its derivation first. Then open-source-repository-sampler's run
# loop shallow-clones each usable repository at its pinned commit, the study measures it, and the
# clone is deleted, so disk use stays at one repository. A repository in two samples is measured
# once. PMD/CK default to ./lib (from step 1). Resumable: re-run with the same --out-dir to
# continue. Also writes the ancillary package (results.csv, oracles.json, README.txt and the sample
# files) to <out-dir>/anc.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
SAMPLES=()
OUTDIR="results/$(date +%Y-%m-%d)"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --sample) SAMPLES+=("$2"); shift 2 ;;
    --sample=*) SAMPLES+=("${1#*=}"); shift ;;
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
if [ ${#SAMPLES[@]} -eq 0 ]; then
  for f in sample/open-source-repository-sample.csv sample/open-source-repository-sample.java-supplement.csv; do
    [ -f "$f" ] && SAMPLES+=("$f")
  done
fi
[ ${#SAMPLES[@]} -gt 0 ] || { echo "ERROR: no sample in sample/ — run ./step2_sample.sh, or pass --sample"; exit 1; }
SAMPLE_FLAGS=()
for s in "${SAMPLES[@]}"; do
  [ -f "$s" ] || { echo "ERROR: no sample at $s"; exit 1; }
  SAMPLE_FLAGS+=(--sample "$s")
done

echo "=== STEP 3/4: run the study on ${SAMPLES[*]} -> $OUTDIR ==="
for s in "${SAMPLES[@]}"; do
  "$VENV/bin/open-source-repository-sampler" verify "$s"
done
"$VENV/bin/python" -m complexity_concentration_study.cli study "${SAMPLE_FLAGS[@]}" \
    --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 3 complete. ==="
echo "Next — analyse this run (see README, 'Analysing a run', for the rules the analysis must follow):"
echo
echo "    ./step4_analyse.sh --results $OUTDIR"
echo
