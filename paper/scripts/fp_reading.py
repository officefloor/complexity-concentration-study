#!/usr/bin/env python3
"""EXPLORATORY: prepare, run and collect the reading of the false-positive sample that
false_positives.py draws. The readings are judgements no script can reproduce, so they are the
only inputs kept as recorded: under paper/readings/, committed, and packed into the ancillary
bundle by build.sh. Everything else here is regenerated.

    paper/scripts/fp_reading.py prepare [--n-author-fp 20] [--n-author-tp 20] [--seed 12345]
    paper/scripts/fp_reading.py run-model [--model claude-fable-5-1] [--batches 0,1,...] [--jobs 4]
    paper/scripts/fp_reading.py collect-model

Randomisation and blinding, end to end:
  1. false_positives.draw_sample: each group (FP, TP) is shuffled with random.Random(--seed),
     taken in that order up to its size with at most --per-repo units per repository, then the
     two groups are shuffled TOGETHER with the same generator, and ids u001.. are assigned in the
     shuffled order. An id, and its position in any list, carries no information on its group.
  2. The PMD verdict is only in data/fp_sample_key.json; no reader is shown it, the sheet or the
     key. What a reader sees is listed below for each reader.
  3. The author's units (prepare): random.Random(--seed).sample of --n-author-fp false positives,
     then of --n-author-tp true positives, from the sheet in id order; listed by id, i.e. in the
     random order of step 1. data/fp_author_list.md shows id, repository, path, the local copy,
     the pinned GitHub link and the method the harness measured as most complex; no verdict, no
     complexity values. The author knows only the split (20 and 20), not which unit is which.
  4. The model readers (run-model): the 200 units in id order, cut into batches of 20. Each batch
     is read by its own `claude -p` session, run in a fresh temporary directory that holds only
     protocol.md, batch.md (id, path in its repository, local file name) and files/<id>.java.
     The session has only the Read tool, permission mode dontAsk (anything outside the directory
     is denied, not asked), no settings, CLAUDE.md, memory, MCP servers or session persistence
     (--safe-mode --setting-sources "" --strict-mcp-config --no-session-persistence), and must
     answer in the JSON schema ANSWER_SCHEMA. Each run's full result, the command and the CLI
     version go to readings/fp_model_runs/batch_<k>.json, including any permission denials, with
     the git commit of the reading scripts (SCRIPTS); run-model refuses to start while any of them
     differs from that commit, so a record names the committed code that produced it.
  5. collect-model turns those runs into readings/fp_readings_model.json; false_positives.py
     merges every readings/fp_readings_*.json with the key and applies the protocol's mapping,
     so no reader picks a category.

prepare (after false_positives.py --fetch; streams the main run's per-unit sidecar, minutes)
writes data/fp_sample_methods.json (per unit, the method of highest cognitive complexity, ties
by CC), data/fp_author_subset.json, data/fp_author_list.md, and readings/fp_readings_author.json
with a blank answer per author unit, only if that file is absent (it holds the author's
decisions and is never overwritten).

Reader files are {id: {reader: {q1, q2, q3, q4, note, evidence?}}}.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import BOOT  # noqa: E402

READINGS = os.path.join(common.PAPER, "readings")
RUNS = os.path.join(READINGS, "fp_model_runs")
BATCH = 20
QS = ("q1", "q2", "q3", "q4")
SCRIPTS = [os.path.join("paper", "scripts", f) for f in ("fp_reading.py", "false_positives.py", "common.py")]

READER_PROMPT = """You are a blind code reader in an empirical software-engineering study. Work only from the files in the current directory.

