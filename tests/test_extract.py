"""Hand-worked self-test for the complexity extractor. The extractor is lexical and
language-neutral; it reports per-function complexity definitions and per-file WMC.

Assertions avoid brittle exact cyclomatic values and pin the stable facts: which functions
are found, that every unit is its own record (overloads are NOT merged), parameter counts,
that per-file WMC equals the class-level cc_sum exactly, that nesting is alive, and that
test files are excluded.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import extract, metrics

SRC = {
    "Owner.java": """package t;
public class Owner {
    public String getName() { return name; }
    public void addPet(Pet p) { String s = p.toString(); }
}
""",
    "Ctl.java": """package t;
public class Ctl {
    public String handle(Owner o, int id) {
        if (id > 0) { validate(o); } else { enrich(o); }
        for (int i = 0; i < id; i++) { if (i % 2 == 0) { enrich(o); } }
        return getName();
    }
    void validate(Owner o) { if (o == null) { return; } }
    void enrich(Owner o) { addPet(o); }
    // two overloads of the same name: two UNITS, keyed by start line
    int foo(int a) { return a; }
    int foo(int a, int b) { return a + b; }
}
""",
    # a test class, in a test DIRECTORY (Java test exclusion is by directory, not filename)
    "src/test/java/CtlTest.java": """package t;
public class CtlTest {
    public void testHandle() { for (int i = 0; i < 10; i++) { assertTrue(i >= 0); } }
}
""",
    "lib.php": """<?php
function deep($x, $y, $z = array(1, 2), ?string $w = null, ...$v) { if ($x) { return $y; } return $z; }
function one($a) { return $a; }
""",
}


def _tree():
    root = tempfile.mkdtemp(prefix="ccs_test_")
    for name, body in SRC.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(body)
    return root


def test_complexity_fields_present_and_params_correct():
    res = extract.analyze_tree(_tree())
    by_name = {r["name"]: r for r in res["funcs"].values() if r["name"] != "foo"}
    assert "handle" in by_name and "getName" in by_name, sorted(by_name)
    for r in res["funcs"].values():                   # every record carries every definition
        for f in extract.COMPLEXITY_FIELDS:
            assert f in r, (f, r)
        assert r["start_line"] <= r["end_line"]
    assert by_name["handle"]["params"] == 2, by_name["handle"]
    assert by_name["getName"]["params"] == 0, by_name["getName"]
    assert by_name["handle"]["cc"] > by_name["getName"]["cc"], by_name
    # nesting is alive: handle nests for > if (depth 2); getName nests nothing
    assert by_name["handle"]["nesting"] == 2 and by_name["getName"]["nesting"] == 0, by_name
    assert by_name["handle"]["cognitive"] > 0


def test_overloads_are_separate_units_keyed_by_start_line():
    res = extract.analyze_tree(_tree())
    foos = sorted((fid, r) for fid, r in res["funcs"].items() if r["name"] == "foo")
    assert len(foos) == 2, foos
    assert [r["params"] for _, r in foos] == [1, 2]
    assert all(fid == extract.function_id("Ctl.java", "foo", r["start_line"]) for fid, r in foos)
    assert foos[0][0][1] == f"foo@{foos[0][1]['start_line']}"


def test_wmc_equals_class_cc_sum_exactly_over_nontest_files():
    res = extract.analyze_tree(_tree())
    wmc = res["wmc"]
    assert set(wmc) == {"Owner.java", "Ctl.java", "lib.php"}, wmc      # CtlTest.java excluded
    cc_sum = metrics.matrix_outliers(res["funcs"], wmc)["class"]["_vals"]["cc_sum"]
    assert all(cc_sum[f] == wmc[f] for f in wmc), (cc_sum, wmc)
    assert max(wmc, key=lambda f: wmc[f]) == "Ctl.java", wmc


def test_test_files_are_excluded():
    res = extract.analyze_tree(_tree())
    assert not any("CtlTest" in r["file"] for r in res["funcs"].values())


def test_generated_and_oversize_files_leave_the_universe_but_are_counted():
    root = _tree()
    os.makedirs(os.path.join(root, "gen"))
    open(os.path.join(root, "gen", "Msg.pb.go"), "w").write("package g\nfunc f() { if true { } }\n")
    open(os.path.join(root, "app_pb2.py"), "w").write("def f():\n    return 1\n")
    with open(os.path.join(root, "Huge.java"), "w") as fh:
        fh.write("class Huge { void f() { } }\n// " + "x" * (extract.MAX_FILE_BYTES + 10) + "\n")
    scan = extract.scan_files(root)
    assert sorted(scan["generated"]) == ["app_pb2.py", "gen/Msg.pb.go"]
    assert scan["oversize"] == ["Huge.java"]
    assert not any(f in scan["source"] for f in ("app_pb2.py", "gen/Msg.pb.go", "Huge.java"))
    res = extract.analyze_tree(root)
    assert res["skipped"]["oversize"] == ["Huge.java"] and len(res["skipped"]["generated"]) == 2
    assert res["skipped"]["unparsed"] == [] and "Huge.java" not in res["wmc"]


def test_build_dirs_are_skipped_at_the_root_only_like_the_sampler():
    root = _tree()
    for d in ("target", "src/org/spring/aop/target"):
        os.makedirs(os.path.join(root, d))
        open(os.path.join(root, d, "T.java"), "w").write("class T { void f() { } }\n")
    src = set(extract.source_files(root))
    assert "src/org/spring/aop/target/T.java" in src and "target/T.java" not in src


def test_php_parameters_are_counted_lexically():
    res = extract.analyze_tree(_tree())
    php = {r["name"]: r for r in res["funcs"].values() if r["file"] == "lib.php"}
    assert php["deep"]["params"] == 5 and php["one"]["params"] == 1, php
    assert extract._php_param_count("function f() {") == 0


def test_signal_inputs_name_real_signals():
    for sig, inputs in extract.SIGNAL_INPUTS.items():
        assert sig in extract.COMPLEXITY_FIELDS
        assert inputs <= set(extract.COMPLEXITY_FIELDS)


if __name__ == "__main__":
    ok = True
    for k, fn in sorted(globals().items()):
        if k.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                ok = False
                print(f"  [FAIL] {fn.__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
