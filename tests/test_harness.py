"""Regression tests for the study harness: usability, the oracle registry, the PMD/CK/human
oracle wiring, the signal preflight, pins, and the resumable multi-sample run.
Each test pins one behaviour so it cannot silently break.

No network: the study-run test drives the sampler's run loop over a local git repository named
in a sample CSV, so cloning at the pinned commit and measuring run for real.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import cognitive, extract, metrics, study


# --- usability is decided before any detection outcome -------------------------------------

def _row(n_univ, n_funcs=100, **kw):
    return {"repo": kw.pop("repo", "u"), "n_funcs": n_funcs,
            "matrix": {"class": {"n_univ": n_univ}}, **kw}


def test_is_usable_substance_floor():
    assert study.is_usable(_row(40)) is True
    assert study.is_usable(_row(10)) is False               # universe < 15
    assert study.is_usable(_row(40, n_funcs=10)) is False    # too few functions
    assert study.is_usable(_row(40, error="boom")) is False
    assert study.is_usable(_row(40, excluded_min_substance=True)) is False


# --- average precision is reproducible ----------------------------------------------------

def test_average_precision_is_tie_aware_and_order_free():
    vals = {"a": 1, "b": 1, "c": 0, "d": 0}
    gods = {"a", "c"}
    seen = set()
    for perm in (["a", "b", "c", "d"], ["d", "c", "b", "a"], ["b", "a", "d", "c"]):
        _, ap, _, _ = metrics.auc_ap(vals, gods, perm)
        seen.add(round(ap, 10))
    assert seen == {0.5}, seen


# --- the oracle registry ---------------------------------------------------------------------

def test_registry_declares_ingredients_of_every_composite():
    assert {"cc_sum", "cc_mean", "cc_max", "mi_sum", "cyc_density_max"} <= study.ingredients("pmd_GodClass")
    assert "nom" not in study.ingredients("pmd_GodClass")
    assert study.ingredients("decor_blob") == {"nom"}
    assert study.ingredients("brain_method") == {"nloc", "cc", "nesting", "mi", "cyc_density"}
    assert study.ingredients("pmd_method_NPath200") == set()
    assert study.ingredients("wmc47") >= {"cc_sum"}
    for name, meta in study.ORACLES.items():
        assert meta["level"] in ("class", "method"), name
        assert meta["kind"] in ("self", "calibration", "component", "tool", "composite", "human"), name
        if meta["headline"]:
            assert meta["kind"] in ("composite", "tool", "human"), name     # never a self/component
        if meta["kind"] == "self":
            assert len(meta["bases"]) == 1, name
    for name, meta in study.ORACLES.items():
        assert meta["origin"] in ("tool", "human", "composed", "internal"), name
        if meta["kind"] in ("self",) or name == "brain_method":
            assert meta["origin"] == "internal", name                  # never read as external
        if name.startswith(("pmd_", "ck_")):
            assert meta["origin"] == "tool", name
        cond = meta.get("conditional_on")
        if cond:
            assert study.ORACLES[cond]["level"] == meta["level"], name
    assert study.ORACLES["pmd_GodClass"]["conditional_on"] == "wmc47"
    assert study.ORACLES["decor_blob"]["conditional_on"] == "ck_LargeClass"
    reg = study.oracle_registry()
    assert set(reg["oracles"]) == set(study.ORACLES)
    assert reg["algorithms"] == metrics.ALGORITHM_CONSTANTS
    assert reg["families"]["class"]["size"] == list(metrics.CLASS_FAMILIES["size"])
    assert reg["headline_order"] == ["tool", "human", "composed", "internal"]
    assert reg["pmd_thresholds"]["CognitiveComplexity"]["method"] == 15
    json.dumps(reg)                                                   # serialisable as written


def test_every_oracle_analyse_emits_is_registered():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "src"))
    for rel, body in study._SIGNAL_FIXTURES.items():
        with open(os.path.join(root, os.path.basename(rel)), "w") as fh:
            fh.write(body)
    res = study.analyse(root, None, None, human={"blob": {"Deep.java"}})
    emitted = set(res["matrix"]["method"]["oracle_gods"]) | set(res["matrix"]["class"]["oracle_gods"]) | {"wmc47"}
    assert emitted <= set(study.ORACLES), emitted - set(study.ORACLES)
    assert "human_blob" in emitted and study.ORACLES["human_blob"]["kind"] == "human"
    assert res["human_labels"] == {"blob": {"labelled": 1, "measured": 1}}
    # a zero-god oracle still has its cells recorded (n_god_univ == 0), never dropped
    c = res["matrix"]["method"]["cells"]["cc"]["mad_z"]["brain_method"]
    assert c["n_univ"] > 0 and c["n_god_univ"] == 0
    # diagnostics travel with the row: skipped files, trivial share, per-signal scale
    assert res["files_skipped"] == {"oversize": 0, "generated": 0, "unparsed": 0}
    assert 0 <= res["trivial_frac"] <= 1 and set(res["matrix"]["method"]["diag"]) == set(metrics.METHOD_SIGNALS)
    assert res["matrix"]["method"]["diag"]["cc"]["scale"] in ("mad", "mean_ad", "constant")
    assert res["matrix"]["class"]["god_outside_univ"]["human_blob"] == 0


# --- PMD: path-keyed, measured files only, class AND method forms ------------------------------

FAKE_PMD = r'''#!{py}
import json, sys
files = [l.strip() for l in open(sys.argv[sys.argv.index("--file-list") + 1]) if l.strip()]
out = {{"files": []}}
for f in files:
    src = open(f).read()
    v = []
    if "GODMARK" in src:
        v.append({{"rule": "GodClass", "beginline": 1, "description": "Possible God Class"}})
        v.append({{"rule": "CyclomaticComplexity", "beginline": 1,
                   "description": "The class 'Util' has a total cyclomatic complexity of 80 (highest 20)."}})
        v.append({{"rule": "CyclomaticComplexity", "beginline": 2,
                   "description": "The method 'a(int)' has a cyclomatic complexity of 12."}})
        v.append({{"rule": "NcssCount", "beginline": 3,
                   "description": "The constructor 'Util()' has a NCSS line count of 70."}})
        v.append({{"rule": "NcssCount", "beginline": 1,
                   "description": "The class 'Util' has a NCSS line count of 1600."}})
    out["files"].append({{"filename": f, "violations": v}})
json.dump(out, sys.stdout)
open({log!r}, "w").write("\n".join(files))
'''


def _fake_pmd():
    log = os.path.join(tempfile.mkdtemp(), "pmd-files.txt")
    pmd = os.path.join(tempfile.mkdtemp(), "pmd")
    open(pmd, "w").write(FAKE_PMD.format(py=sys.executable, log=log))
    os.chmod(pmd, 0o755)
    return pmd, log


def test_pmd_report_is_path_keyed_runs_on_measured_files_and_splits_method_forms():
    root = tempfile.mkdtemp()
    java = "class Util {{ {0}\n  void a(int x) {{ b(x, x); }}\n  Util() {{ }}\n  void b(int p, int q) {{ }} }}"
    files = {"core/src/main/java/a/Util.java": java.format("/* GODMARK */"),
             "web/src/main/java/b/Util.java": java.format(""),
             "core/src/test/java/a/UtilTest.java": java.format("/* GODMARK */")}
    for rel, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        open(os.path.join(root, rel), "w").write(body)
    pmd, log = _fake_pmd()
    measured = sorted(f for f in files if "/test/" not in f)
    rep = study._pmd_report(pmd, root, measured)
    god = "core/src/main/java/a/Util.java"
    assert rep["class"]["GodClass"] == {god}, rep
    assert rep["class"]["CyclomaticComplexity"] == {god}        # the class form stays class-level
    assert rep["class"]["NcssCount"] == {god}                    # class form only; not the ctor's
    assert [(r, l, rule) for r, l, rule, _ in rep["method"]] == [
        (god, 2, "CyclomaticComplexity"), (god, 3, "NcssCount")]
    passed = open(log).read().splitlines()
    assert not any("UtilTest" in p for p in passed) and len(passed) == 2, passed
    # mapping onto measured units: innermost function containing the line
    funcs = extract.analyze_tree(root)["funcs"]
    oracles, unmatched = study.pmd_method_oracles(rep["method"], funcs)
    names = {o: sorted(funcs[f]["name"] for f in s) for o, s in oracles.items()}
    assert names["pmd_method_CC10"] == ["a"] and names["pmd_method_Ncss60"] == ["Util"], names
    assert unmatched == 0
    _, unmatched = study.pmd_method_oracles([(god, 999, "NPathComplexity", "The method ...")], funcs)
    assert unmatched == 1
    # PMD's VALUES are parsed from every finding and the thresholds applied here
    assert rep["values"]["method"] == [(god, 2, "cc", 12), (god, 3, "ncss", 70)]
    assert rep["values"]["class"] == {"cc": {god: 80}, "ncss": {god: 1600}}
    vals, _ = study.pmd_method_values(rep["values"]["method"], funcs)
    assert {funcs[f]["name"]: v for f, v in vals["cc"].items()} == {"a": 12}
    below = [(god, 2, "CyclomaticComplexity", "The method 'a(int)' has a cyclomatic complexity of 9.")]
    assert study._pmd_report.__doc__ and study.PMD_THRESHOLDS["CyclomaticComplexity"]["method"] == 10
    assert "pmd_method_CC10" in study.pmd_method_oracles(below, funcs)[0]


def test_human_labels_at_both_levels_with_reviewed_universes():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "src"))
    for rel, body in study._SIGNAL_FIXTURES.items():
        open(os.path.join(root, os.path.basename(rel)), "w").write(body)
    human = {"blob": {"Deep.java"}, "blob_reviewed": {"Deep.java", "deep.py"},
             "long_method": {("deep.py", 3)}, "long_method_reviewed": {("deep.py", 3), ("deep.py", 18)}}
    res = study.analyse(root, None, None, human=human)
    assert res["human_labels"]["blob"] == {"labelled": 1, "measured": 1}
    assert res["human_labels"]["long_method@method"] == {"labelled": 1, "measured": 1}
    assert res["human_labels"]["long_method_reviewed@method"]["measured"] == 2
    assert study.ORACLES["human_blob"]["conditional_on"] == "human_blob_reviewed"
    assert study.ORACLES["human_method_long_method"]["conditional_on"] == "human_method_long_method_reviewed"
    assert study.ORACLES["human_blob_reviewed"]["kind"] == "component"
    assert study.ORACLES["human_method_long_method"]["level"] == "method"
    m = res["matrix"]["method"]
    assert m["oracle_gods"]["human_method_long_method"] == 1
    assert m["oracle_gods"]["human_method_long_method_reviewed"] == 2
    g = res["matrix"]["class"]["auc_given"]["human_blob"]
    assert g["given"] == "human_blob_reviewed" and g["n_univ"] == 2 and g["n_god"] == 1
    units = res["_units"]["method"]
    gi = units["god_idx"]["human_method_long_method"]
    assert len(gi) == 1 and units["units"][gi[0]].startswith("deep.py::deep@")


def test_java_scoped_definitions_are_scored_on_java_units_only():
    """A Kotlin file in a Java repository is in the ALL universe but PMD never evaluated it,
    so a Java-scoped definition must not count it as a (forced) negative."""
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "src/main/java/a"))
    os.makedirs(os.path.join(root, "src/main/kotlin"))
    java = "class U{0} {{ /* GODMARK */\n  void a(int x) {{ if (x > 0) {{ b(x); }} }}\n  void b(int p) {{ }} }}"
    for i in range(3):
        open(os.path.join(root, f"src/main/java/a/U{i}.java"), "w").write(java.format(i))
    body = "\n".join(f"    fun m{i}(x: Int): Int {{ if (x > {i}) {{ return x }} else {{ return -x }} }}"
                     for i in range(40))
    open(os.path.join(root, "src/main/kotlin/Big.kt"), "w").write("class Big {\n" + body + "\n}\n")
    open(os.path.join(root, "src/main/java/a/Gen.generated.java"), "w").write(java.format(9))
    pmd, _ = _fake_pmd()
    res = study.analyse(root, pmd, None)
    m = res["matrix"]
    assert m["class"]["n_univ"] == 4 and m["class"]["n_univ_scope"] == {"all": 4, "java": 3}
    assert m["class"]["oracle_scope"]["pmd_GodClass"] == "java"
    assert m["class"]["oracle_scope"]["wmc47"] == "all"
    cell = m["class"]["cells"]["nloc_sum"]["pct_top1"]["pmd_GodClass"]
    assert cell["n_univ"] == 3 and cell["n_god_univ"] == 3           # Kotlin file not a negative
    assert m["class"]["cells"]["nloc_sum"]["pct_top1"]["wmc47"]["n_univ"] == 4
    # the Kotlin file is the top-1% outlier over ALL units; it is not even in the Java cell
    assert cell["n_out"] == 0
    assert m["method"]["n_univ_scope"]["java"] == 6 and m["method"]["n_univ"] == 46
    assert m["method"]["cells"]["cc"]["mad_z"]["pmd_method_CC10"]["n_univ"] == 6
    assert m["method"]["cells"]["cc"]["mad_z"]["brain_method"]["n_univ"] == 46
    assert res["files_skipped"]["generated"] == 1 and res["java_files_skipped"]["generated"] == 1
    # the conditional block exists for the composite with a registered size clause
    g = m["class"]["auc_given"]["pmd_GodClass"]
    assert g["given"] == "wmc47" and set(g["signals"]) == set(metrics.CLASS_SIGNALS)
    assert g["n_univ"] == 0                                           # no file reaches WMC 47 here
    # the sidecar carries PMD's values aligned to units: Java units get a value, Kotlin None
    pv = res["_units"]["method"]["pmd_values"]
    units = res["_units"]["method"]["units"]
    assert len(pv["cc"]) == len(units) == 46
    assert sum(1 for v in pv["cc"] if v is None) == 40
    assert {u.split("::")[0] for u, v in zip(units, pv["cc"]) if v == 12} == {
        f"src/main/java/a/U{i}.java" for i in range(3)}


# --- human labels ------------------------------------------------------------------------------

def test_labels_match_by_url_or_full_name_and_only_at_the_labelled_commit():
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "labels.csv")
    open(p, "w").write("repo,commit,path,label\n"
                       "https://github.com/O/R.git,abc,src/A.java,Blob\n"
                       "o/r,abc,/src/B.java,blob\n"
                       "o/r,def,src/C.java,blob\n"
                       "o/other,abc,src/D.java,blob\n")
    labels = study.load_labels(p)
    hit, other = study.labels_for(labels, "https://github.com/o/r.git", "o/r", "ABC")
    assert hit == {"blob": {"src/A.java", "src/B.java"}}, hit
    assert other == []
    hit, other = study.labels_for(labels, "https://github.com/o/r.git", "o/r", "zzz")
    assert hit == {} and other == ["blob"]
    assert study.load_labels(None) == {}


# --- preflight: every signal alive, parser bounds, pins ---------------------------------------

def test_check_signals_passes_for_every_sampled_language_and_fails_closed_on_a_dead_signal():
    vals = study.check_signals()
    assert set(vals) == set(study.SAMPLED_LANGUAGES)
    for lang, v in vals.items():
        assert v["nesting"] >= study._MIN_DEEP_NESTING and v["cognitive"] > 0, (lang, v)
    orig = cognitive.analyze
    cognitive.analyze = lambda src, ext="": (0, 0)           # kill cognitive + nesting
    try:
        try:
            study.check_signals()
            assert False, "a dead signal must fail preflight"
        except study.SignalDead as e:
            assert "nesting" in str(e) and "cognitive" in str(e)
    finally:
        cognitive.analyze = orig


def test_ruby_is_excluded_while_the_pinned_parser_misbounds_it():
    assert study.ruby_parser_bounds_ok() is False             # the documented lizard 1.23 defect
    assert "ruby" not in study.SAMPLED_LANGUAGES and "ruby" in study.EXCLUDED_LANGUAGES
    assert "ruby" in study._FIXTURE_LANG                      # the fixture is kept for re-admission
    assert study.check_signals(("ruby",))["ruby"]["nesting"] >= 3


def test_preflight_passes_with_no_java_tools_and_smoke_class_is_god_like():
    study.preflight(None, None)        # must not raise
    assert study._tool_problems(None, None) == []
    src = study._java_smoke_source()
    assert src.count("public int m") == 30 and src.count("public int f") == 16
    assert "public int deep" in src


def test_preflight_hard_fails_on_version_drift():
    orig = study.LIZARD_VERSION
    study.LIZARD_VERSION = "9.9.9"
    try:
        try:
            study.preflight(None, None)
            assert False, "preflight should hard-fail on version drift"
        except RuntimeError as e:
            assert "9.9.9" in str(e) and "pin" in str(e).lower()
    finally:
        study.LIZARD_VERSION = orig


def test_installed_lizard_is_the_pinned_one_and_sees_annotated_classes():
    assert study._lizard_version() == study.LIZARD_VERSION
    study.check_parser()          # raises ParserBlind under the lizard 1.24 Java regression


def test_pmd_version_skips_the_ascii_banner():
    fake = os.path.join(tempfile.mkdtemp(), "pmd")
    open(fake, "w").write("#!/bin/sh\necho ' ____  __  __ ____'\necho '|  _ \\\\|  \\\\/  |'\n"
                          "echo 'PMD 7.27.0 (abc, 2026-01-01)'\n")
    os.chmod(fake, 0o755)
    assert study.pmd_version(fake) == "7.27.0"


def test_tool_drift_names_every_mismatch_and_tools_record_the_harness_commit():
    ok = {"lizard": study.LIZARD_VERSION, "pmd": study.PMD_VERSION,
          "ck_sha256": study.CK_SHA256}
    assert study.tool_drift(ok) == []
    bad = {"lizard": "1.24.1", "pmd": "7.0.0", "ck_sha256": "0" * 64}
    assert len(study.tool_drift(bad)) == 3
    hc = study.tool_versions(None, None)["harness_commit"]
    assert hc is None or len(hc.split("-")[0]) == 40


# --- a study run measures each sampled repository at its pinned commit, once -----------------

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _local_repo():
    src = tempfile.mkdtemp()
    _git(src, "init", "--quiet")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    body = "\n".join(f"def f{i}(x):\n    if x > {i}:\n        return x\n    return {i}\n"
                     for i in range(60))
    os.makedirs(os.path.join(src, "pkg"))
    for i in range(20):
        open(os.path.join(src, "pkg", f"m{i}.py"), "w").write(body)
    _git(src, "add", "-A")
    _git(src, "commit", "--quiet", "-m", "sampled")
    sampled = _git(src, "rev-parse", "HEAD")
    open(os.path.join(src, "pkg", "later.py"), "w").write("def later():\n    return 1\n")
    _git(src, "add", "-A")
    _git(src, "commit", "--quiet", "-m", "after sampling")       # must NOT be measured
    return src, sampled


def test_run_measures_each_usable_sampled_repository_at_its_commit_once_across_samples():
    from open_source_repository_sampler import files
    src, sampled = _local_repo()
    tmp = tempfile.mkdtemp()
    row = {"draw": 1, "status": "usable", "url": "file://" + src, "full_name": "o/proj",
           "commit": sampled, "commit_date": "2026-01-02T03:04:05+00:00", "language": "python",
           "stratum_language": "python", "tier": "low", "stars": 300, "rank": 4}
    main = os.path.join(tmp, "open-source-repository-sample.csv")
    files.write_csv(main, [row, {"draw": 2, "status": "excluded", "reason": "n_functions 3 < 50",
                                 "url": "file:///nope", "full_name": "o/small", "commit": "0" * 40,
                                 "language": "python"}])
    supp = os.path.join(tmp, "open-source-repository-sample.java-supplement.csv")
    files.write_csv(supp, [row])                                  # the same repo again
    out = os.path.join(tmp, "results")
    rows = study.run([main, supp], out, None, None)
    assert [r["full_name"] for r in rows] == ["o/proj"]          # measured once; excluded row not run
    r = rows[0]
    assert (r["commit"], r["lang"], r["tier"], r["stars"], r["date"], r["sample"]) == (
        sampled, "python", "low", 300, "2026-01-02", "open-source-repository-sample.csv")
    assert r["n_funcs"] == 20 * 60 and study.is_usable(r)        # later.py's function absent
    assert r["matrix"]["method"]["oracle_gods"]["brain_method"] == 0   # recorded, not dropped
    assert sorted(os.listdir(out)) == ["halves.json", "oracles.json", "run-log.jsonl",
                                       "study.csv", "study.json", "study.units.jsonl"]
    # the split was frozen from the sample CSV before measurement and recorded in the row
    h = json.load(open(os.path.join(out, "halves.json")))
    assert set(h["halves"]) == {"file://" + src} and r["half"] == h["halves"]["file://" + src]
    assert r["half"] in ("explore", "confirm") and set(h["samples"]) == {
        "open-source-repository-sample.csv", "open-source-repository-sample.java-supplement.csv"}
    assert study.run(main, out, None, None) == rows              # resumed: nothing re-measured
    csv_text = open(os.path.join(out, "study.csv")).read()
    assert ",half," in csv_text.splitlines()[0]
    units = [json.loads(l) for l in open(os.path.join(out, "study.units.jsonl"))]
    assert len(units) == 1 and units[0]["method"]["god_idx"]["brain_method"] == []
    anc = os.path.join(tmp, "anc")
    study.write_anc(rows, anc, frame_files=[main, supp])
    assert sorted(os.listdir(anc)) == ["README.txt", "open-source-repository-sample.csv",
                                       "open-source-repository-sample.java-supplement.csv",
                                       "oracles.json", "results.csv"]
    readme = open(os.path.join(anc, "README.txt")).read()
    assert "{base}_sum" in readme and "1 usable repositories" in readme and "SCALE-FREE" in readme


def test_freeze_halves_is_stratified_from_the_csv_and_never_moves():
    from open_source_repository_sampler import files
    tmp = tempfile.mkdtemp()
    rows = [{"draw": i, "status": "usable", "url": f"https://github.com/o/r{i}",
             "full_name": f"o/r{i}", "commit": "0" * 40, "language": "java" if i < 12 else "go",
             "stratum_language": "java", "tier": ["low", "mid", "high"][i % 3]}
            for i in range(24)] + [{"draw": 99, "status": "excluded", "url": "https://x/no",
                                    "full_name": "x/no", "commit": "1" * 40, "language": "go"}]
    csv_path = os.path.join(tmp, "open-source-repository-sample.csv")
    files.write_csv(csv_path, rows)
    path = os.path.join(tmp, "halves.json")
    h = study.freeze_halves(csv_path, path)
    assert len(h) == 24 and "https://x/no" not in h              # usable rows only
    for lang in ("java", "go"):
        for tier in ("low", "mid", "high"):
            ks = [r["url"] for r in rows if r.get("language") == lang and r.get("tier") == tier]
            ex = sum(1 for k in ks if h[k] == "explore")
            assert abs(ex - (len(ks) - ex)) <= 1
    assert study.freeze_halves(csv_path, path) == h              # reused on resume
    files.write_csv(csv_path, rows[:20])                          # a different sample now
    try:
        study.freeze_halves(csv_path, path)
        assert False, "a moved split must be refused"
    except RuntimeError as e:
        assert "never moves" in str(e)


def test_run_refuses_to_resume_a_directory_that_would_lose_rows():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "results")
    os.makedirs(out)
    open(os.path.join(out, "run-log.jsonl"), "w").write('{"status": "done"}\n')
    try:
        study.run("whatever.csv", out, None, None)
        assert False, "must refuse: a run log with no study.json"
    except RuntimeError as e:
        assert "study.json" in str(e)
    open(os.path.join(out, "study.json"), "w").write("{not json")
    try:
        study.run("whatever.csv", out, None, None)
        assert False, "must refuse: unreadable study.json"
    except RuntimeError as e:
        assert "cannot be read" in str(e)


# --- dependency locations ---------------------------------------------------------------------

def test_deps_paths_defaults_and_pinned_urls():
    from complexity_concentration_study import deps
    os.environ["CCS_LIB"] = "/tmp/xlib"
    try:
        assert deps.default_lib() == "/tmp/xlib"
        assert deps.pmd_path().endswith(f"pmd-bin-{study.PMD_VERSION}/bin/pmd")
        assert deps.ck_path().endswith(f"ck/ck-{study.CK_VERSION}.jar")
    finally:
        del os.environ["CCS_LIB"]
    lib = tempfile.mkdtemp()
    assert deps.default_pmd(lib) is None and deps.default_ck(lib) is None   # nothing installed
    for p in (deps.pmd_path(lib), deps.ck_path(lib)):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    assert deps.default_pmd(lib) == deps.pmd_path(lib)
    assert deps.default_ck(lib) == deps.ck_path(lib)
    assert study.PMD_VERSION in deps.PMD_URL and study.CK_VERSION in deps.CK_URL


if __name__ == "__main__":
    ok = True
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except Exception as e:
            ok = False
            print(f"  [FAIL] {fn.__name__}: {type(e).__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
