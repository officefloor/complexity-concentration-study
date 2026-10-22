#!/usr/bin/env python3
"""EXPLORATORY: what the relative rule's false positives are, on the confirm half of the main
run, two ways: every one of them characterised by the tool definitions' own component clauses,
and a blinded, seeded sample of them beside true positives for a reading of the source.

    paper/scripts/false_positives.py [--data paper/data] [--out paper/data/false_positives.json]
                                     [--n-fp 100] [--n-tp 100] [--per-repo 3] [--seed 12345]
                                     [--fetch]   [--readings 'paper/readings/fp_readings_*.json']

Population: every confirm Java repository carrying PMD GodClass; the Java class units (files)
the plan fits on; the primary signal cognitive_max; the relative rule at modified z >= 3.5 and
the explore-tuned absolute cutoff from data/main.json. Groups: TP (rule flags, PMD marks), FP
(rule flags, PMD does not), FN (PMD marks, rule does not), neither; and the absolute cutoff's
own extra flags for comparison.

A. The component breakdown, over EVERY unit of each group (nothing sampled): the share that
   passes PMD's size clause (WMC >= 47, the registered wmc47 definition), the share a coupling
   component marks (CK CBO >= 14 or PMD CouplingBetweenObjects), the share a cohesion component
   marks (CK TCC < 1/3 or LCOM* >= 0.8), the share with neither, the share whose most complex
   method reaches 15 on the harness's cognitive estimate (PMD's own method-level
   CognitiveComplexity threshold: a file holding one method PMD would flag as too complex),
   and the medians of the raw signal, lines and method count. A GodClass is WMC >= 47 AND ATFD > few AND TCC < 1/3, so an
   extra flag that passes the size clause failed on data access or cohesion, and one that does
   not was never a candidate on size. Shares carry a repository bootstrap interval.
B. The reading sample: --n-fp false positives and --n-tp true positives drawn with --seed,
   shuffled across repositories with at most --per-repo units from one repository, and written
   BLINDED to data/fp_reading_sheet.json (id, repository, commit, path, raw URL, the signal
   values; never PMD's verdict) with the key in data/fp_sample_key.json. --fetch downloads each
   file at its pinned commit from raw.githubusercontent.com into data/fp_sample/<id>.java.
   The reading protocol is in data/fp_reading_protocol.md (written here, so it is versioned with
   the sample it applies to). data/fp_units.json indexes every unit (id, repository, commit,
   path, group) so the readings can be read without the sidecar; build.sh packs it beside them.
   scripts/fp_reading.py prepares the author's reading and runs the model readers; its docstring
   sets out the randomisation and blinding end to end.
C. --readings merges every reader file (paper/readings/fp_readings_*.json, {id: {reader:
   {q1..q4, note}}}) with the key: category by group, and Cohen's kappa between readers on the
   units both read. A unit whose four answers are not all booleans is not yet read and is
   skipped. Reported as exploratory; the reading is a judgement.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import random
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import stats, BOOT  # noqa: E402

Z_CUT = 3.5
SIGNAL = "cognitive_max"
ORACLE = "pmd_GodClass"
COUPLED = ("ck_CBOhigh", "pmd_CouplingBetweenObjects")
COGNITIVE_METHOD_THRESHOLD = 15  # PMD CognitiveComplexity reportLevel; cognitive_max is the file's most complex method
LOW_COHESION = ("ck_TCClow", "ck_LCOM")
GROUPS = ("tp", "fp", "fn", "neither", "abs_fp")

PROTOCOL = """# Reading protocol for the false-positive sample

Each unit is one Java file the relative rule (modified z >= 3.5 on the file's maximum cognitive
complexity, fitted on its own repository) flagged. Some are classes PMD's GodClass also marks,
some are not; the reader is not told which. Read the whole file, then answer the four questions
with yes or no and give one sentence of evidence for each. The category follows from the answers
by the fixed mapping below; do not pick the category first.

Q1 Single algorithm. Is the method carrying the file's highest cognitive complexity an
   implementation of one algorithm or procedure over the class's own inputs and state (a parser,
   encoder/decoder, matcher, solver, layout or rendering pass, protocol or state machine, numeric
   routine), as opposed to a sequence of calls into other objects?
Q2 One responsibility. Can the class be described in one sentence without "and" joining
   unrelated concerns? (Yes = one responsibility.)
