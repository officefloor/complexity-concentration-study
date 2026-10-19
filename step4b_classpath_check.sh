#!/usr/bin/env bash
#
# Step 4b — the classpath validation (PLAN.md step 4; README, 'The classpath validation
# sub-study'): build explore-half Java repositories and report how many PMD GodClass verdicts
# flip when PMD is given the built classpath.
#
#   ./step4b_classpath_check.sh [--results results/<date>] [--target 10] [--work DIR]
#                               [--timeout 45m] [--jdks JAVA_HOME:JAVA_HOME:...]
#
# Works down classpath-candidates.tsv (./step4a_classpath_order.sh) in order until --target
# repositories have a report. For each: shallow-clone it at its sampled commit, build it with
# its own Maven or Gradle wrapper (tests skipped), trying each JDK of --jdks in order until one
# builds, collect the classpath, and run `classpath-check`, writing
# <results>/classpath/<owner>__<name>.json, which step 4c's analysis aggregates.
#
# The log, classpath-log.tsv, is only ever appended to, and only by this script. It opens each
# run with a `run` row (this script's commit, the target, the timeout and the JDKs found), then
# one row per attempt: `retry` when a build fails under one JDK and the next is tried, and one
# final row per repository, `ok`, `skip` or `fail`, with the reason and the JDK. Commit it at
# the end. If the log or the reports are wrong (a bug here), fix this script, commit the fix,
# delete classpath-log.tsv and <results>/classpath/, and run again: never edit either by hand.
#
# Resumable: a repository with a final row is not tried again, so re-running the same command
# after an interruption carries on; the interrupted repository starts over, under a new `run`
# row. The script refuses to run uncommitted, so every row is traceable to committed code.
#
# Guard: a repository is built only if halves.json puts it in the EXPLORE half. Confirm
# repositories are never cloned here.
#
# Needs Maven (for pom.xml projects), the JDKs, network. Gradle projects use their own
# ./gradlew. Maven artifacts go to <work>/m2, not ~/.m2.
#
# Decisions, made on 2026-10-19 AFTER the confirmatory analysis.json was written and read (the
# plan required this validation before confirm was read; it was skipped, so everything this
# step feeds is exploratory and reported as a deviation):
#   - Which repositories: classpath-candidates.tsv's fixed order (step 4a), first --target that
#     build. The plan says "at least ten"; ten is the default, chosen before any was built.
#   - What counts as building: the project's own build as sampled, with tests, javadoc and
#     signing skipped (-Dmaven.test.skip, -Dmaven.javadoc.skip, -Dgpg.skip; Gradle's `classes`
#     only). A build that needs any file edited, a dependency forced, or more than --timeout
#     (45m) under every JDK is a fail. Skipping test compilation can break a build that
#     consumes a test-jar; that is a fail too, not a reason to change the flags.
#   - JDKs: the projects target different Java versions (on the first attempt, Jenkins,
#     resilience4j and baritone required 21; Gradle 5 projects cannot run on 17), so each build
#     is tried under each JDK in a fixed order until one succeeds: 17 (the JDK the study's own
#     run used), then 21, 11 and 8. A JDK that is not installed is left out, and the `run` row
#     says which were found. Which JDK built a repository changes only how its classpath was
#     produced; PMD always runs on the default `java`, the JDK of the study's run, with and
#     without the classpath alike, so the flips come from the classpath alone.
#   - Skips, recorded but not counted: a build that fails for want of an Android SDK (none on
#     this machine; no JDK changes that, so it is not retried), Gradle without a wrapper (no
#     way to know which Gradle the project needs), and no Maven/Gradle build at the root.
#     Android is judged by the build failing for want of the SDK, not by the build files
#     mentioning Android: a project whose Android module is optional (e.g. Mindustry includes
#     it only when an SDK is found) builds its Java modules without one.
#   - Builds run with stdin from /dev/null: `timeout` puts the build in its own process group,
#     and a build that reads the terminal from there is stopped by the kernel, timer and all.
#   - The classpath: the union over modules of each module's main runtime classpath (Maven's
#     dependency:build-classpath per module; Gradle's sourceSets.main.runtimeClasspath), plus
#     the project's own compiled classes, which classpath-check adds itself. PMD sees the
#     study's own file list for the checkout either way, so only the classpath differs.
#   - Classpath entries that do not exist are dropped before classpath-check. PMD refuses a
#     whole classpath naming a missing jar, and Gradle's runtime classpath names the project's
#     own module jars (e.g. core/build/libs/core.jar), which only the `jar` task builds. The
#     classes in those jars are the modules' compiled classes, which classpath-check adds
#     itself, so nothing is lost. The number dropped is written to the build log.
#   - Maven uses <work>/m2 so the user's ~/.m2 is not filled with these projects' snapshots.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

