"""The analysis of a run, to the README's rules ('Analysing a run') and PLAN.md.

    complexity-concentration-study analyse [--results results/<date>] [--json analysis.json]

Reads study.json, study.units.jsonl and oracles.json from the results directory (the latest
results/<date> by default), prints the report and writes analysis.json beside the run. The
first analysis of a run is its confirmatory analysis: analysis.json is written once and never
overwritten; a later run of this command refuses unless `--exploratory`, which writes a dated
analysis.exploratory.<utc>.json beside it.

`PLAN` below is the machine-readable form of PLAN.md: the primary estimand, the DECISION rule
that reads it (a paired bootstrap over confirm repositories of the relative rule against the
tuned absolute cutoff, a non-inferiority margin, an AUC floor, and the minimum effective
sample below which the primary is reported as underpowered), the families a headline signal
may come from, the minimum positives, the Friedman subsets and the bootstrap. It is committed
and tagged before the confirmatory sample is drawn; changing it afterwards makes the run
exploratory.

The explore/confirm half of every repository is assigned by the harness from the sample CSV
before any repository is measured (`study.run`, halves.json) and recorded in its row. The
analysis reads that recorded half; it falls back to computing the split only for a run that
predates the freeze, and says so in the diagnostics.

Every accuracy number in the report is computed from the per-unit sidecar with one code path
(`Run.block`): a definition's units are its own scope (Java units for a Java tool definition;
the reviewed units for a human definition), the relative rules are fitted on that scope's
fitting population exactly as the harness fits them, and god-free repositories are kept. The
harness's own cells are used only as a cross-check and for the exploratory best-cell table.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

from . import metrics, stats, study

PLAN = {
    "primary": {"level": "class", "definition": "pmd_GodClass",
                "families": ["peak", "density"], "rule": "mad_z"},
    # The decision rule (PLAN.md, 'Decision rule'). The head-to-head is PAIRED: both rules are
    # read on the same confirm repositories and the bootstrap resamples repositories, so the
    # interval is on the DIFFERENCE. Non-inferiority must hold on the macro (one repository,
    # one vote) AND the micro (pooled) MCC, because the macro MCC is 0 in a god-free repository
    # whatever was flagged and only the micro number sees those false positives.
    "decision": {
        "statistic": "relative rule at default minus absolute cutoff tuned on explore, on the "
                     "same confirm repositories, 95% paired percentile bootstrap, on three arms",
        # The three arms, each a paired difference; the verdict is the WEAKEST of them.
        #   macro_mcc  mean per-repository MCC, over the repositories with >= 1 positive (in a
        #              god-free repository the MCC is 0 for both rules by convention, and such
        #              0 - 0 pairs would only narrow the interval)
        #   micro_mcc  pooled MCC over every repository carrying the definition, god-free ones
        #              included: the arm that sees the false positives in god-free repositories
        #   macro_fpr  mean per-repository false-positive rate, every repository; LOWER is
        #              better, so its margin is read the other way round
        "arms": ["macro_mcc", "micro_mcc", "macro_fpr"],
        "macro_mcc_population": "confirm repositories with >= 1 positive",
        # The MCC margin: non-inferior if the lower bound of the difference is above -margin.
        # 0.10 is the ceiling; the margin read is min(0.10, 0.30 x the explore-half macro MCC of
        # the relative rule on the chosen signal), because the pilot measured only per-file
        # SUMS at class level, so the level of a peak or density signal is unknown until explore
        # and a fixed 0.10 could be most of it.
        "noninferiority_margin": 0.10,
        "margin_fraction_of_explore_level": 0.30,
        # The FPR margin: the relative rule is non-inferior on false positives if the upper
        # bound of (relative FPR - absolute FPR) is below this. 0.05 is below the pilot's own
        # relative-rule FPR level (mad_z flagged 5-7% of the non-god files per Java repository),
        # so a rule that flags five points more non-gods than the tuned cut is read as inferior.
        "fpr_margin": 0.05,
        "auc_floor": 0.70,                 # the signal carries the definition at all: macro
                                           # per-repository AUC lower bound >= this
        "min_confirm_repos_auc": 20,       # repositories with >= min_positives on confirm
        "min_confirm_repos_mcc": 40,       # repositories carrying the definition on confirm
        # The absolute competitor is ONE raw-scale cutoff, tuned to maximise the POOLED MCC on
        # explore, and that single cut is read on every arm. On the macro arm that mildly
        # disadvantages the absolute rule; the design is tilted toward it everywhere else.
        "absolute_cutoff": "one raw cut maximising the pooled MCC on explore, read on all arms",
        # The classpath validation (PLAN.md step 4): classpath-check reports under
        # <results>/classpath/ (or --classpath-dir) are aggregated; above the bound the
        # primary oracle is under-counted by a material amount and the verdict is reported as
        # ORACLE-BOUNDED, not read as confirmatory. Missing reports are flagged the same way.
        "classpath_flip_bound": 0.10,
        "classpath_min_repos": 10,
        # Pilot overlap: repositories the pilot measured are RETAINED (the plan was shaped on
        # pilot aggregates, not on repositories), reported, and the primary is re-read on the
        # confirm half without them as a labelled sensitivity analysis.
        "pilot_overlap": "retained; sensitivity re-read of the primary without pilot repositories",
    },
    # The threshold-free form of the relative claim: the pooled AUC on the per-repository
    # modified z minus the pooled AUC on the raw value, over the same confirm repositories, as a
    # paired bootstrap. Read three ways (lower bound > 0: the relative ranking is better; upper
    # bound < 0: the absolute ranking is better; else: no difference resolved). It is a
    # different question from the operating-point verdict (ranking, not a cut) and is reported
    # beside it, not folded into it.
    "threshold_free": {"statistic": "pooled AUC standardised - pooled AUC raw, paired bootstrap "
                                    "over confirm repositories; reported beside the verdict"},
    # Human-label definitions (the MLCQ sub-study): a reviewed universe of a few classes per
    # repository makes a per-repository MCC or FPR mostly noise, so the decision for a human
    # definition is read on the micro arm alone (pooled over the reviewed units of the confirm
    # half), with the same margin rule; the macro numbers are reported. MLCQ's aggregation rule
    # is the strict majority of reviews with any severity above 'none' as positive; the 'any'
    # and 'all' rules are labelled sensitivity runs.
    "human": {"decide_on": ["micro_mcc"], "mlcq_rule": "majority",
              "mlcq_positive": "severity above none", "mlcq_sensitivity_rules": ["any", "all"]},
    # All-language statistics (a definition whose scope is not Java) are read on the MAIN
    # sample only: the Java supplement would otherwise make Java a third of every pooled
    # cross-language number.
    "cross_language_sample": "main",
    "secondary": [
        {"level": "method", "definition": "pmd_method_NPath200",
         "families": ["structure", "density"]},
        {"level": "class", "definition": "decor_blob", "families": ["peak", "density"]},
        {"level": "method", "definition": "brain_method", "families": ["structure", "density"]},
    ],
    "human_families": {"class": ["peak", "density"], "method": ["structure", "density"]},
    "min_positives": 3,
    "friedman_signals": {"class": ["nloc_sum", "nom", "cc_max", "cognitive_max", "cc_mean",
                                   "mi_mean"],
                         "method": ["nloc", "hvol", "cc", "cognitive", "cyc_density", "mi"]},
    "friedman_rules": ["mad_z", "double_mad", "iqr", "adj_boxplot", "pct_top1"],
    "bootstrap": {"b": 2000, "seed": 12345},
}
_CALIBRATION = (("cc", "cc", "pmd_method_CC10"), ("cognitive", "cognitive",
                                                 "pmd_method_Cognitive15"),
                ("nloc", "ncss", "pmd_method_Ncss60"))


def _f(x, nd=3):
    return "   n/a" if x is None else f"{x:6.{nd}f}"


def _ci(b):
    return "" if not b else f" [{b['lo']:.3f}, {b['hi']:.3f}] n={b['n']}"


# The file extensions of each sampled language: the population a HUMAN definition's relative
# rules are fitted on is the labelled repository's own language, as a Java tool definition's
# is the Java units, so a JavaScript file in an MLCQ Java repository is neither fitted on nor
# scored.
LANG_EXTS = {"java": (".java",), "python": (".py", ".pyw"), "javascript": (".js", ".jsx"),
             "typescript": (".ts", ".tsx"), "go": (".go",), "c": (".c", ".h"),
             "c++": (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".h"), "c#": (".cs",),
             "php": (".php",), "rust": (".rs",), "ruby": (".rb",)}


def _is_main_sample(row: dict) -> bool:
    """Drawn by the main sample (or by a run with no supplement at all): the rows every
    all-language statistic is read on. The Java supplement is labelled `java-supplement`
    (step2_sample.sh), and a repository in both samples is measured under the main one."""
    return "supplement" not in (row.get("sample") or "")


def _pilot_repos() -> set:
    """owner/name (lower case) of every repository the pilot run measured
    (pilot/run-v1-repos.txt), so a confirmatory sample's overlap with data an analysis has
    already seen is reported, never assumed."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "pilot", "run-v1-repos.txt")
    out = set()
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(line.split()[0].lower())
    except OSError:
        pass
    return out


