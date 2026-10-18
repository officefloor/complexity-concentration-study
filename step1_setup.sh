#!/usr/bin/env bash
#
# Step 1 of 3 — set up for replication.
#
#   ./step1_setup.sh
#
# A thin alias for ./setup.sh (venv + pinned Python deps + PMD 7.27.0 / CK 0.7.0 into ./lib,
# each verified against its pinned sha256) that also prints the next step in the flow.
#
# Needs on the machine already: python3, git, and Java (JRE 17+). Step 2 (sampling) also needs
# the GitHub CLI authenticated — run `gh auth login` if you have not.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== STEP 1/3: setup ==="
./setup.sh "$@"

cat <<'NEXT'

=== STEP 1 complete. ===
Next — run the study (needs `gh auth login` done first):

    ./step2_run.sh --seed 1

NEXT
