"""Multi-language snapshot study: how well does a relative COMPLEXITY outlier identify
textbook god classes/methods at a repository's sampled commit?

Identification is a placement (snapshot) property, so one commit per repository is enough.
The repositories, and the commit of each, come from a sample drawn by
open-source-repository-sampler (`open-source-repository-sample.csv`). Its run loop
shallow-clones each usable repository at its pinned commit, hands it to `measure`, and deletes
the clone, so this module only measures.

For every (level, complexity signal, outlier algorithm, god DEFINITION) the per-repo `matrix`
block records lean confusion counts and the threshold-free AUC/AP of the raw signal. The
analysis of that matrix lives in paper/analyse.py.

God DEFINITIONS (language-neutral + Java panels):
  * god CLASS  = file WMC >= 47 (Lanza-Marinescu size threshold)
  * god METHOD = CC >= 14, cognitive >= 15, nesting >= 5, nloc >= 50, params >= 5
  * Java only, with --pmd: PMD's design panel (GodClass, CouplingBetweenObjects, ...)
  * Java only, with --ck:  CK cohesion/coupling (LCOM*, TCC, CBO) + an approximate DECOR Blob

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

CC_GOD = 14
# The study's substance floor. step2_sample.sh samples with the same floor
# (--min-functions 50, --min-files-with-functions 15), so usable repositories clear it.
MIN_FUNCS, MIN_UNIV = 50, 15


def _rel(root: str, path: str) -> str:
    """A tool-reported path as the repo-relative path the extractor keys files by."""
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")


def _pmd_violations(pmd: str, root: str, files: list[str]) -> dict | None:
    """rule name -> set of repo-relative paths that violate it, over PMD's whole Java design
    category. PMD is run on EXACTLY the Java files the extractor measured (a --file-list, so
    every module is covered and test code is excluded the same way), and results are keyed
    by path, not basename, so same-named classes in different packages do not collide.
    One PMD pass yields the full oracle panel (GodClass, CouplingBetweenObjects ~ CK's CBO,
    TooManyMethods, ExcessiveClassLength/NcssCount, TooManyFields, ...). Needs PMD 7.
    Returns None if PMD could not be run or parsed."""
    if not files:
        return {}
    fd, lst = tempfile.mkstemp(prefix="ccs-pmd-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(os.path.join(root, f) for f in files) + "\n")
        out = subprocess.run([pmd, "check", "--file-list", lst, "-R", "category/java/design.xml",
                              "--format", "json", "--no-cache", "--no-progress"],
                             capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None                     # PMD missing/crashed here: a pmd_error, never a raise
    finally:
        try:
            os.unlink(lst)
        except OSError:
            pass
    try:
        d = json.loads(out.stdout)
    except Exception:
        return None
    byrule: dict = {}
    for f in d.get("files", []):
        rel = _rel(root, f["filename"])
        for v in f.get("violations", []):
            byrule.setdefault(v.get("rule"), set()).add(rel)
    return byrule


# class-level PMD rules used as god-class oracles in the comparison matrix (class-scoped
# "largeness/coupling/cohesion" rules; method-level and stylistic design rules are ignored).
_PMD_ORACLE_RULES = ("GodClass", "CouplingBetweenObjects", "TooManyMethods",
                     "ExcessiveClassLength", "NcssCount", "TooManyFields",
                     "ExcessivePublicCount", "ExcessiveImports")


def _ck_gods(ck_jar: str, root: str, files: list[str]) -> dict | None:
    """Run CK (mauricioaniche/ck) and derive cohesion/coupling god-class DEFINITIONS, keyed by
    repo-relative path (a file is a god if ANY class in it meets the threshold) and limited
    to the files the extractor measured, so CK's view of tests matches ours. These are
    non-size definitions, independent of WMC, which PMD alone does not give directly:
      ck_LCOM    : Henderson-Sellers LCOM* >= 0.8           (low cohesion)
      ck_TCClow  : Tight Class Cohesion < 1/3, >=2 methods  (Lanza-Marinescu cohesion component)
      ck_CBOhigh : Coupling Between Objects >= 14           (high coupling)
      decor_blob : an approximation of DECOR's Blob (Moha et al.): LargeClass (NMD+NAD >= 20)
                   AND (LowCohesion lcom* >= 0.8 OR a controller class name). The ASSOC-to-
                   data-classes clause is omitted (needs cross-class analysis), so this is a
                   faithful-but-partial Blob, not the certified Ptidej detector.
    Returns None if CK did not produce a class table."""
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
        defs = {"ck_LCOM": set(), "ck_TCClow": set(), "ck_CBOhigh": set(), "decor_blob": set()}

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
                if b not in measured:
                    continue
                lcomn, tcc, cbo = num(row, "lcom*"), num(row, "tcc"), num(row, "cbo")
                nm = num(row, "totalMethodsQty") or 0
                nf = num(row, "totalFieldsQty") or 0
                name = (row.get("class") or "").split(".")[-1]
                low_coh = lcomn is not None and lcomn >= 0.8
                if low_coh:
                    defs["ck_LCOM"].add(b)
                if tcc is not None and 0 <= tcc < 1 / 3 and nm >= 2:
                    defs["ck_TCClow"].add(b)
                if cbo is not None and cbo >= 14:
                    defs["ck_CBOhigh"].add(b)
                if (nm + nf) >= 20 and (low_coh or _CONTROLLER.search(name)):
                    defs["decor_blob"].add(b)
        return defs
    except Exception:
        return None
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


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
    if any(fid[1] == "main" for fid in funcs):           # Go/Java/C/Rust entry point
        return "application"
    return "library"


def _cell(outset: set, god: set, universe: set) -> dict:
    """Lean confusion counts for one (signal, definition) pair; MCC/F1/precision/recall are
    derived downstream from these four, keeping the per-repo matrix small."""
    return {"n_univ": len(universe), "n_out": len(outset),
            "n_overlap": len(outset & god), "n_god_univ": len(universe & god)}


def _matrix_block(mx, method_oracles, class_oracles) -> dict:
    """The full detection matrix (from a pre-computed metrics.matrix_outliers result). For every
    (level, signal, algorithm) cell: the confusion counts against every applicable god DEFINITION
    (all keyed like the extractor: function ids at method level, repo-relative paths at class
    level). Also, for every (level, signal, definition): the THRESHOLD-FREE AUC/AP of the raw
    signal, which separates signal quality from the outlier algorithm's threshold. A COMMON
    per-level universe (funcs cc>0 / files wmc>0) is used for a fair head-to-head."""
    def sigs(level_dict):
        return [k for k in level_dict if k not in ("universe", "_vals")]

    def cells(level_dict, universe, oracles):
        return {signal: {algo: {name: _cell(outset, god, universe)
                                for name, god in oracles.items()}
                         for algo, outset in level_dict[signal].items()}
                for signal in sigs(level_dict)}

    def auc(level_dict, universe, oracles):
        vals = level_dict["_vals"]
        res = {}
        for signal in sigs(level_dict):
            res[signal] = {}
            for name, god in oracles.items():
                a, p, ng, _ = metrics.auc_ap(vals[signal], god, universe)
                res[signal][name] = {"auc": round(a, 4) if a is not None else None,
                                     "ap": round(p, 4) if p is not None else None, "n_god": ng}
        return res

    m, c = mx["method"], mx["class"]
    return {
        "universe_note": "common per-level universe (funcs cc>0 / files wmc>0)",
        "signals_method": sigs(m), "signals_class": sigs(c),
        "method": {
            "n_univ": len(m["universe"]),
            "oracle_gods": {name: len(s) for name, s in method_oracles.items()},
            "cells": cells(m, m["universe"], method_oracles),
            "auc": auc(m, m["universe"], method_oracles),
        },
        "class": {
            "n_univ": len(c["universe"]), "wmc47_gods": len(class_oracles["wmc47"]),
            "oracle_gods": {name: len(s) for name, s in class_oracles.items()
                            if name != "wmc47"},
            "cells": cells(c, c["universe"], class_oracles),
            "auc": auc(c, c["universe"], class_oracles),
        },
    }


def _unit_payload(mx, method_oracles, class_oracles) -> dict:
    """Per-unit raw signal values and god membership for one repo, for cross-repo analyses the
    lean matrix cannot carry (measure correlation, the relative-vs-absolute-threshold head-to-
    head, bootstrap CIs). Written to the run's append-only `*.units.jsonl` sidecar, NOT to
    study.json (which `run` rewrites after every repo). Units are the common per-level universe, in a
    fixed order; `values[signal]` aligns to `units`, and `god_idx[oracle]` lists god positions."""
    def level(level_dict, oracles):
        universe = sorted(level_dict["universe"],
                          key=lambda u: u if isinstance(u, str) else "\u0000".join(u))
        pos = {u: i for i, u in enumerate(universe)}
        signals = [k for k in level_dict if k not in ("universe", "_vals")]
        vals = level_dict["_vals"]
        values = {sig: [round(float(vals[sig].get(u, 0)), 4) for u in universe]
                  for sig in signals}
        god_idx = {name: sorted(pos[u] for u in g if u in pos)
                   for name, g in oracles.items()}
        units = [u if isinstance(u, str) else "::".join(u) for u in universe]
        return {"units": units, "signals": signals, "values": values, "god_idx": god_idx}

    return {"method": level(mx["method"], method_oracles),
            "class": level(mx["class"], class_oracles)}


def analyse(root: str, pmd: str | None, ck: str | None = None) -> dict:
    res = extract.analyze_tree(root)
    funcs, wmc = res["funcs"], res["wmc"]
    if not funcs:
        return {"error": "no functions"}
    kind = classify_kind(root, funcs)
    # method-level god DEFINITIONS. Five SINGLE-metric textbook thresholds (each IS a signal
    # thresholded, so self-referential for that signal): McCabe CC, Campbell cognitive, deep
    # nesting, long method, long parameter list. Plus one COMPOSITE, independent-of-any-single-
    # signal target -- `brain_method`, the Lanza-Marinescu Brain Method as the conjunction of
    # the long-method, high-CC and deep-nesting thresholds (a faithful-but-partial rule, omitting
    # the NOAV / accessed-variables clause we cannot resolve language-neutrally). Because it is a
    # conjunction, recovering it from any one complexity measure is a real result; nloc/cc/nesting
    # are its ingredients, the other signals are clean cross-signal tests of concentration.
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
    out = {"n_funcs": len(funcs), "n_files": len(wmc), "kind": kind, "wmc_gods": len(c_god)}

    # Java reference panels, keyed by repo-relative path over exactly the measured files.
    java_files = sorted(f for f in wmc if f.endswith(".java"))
    class_oracles: dict = {"wmc47": c_god}
    pmd_godclass = None
    if pmd:
        pmd_byrule = _pmd_violations(pmd, root, java_files)
        if pmd_byrule is None:
            out["pmd_error"] = "PMD produced no parsable report"
        else:
            class_oracles.update({"pmd_" + r: pmd_byrule.get(r, set())
                                  for r in _PMD_ORACLE_RULES})
            pmd_godclass = pmd_byrule.get("GodClass", set())
            out["pmd_gods"] = len(pmd_godclass)
    if ck:
        ck_defs = _ck_gods(ck, root, java_files)
        if ck_defs is None:
            out["ck_error"] = "CK produced no class table"
        else:
            class_oracles.update(ck_defs)
            out["ck_def_gods"] = {name: len(s) for name, s in ck_defs.items()}

    # full (level x signal x algorithm x oracle) comparison matrix, computed once and split
    # into the lean per-repo block (-> study.json) and the per-unit payload (-> units sidecar).
    mx = metrics.matrix_outliers(funcs, wmc)
    out["matrix"] = _matrix_block(mx, method_oracles, class_oracles)
    out["_units"] = _unit_payload(mx, method_oracles, class_oracles)
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


class ParserBlind(RuntimeError):
    """lizard cannot see functions it must see; the study cannot be measured with it."""


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


def tool_versions(pmd: str | None, ck: str | None) -> dict:
    """The versions of every tool that shapes a measurement, recorded with each run so a
    replication can tell a tool change from a real difference."""
    import platform
    v = {"python": platform.python_version(), "lizard": _lizard_version()}
    try:
        from importlib.metadata import version
        v["complexity_concentration_study"] = version("complexity-concentration-study")
    except Exception:
        pass
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
    """A deliberately god-like Java class (16 fields, 30 branching methods) used only to verify,
    at preflight, that PMD and CK actually run AND produce a non-empty panel here."""
    fields = "\n".join(f"    public int f{i};" for i in range(16))
    methods = "\n".join(
        f"    public int m{i}(int x) {{ if (x > {i}) {{ return f{i % 16} + x; }} "
        f"else {{ return f{i % 16} - x; }} }}" for i in range(30))
    return "public class PreflightGod {\n" + fields + "\n" + methods + "\n}\n"


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
                v = _pmd_violations(pmd, smoke, ["PreflightGod.java"])
                if v is None:
                    problems.append(f"--pmd {pmd!r}: PMD ran but produced no parsable report on "
                                    f"the smoke class -- the design panel would be silently empty.")
                elif not v:
                    problems.append(f"--pmd {pmd!r}: PMD's design ruleset flagged nothing on a "
                                    f"30-method/16-field class -- the ruleset likely did not load, "
                                    f"so the Java PMD panel would be silently empty.")
        if ck:
            if not os.path.isfile(ck):
                problems.append(f"--ck {ck!r}: CK jar not found. Fix the path, or omit --ck.")
            elif _ck_gods(ck, smoke, ["PreflightGod.java"]) is None:
                problems.append(f"--ck {ck!r}: CK produced no class table on the smoke class -- "
                                f"the CK cohesion/coupling panel would be silently empty.")
    finally:
        shutil.rmtree(smoke, ignore_errors=True)
    return problems


def preflight(pmd: str | None, ck: str | None) -> None:
    """Fail LOUD and EARLY, before any repository is cloned, if ANYTHING needed to capture the
    full set of numbers is missing, broken, or off the pins: the lizard parser (not blind), git,
    the gh CLI authenticated (when sampling), and -- when configured -- PMD and CK actually
    RUNNING on a synthetic Java class and returning a non-empty panel. A tool left unset is a
    deliberate choice to skip its panel; that is reported explicitly so an omission is never
    mistaken for a silent hole.

    Tool VERSIONS are enforced EXACTLY against the pins (lizard, PMD, CK sha256): a mismatch is a
    HARD failure, not a warning, so every run and every independent review uses identical tools
    and the numbers are comparable. To use a different version deliberately, change the pin in
    this file -- a git-auditable code change -- so any resulting difference is traceable."""
    check_parser()                                   # lizard not blind (raises ParserBlind)
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
    have = ([f"PMD design panel (PMD {pmd_version(pmd)})"] if pmd else []) \
        + (["CK LCOM/TCC/CBO + DECOR Blob"] if ck else [])
    print("preflight OK: lizard parser not blind, versions match pins, git present"
          + (f", Java panels verified [{'; '.join(have)}]" if have else "") + ".", flush=True)
    if not (pmd and ck):
        missing = ([] if pmd else ["--pmd (PMD GodClass + design panel)"]) \
            + ([] if ck else ["--ck (CK LCOM/TCC/CBO + DECOR Blob)"])
        print("NOTE: running WITHOUT " + " and ".join(missing)
              + " -- the Java composite class oracle(s) (pmd_GodClass, decor_blob) and the CK "
              + "definitions will NOT be captured; the headline then rests on brain_method and "
              + "the size references. This is explicit, not a silent hole.", flush=True)


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


def measure(repo, pmd: str | None, ck: str | None, tools: dict) -> dict:
    """The study's row for one sampled repository, measured in its clone at `repo.path`. The
    language is the one the sampler detected, so per-language results match the sample."""
    row = repo.row
    lang = repo.language
    try:
        a = analyse(repo.path, pmd if lang == "java" else None, ck if lang == "java" else None)
    except Exception as e:
        a = {"error": f"{type(e).__name__}: {e}"}
    return {"repo": repo.url, "name": repo.full_name.split("/")[-1], "full_name": repo.full_name,
            "lang": lang, "commit": repo.commit, "date": (row.get("commit_date") or "")[:10],
            "stratum_lang": row.get("stratum_language"), "tier": row.get("tier"),
            "stars": row.get("stars"), "rank": row.get("rank"), "star_band": row.get("star_band"),
            "tools": tools, **a}


def run(sample_path: str, out_dir: str, pmd: str | None, ck: str | None = None) -> list[dict]:
    """Measure every usable repository of the sample into `out_dir`: study.json (one row per
    repository, rewritten after each), the append-only study.units.jsonl sidecar (per-unit
    values and god membership), study.csv, and the sampler's run log. Resumable."""
    from open_source_repository_sampler import for_each, read_sample

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "study.json")
    units_path = os.path.join(out_dir, "study.units.jsonl")
    results = {}
    if os.path.exists(out_path):
        try:
            results = {r["repo"]: r for r in json.load(open(out_path))}
        except Exception:
            results = {}
    preflight(pmd, ck)                  # fail loud/early: parser, git, exact tool pins, PMD/CK
    tools = tool_versions(pmd, ck)      # recorded with every row (preflight guarantees pins)
    n = len(read_sample(sample_path))
    print(f"complexity-concentration-study: {n} usable repositories in {sample_path} | "
          f"references: class WMC>=47, method CC>={CC_GOD}"
          + (", Java PMD panel" if pmd else "") + (", Java CK panel" if ck else "") + "\n"
          f"each is shallow-cloned at its sampled commit by open-source-repository-sampler, "
          f"measured, then deleted. tools {tools}\noutput -> {out_dir}\n", flush=True)

    def experiment(repo):
        row = measure(repo, pmd, ck, tools)
        units = row.pop("_units", None)          # keep the per-unit payload out of study.json
        results[row["repo"]] = row
        json.dump(list(results.values()), open(out_path, "w"), indent=2)
        if units is not None:
            with open(units_path, "a") as fh:
                fh.write(json.dumps({"repo": row["repo"], **units}) + "\n")
        cm = (row.get("matrix") or {}).get("class") or {}
        print(f"        {row['lang']:7} {row.get('n_funcs', '?'):>6} fns | class universe "
              f"{cm.get('n_univ')} | wmc47 gods {cm.get('wmc47_gods')}"
              + (f" | PMD gods {row['pmd_gods']}" if "pmd_gods" in row else "")
              + (f" | ERROR {row['error']}" if row.get("error") else ""), flush=True)
        _warn_panel_holes(row["name"], row["lang"], row, pmd, ck)

    for_each(sample_path, experiment, deep=False,
             run_log=os.path.join(out_dir, "run-log.jsonl"))
    rows = list(results.values())
    write_csv(rows, os.path.join(out_dir, "study.csv"))
    _summary(rows, pmd, ck)
    return rows