def _classpath_reports(path: str) -> list[dict]:
    """Every classpath-check report (classpath_check.compare, written with --out) found in
    `path`, so the analysis can aggregate the GodClass flip rate PLAN.md step 4 bounds the
    primary with. An empty list when the directory is absent."""
    out = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(path, name)))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "godclass_flips" in d:
            out.append({**d, "_file": name})
    return out


def _owner(full_name: str | None) -> str:
    return (full_name or "").split("/")[0].lower()


class Run:
    """A results directory, loaded: usable rows, their halves, the sidecar and the registry."""

    def __init__(self, results_dir: str, plan: dict = PLAN, classpath_dir: str | None = None):
        self.dir = results_dir
        self.plan = plan
        self.pilot = _pilot_repos()
        self.classpath = _classpath_reports(classpath_dir or os.path.join(results_dir, "classpath"))
        self.rows = [r for r in json.load(open(os.path.join(results_dir, "study.json")))
                     if study.is_usable(r) and r.get("matrix")]
        self.all_rows = json.load(open(os.path.join(results_dir, "study.json")))
        self.registry = json.load(open(os.path.join(results_dir, "oracles.json")))["oracles"]
        self.lang = {r["repo"]: r.get("lang") for r in self.rows}
        # the FROZEN split: the half each row records (assigned from the sample CSV before any
        # measurement). A run that predates the freeze gets the computed split, flagged.
        recorded = {r["repo"]: r.get("half") for r in self.rows}
        if self.rows and all(h in ("explore", "confirm") for h in recorded.values()):
            self.halves, self.split_frozen = recorded, True
        else:
            self.halves = stats.assign_halves(
                self.rows, stratum_of=lambda r: (r.get("lang"), r.get("tier")),
                key_of=lambda r: r["repo"])
            self.split_frozen = False
        self.main_rows = [r for r in self.rows if _is_main_sample(r)]
        self.units: dict = {}
        try:
            with open(os.path.join(results_dir, "study.units.jsonl")) as fh:
                keep = {r["repo"] for r in self.rows}
                for line in fh:
                    if line.strip():
                        d = json.loads(line)
                        if d.get("repo") in keep:
                            self.units[d["repo"]] = d
        except OSError:
            pass
        self.by_half = {"explore": [r for r in self.rows if self.halves[r["repo"]] == "explore"],
                        "confirm": [r for r in self.rows if self.halves[r["repo"]] == "confirm"]}

    def rows_for(self, oracle: str) -> list[dict]:
        """The repositories a definition is read on: every usable row for a Java-scoped
        definition (only Java rows carry it), the MAIN sample for an all-language one."""
        if self.registry.get(oracle, {}).get("scope") == "java":
            return self.rows
        return self.main_rows if self.plan.get("cross_language_sample") == "main" else self.rows

    def halves_for(self, oracle: str) -> dict:
        rows = self.rows_for(oracle)
        return {h: [r for r in rows if self.halves[r["repo"]] == h]
                for h in ("explore", "confirm")}

    # ---- the one code path for a definition's units in a repository ----------------------
    def oracles_present(self, level: str) -> list[str]:
        seen: dict = {}
        for r in self.rows:
            for o in (r["matrix"][level].get("oracle_gods") or {}):
                seen[o] = True
        if level == "class":
            seen["wmc47"] = True
        return sorted(seen)

    def block(self, repo: str, level: str, oracle: str):
        """(payload, fit_idx, score_idx, god_positions) or None. fit_idx is the population the
        relative rules are fitted on (Java units for a Java-scoped definition, else all);
        score_idx the units scored (the reviewed units for a human definition with a
        `*_reviewed` companion, else fit_idx). god positions are indices into the payload."""
        d = self.units.get(repo)
        if not d or level not in d:
            return None
        pl = d[level]
        if oracle not in pl["god_idx"]:
            return None
        units = pl["units"]
        meta = self.registry.get(oracle, {})
        exts = None
        if meta.get("scope") == "java":
            exts = (".java",)
        elif meta.get("origin") == "human":
            exts = LANG_EXTS.get(self.lang.get(repo))
        if exts:
            fit = [i for i, u in enumerate(units) if u.split("::")[0].endswith(exts)]
        else:
            fit = list(range(len(units)))
        cond = meta.get("conditional_on")
        if meta.get("origin") == "human" and cond and cond in pl["god_idx"]:
            rev = set(pl["god_idx"][cond])
            score = [i for i in fit if i in rev]
        else:
            score = fit
        return pl, fit, score, set(pl["god_idx"][oracle])

    def n_pos(self, repo, level, oracle) -> int | None:
        b = self.block(repo, level, oracle)
        if b is None:
            return None
        _, _, score, gods = b
        return sum(1 for i in score if i in gods)

    def auc(self, repo, level, signal, oracle, min_pos=None):
        b = self.block(repo, level, oracle)
        if b is None:
            return None
        pl, _, score, gods = b
        vals = pl["values"][signal]
        pos = [vals[i] for i in score if i in gods]
        neg = [vals[i] for i in score if i not in gods]
        if len(pos) < (self.plan["min_positives"] if min_pos is None else min_pos):
            return None
        return stats.auc(pos, neg)

    def auc_given(self, repo, level, signal, oracle):
        """AUC within the units satisfying the definition's registered size clause."""
        cond = self.registry.get(oracle, {}).get("conditional_on")
        b = self.block(repo, level, oracle)
        if b is None or not cond or cond not in b[0]["god_idx"]:
            return None
        pl, _, score, gods = b
        sub = set(pl["god_idx"][cond])
        vals = pl["values"][signal]
        pos = [vals[i] for i in score if i in gods and i in sub]
        neg = [vals[i] for i in score if i not in gods and i in sub]
        if len(pos) < self.plan["min_positives"]:
            return None
        return stats.auc(pos, neg)

    def counts(self, repo, level, signal, oracle, flagged_fn) -> dict | None:
        """Confusion counts over the scored units: `flagged_fn(fit_vmap) -> set` applies a
        rule to the fitting population exactly as the harness does."""
        b = self.block(repo, level, oracle)
        if b is None:
            return None
        pl, fit, score, gods = b
        vals = pl["values"][signal]
        flagged = flagged_fn({i: vals[i] for i in fit})
        tp = sum(1 for i in score if i in flagged and i in gods)
        fp = sum(1 for i in score if i in flagged and i not in gods)
        fn = sum(1 for i in score if i not in flagged and i in gods)
        tn = len(score) - tp - fp - fn
        return {"n_univ": len(score), "n_out": tp + fp, "n_overlap": tp,
                "n_god_univ": tp + fn, "tp": tp, "fp": fp, "fn": fn, "tn": tn}

    def rule_fn(self, rule: str, cut=None):
        algo = metrics.ALGORITHMS[rule]
        if cut is None:
            return algo
        return lambda vmap: algo(vmap, cut)

    def cutoff_fn(self, k: float):
        return lambda vmap: {i for i, v in vmap.items() if v >= k}

    def z_cut_fn(self, z: float):
        def f(vmap):
            keys = list(vmap)
            zs = stats.modified_z_values([vmap[i] for i in keys])
            return {i for i, zz in zip(keys, zs) if zz >= z}
        return f

    def pairs(self, rows, level, signal, oracle, standardise=False):
        out = []
        for r in rows:
            b = self.block(r["repo"], level, oracle)
            if b is None:
                continue
            pl, fit, score, gods = b
            vals = pl["values"][signal]
            if standardise:
                zs = dict(zip(fit, stats.modified_z_values([vals[i] for i in fit])))
                out.extend((zs[i], i in gods) for i in score)
            else:
                out.extend((vals[i], i in gods) for i in score)
        return out

    # ---- aggregation over repositories ----------------------------------------------------
    def macro(self, values):
        b = self.plan["bootstrap"]
        return stats.bootstrap_mean(values, b=b["b"], seed=b["seed"], min_n=2)

    def macro_mcc(self, rows, level, signal, oracle, flagged_fn):
        """Macro (one repository, one vote) and micro (pooled) MCC, plus the macro
        false-positive rate, which unlike the MCC is defined in god-free repositories, and the
        mean number of flags in those repositories."""
        cs = [self.counts(r["repo"], level, signal, oracle, flagged_fn) for r in rows]
        cs = [c for c in cs if c]
        per = [stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"]) for c in cs]
        fprs = [stats.fpr(c["fp"], c["tn"]) for c in cs]
        god_free = [c for c in cs if c["n_god_univ"] == 0]
        return {"macro": self.macro(per), "micro": stats.pooled_confusion(cs),
                "macro_fpr": self.macro(fprs), "n_repos": len(cs),
                "god_free": {"n_repos": len(god_free),
                             "mean_flags": (sum(c["n_out"] for c in god_free) / len(god_free))
                             if god_free else None},
                "_cells": cs}

    def paired(self, rows, level, signal, oracle, fn_a, fn_b) -> list:
        """One (counts_a, counts_b) item per repository carrying the definition: both rules
        on the same units, for stats.bootstrap_paired."""
        out = []
        for r in rows:
            a = self.counts(r["repo"], level, signal, oracle, fn_a)
            b = self.counts(r["repo"], level, signal, oracle, fn_b)
            if a and b:
                out.append((a, b))
        return out

    def explore_level(self, rows, level, signal, oracle, flagged_fn) -> float | None:
        """The explore-half macro MCC of a rule over the repositories with >= 1 positive: the
        level the non-inferiority margin is scaled to (PLAN['decision'])."""
        cs = [self.counts(r["repo"], level, signal, oracle, flagged_fn) for r in rows]
        per = [stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"]) for c in cs if c and c["n_god_univ"]]
        return sum(per) / len(per) if per else None

    def without_pilot(self, rows) -> list[dict]:
        return [r for r in rows if (r.get("full_name") or "").lower() not in self.pilot]

    def candidates(self, level, oracle, families):
        ing = set(self.registry.get(oracle, {}).get("ingredients") or [])
        return [s for fam in families for s in metrics.FAMILIES[level][fam] if s not in ing]

    def choose(self, level, oracle, families, ex=None):
        """The explore choice: the candidate with the highest macro mean per-repo AUC."""
        ex = self.halves_for(oracle)["explore"] if ex is None else ex
        scores = {}
        for s in self.candidates(level, oracle, families):
            v = [self.auc(r["repo"], level, s, oracle) for r in ex]
            v = [x for x in v if x is not None]
            scores[s] = (sum(v) / len(v), len(v)) if v else (None, 0)
        ranked = sorted((s for s in scores if scores[s][0] is not None),
                        key=lambda s: (-scores[s][0], s))
        return (ranked[0] if ranked else None), scores


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------
def readout(run: Run, level: str, oracle: str, families: list[str], rule: str,
            label: str, out: dict, print_fn=print, arms: list[str] | None = None) -> None:
    """One definition, explore -> confirm, as PLAN.md orders the read-outs. `arms` names the
    decision arms read for this definition (default: PLAN['decision']['arms'])."""
    p = print_fn
    arms = arms or run.plan["decision"]["arms"]
    halves = run.halves_for(oracle)
    ex, co = halves["explore"], halves["confirm"]
    meta = run.registry.get(oracle, {})
    ncar = {h: sum(1 for r in rs if run.block(r["repo"], level, oracle) is not None)
            for h, rs in halves.items()}
    npos = {h: sum(run.n_pos(r["repo"], level, oracle) or 0 for r in rs)
            for h, rs in halves.items()}
    nrep = {h: sum(1 for r in rs if (run.n_pos(r["repo"], level, oracle) or 0) >= run.plan["min_positives"])
            for h, rs in halves.items()}
    p(f"\n{label}: {oracle}  [origin {meta.get('origin')}, scope {meta.get('scope')}, "
      f"level {level}]  constant: {meta.get('constant')}")
    p(f"   read on {'all usable' if meta.get('scope') == 'java' else 'the MAIN-sample'} "
      f"repositories: {len(ex)} explore / {len(co)} confirm; carrying the definition "
      f"{ncar['explore']} / {ncar['confirm']}")
    p(f"   positives explore {npos['explore']} / confirm {npos['confirm']}; repositories with "
      f">= {run.plan['min_positives']} positives: explore {nrep['explore']} / confirm "
      f"{nrep['confirm']}")
    res = {"definition": oracle, "level": level, "origin": meta.get("origin"),
           "families": families, "repos": {h: len(rs) for h, rs in halves.items()},
           "repos_with_definition": ncar, "positives": npos, "repos_with_min_positives": nrep}
    if meta.get("origin") == "human":
        res["label_match"] = _human_match(run, ex + co, oracle, p)
    best, scores = run.choose(level, oracle, families, ex)
    res.update({"explore_scores": {s: {"mean_auc": v[0], "n": v[1]} for s, v in scores.items()},
                "chosen_signal": best})
    out[oracle] = res
    if best is None:
        p("   no candidate signal has a per-repository AUC on explore; nothing to read on confirm")
        return
    p(f"   explore (macro mean AUC, {', '.join(families)} families, ingredients excluded):")
    for s in sorted((s for s in scores if scores[s][0] is not None),
                    key=lambda s: -scores[s][0])[:8]:
        p(f"      {s:16} {scores[s][0]:.3f}  (n={scores[s][1]}, {metrics.family_of(level, s)})")
    p(f"   -> chosen on explore: {best}")
    # confirm read-outs
    auc_c = run.macro([run.auc(r["repo"], level, best, oracle) for r in co])
    giv_c = run.macro([run.auc_given(r["repo"], level, best, oracle) for r in co])
    # _blocks already standardised on the fitting population (so a human definition's reviewed
    # units are scored on z-scores fitted on all units), hence the flag is set here
    std_blocks = _blocks(run, co, level, best, oracle, True)
    raw_blocks = _blocks(run, co, level, best, oracle, False)
    pooled_std = {**stats.pooled_auc(std_blocks), "standardised": True}
    pooled_raw = stats.pooled_auc(raw_blocks)
    bcfg = run.plan["bootstrap"]
    auc_diff = stats.bootstrap_paired(list(zip(std_blocks, raw_blocks)), _pooled_auc_diff,
                                      b=bcfg["b"], seed=bcfg["seed"])
    rel = run.macro_mcc(co, level, best, oracle, run.rule_fn(rule))
    cut = stats.best_cutoff(run.pairs(ex, level, best, oracle))
    absd = run.macro_mcc(co, level, best, oracle, run.cutoff_fn(cut["cut"])) if cut else None
    zcut = stats.best_cutoff(run.pairs(ex, level, best, oracle, standardise=True))
    relt = run.macro_mcc(co, level, best, oracle, run.z_cut_fn(zcut["cut"])) if zcut else None
    p(f"   CONFIRM, signal {best}:")
    p(f"      per-repo AUC, macro mean      {_f(auc_c and auc_c['mean'])}{_ci(auc_c)}")
    if meta.get("conditional_on"):
        p(f"      AUC within {meta['conditional_on']:14} {_f(giv_c and giv_c['mean'])}{_ci(giv_c)}")
    p(f"      pooled AUC standardised       {_f(pooled_std['auc'])}  (pos {pooled_std['n_pos']}, "
      f"neg {pooled_std['n_neg']}, god-free repos {pooled_std['n_blocks_no_god']})")
    p(f"      pooled AUC raw                {_f(pooled_raw['auc'])}")
    tf = _threshold_free_reading(auc_diff)
    p(f"      standardised - raw            "
      + (f"{auc_diff['value']:+.3f} [{auc_diff['lo']:+.3f}, {auc_diff['hi']:+.3f}]"
         if auc_diff else "   n/a")
      + f"  -> {tf} (threshold-free reading; reported beside the verdict, not part of it)")
    _mcc_line(p, f"{rule} at default", rel)
    if absd:
        _mcc_line(p, f"absolute {best} >= {cut['cut']:g} (tuned on explore)", absd)
    if relt:
        _mcc_line(p, f"[secondary] modified z >= {zcut['cut']:.2f} (tuned on explore)", relt)
    strip = lambda m: m and {k: v for k, v in m.items() if k != "_cells"}
    res.update({"confirm": {
        "auc_macro": auc_c, "auc_given_macro": giv_c, "pooled_auc_standardised": pooled_std,
        "pooled_auc_raw": pooled_raw,
        "pooled_auc_difference": {"paired": auc_diff, "reading": tf},
        "relative_default": strip(rel),
        "absolute_cutoff": {"cut": cut["cut"] if cut else None, "explore_mcc": cut and cut["mcc"],
                            "confirm": strip(absd)},
        "relative_tuned": {"z_cut": zcut["cut"] if zcut else None, "confirm": strip(relt)}}})
    # the pre-registered decision: paired, on the same confirm repositories. The MCC margin is
    # scaled to the EXPLORE level of the relative rule on the chosen signal (PLAN['decision']).
    if cut:
        level_ex = run.explore_level(ex, level, best, oracle, run.rule_fn(rule))
        is_primary = label.startswith("PRIMARY")
        res["decision"] = _decision(run, co, level, best, oracle, run.rule_fn(rule),
                                    run.cutoff_fn(cut["cut"]), auc_c, nrep["confirm"], p,
                                    arms=arms, explore_level=level_ex,
                                    classpath=is_primary, label="DECISION")
        if is_primary:
            co_np = run.without_pilot(co)
            n_pilot = len(co) - len(co_np)
            if n_pilot:
                p(f"   SENSITIVITY: the same decision on the confirm half without the {n_pilot} "
                  f"repositories the pilot measured (labelled sensitivity, PLAN.md):")
                auc_np = run.macro([run.auc(r["repo"], level, best, oracle) for r in co_np])
                n_auc_np = sum(1 for r in co_np
                               if (run.n_pos(r["repo"], level, oracle) or 0) >= run.plan["min_positives"])
                res["sensitivity_without_pilot"] = _decision(
                    run, co_np, level, best, oracle, run.rule_fn(rule), run.cutoff_fn(cut["cut"]),
                    auc_np, n_auc_np, p, arms=arms, explore_level=level_ex, classpath=False,
                    label="SENSITIVITY (without pilot repositories)")
            else:
                p("   SENSITIVITY: no pilot repository in the confirm half; the decision above "
                  "is also the pilot-free one")
                res["sensitivity_without_pilot"] = {"n_pilot_removed": 0,
                                                    "same_as_decision": True}
    # breakdowns for the primary only
    if label.startswith("PRIMARY"):
        p("   breakdown on confirm (macro mean AUC | default-rule MCC | n repos):")
        br = {}
        for key in ("lang", "tier", "kind"):
            groups = defaultdict(list)
            for r in co:
                groups[r.get(key)].append(r)
            for g, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
                a = run.macro([run.auc(r["repo"], level, best, oracle) for r in rs])
                m = run.macro_mcc(rs, level, best, oracle, run.rule_fn(rule))
                br[f"{key}={g}"] = {"auc": a, "mcc": m["macro"], "n": len(rs)}
                p(f"      {key:5}={str(g):12} {_f(a and a['mean'])} | "
                  f"{_f(m['macro'] and m['macro']['mean'])} | {len(rs)}")
        res["breakdown"] = br


def _blocks(run, rows, level, signal, oracle, standardise):
    """Sidecar blocks for stats.pooled_auc, standardised on the fitting population and scored
    on the scored units (so a human definition's pool is its reviewed units)."""
    out = []
    for r in rows:
        b = run.block(r["repo"], level, oracle)
        if b is None:
            continue
        pl, fit, score, gods = b
        vals = pl["values"][signal]
        if standardise:
            zs = dict(zip(fit, stats.modified_z_values([vals[i] for i in fit])))
            vs = [zs[i] for i in score]
        else:
            vs = [vals[i] for i in score]
        out.append((vs, [k for k, i in enumerate(score) if i in gods]))
    return out


def _pooled_auc_diff(items) -> float | None:
    """pooled AUC of the standardised blocks minus pooled AUC of the raw blocks, over the same
    repositories (one (std_block, raw_block) item per repository)."""
    s = stats.pooled_auc([a for a, _ in items])["auc"]
    r = stats.pooled_auc([b for _, b in items])["auc"]
    return None if s is None or r is None else s - r


def _threshold_free_reading(b) -> str:
    if not b:
        return "not estimable"
    if b["lo"] > 0:
        return "relative ranking better"
    if b["hi"] < 0:
        return "absolute ranking better"
    return "no difference resolved"


def _mcc_line(p, name, m):
    mi = m["micro"]
    gf = m.get("god_free") or {}
    p(f"      MCC {name:44} macro {_f(m['macro'] and m['macro']['mean'])}{_ci(m['macro'])}  "
      f"micro {_f(mi['mcc'])}  P {_f(mi['precision'], 2)} R {_f(mi['recall'], 2)}")
    p(f"          macro FPR {_f(m['macro_fpr'] and m['macro_fpr']['mean'], 4)}"
      f"{_ci(m['macro_fpr'])}  FP in god-free repos {mi['fp_in_no_god']}/{mi['n_blocks_no_god']}"
      f" (mean flags per god-free repo {_f(gf.get('mean_flags'), 2)})")


def _human_match(run, rows, oracle, p) -> dict:
    """How many of the expert labels landed on a measured unit: a label on a file outside the
    universe (a test file, a generated file) or on a line no measured function contains is
    dropped at measurement, and a low match rate is a threat the paper must carry."""
    key = (oracle[len("human_method_"):] + "@method" if oracle.startswith("human_method_")
           else oracle[len("human_"):])
    out = {}
    for name, k in (("positives", key), ("reviewed", key.replace("@method", "_reviewed@method")
                                         if "@method" in key else key + "_reviewed")):
        lab = meas = 0
        for r in rows:
            h = (r.get("human_labels") or {}).get(k)
            if h:
                lab += h.get("labelled", 0)
                meas += h.get("measured", 0)
        out[name] = {"labelled": lab, "measured": meas, "rate": (meas / lab) if lab else None}
        p(f"   label match ({name}): {meas} of {lab} labelled units measured"
          f" ({_f(out[name]['rate'], 3)})")
    return out


def _verdict(b, margin):
    """Higher is better (an MCC difference): non-inferior if the lower bound clears -margin."""
    if not b:
        return "not estimable"
    if b["lo"] > 0:
        return "superior"
    if b["lo"] > -margin:
        return "non-inferior"
    if b["hi"] < -margin:
        return "inferior"
    return "inconclusive"


def _verdict_lower_better(b, margin):
    """Lower is better (a false-positive-rate difference): non-inferior if the upper bound of
    relative minus absolute stays below +margin."""
    if not b:
        return "not estimable"
    if b["hi"] < 0:
        return "superior"
    if b["hi"] < margin:
        return "non-inferior"
    if b["lo"] > margin:
        return "inferior"
    return "inconclusive"


_RANK = {"superior": 3, "non-inferior": 2, "inconclusive": 1, "inferior": 0, "not estimable": -1}


def classpath_summary(run: Run) -> dict:
    """The classpath validation aggregated (PLAN.md step 4): reports found, GodClass flips over
    the union of verdicts, the flip rate, and whether it is within the pre-registered bound on
    at least the minimum number of repositories. A report that names its repository (--url) is
    checked against the frozen split: the validation must never touch a confirm repository."""
    d = run.plan["decision"]
    reps = run.classpath
    flips = sum(int(r.get("godclass_flips") or 0) for r in reps)
    union = 0
    for r in reps:
        g = (r.get("rules") or {}).get("GodClass") or {}
        lost = len(g.get("lost") or [])
        union += (int(g.get("without") or 0) - lost) + lost + len(g.get("gained") or [])
    halves = {}
    for r in reps:
        key = (r.get("url") or r.get("full_name") or "").lower()
        if not key:
            continue
        for row in run.rows:
            if key in ((row.get("repo") or "").lower(), (row.get("full_name") or "").lower()):
                halves[key] = run.halves.get(row["repo"])
    rate = (flips / union) if union else None
    enough = len(reps) >= d["classpath_min_repos"]
    within = None if not reps else (rate is not None and rate <= d["classpath_flip_bound"] and enough)
    return {"n_reports": len(reps), "files": [r["_file"] for r in reps], "flips": flips,
            "union": union, "flip_rate": rate, "bound": d["classpath_flip_bound"],
            "min_repos": d["classpath_min_repos"], "enough_repos": enough, "within_bound": within,
            "halves_named": halves,
            "confirm_touched": sorted(k for k, h in halves.items() if h == "confirm"),
            "unnamed_reports": sum(1 for r in reps if not (r.get("url") or r.get("full_name")))}


def _decision(run, co, level, signal, oracle, fn_rel, fn_abs, auc_c, n_auc_repos, p,
              arms=None, explore_level=None, classpath: bool = False,
              label: str = "DECISION") -> dict:
    """The pre-registered read-out (PLAN['decision']): paired bootstrap over the confirm
    repositories of relative-at-default minus absolute-tuned on three arms (macro MCC over the
    repositories with >= 1 positive, micro MCC over all, macro FPR over all, lower better); the
    verdict is the weakest arm named in `arms`. Then the AUC floor, the effective-sample gate
    and, for the primary, the classpath bound. The MCC margin is min(ceiling, fraction x
    `explore_level`)."""
    d = run.plan["decision"]
    arms = arms or d["arms"]
    bcfg = run.plan["bootstrap"]
    items = run.paired(co, level, signal, oracle, fn_rel, fn_abs)
    items_pos = [(a, b) for a, b in items if a["n_god_univ"] > 0]
    m = lambda c: stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"])

    def macro_diff(its):
        return sum(m(a) - m(b) for a, b in its) / len(its)

    def micro_diff(its):
        pa = stats.pooled_confusion([a for a, _ in its])["mcc"]
        pb = stats.pooled_confusion([b for _, b in its])["mcc"]
        return None if pa is None or pb is None else pa - pb

    def fpr_diff(its):
        ds = [(stats.fpr(a["fp"], a["tn"]), stats.fpr(b["fp"], b["tn"])) for a, b in its]
        ds = [x - y for x, y in ds if x is not None and y is not None]
        return sum(ds) / len(ds) if ds else None

    bs = {"macro_mcc": stats.bootstrap_paired(items_pos, macro_diff, b=bcfg["b"], seed=bcfg["seed"]),
          "micro_mcc": stats.bootstrap_paired(items, micro_diff, b=bcfg["b"], seed=bcfg["seed"]),
          "macro_fpr": stats.bootstrap_paired(items, fpr_diff, b=bcfg["b"], seed=bcfg["seed"])}
    ceiling = d["noninferiority_margin"]
    scaled = (d["margin_fraction_of_explore_level"] * explore_level
              if explore_level is not None else None)
    margin = min(ceiling, scaled) if scaled is not None else ceiling
    v = {"macro_mcc": _verdict(bs["macro_mcc"], margin),
         "micro_mcc": _verdict(bs["micro_mcc"], margin),
         "macro_fpr": _verdict_lower_better(bs["macro_fpr"], d["fpr_margin"])}
    decided = {k: v[k] for k in arms}
    overall = min(decided.values(), key=lambda x: _RANK[x])
    auc_ok = bool(auc_c) and auc_c["lo"] >= d["auc_floor"]
    powered = (n_auc_repos >= d["min_confirm_repos_auc"]
               and len(items) >= d["min_confirm_repos_mcc"])
    cp = classpath_summary(run) if classpath else None
    p(f"   {label} (pre-registered; paired bootstrap over {len(items)} confirm repositories, "
      f"{len(items_pos)} with >= 1 positive; MCC margin {margin:.3f} = min({ceiling}, "
      f"{d['margin_fraction_of_explore_level']} x explore level {_f(explore_level).strip()}); "
      f"FPR margin {d['fpr_margin']}):")
    for k, name in (("macro_mcc", "macro MCC"), ("micro_mcc", "micro MCC"),
                    ("macro_fpr", "macro FPR")):
        b = bs[k]
        p(f"      relative - absolute, {name:10} "
          + (f"{b['value']:+.3f} [{b['lo']:+.3f}, {b['hi']:+.3f}] n={b['n']}" if b else "   n/a")
          + f"  -> {v[k]}" + ("" if k in arms else "  (reported, not decided on)"))
    p(f"      AUC floor {d['auc_floor']}: lower bound "
      f"{_f(auc_c and auc_c['lo'])} -> {'met' if auc_ok else 'NOT met'}")
    p(f"      effective sample: {n_auc_repos} repositories with >= {run.plan['min_positives']} "
      f"positives (need {d['min_confirm_repos_auc']}), {len(items)} carrying the definition "
      f"(need {d['min_confirm_repos_mcc']}) -> {'powered' if powered else 'UNDERPOWERED'}")
    notes = []
    if not powered:
        notes.append("underpowered: reported, not read as confirmatory")
    if not auc_ok:
        notes.append("AUC floor not met: the signal does not carry the definition")
    if cp is not None:
        if cp["n_reports"] == 0:
            p(f"      classpath validation: NO reports under <results>/classpath (PLAN.md step 4)")
            notes.append("classpath validation missing: not read as confirmatory")
        else:
            p(f"      classpath validation: {cp['n_reports']} repositories (need "
              f"{cp['min_repos']}), GodClass flips {cp['flips']} of {cp['union']} verdicts, "
              f"flip rate {_f(cp['flip_rate'])} (bound {cp['bound']}) -> "
              f"{'within bound' if cp['within_bound'] else 'NOT within bound'}"
              + (f"; CONFIRM repositories touched: {cp['confirm_touched']}"
                 if cp["confirm_touched"] else ""))
            if not cp["within_bound"]:
                notes.append(f"ORACLE-BOUNDED: GodClass flip rate {_f(cp['flip_rate']).strip()} "
                             f"on {cp['n_reports']} repositories; the oracle is under-counted by "
                             f"a material amount and the verdict is not read as confirmatory")
            if cp["confirm_touched"]:
                notes.append("classpath validation touched confirm repositories: not confirmatory")
    confirmatory = powered and auc_ok and (cp is None or bool(cp["within_bound"])) \
        and not (cp and cp["confirm_touched"])
    p(f"      verdict: {overall.upper()}" + "".join(f" ({n})" for n in notes))
    return {"paired": bs, "verdicts": v, "arms": list(arms), "overall": overall,
            "margin": margin, "margin_ceiling": ceiling, "explore_level": explore_level,
            "fpr_margin": d["fpr_margin"], "auc_floor_met": auc_ok, "powered": powered,
            "n_paired_repos": len(items), "n_paired_repos_macro": len(items_pos),
            "n_auc_repos": n_auc_repos, "classpath": cp, "notes": notes,
            "confirmatory": confirmatory}


def diagnostics(run: Run, out: dict, print_fn=print) -> None:
    p = print_fn
    d: dict = {}
    p("\n== 1. DIAGNOSTICS (read before any accuracy number) ==")
    # sample
    strata = defaultdict(lambda: {"explore": 0, "confirm": 0})
    for r in run.rows:
        strata[(r.get("lang"), r.get("tier"))][run.halves[r["repo"]]] += 1
    p("   usable repositories by language x tier (explore/confirm):")
    for (lang, tier), c in sorted(strata.items(), key=lambda kv: str(kv[0])):
        p(f"      {str(lang):11} {str(tier):8} {c['explore']:>3} / {c['confirm']:>3}")
    d["strata"] = {f"{k[0]}/{k[1]}": v for k, v in strata.items()}
    flips = [r.get("name") for r in run.all_rows if not r.get("error") and r.get("matrix")
             and not study.is_usable(r)]
    errors = [r.get("name") for r in run.all_rows if r.get("error")]
    dirty = sum(1 for r in run.rows if ((r.get("tools") or {}).get("harness_commit") or "").endswith("-dirty"))
    commits = sorted({(r.get("tools") or {}).get("harness_commit") for r in run.rows})
    p(f"   rows: {len(run.rows)} usable, {len(flips)} drawn-usable but failing the floor "
      f"{flips[:10]}, {len(errors)} errors {errors[:10]}")
    p(f"   harness commits {commits}; rows measured with a DIRTY tree: {dirty}"
      + ("  <-- not confirmatory" if dirty else ""))
    p("   explore/confirm split: " + ("FROZEN before measurement (recorded in every row)"
                                       if run.split_frozen else
                                       "COMPUTED at analysis time (rows carry no half)  <-- not confirmatory"))
    pilot = _pilot_repos()
    overlap = sorted(r.get("full_name") for r in run.rows
                     if (r.get("full_name") or "").lower() in pilot)
    p(f"   overlap with the pilot (pilot/run-v1-repos.txt, {len(pilot)} repositories): "
      f"{len(overlap)} of {len(run.rows)} usable rows {overlap[:10]}")
    java_rows = [r for r in run.rows if r.get("lang") == "java"]
    java_main = sum(1 for r in java_rows if _is_main_sample(r))
    p(f"   main sample {len(run.main_rows)} rows; supplement {len(run.rows) - len(run.main_rows)} "
      f"(all-language statistics are read on the main sample only); Java rows {len(java_rows)} "
      f"({java_main} drawn by the main sample, {len(java_rows) - java_main} by the supplement; "
      f"the supplement's draw repeats the main Java draw only if both enumerations of GitHub "
      f"returned the same candidates)")
    # owner concentration: repositories of one GitHub owner are not independent draws, and the
    # bootstrap resamples repositories; the concentration is reported so a reader can judge it
    owners = defaultdict(list)
    for r in run.rows:
        owners[_owner(r.get("full_name"))].append(r.get("full_name"))
    multi = {o: len(v) for o, v in owners.items() if len(v) > 1}
    shared = sum(multi.values())
    top = sorted(multi.items(), key=lambda kv: -kv[1])[:5]
    p(f"   owner concentration: {len(owners)} distinct owners for {len(run.rows)} rows; "
      f"{shared} rows share an owner with another row; largest owners {top}")
    d.update({"n_usable": len(run.rows), "n_main_sample": len(run.main_rows),
              "n_java": len(java_rows), "n_java_main_sample": java_main,
              "usable_flips": flips, "errors": errors,
              "harness_commits": commits, "dirty_rows": dirty, "split_frozen": run.split_frozen,
              "pilot_overlap": overlap, "n_pilot": len(pilot),
              "owners": {"distinct": len(owners), "rows_sharing_owner": shared, "largest": top}})
    cp = classpath_summary(run)
    p(f"   classpath validation reports: {cp['n_reports']} (GodClass flips {cp['flips']} of "
      f"{cp['union']}, flip rate {_f(cp['flip_rate'])}; bound {cp['bound']} on >= {cp['min_repos']} "
      f"repositories)" + (f"; {cp['unnamed_reports']} report(s) name no repository, so their half "
                          f"cannot be checked" if cp["unnamed_reports"] else "")
      + (f"; CONFIRM repositories touched: {cp['confirm_touched']}" if cp["confirm_touched"] else ""))
    d["classpath"] = cp
    skipped = defaultdict(int)
    outside = defaultdict(int)
    for r in run.rows:
        for k, v in (r.get("files_skipped") or {}).items():
            skipped[k] += v
        for lvl in ("class", "method"):
            for o, v in (r["matrix"][lvl].get("god_outside_univ") or {}).items():
                outside[o] += v
    p(f"   files outside the universe: {dict(skipped)}")
    p(f"   definition positives outside the universe: "
      f"{ {k: v for k, v in outside.items() if v} or 'none'}")
    d["files_skipped"] = dict(skipped)
    d["god_outside_univ"] = dict(outside)
    # calibration
    p("   calibration of the lexical estimators against PMD's values (Java, per repository):")
    cal = {}
    for sig, pm, odef in _CALIBRATION:
        rhos, aucs = [], []
        for r in run.rows:
            u = run.units.get(r["repo"], {}).get("method")
            pv = (u or {}).get("pmd_values", {}).get(pm) if u else None
            if not pv:
                continue
            xs = [(a, b) for a, b in zip(u["values"][sig], pv) if b is not None]
            if len(xs) >= 10:
                rho = stats.spearman([a for a, _ in xs], [b for _, b in xs])
                if rho is not None:
                    rhos.append(rho)
            a = run.auc(r["repo"], "method", sig, odef)
            if a is not None:
                aucs.append(a)
        mr, ma = run.macro(rhos), run.macro(aucs)
        cal[sig] = {"spearman": mr, "threshold_auc": ma}
        p(f"      {sig:10} vs PMD {pm:10} Spearman {_f(mr and mr['mean'])}{_ci(mr)}   "
          f"AUC on {odef} {_f(ma and ma['mean'])}{_ci(ma)}")
    d["calibration"] = cal
    # scale kinds and zero shares
    p("   modified-z scale per signal (share of repositories: mad / mean_ad / constant) and mean zero share:")
    sc = {}
    for lvl in ("method", "class"):
        for sig in [s for fam in metrics.FAMILIES[lvl].values() for s in fam]:
            kinds = defaultdict(int)
            zf = []
            for r in run.rows:
                dg = (r["matrix"][lvl].get("diag") or {}).get(sig)
                if dg:
                    kinds[dg["scale"]] += 1
                    if dg.get("zero_frac") is not None:
                        zf.append(dg["zero_frac"])
            n = sum(kinds.values()) or 1
            sc[f"{lvl}:{sig}"] = {"mad": kinds["mad"] / n, "mean_ad": kinds["mean_ad"] / n,
                                  "constant": kinds["constant"] / n,
                                  "zero_frac": sum(zf) / len(zf) if zf else None}
    for k, v in sc.items():
        if v["mad"] < 0.9 or (v["zero_frac"] or 0) > 0.2:
            p(f"      {k:22} mad {v['mad']:.2f} mean_ad {v['mean_ad']:.2f} const {v['constant']:.2f}"
              f"  zeros {_f(v['zero_frac'], 2)}")
    p("      (signals with >= 90% MAD scale and <= 20% zeros are not listed)")
    d["scale"] = sc
    # trivial / anonymous units per language
    tl = defaultdict(list)
    for r in run.rows:
        tl[r.get("lang")].append((r.get("trivial_frac") or 0, r.get("anon_frac") or 0))
    p("   per language: mean share of trivial units (CC 1) and of anonymous units:")
    d["trivial"] = {}
    for lang, v in sorted(tl.items(), key=lambda kv: str(kv[0])):
        t = sum(a for a, _ in v) / len(v)
        a = sum(b for _, b in v) / len(v)
        d["trivial"][str(lang)] = {"trivial_frac": t, "anon_frac": a}
        p(f"      {str(lang):11} trivial {t:.2f}  anonymous {a:.2f}")
    out["diagnostics"] = d


def flag_rates(run: Run, level: str, signal: str, oracle: str, out: dict, print_fn=print):
    p = print_fn
    p(f"   flag rate per rule and language (signal {signal}, scope of {oracle}; mean n_out/n_univ):")
    rates = {}
    for rule in metrics.ALGORITHMS:
        by = defaultdict(list)
        for r in run.rows:
            c = run.counts(r["repo"], level, signal, oracle, run.rule_fn(rule))
            if c and c["n_univ"]:
                by[r.get("lang")].append(c["n_out"] / c["n_univ"])
        rates[rule] = {str(l): sum(v) / len(v) for l, v in by.items()}
        p(f"      {rule:12} " + "  ".join(f"{str(l)[:6]}={sum(v)/len(v):.3f}"
                                        for l, v in sorted(by.items(), key=lambda kv: str(kv[0]))))
    out["flag_rates"] = rates


def friedman_sections(run: Run, level: str, oracle: str, signal: str, out: dict, print_fn=print):
    p = print_fn
    p(f"\n== 4. RULES compared (Friedman over repositories; {oracle}, signal {signal}, "
      f"per-repo MCC) ==")
    rows = []
    for r in run.rows:
        row = {}
        for rule in run.plan["friedman_rules"]:
            c = run.counts(r["repo"], level, signal, oracle, run.rule_fn(rule))
            if c is None:
                row = None
                break
            row[rule] = stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"])
        if row:
            rows.append(row)
    fr = stats.friedman(rows) if len(rows) >= 2 else None
    _print_friedman(p, fr)
    out["friedman_rules"] = fr
    p(f"\n== 5. SIGNALS compared (Friedman over repositories; {oracle}, per-repo AUC, "
      f"pre-specified signals) ==")
    rows = []
    for r in run.rows:
        row = {s: run.auc(r["repo"], level, s, oracle) for s in run.plan["friedman_signals"][level]}
        if all(v is not None for v in row.values()):
            rows.append(row)
    fr = stats.friedman(rows) if len(rows) >= 2 else None
    _print_friedman(p, fr)
    out["friedman_signals"] = fr


def _print_friedman(p, fr):
    if not fr:
        p("   too few complete blocks")
        return
    for m, rk in sorted(fr["mean_rank"].items(), key=lambda kv: kv[1]):
        p(f"      {m:14} mean rank {rk:.2f}")
    p(f"   N={fr['n']} k={fr['k']}  chi2={fr['chi2']:.2f} p={fr['p_chi2']:.4f}  "
      f"Iman-Davenport F={fr['F']:.2f} p={fr['p_F']:.4f}  Nemenyi CD={fr['cd_05']:.3f}"
      f"  (all-tied blocks dropped: {fr.get('n_tied_dropped', 0)})")


def exploratory(run: Run, out: dict, print_fn=print):
    p = print_fn
    p("\n== 6. EXPLORATORY: best signal (macro AUC, all repos) and best cell (macro MCC from the "
      "harness cells) per definition; best-of-many is upward-biased ==")
    ex = {}
    for level in ("class", "method"):
        for o in run.oracles_present(level):
            meta = run.registry.get(o, {})
            ing = set(meta.get("ingredients") or [])
            sig = {}
            for s in metrics.METHOD_SIGNALS if level == "method" else metrics.CLASS_SIGNALS:
                v = [run.auc(r["repo"], level, s, o) for r in run.rows]
                v = [x for x in v if x is not None]
                if v:
                    sig[s] = sum(v) / len(v)
            if not sig:
                continue
            bs = max(sig, key=sig.get)
            cells = {}
            for s in sig:
                for a in metrics.ALGORITHMS:
                    v = []
                    for r in run.rows:
                        c = ((r["matrix"][level]["cells"].get(s) or {}).get(a) or {}).get(o)
                        if c and c.get("n_univ"):
                            tp = c["n_overlap"]
                            fp = c["n_out"] - tp
                            fn = c["n_god_univ"] - tp
                            v.append(stats.mcc(tp, fp, fn, c["n_univ"] - tp - fp - fn))
                    if v:
                        cells[(s, a)] = sum(v) / len(v)
            bc = max(cells, key=cells.get) if cells else (None, None)
            star = "*" if bs in ing else ""
            p(f"   {level:6} {o:28} [{meta.get('kind'):11} {str(meta.get('origin')):8}] "
              f"AUC {bs}{star}={sig[bs]:.3f}   MCC {bc[0]}/{bc[1]}={cells.get(bc, 0):.3f}")
            ex[f"{level}:{o}"] = {"best_signal": bs, "best_signal_is_ingredient": bs in ing,
                                  "auc": sig[bs], "best_cell": list(bc),
                                  "mcc": cells.get(bc)}
    p("   (* = an ingredient of the definition)")
    out["exploratory"] = ex


def _sha256(path: str) -> str | None:
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def report(run: Run, print_fn=print, is_exploratory: bool = False) -> dict:
    import datetime
    p = print_fn
    out: dict = {"plan": run.plan, "results_dir": os.path.abspath(run.dir),
                 "study_sha256": _sha256(os.path.join(run.dir, "study.json")),
                 "analysed_utc": datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "is_exploratory": is_exploratory}
    p(f"=== complexity-concentration-study: {'EXPLORATORY ' if is_exploratory else ''}analysis of "
      f"{run.dir} ===")
    p(f"PLAN: primary {run.plan['primary']}; decision {run.plan['decision']}; min positives "
      f"{run.plan['min_positives']}; split stratified by (language, tier), frozen before "
      f"measurement")
    if not run.units:
        p("no study.units.jsonl sidecar: nothing can be computed to the rules (older run?)")
        return out
    diagnostics(run, out, p)
    prim = run.plan["primary"]
    present_c = set(run.oracles_present("class"))
    present_m = set(run.oracles_present("method"))

    def present(o, level):
        return o in (present_c if level == "class" else present_m)

    p("\n== 2. PRIMARY (chosen on explore, read on confirm) ==")
    out["primary"] = {}
    chosen = None
    if present(prim["definition"], prim["level"]):
        readout(run, prim["level"], prim["definition"], prim["families"], prim["rule"],
                "PRIMARY", out["primary"], p)
        chosen = out["primary"][prim["definition"]].get("chosen_signal")
        if chosen:
            flag_rates(run, prim["level"], chosen, prim["definition"], out, p)
    else:
        p(f"   {prim['definition']} is not in this run (no PMD panel?)")
    p("\n== 3. SECONDARY definitions, in headline order ==")
    out["secondary"] = {}
    secs = list(run.plan["secondary"])
    for level in ("class", "method"):
        for o in run.oracles_present(level):
            meta = run.registry.get(o, {})
            if meta.get("origin") == "human" and meta.get("kind") == "human":
                secs.append({"level": level, "definition": o,
                             "families": run.plan["human_families"][level],
                             "arms": run.plan["human"]["decide_on"]})
    order = {"tool": 0, "human": 0, "composed": 1, "internal": 2}
    secs.sort(key=lambda s: order.get(run.registry.get(s["definition"], {}).get("origin"), 3))
    for s in secs:
        if present(s["definition"], s["level"]):
            readout(run, s["level"], s["definition"], s["families"], prim["rule"],
                    "SECONDARY", out["secondary"], p, arms=s.get("arms"))
        else:
            p(f"\nSECONDARY: {s['definition']} is not in this run")
    if chosen:
        friedman_sections(run, prim["level"], prim["definition"], chosen, out, p)
    exploratory(run, out, p)
    p("\n(Sections 2 and 3 are read once on the confirmatory sample; 4-6 are exploratory. "
      "Definitions of origin 'internal' are internal consistency, not recovery of an external "
      "definition. See README, 'Analysing a run', and PLAN.md.)")
    return out


_DATED = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}")


def _latest(base: str):
    """The latest DATED run (results/<YYYY-MM-DD...>); a named run such as results/mlcq is
    never picked by default, only with --results."""
    try:
        subs = sorted(d for d in os.listdir(base)
                      if _DATED.match(d) and os.path.exists(os.path.join(base, d, "study.json")))
    except OSError:
        return None
    return os.path.join(base, subs[-1]) if subs else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study analyse",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=None, help="a results/<date> directory (default: latest)")
    ap.add_argument("--json", default=None, help="write the numbers here (default: "
                    "<results>/analysis.json, written ONCE)")
    ap.add_argument("--exploratory", action="store_true",
                    help="a re-analysis of a run already analysed: labelled exploratory and "
                         "written to <results>/analysis.exploratory.<utc>.json; the "
                         "confirmatory analysis.json is never overwritten")
    ap.add_argument("--classpath-dir", default=None,
                    help="directory of classpath-check reports (default <results>/classpath); "
                         "their GodClass flip rate bounds the primary (PLAN.md step 4)")
    args = ap.parse_args(argv)
    from . import deps
    import datetime
    results = args.results or _latest(deps.default_results())
    if not results or not os.path.exists(os.path.join(results, "study.json")):
        print("no results: pass --results DIR holding study.json", file=sys.stderr)
        return 2
    confirmatory = os.path.join(results, "analysis.json")
    if args.exploratory and not args.json:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(results, f"analysis.exploratory.{stamp}.json")
    else:
        path = args.json or confirmatory
    if os.path.exists(path) and not args.exploratory:
        print(f"{path} exists: this run has been analysed, and the first analysis of a run is "
              f"its confirmatory one (PLAN.md). A re-analysis is exploratory: pass "
              f"--exploratory to write a dated analysis.exploratory.<utc>.json beside it.",
              file=sys.stderr)
        return 3
    run = Run(results, classpath_dir=args.classpath_dir)
    out = report(run, is_exploratory=args.exploratory)
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    digest = _sha256(path)
    with open(path + ".sha256", "w") as fh:
        fh.write(f"{digest}  {os.path.basename(path)}\n")
    print(f"\nwrote {path}\nsha256 {digest}  (also in {path}.sha256)")
    if not args.exploratory:
        print("Commit that digest with the harness (PLAN.md, procedure step 5) so the "
              "confirmatory analysis is auditable against this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
