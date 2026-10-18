"""Language-independent extraction of per-unit COMPLEXITY from a source tree.

Built on lizard (multi-language function list, cyclomatic complexity and line ranges), so it
works on any language lizard parses without a per-language
analyser. Everything above lizard is lexical and language-neutral.

For each function we capture several complexity definitions, so the god-class/method
comparison can spike each one (all language-neutral: five straight from lizard, the rest from
vendored parser-free estimators). Every one is oriented so HIGHER == more god-like:

    cc          cyclomatic complexity (McCabe)
    cognitive   Campbell cognitive complexity (vendored estimator)
    nloc        non-comment lines of code
    tokens      token count
    params      parameter count
    nesting     maximum depth of nested control structures (same walk as cognitive)
    cyc_density cyclomatic density, cc / nloc (branching per line)        [derived: cc, nloc]
    exit_points return / throw / raise / panic statements (control exits)
    hvol        Halstead volume (vendored approximate estimator)
    mi          maintainability BURDEN = 100 - Maintainability Index, so higher == less
                maintainable, consistent with the other signals          [derived: hvol, cc, nloc]

SIGNAL_INPUTS records which signals are arithmetic functions of which others, so an oracle
built from `cc` or `nloc` can mark `cyc_density` and `mi` as ingredients too.

Class-level values are the per-file sum / mean / max of these (metrics.CLASS_SIGNALS); WMC per
FILE (sum of function cyclomatic complexity) IS `cc_sum` -- both are computed from the same
per-function records, so they agree exactly. The textbook god-class size threshold is WMC >= 47.

A FILE is the language-neutral class-level unit (see the README: this holds roughly for Java,
one public top-level class per file, and only loosely elsewhere; the Java CK pass counts the
classes per file so the approximation is quantified, not assumed).

Each function is its own unit, keyed by (file, "name@start_line"): overloads and same-named
functions in different classes of one file are NOT merged. Test files (by directory and by each
language's colocated-test naming, plus Rust #[cfg(test)] modules) are excluded unless
include_tests.
"""
from __future__ import annotations

import math
import os
import re

import lizard

from . import cognitive as _cognitive
from . import halstead as _halstead

# Per-function complexity definitions, each oriented so higher == more god-like. Class-level
# values are the per-file sum / mean / max of these (see metrics.CLASS_SIGNALS).
COMPLEXITY_FIELDS = ("cc", "cognitive", "nloc", "tokens", "params", "nesting",
                     "cyc_density", "exit_points", "hvol", "mi")

# Signals that are arithmetic functions of other signals. An oracle whose definition uses `cc`
# therefore also has `cyc_density` and `mi` as (derived) ingredients. Used by study.ingredients.
SIGNAL_INPUTS = {"cyc_density": {"cc", "nloc"}, "mi": {"hvol", "cc", "nloc"}}

# Nesting is NOT taken from lizard: plain `lizard.analyze_file` carries no nesting metric (its
# `max_nesting_depth` attribute is never populated -- a dead column in an earlier draft) and its
# NS extension mis-counts indentation languages (depths of 100+ on Python). The cognitive walk
# tracks exactly the depth Campbell's rules increment, so nesting comes from the same walk.
# study.check_signals verifies at preflight that every signal, nesting included, is alive in
# every sampled language.

# Control-exit statements, counted language-neutrally for the `exit_points` signal. Approximate
# across languages (implicit returns are not seen); read as a relative spike, not an exact count.
_EXIT_KW = re.compile(r"\b(?:return|throw|raise|panic)\b")


def maintainability_burden(hvol: float, cc: int, nloc: int) -> float:
    """100 - normalised Maintainability Index, so higher == LESS maintainable (consistent with
    the other complexity signals). MI = A - B*ln(HV) - C*CC - D*ln(LOC), normalised to [0,100]
    by the SEI/Visual-Studio convention (clamp(MI*100/A, 0, 100)). Degenerate (empty) bodies
    with hvol<=0 have no burden. Applied per FUNCTION (the classic formula is per module), which
    is internally consistent across units and is all a relative spike needs."""
    if hvol <= 0 or nloc <= 0:
        return 0.0
    raw = (_halstead.MI_A - _halstead.MI_B * math.log(hvol)
           - _halstead.MI_C * cc - _halstead.MI_D * math.log(nloc))
    mi_norm = max(0.0, min(100.0, raw * 100.0 / _halstead.MI_A))
    return round(100.0 - mi_norm, 2)