Q3 Foreign data. Does the class mostly work on other objects' data: chains of getters on other
   classes, copying between objects, deciding on the basis of other objects' fields?
Q4 Dispatch table. Is the complexity mainly one large switch or if-else chain over cases
   (opcodes, token kinds, message types, enum values), each case short?

Reading conventions (added 2026-10-21, after the author had read 13 units, before any model
reading; they settle what the questions leave open and change no question or mapping row):
   Q1 Yes if the method uses the values it holds or receives to compute and return a value (or
      its own state); no if it mainly forwards values to other objects' method calls, deciding
      which to call and in what order.
   Q2 Judge the class's cohesion: yes if all its methods contribute to one cohesive, related
      concept; no if they serve two or more unrelated concepts.
   Q3 Yes if the class mainly holds behaviour that should live in the classes it references:
      getter chains of depth 2 or more, copying fields between objects, deciding on another
      behaviour-bearing object's fields. Plain data holders (DTOs, value objects, syntax trees)
      have no behaviour to move, so using them is not foreign data.
   Q4 Yes if the complexity is mainly one switch or if-else chain that separates behaviour by
      the kinds of one controlling value (enum, opcode, message type, instanceof over one
      variable), each case short. Separate conditions guarding calls or early returns are not a
      table.

Mapping:
   LEAF       Q1 yes, Q2 yes, Q3 no          complexity that belongs to the algorithm the class computes
   GATHERER   Q2 no, or Q3 yes               a class that gathers responsibilities or others' data
   TABLE      Q4 yes and Q2 yes and Q3 no    a dispatch or lookup table; complex by count, not by logic
   OTHER      anything else                  say what in the evidence (generated code, a test, a
                                             fixture, an unreadable file)
