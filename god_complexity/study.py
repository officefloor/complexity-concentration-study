"""Multi-language snapshot study: how well does a relative COMPLEXITY outlier identify
textbook god classes/methods at a repo's latest main commit?

Identification is a placement (snapshot) property, so we only need the latest commit. For
each repo we shallow-clone the default branch, record the exact commit (the source of truth
is the public repo; we keep only the sha), measure, and delete the clone to bound disk.

For every (level, complexity signal, outlier algorithm, god DEFINITION) the per-repo `matrix`
block records lean confusion counts and the threshold-free AUC/AP of the raw signal. The
analysis of that matrix lives in paper/god_complexity.py.

God DEFINITIONS (language-neutral + Java panels):
  * god CLASS  = file WMC >= 47 (Lanza-Marinescu size threshold)
  * god METHOD = CC >= 14, cognitive >= 15, nesting >= 5, nloc >= 50, params >= 5
  * Java only, with --pmd: PMD's design panel (GodClass, CouplingBetweenObjects, ...)
  * Java only, with --ck:  CK cohesion/coupling (LCOM*, TCC, CBO) + an approximate DECOR Blob

Resumable: results already in the output JSON are skipped.
"""
from __future__ import annotations

import argparse
import csv as _csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

from . import extract
from . import metrics

CC_GOD = 14
MIN_FUNCS, MIN_UNIV = 50, 15          # the study's substance floor (grow mirrors it)

DEFAULT_REPOS = [
    # java
    "https://github.com/apache/commons-lang.git",
    "https://github.com/google/gson.git",
    "https://github.com/jhy/jsoup.git",
    "https://github.com/mockito/mockito.git",
    "https://github.com/square/retrofit.git",
    # python
    "https://github.com/pallets/flask.git",
    "https://github.com/psf/requests.git",
    "https://github.com/Textualize/rich.git",
    "https://github.com/encode/httpx.git",
    "https://github.com/psf/black.git",
    # javascript / typescript
    "https://github.com/expressjs/express.git",
    "https://github.com/lodash/lodash.git",
    "https://github.com/axios/axios.git",
    "https://github.com/colinhacks/zod.git",
    "https://github.com/date-fns/date-fns.git",
    # go
    "https://github.com/gin-gonic/gin.git",
    "https://github.com/spf13/cobra.git",
    "https://github.com/sirupsen/logrus.git",
    # c / c++
    "https://github.com/nlohmann/json.git",
    "https://github.com/fmtlib/fmt.git",
    # c#
    "https://github.com/JamesNK/Newtonsoft.Json.git",
    "https://github.com/App-vNext/Polly.git",
    # ruby / php / rust
    "https://github.com/sinatra/sinatra.git",
    "https://github.com/guzzle/guzzle.git",
    "https://github.com/clap-rs/clap.git",
]


def _git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


# Extension -> language. `.h` is deliberately absent: it is ambiguous between C and C++
# and is resolved per repo in _lang (a header counts as C++ only when the tree carries a
# C++ marker, the way GitHub's Linguist resolves it). Mapping it blindly to C is what made
# header-heavy C++ projects (mlx, WindowsAppSDK) measure as C.
# Values are the canonical language keys used everywhere else (sample.LANGS, the grow
# targets): e.g. "javascript", not "js". A mismatch here silently breaks the per-language
# accounting -- grow counts usable repos by this label, so a label that no stratum uses can
# never reach its target (the .js/.ts -> js/ts bug that looped the sampler).
_EXT_LANG = {".java": "java", ".py": "python", ".js": "javascript", ".jsx": "javascript",
             ".ts": "typescript", ".tsx": "typescript",
             ".go": "go", ".c": "c", ".cc": "c++", ".cpp": "c++",
             ".cxx": "c++", ".c++": "c++", ".hpp": "c++", ".hh": "c++", ".hxx": "c++",
             ".cs": "c#", ".rb": "ruby", ".php": "php", ".rs": "rust", ".kt": "kotlin",
             ".swift": "swift", ".scala": "scala"}


