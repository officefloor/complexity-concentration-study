#!/usr/bin/env bash
#
# Step 6b — the author's blind reading, by hand, then a check that it is complete.
#
#   ./step6b_fp_author_reading.sh
#
# Read each unit in paper/data/fp_author_list.md (local copies in paper/data/fp_sample/) under
# paper/data/fp_reading_protocol.md, and answer q1-q4 with true or false and a one-line note in
# paper/readings/fp_readings_author.json. Do this BEFORE step 6c, so the model's answers are not
# seen first. This script only reports progress; it fails until every unit is answered.
#
# Then ./step6c_fp_model_reading.sh.
set -euo pipefail
cd "$(dirname "$0")"

F=paper/readings/fp_readings_author.json
[ -f "$F" ] || { echo "ERROR: no $F — run ./step6a_fp_prepare.sh first" >&2; exit 1; }

echo "=== STEP 6b: the author's reading ($F) ==="
python3 - "$F" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
todo = [u for u, v in d.items() if not all(isinstance(v["author"].get(q), bool) for q in ("q1", "q2", "q3", "q4"))]
print(f"answered {len(d) - len(todo)} of {len(d)}")
if todo:
    print("not yet answered: " + " ".join(todo))
    sys.exit(1)
PY
echo
echo "=== STEP 6b complete. Next: ./step6c_fp_model_reading.sh ==="
