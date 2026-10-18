#!/usr/bin/env bash
#
# Step 2 of 4 — draw the samples of repositories, with open-source-repository-sampler.
#
#   ./step2_sample.sh [--seed N] [--out-dir DIR] [--java-target N] [any other `open-source-repository-sampler sample` flag]
#
# Draws TWO samples into sample/ (or --out-dir), each a pair of files -- the CSV of every candidate
# drawn (usable or excluded with its reason, each pinned to the commit that met the criteria) and
# the .derivation.json of how it was drawn:
#
#   open-source-repository-sample.csv                   the MAIN sample: every language in
#                                                       study.SAMPLED_LANGUAGES x 3 tiers, 30 usable
#                                                       repositories per language (Ruby is not
#                                                       sampled: see study.EXCLUDED_LANGUAGES)
#   open-source-repository-sample.java-supplement.csv   the JAVA SUPPLEMENT: Java only, grown to
#                                                       --java-target (default 150) usable repos
#
# Why a Java supplement: every composite class-level god definition (PMD GodClass, DECOR Blob)
# and every tool method-level definition is Java-only, so the class-level headline's effective
# sample is the number of JAVA repositories, not the number of repositories. 30 is too few for a
# held-out confirm half with a median of ~2 god classes per repository. Same seed and criteria:
# the supplement's draw ORDER repeats the main sample's Java draw, so its first 30 usable Java
# repositories are normally the main sample's. That holds only while both enumerations of
# GitHub return the same candidate set (the seeded shuffle runs over the sorted set, so one
# repository gained or lost between the two draws permutes the order); if they differ, the
# Java population is the UNION of the two draws, step 3 still measures each repository once,
# and the analysis reports how many Java rows each sample drew.
#
# The study's sampling criteria are set here, once, as code. Each flag is written out even when it
# equals the sampler's default, so the design is readable here and recorded in the derivation:
#   - the substance floor the analysis uses (study.MIN_FUNCS / MIN_UNIV): >= 50 functions in
#     >= 15 source files with a function;
#   - the author's own ecosystem excluded (the conflict-of-interest guard);
#   - no history criterion, so every candidate is shallow-cloned for inspection.
# The seed defaults to 2, the pre-registered confirmatory seed (PLAN.md, 'Sample seed'): it is
# the seed the companion coupling study (sinew-identification-study) draws its Java sample
# with, and the sampler's draw order is keyed by seed, language and tier alone, so the two
# studies share one Java population by design. Seed 1 drew the pilot and is refused. Pass
# --seed N only for a deliberately independent sample, and record why. Extra flags are passed
# straight through to BOTH draws (a later flag overrides an earlier one). Interrupted? Re-run
# the same command to resume.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
SAMPLER="$VENV/bin/open-source-repository-sampler"
[ -x "$SAMPLER" ] || { echo "ERROR: $SAMPLER not found — run ./step1_setup.sh first"; exit 1; }

OUTDIR="sample"
JAVA_TARGET=150
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) OUTDIR="$2"; shift 2 ;;
    --out-dir=*) OUTDIR="${1#*=}"; shift ;;
    --java-target) JAVA_TARGET="$2"; shift 2 ;;
    --java-target=*) JAVA_TARGET="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

# The seed: 2 unless overridden, and never 1. The pilot (pilot/run-v1-repos.txt) was drawn
# with seed 1, so 1 is refused: a confirmatory sample drawn with it would be a re-draw of data
# the plan was shaped on (README, 'Pre-registration'). Seed 2 is shared with the coupling
# study on purpose (see above); an explicit --seed is passed through unchanged.
DEFAULT_SEED=2
SEED=""
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --seed) SEED="${ARGS[$((i + 1))]:-}" ;;
    --seed=*) SEED="${ARGS[$i]#*=}" ;;
  esac
done
if [ -z "$SEED" ]; then
  SEED="$DEFAULT_SEED"
  ARGS+=(--seed "$SEED")
  echo "seed $SEED (the pre-registered seed, shared with sinew-identification-study's Java draw)"
elif [ "$SEED" != "$DEFAULT_SEED" ]; then
  echo "NOTE: seed $SEED is not the pre-registered seed $DEFAULT_SEED; this sample is INDEPENDENT of the coupling study's. Record why." >&2
fi
if [ "$SEED" = "1" ]; then
  echo "ERROR: seed 1 drew the pilot (pilot/run-v1-repos.txt); a confirmatory sample needs a fresh seed." >&2
  exit 1
fi

COMMON=(
  --tiers high,mid,low
  --min-functions 50
  --min-files-with-functions 15
  --exclude-owners officefloor,sagenschneider
)
LANGS="$("$VENV/bin/python" -c 'from complexity_concentration_study.study import SAMPLED_LANGUAGES as L; print(",".join(L))')"
# (The sampler enumerates the whole population of each stratum, so there is no candidate pool to
# size; sampler 0.1.0 has no such flag and refuses one.)
MAIN=(--langs "$LANGS" --target 30)
JAVA=(--langs java --target "$JAVA_TARGET" --label java-supplement)

echo "=== STEP 2/4: draw the MAIN sample ($LANGS x 30) -> $OUTDIR ==="
"$SAMPLER" sample "${COMMON[@]}" "${MAIN[@]}" --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 2/4: draw the JAVA SUPPLEMENT (java x $JAVA_TARGET) -> $OUTDIR ==="
"$SAMPLER" sample "${COMMON[@]}" "${JAVA[@]}" --out-dir "$OUTDIR" ${ARGS[@]+"${ARGS[@]}"}

echo
echo "=== STEP 2 complete. ==="
echo "Next — measure every repository of both samples (each once):"
echo
echo "    ./step3_run.sh --sample $OUTDIR/open-source-repository-sample.csv --sample $OUTDIR/open-source-repository-sample.java-supplement.csv"
echo
