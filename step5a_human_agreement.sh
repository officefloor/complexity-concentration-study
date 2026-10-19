#!/usr/bin/env bash
#
# Step 5a — exploratory: the tool definitions and the main study's rules against MLCQ's
# reviewers, then the hashes of everything step 5 and this step wrote.
#
#   ./step5a_human_agreement.sh [--results results/mlcq] [--main results/<date>] [--labels-dir labels]
#
# 1. runs `agreement` on the MLCQ run (see complexity_concentration_study/agreement.py): over the
#    reviewed class units, how well PMD's GodClass, DECOR's Blob, WMC >= 47 and the main study's
#    relative and absolute rules predict the reviewers' Blob, and how often the reviewers called
#    Blob the classes the relative rule flags but PMD does not. Written to a dated
#    <results>/agreement.exploratory.<utc>.json; the planned MLCQ analysis.json is untouched.
# 2. writes mlcq-hashes.txt: the sha256 of the MLCQ download and its conversion, of the
#    planned MLCQ analysis.json (checked first against the analysis.json.sha256 the analysis
#    wrote beside it), and of every agreement.exploratory.*.json. Commit it.
#
# Decisions, made on 2026-10-19 BEFORE step 5 had produced any data (this script and
# agreement.py were committed before the MLCQ run), after the main confirmatory analysis.json
# was read, so the comparison is exploratory and not in PLAN.md:
#   - The questions are the ones the main result raised: does PMD itself agree with people,
#     and are the relative rule's "false positives" against PMD classes people call Blob?
#   - Nothing is tuned on MLCQ: signal, rule and cutoff are the main study's (cognitive_max,
#     mad_z, 22), checked against --main's analysis.json, which is refused on a mismatch.
#   - The MLCQ hashes go in their own file, mlcq-hashes.txt, so analysis-hashes.txt stays the
#     record of the main run; both are regenerated in full, never edited.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
RESULTS="results/mlcq"
MAIN=""
LABELS="labels"
while [ $# -gt 0 ]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2 ;;
    --results=*) RESULTS="${1#*=}"; shift ;;
    --main) MAIN="$2"; shift 2 ;;
    --main=*) MAIN="${1#*=}"; shift ;;
    --labels-dir) LABELS="$2"; shift 2 ;;
    --labels-dir=*) LABELS="${1#*=}"; shift ;;
    *) echo "ERROR: unknown flag $1" >&2; exit 1 ;;
  esac
done
PY="$VENV/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first"; exit 1; }
# the main run: the latest dated results directory (results/mlcq is not dated)
[ -n "$MAIN" ] || MAIN="$(ls -d results/2*/ 2>/dev/null | sort | tail -n1)"
MAIN="${MAIN%/}"
RESULTS="${RESULTS%/}"
A="$RESULTS/analysis.json"
[ -f "$A" ] || { echo "ERROR: no $A — run ./step5_mlcq.sh first" >&2; exit 1; }
[ -f "$MAIN/analysis.json" ] || { echo "ERROR: no main analysis.json in '$MAIN'" >&2; exit 1; }

echo "=== STEP 5a: exploratory agreement on $RESULTS (constants from $MAIN/analysis.json) ==="
"$PY" -m complexity_concentration_study.cli agreement --results "$RESULTS" --main "$MAIN"

RECORDED="$(cut -d' ' -f1 "$A.sha256")"
ACTUAL="$(sha256sum "$A" | cut -d' ' -f1)"
[ "$RECORDED" = "$ACTUAL" ] || { echo "ERROR: $A does not match its $A.sha256 ($ACTUAL vs $RECORDED)" >&2; exit 1; }

OUT="mlcq-hashes.txt"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
shopt -s nullglob
{
  echo "# sha256 of the MLCQ sub-study (step 5) and its exploratory agreement (step 5a). Written by"
  echo "# ./step5a_human_agreement.sh; never edited by hand. analysis.json is the planned MLCQ"
  echo "# analysis (PLAN.md, The MLCQ sub-study); agreement.exploratory.*.json is not in the plan."
  for f in "$LABELS"/MLCQCodeSmellSamples.csv "$LABELS"/mlcq-labels.csv "$LABELS"/mlcq-repos.csv \
           "$LABELS"/mlcq-summary.json "$A" "$RESULTS"/agreement.exploratory.*.json; do
    sha256sum "$f"
  done
} > "$TMP"
mv "$TMP" "$OUT"
trap - EXIT

echo
echo "=== STEP 5a complete: wrote $OUT ($(grep -vc '^#' "$OUT") files hashed). Commit it. ==="