RESULTS=""
TARGET=10
WORK="$HOME/cp-work"
TIMEOUT="45m"
JDKS="/usr/lib/jvm/java-17-openjdk-amd64:/usr/lib/jvm/java-21-openjdk-amd64:/usr/lib/jvm/java-11-openjdk-amd64:/usr/lib/jvm/java-8-openjdk-amd64"
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
    --jdks) JDKS="$2"; shift 2 ;;
    --jdks=*) JDKS="${1#*=}"; shift ;;
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
SELF="$(basename "$0")"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run ./step1_setup.sh first" >&2; exit 1; }
[ -f "$CANDS" ] || { echo "ERROR: $CANDS not found — run ./step4a_classpath_order.sh first" >&2; exit 1; }
command -v java >/dev/null || { echo "ERROR: no java on PATH (PMD runs on it)" >&2; exit 1; }

# Every row must be traceable to committed code and a committed order.
for f in "$SELF" "$CANDS"; do
  if ! git ls-files --error-unmatch "$f" >/dev/null 2>&1 || ! git diff --quiet HEAD -- "$f"; then
    echo "ERROR: $f is not committed as it stands; commit it before running." >&2
    exit 1
  fi
done
COMMIT_SELF="$(git rev-parse --short HEAD)"

# The JDKs found, in order, as "label=JAVA_HOME"; a missing one is reported, not an error.
jdk_version() { "$1/bin/java" -version 2>&1 | head -n1 | sed -E 's/.*version "([^"]+)".*/\1/'; }
FOUND=()
JDK_NOTE=""
IFS=':' read -r -a JDK_LIST <<< "$JDKS"
for jh in "${JDK_LIST[@]}"; do
  if [ -x "$jh/bin/java" ]; then
    FOUND+=("$(jdk_version "$jh")=$jh")
    JDK_NOTE+="${JDK_NOTE:+, }$(jdk_version "$jh")"
  else
    JDK_NOTE+="${JDK_NOTE:+, }$(basename "$jh") not installed"
  fi