def _lang(root: str) -> str:
    """Dominant language of a checkout, by source-file count aggregated into languages.

    Aggregating by language rather than by raw extension fixes two mislabels: the js/ts
    family split across .js/.jsx and .ts/.tsx, and ambiguous C/C++ headers. A `.h` is
    counted as C++ when the tree holds any unambiguous C++ file (.cpp/.cc/.hpp/...) and as
    C otherwise, so a C++ project whose headers outnumber its .cpp files no longer reads as
    C. Unknown extensions fall back to the bare suffix as their own bucket."""
    ext_counts = Counter()
    for rel in extract.source_files(root):
        ext_counts[os.path.splitext(rel)[1].lower()] += 1
    if not ext_counts:
        return "?"
    h_lang = "c++" if any(ext_counts.get(e) for e in
                          (".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx")) else "c"
    by_lang = Counter()
    for ext, n in ext_counts.items():
        lang = h_lang if ext == ".h" else _EXT_LANG.get(ext, ext.lstrip("."))
        by_lang[lang] += n
    # Tie-break deterministically by language name so re-runs are stable.
    return max(sorted(by_lang), key=by_lang.get)


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
    fd, lst = tempfile.mkstemp(prefix="godc-pmd-", suffix=".txt")
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
    outdir = tempfile.mkdtemp(prefix="godc-ck-")
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


def _matrix_block(funcs, wmc, method_oracles, class_oracles, pmd_godclass) -> dict:
    """The full detection matrix. For every (level, signal, algorithm) cell: the confusion
    counts against every applicable god DEFINITION (all keyed like the extractor: function
    ids at method level, repo-relative paths at class level). Also, for every (level, signal,
    definition): the THRESHOLD-FREE AUC/AP of the raw signal, which separates signal quality
    from the outlier algorithm's threshold. A COMMON per-level universe (funcs cc>0 / files
    wmc>0) is used for a fair head-to-head."""
    mx = metrics.matrix_outliers(funcs, wmc)

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


def analyse(root: str, pmd: str | None, ck: str | None = None) -> dict:
    res = extract.analyze_tree(root)
    funcs, wmc = res["funcs"], res["wmc"]
    if not funcs:
        return {"error": "no functions"}
    kind = classify_kind(root, funcs)
    # method-level god DEFINITIONS (textbook thresholds), so the method comparison is not
    # limited to a single oracle: McCabe CC, Campbell cognitive, deep nesting, long method,
    # long parameter list.
    method_oracles = {
        "cc14": {fid for fid, r in funcs.items() if r.get("cc", 0) >= CC_GOD},
        "cognitive15": {fid for fid, r in funcs.items() if r.get("cognitive", 0) >= 15},
        "nesting5": {fid for fid, r in funcs.items() if r.get("nesting", 0) >= 5},
        "loc50": {fid for fid, r in funcs.items() if r.get("nloc", 0) >= 50},
        "params5": {fid for fid, r in funcs.items() if r.get("params", 0) >= 5},
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

    # full (level x signal x algorithm x oracle) comparison matrix
    out["matrix"] = _matrix_block(funcs, wmc, method_oracles, class_oracles, pmd_godclass)
    return out


def is_usable(row: dict, min_funcs: int = MIN_FUNCS, min_univ: int = MIN_UNIV) -> bool:
    """Whether a measured row clears the substance floor: it parsed, has >= min_funcs
    functions and a class-level universe (files with WMC>0) of at least min_univ. Decided
    only on quantities fixed before any detection outcome, so the grow loop cannot select on
    results."""
    if row.get("error") or row.get("excluded_min_substance"):
        return False
    if (row.get("n_funcs") or 0) < min_funcs:
        return False
    nu = (((row.get("matrix") or {}).get("class") or {}).get("n_univ")) or 0
    return nu >= min_univ


_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def read_repo_pins(path: str) -> list[tuple[str, str | None]]:
    """(url, commit or None) per line of a repo-list file. A line is `URL [SHA]  # comment`;
    the commit, when present, pins the exact revision to re-measure (grow writes it), so a
    re-run measures the same code rather than whatever the default branch holds today.
    Inline comments, whole-line comments and blanks are tolerated."""
    out = []
    for ln in open(path):
        toks = ln.split("#", 1)[0].split()
        if toks:
            sha = toks[1].lower() if len(toks) > 1 and _SHA.match(toks[1].lower()) else None
            out.append((toks[0], sha))
    return out


def read_repo_list(path: str) -> list[str]:
    """Git URLs from a repo-list file (any pinned commit is dropped; see read_repo_pins)."""
    return [u for u, _ in read_repo_pins(path)]


def clone_at(url: str, dest: str, sha: str | None = None,
             timeout: float | None = None) -> str | None:
    """Shallow-clone `url` into `dest`, at commit `sha` when given (fetched by id, depth 1),
    else at the default branch's latest commit. Returns None on success, else an error."""
    shutil.rmtree(dest, ignore_errors=True)
    try:
        if not sha:
            cl = subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, dest],
                                capture_output=True, text=True, timeout=timeout)
            return None if cl.returncode == 0 else "clone failed"
        os.makedirs(dest, exist_ok=True)
        for args in (["init", "--quiet"], ["remote", "add", "origin", url],
                     ["fetch", "--depth", "1", "--quiet", "origin", sha],
                     ["checkout", "--quiet", "--detach", "FETCH_HEAD"]):
            r = subprocess.run(["git", *args], cwd=dest, capture_output=True, text=True,
                               timeout=timeout)
            if r.returncode != 0:
                return f"pinned clone failed at `git {args[0]}`"
        head = _git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
        return None if head.startswith(sha) else f"pinned clone landed on {head[:10]}"
    except subprocess.TimeoutExpired:
        return f"clone timeout ({timeout}s)"


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
        v["god_complexity"] = version("god-complexity")
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


