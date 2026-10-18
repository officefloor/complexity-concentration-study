"""Multi-language snapshot study: how well does a relative COMPLEXITY outlier identify
textbook god classes/methods at a repository's sampled commit?

Identification is a placement (snapshot) property, so one commit per repository is enough.
The repositories, and the commit of each, come from one or more samples drawn by
open-source-repository-sampler (`open-source-repository-sample.csv`). Its run loop
shallow-clones each usable repository at its pinned commit, hands it to `measure`, and deletes
the clone, so this module only measures.

For every (level, complexity signal, outlier algorithm, god DEFINITION) the per-repo `matrix`
block records lean confusion counts -- for EVERY repository, including those where a definition
finds no god (those cells carry n_god_univ == 0 and MUST be kept by any pooled statistic, see
stats.pooled_confusion) -- and the threshold-free AUC/AP of the raw signal.

Every god DEFINITION (oracle) the study scores against is declared ONCE in `ORACLES`, with its
level, kind, group, source, constant and INGREDIENTS (the complexity signals its own definition
is built from), so the analysis cannot present a signal recovering a definition it is part of
as an independent result. `write_oracles` records that registry with each run.

Resumable: repositories the run log records as done are skipped.
"""
from __future__ import annotations

import csv as _csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict

from . import extract
from . import metrics
from . import stats

CC_GOD = 14
# The languages the study samples (step2_sample.sh reads this list). Ruby is NOT among them:
# the pinned lizard mis-bounds Ruby functions that contain a `case`, `unless` or `until` block
# (the function is closed at that block's `end`, so every line after it is dropped from the
# unit and every per-unit number is wrong) -- see ruby_parser_bounds_ok(). The harness carries a Ruby cognitive/nesting scanner and fixture so
# Ruby can be re-admitted as soon as a pinned parser bounds it correctly.
SAMPLED_LANGUAGES = ("java", "python", "javascript", "typescript", "go", "c", "c++", "c#",
                     "php", "rust")
EXCLUDED_LANGUAGES = {"ruby": "lizard %s closes a Ruby function at the `end` of a `case`, "
                              "`unless` or `until` block inside it (ruby_parser_bounds_ok)"}
# The study's substance floor. step2_sample.sh samples with the same floor
# (--min-functions 50, --min-files-with-functions 15), so usable repositories clear it.
MIN_FUNCS, MIN_UNIV = 50, 15


# ---------------------------------------------------------------------------
# the oracle registry: every god definition, declared once with its provenance
# ---------------------------------------------------------------------------
# kind:
#   self         one complexity signal restated as an absolute threshold (AUC~1 for that signal
#                is a tautology; reported apart, never a headline)
#   calibration  an external TOOL's implementation of one of our signals (PMD on Java): the
#                matching signal's AUC on it measures the lexical estimator against the tool
#   component    one clause of a textbook definition (cohesion or coupling alone); not a god
#                definition by itself -- its prevalence is reported with it
#   tool         a tool-defined single measure none of our signals computes (NPath)
#   composite    a multi-clause textbook definition (the real targets)
#   human        expert-labelled instances supplied with --labels (the external ground truth)
# bases: the BASE complexity measures the definition is built from (closure over
#        extract.SIGNAL_INPUTS and, at class level, over every aggregation -- see ingredients()).
# headline: whether the definition may carry a headline number.
# origin: who computed the label --
#   tool      an external tool's own rule (PMD, CK): external to this harness
#   human     expert labels (--labels): external, and the only kind with no built-in scale
#   composed  the study's composition of tool-computed values (decor_blob): external values,
#             this study's constants
#   internal  the study's own signals thresholded (self definitions, brain_method): NOT an
#             external oracle; a result on it is internal consistency, reported as such
#   The headline order is tool/human, then composed, then internal (README, Analysing a run).
# conditional_on: the SIZE clause of a composite, as a registered component. The ingredient
#   rule removes definitional inputs, but every size signal is statistically collinear with a
#   size clause, so the matrix also records each signal's AUC WITHIN the units that already
#   satisfy that clause: whether the signal carries anything beyond size.
ORACLES: dict = {
    # ---- class level (unit = file) ----
    "wmc47": dict(level="class", kind="self", group="size/complexity", bases={"cc"},
                  headline=False, scope="all", origin="internal",
                  source="Lanza & Marinescu 2006, God Class size clause: WMC >= VERY_HIGH (47)",
                  constant="WMC >= 47"),
    "pmd_GodClass": dict(level="class", kind="composite", group="composite", bases={"cc"},
                         headline=True, scope="java", origin="tool", conditional_on="wmc47",
                         source="PMD 7 category/java/design GodClass (Lanza-Marinescu): "
                                "WMC >= 47 AND ATFD > 5 AND TCC < 1/3",
                         constant="PMD defaults"),
    "pmd_CouplingBetweenObjects": dict(level="class", kind="component", group="coupling",
                                       bases=set(), headline=False, scope="java", origin="tool",
                                       source="PMD 7 design/CouplingBetweenObjects",
                                       constant="threshold 20 unique referenced types"),
    "pmd_TooManyMethods": dict(level="class", kind="component", group="size/complexity",
                               bases={"nom"}, headline=False, scope="java", origin="tool",
                               source="PMD 7 design/TooManyMethods", constant="maxmethods 10"),
    "pmd_ExcessiveClassLength": dict(level="class", kind="component", group="size/complexity",
                                     bases={"nloc"}, headline=False, scope="java", origin="tool",
                                     source="PMD 7 design/ExcessiveClassLength",
                                     constant="minimum 1000 lines"),
    "pmd_NcssCount": dict(level="class", kind="component", group="size/complexity",
                          bases={"nloc"}, headline=False, scope="java", origin="tool",
                          source="PMD 7 design/NcssCount (class form)",
                          constant="classReportLevel 1500"),
    "pmd_TooManyFields": dict(level="class", kind="component", group="size/complexity",
                              bases=set(), headline=False, scope="java", origin="tool",
                              source="PMD 7 design/TooManyFields", constant="maxfields 15"),
    "pmd_ExcessivePublicCount": dict(level="class", kind="component", group="size/complexity",
                                     bases={"nom"}, headline=False, scope="java", origin="tool",
                                     source="PMD 7 design/ExcessivePublicCount (public methods "
                                            "+ attributes; nom is a partial ingredient)",
                                     constant="minimum 45"),
    "pmd_ExcessiveImports": dict(level="class", kind="component", group="coupling",
                                 bases=set(), headline=False, scope="java", origin="tool",
                                 source="PMD 7 design/ExcessiveImports", constant="minimum 30"),
    "ck_LCOM": dict(level="class", kind="component", group="cohesion", bases=set(),
                    headline=False, scope="java", origin="tool",
                    source="CK 0.7.0 lcom* (Henderson-Sellers LCOM*); a cohesion clause, "
                           "e.g. of DECOR's Blob (LowCohesion). The 0.8 cut is this study's "
                           "choice on the [0,1] scale, not a canonical constant",
                    constant="LCOM* >= 0.8"),
    "ck_TCClow": dict(level="class", kind="component", group="cohesion", bases=set(),
                      headline=False, scope="java", origin="tool",
                      source="CK 0.7.0 tcc; the TCC clause of Lanza-Marinescu's God Class. "
                             "Alone it marks most classes (its prevalence is reported)",
                      constant="TCC < 1/3 with >= 2 methods"),
    "ck_CBOhigh": dict(level="class", kind="component", group="coupling", bases=set(),
                       headline=False, scope="java", origin="tool",
                       source="CK 0.7.0 cbo; the 14 cut is this study's choice with no "
                              "canonical source -- PMD's CouplingBetweenObjects is the cited "
                              "coupling definition",
                       constant="CBO >= 14"),
    "ck_LargeClass": dict(level="class", kind="component", group="size/complexity",
                          bases={"nom"}, headline=False, scope="java", origin="tool",
                          source="DECOR LargeClass clause from CK counts: NMD + NAD >= 20 "
                                 "(totalMethodsQty + totalFieldsQty); the size clause of "
                                 "decor_blob, registered so the conditional AUC can use it",
                          constant="NMD+NAD >= 20"),
    "decor_blob": dict(level="class", kind="composite", group="composite", bases={"nom"},
                       headline=True, scope="java", origin="composed",
                       conditional_on="ck_LargeClass",
                       source="DECOR Blob (Moha et al. 2010), approximated: LargeClass "
                              "(NMD + NAD >= 20) AND (LowCohesion LCOM* >= 0.8 OR a controller "
                              "class name). The association-to-data-classes clause is omitted",
                       constant="NMD+NAD >= 20; LCOM* >= 0.8"),
    # ---- method level ----
    "cc14": dict(level="method", kind="self", group="size/complexity", bases={"cc"},
                 headline=False, scope="all", origin="internal",
                 source="McCabe cyclomatic complexity; the cut is this study's (PMD reports at "
                        "10, Lanza-Marinescu's Brain Method uses CYCLO >= HIGH)",
                 constant="CC >= 14"),
    "cognitive15": dict(level="method", kind="self", group="size/complexity",
                        bases={"cognitive"}, headline=False, scope="all", origin="internal",
                        source="Campbell 2018 cognitive complexity; SonarSource/PMD default",
                        constant="cognitive >= 15"),
    "nesting5": dict(level="method", kind="self", group="size/complexity", bases={"nesting"},
                     headline=False, scope="all", origin="internal",
                     source="Lanza-Marinescu Brain Method MAXNESTING >= SEVERAL (2..5); the "
                            "study uses the strict end",
                     constant="nesting >= 5"),
    "loc50": dict(level="method", kind="self", group="size/complexity", bases={"nloc"},
                  headline=False, scope="all", origin="internal",
                  source="long method; the cut is this study's (Lanza-Marinescu use LOC >= 65 "
                         "for Java, PMD NcssCount reports at 60)",
                  constant="NLOC >= 50"),
    "params5": dict(level="method", kind="self", group="size/complexity", bases={"params"},
                    headline=False, scope="all", origin="internal",
                    source="long parameter list (Fowler); PMD ExcessiveParameterList default 10",
                    constant="params >= 5"),
    "brain_method": dict(level="method", kind="composite", group="composite",
                         bases={"nloc", "cc", "nesting"}, headline=True, scope="all",
                         origin="internal",
                         source="Lanza-Marinescu Brain Method without the NOAV clause, on the "
                                "study's OWN signals and cuts: long AND high-CC AND deeply "
                                "nested (loc50 AND cc14 AND nesting5). An INTERNAL composite: "
                                "cross-language, but not an external oracle",
                         constant="NLOC >= 50 and CC >= 14 and nesting >= 5"),
    "pmd_method_CC10": dict(level="method", kind="calibration", group="size/complexity",
                            bases={"cc"}, headline=False, scope="java", origin="tool",
                            source="PMD 7 design/CyclomaticComplexity (method/constructor form)",
                            constant="methodReportLevel 10"),
    "pmd_method_Cognitive15": dict(level="method", kind="calibration", group="size/complexity",
                                   bases={"cognitive"}, headline=False, scope="java", origin="tool",
                                   source="PMD 7 design/CognitiveComplexity (the reference "
                                          "implementation our `cognitive` estimates)",
                                   constant="reportLevel 15"),
    "pmd_method_NPath200": dict(level="method", kind="tool", group="composite", bases=set(),
                                headline=True, scope="java", origin="tool",
                                source="PMD 7 design/NPathComplexity (Nejmeh 1988): acyclic "
                                       "execution paths; no lexical signal here computes it",
                                constant="reportLevel 200"),
    "pmd_method_Ncss60": dict(level="method", kind="calibration", group="size/complexity",
                              bases={"nloc"}, headline=False, scope="java", origin="tool",
                              source="PMD 7 design/NcssCount (method/constructor form)",
                              constant="methodReportLevel 60"),
}


