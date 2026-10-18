#!/usr/bin/env bash
#
# Step 2 of 4 — draw the sample of repositories, with open-source-repository-sampler.
#
#   ./step2_sample.sh [--out-dir DIR] [any other `open-source-repository-sampler sample` flag]
#
# Writes open-source-repository-sample.csv (every candidate drawn, each pinned to the commit that
# met the criteria) and open-source-repository-sample.derivation.json (how it was drawn) into
# sample/ (or --out-dir). Those two files are the study population and go in the paper's
# ancillary data unchanged. Skip this step to reuse an existing sample.
#
# The study's sampling criteria are set here, once, as code. Each flag is written out even when it
# equals the sampler's default, so the design is readable here and recorded in the derivation:
#   - all 11 languages x 3 popularity tiers, grown until each language has 30 usable repositories;
#   - the substance floor the analysis uses (study.MIN_FUNCS / MIN_UNIV): >= 50 functions in
#     >= 15 source files with a function;
#   - the author's own ecosystem excluded (the conflict-of-interest guard);
#   - no history criterion, so every candidate is shallow-cloned for inspection.
# Extra flags are passed straight through (a later flag overrides an earlier one), e.g. a
# different --seed for an independent sample. Interrupted? Re-run the same command to resume.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
SAMPLER="$VENV/bin/open-source-repository-sampler"
[ -x "$SAMPLER" ] || { echo "ERROR: $SAMPLER not found — run ./step1_setup.sh first"; exit 1; }

OUTDIR="sample"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

CRITERIA=(
  --langs java,python,javascript,typescript,go,c,c++,c#,ruby,php,rust
  --tiers high,mid,low
  --target 30
  --seed 1
  --pool 400
  --min-functions 50
  --min-files-with-functions 15
  --exclude-owners officefloor,sagenschneider
)

echo "=== STEP 2/4: draw the sample -> $OUTDIR ==="
"$SAMPLER" sample "${CRITERIA[@]}" --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 2 complete. ==="
echo "Next — measure every repository of this sample:"
echo
echo "    ./step3_run.sh --sample $OUTDIR/open-source-repository-sample.csv"
echo
