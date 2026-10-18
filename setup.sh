#!/usr/bin/env bash
#
# Set up for replication: creates .venv, installs the pinned Python dependencies (editable), and
# downloads the non-pip tools PMD 7.27.0 + CK 0.7.0 into ./lib, each verified against its pinned
# sha256.
#
# Needs on the machine already: python3, git, and Java (JRE 17+). Override the interpreter with
# PYTHON=..., the dependency dir with CCS_LIB=... .
#
# (step1_setup.sh wraps this and prints the next step in the numbered flow.)
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "[1/3] creating .venv"
"$PYTHON" -m venv .venv
echo "[2/3] installing pinned Python dependencies (editable)"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
echo "[3/3] downloading PMD + CK into ./lib (verified by sha256)"
.venv/bin/python -m complexity_concentration_study.cli deps
echo "setup complete."