def register_human(label: str, level: str = "class") -> str:
    """Declare a human-labelled definition from --labels in the registry: `human_<label>` at
    class level (a labelled path), `human_method_<label>` at method level (a labelled path and
    line). A companion label `<label>_reviewed`, listing every unit the experts looked at, is
    registered as a component and named as the definition's `conditional_on`
    (link_reviewed), so the analysis scores the human definition within the reviewed units
    only: an unreviewed unit is unknown, not a negative."""
    name = f"human_{label}" if level == "class" else f"human_method_{label}"
    if name not in ORACLES:
        meta = dict(level=level, kind="human", group="human", bases=set(), headline=True,
                    scope="labelled", origin="human",
                    source="expert labels supplied with --labels", constant="none")
        if label.endswith("_reviewed"):
            meta.update(kind="component", headline=False,
                        source="the units the experts reviewed (--labels); the universe "
                               "of the matching human definition")
        ORACLES[name] = meta
    return name


def link_reviewed() -> None:
    """Name `<x>_reviewed` as the `conditional_on` of every registered human definition `<x>`
    that has one."""
    for name, meta in ORACLES.items():
        if meta.get("origin") == "human" and name + "_reviewed" in ORACLES:
            meta["conditional_on"] = name + "_reviewed"


def _base_closure(bases: set) -> set:
    """A base measure plus every signal that is an arithmetic function of it."""
    out = set(bases)
    for sig, inputs in extract.SIGNAL_INPUTS.items():
        if inputs & bases:
            out.add(sig)
    return out


def ingredients(oracle: str) -> set:
    """The SIGNALS (at the oracle's own level) whose AUC on this oracle is partly built in:
    its base measures, their derived signals, and at class level every aggregation of them.
    `nom` is a class-level signal in its own right."""
    meta = ORACLES[oracle]
    bases = set(meta["bases"])
    nom = {"nom"} if "nom" in bases else set()
    closure = _base_closure(bases - {"nom"})
    if meta["level"] == "method":
        return closure
    return nom | {f"{b}_{agg}" for b in closure for agg in metrics.AGGREGATIONS}


def oracle_registry() -> dict:
    """The registry as plain JSON-able data, with the ingredient signals expanded per oracle,
    plus the signal pools and the relative rules' constants -- written with every run."""
    return {
        "oracles": {name: {**{k: (sorted(v) if isinstance(v, set) else v)
                              for k, v in meta.items()},
                           "ingredients": sorted(ingredients(name))}
                    for name, meta in ORACLES.items()},
        "signals": {"method": list(metrics.METHOD_SIGNALS), "class": list(metrics.CLASS_SIGNALS),
                    "derived": {k: sorted(v) for k, v in extract.SIGNAL_INPUTS.items()}},
        "families": {lvl: {fam: list(sigs) for fam, sigs in fams.items()}
                     for lvl, fams in metrics.FAMILIES.items()},
        "algorithms": metrics.ALGORITHM_CONSTANTS,
        "pmd_thresholds": PMD_THRESHOLDS,
        "headline_order": ["tool", "human", "composed", "internal"],
        "universe": "class: files with >= 1 function (WMC > 0); method: functions (CC > 0). "
                    "Every relative rule is fitted on exactly the population it scores, zeros "
                    "included. A definition with scope 'java' is scored on the Java units only "
                    "(rules fitted on the Java units), so no unit the tool never evaluated is a "
                    "forced negative; its cells carry that smaller n_univ.",
        "zero_god_rule": "cells with n_god_univ == 0 are recorded for every repository and "
                         "must be included in every pooled statistic (stats.pooled_confusion).",
        "split": "explore/confirm is assigned by stats.assign_halves, stratified by "
                 "(language, tier), ordered by sha256 of the URL and alternated.",
        "pooling": "macro (one repository, one vote; stats.bootstrap_mean over repositories) is "
                   "primary; micro (stats.pooled_confusion, size-weighted) is secondary.",
    }


