#!/usr/bin/env bash
#
# Write analysis-hashes.txt: the sha256 of every analysis of a run and of what it rests on, so
# the files the paper quotes are auditable against what was committed when.
#
#   ./record_hashes.sh [--results results/<date>]     # default: the latest run
#
# The file is regenerated in full from the files as they are, never edited, so its content
# is a function of the data; the ORDER of events (the confirmatory analysis recorded before any
# classpath report existed) is shown by the git history of this file, not by its content.
# Listed, in this order:
#   - <results>/analysis.json, the confirmatory analysis (PLAN.md step 5), checked first
#     against the analysis.json.sha256 the analysis wrote beside it: a mismatch is an error;
#   - every <results>/analysis.exploratory.*.json, the re-analyses (step 4c), oldest first;
#   - every <results>/classpath/*.json, the classpath validation reports (step 4b), which live
#     in the uncommitted results directory;
#   - the sample/ files the run was drawn from.
# Commit the file after each run of this script.
set -euo pipefail
cd "$(dirname "$0")"

RESULTS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2 ;;
    --results=*) RESULTS="${1#*=}"; shift ;;
    *) echo "ERROR: unknown flag $1" >&2; exit 1 ;;
  esac
done
[ -n "$RESULTS" ] || RESULTS="$(ls -d results/*/ 2>/dev/null | sort | tail -n1)"
RESULTS="${RESULTS%/}"
A="$RESULTS/analysis.json"
[ -f "$A" ] || { echo "ERROR: no analysis.json in '$RESULTS' — run ./step4_analyse.sh first" >&2; exit 1; }

RECORDED="$(cut -d' ' -f1 "$A.sha256")"
ACTUAL="$(sha256sum "$A" | cut -d' ' -f1)"
[ "$RECORDED" = "$ACTUAL" ] || { echo "ERROR: $A does not match its $A.sha256 ($ACTUAL vs $RECORDED)" >&2; exit 1; }

OUT="analysis-hashes.txt"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
# Globs expand sorted; nullglob makes an absent group (no exploratory analysis yet) empty.
shopt -s nullglob
{
  echo "# sha256 of the analyses of $RESULTS and of what they rest on. Written by ./record_hashes.sh;"
  echo "# never edited by hand. analysis.json is the confirmatory analysis (PLAN.md step 5);"
  echo "# analysis.exploratory.*.json are re-analyses; classpath/*.json are step 4b's reports."
  sha256sum "$A"
  for f in "$RESULTS"/analysis.exploratory.*.json "$RESULTS"/classpath/*.json sample/*; do
    sha256sum "$f"
  done
} > "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
echo "Wrote $OUT ($(grep -vc '^#' "$OUT") files hashed). Commit it."