# Extensions lizard can parse that we scan. A superset; lizard skips what it cannot handle.
SOURCE_EXTS = {
    ".java", ".kt", ".scala", ".groovy",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".m", ".mm",
    ".cs", ".js", ".jsx", ".ts", ".tsx", ".py", ".go", ".rb", ".php",
    ".swift", ".rs", ".lua",
}
# Lightweight comment/string strip (used by the Rust inline-test detector). Per language,
# because a token that opens a comment in one language is code in another: `//` is floor
# division in Python, `#` is a private field in JS and an attribute in Rust, and `'a` is a
# Rust lifetime, not the start of a character literal.
_DQ = r'"(?:\\.|[^"\\])*"'
_SQ = r"'(?:\\.|[^'\\])*'"
_CHAR = r"'(?:\\.|[^'\\])'|'\\[^'\n]{1,10}'"       # a single char literal only
_BTICK = r'`(?:\\.|[^`\\])*`'
_TRIPLE = r'"""(?:\\.|[^\\])*?"""|' + r"'''(?:\\.|[^\\])*?'''"
_SLASH = r'//[^\n]*|/\*.*?\*/'
_HASH = r'#[^\n]*'
_PREPROC = r'(?m:^[ \t]*#[^\n]*)'
_STRIP_PARTS = {
    "py": (_TRIPLE, _DQ, _SQ, _HASH),
    "rb": (_DQ, _SQ, _BTICK, _HASH),
    "php": (_DQ, _SQ, _SLASH, _HASH),
    "rs": (_DQ, _CHAR, _SLASH),
    "swift": (_TRIPLE, _DQ, _SLASH),
    "lua": (_DQ, _SQ, r'--[^\n]*'),
    "c": (_DQ, _SQ, _SLASH, _PREPROC),
    "js": (_DQ, _SQ, _BTICK, _SLASH),
    "": (_TRIPLE, _DQ, _SQ, _SLASH),               # Java, Kotlin, Scala, Groovy, ...
}
_STRIP_EXT = {"pyw": "py", "pyi": "py", "jsx": "js", "ts": "js", "tsx": "js", "go": "js",
              "h": "c", "hh": "c", "hpp": "c", "cc": "c", "cpp": "c", "cxx": "c", "m": "c",
              "mm": "c", "cs": "c"}
_STRIP_BY = {k: re.compile("|".join(v), re.S) for k, v in _STRIP_PARTS.items()}


def _strip(text: str, ext: str) -> str:
    """Blank strings and comments, keeping every newline so line positions are kept."""
    ext = ext.lower()
    rx = _STRIP_BY.get(_STRIP_EXT.get(ext, ext), _STRIP_BY[""])
    return rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
# The same directory names as open-source-repository-sampler (`javatests` included), so the
# floor the sample was drawn on and the one the harness re-applies see the same files.
_TEST_DIR = re.compile(r"(?:^|/)(?:test|tests|testing|spec|specs|__tests__|testdata|javatests"
                       r"|[^/]+\.(?:tests?|unittests|integrationtests|specs))(?:/|$)", re.I)
# Test files that live BESIDE the code they test, by each language's naming convention
# (Go *_test.go, JS/TS *.test.* / *.spec.*, pytest test_*.py / *_test.py, RSpec *_spec.rb,
# gtest *_test.cc / *_unittest.cc, Rust tests.rs). A directory filter alone misses them.
_TEST_FILE = re.compile(
    r"(?:_test\.go"
    r"|[.-](?:test|spec)\.(?:js|jsx|ts|tsx)"
    r"|(?:^|/)(?:test_[^/]*|[^/]*_test|conftest|tests)\.py"
    r"|(?:^|/)(?:test_[^/]*|[^/]*_(?:test|spec))\.rb"
    r"|_(?:unit)?test\.(?:c|cc|cpp|cxx)"
    r"|(?:^|/)tests\.rs)$", re.I)
# A Rust inline test module: `#[cfg(test)]` followed by `mod name {`.
_RUST_CFG_TEST = re.compile(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]\s*(?:pub(?:\([^)]*\))?\s+)?"
                            r"mod\s+\w+\s*\{")
# Directories that are not the project's own code. Mirrors open-source-repository-sampler
# exactly, so the substance floor the sample was drawn on and the one the harness re-applies
# see the same files: vendored trees are skipped anywhere; build output and environments are
# skipped at the repository ROOT only (deeper, `org/springframework/aop/target` and
# `com/example/build` are ordinary package names).
_VENDOR_DIRS = {".git", "node_modules", "vendor", "vendored", "third_party", "thirdparty",
                "third-party", "bower_components"}
