"""The classpath validation: PMD is run twice over the study's own Java file list, with and
without --aux-classpath, and every class finding that flips is reported."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import classpath_check

FAKE = '''#!{py}
import json, sys
if "--version" in sys.argv:
    print("PMD 7.27.0 (x)"); sys.exit(0)
files = [l.strip() for l in open(sys.argv[sys.argv.index("--file-list") + 1]) if l.strip()]
cp = sys.argv[sys.argv.index("--aux-classpath") + 1] if "--aux-classpath" in sys.argv else ""
out = {{"files": []}}
for f in files:
    v = []
    if "A.java" in f and "dep1.jar" in cp:
        v.append({{"rule": "GodClass", "beginline": 1, "description": "x"}})
    if "B.java" in f and not cp:
        v.append({{"rule": "GodClass", "beginline": 1, "description": "x"}})
    if "A.java" in f:
        v.append({{"rule": "TooManyFields", "beginline": 1, "description": "x"}})
    out["files"].append({{"filename": f, "violations": v}})
json.dump(out, sys.stdout)
'''


def _repo():
    root = tempfile.mkdtemp()
    for d in ("src/main/java", "src/test/java", "target/classes", "mod/build/classes/java/main",
              "src/main/java/org/x/target"):
        os.makedirs(os.path.join(root, d))
    for n in ("A", "B"):
        open(os.path.join(root, "src/main/java", f"{n}.java"), "w").write(f"class {n} {{ void f() {{ }} }}\n")
    open(os.path.join(root, "src/test/java/ATest.java"), "w").write("class ATest { void f() { } }\n")
    pmd = os.path.join(root, "pmd")
    open(pmd, "w").write(FAKE.format(py=sys.executable))
    os.chmod(pmd, 0o755)
    cp = os.path.join(root, "cp.txt")
    open(cp, "w").write("/x/dep1.jar:/x/dep2.jar\n")
    return root, pmd, cp


def test_compare_reports_flips_both_ways_over_the_measured_files_only():
    root, pmd, cp = _repo()
    rep = classpath_check.compare(pmd, root, classpath_check.read_classpath_file(cp))
    assert rep["n_java_files"] == 2 and rep["aux_classpath_entries"] == 2      # test file excluded
    g = rep["rules"]["GodClass"]
    assert (g["without"], g["with"]) == (1, 1)
    assert g["gained"] == ["src/main/java/A.java"] and g["lost"] == ["src/main/java/B.java"]
    assert rep["godclass_flips"] == 2 and rep["godclass_flip_rate"] == 1.0
    assert rep["rules"]["TooManyFields"] == {"without": 1, "with": 1, "gained": [], "lost": []}
    assert rep["pmd"] == "7.27.0"


def test_build_output_dirs_and_main():
    root, pmd, cp = _repo()
    dirs = [os.path.relpath(d, root) for d in classpath_check.build_output_dirs(root)]
    assert dirs == ["mod/build/classes/java/main", "target/classes"]
    out = os.path.join(root, "r.json")
    assert classpath_check.main(["--repo", root, "--pmd", pmd, "--classpath-file", cp,
                                 "--url", "o/r", "--out", out]) == 0
    rep = json.load(open(out))
    assert rep["aux_classpath_entries"] == 4                     # 2 jars + 2 build dirs
    assert rep["url"] == "o/r"                                   # named, so its half can be checked
    assert classpath_check.main(["--repo", root, "--pmd", pmd, "--no-build-output"]) == 2  # no cp


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