Apply the rows in order; the first that matches is the category. Record also, in `note`, the
name of the most complex method and what it does, in one line.
"""


def units_of(data: dict) -> list[dict]:
    rows = {r["repo"]: r for r in data["rows"]}
    cut = float(data["cuts"][f"class:{ORACLE}"][SIGNAL][0])
    out = []
    for repo, rec in data["class"].items():
        d = rec.get("dist")
        if not d or rows[repo]["half"] != "confirm" or not d.get("raw") or "units" not in d:
            continue
        god = set(d["god"])
        members = {o: set(ks) for o, ks in (d.get("members") or {}).items()}
        aux = d.get("aux") or {}
        row = rows[repo]
        for k, (path, x, z) in enumerate(zip(d["units"], d["raw"], d["z"])):
            rel, god_k, ab = z >= Z_CUT, k in god, x >= cut
            group = "tp" if rel and god_k else "fp" if rel else "fn" if god_k else "neither"
            u = {"repo": repo, "full_name": row["full_name"], "commit": row["commit"], "path": path,
                 "raw": x, "z": z, "god": god_k, "rel": rel, "abs": ab, "group": group,
                 "abs_fp": ab and not god_k,
                 "wmc47": k in members.get("wmc47", ()),
                 "coupled": any(k in members.get(o, ()) for o in COUPLED),
                 "low_cohesion": any(k in members.get(o, ()) for o in LOW_COHESION),
                 "large_class": k in members.get("ck_LargeClass", ()),
                 "decor_blob": k in members.get("decor_blob", ()),
                 "nloc_sum": (aux.get("nloc_sum") or [None] * (k + 1))[k],
                 "nom": (aux.get("nom") or [None] * (k + 1))[k]}
            out.append(u)
    return out, cut


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    return None if not xs else (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)


SHARES = (("wmc47", lambda u: u["wmc47"]), ("coupled", lambda u: u["coupled"]),
          ("cognitive15", lambda u: u["raw"] >= COGNITIVE_METHOD_THRESHOLD),
          ("low_cohesion", lambda u: u["low_cohesion"]),
          ("wmc47_and_coupled", lambda u: u["wmc47"] and u["coupled"]),
          ("neither_coupled_nor_low_cohesion", lambda u: not u["coupled"] and not u["low_cohesion"]),
          ("none_of_three", lambda u: not u["wmc47"] and not u["coupled"] and not u["low_cohesion"]),
          ("large_class", lambda u: u["large_class"]), ("decor_blob", lambda u: u["decor_blob"]))


def breakdown(units: list[dict]) -> dict:
    """Per group, the shares over every unit, with a repository bootstrap: each repository is
    reduced to its (hits, units) counts per group and share first, so a resample sums counts."""
    counts: dict = {}
    for u in units:
        c = counts.setdefault(u["repo"], {})
        for g in GROUPS:
            if (u["abs_fp"] if g == "abs_fp" else u["group"] == g):
                cg = c.setdefault(g, {"n": 0, **{k: 0 for k, _ in SHARES}})
                cg["n"] += 1
                for k, fn in SHARES:
                    cg[k] += bool(fn(u))
    items = list(counts.values())
    out = {}
    for g in GROUPS:
        us = [u for u in units if (u["abs_fp"] if g == "abs_fp" else u["group"] == g)]
        res = {"n": len(us), "n_repos": sum(1 for c in items if g in c),
               "median_raw": median(u["raw"] for u in us), "median_nloc": median(u["nloc_sum"] for u in us),
               "median_nom": median(u["nom"] for u in us), "shares": {}}
        for key, _ in SHARES:
            def share(its, g=g, key=key):
                n = sum(c[g]["n"] for c in its if g in c)
                k = sum(c[g][key] for c in its if g in c)
                return k / n if n else None
            res["shares"][key] = {"rate": share(items), "count": sum(c[g][key] for c in items if g in c),
                                  "ci": stats.bootstrap_paired(items, share, **BOOT)}
        out[g] = res
    return out


def draw_sample(units, n_fp, n_tp, per_repo, seed):
    rnd = random.Random(seed)
    picked = []
    for group, n in (("fp", n_fp), ("tp", n_tp)):
        pool = [u for u in units if u["group"] == group]
        rnd.shuffle(pool)
        per: dict = {}
        for u in pool:
            if len([x for x in picked if x["group"] == group]) >= n:
                break
            if per.get(u["repo"], 0) >= per_repo:
                continue
            per[u["repo"]] = per.get(u["repo"], 0) + 1
            picked.append(u)
    rnd.shuffle(picked)
    sheet, key = [], {}
    for i, u in enumerate(picked, 1):
        uid = f"u{i:03d}"
        sheet.append({"id": uid, "repository": u["full_name"], "commit": u["commit"], "path": u["path"],
                      "url": f"https://github.com/{u['full_name']}/blob/{u['commit']}/{u['path']}",
                      "raw_url": f"https://raw.githubusercontent.com/{u['full_name']}/{u['commit']}/{urllib.parse.quote(u['path'])}",
                      "cognitive_max": u["raw"], "modified_z": u["z"], "nloc": u["nloc_sum"], "methods": u["nom"]})
        key[uid] = {"group": u["group"], "pmd_god_class": u["god"], "wmc47": u["wmc47"], "coupled": u["coupled"],
                    "low_cohesion": u["low_cohesion"], "repository": u["full_name"], "path": u["path"]}
    return sheet, key


def fetch(sheet, folder):
    os.makedirs(folder, exist_ok=True)
    ok = fail = 0
    for s in sheet:
        dest = os.path.join(folder, s["id"] + ".java")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            ok += 1
            continue
        try:
            with urllib.request.urlopen(s["raw_url"], timeout=60) as r:
                data = r.read()
            with open(dest, "wb") as fh:
                fh.write(data)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  ! {s['id']} {s['raw_url']}: {e}", file=sys.stderr)
    print(f"fetched {ok} files into {folder}, {fail} failed")


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa over (label_a, label_b) pairs."""
    n = len(pairs)
    if n == 0:
        return None
    cats = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def category_of(ans: dict) -> str:
    """The protocol's fixed mapping from the four answers, applied in order."""
    q1, q2, q3, q4 = (bool(ans.get(k)) for k in ("q1", "q2", "q3", "q4"))
    if q1 and q2 and not q3:
        return "LEAF"
    if (not q2) or q3:
        return "GATHERER"
    if q4 and q2 and not q3:
        return "TABLE"
    return "OTHER"


def answered(v: dict) -> bool:
    return all(isinstance(v.get(q), bool) for q in ("q1", "q2", "q3", "q4"))