def preflight_tools(pmd: str | None, ck: str | None) -> None:
    """Fail LOUD and EARLY if a CONFIGURED tool cannot run at all, so a study is never quietly
    measured with holes in its Java oracle panels. A tool left unset (None) is a deliberate
    choice to run without that panel and is fine. A tool that is set but unusable aborts here,
    before any repository is cloned, rather than silently dropping its oracles on every Java
    repo. (A tool that runs but is the wrong VERSION is a soft warning via tool_drift, not a
    stop -- the panel is still produced.)"""
    bad = []
    if pmd and not pmd_version(pmd):
        bad.append(f"--pmd {pmd!r}: PMD does not run here (need PMD {PMD_VERSION}). Fix the "
                   f"path, or omit --pmd to run without the Java PMD panel.")
    if ck:
        if not os.path.isfile(ck):
            bad.append(f"--ck {ck!r}: CK jar not found. Fix the path, or omit --ck.")
        elif shutil.which("java") is None:
            bad.append(f"--ck {ck!r}: no `java` on PATH to run CK. Install a JRE, or omit --ck.")
    if bad:
        raise RuntimeError("tool preflight failed (a configured tool must be runnable, so the "
                           "study is never measured with silent oracle holes):\n  - "
                           + "\n  - ".join(bad))


def _load_selection(manifest_path: str | None) -> dict:
    """url -> selection metadata {stratum_lang, tier, stars, rank} from a sampling manifest,
    so results can be grouped by how each repo was selected."""
    if not manifest_path or not os.path.isfile(manifest_path):
        return {}
    try:
        m = json.load(open(manifest_path))
    except Exception:
        return {}
    sel = {}
    for s in m.get("strata", []):
        for it in s.get("selected", []):
            sel[it["url"]] = {"stratum_lang": s.get("lang"), "tier": s.get("tier"),
                              "stars": it.get("stars"), "rank": it.get("rank")}
    return sel


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


