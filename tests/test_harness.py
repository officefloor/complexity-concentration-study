"""Regression tests for the study harness: sampling, usability, oracles and reproducibility.
Each test pins one behaviour so it cannot silently break.

No network: the study-run test drives the sampler's run loop over a local git repository named
in a sample CSV, so cloning at the pinned commit and measuring run for real.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import metrics, study

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


complexity_concentration_study_report = _load(os.path.join(_HERE, "..", "paper", "analyse.py"), "gcr")


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
    # threshold 1: precision 1/2, recall +1/2; threshold 0: precision 2/4, recall +1/2
    assert seen == {0.5}, seen


def test_average_precision_perfect_ranking_is_one():
    _, ap, _, _ = metrics.auc_ap({"a": 3, "b": 2, "c": 1}, {"a"}, {"a", "b", "c"})
    assert ap == 1.0


# --- a study run measures each sampled repository at its pinned commit ----------------------

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_run_measures_each_usable_sampled_repository_at_its_commit():
    from open_source_repository_sampler import files
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
    tmp = tempfile.mkdtemp()
    sample = os.path.join(tmp, "open-source-repository-sample.csv")
    files.write_csv(sample, [
        {"draw": 1, "status": "usable", "url": "file://" + src, "full_name": "o/proj",
         "commit": sampled, "commit_date": "2026-01-02T03:04:05+00:00", "language": "python",
         "stratum_language": "python", "tier": "low", "stars": 300, "rank": 4},
        {"draw": 2, "status": "excluded", "reason": "n_functions 3 < 50", "url": "file:///nope",
         "full_name": "o/small", "commit": "0" * 40, "language": "python"}])
    out = os.path.join(tmp, "results")
    rows = study.run(sample, out, None, None)
    assert [r["full_name"] for r in rows] == ["o/proj"]          # the excluded row is not run
    r = rows[0]
    assert (r["commit"], r["lang"], r["tier"], r["stars"], r["date"]) == (
        sampled, "python", "low", 300, "2026-01-02")
    assert r["n_funcs"] == 20 * 60 and study.is_usable(r)        # later.py's function absent
    assert sorted(os.listdir(out)) == ["run-log.jsonl", "study.csv", "study.json",
                                       "study.units.jsonl"]
    assert study.run(sample, out, None, None) == rows            # resumed: nothing re-measured
    anc = os.path.join(tmp, "anc")
    study.write_anc(rows, anc, frame_files=[sample])
    assert sorted(os.listdir(anc)) == ["README.txt", "open-source-repository-sample.csv",
                                       "results.csv"]
    readme = open(os.path.join(anc, "README.txt")).read()
    assert "{base}_sum" in readme and "1 usable repositories" in readme


# --- oracles are keyed by path, over the measured files ------------------------------------

FAKE_PMD = r'''#!{py}
import json, sys
files = [l.strip() for l in open(sys.argv[sys.argv.index("--file-list") + 1]) if l.strip()]
out = {{"files": [{{"filename": f, "violations": [{{"rule": "GodClass"}}]}}
                  for f in files if "GODMARK" in open(f).read()]}}
json.dump(out, sys.stdout)
open({log!r}, "w").write("\n".join(files))
'''


def test_pmd_is_path_keyed_and_runs_on_measured_files_only():
    root = tempfile.mkdtemp()
    java = "class Util {{ {0} void a(int x) {{ b(x, x); }} void b(int p, int q) {{ }} }}"
    files = {"core/src/main/java/a/Util.java": java.format("/* GODMARK */"),
             "web/src/main/java/b/Util.java": java.format(""),
             "core/src/test/java/a/UtilTest.java": java.format("/* GODMARK */")}
    for rel, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        open(os.path.join(root, rel), "w").write(body)
    log = os.path.join(tempfile.mkdtemp(), "pmd-files.txt")
    pmd = os.path.join(tempfile.mkdtemp(), "pmd")
    open(pmd, "w").write(FAKE_PMD.format(py=sys.executable, log=log))
    os.chmod(pmd, 0o755)
    by = study._pmd_violations(pmd, root, sorted(f for f in files if "/test/" not in f))
    assert by["GodClass"] == {"core/src/main/java/a/Util.java"}, by
    passed = open(log).read().splitlines()
    assert not any("UtilTest" in p for p in passed) and len(passed) == 2, passed


# --- the explore/confirm split is deterministic and balanced --------------------------------

def test_explore_confirm_split_is_deterministic_and_balanced():
    urls = [f"https://github.com/o/r{i}.git" for i in range(400)]
    halves = [complexity_concentration_study_report.half_of(u) for u in urls]
    assert halves == [complexity_concentration_study_report.half_of(u) for u in urls]
    assert 150 < halves.count("confirm") < 250


# --- reporter statistics for the conservation / no-calibration sections ---------------------

def test_spearman_matches_hand_values():
    gcr = complexity_concentration_study_report
    assert abs(gcr.spearman([1, 2, 3, 4], [1, 2, 3, 4]) - 1.0) < 1e-9
    assert abs(gcr.spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-9
    assert abs(gcr.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) - 0.8) < 1e-9   # 1-6*4/120


def test_best_global_cutoff_finds_the_separating_threshold():
    gcr = complexity_concentration_study_report
    # values 1..6, gods {5,6}: a single cutoff >=5 separates them perfectly (MCC 1.0)
    m, k, p, r = gcr.best_global_cutoff([(1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (6, 1)])
    assert round(m, 6) == 1.0 and k == 5 and p == 1.0 and r == 1.0
    assert gcr.best_global_cutoff([(1, 0), (2, 0)]) is None       # no gods


def test_bootstrap_ci_brackets_a_constant_and_needs_enough():
    gcr = complexity_concentration_study_report
    lo, hi = gcr.bootstrap_ci([0.9] * 50)
    assert abs(lo - 0.9) < 1e-9 and abs(hi - 0.9) < 1e-9
    assert gcr.bootstrap_ci([0.5, 0.5]) is None                   # fewer than 5 repos


# --- dependency locations and results resolution --------------------------------------------

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


def test_reporter_latest_results_dir():
    gcr = complexity_concentration_study_report
    base = tempfile.mkdtemp()
    os.environ["CCS_RESULTS"] = base
    try:
        assert gcr._latest_results_dir() is None                 # empty: nothing to pick
        for d in ("2026-10-10", "2026-10-18", "2026-10-12"):
            os.makedirs(os.path.join(base, d))
            open(os.path.join(base, d, "study.json"), "w").write("[]")
        assert gcr._latest_results_dir() == os.path.join(base, "2026-10-18")   # newest ISO date
    finally:
        del os.environ["CCS_RESULTS"]


# --- preflight (no silent missing data) -----------------------------------------------------

def test_preflight_passes_with_no_java_tools_and_smoke_class_is_god_like():
    # with no PMD/CK, preflight needs only lizard + git (both present here)
    study.preflight(None, None)        # must not raise
    assert study._tool_problems(None, None) == []
    src = study._java_smoke_source()
    assert src.count("public int m") == 30 and src.count("public int f") == 16


def test_preflight_hard_fails_on_version_drift():
    # an exact-pin mismatch is fatal (no runtime override): forcing the lizard pin off its
    # installed value must abort preflight, so every run/review uses identical tools.
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


# --- pinned tools ---------------------------------------------------------------------------

def test_installed_lizard_is_the_pinned_one_and_sees_annotated_classes():
    assert study._lizard_version() == study.LIZARD_VERSION
    study.check_parser()          # raises ParserBlind under the lizard 1.24 Java regression


def test_pmd_version_skips_the_ascii_banner():
    fake = os.path.join(tempfile.mkdtemp(), "pmd")
    open(fake, "w").write("#!/bin/sh\necho ' ____  __  __ ____'\necho '|  _ \\\\|  \\\\/  |'\n"
                          "echo 'PMD 7.27.0 (abc, 2026-01-01)'\n")
    os.chmod(fake, 0o755)
    assert study.pmd_version(fake) == "7.27.0"


def test_tool_drift_names_every_mismatch():
    ok = {"lizard": study.LIZARD_VERSION, "pmd": study.PMD_VERSION,
          "ck_sha256": study.CK_SHA256}
    assert study.tool_drift(ok) == []
    bad = {"lizard": "1.24.1", "pmd": "7.0.0", "ck_sha256": "0" * 64}
    assert len(study.tool_drift(bad)) == 3


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
