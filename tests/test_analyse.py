"""The analysis script: a synthetic run (Java repositories under a fake PMD, Python ones
without) is measured for real by study.analyse and written the way study.run writes it, then
the report is produced to the plan. Pins: the one code path agrees with the harness's cells
for a Java-scoped definition, the explore choice never picks a size signal or an ingredient,
god-free repositories stay in the pooled numbers, and the JSON carries every section."""
import io
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import analyse, metrics, stats, study

FAKE_PMD = r'''#!{py}
import json, sys
files = [l.strip() for l in open(sys.argv[sys.argv.index("--file-list") + 1]) if l.strip()]
out = {{"files": []}}
for f in files:
    src = open(f).read()
    v = []
    if "GODMARK" in src:
        v.append({{"rule": "GodClass", "beginline": 1, "description": "Possible God Class"}})
    ln = 1
    for line in src.splitlines():
        if line.strip().startswith("void m") or line.strip().startswith("public int deep"):
            cc = 20 if "deep" in line else 2
            v.append({{"rule": "CyclomaticComplexity", "beginline": ln,
                       "description": "The method 'm()' has a cyclomatic complexity of %d." % cc}})
            v.append({{"rule": "NPathComplexity", "beginline": ln,
                       "description": "The method 'm()' has an NPath complexity of %d, current threshold is 1" % (cc * 30)}})
        ln += 1
    out["files"].append({{"filename": f, "violations": v}})
json.dump(out, sys.stdout)
'''


def _synthetic_run(n_java=16, n_py=4, seed=7):
    root = tempfile.mkdtemp()
    pmd = os.path.join(root, "pmd")
    open(pmd, "w").write(FAKE_PMD.format(py=sys.executable))
    os.chmod(pmd, 0o755)
    rnd = random.Random(seed)
    rows, units = [], []
    tools = {"lizard": study.LIZARD_VERSION, "harness_commit": "a" * 40}
    for i in range(n_java + n_py):
        lang = "java" if i < n_java else "python"
        repo = os.path.join(root, f"r{i}")
        gods = rnd.choice([0, 0, 1, 2, 3]) if lang == "java" else 0
        if lang == "java":
            d = os.path.join(repo, "src/main/java/a")
            os.makedirs(d)
            for k in range(18):
                body = "\n".join(f"  void m{j}(int x) {{ if (x > {j}) {{ x++; }} }}"
                                 for j in range(rnd.randint(2, 6)))
                open(os.path.join(d, f"C{k}.java"), "w").write(f"package a;\nclass C{k} {{\n{body}\n}}\n")
            # two mid-sized classes with nested branching (near-gods), so that the relative
            # rules disagree with each other and the Friedman blocks carry information
            for k in range(2):
                body = "\n".join(f"  void n{j}(int x) {{ if (x > {j}) {{ if (x > {j + 1}) {{ "
                                 f"if (x > {j + 2}) {{ x++; }} }} }} }}" for j in range(rnd.randint(8, 12)))
                open(os.path.join(d, f"Big{k}.java"), "w").write(f"package a;\nclass Big{k} {{\n{body}\n}}\n")
            for g in range(gods):
                open(os.path.join(d, f"God{g}.java"), "w").write(
                    "package a;\n/* GODMARK */\n"
                    + study._java_smoke_source().replace("PreflightGod", f"God{g}"))
        else:
            os.makedirs(os.path.join(repo, "pkg"))
            for k in range(16):
                body = "\n".join(f"def f{j}(x):\n    if x > {j}:\n        return x\n    return {j}\n"
                                 for j in range(rnd.randint(3, 8)))
                open(os.path.join(repo, "pkg", f"m{k}.py"), "w").write(body)
        a = study.analyse(repo, pmd if lang == "java" else None, None)
        u = a.pop("_units")
        url = f"https://github.com/o/{lang}{i}"
        # the last two Java repositories come from the supplement; every row carries its half
        sample = ("open-source-repository-sample.java-supplement.csv" if lang == "java" and i >= n_java - 2
                  else "open-source-repository-sample.csv")
        rows.append({"repo": url, "name": f"{lang}{i}", "full_name": f"o/{lang}{i}", "lang": lang,
                     "tier": ["low", "mid", "high"][i % 3], "kind": "library", "tools": tools,
                     "sample": sample, **a})
        units.append({"repo": url, **u})
    halves = stats.assign_halves(rows, stratum_of=lambda r: (r["lang"], r["tier"]),
                                 key_of=lambda r: r["repo"])
    for r in rows:
        r["half"] = halves[r["repo"]]
    out = os.path.join(root, "results")
    os.makedirs(out)
    json.dump(rows, open(os.path.join(out, "study.json"), "w"))
    with open(os.path.join(out, "study.units.jsonl"), "w") as fh:
        for u in units:
            fh.write(json.dumps(u) + "\n")
    study.write_oracles(out)
    return out