def run(repos: list, out_path: str, pmd: str | None, keep: bool,
        manifest_path: str | None = None, ck: str | None = None) -> None:
    """Measure each repo. `repos` holds URLs or (url, commit) pins; a pinned repo is measured
    at that exact commit (and re-measured if a previous result recorded another one)."""
    results = {}
    if os.path.exists(out_path):
        try:
            results = {r["repo"]: r for r in json.load(open(out_path))}
        except Exception:
            results = {}
    check_parser()                      # fail closed on a blind Java parser
    preflight_tools(pmd, ck)            # fail closed on a configured-but-unusable PMD/CK
    selection = _load_selection(manifest_path)
    tools = tool_versions(pmd, ck)
    for d in tool_drift(tools):
        print(f"WARNING: tool drift -- {d}; results are not comparable with the pinned study",
              flush=True)
    work = tempfile.mkdtemp(prefix="godc-study-")
    pins = [(r, None) if isinstance(r, str) else tuple(r) for r in repos]
    total = len(pins)
    n_pinned = sum(1 for _, sha in pins if sha)
    print(f"god-complexity study: {total} repositories ({n_pinned} pinned to a commit) | "
          f"references: class WMC>=47, method CC>={CC_GOD}"
          + (", Java PMD panel" if pmd else "") + (", Java CK panel" if ck else "") + "\n"
          f"each repo is shallow-cloned (at its pinned commit, else the latest default branch), "
          f"measured, its commit recorded, then deleted. tools {tools}\n"
          f"output -> {out_path}\n", flush=True)
    for i, (url, pin) in enumerate(pins, 1):
        name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        prev = results.get(url)
        if prev and (not pin or (prev.get("commit") or "").startswith(pin)):
            print(f"[{i}/{total}] {name}: skip (already in {os.path.basename(out_path)})",
                  flush=True)
            continue
        print(f"[{i}/{total}] {name}: cloning {url}" + (f" @ {pin[:10]}" if pin else "")
              + " ...", flush=True)
        dest = os.path.join(work, name)
        err = clone_at(url, dest, pin)
        if err:
            print(f"CLONE FAIL {name}: {err}")
            results[url] = {"repo": url, "name": name, "error": err, "pinned": pin}
            json.dump(list(results.values()), open(out_path, "w"), indent=2)
            continue
        sha = _git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
        date = _git(["show", "-s", "--format=%ci", "HEAD"], cwd=dest).stdout.strip()[:10]
        lang = _lang(dest)
        try:
            a = analyse(dest, pmd if lang == "java" else None,
                        ck if lang == "java" else None)
        except Exception as e:
            a = {"error": f"{type(e).__name__}: {e}"}
        row = {"repo": url, "name": name, "lang": lang, "commit": sha, "date": date,
               **selection.get(url, {}), "tools": tools, **a}
        results[url] = row
        json.dump(list(results.values()), open(out_path, "w"), indent=2)
        cm = (row.get("matrix") or {}).get("class") or {}
        print(f"        {lang:7} {row.get('n_funcs','?'):>6} fns @ {sha[:10]} ({date}) | "
              f"class universe {cm.get('n_univ')} | wmc47 gods {cm.get('wmc47_gods')}"
              + (f" | PMD gods {row['pmd_gods']}" if 'pmd_gods' in row else ""),
              flush=True)
        _warn_panel_holes(name, lang, row, pmd, ck)
        if not keep:
            shutil.rmtree(dest, ignore_errors=True)
    rows = list(results.values())
    write_csv(rows, os.path.splitext(out_path)[0] + ".csv")
    _summary(rows, pmd, ck)


# ---------------------------------------------------------------------------
# results table and summary
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "name", "repo", "lang", "kind", "stratum_lang", "tier", "stars", "rank",
    "commit", "date", "n_files", "n_funcs", "usable", "wmc_gods", "pmd_gods",
    "class_universe", "method_universe", "lizard",
]