def load_readings(pattern: str) -> tuple[dict, dict]:
    """Every reader file matching `pattern` merged into {id: {reader: answers}}, keeping only
    answered units; and {reader: units not yet answered}."""
    readings: dict = {}
    pending: dict = {}
    for f in sorted(glob.glob(pattern)):
        for uid, v in common.load_json(f).items():
            for r, a in v.items():
                if answered(a):
                    readings.setdefault(uid, {})[r] = dict(a)
                else:
                    pending[r] = pending.get(r, 0) + 1
    return readings, pending


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a, b], [c, d]]: the summed probability, under
    the fixed margins, of every table at most as likely as the observed one."""
    from math import comb
    n = a + b + c + d
    r1, c1 = a + b, a + c
    if n == 0 or r1 in (0, n) or c1 in (0, n):
        return 1.0

    def prob(x: int) -> float:
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    p0 = prob(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p0 * (1 + 1e-9)))


def merge_readings(readings: dict, key: dict) -> dict:
    """{reader: {group: {category: n}}}: each reader's category by group (derived from the
    answers by the protocol's mapping), each reader's yes-count on every question by group,
    and the agreement between every pair of readers on the units both read: on the category
    (Cohen's kappa) and on each question. For each reader, the separation of the two groups on
    each question and on each category is a two-sided Fisher exact p on the yes/no counts."""
    readers = sorted({r for v in readings.values() for r in v})
    for v in readings.values():
        for r in readers:
            if r in v:
                v[r]["category"] = category_of(v[r])
    out = {"readers": readers, "n_read": {r: sum(1 for v in readings.values() if r in v) for r in readers},
           "by_reader": {}, "questions_by_reader": {}, "separation_by_reader": {}, "agreement": {}}
    for r in readers:
        tab: dict = {}
        qtab: dict = {}
        for uid, v in readings.items():
            if r not in v or uid not in key:
                continue
            g = key[uid]["group"]
            tab.setdefault(g, {})
            c = v[r]["category"]
            tab[g][c] = tab[g].get(c, 0) + 1
            qt = qtab.setdefault(g, {q: {"yes": 0, "n": 0} for q in ("q1", "q2", "q3", "q4")})
            for q in qt:
                qt[q]["n"] += 1
                qt[q]["yes"] += 1 if bool(v[r].get(q)) else 0
        out["by_reader"][r] = tab
        out["questions_by_reader"][r] = qtab
        sep: dict = {}
        if "fp" in qtab and "tp" in qtab:
            for q in ("q1", "q2", "q3", "q4"):
                x, y = qtab["fp"][q], qtab["tp"][q]
                sep[q] = {"fp_yes": x["yes"], "fp_n": x["n"], "tp_yes": y["yes"], "tp_n": y["n"],
                          "p": fisher_two_sided(x["yes"], x["n"] - x["yes"], y["yes"], y["n"] - y["yes"])}
            n_fp, n_tp = sum(tab["fp"].values()), sum(tab["tp"].values())
            for c in ("LEAF", "GATHERER", "TABLE", "OTHER"):
                a_, b_ = tab["fp"].get(c, 0), tab["tp"].get(c, 0)
                sep[c] = {"fp_yes": a_, "fp_n": n_fp, "tp_yes": b_, "tp_n": n_tp,
                          "p": fisher_two_sided(a_, n_fp - a_, b_, n_tp - b_)}
        out["separation_by_reader"][r] = sep
    for i, a in enumerate(readers):
        for b in readers[i + 1:]:
            both = [v for v in readings.values() if a in v and b in v]
            pairs = [(v[a]["category"], v[b]["category"]) for v in both]
            out["agreement"][f"{a}|{b}"] = {
                "n": len(pairs), "agree": sum(1 for x, y in pairs if x == y), "kappa": kappa(pairs),
                "questions": {q: {"agree": sum(1 for v in both if bool(v[a].get(q)) == bool(v[b].get(q))),
                                  "kappa": kappa([(str(bool(v[a].get(q))), str(bool(v[b].get(q)))) for v in both])}
                              for q in ("q1", "q2", "q3", "q4")}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=common.DATA)
    ap.add_argument("--out", default=os.path.join(common.DATA, "false_positives.json"))
    ap.add_argument("--n-fp", type=int, default=100)
    ap.add_argument("--n-tp", type=int, default=100)
    ap.add_argument("--per-repo", type=int, default=3)
    ap.add_argument("--seed", type=int, default=BOOT["seed"])
    ap.add_argument("--fetch", action="store_true", help="download the sampled files at their pinned commits")
    ap.add_argument("--readings", default=os.path.join(common.PAPER, "readings", "fp_readings_*.json"),
                    help="glob of the reader files")
    args = ap.parse_args(argv)
    data = common.load_json(os.path.join(args.data, "main.json"))
    units, cut = units_of(data)
    if not units:
        raise SystemExit("data/main.json carries no per-unit dist with units: re-run extract_main.py")
    p = print
    p(f"EXPLORATORY (not in PLAN.md): the relative rule's false positives on the confirm half, "
      f"{len(units)} Java class units in {len({u['repo'] for u in units})} repositories; absolute cutoff {cut:g}")
    bd = breakdown(units)
    for g in GROUPS:
        r = bd[g]
        p(f"   {g:8} n={r['n']:6} repos={r['n_repos']:3}  " + "  ".join(
            f"{k} {100 * v['rate']:.1f}%" for k, v in r["shares"].items() if v["rate"] is not None)
          + f"  median raw {r['median_raw']} nloc {r['median_nloc']} nom {r['median_nom']}")
    sheet, key = draw_sample(units, args.n_fp, args.n_tp, args.per_repo, args.seed)
    common.dump_json(sheet, os.path.join(args.data, "fp_reading_sheet.json"))
    common.dump_json(key, os.path.join(args.data, "fp_sample_key.json"))
    common.dump_json({s["id"]: {"repository": s["repository"], "commit": s["commit"], "path": s["path"],
                                "url": s["url"], "group": key[s["id"]]["group"],
                                "pmd_god_class": key[s["id"]]["pmd_god_class"]} for s in sheet},
                     os.path.join(args.data, "fp_units.json"))
    with open(os.path.join(args.data, "fp_reading_protocol.md"), "w") as fh:
        fh.write(PROTOCOL)
    p(f"\nsample: {sum(1 for k in key.values() if k['group'] == 'fp')} false positives and "
      f"{sum(1 for k in key.values() if k['group'] == 'tp')} true positives from "
      f"{len({k['repository'] for k in key.values()})} repositories, seed {args.seed}, at most {args.per_repo} per repository; "
      f"blinded sheet data/fp_reading_sheet.json, key data/fp_sample_key.json, protocol data/fp_reading_protocol.md")
    if args.fetch:
        fetch(sheet, os.path.join(args.data, "fp_sample"))
    out = {"exploratory": True, "signal": SIGNAL, "oracle": ORACLE, "z_cut": Z_CUT, "absolute_cut": cut,
           "computed_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "n_units": len(units), "n_repos": len({u["repo"] for u in units}), "bootstrap": BOOT,
           "breakdown": bd, "sample": {"n_fp": args.n_fp, "n_tp": args.n_tp, "per_repo": args.per_repo,
                                       "seed": args.seed, "n": len(sheet)}, "readings": None}
    readings, pending = load_readings(args.readings)
    if readings:
        out["readings"] = merge_readings(readings, key)
        out["readings"]["n_pending"] = pending
        p(f"\nreadings: {out['readings']['n_read']}, not yet answered {pending}")
        for r, tab in out["readings"]["by_reader"].items():
            p(f"   {r}: " + "; ".join(f"{g}: " + ", ".join(f"{c} {n}" for c, n in sorted(cs.items())) for g, cs in tab.items()))
        for r, qtab in out["readings"]["questions_by_reader"].items():
            p(f"   {r} yes by question: " + "; ".join(
                f"{g}: " + ", ".join(f"{q} {x['yes']}/{x['n']}" for q, x in qt.items()) for g, qt in qtab.items()))
        for r, sep in out["readings"]["separation_by_reader"].items():
            p(f"   {r} fp vs tp, Fisher two-sided p: " + ", ".join(
                f"{k} {x['fp_yes']}/{x['fp_n']} vs {x['tp_yes']}/{x['tp_n']} p={x['p']:.3f}" for k, x in sep.items()))
        for pair, a in out["readings"]["agreement"].items():
            p(f"   agreement {pair}: category {a['agree']}/{a['n']} kappa {a['kappa']}; " +
              "; ".join(f"{q} {x['agree']}/{a['n']} kappa {x['kappa']}" for q, x in a["questions"].items()))
    common.dump_json(out, args.out)
    p(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
