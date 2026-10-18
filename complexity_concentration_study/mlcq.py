"""Convert the MLCQ code-smell data set (Madeyski and Lewowski 2020, Zenodo 3666840) into the
study's label and sample files, for the human-label sub-study.

    complexity-concentration-study mlcq --download --out-dir labels/      # fetch from Zenodo
    complexity-concentration-study mlcq --input MLCQCodeSmellSamples.csv --out-dir labels/

MLCQCodeSmellSamples.csv (semicolon-separated, UTF-8; sha256 MLCQ_SHA256, verified on
--download and reported otherwise) holds one row per REVIEW: sample_id, reviewer_id, smell
(blob, data class, feature envy, long method), severity (none, minor, major, critical), type
(class or function), code_name, repository (a git URL, SSH form in the published file: it is
normalised to https://github.com/owner/name so the run loop clones anonymously), commit_hash,
path, start_line, end_line. Several reviewers graded the same sample, so one label per sample
needs an aggregation rule; the rule is a pre-registered choice (--rule):

    majority  (default) a sample is positive when a strict majority of its reviews grade the
              smell above 'none'
    any       positive when any review does
    all       positive when every review does

Two god smells are converted: Blob (class level, the file at `path`) becomes the label `blob`,
and Long Method (function level, `path` + `start_line`) becomes `long_method`. For each, a
companion label `<label>_reviewed` lists EVERY reviewed sample, positive or not: MLCQ reviewed a
sample of the classes of each project, so an unreviewed class is unknown, not a negative, and
the harness scores the human definition within the reviewed units (study.register_human).

Writes, into --out-dir:
    mlcq-labels.csv   repo, commit, path, label, line   (the --labels file)
    mlcq-repos.csv    the sample CSV (sampler columns) listing each labelled repository at
                      its labelled commit, one commit per repository (the commit with the
                      most reviewed samples; the others are reported and dropped)
    mlcq-summary.json counts, the rule, the dropped commits, the input's sha256
Then:  ./step3_run.sh is for sampled runs; for this one call the CLI directly:
    .venv/bin/python -m complexity_concentration_study.cli study \\
        --sample labels/mlcq-repos.csv --labels labels/mlcq-labels.csv --out-dir results/mlcq
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

MLCQ_SHA256 = "8e05db55150a984f0b08ab211f5f612374790ea918ba08afc290cf122b63551b"
MLCQ_URL = "https://zenodo.org/records/3666840/files/MLCQCodeSmellSamples.csv?download=1"
MLCQ_FILE = "MLCQCodeSmellSamples.csv"
SMELLS = {"blob": ("blob", "class"), "long method": ("long_method", "function")}
RULES = ("majority", "any", "all")


_GITHUB = re.compile(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", re.I)


def _norm_repo(url: str) -> str:
    """A repository as an anonymous HTTPS clone URL: the published file uses the SSH form
    (git@github.com:owner/name.git), which would need keys to clone."""
    u = url.strip()
    m = _GITHUB.search(u)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}"
    u = u.rstrip("/")
    return u[:-4] if u.endswith(".git") else u


def full_name_of(url: str) -> str:
    m = _GITHUB.search(url.strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    parts = _norm_repo(url).rsplit("/", 2)
    return "/".join(parts[-2:])


def fetch(dest_dir: str, force: bool = False) -> str:
    """Download MLCQCodeSmellSamples.csv from Zenodo into `dest_dir`, verify its sha256 against
    the datasheet's, and return its path. An existing file with the right checksum is kept."""
    import urllib.request
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, MLCQ_FILE)
    if os.path.exists(path) and not force and _sha256(path) == MLCQ_SHA256:
        return path
    tmp = path + ".part"
    with urllib.request.urlopen(MLCQ_URL, timeout=300) as resp, open(tmp, "wb") as fh:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            fh.write(chunk)
    got = _sha256(tmp)
    if got != MLCQ_SHA256:
        os.unlink(tmp)
        raise RuntimeError(f"downloaded MLCQ file sha256 {got} != pinned {MLCQ_SHA256}; the "
                           f"Zenodo record may have a new version -- check it and re-pin")
    os.replace(tmp, path)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_reviews(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def aggregate(reviews: list[dict], rule: str = "majority", smells=("blob", "long method"),
              min_reviews: int = 1) -> dict:
    """{(repo, commit, path, type, sample_id, start_line): {"smell", "label", "level",
    "reviews", "positive", "is_positive"}} over the chosen smells. The published file carries a
    sample_id; a file without one is keyed by code_name instead."""
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}")
    agg: dict = {}
    for r in reviews:
        smell = (r.get("smell") or "").strip().lower()
        if smell not in smells or smell not in SMELLS:
            continue
        label, want_type = SMELLS[smell]
        typ = (r.get("type") or "").strip().lower()
        if typ != want_type:
            continue
        repo = _norm_repo(r.get("repository") or "")
        commit = (r.get("commit_hash") or "").strip().lower()
        path = (r.get("path") or "").strip().lstrip("/")
        line = (r.get("start_line") or "").strip()
        if not (repo and commit and path) or (want_type == "function" and not line):
            continue
        sid = (r.get("sample_id") or r.get("code_name") or "").strip()
        key = (repo, commit, path, typ, sid, line)
        a = agg.setdefault(key, {"smell": smell, "label": label,
                                 "level": "class" if typ == "class" else "method",
                                 "reviews": 0, "positive": 0})
        a["reviews"] += 1
        if (r.get("severity") or "").strip().lower() not in ("none", ""):
            a["positive"] += 1
    out = {}
    for key, a in agg.items():
        if a["reviews"] < min_reviews:
            continue
        n, k = a["reviews"], a["positive"]
        a["is_positive"] = ((2 * k > n) if rule == "majority" else
                            (k >= 1) if rule == "any" else (k == n))
        out[key] = a
    return out


