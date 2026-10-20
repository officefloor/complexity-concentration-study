"""Shared helpers for the paper's scripts.

Every script here reads the harness's OUTPUT (results/<run>/analysis.json, study.json and the
per-unit sidecar study.units.jsonl) and the harness's own tested statistics
(complexity_concentration_study.stats, .metrics) by importing the package from the repository
root, so the paper's numbers are computed by the same rules and the same code the study
registered. Standard library only; matplotlib is needed by figures.py alone.

Paths are resolved from this file, so the scripts run from any directory:

    paper/scripts/extract_main.py   --results results/2026-10-19   -> paper/data/main.json
    paper/scripts/extract_mlcq.py   --results results/mlcq         -> paper/data/mlcq.json
    paper/scripts/human_readout.py                                 -> paper/data/human.json
    paper/scripts/agreement.py                                     -> paper/data/agreement.json
    paper/scripts/tables.py                                        -> paper/generated/*.tex
    paper/scripts/figures.py                                       -> paper/figures/*.pdf
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

PAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PAPER)
DATA = os.path.join(PAPER, "data")
GENERATED = os.path.join(PAPER, "generated")
FIGURES = os.path.join(PAPER, "figures")

# The two runs the paper reports. MAIN is the confirmatory seed-2 run; MLCQ the human-label
# sub-study. Override with --results on each script, or these environment variables.
MAIN_RESULTS = os.environ.get("CCS_MAIN_RESULTS", os.path.join(ROOT, "results", "2026-10-19"))
MLCQ_RESULTS = os.environ.get("CCS_MLCQ_RESULTS", os.path.join(ROOT, "results", "mlcq"))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from complexity_concentration_study import metrics, stats, study  # noqa: E402

PLAN = __import__("complexity_concentration_study.analyse", fromlist=["PLAN"]).PLAN
BOOT = {"b": PLAN["bootstrap"]["b"], "seed": PLAN["bootstrap"]["seed"]}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str):
    with open(path) as fh:
        return json.load(fh)


def dump_json(obj, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str)
    os.replace(tmp, path)


def usable_rows(results_dir: str) -> list[dict]:
    """The usable rows of a run, with the heavy per-repository matrix dropped, in the order
    study.json holds them. The same floor the harness analysis applies (study.is_usable)."""
    rows = load_json(os.path.join(results_dir, "study.json"))
    out = []
    for r in rows:
        if not (study.is_usable(r) and r.get("matrix")):
            continue
        m = r["matrix"]
        slim = {k: v for k, v in r.items() if k != "matrix"}
        slim["class_n_univ"] = m["class"].get("n_univ")
        slim["class_n_univ_scope"] = m["class"].get("n_univ_scope")
        slim["method_n_univ"] = m["method"].get("n_univ")
        slim["method_n_univ_scope"] = m["method"].get("n_univ_scope")
        slim["class_oracle_gods"] = m["class"].get("oracle_gods")
        slim["method_oracle_gods"] = m["method"].get("oracle_gods")
        slim["class_diag"] = m["class"].get("diag")
        slim["method_diag"] = m["method"].get("diag")
        # flag rates per rule from the harness's own cells (scope 'all'), for the
        # does-the-constant-transfer diagnostic across languages
        rates = {}
        for level, sig, oracle in (("class", "cognitive_max", "wmc47"), ("method", "cognitive", "cc14"),
                                   ("class", "nloc_sum", "wmc47"), ("method", "cc", "cc14")):
            cells = (m[level].get("cells") or {}).get(sig) or {}
            for rule, by_oracle in cells.items():
                c = (by_oracle or {}).get(oracle)
                if c and c.get("n_univ"):
                    rates[f"{level}:{sig}:{rule}"] = c["n_out"] / c["n_univ"]
        slim["flag_rates"] = rates
        out.append(slim)
    return out


def iter_sidecar(results_dir: str, keep: set | None = None):
    """Stream the per-unit sidecar one repository at a time (it is hundreds of MB, so it is
    never loaded whole). Yields the parsed line for repositories in `keep` (or all)."""
    with open(os.path.join(results_dir, "study.units.jsonl")) as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            if keep is None or d.get("repo") in keep:
                yield d


def fit_indices(units: list[str], exts) -> list[int]:
    """The fitting population of a payload: the units whose file has one of `exts`
    (analyse.Run.block: Java units for a Java-scoped definition, the labelled repository's
    language for a human one), else every unit."""
    if not exts:
        return list(range(len(units)))
    return [i for i, u in enumerate(units) if u.split("::")[0].endswith(tuple(exts))]


def rule_flags(vmap: dict) -> dict:
    """{rule: set of flagged keys} for every relative rule of the study at its default."""
    return {name: algo(vmap) for name, algo in metrics.ALGORITHMS.items()}


def confusion(flagged: set, gods: set, score: list) -> dict:
    tp = sum(1 for i in score if i in flagged and i in gods)
    fp = sum(1 for i in score if i in flagged and i not in gods)
    fn = sum(1 for i in score if i not in flagged and i in gods)
    tn = len(score) - tp - fp - fn
    return {"n_univ": len(score), "n_out": tp + fp, "n_overlap": tp, "n_god_univ": tp + fn,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}