def write_oracles(out_dir: str) -> str:
    path = os.path.join(out_dir, "oracles.json")
    with open(path, "w") as fh:
        json.dump(oracle_registry(), fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# Java tool panels: PMD (class + method rules) and CK
# ---------------------------------------------------------------------------
def _rel(root: str, path: str) -> str:
    """A tool-reported path as the repo-relative path the extractor keys files by."""
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")


# class-level PMD rules used as god-class oracles (class-scoped largeness / coupling rules)
_PMD_CLASS_RULES = ("GodClass", "CouplingBetweenObjects", "TooManyMethods",
                    "ExcessiveClassLength", "NcssCount", "TooManyFields",
                    "ExcessivePublicCount", "ExcessiveImports")
# method-level PMD rules -> oracle names. The same PMD rule may report a class-level form
# ("The class 'X' has a total cyclomatic complexity ..."); only the method/constructor forms
# are taken, by the message prefix, and mapped to the innermost measured function containing
# the violation's begin line.
_PMD_METHOD_RULES = {"CyclomaticComplexity": "pmd_method_CC10",
                     "CognitiveComplexity": "pmd_method_Cognitive15",
                     "NPathComplexity": "pmd_method_NPath200",
                     "NcssCount": "pmd_method_Ncss60"}
_PMD_METHOD_MSG = re.compile(r"^The (?:method|constructor) ")
_PMD_VALUE = re.compile(r"\bof (\d+)")
# The four metric rules run at report level 1 (every method and class reports its VALUE), and
# THESE thresholds -- PMD's defaults, quoted in the registry -- are applied here. That gives a
# continuous calibration of the lexical estimators against PMD's values (Spearman per
# repository from the sidecar's pmd_values), not only agreement at one cut.
PMD_THRESHOLDS = {"CyclomaticComplexity": {"method": 10, "class": 80},
                  "CognitiveComplexity": {"method": 15},
                  "NPathComplexity": {"method": 200},
                  "NcssCount": {"method": 60, "class": 1500}}
_PMD_VALUE_NAME = {"CyclomaticComplexity": "cc", "CognitiveComplexity": "cognitive",
                   "NPathComplexity": "npath", "NcssCount": "ncss"}
_PMD_RULESET = """<?xml version="1.0"?>
<ruleset name="ccs" xmlns="http://pmd.sourceforge.net/ruleset/2.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://pmd.sourceforge.net/ruleset/2.0.0 https://pmd.sourceforge.io/ruleset_2_0_0.xsd">
  <description>PMD design category; the four metric rules at report level 1 so every value is reported</description>
  <rule ref="category/java/design.xml">
    <exclude name="CyclomaticComplexity"/>
    <exclude name="CognitiveComplexity"/>
    <exclude name="NPathComplexity"/>
    <exclude name="NcssCount"/>
  </rule>
  <rule ref="category/java/design.xml/CyclomaticComplexity">
    <properties><property name="methodReportLevel" value="1"/><property name="classReportLevel" value="1"/></properties>
  </rule>
  <rule ref="category/java/design.xml/CognitiveComplexity">
    <properties><property name="reportLevel" value="1"/></properties>
  </rule>
  <rule ref="category/java/design.xml/NPathComplexity">
    <properties><property name="reportLevel" value="1"/></properties>
  </rule>
  <rule ref="category/java/design.xml/NcssCount">
    <properties><property name="methodReportLevel" value="1"/><property name="classReportLevel" value="1"/></properties>
  </rule>
</ruleset>
"""


def _pmd_report(pmd: str, root: str, files: list[str],
                aux_classpath: str | None = None) -> dict | None:
    """Run PMD's whole Java design category on EXACTLY the Java files given (a --file-list, so
    every module is covered and test code is excluded the same way), the four metric rules at
    report level 1 (see PMD_THRESHOLDS). Returns
      {"class":  {rule: set(repo-relative paths)}   -- class findings; for the metric rules,
                                                       those at or above the CLASS threshold
       "method": [(path, beginline, rule, description)]  -- method/constructor findings at or
                                                       above the METHOD threshold
       "values": {"method": [(path, beginline, metric, value)],   -- EVERY reported value
                  "class": {metric: {path: value}}}}
    keyed by path, not basename, so same-named classes in different packages do not collide.
    None if PMD could not be run or its report not parsed. NOTE: PMD runs without an auxiliary
    classpath, so type-resolution-dependent metrics (ATFD, coupling) see only what the sources
    themselves declare (see README, threats to validity) -- unless `aux_classpath` is given
    (the classpath validation sub-study, classpath_check.py)."""
    if not files:
        return {"class": {}, "method": [], "values": {"method": [], "class": {}}}
    fd, lst = tempfile.mkstemp(prefix="ccs-pmd-", suffix=".txt")
    fd2, rules = tempfile.mkstemp(prefix="ccs-pmd-rules-", suffix=".xml")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(os.path.join(root, f) for f in files) + "\n")
        with os.fdopen(fd2, "w") as fh:
            fh.write(_PMD_RULESET)
        cmd = [pmd, "check", "--file-list", lst, "-R", rules,
               "--format", "json", "--no-cache", "--no-progress"]
        if aux_classpath:
            cmd += ["--aux-classpath", aux_classpath]
        out = subprocess.run(cmd, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None                     # PMD missing/crashed here: a pmd_error, never a raise
    finally:
        for f in (lst, rules):
            try:
                os.unlink(f)
            except OSError:
                pass
    try:
        d = json.loads(out.stdout)
    except Exception:
        return None
    byrule: dict = {}
    methods: list = []
    mvals: list = []
    cvals: dict = {}
    for f in d.get("files", []):
        rel = _rel(root, f["filename"])
        for v in f.get("violations", []):
            rule = v.get("rule")
            desc = v.get("description") or ""
            if rule in _PMD_METHOD_RULES:
                m = _PMD_VALUE.search(desc)
                value = int(m.group(1)) if m else None
                metric = _PMD_VALUE_NAME[rule]
                line = int(v.get("beginline") or 0)
                if _PMD_METHOD_MSG.match(desc):
                    if value is not None:
                        mvals.append((rel, line, metric, value))
                    thr = PMD_THRESHOLDS[rule].get("method")
                    if value is not None and thr is not None and value >= thr:
                        methods.append((rel, line, rule, desc))
                    continue
                # the class form: keep its value; it is a class finding only above the class
                # threshold (NcssCount 1500 is the registered pmd_NcssCount definition)
                if value is not None:
                    cvals.setdefault(metric, {})[rel] = max(value, cvals.get(metric, {}).get(rel, 0))
                thr = PMD_THRESHOLDS[rule].get("class")
                if value is None or thr is None or value < thr:
                    continue
            byrule.setdefault(rule, set()).add(rel)
    return {"class": byrule, "method": methods, "values": {"method": mvals, "class": cvals}}


def _pmd_violations(pmd: str, root: str, files: list[str]) -> dict | None:
    """rule name -> set of repo-relative paths (class-level view of _pmd_report)."""
    rep = _pmd_report(pmd, root, files)
    return None if rep is None else rep["class"]


def _unit_at(by_file: dict, rel: str, line: int):
    """The innermost measured function in `rel` whose [start_line, end_line] contains `line`
    (nested/anonymous-class methods are their own units), or None."""
    best = None
    for st, en, fid in by_file.get(rel, ()):
        if st <= line <= en and (best is None or (en - st) < (best[1] - best[0])):
            best = (st, en, fid)
    return best[2] if best else None


def _by_file(funcs: dict) -> dict:
    by_file: dict = defaultdict(list)
    for fid, r in funcs.items():
        by_file[r["file"]].append((r["start_line"], r["end_line"], fid))
    return by_file


def pmd_method_oracles(method_violations: list, funcs: dict) -> tuple[dict, int]:
    """Map PMD's method-level findings (already at or above their thresholds) onto the
    extractor's function units. Returns ({oracle_name: set(fid)}, n_unmatched)."""
    by_file = _by_file(funcs)
    out = {name: set() for name in _PMD_METHOD_RULES.values()}
    unmatched = 0
    for rel, line, rule, _ in method_violations:
        fid = _unit_at(by_file, rel, line)
        if fid is None:
            unmatched += 1
            continue
        out[_PMD_METHOD_RULES[rule]].add(fid)
    return out, unmatched


def pmd_method_values(method_values: list, funcs: dict) -> tuple[dict, int]:
    """PMD's own per-method metric VALUES mapped onto the extractor's units:
    ({metric: {fid: value}}, n_unmatched). A unit PMD reported more than once (it cannot, but
    a fake could) keeps the maximum."""
    by_file = _by_file(funcs)
    out: dict = {m: {} for m in _PMD_VALUE_NAME.values()}
    unmatched = 0
    for rel, line, metric, value in method_values:
        fid = _unit_at(by_file, rel, line)
        if fid is None:
            unmatched += 1
            continue
        out[metric][fid] = max(value, out[metric].get(fid, 0))
    return out, unmatched


def _ck_report(ck_jar: str, root: str, files: list[str]) -> dict | None:
    """Run CK (mauricioaniche/ck) over the checkout and derive, over the files the extractor
    measured (so CK's view of tests matches ours):
      defs             : the cohesion/coupling COMPONENT definitions ck_LCOM / ck_TCClow /
                         ck_CBOhigh, the size clause ck_LargeClass and the composite decor_blob
                         (see ORACLES), keyed by repo-relative path (a file is marked if ANY
                         class in it qualifies), over the measured files only;
      outside          : per definition, how many qualifying CK rows fell in files NOT in the
                         measured set (test, generated, oversize or lizard-unparsed files), so
                         positives outside the universe are counted, never silent;
      classes_per_file : how many classes CK found in each measured file, so the file-as-class
                         approximation is quantified (README, threats to validity).
    Like PMD, CK runs without a classpath. Returns None if CK produced no class table."""
    import csv as _csvmod
    _CONTROLLER = re.compile(r"(process|control|manage|system|command|handler|manager|"
                             r"driver|exec|service|coordinator|dispatcher)", re.I)
    measured = set(files)
    outdir = tempfile.mkdtemp(prefix="ccs-ck-")
    try:
        subprocess.run(["java", "-jar", ck_jar, root, "false", "0", "false", outdir + os.sep],
                       capture_output=True, text=True, timeout=1800)
        path = os.path.join(outdir, "class.csv")
        if not os.path.isfile(path):
            return None
        defs = {"ck_LCOM": set(), "ck_TCClow": set(), "ck_CBOhigh": set(),
                "ck_LargeClass": set(), "decor_blob": set()}
        outside: dict = {k: 0 for k in defs}
        per_file: dict = defaultdict(int)

        def num(row, key):
            try:
                return float(row.get(key, ""))
            except (TypeError, ValueError):
                return None
        with open(path, newline="") as fh:
            for row in _csvmod.DictReader(fh):
                if not row.get("file"):
                    continue
                b = _rel(root, row["file"])
                inside = b in measured
                if inside:
                    per_file[b] += 1
                lcomn, tcc, cbo = num(row, "lcom*"), num(row, "tcc"), num(row, "cbo")
                nm = num(row, "totalMethodsQty") or 0
                nf = num(row, "totalFieldsQty") or 0
                name = (row.get("class") or "").split(".")[-1]
                low_coh = lcomn is not None and lcomn >= 0.8
                large = (nm + nf) >= 20
                hits = []
                if low_coh:
                    hits.append("ck_LCOM")
                if tcc is not None and 0 <= tcc < 1 / 3 and nm >= 2:
                    hits.append("ck_TCClow")
                if cbo is not None and cbo >= 14:
                    hits.append("ck_CBOhigh")
                if large:
                    hits.append("ck_LargeClass")
                if large and (low_coh or _CONTROLLER.search(name)):
                    hits.append("decor_blob")
                for h in hits:
                    if inside:
                        defs[h].add(b)
                    else:
                        outside[h] += 1
        return {"defs": defs, "outside": outside, "classes_per_file": dict(per_file)}
    except Exception:
        return None
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def _ck_gods(ck_jar: str, root: str, files: list[str]) -> dict | None:
    rep = _ck_report(ck_jar, root, files)
    return None if rep is None else rep["defs"]


# ---------------------------------------------------------------------------
# human labels (external ground truth)
# ---------------------------------------------------------------------------
def load_labels(path: str | None) -> dict:
    """Expert labels as oracles. CSV columns: repo (GitHub URL or owner/name), commit (full sha
    the labels were made at), path (repo-relative file), label (e.g. blob), and optionally
    line: a row WITH a line is a method-level label (the function containing that line), a
    row without one is class-level (the file). Returns {(repo_key_lower, commit): {label:
    set(items)}} where an item is a path or a (path, line) pair and repo_key is both the URL
    (without .git) and owner/name, so either spelling matches the sample. Labels are applied
    to a repository ONLY when its sampled commit equals the label's commit; otherwise the row
    records `labels_commit_mismatch` and no human oracle is added. A label `<x>_reviewed`
    lists the units the experts looked at and becomes the universe of `<x>` (register_human)."""
    if not path:
        return {}
    out: dict = {}
    with open(path, newline="") as fh:
        for row in _csv.DictReader(fh):
            repo = (row.get("repo") or "").strip()
            commit = (row.get("commit") or "").strip().lower()
            p = (row.get("path") or "").strip().lstrip("/").replace(os.sep, "/")
            label = re.sub(r"\W+", "_", (row.get("label") or "").strip().lower()).strip("_")
            line = (row.get("line") or "").strip()
            if not (repo and commit and p and label):
                continue
            item = (p, int(line)) if line else p
            for key in _repo_keys(repo):
                out.setdefault((key, commit), {}).setdefault(label, set()).add(item)
    return out


def _repo_keys(repo: str) -> set:
    r = repo.strip().lower()
    r = r[:-4] if r.endswith(".git") else r
    keys = {r}
    m = re.search(r"github\.com[/:]([^/]+/[^/]+)$", r)
    if m:
        keys.add(m.group(1))
    else:
        keys.add(f"https://github.com/{r}")
    return keys


def labels_for(labels: dict, url: str, full_name: str, commit: str) -> tuple[dict, list]:
    """({label: set(paths)} for this repo at this commit, [labels present at ANOTHER commit])."""
    keys = _repo_keys(url) | _repo_keys(full_name)
    commit = (commit or "").lower()
    hit: dict = {}
    other: list = []
    for (k, c), by_label in labels.items():
        if k in keys:
            if c == commit:
                for lab, ps in by_label.items():
                    hit.setdefault(lab, set()).update(ps)
            else:
                other.extend(by_label)
    return hit, sorted(set(other) - set(hit))


# ---------------------------------------------------------------------------
# per-repository measurement
# ---------------------------------------------------------------------------
_APP_FILES = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Procfile")


def classify_kind(root: str, funcs: dict) -> str:
    """Post-hoc heuristic: application vs library. Not controlled by the sampler and not a
    precise taxonomy; it is reported so the realized type mix of the sample is visible.
    Signals of a deployable application: a container/deploy descriptor, a Rust binary crate
    (main.rs without lib.rs), a Python `__main__.py`, or an entry function named `main`
    (Go/Java/C/Rust). Everything else is called a library."""
    try:
        top = set(os.listdir(root))
    except OSError:
        top = set()
    if top & set(_APP_FILES):
        return "application"
    hits = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "vendor",
                                                        "target", "build", "dist", ".venv")]
        for f in filenames:
            if f in _APP_FILES or f == "__main__.py" or f in ("main.rs", "lib.rs"):
                hits.add(f)
    if hits & set(_APP_FILES) or "__main__.py" in hits or ("main.rs" in hits and "lib.rs" not in hits):
        return "application"
    if any(r.get("name") == "main" for r in funcs.values()):   # Go/Java/C/Rust entry point
        return "application"
    return "library"