_RUN = None


def _run():
    global _RUN
    if _RUN is None:
        _RUN = analyse.Run(_synthetic_run())
    return _RUN


def test_sidecar_code_path_agrees_with_the_harness_cells_for_a_java_scoped_definition():
    run = _run()
    for r in run.rows:
        for sig in ("nloc_sum", "cc_max"):
            for rule in ("mad_z", "pct_top1", "iqr"):
                cell = r["matrix"]["class"]["cells"][sig][rule].get("pmd_GodClass")
                if cell is None:
                    continue
                c = run.counts(r["repo"], "class", sig, "pmd_GodClass", run.rule_fn(rule))
                assert (c["n_univ"], c["n_out"], c["n_overlap"], c["n_god_univ"]) == (
                    cell["n_univ"], cell["n_out"], cell["n_overlap"], cell["n_god_univ"]), (r["name"], sig, rule, c, cell)
        # and for an all-scope definition
        cell = r["matrix"]["class"]["cells"]["nloc_sum"]["mad_z"]["wmc47"]
        c = run.counts(r["repo"], "class", "nloc_sum", "wmc47", run.rule_fn("mad_z"))
        assert c["n_univ"] == cell["n_univ"] and c["n_out"] == cell["n_out"]


def test_explore_choice_is_restricted_to_the_plan_families_and_excludes_ingredients():
    run = _run()
    cands = run.candidates("class", "pmd_GodClass", ["peak", "density"])
    assert cands and all(metrics.family_of("class", s) in ("peak", "density") for s in cands)
    assert not any(s.startswith("cc_") for s in cands)             # cc_* are ingredients
    assert "nloc_sum" not in cands and "nom" not in cands           # size family excluded
    best, scores = run.choose("class", "pmd_GodClass", ["peak", "density"])
    assert best in cands and all(s in cands for s in scores)
    m = run.candidates("method", "brain_method", ["structure", "density"])
    assert "cc" not in m and "nesting" not in m and "mi" not in m and "cyc_density" not in m
    assert "cognitive" in m and "params" in m


def test_halves_are_stratified_and_god_free_repositories_are_pooled():
    run = _run()
    for (lang, tier), n in {(r["lang"], r["tier"]): 0 for r in run.rows}.items():
        rs = [r for r in run.rows if (r["lang"], r["tier"]) == (lang, tier)]
        ex = sum(1 for r in rs if run.halves[r["repo"]] == "explore")
        assert abs(ex - (len(rs) - ex)) <= 1
    java = [r for r in run.rows if r["lang"] == "java"]
    blocks = analyse._blocks(run, java, "class", "nloc_max", "pmd_GodClass", True)
    pooled = stats.pooled_auc(blocks)
    assert pooled["n_blocks"] == len(java)
    assert pooled["n_blocks_no_god"] == sum(1 for r in java if not r.get("pmd_gods"))
    m = run.macro_mcc(java, "class", "nloc_max", "pmd_GodClass", run.rule_fn("mad_z"))
    assert m["micro"]["n_blocks"] == len(java) and m["n_repos"] == len(java)
    # a Python repository has no Java-scoped block at all (not a block of zeros)
    py = [r for r in run.rows if r["lang"] == "python"][0]
    assert run.block(py["repo"], "class", "pmd_GodClass") is None
    assert run.block(py["repo"], "class", "wmc47") is not None


def test_split_is_read_from_the_rows_and_all_language_definitions_use_the_main_sample():
    run = _run()
    assert run.split_frozen is True
    assert run.halves == {r["repo"]: r["half"] for r in run.rows}
    assert len(run.main_rows) == len(run.rows) - 2
    assert run.rows_for("pmd_GodClass") == run.rows                  # Java-scoped: every row
    assert run.rows_for("brain_method") == run.main_rows             # all-language: main only
    h = run.halves_for("brain_method")
    assert len(h["explore"]) + len(h["confirm"]) == len(run.main_rows)
    # a run whose rows carry no half gets the computed split, flagged as not frozen
    d = tempfile.mkdtemp()
    rows = json.load(open(os.path.join(run.dir, "study.json")))
    for r in rows:
        del r["half"]
    json.dump(rows, open(os.path.join(d, "study.json"), "w"))
    for f in ("study.units.jsonl", "oracles.json"):
        open(os.path.join(d, f), "w").write(open(os.path.join(run.dir, f)).read())
    r2 = analyse.Run(d)
    assert r2.split_frozen is False and set(r2.halves.values()) == {"explore", "confirm"}


