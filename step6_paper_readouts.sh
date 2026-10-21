#!/usr/bin/env bash
#
# Step 6 — the paper's read-outs from the runs, including the blinded false-positive sample.
#
#   ./step6_paper_readouts.sh [--main results/<date>] [--mlcq results/mlcq]
#
# 1. runs paper/regenerate.sh in full: streams the main and MLCQ runs' per-unit sidecars into
#    paper/data/, checks that reduction against analysis.json, writes the human-label read-out,
#    the exploratory agreement, transfer and false-positive read-outs, every table and figure.
# 2. paper/scripts/false_positives.py, inside it, draws the reading sample with the seed 12345:
#    100 false positives and 100 true positives, at most 3 per repository, shuffled together and
#    numbered u001.. in shuffled order, written BLINDED to paper/data/fp_reading_sheet.json with
#    the key in paper/data/fp_sample_key.json and the protocol in paper/data/fp_reading_protocol.md.
#
# Then ./step6a_fp_prepare.sh.
#
# Decisions, made on 2026-10-21 before any reading of this sample: the sample, the protocol and
# the reading scripts were committed in 0202888 and pushed (2026-10-20 23:42 UTC) before the
# reading below was run; an earlier, unscripted reading was deleted unused.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
[ -x "$VENV/bin/python" ] || { echo "ERROR: $VENV/bin/python not found — run ./step1_setup.sh first" >&2; exit 1; }
[ -x paper/.venv/bin/python ] || { echo "ERROR: paper/.venv not found — run paper/setup.sh first" >&2; exit 1; }

echo "=== STEP 6: the paper's read-outs and the blinded reading sample ==="
paper/regenerate.sh "$@"
echo
echo "=== STEP 6 complete. Next: ./step6a_fp_prepare.sh ==="
