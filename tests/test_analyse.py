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


def _synthetic_run(n_java=24, n_py=4, seed=7):
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
                   "overlap with the pilot", "all-tied blocks dropped", "standardised - raw",
                   "threshold-free reading", "SENSITIVITY", "owner concentration",
                   "classpath validation", "MCC margin", "FPR margin"):
        assert marker in text, marker
    assert out["plan"] == analyse.PLAN and out["is_exploratory"] is False
    assert out["study_sha256"] and out["diagnostics"]["split_frozen"] is True
    assert out["diagnostics"]["n_pilot"] > 500 and out["diagnostics"]["pilot_overlap"] == []
    assert out["diagnostics"]["n_java"] == 24 and out["diagnostics"]["n_java_main_sample"] == 22
    assert out["diagnostics"]["owners"]["distinct"] == 1              # all synthetic rows are o/*
    assert out["diagnostics"]["classpath"]["n_reports"] == 0
    prim = out["primary"]["pmd_GodClass"]
    dec = prim["decision"]
    assert dec["overall"] in ("superior", "non-inferior", "inconclusive", "inferior", "not estimable")
    assert dec["powered"] is False and dec["confirmatory"] is False   # 12 confirm Java repos
    assert set(dec["paired"]) == {"macro_mcc", "micro_mcc", "macro_fpr"}
    assert dec["arms"] == analyse.PLAN["decision"]["arms"] and set(dec["verdicts"]) == set(dec["paired"])
    assert dec["paired"]["macro_mcc"] is not None and dec["overall"] != "not estimable"
    pm = dec["paired"]["macro_mcc"]
    # the macro arm is read over the repositories with >= 1 positive only
    assert pm["lo"] <= pm["value"] <= pm["hi"]
    assert 5 <= pm["n"] == dec["n_paired_repos_macro"] < dec["n_paired_repos"] == dec["paired"]["micro_mcc"]["n"]
    # the MCC margin is min(ceiling, fraction x explore level), both recorded
    assert dec["margin_ceiling"] == 0.10 and dec["explore_level"] is not None
    assert abs(dec["margin"] - min(0.10, 0.30 * dec["explore_level"])) < 1e-12
    assert dec["fpr_margin"] == 0.05
    # no classpath reports: flagged, not confirmatory
    assert dec["classpath"]["n_reports"] == 0 and dec["classpath"]["within_bound"] is None
    assert any("classpath validation missing" in n for n in dec["notes"])
    # the pilot sensitivity: nothing overlaps here, so it is the same decision
    assert prim["sensitivity_without_pilot"] == {"n_pilot_removed": 0, "same_as_decision": True}
    assert "macro_fpr" in prim["confirm"]["relative_default"]
    assert "_cells" not in prim["confirm"]["relative_default"]
    assert prim["chosen_signal"] and metrics.family_of("class", prim["chosen_signal"]) in ("peak", "density")
    c = prim["confirm"]
    assert c["pooled_auc_standardised"]["standardised"] is True
    assert c["pooled_auc_raw"]["standardised"] is False
    d = c["pooled_auc_difference"]
    assert d["reading"] in ("relative ranking better", "absolute ranking better",
                            "no difference resolved", "not estimable")
    if d["paired"]:
        assert abs(d["paired"]["value"] - (c["pooled_auc_standardised"]["auc"]
                                           - c["pooled_auc_raw"]["auc"])) < 1e-9
    assert c["relative_default"]["micro"]["n_blocks"] > 0
    assert c["absolute_cutoff"]["cut"] is not None
    assert "lang=java" in prim["breakdown"]
    # secondaries are decided on the plan's arms; a human definition would use the micro arm
    assert out["secondary"]["pmd_method_NPath200"]["decision"]["arms"] == analyse.PLAN["decision"]["arms"]
    assert analyse.PLAN["human"]["decide_on"] == ["micro_mcc"]
    assert set(out["secondary"]) >= {"pmd_method_NPath200", "brain_method"}
    assert out["friedman_rules"] is not None and out["friedman_rules"]["k"] == len(analyse.PLAN["friedman_rules"])
    assert "class:pmd_GodClass" in out["exploratory"]
    assert out["diagnostics"]["dirty_rows"] == 0 and out["diagnostics"]["usable_flips"] == []
    json.dumps(out, default=str)
    # main writes analysis.json beside the run ONCE; a re-run needs --exploratory
    assert analyse.main(["--results", run.dir]) == 0
    assert "primary" in json.load(open(os.path.join(run.dir, "analysis.json")))
    digest = open(os.path.join(run.dir, "analysis.json.sha256")).read().split()[0]
    assert digest == analyse._sha256(os.path.join(run.dir, "analysis.json"))
    assert analyse.main(["--results", run.dir]) == 3
    assert analyse.main(["--results", run.dir, "--exploratory"]) == 0
    extra = [f for f in os.listdir(run.dir)
             if f.startswith("analysis.exploratory.") and f.endswith(".json")]
    assert len(extra) == 1 and json.load(open(os.path.join(run.dir, extra[0])))["is_exploratory"] is True
    assert json.load(open(os.path.join(run.dir, "analysis.json")))["is_exploratory"] is False


