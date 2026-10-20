#!/usr/bin/env bash
#
# Regenerate every number, table and figure of the paper from the harness's results.
#
#   ./regenerate.sh [--main results/<date>] [--mlcq results/mlcq] [--skip-extract]
#
# Steps, in order (each script's docstring says what it reads and writes):
#   1. scripts/extract_main.py   streams the main run's per-unit sidecar      -> data/main.json
#   2. scripts/check_extract.py  checks that reduction against analysis.json  (fails loudly)
#   3. scripts/extract_mlcq.py   streams the MLCQ run's sidecar               -> data/mlcq.json
#   4. scripts/human_readout.py  the planned human-label read-out             -> data/human.json
#   5. scripts/agreement.py      exploratory: tools and rules vs the reviewers -> data/agreement.json
#   6. scripts/tables.py         every table and inline number                -> generated/*.tex
#   7. scripts/figures.py        every figure                                 -> figures/*.pdf
# Steps 1-6 run on the harness's virtualenv (../.venv); step 7 on ./.venv (./setup.sh).
# --skip-extract reuses data/*.json from an earlier run (steps 1-3 take a few minutes each).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
HPY="$ROOT/.venv/bin/python"
FPY="$PWD/.venv/bin/python"
MAIN="" MLCQ="" SKIP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --main) MAIN="$2"; shift 2 ;;
    --mlcq) MLCQ="$2"; shift 2 ;;
    --skip-extract) SKIP=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -x "$HPY" ] || { echo "ERROR: $HPY missing: run ../step1_setup.sh" >&2; exit 1; }
[ -x "$FPY" ] || { echo "ERROR: $FPY missing: run ./setup.sh" >&2; exit 1; }
[ -n "$MAIN" ] && export CCS_MAIN_RESULTS="$(cd "$ROOT" && realpath "$MAIN")"
[ -n "$MLCQ" ] && export CCS_MLCQ_RESULTS="$(cd "$ROOT" && realpath "$MLCQ")"
if [ "$SKIP" = 0 ]; then
  echo "== 1/7 extract main run";  "$HPY" scripts/extract_main.py
  echo "== 2/7 check extraction";  "$HPY" scripts/check_extract.py
  echo "== 3/7 extract MLCQ run";  "$HPY" scripts/extract_mlcq.py
else
  echo "== 1-3/7 skipped (--skip-extract)"
fi
echo "== 4/7 human-label read-out"; "$HPY" scripts/human_readout.py | tee data/human_readout.log
echo "== 5/7 agreement";            "$HPY" scripts/agreement.py | tee data/agreement.log
echo "== 6/7 tables and numbers";   "$HPY" scripts/tables.py
echo "== 7/7 figures";              "$FPY" scripts/figures.py
echo
echo "Regenerated. Next: ./build.sh"
