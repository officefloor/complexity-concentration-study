#!/usr/bin/env bash
#
# Step 2 of 3 — run the study.
#
#   ./step2_run.sh --seed 1 [any other `grow` flags]
#
# Draws the seeded sample and measures it. PMD/CK default to ./lib (from step 1); output goes to
# results/<date>/ unless you pass --out-dir. Any extra flags are passed straight through to
# `complexity-concentration-study grow` (e.g. --target, --langs). It is resumable: re-run with the same
# --out-dir to continue. The script prints the exact analyse command for step 3.
set -euo pipefail
cd "$(dirname "$0")"

# Own the output directory so we can hand its exact path to step 3. Default results/<date>;
# honour an explicit --out-dir and pass every other flag through to `grow` unchanged.
OUTDIR="results/$(date +%Y-%m-%d)"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

echo "=== STEP 2/3: run the study -> $OUTDIR ==="
.venv/bin/python -m complexity_concentration_study.cli grow --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 2 complete. ==="
echo "Next — analyse this run:"
echo
echo "    ./step3_analyse.sh --results $OUTDIR"
echo
