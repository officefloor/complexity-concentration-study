#!/usr/bin/env bash
#
# Step 4a — fix the order the classpath validation works through (PLAN.md step 4).
#
#   ./step4a_classpath_order.sh [--results results/<date>]     # default: the latest run
#
# Writes classpath-candidates.tsv: every EXPLORE-half Java repository of the run with at least
# one PMD GodClass (a repository with none cannot flip a GodClass verdict), sorted by name, then
# shuffled with random.Random(2) (the study's seed). ./step4b_classpath_check.sh works down this
# order and takes the first ten that build, so which repositories are validated is fixed before
# any is built, not picked by size or by how easy it looks. Commit the file before step 4b.
#
# Re-running regenerates the order and compares: an existing file that differs is an error,
# never overwritten (the order on record is the one validated).
#
# Decisions, made on 2026-10-19 after the confirmatory analysis.json was read (the validation
# was due before it, so it is a deviation from the plan and exploratory):
#   - Population: explore half only, as the plan requires; Java only, since PMD GodClass is
#     Java-only; at least one GodClass, since the flip rate is flips over the union of GodClass
#     verdicts and a repository with none adds nothing to it unless the classpath creates one.
#   - Order: a seeded shuffle, not by size, tier or ease of building, so the validated set is
#     fixed before any build and cannot be chosen by how it turns out. Sorting by name first
#     makes the shuffle independent of study.csv's row order.
#   - Seed: 2, the study's pre-registered sample seed, so no new free choice is introduced.
#   - No stratification by tier: ten repositories cannot balance three tiers usefully, and the
#     plan bounds a pooled flip rate.
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
[ -f "$RESULTS/study.csv" ] || { echo "ERROR: no study.csv in '$RESULTS' — run ./step3_run.sh first" >&2; exit 1; }

VENV="${VENV:-.venv}"
OUT="classpath-candidates.tsv"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

"$VENV/bin/python" - "$RESULTS/study.csv" "$TMP" <<'EOF'
import csv, random, sys
study, out = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open(study))
        if r["lang"] == "java" and r["half"] == "explore" and float(r["pmd_gods"] or 0) > 0]
rows.sort(key=lambda r: r["full_name"])
random.Random(2).shuffle(rows)
with open(out, "w") as f:
    f.write("# Classpath validation order (PLAN.md step 4): explore-half Java repos with >= 1 PMD GodClass,\n"
            "# sorted by name then shuffled with random.Random(2). Work down in order; take the first 10 that\n"
            "# build; record every skip and why. Do not reorder or pick by size.\n")
    f.write("order\tfull_name\tcommit\ttier\tpmd_gods\n")
    for i, r in enumerate(rows, 1):
        f.write(f"{i}\t{r['full_name']}\t{r['commit']}\t{r['tier']}\t{r['pmd_gods']}\n")
EOF

if [ -f "$OUT" ]; then
  if cmp -s "$TMP" "$OUT"; then
    echo "$OUT is already the order for $RESULTS ($(grep -vc '^#\|^order' "$OUT") candidates); unchanged."
  else
    echo "ERROR: $OUT exists and differs from the order generated from $RESULTS; not overwritten." >&2
    exit 1
  fi
else
  cp "$TMP" "$OUT"
  echo "Wrote $OUT ($(grep -vc '^#\|^order' "$OUT") candidates) from $RESULTS."
fi
echo
echo "Next: commit $OUT, then ./step4b_classpath_check.sh --results $RESULTS"
