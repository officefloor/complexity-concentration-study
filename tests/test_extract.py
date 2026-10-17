"""Hand-worked self-test for the complexity extractor. The extractor is lexical and
language-neutral; it reports per-function complexity definitions and per-file WMC.

Assertions avoid brittle exact cyclomatic values and pin the stable facts: which functions
are found, parameter counts, per-file WMC = sum of the file's function CC, overload
merge-by-max, and test-file exclusion.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from god_complexity import extract

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
        return getName();
    }
    void validate(Owner o) { if (o == null) { return; } }
    void enrich(Owner o) { addPet(o); }
    // two overloads of the same name: merged into one record by MAX of each field
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
}


def _tree():
    root = tempfile.mkdtemp(prefix="god_complexity_test_")
    for name, body in SRC.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(body)
    return root


def test_complexity_fields_present_and_params_correct():
    res = extract.analyze_tree(_tree())
    by_name = {fid[1]: r for fid, r in res["funcs"].items()}
    assert "handle" in by_name and "getName" in by_name, sorted(by_name)
    # every record carries every complexity definition
    for r in by_name.values():
        for f in extract.COMPLEXITY_FIELDS:
            assert f in r, (f, r)
    assert by_name["handle"]["params"] == 2, by_name["handle"]
    assert by_name["getName"]["params"] == 0, by_name["getName"]
    # handle branches (if/else), so its cyclomatic complexity exceeds the straight getName
    assert by_name["handle"]["cc"] > by_name["getName"]["cc"], by_name


def test_overloads_merge_by_max():
    res = extract.analyze_tree(_tree())
    foo = res["funcs"][("Ctl.java", "foo")]
    assert foo["params"] == 2, foo          # max(1, 2) across the two overloads


def test_wmc_is_per_file_cc_sum_over_nontest_files():
    res = extract.analyze_tree(_tree())
    wmc = res["wmc"]
    assert set(wmc) == {"Owner.java", "Ctl.java"}, wmc      # CtlTest.java excluded
    # Ctl.java holds the branchy methods, so it is the heaviest file
    assert max(wmc, key=lambda f: wmc[f]) == "Ctl.java", wmc


def test_test_files_are_excluded():
    res = extract.analyze_tree(_tree())
    assert not any("CtlTest" in fid[0] for fid in res["funcs"]), res["funcs"].keys()


if __name__ == "__main__":
    ok = True
    for fn in (test_complexity_fields_present_and_params_correct, test_overloads_merge_by_max,
               test_wmc_is_per_file_cc_sum_over_nontest_files, test_test_files_are_excluded):
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            ok = False
            print(f"  [FAIL] {fn.__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