def _cell(outset: set, god: set, universe: set) -> dict:
    """Lean confusion counts for one (signal, definition) pair; MCC/F1/precision/recall are
    derived downstream from these four, keeping the per-repo matrix small. Recorded even when
    the definition marks nothing in this repository (n_god_univ == 0)."""
    return {"n_univ": len(universe), "n_out": len(outset & universe),
            "n_overlap": len(outset & god & universe), "n_god_univ": len(universe & god)}


def oracle_scope(name: str) -> str:
    """The population a definition is scored on: "java" for a Java-only tool definition (its
    rules fitted on, and its cells counted over, the Java units only), else "all"."""
    return "java" if ORACLES.get(name, {}).get("scope") == "java" else "all"


def _sigs(level_dict):
    return [k for k in level_dict if k not in ("universe", "_vals", "_diag")]


def _matrix_block(mx_by_scope: dict, method_oracles: dict, class_oracles: dict) -> dict:
    """The full detection matrix. `mx_by_scope` maps "all" and "java" to a
    metrics.matrix_outliers result (the Java one fitted on the Java units only). For every
    (level, signal, algorithm) cell: the confusion counts against every applicable god
    DEFINITION, over that definition's own scope (all keyed like the extractor: function ids at
    method level, repo-relative paths at class level). Also, for every (level, signal,
    definition): the THRESHOLD-FREE AUC/AP of the raw signal, which separates signal quality
    from the outlier algorithm's threshold; for a composite with a registered size clause
    (`conditional_on`), the AUC WITHIN the units that already satisfy that clause; per oracle,
    how many of its positives fell OUTSIDE the universe; and per signal, the scale the modified
    z used and the zero share (diagnostics the analysis reports first)."""
    def level_block(level, oracles):
        mx_all = mx_by_scope["all"][level]
        signals = _sigs(mx_all)
        scope_of = {name: oracle_scope(name) for name in oracles}

        def mx_for(name):
            return mx_by_scope[scope_of[name]][level]

        cells = {sig: {algo: {} for algo in metrics.ALGORITHMS} for sig in signals}
        aucs = {sig: {} for sig in signals}
        for name, god in oracles.items():
            m = mx_for(name)
            universe = m["universe"]
            for sig in signals:
                for algo, outset in m[sig].items():
                    cells[sig][algo][name] = _cell(outset, god, universe)
                a, pr, ng, _ = metrics.auc_ap(m["_vals"][sig], god, universe)
                aucs[sig][name] = {"auc": round(a, 4) if a is not None else None,
                                   "ap": round(pr, 4) if pr is not None else None, "n_god": ng}
        # conditional AUC: within the units that satisfy the composite's size clause
        given: dict = {}
        for name, god in oracles.items():
            cond = ORACLES.get(name, {}).get("conditional_on")
            if not cond or cond not in oracles:
                continue
            m = mx_for(name)
            sub = m["universe"] & oracles[cond]
            given[name] = {"given": cond, "n_univ": len(sub), "n_god": len(sub & god),
                           "signals": {}}
            for sig in signals:
                a, pr, ng, _ = metrics.auc_ap(m["_vals"][sig], god, sub)
                given[name]["signals"][sig] = {
                    "auc": round(a, 4) if a is not None else None,
                    "ap": round(pr, 4) if pr is not None else None}
        outside = {name: len(god - mx_all["universe"]) for name, god in oracles.items()}
        return {
            "n_univ": len(mx_all["universe"]),
            "n_univ_scope": {sc: len(mx_by_scope[sc][level]["universe"])
                             for sc in mx_by_scope},
            "oracle_scope": scope_of,
            "oracle_gods": {name: len(g) for name, g in oracles.items()},
            "god_outside_univ": outside,
            "cells": cells, "auc": aucs, "auc_given": given,
            "diag": dict(mx_all["_diag"]),
        }

    m = level_block("method", method_oracles)
    c = level_block("class", class_oracles)
    c["wmc47_gods"] = c["oracle_gods"].pop("wmc47", 0)
    return {
        "universe_note": "common per-level universe (funcs cc>0 / files wmc>0); a 'java'-scoped "
                         "definition is scored on the Java units only",
        "signals_method": _sigs(mx_by_scope["all"]["method"]),
        "signals_class": _sigs(mx_by_scope["all"]["class"]),
        "method": m, "class": c,
    }


def _unit_payload(mx, method_oracles, class_oracles, pmd_values=None, java_units=None) -> dict:
    """Per-unit raw signal values and god membership for one repo, for cross-repo analyses the
    lean matrix cannot carry (measure correlation, the relative-vs-absolute head-to-head with
    BOTH sides tuned the same way, the pooled standardised AUC, bootstrap CIs, per-language
    breakdowns, the continuous calibration against PMD). Written to the run's append-only
    `*.units.jsonl` sidecar, NOT to study.json. Units are the common per-level universe (ALL
    units; a Java-scoped analysis filters by the unit's path, `.java`), in a fixed order;
    `values[signal]` aligns to `units`, `god_idx[oracle]` lists god positions (an empty list
    when the oracle marks nothing here -- keep those repositories in every pooled analysis),
    and at method level `pmd_values[metric]` holds PMD's own value per unit: None for a
    non-Java unit, 0 for a Java unit PMD did not report (CognitiveComplexity reports from 1;
    the other three report every method, so 0 there means PMD saw no method at that unit,
    e.g. a lambda lizard counts as a function)."""
    def level(level_dict, oracles, extra=None):
        universe = sorted(level_dict["universe"],
                          key=lambda u: u if isinstance(u, str) else "\u0000".join(u))
        pos = {u: i for i, u in enumerate(universe)}
        signals = _sigs(level_dict)
        vals = level_dict["_vals"]
        values = {sig: [round(float(vals[sig].get(u, 0)), 4) for u in universe]
                  for sig in signals}
        god_idx = {name: sorted(pos[u] for u in g if u in pos)
                   for name, g in oracles.items()}
        units = [u if isinstance(u, str) else "::".join(u) for u in universe]
        out = {"units": units, "signals": signals, "values": values, "god_idx": god_idx}
        if extra is not None:
            out["pmd_values"] = {
                metric: [(byunit.get(u, 0) if u in java_units else None) for u in universe]
                for metric, byunit in extra.items()}
        return out

    return {"method": level(mx["method"], method_oracles, pmd_values),
            "class": level(mx["class"], class_oracles)}


def analyse(root: str, pmd: str | None, ck: str | None = None,
            human: dict | None = None) -> dict:
    """Measure one checkout: every signal, every applicable oracle, the matrix and the per-unit
    payload. `human` is {label: set(repo-relative paths)} of expert labels for THIS commit."""
    res = extract.analyze_tree(root)
    funcs, wmc, skipped = res["funcs"], res["wmc"], res["skipped"]
    if not funcs:
        return {"error": "no functions"}
    kind = classify_kind(root, funcs)
    # method-level definitions: five SINGLE-metric thresholds (self-referential for their
    # signal) and the INTERNAL composite brain_method (see ORACLES for provenance).
    method_oracles = {
        "cc14": {fid for fid, r in funcs.items() if r.get("cc", 0) >= CC_GOD},
        "cognitive15": {fid for fid, r in funcs.items() if r.get("cognitive", 0) >= 15},
        "nesting5": {fid for fid, r in funcs.items() if r.get("nesting", 0) >= 5},
        "loc50": {fid for fid, r in funcs.items() if r.get("nloc", 0) >= 50},
        "params5": {fid for fid, r in funcs.items() if r.get("params", 0) >= 5},
        "brain_method": {fid for fid, r in funcs.items()
                         if r.get("nloc", 0) >= 50 and r.get("cc", 0) >= CC_GOD
                         and r.get("nesting", 0) >= 5},
    }
    c_god = {f for f, w in wmc.items() if w >= extract.WMC_GOD}       # class size reference
    is_java = lambda path: path.endswith(".java")
    n_trivial = sum(1 for r in funcs.values() if r.get("cc", 0) <= 1)
    n_anon = sum(1 for r in funcs.values() if "anonymous" in (r.get("name") or "").lower())
    out = {"n_funcs": len(funcs), "n_files": len(wmc), "kind": kind, "wmc_gods": len(c_god),
           # diagnostics the analysis reports before any accuracy number
           "files_skipped": {k: len(v) for k, v in skipped.items()},
           "java_files_skipped": {k: sum(1 for f in v if is_java(f)) for k, v in skipped.items()},
           "trivial_frac": round(n_trivial / len(funcs), 4),     # units with CC <= 1
           "anon_frac": round(n_anon / len(funcs), 4)}           # lizard "(anonymous)" units

    # Java reference panels, keyed by repo-relative path over exactly the measured files, PLUS
    # (for PMD) the Java files that left the universe as oversize or unparsed, so a god class
    # in one of those is counted as a positive OUTSIDE the universe rather than vanishing.
    java_files = sorted(f for f in wmc if is_java(f))
    java_extra = sorted(f for k in ("oversize", "unparsed") for f in skipped[k] if is_java(f))
    java_units = {fid for fid, r in funcs.items() if is_java(r["file"])}
    class_oracles: dict = {"wmc47": c_god}
    pmd_values = None
    if pmd:
        rep = _pmd_report(pmd, root, java_files + java_extra)
        if rep is None:
            out["pmd_error"] = "PMD produced no parsable report"
        else:
            class_oracles.update({"pmd_" + r: rep["class"].get(r, set())
                                  for r in _PMD_CLASS_RULES})
            out["pmd_gods"] = len(rep["class"].get("GodClass", set()) & set(java_files))
            m_or, unmatched = pmd_method_oracles(rep["method"], funcs)
            method_oracles.update(m_or)
            out["pmd_method_gods"] = {k: len(v) for k, v in m_or.items()}
            out["pmd_method_unmatched"] = unmatched
            pmd_values, _ = pmd_method_values(rep["values"]["method"], funcs)
            out["pmd_method_values"] = {m: len(v) for m, v in pmd_values.items()}
    if ck:
        rep = _ck_report(ck, root, java_files)
        if rep is None:
            out["ck_error"] = "CK produced no class table"
        else:
            class_oracles.update(rep["defs"])
            out["ck_def_gods"] = {name: len(s) for name, s in rep["defs"].items()}
            out["ck_def_outside"] = rep["outside"]
            cpf = rep["classes_per_file"]
            out["java_files_ck"] = len(cpf)
            out["java_files_multi_class"] = sum(1 for n in cpf.values() if n > 1)
    if human:
        out["human_labels"] = {}
        by_file = _by_file(funcs)
        for label, items in sorted(human.items()):
            paths = {i for i in items if isinstance(i, str)}
            lines = {i for i in items if isinstance(i, tuple)}
            if paths:
                name = register_human(label, "class")
                matched = {p for p in paths if p in wmc}
                class_oracles[name] = matched
                out["human_labels"][label] = {"labelled": len(paths), "measured": len(matched)}
            if lines:
                name = register_human(label, "method")
                matched = set()
                for p, ln in lines:
                    fid = _unit_at(by_file, p, ln)
                    if fid is not None:
                        matched.add(fid)
                method_oracles[name] = matched
                out["human_labels"][label + "@method"] = {"labelled": len(lines),
                                                          "measured": len(matched)}
        link_reviewed()

    # full (level x signal x algorithm x oracle) comparison matrix, computed once per SCOPE
    # (all units; the Java units alone, for the Java-only definitions) and split into the lean
    # per-repo block (-> study.json) and the per-unit payload (-> units sidecar).
    mx = metrics.matrix_outliers(funcs, wmc)
    scopes = {"all": mx}
    if any(oracle_scope(n) == "java" for n in list(method_oracles) + list(class_oracles)):
        scopes["java"] = metrics.matrix_outliers(
            {fid: r for fid, r in funcs.items() if fid in java_units},
            {f: w for f, w in wmc.items() if is_java(f)})
    out["matrix"] = _matrix_block(scopes, method_oracles, class_oracles)
    out["_units"] = _unit_payload(mx, method_oracles, class_oracles, pmd_values, java_units)
    return out


