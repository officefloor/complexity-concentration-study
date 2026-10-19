#!/usr/bin/env bash
#
# Step 4b — the classpath validation (PLAN.md step 4; README, 'The classpath validation
# sub-study'): build explore-half Java repositories and report how many PMD GodClass verdicts
# flip when PMD is given the built classpath.
#
#   ./step4b_classpath_check.sh [--results results/<date>] [--target 10] [--work DIR]
#                               [--timeout 45m] [--only owner/name]
#
# Works down classpath-candidates.tsv (./step4a_classpath_order.sh) in order until --target
# repositories have a report. For each: shallow-clone it at its sampled commit, build it with
# its own Maven or Gradle wrapper (tests skipped), collect the classpath, and run
# `classpath-check`, writing <results>/classpath/<owner>__<name>.json, which step 4c's analysis
# aggregates. Every attempt is appended to classpath-log.tsv (ok / skip / fail, with the reason
# and the JDK), so the paper can report how many were tried; commit that log at the end.
#
# Resumable: a repository already in the log is not tried again. To retry one (say, under an
# older JDK: JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 ./step4b_classpath_check.sh --only
# owner/name), --only replaces its log line. A build that needs its sources or build files
# edited is a skip, not something to fix: the validation is of the repositories as sampled.
#
# Guard: a repository is built only if halves.json puts it in the EXPLORE half. Confirm
# repositories are never cloned here.
#
# Needs Maven (for pom.xml projects), a JDK, network. Gradle projects use their own ./gradlew;
# one without a wrapper, and any Android project (no SDK here), is a skip. Maven artifacts go
# to <work>/m2, not ~/.m2.
#
# Decisions, made on 2026-10-19 AFTER the confirmatory analysis.json was written and read (the
# plan required this validation before confirm was read; it was skipped, so everything this
# step feeds is exploratory and reported as a deviation):
#   - Which repositories: classpath-candidates.tsv's fixed order (step 4a), first --target that
#     build. The plan says "at least ten"; ten is the default, chosen before any was built.
#   - What counts as building: the project's own build as sampled, with tests, javadoc and
#     signing skipped (-Dmaven.test.skip, -Dmaven.javadoc.skip, -Dgpg.skip; Gradle's `classes`
#     only). A build that needs any file edited, a dependency forced, or more than --timeout
#     (45m) is a fail. Skipping test compilation can break a build that consumes a test-jar;
#     that is a fail too, not a reason to change the flags.
#   - Skips, recorded but not counted: Android projects (no SDK on this machine), Gradle without
#     a wrapper (no way to know which Gradle the project needs), and no Maven/Gradle build.
#   - JDK: whatever is on PATH; a fail that is only a JDK version mismatch may be retried under
#     another JDK with --only. The JDK of every attempt is in the log.
#   - The classpath: the union over modules of each module's main runtime classpath (Maven's
#     dependency:build-classpath per module; Gradle's sourceSets.main.runtimeClasspath), plus
#     the project's own compiled classes, which classpath-check adds itself. PMD sees the
#     study's own file list for the checkout either way, so only the classpath differs.
#   - Maven uses <work>/m2 so the user's ~/.m2 is not filled with these projects' snapshots.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

RESULTS=""
TARGET=10
WORK="$HOME/cp-work"
TIMEOUT="45m"
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --results) RESULTS="$2"; shift 2 ;;
    --results=*) RESULTS="${1#*=}"; shift ;;
    --target) TARGET="$2"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    --work) WORK="$2"; shift 2 ;;
    --work=*) WORK="${1#*=}"; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --timeout=*) TIMEOUT="${1#*=}"; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --only=*) ONLY="${1#*=}"; shift ;;
    *) echo "ERROR: unknown flag $1" >&2; exit 1 ;;
  esac
done
[ -n "$RESULTS" ] || RESULTS="$(ls -d results/*/ 2>/dev/null | sort | tail -n1)"
RESULTS="${RESULTS%/}"
[ -f "$RESULTS/halves.json" ] || { echo "ERROR: no halves.json in '$RESULTS'" >&2; exit 1; }

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
CANDS="classpath-candidates.tsv"
LOG="classpath-log.tsv"
REPORTS="$RESULTS/classpath"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first" >&2; exit 1; }
[ -f "$CANDS" ] || { echo "ERROR: $CANDS not found — run ./step4a_classpath_order.sh first" >&2; exit 1; }
git ls-files --error-unmatch "$CANDS" >/dev/null 2>&1 \
  || echo "WARNING: $CANDS is not committed; commit it so the order is on record before building." >&2
command -v java >/dev/null || { echo "ERROR: no java on PATH" >&2; exit 1; }
mkdir -p "$REPORTS" "$WORK"
[ -f "$LOG" ] || printf 'order\tfull_name\tstatus\treason\tjdk\tutc\n' > "$LOG"

