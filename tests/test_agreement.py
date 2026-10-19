"""The exploratory MLCQ agreement: tool definitions and the main study's rules against the
reviewers' Blob, on the reviewed class units, through analyse.Run's own code path."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import agreement, analyse, metrics

# 20 Java classes per repository. cognitive_max: 1..16, then 25 (absolute only), 60, 70, 80.
VALUES = list(range(1, 17)) + [25, 60, 70, 80]
REVIEWED = list(range(10, 20))
GODS = {"human_blob": [12, 18, 19], "human_blob_reviewed": REVIEWED,
        "pmd_GodClass": [19], "decor_blob": [18], "wmc47": [19]}


def _run_dir():
    d = tempfile.mkdtemp()
    rows, units = [], []
    for k in range(7):
        repo = f"https://github.com/o/r{k}"
        rows.append({"repo": repo, "full_name": f"o/r{k}", "lang": "java", "sample": "mlcq",
                     "half": "confirm" if k < 5 else "explore", "n_funcs": 10 ** 6,
                     "matrix": {"class": {"n_univ": 10 ** 6}, "method": {}}})
        gods = dict(GODS)
        if k == 6:
            gods.pop("pmd_GodClass")                   # PMD failed here: skipped, and said so
        units.append({"repo": repo, "class": {
            "units": [f"src/C{i}.java" for i in range(20)], "signals": ["cognitive_max"],
            "values": {"cognitive_max": VALUES}, "god_idx": gods}})
    json.dump(rows, open(os.path.join(d, "study.json"), "w"))
    with open(os.path.join(d, "study.units.jsonl"), "w") as fh:
        for u in units:
            fh.write(json.dumps(u) + "\n")
    reg = {"human_blob": {"origin": "human", "level": "class",
                          "conditional_on": "human_blob_reviewed"},
           "human_blob_reviewed": {"origin": "human", "level": "class", "kind": "component"},
           "pmd_GodClass": {"scope": "java"}, "decor_blob": {"scope": "java"},
           "wmc47": {"scope": "java"}}
    json.dump({"oracles": reg}, open(os.path.join(d, "oracles.json"), "w"))
    return d


def test_the_fixture_flags_what_the_hand_counts_assume():
    vmap = dict(enumerate(VALUES))
    assert metrics.ALGORITHMS["mad_z"](vmap) == {17, 18, 19}
    assert {i for i, v in vmap.items() if v >= agreement.CUT} == {16, 17, 18, 19}


def test_agreement_counts_on_the_reviewed_units_only():
    out = agreement.report(analyse.Run(_run_dir()), print_fn=lambda *a: None)
    assert [why for _, why in out["skipped"]] == ["no pmd_GodClass or cognitive_max"]
    a = out["all"]
    assert (a["n_repos"], a["n_reviewed_units"], a["n_blob"]) == (6, 60, 18)
    pmd = a["predictors"]["pmd_GodClass"]
    assert (pmd["tp"], pmd["fp"], pmd["fn"], pmd["tn"]) == (6, 0, 12, 42)
    rel = a["predictors"]["rel"]                       # flags 17, 18, 19; Blob 18, 19
    assert (rel["tp"], rel["fp"], rel["fn"], rel["tn"]) == (12, 6, 6, 36)
    g = a["groups"]
    assert (g["rel_not_pmd"]["blob"], g["rel_not_pmd"]["n"]) == (6, 12)          # {17, 18}
    assert (g["neither_rel_nor_pmd"]["blob"], g["neither_rel_nor_pmd"]["n"]) == (6, 42)  # 10..16
    assert (g["abs_not_pmd"]["blob"], g["abs_not_pmd"]["n"]) == (6, 18)          # {16, 17, 18}
    assert (g["pmd"]["blob"], g["pmd"]["n"]) == (6, 6)
    d = a["rel_extra_minus_neither"]
    assert abs(d["paired"]["value"] - (1 / 2 - 1 / 7)) < 1e-9
    assert d["reading"].startswith("reviewers call the extra flags Blob more often")
    assert out["confirm_only"]["n_repos"] == 5


def test_exploratory_section_prints_a_definition_without_a_kind():
    # human_blob is registered without a "kind"; the MLCQ run's analysis crashed formatting it
    d = _run_dir()
    path = os.path.join(d, "study.units.jsonl")
    units = [json.loads(ln) for ln in open(path)]
    with open(path, "w") as fh:
        for u in units:
            u["class"]["signals"] = list(metrics.CLASS_SIGNALS)
            u["class"]["values"] = {s: VALUES for s in metrics.CLASS_SIGNALS}
            fh.write(json.dumps(u) + "\n")
    run = analyse.Run(d)
    for r in run.rows:
        r["matrix"]["class"].update(cells={}, oracle_gods={"human_blob": 3})
    lines = []
    analyse.exploratory(run, {}, print_fn=lines.append)
    assert any("human_blob " in ln and "[None" in ln for ln in lines)


def test_main_constants_are_checked_against_the_main_analysis():
    d = tempfile.mkdtemp()
    a = {"plan": {"primary": {"rule": "mad_z"}},
         "primary": {"pmd_GodClass": {"chosen_signal": "cognitive_max",
                                      "confirm": {"absolute_cutoff": {"cut": 22.0}}}}}
    json.dump(a, open(os.path.join(d, "analysis.json"), "w"))
    agreement.check_main(d)
    a["primary"]["pmd_GodClass"]["chosen_signal"] = "nloc_sum"
    json.dump(a, open(os.path.join(d, "analysis.json"), "w"))
    try:
        agreement.check_main(d)
        raise AssertionError("a mismatch must refuse")
    except SystemExit:
        pass


if __name__ == "__main__":
    ok = True
    for k, fn in sorted(globals().items()):
        if k.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {fn.__name__}")
            except Exception as e:
                ok = False
                print(f"  [FAIL] {fn.__name__}: {type(e).__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