def is_usable(row: dict, min_funcs: int = MIN_FUNCS, min_univ: int = MIN_UNIV) -> bool:
    """Whether a measured row clears the substance floor: it parsed, has >= min_funcs
    functions and a class-level universe (files with WMC>0) of at least min_univ. Decided
    only on quantities fixed before any detection outcome, so a repository cannot be kept or
    dropped on its results. The sample is drawn with the same floor (step2_sample.sh)."""
    if row.get("error") or row.get("excluded_min_substance"):
        return False
    if (row.get("n_funcs") or 0) < min_funcs:
        return False
    nu = (((row.get("matrix") or {}).get("class") or {}).get("n_univ")) or 0
    return nu >= min_univ


# ---------------------------------------------------------------------------
# pins, preflight
# ---------------------------------------------------------------------------
# PINNED tool versions. Every number in the study is a lizard, PMD or CK number, so a version
# change can move all of them; drift is refused, not tolerated.
LIZARD_VERSION = "1.23.0"
PMD_VERSION = "7.27.0"
CK_VERSION = "0.7.0"
CK_SHA256 = "2ddfdc275b6b59c2033e03253c4fec511c338fe494a10b70f651bc039a72c74d"

# lizard 1.24.x regressed its Java state machine: a bare class annotation followed by a
# parenthesised one (@Entity then @Table(...)) makes the WHOLE file parse to zero functions,
# silently. Every JPA entity would vanish from the study. This fixture must parse.
_PARSER_FIXTURE_PATH = "src/main/java/fixture/Fixture.java"
_PARSER_FIXTURE = """package fixture;

import jakarta.persistence.*;

@Entity
@Table(name = "owners")
public class Fixture {

    @Column(name = "email")
    private String email;

    public String getEmail() {
        return this.email;
    }

    @PrePersist
    void normalise() {
        if (this.email != null) {
            this.email = this.email.toLowerCase();
        }
    }
}
"""
_PARSER_EXPECTED = {"Fixture::getEmail", "Fixture::normalise"}


# A Ruby method holding a `case` statement: the pinned lizard ends `f` at the case's `end`
# (line 8) instead of the method's (line 10), silently truncating the unit. While this fails,
# Ruby is not sampled (EXCLUDED_LANGUAGES); preflight reports the status every run.
_RUBY_BOUND_FIXTURE = """class A
  def f(x)
    case x
    when 1
      x = 2
    else
      x = 3
    end
    return x
  end

  def g
    2
  end
end
"""


def ruby_parser_bounds_ok() -> bool:
    """True if lizard bounds the Ruby fixture's `f` on its own `end` (line 10)."""
    import lizard
    fl = lizard.analyze_file.analyze_source_code("a.rb", _RUBY_BOUND_FIXTURE).function_list
    by = {f.name: (f.start_line, f.end_line) for f in fl}
    return by.get("f") == (2, 10) and by.get("g") == (12, 14)


class ParserBlind(RuntimeError):
    """lizard cannot see functions it must see; the study cannot be measured with it."""


class SignalDead(RuntimeError):
    """A complexity signal is degenerate (constant) on a fixture where it must vary: the
    measurement would silently carry a dead column (as `nesting` once did)."""


def check_parser() -> None:
    """Fail closed if the installed lizard is blind to annotated Java classes."""
    import lizard
    got = {f.name for f in lizard.analyze_file.analyze_source_code(
        _PARSER_FIXTURE_PATH, _PARSER_FIXTURE).function_list}
    if not _PARSER_EXPECTED <= got:
        raise ParserBlind(
            f"lizard {_lizard_version()} sees {sorted(got)} in an @Entity/@Table class, "
            f"expected {sorted(_PARSER_EXPECTED)} (the lizard 1.24 Java regression). "
            f"Install the pinned parser: pip install 'lizard=={LIZARD_VERSION}'")


# One deeply nested, branchy function ("deep") and one trivial function ("small") in EVERY
# sampled language. Preflight measures them and requires every complexity signal to separate
# deep from small in every language, so no signal can be a dead column for any language.
_SIGNAL_FIXTURES = {
    "src/Deep.java": """public class Deep {
    public int deep(int x, int y, int z, int w, int v) {
        int s = 0;
        for (int a = 0; a < x; a++) {
            if (a > y) {
                while (s < z) {
                    if (s % 2 == 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                    if (s > 100) { return s; }
                }
            } else if (a == v) { throw new IllegalStateException("x"); }
        }
        return s;
    }
    public int small(int x) { return x + 1; }
}
""",
    "src/deep.py": """def deep(x, y, z, w, v):
    s = 0
    for a in range(x):
        if a > y:
            while s < z:
                if s % 2 == 0 and a > 1 or w > 3:
                    s += 2
                else:
                    s += 1
                if s > 100:
                    return s
        elif a == v:
            raise ValueError("x")
    return s


def small(x):
    return x + 1
""",
    "src/deep.js": """function deep(x, y, z, w, v) {
    let s = 0;
    for (let a = 0; a < x; a++) {
        if (a > y) {
            while (s < z) {
                if (s % 2 === 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                if (s > 100) { return s; }
            }
        } else if (a === v) { throw new Error("x"); }
    }
    return s;
}
function small(x) { return x + 1; }
""",
    "src/deep.ts": """export function deep(x: number, y: number, z: number, w: number, v: number): number {
    let s = 0;
    for (let a = 0; a < x; a++) {
        if (a > y) {
            while (s < z) {
                if (s % 2 === 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                if (s > 100) { return s; }
            }
        } else if (a === v) { throw new Error("x"); }
    }
    return s;
}
export function small(x: number): number { return x + 1; }
""",
    "src/deep.go": """package deep

func deep(x, y, z, w, v int) int {
    s := 0
    for a := 0; a < x; a++ {
        if a > y {
            for s < z {
                if s%2 == 0 && a > 1 || w > 3 { s += 2 } else { s += 1 }
                if s > 100 { return s }
            }
        } else if a == v { panic("x") }
    }
    return s
}

func small(x int) int { return x + 1 }
""",
    "src/deep.c": """int deep(int x, int y, int z, int w, int v) {
    int s = 0;
    for (int a = 0; a < x; a++) {
        if (a > y) {
            while (s < z) {
                if (s % 2 == 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                if (s > 100) { return s; }
            }
        } else if (a == v) { return -1; }
    }
    return s;
}
int small(int x) { return x + 1; }
""",
    "src/deep.cpp": """namespace d {
int deep(int x, int y, int z, int w, int v) {
    int s = 0;
    for (int a = 0; a < x; a++) {
        if (a > y) {
            while (s < z) {
                if (s % 2 == 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                if (s > 100) { return s; }
            }
        } else if (a == v) { throw 1; }
    }
    return s;
}
int small(int x) { return x + 1; }
}
""",
    "src/Deep.cs": """namespace D {
public class Deep {
    public int deep(int x, int y, int z, int w, int v) {
        int s = 0;
        for (int a = 0; a < x; a++) {
            if (a > y) {
                while (s < z) {
                    if (s % 2 == 0 && a > 1 || w > 3) { s += 2; } else { s += 1; }
                    if (s > 100) { return s; }
                }
            } else if (a == v) { throw new System.Exception("x"); }
        }
        return s;
    }
    public int small(int x) { return x + 1; }
}
}
""",
    "src/deep.rb": """class Deep
  def deep(x, y, z, w, v)
    s = 0
    x.times do |a|
      if a > y
        while s < z
          if s % 2 == 0 && a > 1 || w > 3
            s += 2
          else
            s += 1
          end
          return s if s > 100
        end
      elsif a == v
        raise "x"
      end
    end
    s
  end

  def small(x)
    x + 1
  end
end
""",
    "src/deep.php": """<?php
function deep($x, $y, $z, $w, $v) {
    $s = 0;
    for ($a = 0; $a < $x; $a++) {
        if ($a > $y) {
            while ($s < $z) {
                if ($s % 2 == 0 && $a > 1 || $w > 3) { $s += 2; } else { $s += 1; }
                if ($s > 100) { return $s; }
            }
        } elseif ($a == $v) { throw new Exception("x"); }
    }
    return $s;
}
function small($x) { return $x + 1; }
""",
    "src/deep.rs": """pub fn deep(x: i32, y: i32, z: i32, w: i32, v: i32) -> i32 {
    let mut s = 0;
    for a in 0..x {
        if a > y {
            while s < z {
                if s % 2 == 0 && a > 1 || w > 3 { s += 2; } else { s += 1; }
                if s > 100 { return s; }
            }
        } else if a == v { panic!("x"); }
    }
    s
}
pub fn small(x: i32) -> i32 { x + 1 }
""",
}
_FIXTURE_LANG = {"java": "Deep.java", "python": "deep.py", "javascript": "deep.js",
                 "typescript": "deep.ts", "go": "deep.go", "c": "deep.c", "c++": "deep.cpp",
                 "c#": "Deep.cs", "ruby": "deep.rb", "php": "deep.php", "rust": "deep.rs"}