# ---------------------------------------------------------------------------
# results table and summary
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "name", "full_name", "repo", "lang", "kind", "stratum_lang", "tier", "stars", "rank",
    "commit", "date", "n_files", "n_funcs", "usable", "wmc_gods", "pmd_gods",
    "class_universe", "method_universe", "lizard",
]


def _row_to_csv(r: dict) -> dict:
    cm = (r.get("matrix") or {}).get("class") or {}
    mm = (r.get("matrix") or {}).get("method") or {}
    return {
        "name": r.get("name"), "full_name": r.get("full_name"), "repo": r.get("repo"),
        "lang": r.get("lang"),
        "kind": r.get("kind"), "stratum_lang": r.get("stratum_lang"), "tier": r.get("tier"),
        "stars": r.get("stars"), "rank": r.get("rank"),
        "commit": r.get("commit"), "date": r.get("date"),
        "n_files": r.get("n_files"), "n_funcs": r.get("n_funcs"),
        "usable": is_usable(r), "wmc_gods": r.get("wmc_gods"), "pmd_gods": r.get("pmd_gods"),
        "class_universe": cm.get("n_univ"), "method_universe": mm.get("n_univ"),
        "lizard": (r.get("tools") or {}).get("lizard"),
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
    print(f"\n{len(usable)} usable repositories of {len(ok)} measured; "
          f"PMD panel on {n_pmd}, CK panel on {n_ck} (Java only).")
    # Loudly account for any Java row that a CONFIGURED tool failed to cover, so the holes are
    # never silent: a run full of partial Java rows is reported, not discovered later.
    java_ok = [r for r in ok if r.get("lang") == "java"]
    if pmd:
        holes = [r for r in java_ok if "pmd_gods" not in r]
        print(f"WARNING: PMD was configured but produced NO panel on {len(holes)} of "
              f"{len(java_ok)} Java repos -- those rows lack PMD oracles: "
              f"{[r.get('name') for r in holes][:15]}" if holes else
              f"PMD configured: panel present on all {len(java_ok)} Java repos.")
    if ck:
        holes = [r for r in java_ok if "ck_def_gods" not in r]
        print(f"WARNING: CK was configured but produced NO table on {len(holes)} of "
              f"{len(java_ok)} Java repos -- those rows lack CK oracles: "
              f"{[r.get('name') for r in holes][:15]}" if holes else
              f"CK configured: panel present on all {len(java_ok)} Java repos.")
    print("Analysis of the comparison matrix: paper/analyse.py <study.json>.")


def write_anc(rows: list[dict], anc_dir: str, frame_files=None) -> None:
    """Write the paper's ancillary-data package: results table + README, plus the sample's two
    files (open-source-repository-sample.csv and its .derivation.json) so the attachment shows
    how the population was chosen as well as what was found."""
    os.makedirs(anc_dir, exist_ok=True)
    write_csv(rows, os.path.join(anc_dir, "results.csv"))
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
    print(f"wrote ancillary-data package -> {anc_dir}/ (results.csv, README.txt)")


_ANC_README = """Complexity-concentration study: complexity-outlier god-class/method identification study (ancillary data)
================================================================================

WHAT THIS IS
  results.csv holds one row per open-source repository. The study asks whether an
  unsupervised, relative COMPLEXITY outlier identifies textbook god classes and methods at
  the repository's sampled commit. Each row records the exact commit measured, so any result
  can be reproduced by checking that commit out.

  The full (level x complexity signal x outlier algorithm x god definition) matrix is in the
  study JSON; this table is a per-repository summary.

  The repositories were drawn by open-source-repository-sampler: the sample is the two files
  open-source-repository-sample.csv (every candidate drawn, each pinned to a commit) and
  open-source-repository-sample.derivation.json (how it was drawn, and how to redo it).

THE SIGNALS (per function; class level = per-file sum / mean / max of each)
  cc (cyclomatic), cognitive (Campbell), nloc, tokens, params, nesting, cyc_density (cc/nloc),
  exit_points, hvol (Halstead volume, approximate), mi (maintainability BURDEN = 100 - MI, so
  higher = worse). At class level each is aggregated three ways ({{base}}_sum/_mean/_max) and
  cc_sum = WMC; nom (methods per class) is class level only. A unit is flagged when its value
  is a relative outlier under one of several rules (modified z, double MAD, Tukey fence,
  skew-adjusted boxplot, GPD tail, top percentile, classic z).

GOD DEFINITIONS (the tool-derived "ground truth" each signal is scored against)
  god class  = file WMC >= 47          (Lanza-Marinescu size threshold)
  god method = CC >= 14, cognitive >= 15, nesting >= 5, nloc >= 50, params >= 5 (single-metric,
               self-referential) and brain_method = long AND complex AND deeply nested (the
               composite Lanza-Marinescu Brain Method, minus the NOAV clause)
  Java only  = PMD design panel (GodClass, CouplingBetweenObjects, TooManyMethods, ...)
  Java only  = CK cohesion/coupling (LCOM*, TCC, CBO) + an approximate DECOR Blob

COLUMNS
  name, repo, lang, commit, date   repository identity and the exact revision measured
  kind                             application or library (post-hoc heuristic)
  full_name                        owner/name on GitHub
  stratum_lang, tier, stars, rank  selection metadata from the sample CSV
  n_files, n_funcs                 source files and functions parsed (tests excluded)
  usable                           cleared the substance floor (>= {min_funcs} funcs, class
                                   universe >= {min_univ})
  wmc_gods, pmd_gods               files WMC>=47; Java files PMD calls a GodClass
  class_universe, method_universe  the common scoring universe (files WMC>0 / funcs CC>0)
  lizard                           the lizard version that parsed the repository

HEADLINE (this run)
  {n_repos} usable repositories, {n_langs} languages ({langs}).

REPRODUCE (from the complexity-concentration-study source)
  ./step1_setup.sh                                          tools, pinned, plus the sampler
  ./step3_run.sh --sample open-source-repository-sample.csv   re-measure this exact population
  ./step4_analyse.sh --results results/<date>               analyse the matrix
  (./step2_sample.sh draws a fresh sample by the same method instead.)
""".replace("{min_funcs}", str(MIN_FUNCS)).replace("{min_univ}", str(MIN_UNIV))

