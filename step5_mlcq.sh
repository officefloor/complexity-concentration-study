#!/usr/bin/env bash
#
# Step 5 (optional, after step 1) — the human-label sub-study on MLCQ, end to end.
#
#   ./step5_mlcq.sh [--out-dir DIR] [--labels-dir DIR] [--rule majority|any|all] [any other study flag]
#
# 1. downloads MLCQCodeSmellSamples.csv (Madeyski and Lewowski 2020, Zenodo 3666840) into
#    --labels-dir (default labels/) and verifies its sha256 against the datasheet's;
# 2. converts it: Blob -> class-level `blob`, Long Method -> method-level `long_method`, each with
#    a `*_reviewed` companion listing every reviewed unit (an unreviewed unit is unknown, not a
#    negative), several reviews per sample aggregated by --rule (default: strict majority), one
#    commit per repository; writes labels/mlcq-labels.csv, labels/mlcq-repos.csv, a summary;
# 3. measures every labelled repository at its labelled commit (the sampler's run loop clones
#    each one; resumable with the same --out-dir), with the human definitions scored within the
#    reviewed units;
# 4. prints the report, in which the human definitions are headline-order secondaries.
#
# The MLCQ repositories are a different population from the sampled one (chosen by MLCQ, Java,
# commits from 2019), so this run is reported beside the main run, never pooled with it.
# Needs step 1 (venv, PMD, CK) and network for the download and the clones.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
OUTDIR="results/mlcq"
LABELS="labels"
RULE="majority"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    --labels-dir) LABELS="$2"; shift 2 ;;
    --labels-dir=*) LABELS="${1#*=}"; shift ;;
    --rule) RULE="$2"; shift 2 ;;
    --rule=*) RULE="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
PY="$VENV/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first"; exit 1; }

echo "=== STEP 5: MLCQ human-label sub-study -> $OUTDIR ==="
echo "--- 5a. download (sha256-verified) and convert MLCQ -> $LABELS (rule: $RULE)"
"$PY" -m complexity_concentration_study.cli mlcq --download --out-dir "$LABELS" --rule "$RULE"

echo
echo "--- 5b. measure every labelled repository at its labelled commit"
"$PY" -m complexity_concentration_study.cli study \
    --sample "$LABELS/mlcq-repos.csv" --labels "$LABELS/mlcq-labels.csv" \
    --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "--- 5c. analyse"
"$PY" -m complexity_concentration_study.cli analyse --results "$OUTDIR"

echo
echo "=== STEP 5 complete: $OUTDIR/analysis.json (human definitions: human_blob, human_method_long_method) ==="