1. Read protocol.md first.
2. Read batch.md. It names {n} Java files by id, their path in their repository, and their local copy under files/.
3. For every file: read the whole file (use Read with offset and limit for files over 2000 lines, do not skip the tail). Identify the method with the highest cognitive complexity (the one with the most and deepest nested branches, loops and boolean chains) and name it. Then answer Q1, Q2, Q3 and Q4 from the protocol as true or false, each with one sentence of evidence from the file, and write a one-line note of the form "methodName: what it does". Do NOT derive or state the category; the mapping is applied later.
4. Blindness: do not try to read anything outside the current directory and do not try to find out anything about these classes beyond the file itself.
5. Answer with one entry per id of the batch, all {n} of them, in the required JSON form.
"""

ANSWER_SCHEMA = {
    "type": "object", "required": ["readings"],
    "properties": {"readings": {"type": "array", "items": {
        "type": "object", "required": ["id", "q1", "q2", "q3", "q4", "evidence", "note"],
        "properties": {"id": {"type": "string"}, **{q: {"type": "boolean"} for q in QS},
                       "evidence": {"type": "object", "required": list(QS),
                                    "properties": {q: {"type": "string"} for q in QS}},
                       "note": {"type": "string"}}}}}}


def measured_methods(sheet: list[dict]) -> dict:
    rows = {r["full_name"]: r["repo"] for r in common.load_json(os.path.join(common.DATA, "main.json"))["rows"]}
    want: dict = {}
    for s in sheet:
        want.setdefault(rows[s["repository"]], {}).setdefault(s["path"], []).append(s["id"])
    out: dict = {}
    for d in common.iter_sidecar(common.MAIN_RESULTS, keep=set(want)):
        m = d["method"]
        cog, cc, nloc = (m["values"][k] for k in ("cognitive", "cc", "nloc"))
        paths = want[d["repo"]]
        for i, u in enumerate(m["units"]):
            path, _, rest = u.partition("::")
            if path not in paths:
                continue
            name, _, line = rest.rpartition("@")
            for uid in paths[path]:
                best = out.get(uid)
                if best is None or cog[i] > best["cognitive"] or (cog[i] == best["cognitive"] and cc[i] > best["cc"]):
                    out[uid] = {"method": name, "line": int(line) if line.isdigit() else line,
                                "cognitive": cog[i], "cc": cc[i], "nloc": nloc[i]}
    return dict(sorted(out.items()))


def author_subset(sheet, key, n_fp, n_tp, seed) -> list[str]:
    rnd = random.Random(seed)
    ids = [s["id"] for s in sheet]
    fp = [i for i in ids if key[i]["group"] == "fp"]
    tp = [i for i in ids if key[i]["group"] == "tp"]
    return sorted(rnd.sample(fp, n_fp) + rnd.sample(tp, n_tp))


def author_list(sheet, ids, methods, n_fp, n_tp, seed) -> str:
    meta = {s["id"]: s for s in sheet}
    rel = os.path.relpath(common.DATA, common.PAPER)
    lines = [f"# Your {len(ids)} units (blind: no PMD verdict here; {n_fp} false positives and {n_tp} true positives, seed {seed})", "",
             f"Answer q1-q4 with true/false in readings/fp_readings_author.json and a one-line note naming the most complex method and what it does. Protocol: {rel}/fp_reading_protocol.md", "",
             "| id | repository | file | local copy | GitHub |", "|---|---|---|---|---|"]
    for uid in ids:
        s = meta[uid]
        lines.append(f"| {uid} | {s['repository']} | {s['path']} | {rel}/fp_sample/{uid}.java | {s['url']} |")
    lines += ["", "## Most complex method per file (measured by the harness; no values shown, read blind)", "",
              "| id | file | most complex method (line) |", "|---|---|---|"]
    for uid in ids:
        b = methods.get(uid, {})
        lines.append(f"| {uid} | {meta[uid]['path'].split('/')[-1]} | {b.get('method', '?')} (line {b.get('line', '?')}) |")
    return "\n".join(lines) + "\n"


def prepare(args) -> int:
    sheet = common.load_json(os.path.join(common.DATA, "fp_reading_sheet.json"))
    key = common.load_json(os.path.join(common.DATA, "fp_sample_key.json"))
    methods = measured_methods(sheet)
    common.dump_json(methods, os.path.join(common.DATA, "fp_sample_methods.json"))
    print(f"measured most complex method for {len(methods)} of {len(sheet)} units")
    ids = author_subset(sheet, key, args.n_author_fp, args.n_author_tp, args.seed)
    common.dump_json({"seed": args.seed, "n_fp": args.n_author_fp, "n_tp": args.n_author_tp, "ids": ids},
                     os.path.join(common.DATA, "fp_author_subset.json"))
    with open(os.path.join(common.DATA, "fp_author_list.md"), "w") as fh:
        fh.write(author_list(sheet, ids, methods, args.n_author_fp, args.n_author_tp, args.seed))
    template = os.path.join(READINGS, "fp_readings_author.json")
    if os.path.exists(template):
        print(f"kept {template} (holds the author's decisions)")
    else:
        os.makedirs(READINGS, exist_ok=True)
        common.dump_json({uid: {"author": {**{q: None for q in QS}, "note": ""}} for uid in ids}, template)
        print(f"wrote blank {template}")
    print(f"author subset {len(ids)} units")
    return 0


def batches(sheet: list[dict]) -> list[list[dict]]:
    return [sheet[k:k + BATCH] for k in range(0, len(sheet), BATCH)]


def scripts_commit() -> str:
    """The commit the reading scripts are at; refuses if any is uncommitted or modified."""
    git = ["git", "-C", common.ROOT]
    dirty = subprocess.run(git + ["status", "--porcelain", "--"] + SCRIPTS, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(f"commit the reading scripts before a run:\n{dirty}")
    return subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def run_batch(b: int, items: list[dict], model: str, version: str, commit: str) -> str:
    """One blind `claude -p` session over one batch, in a directory holding only what it may read."""
    work = tempfile.mkdtemp(prefix=f"fp_reader_{b}_")
    try:
        shutil.copy(os.path.join(common.DATA, "fp_reading_protocol.md"), os.path.join(work, "protocol.md"))
        os.makedirs(os.path.join(work, "files"))
        for s in items:
            shutil.copy(os.path.join(common.DATA, "fp_sample", s["id"] + ".java"), os.path.join(work, "files", s["id"] + ".java"))
        with open(os.path.join(work, "batch.md"), "w") as fh:
            fh.write("\n".join([f"# Batch {b}: {len(items)} Java files to read under the protocol\n",
                                "| id | class (path in its repository) | local file |", "|---|---|---|"]
                               + [f"| {s['id']} | {s['path']} | files/{s['id']}.java |" for s in items]) + "\n")
        prompt = READER_PROMPT.format(n=len(items))
        cmd = ["claude", "-p", prompt, "--model", model, "--tools", "Read", "--permission-mode", "dontAsk",
               "--safe-mode", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
               "--output-format", "json", "--json-schema", json.dumps(ANSWER_SCHEMA)]
        started = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result = {"is_error": True, "stdout": proc.stdout, "stderr": proc.stderr}
        record = {"batch": b, "ids": [s["id"] for s in items], "model": model, "claude_version": version,
                  "scripts_commit": commit, "scripts": SCRIPTS,
                  "started_utc": started, "returncode": proc.returncode,
                  "command": ["claude", "-p", "<prompt>"] + cmd[3:], "prompt": prompt,
                  "batch_md": open(os.path.join(work, "batch.md")).read(), "result": result}
        os.makedirs(RUNS, exist_ok=True)
        common.dump_json(record, os.path.join(RUNS, f"batch_{b}.json"))
        denied = result.get("permission_denials") or []
        return (f"batch {b}: {'ERROR' if result.get('is_error') or proc.returncode else 'ok'}, "
                f"{len((result.get('structured_output') or {}).get('readings', []))} readings, "
                f"{len(denied)} denied tool calls, ${result.get('total_cost_usd', 0):.2f}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_model(args) -> int:
    sheet = common.load_json(os.path.join(common.DATA, "fp_reading_sheet.json"))
    bs = batches(sheet)
    todo = [int(x) for x in args.batches.split(",")] if args.batches else list(range(len(bs)))
    commit = scripts_commit()
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        for line in ex.map(lambda b: run_batch(b, bs[b], args.model, version, commit), todo):
            print(line, flush=True)
    return 0


def collect_model(args) -> int:
    sheet = common.load_json(os.path.join(common.DATA, "fp_reading_sheet.json"))
    merged = {}
    for b, items in enumerate(batches(sheet)):
        path = os.path.join(RUNS, f"batch_{b}.json")
        if not os.path.exists(path):
            raise SystemExit(f"{path} missing: run run-model --batches {b}")
        rec = common.load_json(path)
        want = [s["id"] for s in items]
        if rec["ids"] != want:
            raise SystemExit(f"{path}: its ids are not batch {b} of the current sheet")
        got = {r["id"]: r for r in (rec["result"].get("structured_output") or {}).get("readings", [])}
        if sorted(got) != sorted(want):
            raise SystemExit(f"{path}: answered {sorted(got)} for {want}: re-run run-model --batches {b}")
        for uid in want:
            r = got[uid]
            merged[uid] = {"model": {**{q: r[q] for q in QS}, "evidence": r["evidence"], "note": r["note"]}}
    out = os.path.join(READINGS, "fp_readings_model.json")
    common.dump_json(dict(sorted(merged.items())), out)
    print(f"wrote {out}: {len(merged)} units")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--n-author-fp", type=int, default=20)
    p.add_argument("--n-author-tp", type=int, default=20)
    p.add_argument("--seed", type=int, default=BOOT["seed"])
    r = sub.add_parser("run-model")
    r.add_argument("--model", default="claude-fable-5-1")
    r.add_argument("--batches", help="comma-separated batch numbers (default: all)")
    r.add_argument("--jobs", type=int, default=4)
    sub.add_parser("collect-model")
    args = ap.parse_args(argv)
    return {"prepare": prepare, "run-model": run_model, "collect-model": collect_model}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