def test_verdicts_read_each_margin_in_its_own_direction():
    ci = lambda lo, hi: {"value": (lo + hi) / 2, "lo": lo, "hi": hi, "n": 50}
    # an MCC difference: higher is better
    assert analyse._verdict(ci(0.01, 0.2), 0.10) == "superior"
    assert analyse._verdict(ci(-0.05, 0.1), 0.10) == "non-inferior"
    assert analyse._verdict(ci(-0.3, -0.15), 0.10) == "inferior"
    assert analyse._verdict(ci(-0.2, 0.1), 0.10) == "inconclusive"
    assert analyse._verdict(None, 0.10) == "not estimable"
    # a false-positive-rate difference: lower is better, so the margin is on the upper bound
    assert analyse._verdict_lower_better(ci(-0.02, -0.001), 0.05) == "superior"
    assert analyse._verdict_lower_better(ci(-0.01, 0.03), 0.05) == "non-inferior"
    assert analyse._verdict_lower_better(ci(0.06, 0.1), 0.05) == "inferior"
    assert analyse._verdict_lower_better(ci(-0.01, 0.08), 0.05) == "inconclusive"
    # the verdict is the weakest arm
    assert min(["superior", "non-inferior", "inconclusive"], key=lambda x: analyse._RANK[x]) == "inconclusive"


def test_classpath_reports_bound_the_primary_and_name_their_half():
    run = _run()
    d = tempfile.mkdtemp()
    java = [r for r in run.rows if r["lang"] == "java"]
    ex = next(r for r in java if run.halves[r["repo"]] == "explore")
    co = next(r for r in java if run.halves[r["repo"]] == "confirm")

    def rep(name, url, without, lost, gained):
        json.dump({"url": url, "godclass_flips": len(lost) + len(gained),
                   "rules": {"GodClass": {"without": without, "with": without - len(lost) + len(gained),
                                          "lost": lost, "gained": gained}}},
                  open(os.path.join(d, name), "w"))
    # 12 reports on explore repositories: ten with 2 GodClass verdicts each (one of them loses
    # one with the classpath, one gains one), two with none: 2 flips over 21 verdicts in the
    # union -> 9.5%, within the bound
    for i in range(12):
        rep(f"e{i}.json", ex["full_name"], 2 if i < 10 else 0, ["x"] if i == 0 else [],
            ["y"] if i == 1 else [])
    r2 = analyse.Run(run.dir, classpath_dir=d)
    cp = analyse.classpath_summary(r2)
    assert cp["n_reports"] == 12 and cp["flips"] == 2 and cp["union"] == 21
    assert abs(cp["flip_rate"] - 2 / 21) < 1e-12 and cp["within_bound"] is True
    assert cp["confirm_touched"] == [] and cp["halves_named"][ex["full_name"].lower()] == "explore"
    # one more flip tips it over the bound; a report naming a confirm repository is caught
    rep("e12.json", co["repo"], 1, ["z"], [])
    cp = analyse.classpath_summary(analyse.Run(run.dir, classpath_dir=d))
    assert cp["flip_rate"] > 0.10 and cp["within_bound"] is False
    assert cp["confirm_touched"] == [co["repo"].lower()]
    # too few reports is not within the bound either, whatever the rate
    few = tempfile.mkdtemp()
    json.dump({"url": ex["full_name"], "godclass_flips": 0,
               "rules": {"GodClass": {"without": 3, "with": 3, "lost": [], "gained": []}}},
              open(os.path.join(few, "a.json"), "w"))
    cp = analyse.classpath_summary(analyse.Run(run.dir, classpath_dir=few))
    assert cp["flip_rate"] == 0.0 and cp["enough_repos"] is False and cp["within_bound"] is False
    # a report without a url is counted but its half cannot be checked
    json.dump({"godclass_flips": 0, "rules": {"GodClass": {"without": 1, "with": 1, "lost": [], "gained": []}}},
              open(os.path.join(few, "b.json"), "w"))
    assert analyse.classpath_summary(analyse.Run(run.dir, classpath_dir=few))["unnamed_reports"] == 1


