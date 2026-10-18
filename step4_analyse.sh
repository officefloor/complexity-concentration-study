#!/usr/bin/env bash
#
# Step 4 of 4 — analyse a run.
#
#   ./step4_analyse.sh --results results/<date>      # or omit --results to use the latest run
#
# Prints the report to the README's rules and PLAN.md (diagnostics first, then the primary
# estimand chosen on explore and read on confirm, the secondary definitions in headline order,
# the Friedman comparisons, and the exploratory tables) and writes analysis.json beside the
# run. Any extra flags are passed through to `complexity-concentration-study analyse`.
set -euo pipefail
cd "$(dirname "$0")"

RESULTS=""
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2 ;;
    --results=*) RESULTS="${1#*=}"; shift ;;
    *) PASS+=("$1"); shift ;;
  esac
done
RESARG=()
[ -n "$RESULTS" ] && RESARG=(--results "$RESULTS")

VENV="${VENV:-.venv}"
echo "=== STEP 4/4: analyse ${RESULTS:-the latest run} ==="
"$VENV/bin/python" -m complexity_concentration_study.cli analyse ${RESARG[@]+"${RESARG[@]}"} ${PASS[@]+"${PASS[@]}"}

echo
echo "=== STEP 4 complete. ==="
echo "The first run of this step on a confirmatory sample is the confirmatory analysis; later"
echo "runs are exploratory (PLAN.md). analysis.json beside study.json holds the numbers."
echo
