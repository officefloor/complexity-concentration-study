#!/usr/bin/env bash
#
# Step 6a — fetch the reading sample and prepare the author's reading.
#
#   ./step6a_fp_prepare.sh
#
# 1. paper/scripts/false_positives.py --fetch: downloads the 200 sampled files at their pinned
#    commits from raw.githubusercontent.com into paper/data/fp_sample/<id>.java.
# 2. paper/scripts/fp_reading.py prepare: the method the harness measured as most complex in each
#    file (paper/data/fp_sample_methods.json); the author's 40 units, drawn with the seed 12345
#    (20 false positives, then 20 true positives) and listed blind in paper/data/fp_author_list.md;
#    and a blank paper/readings/fp_readings_author.json (never overwritten once it exists).
#
# Then ./step6b_fp_author_reading.sh.
set -euo pipefail
cd "$(dirname "$0")"

PY="${VENV:-.venv}/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first" >&2; exit 1; }
[ -f paper/data/fp_reading_sheet.json ] || { echo "ERROR: no reading sheet — run ./step6_paper_readouts.sh first" >&2; exit 1; }

echo "=== STEP 6a: fetch the sample and prepare the author's reading ==="
"$PY" paper/scripts/false_positives.py --fetch
"$PY" paper/scripts/fp_reading.py prepare
echo
echo "=== STEP 6a complete. Next: ./step6b_fp_author_reading.sh ==="
