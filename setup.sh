#!/usr/bin/env bash
#
# One-command setup for replication.
#
#   ./setup.sh
#
# Creates the virtualenv, installs the pinned Python dependencies (editable), and downloads the
# non-pip tools -- PMD and CK -- into ./lib, each verified against the sha256 the study pins.
# After this, the study needs only the key flags; PMD/CK default to ./lib and output defaults to
# results/<date>:
#
#   .venv/bin/python -m god_complexity.cli grow --seed 1
#
# Override the Python interpreter with PYTHON=..., the dependency dir with GODC_LIB=..., and the
# output base with GODC_RESULTS=... .
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "[1/3] creating .venv"
"$PYTHON" -m venv .venv

echo "[2/3] installing pinned Python dependencies (editable)"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

echo "[3/3] downloading PMD and CK into ./lib (verified by sha256)"
.venv/bin/python -m god_complexity.cli deps

cat <<'DONE'

setup complete.

  run the study:   .venv/bin/python -m god_complexity.cli grow --seed 1
  output lands in: results/<date>/
  analyse it:      python3 paper/god_complexity.py --results results/<date> --level class

DONE