_BUILD_DIRS = {"build", "target", "dist", "out", ".venv", "venv", ".gradle", "generated",
               "externals", "external", "deps"}
# Generated or minified files by the common naming conventions (after Linguist's; the sampler's
# list). Generated parsers, protobuf output and bundles are classic RELATIVE outliers that no
# one calls a god class, so they are excluded from the universe and counted (scan_files).
_GENERATED_FILE = re.compile(
    r"(?:[.-]min\.(?:js|css)|\.bundle\.js|\.pb\.(?:go|cc|h|rs|swift)|_pb2(?:_grpc)?\.py"
    r"|\.pb(?:objc)?\.(?:m|h)|\.g\.(?:cs|dart)|\.designer\.cs|_generated\.go|\.gen\.go"
    r"|\.generated\.[a-z]+|\.d\.ts|\.tab\.[ch]|\.yy\.[ch])$", re.I)
# A source file larger than this is a generated/minified/vendored blob, not a unit anyone
# maintains by hand (real source is rarely over a few hundred KB). Skipping it keeps the
# measure meaningful AND keeps the lexical scan from stalling on a 100 MB generated file. Such
# files are COUNTED (scan_files), and the Java ones are still handed to PMD so a god class in
# one is recorded as a positive outside the universe rather than vanishing.
MAX_FILE_BYTES = 1_000_000


def scan_files(root: str, include_tests: bool = False) -> dict:
    """The project's own source files, split into what is measured and what is skipped:
    {"source": [...], "oversize": [...], "generated": [...]} (repo-relative paths). Tests,
    vendored trees and root build directories are not listed at all; generated and oversize
    files are listed so the analysis can say how many units left the universe and why."""
    out = {"source": [], "oversize": [], "generated": []}
    for dirpath, dirnames, filenames in os.walk(root):
        skip = _VENDOR_DIRS | (_BUILD_DIRS if dirpath == root else set())
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() not in SOURCE_EXTS:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            relp = "/" + rel
            if not include_tests and (_TEST_DIR.search(relp) or _TEST_FILE.search(relp)):
                continue
            if _GENERATED_FILE.search(fn):
                out["generated"].append(rel)
                continue
            try:
                if os.path.getsize(os.path.join(dirpath, fn)) > MAX_FILE_BYTES:
                    out["oversize"].append(rel)
                    continue
            except OSError:
                continue
            out["source"].append(rel)
    return out


def source_files(root: str, include_tests: bool = False) -> list[str]:
    return scan_files(root, include_tests)["source"]


def _rust_test_lines(src: str) -> list[tuple[int, int]]:
    """1-based inclusive line ranges of the `#[cfg(test)] mod name { ... }` blocks in a Rust
    source, so the inline unit tests Rust keeps beside the code are excluded like test files."""
    text = _strip(src, "rs")
    out = []
    for m in _RUST_CFG_TEST.finditer(src):
        if text[m.end() - 1] != "{":         # the match began inside a string or comment
            continue
        depth, p = 0, m.end() - 1
        while p < len(text):
            if text[p] == "{":
                depth += 1
            elif text[p] == "}":
                depth -= 1
                if depth == 0:
                    break
            p += 1
        out.append((src.count("\n", 0, m.start()) + 1, src.count("\n", 0, p) + 1))
    return out


def _short(name: str) -> str:
    return name.split("::")[-1].split(".")[-1]


_PHP_VAR = re.compile(r"\$[A-Za-z_]\w*")