def test_macro_arm_excludes_god_free_repositories_and_margin_scales_to_explore_level():
    run = _run()
    java = [r for r in run.rows if r["lang"] == "java"]
    co = [r for r in java if run.halves[r["repo"]] == "confirm"]
    ex = [r for r in java if run.halves[r["repo"]] == "explore"]
    sig = "nloc_max"
    cut = stats.best_cutoff(run.pairs(ex, "class", sig, "pmd_GodClass"))
    buf = io.StringIO()
    level = run.explore_level(ex, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"))
    dec = analyse._decision(run, co, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"),
                            run.cutoff_fn(cut["cut"]), None, 0, lambda *a: print(*a, file=buf),
                            explore_level=level)
    god_free = sum(1 for r in co if not r.get("pmd_gods"))
    assert dec["n_paired_repos"] == len(co) and dec["n_paired_repos_macro"] == len(co) - god_free
    assert dec["paired"]["micro_mcc"]["n"] == len(co)
    assert dec["margin"] == min(0.10, 0.30 * level)
    # a low explore level shrinks the margin; a high one is capped at the ceiling
    small = analyse._decision(run, co, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"),
                              run.cutoff_fn(cut["cut"]), None, 0, lambda *a: None, explore_level=0.1)
    big = analyse._decision(run, co, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"),
                            run.cutoff_fn(cut["cut"]), None, 0, lambda *a: None, explore_level=0.9)
    assert abs(small["margin"] - 0.03) < 1e-12 and big["margin"] == 0.10
    none = analyse._decision(run, co, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"),
                             run.cutoff_fn(cut["cut"]), None, 0, lambda *a: None)
    assert none["margin"] == 0.10 and none["explore_level"] is None
    # a human definition is decided on the micro arm alone; the others are reported
    micro = analyse._decision(run, co, "class", sig, "pmd_GodClass", run.rule_fn("mad_z"),
                              run.cutoff_fn(cut["cut"]), None, 0, lambda *a: None, arms=["micro_mcc"])
    assert micro["arms"] == ["micro_mcc"] and micro["overall"] == micro["verdicts"]["micro_mcc"]
    assert set(micro["verdicts"]) == {"macro_mcc", "micro_mcc", "macro_fpr"}


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
    assert f"min({d['noninferiority_margin']:.2f}, {d['margin_fraction_of_explore_level']:.2f} ×" in text
    assert f"**FPR margin: {d['fpr_margin']}" in text and f"{d['auc_floor']}" in text
    assert f"**{d['min_confirm_repos_auc']}**" in text and f"**{d['min_confirm_repos_mcc']}**" in text
    assert f"**{round(d['classpath_flip_bound'] * 100)}%**" in text and f"**{d['classpath_min_repos']}**" in text
    for arm in d["arms"]:
        assert arm.replace("_", " ").replace("mcc", "MCC").replace("fpr", "FPR") in text, arm
    assert "≥ 1 positive" in text and "oracle-bounded" in text and "sensitivity" in text
    assert analyse.PLAN["human"]["decide_on"] == ["micro_mcc"] and "micro MCC arm alone" in text
    assert analyse.PLAN["human"]["mlcq_rule"] in text and "minor" in text
    assert "main sample" in text and "halves.json" in text and "seed 1" in text
    assert "sha256" in text and "owner" in text.lower()


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