def choose_commits(agg: dict) -> tuple[dict, dict]:
    """One commit per repository: the one with the most reviewed samples (ties: the first in
    sort order). Returns ({repo: commit}, {repo: [dropped commits]})."""
    counts: dict = defaultdict(lambda: defaultdict(int))
    for (repo, commit, *_rest) in agg:
        counts[repo][commit] += 1
    chosen, dropped = {}, {}
    for repo, by in counts.items():
        best = sorted(by, key=lambda c: (-by[c], c))
        chosen[repo] = best[0]
        if len(best) > 1:
            dropped[repo] = best[1:]
    return chosen, dropped


def write_outputs(agg: dict, out_dir: str, rule: str, input_sha: str | None) -> dict:
    from open_source_repository_sampler import files as sfiles
    os.makedirs(out_dir, exist_ok=True)
    chosen, dropped = choose_commits(agg)
    labels_path = os.path.join(out_dir, "mlcq-labels.csv")
    counts: dict = defaultdict(int)
    with open(labels_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["repo", "commit", "path", "label", "line"])
        w.writeheader()
        for (repo, commit, path, typ, _name, line), a in sorted(agg.items()):
            if chosen[repo] != commit:
                counts["dropped_other_commit"] += 1
                continue
            ln = line if a["level"] == "method" else ""
            w.writerow({"repo": repo, "commit": commit, "path": path,
                        "label": a["label"] + "_reviewed", "line": ln})
            counts[a["label"] + "_reviewed"] += 1
            if a["is_positive"]:
                w.writerow({"repo": repo, "commit": commit, "path": path,
                            "label": a["label"], "line": ln})
                counts[a["label"]] += 1
    rows = []
    for i, repo in enumerate(sorted(chosen), 1):
        rows.append({"draw": i, "status": "usable", "reason": "", "url": repo,
                     "full_name": full_name_of(repo), "commit": chosen[repo], "commit_date": "",
                     "language": "java", "language_share": "", "github_language": "Java",
                     "mirror": "", "stratum_language": "java", "tier": "labelled",
                     "star_band": "", "stars": "", "rank": "", "n_source_files": "",
                     "n_functions": "", "n_files_with_functions": "", "nloc": "",
                     "n_unparsed_files": "", "n_commits": "", "n_contributors": "",
                     "first_commit_date": "", "sampler_version": "mlcq-converter",
                     "sampler_commit": ""})
    sample_path = os.path.join(out_dir, "mlcq-repos.csv")
    sfiles.write_csv(sample_path, rows)
    summary = {"rule": rule, "input_sha256": input_sha,
               "input_is_mlcq_1_1": (input_sha == MLCQ_SHA256) if input_sha else None,
               "repositories": len(rows), "samples": len(agg), "labels": dict(counts),
               "dropped_commits": dropped, "labels_csv": labels_path, "sample_csv": sample_path}
    with open(os.path.join(out_dir, "mlcq-summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study mlcq",
                                 description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--input", default=None, help="MLCQCodeSmellSamples.csv (or --download)")
    ap.add_argument("--download", action="store_true",
                    help=f"fetch the file from Zenodo into --out-dir and verify its sha256")
    ap.add_argument("--out-dir", default="labels")
    ap.add_argument("--rule", choices=RULES, default="majority")
    ap.add_argument("--smells", default="blob,long method",
                    help="comma-separated subset of: blob, long method")
    ap.add_argument("--min-reviews", type=int, default=1)
    args = ap.parse_args(argv)
    if args.download:
        args.input = fetch(args.out_dir)
        print(f"MLCQ 1.1 at {args.input} (sha256 verified)", file=sys.stderr)
    elif not args.input:
        ap.error("pass --input FILE or --download")
    sha = _sha256(args.input)
    if sha != MLCQ_SHA256:
        print(f"NOTE: input sha256 {sha[:12]}... is not MLCQ 1.1's ({MLCQ_SHA256[:12]}...); "
              f"state the version used.", file=sys.stderr)
    smells = tuple(s.strip().lower() for s in args.smells.split(",") if s.strip())
    agg = aggregate(read_reviews(args.input), args.rule, smells, args.min_reviews)
    summary = write_outputs(agg, args.out_dir, args.rule, sha)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
