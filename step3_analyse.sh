#!/usr/bin/env bash
#
# Step 3 of 3 — analyse a run.
#
#   ./step3_analyse.sh --results results/<date>      # or omit --results to use the latest run
#
# Prints the full report at BOTH levels (class = god classes, method = god methods / brain
# method): the out-of-sample AUC headline with bootstrap CI, the signal and outlier-rule
# rankings, the conservation check, and the no-calibration head-to-head. Any extra flags are
# passed through to paper/analyse.py.
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

echo "=== STEP 3/3: analyse ${RESULTS:-the latest run} ==="
for LVL in class method; do
  echo
  echo "############################## level = $LVL ##############################"
  python3 paper/analyse.py ${RESARG[@]+"${RESARG[@]}"} --level "$LVL" ${PASS[@]+"${PASS[@]}"}
done

echo
echo "=== STEP 3 complete. ==="
echo "Re-run a single level any time, e.g.:"
echo
echo "    python3 paper/analyse.py ${RESULTS:+--results $RESULTS }--level class"
echo