def _php_param_count(body: str) -> int:
    """Parameters of a PHP function from its signature: `$name` tokens at depth 1 of the first
    balanced parenthesis pair. lizard 1.23's PHP reader reports parameter_count == 1 for ANY
    non-empty parameter list (it keeps only the last), which would make `params` a dead column
    for PHP; study.check_signals would refuse to run on it."""
    i = body.find("(")
    if i < 0:
        return 0
    depth = 0
    out = 0
    j = i
    while j < len(body):
        ch = body[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        elif ch == "$" and depth == 1:
            m = _PHP_VAR.match(body, j)
            if m:
                out += 1
                j = m.end()
                continue
        j += 1
    return out


def function_id(rel: str, short: str, start_line: int) -> tuple:
    """The unit key of one function: (repo-relative file, "name@start_line"). Overloads and
    same-named functions in one file stay distinct units."""
    return (rel, f"{short}@{start_line}")


def analyze_tree(root: str, include_tests: bool = False) -> dict:
    """Per-function complexity records plus per-file WMC for one checkout.

    Returns {"funcs": {func_id: {...}}, "wmc": {file: total_cc}, "skipped": {...}}, where
    func_id is function_id(file, short_name, start_line) and each record has file, name,
    start_line, end_line and the complexity definitions in COMPLEXITY_FIELDS so the matrix can
    spike each one. `wmc[file]` is the sum of `cc` over that file's records, so it equals the
    class-level `cc_sum` signal exactly. `skipped` lists the source files that are NOT in the
    universe and why: "oversize", "generated" (scan_files) and "unparsed" (lizard raised on
    them), so positives lost to the parser are counted, never silent."""
    funcs: dict = {}
    wmc: dict = {}
    scan = scan_files(root, include_tests)
    unparsed: list = []
    for rel in scan["source"]:
        path = os.path.join(root, rel)
        try:
            analysis = lizard.analyze_file(path)
        except Exception:
            unparsed.append(rel)
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src_lines = fh.read().splitlines()
        except OSError:
            unparsed.append(rel)
            continue
        ext = os.path.splitext(rel)[1].lstrip(".")
        skip = (_rust_test_lines("\n".join(src_lines))
                if ext == "rs" and not include_tests else [])
        for fn in analysis.function_list:
            s, e = int(fn.start_line), int(fn.end_line)
            if any(a <= s <= b for a, b in skip):
                continue
            body_raw = "\n".join(src_lines[max(s - 1, 0):e])
            cc = int(fn.cyclomatic_complexity)
            nloc = int(getattr(fn, "nloc", 0) or 0)
            hvol = _halstead.halstead_volume(body_raw, ext)
            cog, nesting = _cognitive.analyze(body_raw, ext)
            md = {"cc": cc,
                  "nloc": nloc,
                  "tokens": int(getattr(fn, "token_count", 0) or 0),
                  "params": (_php_param_count(body_raw) if ext == "php"
                             else int(getattr(fn, "parameter_count", 0) or 0)),
                  "nesting": nesting,
                  "cognitive": cog,
                  "cyc_density": round(cc / nloc, 4) if nloc > 0 else 0.0,
                  "exit_points": len(_EXIT_KW.findall(_strip(body_raw, ext))),
                  "hvol": hvol,
                  "mi": maintainability_burden(hvol, cc, nloc)}
            fid = function_id(rel, _short(fn.name), s)
            while fid in funcs:                  # two functions reported on one line (rare)
                fid = (rel, fid[1] + "'")
            funcs[fid] = {"file": rel, "name": _short(fn.name), "start_line": s, "end_line": e,
                          **{k: md[k] for k in COMPLEXITY_FIELDS}}
            wmc[rel] = wmc.get(rel, 0) + cc
    return {"funcs": funcs, "wmc": wmc,
            "skipped": {"oversize": scan["oversize"], "generated": scan["generated"],
                        "unparsed": unparsed}}


def modified_z_scale(values: list[float]):
    """Iglewicz-Hoaglin modified z-score over `values` (all of them, zeros included: the fit
    population is the scoring universe), returned with the SCALE it used: ("mad", fn) when the
    MAD is positive; ("mean_ad", fn), the mean absolute deviation with its normal consistency
    constant, when the MAD is zero (more than half the values tie at the median, as on
    zero-heavy signals); ("constant", fn -> 0) when every value ties. The scale kind is recorded
    per repository and signal, because a standardised constant only transfers between
    populations whose standardised axis means the same thing."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return "constant", (lambda x: 0.0)
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    dev = sorted(abs(x - med) for x in xs)
    mad = dev[n // 2] if n % 2 else (dev[n // 2 - 1] + dev[n // 2]) / 2
    if mad > 0:
        return "mad", (lambda x: 0.6745 * (x - med) / mad)
    mad2 = sum(abs(x - med) for x in xs) / n
    if mad2 > 0:
        return "mean_ad", (lambda x: (x - med) / (1.2533 * mad2))
    return "constant", (lambda x: 0.0)


def modified_z(values: list[float]):
    """The modified z-score function alone (see modified_z_scale)."""
    return modified_z_scale(values)[1]


# The relative rules' constants live on a STANDARDISED (scale-free) axis: 3.5 is the
# Iglewicz-Hoaglin recommendation for the modified z. It is a constant -- the rules are
# scale-free, not constant-free -- and the analysis must tune/compare it with the same
# discipline as any absolute cutoff (see README, "What 'relative' does and does not mean").
OUTLIER_Z = 3.5
WMC_GOD = 47
