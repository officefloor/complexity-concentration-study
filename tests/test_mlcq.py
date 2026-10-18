"""The MLCQ converter: the datasheet's column layout (semicolon-separated reviews), the
aggregation rules, one commit per repository, the *_reviewed companions, and that the outputs
load as the harness's --labels and --sample files at both levels."""
import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import mlcq, study

COLS = ["id", "reviewer_id", "smell", "severity", "review_timestamp", "type", "code_name",
        "repository", "commit_hash", "path", "start_line", "end_line",
        "is_from_industry_relevant_project", "link"]
R1, R2 = "https://github.com/apache/foo.git", "https://github.com/bar/baz"


def _csv():
    rows = []

    def add(rid, smell, sev, typ, name, repo, commit, path, s, e):
        rows.append(dict(zip(COLS, [len(rows) + 1, rid, smell, sev, "2019-04-01 10:00:00.000",
                                    typ, name, repo, commit, path, s, e, "True", "http://x"])))
    add(1, "Blob", "major", "class", "a.Big", R1, "AAA1", "src/a/Big.java", 1, 200)
    add(2, "Blob", "none", "class", "a.Big", R1, "AAA1", "src/a/Big.java", 1, 200)
    add(3, "Blob", "minor", "class", "a.Big", R1, "AAA1", "src/a/Big.java", 1, 200)
    add(1, "Blob", "none", "class", "a.Small", R1, "AAA1", "src/a/Small.java", 1, 20)
    add(2, "Blob", "none", "class", "a.Small", R1, "AAA1", "src/a/Small.java", 1, 20)
    add(1, "Blob", "critical", "class", "a.Old", R1, "BBB2", "src/a/Old.java", 1, 20)
    add(1, "Long Method", "major", "function", "b.C#f", R2, "CCC3", "src/b/C.java", 40, 120)
    add(2, "Long Method", "none", "function", "b.C#f", R2, "CCC3", "src/b/C.java", 40, 120)
    add(1, "Long Method", "major", "function", "b.C#g", R2, "CCC3", "src/b/C.java", 130, 300)
    add(1, "Data Class", "major", "class", "b.D", R2, "CCC3", "src/b/D.java", 1, 10)
    path = os.path.join(tempfile.mkdtemp(), "MLCQCodeSmellSamples.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return path


def test_aggregation_rules():
    reviews = mlcq.read_reviews(_csv())
    maj = mlcq.aggregate(reviews, "majority")
    assert len(maj) == 5                                        # Data Class is not converted
    big = maj[("https://github.com/apache/foo", "aaa1", "src/a/Big.java", "class", "a.Big", "1")]
    assert (big["reviews"], big["positive"], big["is_positive"], big["level"]) == (3, 2, True, "class")
    f = maj[("https://github.com/bar/baz", "ccc3", "src/b/C.java", "function", "b.C#f", "40")]
    assert f["is_positive"] is False and f["level"] == "method"   # 1 of 2 is not a majority
    assert mlcq.aggregate(reviews, "any")[("https://github.com/bar/baz", "ccc3", "src/b/C.java",
                                           "function", "b.C#f", "40")]["is_positive"] is True
    assert mlcq.aggregate(reviews, "all")[("https://github.com/apache/foo", "aaa1",
                                           "src/a/Big.java", "class", "a.Big", "1")]["is_positive"] is False
    assert len(mlcq.aggregate(reviews, "majority", min_reviews=2)) == 3
    chosen, dropped = mlcq.choose_commits(maj)
    assert chosen["https://github.com/apache/foo"] == "aaa1" and dropped == {
        "https://github.com/apache/foo": ["bbb2"]}


def test_outputs_load_as_labels_and_sample_at_both_levels():
    out = os.path.join(tempfile.mkdtemp(), "labels")
    assert mlcq.main(["--input", _csv(), "--out-dir", out]) == 0
    summary = json.load(open(os.path.join(out, "mlcq-summary.json")))
    assert summary["labels"] == {"blob_reviewed": 2, "blob": 1, "dropped_other_commit": 1,
                                 "long_method_reviewed": 2, "long_method": 1}
    assert summary["input_is_mlcq_1_1"] is False and summary["repositories"] == 2
    labels = study.load_labels(os.path.join(out, "mlcq-labels.csv"))
    hit, other = study.labels_for(labels, R1, "apache/foo", "AAA1")
    assert hit == {"blob_reviewed": {"src/a/Big.java", "src/a/Small.java"},
                   "blob": {"src/a/Big.java"}} and other == []
    hit, _ = study.labels_for(labels, "https://github.com/bar/baz.git", "bar/baz", "ccc3")
    assert hit == {"long_method_reviewed": {("src/b/C.java", 40), ("src/b/C.java", 130)},
                   "long_method": {("src/b/C.java", 130)}}
    from open_source_repository_sampler import files
    rows = files.read_sample(os.path.join(out, "mlcq-repos.csv"))
    assert [(r["full_name"], r["commit"], r["language"], r["tier"]) for r in rows] == [
        ("apache/foo", "aaa1", "java", "labelled"), ("bar/baz", "ccc3", "java", "labelled")]


def test_full_name_of_and_ssh_urls_become_https():
    assert mlcq.full_name_of("https://github.com/Apache/Foo.git") == "Apache/Foo"
    assert mlcq.full_name_of("git@github.com:o/r.git") == "o/r"
    assert mlcq.full_name_of("https://gitlab.com/g/o/r") == "o/r"
    assert mlcq._norm_repo("git@github.com:apache/syncope.git") == "https://github.com/apache/syncope"
    assert mlcq._norm_repo("https://gitlab.com/g/o/r.git/") == "https://gitlab.com/g/o/r"


def test_published_layout_keys_samples_by_sample_id_and_strips_leading_slash():
    """The published file (verified header) has sample_id, lowercase smells, SSH repository
    URLs and a leading slash on path."""
    cols = ["id", "reviewer_id", "sample_id", "smell", "severity", "review_timestamp", "type",
            "code_name", "repository", "commit_hash", "path", "start_line", "end_line", "link",
            "is_from_industry_relevant_project"]
    rows = [[1, 6, 5771277, "blob", "major", "2019-03-27 10:34:53", "class", "a.b.C",
             "git@github.com:apache/syncope.git", "114c412a", "/client/src/main/java/a/b/C.java",
             35, 370, "http://x", "True"],
            [2, 7, 5771277, "blob", "minor", "2019-03-28 10:34:53", "class", "a.b.C",
             "git@github.com:apache/syncope.git", "114c412a", "/client/src/main/java/a/b/C.java",
             35, 370, "http://x", "True"]]
    path = os.path.join(tempfile.mkdtemp(), "MLCQCodeSmellSamples.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols)
        w.writerows(rows)
    agg = mlcq.aggregate(mlcq.read_reviews(path))
    assert list(agg) == [("https://github.com/apache/syncope", "114c412a",
                          "client/src/main/java/a/b/C.java", "class", "5771277", "35")]
    assert agg[list(agg)[0]]["is_positive"] is True
    out = os.path.join(tempfile.mkdtemp(), "labels")
    mlcq.write_outputs(agg, out, "majority", mlcq.MLCQ_SHA256)
    from open_source_repository_sampler import files
    r = files.read_sample(os.path.join(out, "mlcq-repos.csv"))[0]
    assert (r["url"], r["full_name"]) == ("https://github.com/apache/syncope", "apache/syncope")
    assert json.load(open(os.path.join(out, "mlcq-summary.json")))["input_is_mlcq_1_1"] is True


def test_fetch_keeps_a_verified_file_and_refuses_a_wrong_checksum():
    import urllib.request
    d = tempfile.mkdtemp()
    orig = urllib.request.urlopen

    class _Resp:
        def __init__(self, data):
            self.data = data

        def read(self, n=-1):
            out, self.data = self.data, b""
            return out

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    urllib.request.urlopen = lambda url, timeout=0: _Resp(b"not the data set")
    try:
        try:
            mlcq.fetch(d)
            assert False, "a wrong checksum must raise"
        except RuntimeError as e:
            assert "sha256" in str(e) and not os.path.exists(os.path.join(d, mlcq.MLCQ_FILE))
        # an existing file with the right checksum is kept without a download
        good = os.path.join(d, mlcq.MLCQ_FILE)
        open(good, "wb").write(b"")
        mlcq.MLCQ_SHA256, saved = mlcq._sha256(good), mlcq.MLCQ_SHA256
        try:
            urllib.request.urlopen = lambda url, timeout=0: (_ for _ in ()).throw(AssertionError("no download"))
            assert mlcq.fetch(d) == good
        finally:
            mlcq.MLCQ_SHA256 = saved
    finally:
        urllib.request.urlopen = orig


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