def _row_to_csv(r: dict) -> dict:
    cm = (r.get("matrix") or {}).get("class") or {}
    mm = (r.get("matrix") or {}).get("method") or {}
    return {
        "name": r.get("name"), "repo": r.get("repo"), "lang": r.get("lang"),
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
    print("Analysis of the comparison matrix: paper/god_complexity.py <study.json>.")


def write_anc(rows: list[dict], anc_dir: str, frame_files=None) -> None:
    """Write the paper's ancillary-data package: results table + README, plus the frame
    (the repo list and sampling manifest) so the attachment shows how the population was
    chosen as well as what was found."""
    os.makedirs(anc_dir, exist_ok=True)
    write_csv(rows, os.path.join(anc_dir, "results.csv"))
    for f in (frame_files or []):
        if f and os.path.isfile(f):
            shutil.copy(f, os.path.join(anc_dir, os.path.basename(f)))
            print(f"  + frame file {os.path.basename(f)}")
    ok = [r for r in rows if not r.get("error") and r.get("matrix")]
    usable = [r for r in ok if is_usable(r)]
    langs = sorted({r.get("lang") for r in usable})
    with open(os.path.join(anc_dir, "README.txt"), "w") as fh:
        fh.write(_ANC_README.format(n_repos=len(usable), n_langs=len(langs),
                                    langs=", ".join(langs)))
    print(f"wrote ancillary-data package -> {anc_dir}/ (results.csv, README.txt)")


_ANC_README = """God-complexity: complexity-outlier god-class/method identification study (ancillary data)
================================================================================

WHAT THIS IS
  results.csv holds one row per open-source repository. The study asks whether an
  unsupervised, relative COMPLEXITY outlier identifies textbook god classes and methods at
  the repository's latest default-branch commit. Each row records the exact commit measured,
  so any result can be reproduced by checking that commit out. The full (level x complexity
  signal x outlier algorithm x god definition) matrix is in the study JSON; this table is a
  per-repository summary.

THE SIGNALS (per function; class level = per-file sum)
  cc (cyclomatic), cognitive (Campbell), nloc, tokens, params, nesting; nom (methods per
  class, class level only). A unit is flagged when its value is a relative outlier under one
  of several rules (modified z, double MAD, Tukey fence, skew-adjusted boxplot, GPD tail,
  top percentile, classic z).

GOD DEFINITIONS (the tool-derived "ground truth" each signal is scored against)
  god class  = file WMC >= 47          (Lanza-Marinescu size threshold)
  god method = CC >= 14, cognitive >= 15, nesting >= 5, nloc >= 50, params >= 5
  Java only  = PMD design panel (GodClass, CouplingBetweenObjects, TooManyMethods, ...)
  Java only  = CK cohesion/coupling (LCOM*, TCC, CBO) + an approximate DECOR Blob

COLUMNS
  name, repo, lang, commit, date   repository identity and the exact revision measured
  kind                             application or library (post-hoc heuristic)
  stratum_lang, tier, stars, rank  selection metadata from the sampling manifest
  n_files, n_funcs                 source files and functions parsed (tests excluded)
  usable                           cleared the substance floor (>= {min_funcs} funcs, class
                                   universe >= {min_univ})
  wmc_gods, pmd_gods               files WMC>=47; Java files PMD calls a GodClass
  class_universe, method_universe  the common scoring universe (files WMC>0 / funcs CC>0)
  lizard                           the lizard version that parsed the repository

HEADLINE (this run)
  {n_repos} usable repositories, {n_langs} languages ({langs}).

REPRODUCE
  pip install -e .   (from the god-complexity source)
  god-complexity grow --anc <out dir>     grow a seeded, stratified sample to target
  god-complexity study --repos repos.txt  re-measure this exact population, each at its commit
  python paper/god_complexity.py <study.json> --level class    analyse the matrix
""".replace("{min_funcs}", str(MIN_FUNCS)).replace("{min_univ}", str(MIN_UNIV))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="god_complexity_study.json")
    ap.add_argument("--repos", default=None, help="file with one git URL per line")
    ap.add_argument("--pmd", default=None, help="PMD binary, for the Java design panel")
    ap.add_argument("--ck", default=None, help="CK jar, for the Java cohesion/coupling panel")
    ap.add_argument("--anc", default=None, help="write the ancillary-data package here "
                    "(results.csv + README.txt)")
    ap.add_argument("--keep", action="store_true", help="do not delete clones")
    args = ap.parse_args(argv)
    repos = DEFAULT_REPOS
    if args.repos:
        repos = read_repo_pins(args.repos)
    manifest = os.path.join(os.path.dirname(args.repos or "."), "sampling-manifest.json")
    run(repos, args.out, args.pmd, args.keep, manifest, args.ck)
    if args.anc:
        write_anc(list({r["repo"]: r for r in json.load(open(args.out))}.values()),
                  args.anc, frame_files=[args.repos, manifest])
    return 0


if __name__ == "__main__":
    sys.exit(main())
