#!/usr/bin/env bash
#
# Step 6c — the model's blind reading of all 200 units, by script.
#
#   ./step6c_fp_model_reading.sh [--model claude-fable-5-1] [--jobs 5]
#
# 1. paper/scripts/fp_reading.py run-model: one `claude -p` session per batch of 20, each in a
#    fresh temporary directory holding only the protocol, its batch list and its 20 files, with
#    only the Read tool and no settings, memory or MCP servers. Every session is recorded in
#    paper/readings/fp_model_runs/batch_<k>.json with the prompt, command, CLI version and the
#    commit of the reading scripts; it refuses to start if those scripts are uncommitted.
#    About $50 and 15-20 minutes. Re-running overwrites the records: run it once.
# 2. paper/scripts/fp_reading.py collect-model: paper/readings/fp_readings_model.json from them.
#
# Then ./step6d_paper_build.sh.
set -euo pipefail
cd "$(dirname "$0")"

PY="${VENV:-.venv}/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first" >&2; exit 1; }
command -v claude >/dev/null || { echo "ERROR: the claude CLI is not on PATH" >&2; exit 1; }
[ -d paper/data/fp_sample ] || { echo "ERROR: no sample files — run ./step6a_fp_prepare.sh first" >&2; exit 1; }

echo "=== STEP 6c: the model's blind reading ==="
"$PY" paper/scripts/fp_reading.py run-model "$@"
"$PY" paper/scripts/fp_reading.py collect-model
echo
echo "=== STEP 6c complete. Next: ./step6d_paper_build.sh ==="
