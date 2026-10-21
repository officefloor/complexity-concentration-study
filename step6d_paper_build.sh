#!/usr/bin/env bash
#
# Step 6d — merge the readings, regenerate the tables and figures, build the paper.
#
#   ./step6d_paper_build.sh
#
# 1. paper/regenerate.sh --skip-extract: re-runs the read-outs on the extraction step 6 made;
#    false_positives.py merges every paper/readings/fp_readings_*.json (unanswered units skipped)
#    and tables.py writes tab_fp_readings.tex.
# 2. paper/build.sh: main.pdf, abstract.txt and arxiv.tar.gz, whose ancillary data carries the
#    readings and the model's session records.
#
# Then commit paper/readings/, paper/generated/ and paper/figures/ together: the readings and
# the numbers they produce, after the commit of the scripts that produced them.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== STEP 6d: merge the readings and build the paper ==="
paper/regenerate.sh --skip-extract
paper/build.sh
echo
echo "=== STEP 6d complete. Commit paper/readings/, paper/generated/ and paper/figures/. ==="
