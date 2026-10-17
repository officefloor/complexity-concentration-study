"""Regression tests for the study harness: sampling, usability, oracles and reproducibility.
Each test pins one behaviour so it cannot silently break.

No network: GitHub search, cloning and measurement are replaced by stubs where needed, and
the pinned-clone test uses a local git repository.
"""
import importlib.util
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from god_complexity import extract, grow, metrics, study

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


god_complexity_report = _load(os.path.join(_HERE, "..", "paper", "god_complexity.py"), "gcr")


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


# --- sampling -------------------------------------------------------------------------------

def test_tiers_are_disjoint():
    from god_complexity.sample import TIERS, TIER_BANDS
    assert TIERS["low"].endswith("..999") and TIERS["mid"].startswith("stars:1000")
    assert TIER_BANDS["low"][-1].endswith("..999") and TIER_BANDS["mid"][0].startswith("1000")


def test_band_draw_follows_band_population():
    def fake(lang, band, pool, exclude, pause):
        total = {"200..290": 9000, "291..400": 1000}.get(band, 0)
        return ([{"full_name": f"{band}/{i}", "url": f"{band}-{i}", "stars": 1, "rank": i,
                  "band": band} for i in range(pool)], total, None)
    orig, orig_bands = grow._band_candidates, grow.TIER_BANDS
    grow._band_candidates = fake
    grow.TIER_BANDS = {"low": ["200..290", "291..400"]}
    try:
        order, totals, _ = grow._candidates("java", "low", 400, set(), 0, random.Random(1))
        again, _, _ = grow._candidates("java", "low", 400, set(), 0, random.Random(1))
    finally:
        grow._band_candidates, grow.TIER_BANDS = orig, orig_bands
    assert [c["url"] for c in order] == [c["url"] for c in again]        # seeded
    first = [c["band"] for c in order[:50]]
    assert first.count("200..290") > 35, first                            # ~90% weight


def test_grow_draws_every_tier_equally_and_stops_at_target():
    tmp = tempfile.mkdtemp()
    measured = []

    def fake_candidates(lang, tier, pool, exclude, pause, rng):
        return ([{"full_name": f"{tier}/{i}", "url": f"https://x/{tier}{i}.git", "stars": 1,
                  "rank": i, "band": "b"} for i in range(10)], {"b": 10}, None)

    class _Out:
        stdout = "abc1234\n"

    patches = {
        (grow, "_candidates"): fake_candidates,
        (study, "clone_at"): lambda url, dest, sha=None, timeout=None:
            (os.makedirs(dest, exist_ok=True), measured.append(url))[0],
        (study, "_git"): lambda args, cwd=None: _Out(),
        (study, "_lang"): lambda root: "java",
        (study, "analyse"): lambda root, pmd, ck=None:
            {"n_funcs": 100, "matrix": {"class": {"n_univ": 40, "wmc47_gods": 3}}},
        (study, "tool_versions"): lambda pmd, ck: {},
        (study, "_summary"): lambda rows, *a, **k: None,
    }
    saved = {k: getattr(*k) for k in patches}
    for (mod, name), fn in patches.items():
        setattr(mod, name, fn)
    try:
        grow.grow(["java"], ["high", "mid", "low"], target=6, cap=6, hw=9.0, seed=1, pool=10,
                  min_funcs=50, min_univ=15, pmd=None,
                  out_path=os.path.join(tmp, "s.json"),
                  manifest_path=os.path.join(tmp, "m.json"),
                  repos_path=os.path.join(tmp, "repos.txt"), keep=False, pause=0,
                  max_clones=100)
    finally:
        for (mod, name), fn in saved.items():
            setattr(mod, name, fn)
    tiers = [u.split("/")[-1][:-5].rstrip("0123456789") for u in measured]
    assert sorted(tiers) == sorted(["high"] * 2 + ["mid"] * 2 + ["low"] * 2), tiers
    pins = study.read_repo_pins(os.path.join(tmp, "repos.txt"))
    assert pins and all(sha == "abc1234" for _, sha in pins), pins   # repos.txt is pinned


# --- reproducibility -----------------------------------------------------------------------

def test_read_repo_pins():
    p = os.path.join(tempfile.mkdtemp(), "repos.txt")
    with open(p, "w") as fh:
        fh.write("# header\nhttps://a/x.git 0123abcd   # high, 9 stars\n"
                 "https://a/y.git   # low, 3 stars\n\nhttps://a/z.git notasha\n")
    assert study.read_repo_pins(p) == [("https://a/x.git", "0123abcd"),
                                       ("https://a/y.git", None), ("https://a/z.git", None)]
    assert study.read_repo_list(p) == ["https://a/x.git", "https://a/y.git", "https://a/z.git"]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_clone_at_checks_out_the_pinned_commit():
    src = tempfile.mkdtemp()
    _git(src, "init", "--quiet")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    _git(src, "config", "uploadpack.allowAnySHA1InWant", "true")
    for i in range(2):
        with open(os.path.join(src, "f.txt"), "w") as fh:
            fh.write(str(i))
        _git(src, "add", "f.txt")
        _git(src, "commit", "--quiet", "-m", f"c{i}")
    first = _git(src, "rev-list", "--max-parents=0", "HEAD")
    dest = os.path.join(tempfile.mkdtemp(), "clone")
    assert study.clone_at("file://" + src, dest, first) is None
    assert _git(dest, "rev-parse", "HEAD") == first
    assert open(os.path.join(dest, "f.txt")).read() == "0"


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
    halves = [god_complexity_report.half_of(u) for u in urls]
    assert halves == [god_complexity_report.half_of(u) for u in urls]
    assert 150 < halves.count("confirm") < 250


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