def test_human_definitions_are_fitted_on_the_repository_language():
    run = _run()
    run.registry["human_x"] = {"origin": "human", "scope": "labelled", "kind": "human"}
    repo = [r for r in run.rows if r["lang"] == "java"][0]["repo"]
    pl = run.units[repo]["class"]
    pl["god_idx"]["human_x"] = pl["god_idx"]["pmd_GodClass"]
    pl, fit, score, _ = run.block(repo, "class", "human_x")
    assert fit and all(pl["units"][i].endswith(".java") for i in fit) and score == fit
    del run.registry["human_x"]
    del run.units[repo]["class"]["god_idx"]["human_x"]


def test_report_runs_to_the_plan_and_writes_every_section():
    run = _run()
    buf = io.StringIO()
    out = analyse.report(run, print_fn=lambda *a: print(*a, file=buf))
    text = buf.getvalue()
    for marker in ("1. DIAGNOSTICS", "2. PRIMARY", "3. SECONDARY", "4. RULES", "5. SIGNALS",
                   "6. EXPLORATORY", "calibration", "flag rate", "FP in god-free repos",
                   "macro FPR", "DECISION (pre-registered", "verdict:", "FROZEN before measurement",
                   "overlap with the pilot", "all-tied blocks dropped"):
        assert marker in text, marker
    assert out["plan"] == analyse.PLAN and out["is_exploratory"] is False
    assert out["study_sha256"] and out["diagnostics"]["split_frozen"] is True
    assert out["diagnostics"]["n_pilot"] > 500 and out["diagnostics"]["pilot_overlap"] == []
    prim = out["primary"]["pmd_GodClass"]
    dec = prim["decision"]
    assert dec["overall"] in ("superior", "non-inferior", "inconclusive", "inferior", "not estimable")
    assert dec["powered"] is False                                   # 10 synthetic repos
    assert set(dec["paired"]) == {"macro_mcc", "micro_mcc", "macro_fpr"}
    assert dec["paired"]["macro_mcc"] is not None and dec["overall"] != "not estimable"
    pm = dec["paired"]["macro_mcc"]
    assert pm["lo"] <= pm["value"] <= pm["hi"] and pm["n"] == dec["n_paired_repos"] >= 5
    assert "macro_fpr" in prim["confirm"]["relative_default"]
    assert "_cells" not in prim["confirm"]["relative_default"]
    assert prim["chosen_signal"] and metrics.family_of("class", prim["chosen_signal"]) in ("peak", "density")
    c = prim["confirm"]
    assert c["pooled_auc_standardised"]["standardised"] is True
    assert c["pooled_auc_raw"]["standardised"] is False
    assert c["relative_default"]["micro"]["n_blocks"] > 0
    assert c["absolute_cutoff"]["cut"] is not None
    assert "lang=java" in prim["breakdown"]
    assert set(out["secondary"]) >= {"pmd_method_NPath200", "brain_method"}
    assert out["friedman_rules"] is not None and out["friedman_rules"]["k"] == len(analyse.PLAN["friedman_rules"])
    assert "class:pmd_GodClass" in out["exploratory"]
    assert out["diagnostics"]["dirty_rows"] == 0 and out["diagnostics"]["usable_flips"] == []
    json.dumps(out, default=str)
    # main writes analysis.json beside the run ONCE; a re-run needs --exploratory
    assert analyse.main(["--results", run.dir]) == 0
    assert "primary" in json.load(open(os.path.join(run.dir, "analysis.json")))
    assert analyse.main(["--results", run.dir]) == 3
    assert analyse.main(["--results", run.dir, "--exploratory"]) == 0
    extra = [f for f in os.listdir(run.dir) if f.startswith("analysis.exploratory.")]
    assert len(extra) == 1 and json.load(open(os.path.join(run.dir, extra[0])))["is_exploratory"] is True
    assert json.load(open(os.path.join(run.dir, "analysis.json")))["is_exploratory"] is False


def test_latest_results_dir_is_the_latest_dated_run_never_a_named_one():
    d = tempfile.mkdtemp()
    for name in ("2026-10-19", "mlcq", "2026-10-20", "notes"):
        os.makedirs(os.path.join(d, name))
        open(os.path.join(d, name, "study.json"), "w").write("[]")
    assert os.path.basename(analyse._latest(d)) == "2026-10-20"
    assert analyse._latest(tempfile.mkdtemp()) is None


def test_plan_matches_plan_md():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "PLAN.md")).read()
    p = analyse.PLAN["primary"]
    assert f"`{p['definition']}`" in text and f"`{p['rule']}`" in text
    assert str(analyse.PLAN["min_positives"]) in text
    for s in analyse.PLAN["friedman_signals"]["class"] + analyse.PLAN["friedman_rules"]:
        assert s in text, s
    for fam in p["families"]:
        assert fam in text
    d = analyse.PLAN["decision"]
    assert f"{d['noninferiority_margin']}" in text and f"{d['auc_floor']}" in text
    assert f"**{d['min_confirm_repos_auc']}**" in text and f"**{d['min_confirm_repos_mcc']}**" in text
    assert "main sample" in text and "halves.json" in text and "seed 1" in text


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
