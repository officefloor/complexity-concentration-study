#!/usr/bin/env bash
#
# Step 1 of 4 — set up for replication.
#
#   ./step1_setup.sh
#
# A thin alias for ./setup.sh (venv + pinned Python deps, including the pinned
# open-source-repository-sampler, + PMD 7.27.0 / CK 0.7.0 into ./lib, each verified against its
# pinned sha256) that also prints the next step in the flow.
#
# Needs on the machine already: python3, git, and Java (JRE 17+). Step 2 (sampling) also needs
# the GitHub CLI authenticated — run `gh auth login` if you have not.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== STEP 1/4: setup ==="
./setup.sh "$@"

cat <<'NEXT'

=== STEP 1 complete. ===
Next — draw the sample (needs `gh auth login` done first):

    ./step2_sample.sh

or skip step 2 and measure an existing sample (e.g. the one published with the paper, or another
study's, to study exactly the same code):

    ./step3_run.sh --sample path/to/open-source-repository-sample.csv

NEXT