# `small` is a one-liner, so deep must exceed it on every signal (differ, for cyc_density);
# nesting must reach the fixture's real depth (for > if > while > if = 4) within one of it.
_MIN_DEEP_NESTING = 3


def check_signals(languages=SAMPLED_LANGUAGES) -> dict:
    """Measure the fixture tree and fail closed (SignalDead) unless, in EVERY sampled language,
    every complexity signal separates `deep` from `small`, `deep` nests at least
    _MIN_DEEP_NESTING levels, and the class-level cc_sum equals WMC. Returns the per-language
    values of `deep` for the preflight log."""
    root = tempfile.mkdtemp(prefix="ccs-signals-")
    try:
        for rel, body in _SIGNAL_FIXTURES.items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(body)
        res = extract.analyze_tree(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    funcs, wmc = res["funcs"], res["wmc"]
    by_file: dict = defaultdict(dict)
    for r in funcs.values():
        by_file[os.path.basename(r["file"])][r["name"]] = r
    problems = []
    deep_values = {}
    for lang in languages:
        fname = _FIXTURE_LANG[lang]
        fns = by_file.get(fname, {})
        deep, small = fns.get("deep"), fns.get("small")
        if deep is None or small is None:
            problems.append(f"{lang}: lizard found {sorted(fns)} in {fname}, expected "
                            f"['deep', 'small'] -- the parser is blind to this language")
            continue
        # every signal must separate deep from small: higher on deep, except cyclomatic DENSITY,
        # where a one-line function is the maximum (1 branch / 1 line); it must merely differ.
        dead = [s for s in extract.COMPLEXITY_FIELDS
                if ((deep[s] == small[s]) if s == "cyc_density" else (not deep[s] > small[s]))]
        if dead:
            problems.append(f"{lang}: signal(s) {dead} do not separate deep from small "
                            f"(deep={ {s: deep[s] for s in dead} }, "
                            f"small={ {s: small[s] for s in dead} })")
        if deep["nesting"] < _MIN_DEEP_NESTING:
            problems.append(f"{lang}: nesting of deep is {deep['nesting']}, expected >= "
                            f"{_MIN_DEEP_NESTING}")
        deep_values[lang] = {s: deep[s] for s in extract.COMPLEXITY_FIELDS}
    mx = metrics.matrix_outliers(funcs, wmc)
    bad = [f for f in wmc if mx["class"]["_vals"]["cc_sum"].get(f) != wmc[f]]
    if bad:
        problems.append(f"class cc_sum != WMC on {bad}")
    if problems:
        raise SignalDead("complexity signals are not all alive on the fixture tree:\n  - "
                         + "\n  - ".join(problems))
    return deep_values


def _lizard_version() -> str:
    try:
        from importlib.metadata import version
        return version("lizard")
    except Exception:
        import lizard
        return str(getattr(lizard, "version", "") or getattr(lizard, "__version__", ""))


def pmd_version(pmd: str) -> str:
    """PMD prints an ASCII-art banner before its version line, so take the line that starts
    with 'PMD ' rather than the first line of output. "" if it cannot be run."""
    try:
        out = subprocess.run([pmd, "--version"], capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("PMD "):
            return line.split()[1]
    return ""


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def harness_commit() -> str | None:
    """The git commit of this harness (plus '-dirty' if the tree has uncommitted changes), so a
    run states exactly which measurement code produced it -- the record that the analysis
    plan was frozen before the data were seen. None outside a git checkout."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=30)
        if sha.returncode != 0:
            return None
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=30)
        return sha.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


def tool_versions(pmd: str | None, ck: str | None) -> dict:
    """The versions of every tool that shapes a measurement, recorded with each run so a
    replication can tell a tool change from a real difference."""
    import platform
    from . import __version__
    v = {"python": platform.python_version(), "lizard": _lizard_version(),
         "harness_commit": harness_commit(),
         "complexity_concentration_study": __version__}   # the code's own version, not stale
                                                          # install metadata
    if pmd:
        v["pmd"] = pmd_version(pmd) or None
    if ck:
        try:
            v["ck_sha256"] = _sha256(ck)
        except OSError:
            v["ck_sha256"] = None
    return v


def tool_drift(tools: dict) -> list[str]:
    """Every way the recorded tools differ from the pins; empty when all match."""
    out = []
    if tools.get("lizard") != LIZARD_VERSION:
        out.append(f"lizard {tools.get('lizard')} != pinned {LIZARD_VERSION}")
    if "pmd" in tools and tools["pmd"] != PMD_VERSION:
        out.append(f"PMD {tools['pmd']} != pinned {PMD_VERSION}")
    if "ck_sha256" in tools and tools["ck_sha256"] != CK_SHA256:
        out.append(f"CK jar sha256 {str(tools['ck_sha256'])[:12]}... is not CK {CK_VERSION} "
                   f"({CK_SHA256[:12]}...)")
    return out


def _java_smoke_source() -> str:
    """A deliberately god-like Java class (16 fields, 30 branching methods, one long deeply
    nested method) used only to verify, at preflight, that PMD and CK actually run AND produce
    a non-empty class panel AND a method-level finding here."""
    fields = "\n".join(f"    public int f{i};" for i in range(16))
    methods = "\n".join(
        f"    public int m{i}(int x) {{ if (x > {i}) {{ return f{i % 16} + x; }} "
        f"else {{ return f{i % 16} - x; }} }}" for i in range(30))
    body = "\n".join(
        f"        if (x > {i} && f{i % 16} > {i}) {{ for (int j = 0; j < x; j++) {{ "
        f"if (j % {i + 2} == 0) {{ s += j; }} else {{ s -= j; }} }} }}" for i in range(12))
    deep = ("    public int deep(int x) {\n        int s = 0;\n" + body
            + "\n        return s;\n    }")
    return ("public class PreflightGod {\n" + fields + "\n" + methods + "\n" + deep + "\n}\n")


def _env_problems() -> list[str]:
    """Missing non-Python runtime dependencies: git, for the sampler to clone with."""
    problems = []
    if shutil.which("git") is None:
        problems.append("`git` is not on PATH -- repositories cannot be cloned.")
    return problems


def _tool_problems(pmd: str | None, ck: str | None) -> list[str]:
    """Verify each CONFIGURED Java tool by actually running it on a synthetic god class, so a
    tool that is present-but-broken (wrong Java, unloadable ruleset, unparsable output) is caught
    here rather than emptying the Java panel on every repo. A tool left unset is not checked."""
    problems: list[str] = []
    if not (pmd or ck):
        return problems
    if shutil.which("java") is None:
        return ["no `java` on PATH -- PMD and CK both need a JRE (install one, or omit "
                "--pmd/--ck to run without the Java panels)."]
    smoke = tempfile.mkdtemp(prefix="ccs-preflight-")
    try:
        with open(os.path.join(smoke, "PreflightGod.java"), "w") as fh:
            fh.write(_java_smoke_source())
        if pmd:
            if not pmd_version(pmd):
                problems.append(f"--pmd {pmd!r}: PMD does not run here (need PMD {PMD_VERSION}). "
                                f"Fix the path, or omit --pmd.")
            else:
                rep = _pmd_report(pmd, smoke, ["PreflightGod.java"])
                if rep is None:
                    problems.append(f"--pmd {pmd!r}: PMD ran but produced no parsable report on "
                                    f"the smoke class -- the design panel would be silently empty.")
                elif not rep["class"]:
                    problems.append(f"--pmd {pmd!r}: PMD's design ruleset flagged nothing on a "
                                    f"30-method/16-field class -- the ruleset likely did not load, "
                                    f"so the Java PMD panel would be silently empty.")
                elif not rep["method"]:
                    problems.append(f"--pmd {pmd!r}: PMD reported no METHOD-level finding on a "
                                    f"deeply nested 12-branch method -- the method oracles "
                                    f"(pmd_method_*) would be silently empty.")
        if ck:
            if not os.path.isfile(ck):
                problems.append(f"--ck {ck!r}: CK jar not found. Fix the path, or omit --ck.")
            elif _ck_report(ck, smoke, ["PreflightGod.java"]) is None:
                problems.append(f"--ck {ck!r}: CK produced no class table on the smoke class -- "
                                f"the CK cohesion/coupling panel would be silently empty.")
    finally:
        shutil.rmtree(smoke, ignore_errors=True)
    return problems


def preflight(pmd: str | None, ck: str | None) -> None:
    """Fail LOUD and EARLY, before any repository is cloned, if ANYTHING needed to capture the
    full set of numbers is missing, broken, or off the pins: the lizard parser (not blind), every
    complexity signal alive in every sampled language (check_signals), git, and -- when
    configured -- PMD and CK actually RUNNING on a synthetic Java class and returning a non-empty
    class panel and a method-level finding. A tool left unset is a deliberate choice to skip
    its panel; that is reported explicitly so an omission is never mistaken for a silent hole.

    Tool VERSIONS are enforced EXACTLY against the pins (lizard, PMD, CK sha256): a mismatch is a
    HARD failure, not a warning, so every run and every independent review uses identical tools
    and the numbers are comparable. To use a different version deliberately, change the pin in
    this file -- a git-auditable code change -- so any resulting difference is traceable."""
    check_parser()                                   # lizard not blind (raises ParserBlind)
    check_signals()                                  # every signal alive (raises SignalDead)
    drift = tool_drift(tool_versions(pmd, ck))       # exact-pin mismatches are fatal here
    problems = _env_problems() + _tool_problems(pmd, ck) + list(drift)
    if drift:
        problems.append("the tool versions above are pinned for run-to-run reproducibility and "
                        "independent review; to use another version, change the pin in "
                        "complexity_concentration_study/study.py (a git-auditable code change), not at runtime.")
    if problems:
        raise RuntimeError(
            "PREFLIGHT FAILED -- fix these before running so the study captures every number "
            "with the pinned tools (no silent missing data, no version drift):\n  - "
            + "\n  - ".join(problems))
    have = ([f"PMD design panel + method rules (PMD {pmd_version(pmd)})"] if pmd else []) \
        + (["CK LCOM/TCC/CBO + DECOR Blob"] if ck else [])
    print("preflight OK: lizard parser not blind, every signal alive in all "
          f"{len(SAMPLED_LANGUAGES)} sampled languages, versions match pins, git present"
          + (f", Java panels verified [{'; '.join(have)}]" if have else "") + ".", flush=True)
    rb = ruby_parser_bounds_ok()
    print(("NOTE: Ruby is not sampled: " + EXCLUDED_LANGUAGES["ruby"] % _lizard_version()
           + (" -- STILL FAILS with this parser." if not rb else
              " -- but THIS parser bounds the fixture correctly: Ruby can be re-admitted "
              "(add it to SAMPLED_LANGUAGES, re-pin, re-sample).")), flush=True)
    if not (pmd and ck):
        missing = ([] if pmd else ["--pmd (PMD GodClass + design panel + method rules)"]) \
            + ([] if ck else ["--ck (CK LCOM/TCC/CBO + DECOR Blob)"])
        print("NOTE: running WITHOUT " + " and ".join(missing)
              + " -- the Java composite class oracle(s) (pmd_GodClass, decor_blob), the PMD "
              + "method oracles and the CK definitions will NOT be captured; the headline then "
              + "rests on brain_method, human labels (if any) and the size references. This is "
              + "explicit, not a silent hole.", flush=True)


def _warn_panel_holes(name: str, lang: str, row: dict, pmd: str | None, ck: str | None) -> None:
    """Print a LOUD per-repo warning when a Java repo was expected to carry a PMD/CK panel
    (the tool was configured) but does not -- so a silently missing oracle is seen, not buried.
    A clone/parse error row is already reported elsewhere, so it is skipped here."""
    if lang != "java" or row.get("error"):
        return
    if pmd and "pmd_gods" not in row:
        print(f"        WARNING: PMD panel MISSING on {name} "
              f"({row.get('pmd_error', 'no report')}) -- this Java row has NO PMD oracles",
              flush=True)
    if ck and "ck_def_gods" not in row:
        print(f"        WARNING: CK panel MISSING on {name} "
              f"({row.get('ck_error', 'no class table')}) -- this Java row has NO CK oracles",
              flush=True)


def measure(repo, pmd: str | None, ck: str | None, tools: dict, labels: dict | None = None) -> dict:
    """The study's row for one sampled repository, measured in its clone at `repo.path`. The
    language is the one the sampler detected, so per-language results match the sample."""
    row = repo.row
    lang = repo.language
    human, other = labels_for(labels or {}, repo.url, repo.full_name, repo.commit)
    try:
        a = analyse(repo.path, pmd if lang == "java" else None, ck if lang == "java" else None,
                    human or None)
    except Exception as e:
        a = {"error": f"{type(e).__name__}: {e}"}
    if other:
        a["labels_commit_mismatch"] = other
    return {"repo": repo.url, "name": repo.full_name.split("/")[-1], "full_name": repo.full_name,
            "lang": lang, "commit": repo.commit, "date": (row.get("commit_date") or "")[:10],
            "stratum_lang": row.get("stratum_language"), "tier": row.get("tier"),
            "stars": row.get("stars"), "rank": row.get("rank"), "star_band": row.get("star_band"),
            "sample": getattr(repo, "sample", None), "tools": tools, **a}


def freeze_halves(sample_paths, path: str) -> dict:
    """The explore/confirm half of every usable repository of the sample(s), assigned from the
    sample CSVs ALONE (stats.assign_halves, stratified by detected language and tier) before
    any repository is measured, and written to `path` (halves.json) with the samples' sha256,
    so the split exists, and is auditable, before any outcome does. A resumed run reuses the
    file and refuses a different one: the split of a run never moves."""
    from open_source_repository_sampler import read_sample, files as sfiles
    if isinstance(sample_paths, str):
        sample_paths = [sample_paths]
    items = {}
    for sp in sample_paths:
        for r in read_sample(sp):
            items.setdefault(r["url"], (r.get("language"), r.get("tier")))
    halves = stats.assign_halves(list(items.items()), stratum_of=lambda it: it[1],
                                 key_of=lambda it: it[0])
    rec = {"halves": halves,
           "samples": {os.path.basename(sp): sfiles.sha256(sp) for sp in sample_paths},
           "method": "stats.assign_halves over the usable rows of the sample CSV(s), "
                     "stratified by (language, tier), ordered by sha256 of the URL and "
                     "alternated; assigned before any repository was measured"}
    if os.path.exists(path):
        old = json.load(open(path))
        if old.get("halves") != halves:
            raise RuntimeError(f"{path} holds a different explore/confirm split from the one "
                               f"these samples give; the split of a run never moves. Use a "
                               f"fresh --out-dir.")
        return old["halves"]
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)
    n = sum(1 for h in halves.values() if h == "explore")
    print(f"explore/confirm split frozen -> {path}: {n} explore / {len(halves) - n} confirm "
          f"(stratified by language x tier, before any measurement)", flush=True)
    return halves


def _atomic_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def run(sample_paths, out_dir: str, pmd: str | None, ck: str | None = None,
        labels_path: str | None = None) -> list[dict]:
    """Measure every usable repository of one or more samples into `out_dir`: study.json (one
    row per repository, rewritten atomically after each), the append-only study.units.jsonl
    sidecar (per-unit values and god membership), oracles.json (the definition registry),
    study.csv, and the sampler's run log. A repository present in two samples (the Java
    supplement overlaps the main sample by construction) is measured once. Resumable: a re-run
    with the same out_dir skips what the run log records as done -- and refuses to resume a
    directory whose study.json is missing or unreadable while its log or sidecar says work was
    done, so no row can be silently lost."""
    from open_source_repository_sampler import for_each, read_sample

    if isinstance(sample_paths, str):
        sample_paths = [sample_paths]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "study.json")
    units_path = os.path.join(out_dir, "study.units.jsonl")
    log_path = os.path.join(out_dir, "run-log.jsonl")
    results: dict = {}
    if os.path.exists(out_path):
        try:
            results = {r["repo"]: r for r in json.load(open(out_path))}
        except Exception as e:
            raise RuntimeError(f"{out_path} exists but cannot be read ({e}); the run log would "
                               f"skip its repositories and their rows would be lost. Move the "
                               f"directory aside or delete it and start the run again.")
    elif os.path.exists(log_path) or os.path.exists(units_path):
        raise RuntimeError(f"{out_dir} holds a run log or units sidecar but no study.json: a "
                           f"resume here would skip repositories without their rows. Use a "
                           f"fresh --out-dir or clear this one.")
    preflight(pmd, ck)                  # fail loud/early: parser, signals, git, pins, PMD/CK
    tools = tool_versions(pmd, ck)      # recorded with every row (preflight guarantees pins)
    halves = freeze_halves(sample_paths, os.path.join(out_dir, "halves.json"))
    if (tools.get("harness_commit") or "").endswith("-dirty"):
        print("WARNING: the harness has UNCOMMITTED changes (harness_commit ends in -dirty). A "
              "confirmatory run must be made from a committed, tagged harness and analysis plan "
              "(README, 'Pre-registration'); this run's rows will say -dirty.", flush=True)
    labels = load_labels(labels_path)
    write_oracles(out_dir)
    n = sum(len(read_sample(p)) for p in sample_paths)
    print(f"complexity-concentration-study: {n} usable repository rows in "
          f"{', '.join(sample_paths)} | references: class WMC>=47, method CC>={CC_GOD}"
          + (", Java PMD panel + method rules" if pmd else "") + (", Java CK panel" if ck else "")
          + (f", human labels from {labels_path}" if labels_path else "") + "\n"
          f"each is shallow-cloned at its sampled commit by open-source-repository-sampler, "
          f"measured, then deleted. tools {tools}\noutput -> {out_dir}\n", flush=True)

    def experiment_for(sample_path):
        def experiment(repo):
            repo.sample = os.path.basename(sample_path)
            row = measure(repo, pmd, ck, tools, labels)
            row["half"] = halves.get(repo.url)       # frozen before any measurement
            units = row.pop("_units", None)          # keep the per-unit payload out of study.json
            results[row["repo"]] = row
            _atomic_json(out_path, list(results.values()))
            if units is not None:
                with open(units_path, "a") as fh:
                    fh.write(json.dumps({"repo": row["repo"], **units}) + "\n")
            cm = (row.get("matrix") or {}).get("class") or {}
            print(f"        {row['lang']:7} {row.get('n_funcs', '?'):>6} fns | class universe "
                  f"{cm.get('n_univ')} | wmc47 gods {cm.get('wmc47_gods')}"
                  + (f" | PMD gods {row['pmd_gods']}" if "pmd_gods" in row else "")
                  + (f" | ERROR {row['error']}" if row.get("error") else ""), flush=True)
            _warn_panel_holes(row["name"], row["lang"], row, pmd, ck)
        return experiment

    for sample_path in sample_paths:
        for_each(sample_path, experiment_for(sample_path), deep=False, run_log=log_path)
    rows = list(results.values())
    write_csv(rows, os.path.join(out_dir, "study.csv"))
    _summary(rows, pmd, ck)
    return rows


# ---------------------------------------------------------------------------
# results table and summary
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "name", "full_name", "repo", "lang", "kind", "stratum_lang", "tier", "stars", "rank",
    "sample", "half", "commit", "date", "n_files", "n_funcs", "usable", "wmc_gods", "pmd_gods",
    "brain_methods", "class_universe", "method_universe", "java_files_multi_class",
    "files_oversize", "files_generated", "files_unparsed", "trivial_frac", "lizard",
    "harness_commit",
]


def _row_to_csv(r: dict) -> dict:
    cm = (r.get("matrix") or {}).get("class") or {}
    mm = (r.get("matrix") or {}).get("method") or {}
    return {
        "name": r.get("name"), "full_name": r.get("full_name"), "repo": r.get("repo"),
        "lang": r.get("lang"),
        "kind": r.get("kind"), "stratum_lang": r.get("stratum_lang"), "tier": r.get("tier"),
        "stars": r.get("stars"), "rank": r.get("rank"), "sample": r.get("sample"),
        "half": r.get("half"), "commit": r.get("commit"), "date": r.get("date"),
        "n_files": r.get("n_files"), "n_funcs": r.get("n_funcs"),
        "usable": is_usable(r), "wmc_gods": r.get("wmc_gods"), "pmd_gods": r.get("pmd_gods"),
        "brain_methods": (mm.get("oracle_gods") or {}).get("brain_method"),
        "class_universe": cm.get("n_univ"), "method_universe": mm.get("n_univ"),
        "java_files_multi_class": r.get("java_files_multi_class"),
        "files_oversize": (r.get("files_skipped") or {}).get("oversize"),
        "files_generated": (r.get("files_skipped") or {}).get("generated"),
        "files_unparsed": (r.get("files_skipped") or {}).get("unparsed"),
        "trivial_frac": r.get("trivial_frac"),
        "lizard": (r.get("tools") or {}).get("lizard"),
        "harness_commit": (r.get("tools") or {}).get("harness_commit"),
    }


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            if not r.get("error"):
                w.writerow(_row_to_csv(r))
    print(f"\nwrote results table -> {path}")


def _summary(rows: list[dict], pmd: str | None = None, ck: str | None = None) -> None:
    ok = [r for r in rows if not r.get("error") and r.get("matrix")]
    usable = [r for r in ok if is_usable(r)]
    print("\n" + "=" * 72 + "\nMEASURED REPOSITORIES (usable = substance floor met)")
    by_lang = defaultdict(list)
    for r in ok:
        by_lang[r.get("lang", "?")].append(r)
    for lang, rs in sorted(by_lang.items()):
        u = sum(1 for r in rs if is_usable(r))
        print(f"  {lang:10} {len(rs):>3} measured  {u:>3} usable")
    n_pmd = sum(1 for r in usable if "pmd_gods" in r)
    n_ck = sum(1 for r in usable if "ck_def_gods" in r)
    n_bm = sum(1 for r in usable
               if ((r["matrix"]["method"].get("oracle_gods") or {}).get("brain_method") or 0) > 0)
    n_hum = sum(1 for r in usable if r.get("human_labels"))
    print(f"\n{len(usable)} usable repositories of {len(ok)} measured; "
          f"PMD panel on {n_pmd}, CK panel on {n_ck} (Java only); brain_method marks >= 1 unit "
          f"in {n_bm}; human labels on {n_hum}.")
    # The sampler drew every measured row as usable on the same floor; a row that fails it here
    # is a filter mismatch between the sampler and the harness and must be reported, not hidden.
    flips = [r.get("name") for r in ok if not is_usable(r)]
    if flips:
        print(f"NOTE: {len(flips)} repositories drawn as usable fail the harness floor "
              f"(sampler/harness file-filter mismatch): {flips[:15]}")
    skipped = defaultdict(int)
    for r in ok:
        for k, v in (r.get("files_skipped") or {}).items():
            skipped[k] += v
    outside = sum(v for r in ok
                  for lvl in ("class", "method")
                  for v in ((r["matrix"].get(lvl) or {}).get("god_outside_univ") or {}).values())
    print(f"Files outside the universe: {dict(skipped)}; definition positives outside the "
          f"universe (all definitions, both levels): {outside}.")
    # Loudly account for any Java row that a CONFIGURED tool failed to cover, so the holes are
    # never silent: a run full of partial Java rows is reported, not discovered later.
    java_ok = [r for r in ok if r.get("lang") == "java"]
    if pmd:
        holes = [r for r in java_ok if "pmd_gods" not in r]
        print(f"WARNING: PMD was configured but produced NO panel on {len(holes)} of "
              f"{len(java_ok)} Java repos -- those rows lack PMD oracles: "
              f"{[r.get('name') for r in holes][:15]}" if holes else
              f"PMD configured: panel present on all {len(java_ok)} Java repos.")
        um = sum(r.get("pmd_method_unmatched", 0) for r in java_ok)
        if um:
            print(f"NOTE: {um} PMD method-level findings fell outside every measured function "
                  f"(recorded per row as pmd_method_unmatched).")
    if ck:
        holes = [r for r in java_ok if "ck_def_gods" not in r]
        print(f"WARNING: CK was configured but produced NO table on {len(holes)} of "
              f"{len(java_ok)} Java repos -- those rows lack CK oracles: "
              f"{[r.get('name') for r in holes][:15]}" if holes else
              f"CK configured: panel present on all {len(java_ok)} Java repos.")
    mism = [r.get("name") for r in ok if r.get("labels_commit_mismatch")]
    if mism:
        print(f"NOTE: human labels exist at ANOTHER commit for {len(mism)} repos and were not "
              f"applied: {mism[:15]}")
    print("Analysis of the comparison matrix: see README, 'Analysing a run'.")


def write_anc(rows: list[dict], anc_dir: str, frame_files=None) -> None:
    """Write the paper's ancillary-data package: results table + README + the oracle registry,
    plus every sample file (each open-source-repository-sample*.csv and its .derivation.json) so
    the attachment shows how the population was chosen as well as what was found."""
    os.makedirs(anc_dir, exist_ok=True)
    write_csv(rows, os.path.join(anc_dir, "results.csv"))
    write_oracles(anc_dir)
    for f in (frame_files or []):
        if f and os.path.isfile(f):
            shutil.copy(f, os.path.join(anc_dir, os.path.basename(f)))
            print(f"  + sample file {os.path.basename(f)}")
    ok = [r for r in rows if not r.get("error") and r.get("matrix")]
    usable = [r for r in ok if is_usable(r)]
    langs = sorted({r.get("lang") for r in usable})
    with open(os.path.join(anc_dir, "README.txt"), "w") as fh:
        fh.write(_ANC_README.format(n_repos=len(usable), n_langs=len(langs),
                                    langs=", ".join(langs)))
    print(f"wrote ancillary-data package -> {anc_dir}/ (results.csv, oracles.json, README.txt)")


_ANC_README = """Complexity-concentration study: relative complexity outliers as god-class/method identifiers (ancillary data)
================================================================================

WHAT THIS IS
  results.csv holds one row per open-source repository. The study asks whether an
  unsupervised, SCALE-FREE relative outlier in per-unit code complexity identifies the
  classes and methods that textbook absolute-threshold definitions (and, where supplied,
  human experts) mark, at the repository's sampled commit. Each row records the exact commit
  measured and the harness commit that measured it, so any result can be reproduced.

  The full (level x complexity signal x outlier rule x god definition) matrix is in the
  study JSON; this table is a per-repository summary. oracles.json is the registry of every
  god definition scored: its source, its constant, and the complexity signals it is built
  from (its INGREDIENTS), so a signal recovering a definition it is part of is never read as
  an independent result.

  The repositories were drawn by open-source-repository-sampler: each sample is a pair of
  files, open-source-repository-sample*.csv (every candidate drawn, each pinned to a commit)
  and *.derivation.json (how it was drawn, and how to redo it). The Java supplement sample
  overlaps the main sample by construction; each repository is measured once.

THE SIGNALS (per function; class level = per-file sum / mean / max of each)
  cc (cyclomatic), cognitive (Campbell), nloc, tokens, params, nesting (max depth of nested
  control structures), cyc_density (cc/nloc), exit_points, hvol (Halstead volume,
  approximate), mi (maintainability BURDEN = 100 - MI, so higher = worse). At class level
  each is aggregated three ways ({{base}}_sum/_mean/_max) and cc_sum IS WMC; nom (methods per
  class) is class level only. A unit is flagged when its value is a relative outlier under
  one of several scale-free rules (modified z, double MAD, Tukey fence, skew-adjusted
  boxplot, GPD tail, top percentile, classic z), each fitted on the whole per-repository
  population it scores. The rules' standardised-axis constants are listed in oracles.json.

GOD DEFINITIONS (see oracles.json for provenance, constants, ingredients and ORIGIN)
  composite  = PMD GodClass (tool), approximate DECOR Blob (composed from CK values, Java);
               brain_method (INTERNAL: the study's own signals and cuts, all languages);
               PMD NPath (tool, Java, method level); human_<label> where expert labels
               were given. Headline order: tool/human, then composed, then internal.
  self       = WMC >= 47; CC >= 14, cognitive >= 15, nesting >= 5, NLOC >= 50, params >= 5
  calibration= PMD's own CyclomaticComplexity / CognitiveComplexity / NcssCount (Java,
               method level): external implementations of our lexical signals
  component  = PMD size/coupling rules; CK LCOM*, TCC, CBO (Java): single clauses, not gods

COLUMNS
  name, full_name, repo, commit, date   repository identity and the exact revision measured
  kind                             application or library (post-hoc heuristic)
  stratum_lang, tier, stars, rank  selection metadata from the sample CSV; sample = which
                                   sample file drew it
  half                             explore or confirm, assigned from the sample CSV before
                                   any repository was measured (halves.json)
  n_files, n_funcs                 source files and functions parsed (tests excluded)
  usable                           cleared the substance floor (>= {min_funcs} funcs, class
                                   universe >= {min_univ})
  wmc_gods, pmd_gods               files WMC>=47; Java files PMD calls a GodClass
  brain_methods                    functions meeting the composite Brain Method definition
  class_universe, method_universe  the common scoring universe (files WMC>0 / funcs CC>0)
  java_files_multi_class           measured Java files holding more than one class (CK), the
                                   size of the file-as-class approximation
  files_oversize, files_generated, files_unparsed
                                   source files kept OUT of the universe and why
  trivial_frac                     share of units with cyclomatic complexity 1
  lizard, harness_commit           the parser version and the harness commit that measured it

HEADLINE (this run)
  {n_repos} usable repositories, {n_langs} languages ({langs}).

REPRODUCE (from the complexity-concentration-study source)
  ./step1_setup.sh                                          tools, pinned, plus the sampler
  ./step3_run.sh --sample <each sample csv here>            re-measure this exact population
  (./step2_sample.sh draws fresh samples by the same method instead.)
""".replace("{min_funcs}", str(MIN_FUNCS)).replace("{min_univ}", str(MIN_UNIV))