done
[ ${#FOUND[@]} -gt 0 ] || { echo "ERROR: none of the JDKs in --jdks is installed: $JDKS" >&2; exit 1; }

mkdir -p "$REPORTS" "$WORK"
[ -f "$LOG" ] || printf 'order\tfull_name\tstatus\treason\tjdk\tutc\n' > "$LOG"

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

log() {  # order full_name status reason jdk
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$(date -u +%FT%TZ)" >> "$ROOT/$LOG"
  echo "  -> $3${4:+: $4}${5:+ (JDK $5)}"
}

n_ok() { awk -F'\t' 'NR>1 && $3=="ok"' "$LOG" | wc -l; }

done_already() {  # has this repository a final row?
  awk -F'\t' -v r="$1" 'NR>1 && $2==r && ($3=="ok" || $3=="skip" || $3=="fail") {f=1} END {exit !f}' "$LOG"
}

needs_android_sdk() {
  grep -qiE "SDK location not found|ANDROID_HOME|ANDROID_SDK_ROOT|define a valid SDK location" "$BLOG"
}

build() {  # tool JAVA_HOME: build $W with that JDK; 0 if it built and wrote the raw classpath to $CP
  local tool="$1" jh="$2"
  rm -f "$CP"
  if [ "$tool" = maven ]; then
    find "$W" -name cp.txt -not -path '*/node_modules/*' -delete
    (cd "$W" && JAVA_HOME="$jh" PATH="$jh/bin:$PATH" timeout "$TIMEOUT" mvn -B -q -Dmaven.repo.local="$WORK/m2" \
        -Dmaven.test.skip=true -Dmaven.javadoc.skip=true -Dgpg.skip=true \
        install dependency:build-classpath -Dmdep.outputFile=cp.txt) < /dev/null >> "$BLOG" 2>&1 || return 1
    find "$W" -name cp.txt -not -path '*/node_modules/*' -exec cat {} + | tr ':' '\n' | sed '/^$/d' | sort -u > "$CP"
  else
    if ! (cd "$W" && JAVA_HOME="$jh" PATH="$jh/bin:$PATH" timeout "$TIMEOUT" ./gradlew --no-daemon -q -I "$INIT" printCp) \
         < /dev/null > "$W/printcp.out" 2>> "$BLOG"; then
      cat "$W/printcp.out" >> "$BLOG"
      return 1
    fi
    grep '^CP=' "$W/printcp.out" | cut -c4- | tr ':' '\n' | sed '/^$/d' | sort -u > "$CP"
  fi
}

log - - run "$SELF at $COMMIT_SELF; target $TARGET; timeout $TIMEOUT; JDKs in order: $JDK_NOTE" -
echo "=== STEP 4b: classpath validation of $RESULTS (target $TARGET, JDKs: $JDK_NOTE, work $WORK) ==="
echo "    $(n_ok) already validated."

# The candidates are read on fd 3, so a build that reads stdin cannot consume them.
while IFS=$'\t' read -r ORDER REPO COMMIT TIER GODS <&3; do
  case "$ORDER" in ''|'#'*|order) continue ;; esac
  [ "$(n_ok)" -ge "$TARGET" ] && break
  done_already "$REPO" && continue

  NAME="${REPO//\//__}"
  W="$WORK/$NAME"
  BLOG="$WORK/$NAME.build.log"
  CP="$W/all-cp.txt"
  echo
  echo "--- [$ORDER] $REPO @ ${COMMIT:0:10} ($TIER, $GODS GodClass)"

  HALF="$(half_of "$REPO")"
  if [ "$HALF" != "explore" ]; then
    echo "ERROR: halves.json puts $REPO in '${HALF:-no half}', not explore; refusing to build it." >&2
    exit 1
  fi

  : > "$BLOG"
  if [ ! -d "$W/.git" ] || [ "$(git -C "$W" rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
    rm -rf "$W"
    if ! { git init -q "$W" && git -C "$W" fetch -q --depth 1 "https://github.com/$REPO.git" "$COMMIT" \
           && git -C "$W" checkout -q FETCH_HEAD; } >> "$BLOG" 2>&1; then
      log "$ORDER" "$REPO" fail "clone at $COMMIT failed" -; continue
    fi
  fi

  if [ -f "$W/pom.xml" ]; then
    TOOL=maven
  elif ls "$W"/build.gradle* >/dev/null 2>&1 || ls "$W"/settings.gradle* >/dev/null 2>&1; then
    if [ ! -f "$W/gradlew" ]; then
      log "$ORDER" "$REPO" skip "Gradle without a wrapper" -; continue
    fi
    chmod +x "$W/gradlew"
    TOOL=gradle
  else
    log "$ORDER" "$REPO" skip "no Maven or Gradle build" -; continue
  fi

  BUILT=""
  SDK=""
  TRIED=""
  for entry in "${FOUND[@]}"; do
    JV="${entry%%=*}"
    JH="${entry#*=}"
    echo "  $TOOL build, JDK $JV (log: $BLOG)"
    echo "=== $TOOL build, JDK $JV ($JH) ===" >> "$BLOG"
    if build "$TOOL" "$JH"; then
      BUILT="$JV"; break
    fi
    TRIED+="${TRIED:+, }$JV"
    if needs_android_sdk; then
      SDK=1; break
    fi
    log "$ORDER" "$REPO" retry "$TOOL build failed or timed out ($TIMEOUT)" "$JV"
  done
  if [ -n "$SDK" ]; then
    log "$ORDER" "$REPO" skip "$TOOL build needs an Android SDK" "$JV"; continue
  fi
  if [ -z "$BUILT" ]; then
    log "$ORDER" "$REPO" fail "$TOOL build failed under every JDK ($TRIED)" -; continue
  fi

  N_ALL=$(wc -l < "$CP")
  while IFS= read -r p; do if [ -e "$p" ]; then printf '%s\n' "$p"; fi; done < "$CP" > "$CP.tmp"
  mv "$CP.tmp" "$CP"
  echo "dropped $((N_ALL - $(wc -l < "$CP"))) of $N_ALL classpath entries that do not exist" >> "$BLOG"

  if [ ! -s "$CP" ]; then
    log "$ORDER" "$REPO" fail "build produced an empty classpath" "$BUILT"; continue
  fi

  echo "  classpath-check ($(wc -l < "$CP") classpath entries)"
  if "$PY" -m complexity_concentration_study.cli classpath-check --repo "$W" --url "$REPO" \
       --classpath-file "$CP" --out "$REPORTS/$NAME.json" >> "$BLOG" 2>&1 && [ -s "$REPORTS/$NAME.json" ]; then
    log "$ORDER" "$REPO" ok "$REPORTS/$NAME.json" "$BUILT"
  else
    log "$ORDER" "$REPO" fail "classpath-check failed (see $BLOG)" "$BUILT"
  fi
done 3< "$CANDS"

echo
echo "=== STEP 4b: $(n_ok) of $TARGET validated; every attempt is in $LOG. ==="
if [ "$(n_ok)" -ge "$TARGET" ]; then
  echo "Next: commit $LOG, then ./step4c_reanalyse.sh --results $RESULTS"
else
  echo "Fewer than $TARGET built from the whole candidate list: report the shortfall as it stands."
fi