JDK="$(java -version 2>&1 | head -n1 | sed -E 's/.*version "([^"]+)".*/\1/')"

# The Gradle init script: a printCp task in every Java project, printing its main runtime
# classpath once its classes are built.
INIT="$WORK/printcp.gradle"
cat > "$INIT" <<'EOF'
allprojects {
  plugins.withType(JavaPlugin) {
    tasks.create('printCp') {
      dependsOn 'classes'
      doLast { println 'CP=' + project.sourceSets.main.runtimeClasspath.asPath }
    }
  }
}
EOF

half_of() {  # the half halves.json assigns to a github owner/name ("" if none)
  "$PY" - "$RESULTS/halves.json" "$1" <<'EOF'
import json, sys
halves = json.load(open(sys.argv[1]))["halves"]
want = sys.argv[2].lower()
for url, half in halves.items():
    name = url.split("github.com/", 1)[-1].removesuffix(".git").lower()
    if name == want:
        print(half)
        break
EOF
}

log() {  # order full_name status reason
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$JDK" "$(date -u +%FT%TZ)" >> "$ROOT/$LOG"
  echo "  -> $3${4:+: $4}"
}

n_ok() { awk -F'\t' 'NR>1 && $3=="ok"' "$LOG" | wc -l; }

if [ -n "$ONLY" ]; then
  grep -q -P "^\d+\t\Q$ONLY\E\t" "$CANDS" || { echo "ERROR: $ONLY is not in $CANDS" >&2; exit 1; }
  awk -F'\t' -v r="$ONLY" '$2!=r' "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "=== STEP 4b: classpath validation of $RESULTS (target $TARGET, JDK $JDK, work $WORK) ==="
echo "    $(n_ok) already validated."

# The candidates are read on fd 3, so a build that reads stdin cannot consume them.
while IFS=$'\t' read -r ORDER REPO COMMIT TIER GODS <&3; do
  case "$ORDER" in ''|'#'*|order) continue ;; esac
  [ -n "$ONLY" ] && [ "$REPO" != "$ONLY" ] && continue
  [ -z "$ONLY" ] && [ "$(n_ok)" -ge "$TARGET" ] && break
  awk -F'\t' -v r="$REPO" 'NR>1 && $2==r {f=1} END {exit !f}' "$LOG" && continue

  NAME="${REPO//\//__}"
  W="$WORK/$NAME"
  BLOG="$WORK/$NAME.build.log"
  echo
  echo "--- [$ORDER] $REPO @ ${COMMIT:0:10} ($TIER, $GODS GodClass)"

  HALF="$(half_of "$REPO")"
  if [ "$HALF" != "explore" ]; then
    echo "ERROR: halves.json puts $REPO in '${HALF:-no half}', not explore; refusing to build it." >&2
    exit 1
  fi

  if [ ! -d "$W/.git" ] || [ "$(git -C "$W" rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
    rm -rf "$W"
    if ! { git init -q "$W" && git -C "$W" fetch -q --depth 1 "https://github.com/$REPO.git" "$COMMIT" \
           && git -C "$W" checkout -q FETCH_HEAD; } > "$BLOG" 2>&1; then
      log "$ORDER" "$REPO" fail "clone at $COMMIT failed"; continue
    fi
  fi

  if grep -qsE "com\.android\.(application|library)|com\.android\.tools\.build" \
       "$W"/build.gradle* "$W"/*/build.gradle* "$W"/settings.gradle* 2>/dev/null; then
    log "$ORDER" "$REPO" skip "Android project (no SDK)"; continue
  fi

  CP="$W/all-cp.txt"
  rm -f "$CP"
  if [ -f "$W/pom.xml" ]; then
    echo "  maven build (log: $BLOG)"
    if ! (cd "$W" && timeout "$TIMEOUT" mvn -B -q -Dmaven.repo.local="$WORK/m2" \
            -Dmaven.test.skip=true -Dmaven.javadoc.skip=true -Dgpg.skip=true \
            install dependency:build-classpath -Dmdep.outputFile=cp.txt) >> "$BLOG" 2>&1; then
      log "$ORDER" "$REPO" fail "maven build failed or timed out ($TIMEOUT)"; continue
    fi
    find "$W" -name cp.txt -not -path '*/node_modules/*' -exec cat {} + | tr ':' '\n' | sed '/^$/d' | sort -u > "$CP"
  elif ls "$W"/build.gradle* >/dev/null 2>&1 || ls "$W"/settings.gradle* >/dev/null 2>&1; then
    if [ ! -f "$W/gradlew" ]; then
      log "$ORDER" "$REPO" skip "Gradle without a wrapper"; continue
    fi
    chmod +x "$W/gradlew"
    echo "  gradle build (log: $BLOG)"
    if ! (cd "$W" && timeout "$TIMEOUT" ./gradlew --no-daemon -q -I "$INIT" printCp) > "$W/printcp.out" 2>> "$BLOG"; then
      cat "$W/printcp.out" >> "$BLOG"
      log "$ORDER" "$REPO" fail "gradle build failed or timed out ($TIMEOUT)"; continue
    fi
    grep '^CP=' "$W/printcp.out" | cut -c4- | tr ':' '\n' | sed '/^$/d' | sort -u > "$CP"
  else
    log "$ORDER" "$REPO" skip "no Maven or Gradle build"; continue
  fi

  if [ ! -s "$CP" ]; then
    log "$ORDER" "$REPO" fail "build produced an empty classpath"; continue
  fi

  echo "  classpath-check ($(wc -l < "$CP") classpath entries)"
  if "$PY" -m complexity_concentration_study.cli classpath-check --repo "$W" --url "$REPO" \
       --classpath-file "$CP" --out "$REPORTS/$NAME.json" >> "$BLOG" 2>&1 && [ -s "$REPORTS/$NAME.json" ]; then
    log "$ORDER" "$REPO" ok "$REPORTS/$NAME.json"
  else
    log "$ORDER" "$REPO" fail "classpath-check failed (see $BLOG)"
  fi
done 3< "$CANDS"

echo
echo "=== STEP 4b: $(n_ok) of $TARGET validated; every attempt is in $LOG. ==="
if [ "$(n_ok)" -ge "$TARGET" ]; then
  echo "Next: commit $LOG, then ./step4c_reanalyse.sh --results $RESULTS"
else
  echo "Fewer than $TARGET built: retry failures under another JDK with --only, or report the shortfall."
fi
