"""Language-independent extraction of per-unit COMPLEXITY from a source tree.

Built on lizard (multi-language function list, cyclomatic complexity and line ranges), the
same substrate impact-gate uses, so it works on any language lizard parses without a
per-language analyser. Everything above lizard is lexical and language-neutral.

For each function we capture several complexity definitions, so the god-class/method
comparison can spike each one (all language-neutral: five straight from lizard, cognitive
from the vendored Campbell estimator):

    cc        cyclomatic complexity (McCabe)
    cognitive Campbell cognitive complexity (vendored estimator)
    nloc      non-comment lines of code
    tokens    token count
    params    parameter count
    nesting   maximum nesting depth

Class-level values are the per-file sums of these; WMC per FILE (sum of function cyclomatic
complexity) is the textbook size reference (Lanza-Marinescu god-class threshold is WMC >= 47).
A file is the language-neutral unit. Test files (by directory and by each language's
colocated-test naming, plus Rust #[cfg(test)] modules) are excluded unless include_tests.
"""
from __future__ import annotations

import os
import re

import lizard

from . import cognitive as _cognitive

# Per-function complexity definitions. Class-level values are the per-file sums of these.
COMPLEXITY_FIELDS = ("cc", "cognitive", "nloc", "tokens", "params", "nesting")

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
_TEST_DIR = re.compile(r"(?:^|/)(?:test|tests|testing|spec|specs|__tests__|testdata"
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
# Directories that are not the project's own code: dependencies, build output, and
# vendored or generated trees (where a single tree-sitter parser.c can be ~100 MB).
_SKIP_DIRS = {".git", "node_modules", "build", "target", "dist", ".venv", "venv",
              "vendor", "vendored", "third_party", "thirdparty", "third-party",
              "generated", "externals", "external", "deps", ".gradle", "out"}
# A source file larger than this is a generated/minified/vendored blob, not a unit anyone
# maintains by hand (real source is rarely over a few hundred KB). Skipping it keeps the
# measure meaningful AND keeps the lexical scan from stalling on a 100 MB generated file.
MAX_FILE_BYTES = 1_000_000


def source_files(root: str, include_tests: bool = False) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in SOURCE_EXTS:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            relp = "/" + rel.replace(os.sep, "/")
            if not include_tests and (_TEST_DIR.search(relp) or _TEST_FILE.search(relp)):
                continue
            try:
                if os.path.getsize(os.path.join(dirpath, fn)) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            out.append(rel)
    return out


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


def analyze_tree(root: str, include_tests: bool = False) -> dict:
    """Per-function complexity records plus per-file WMC for one checkout.

    Returns {"funcs": {func_id: {...}}, "wmc": {file: total_cc}}, where func_id is
    (file, short_name) and each record has file, name and the complexity definitions in
    COMPLEXITY_FIELDS (cc, cognitive, nloc, tokens, params, nesting) so the matrix can spike
    each one. Overloads of the same (file, name) are merged by taking the max of each field."""
    raw: list = []                      # (file, short, metrics_dict)
    for rel in source_files(root, include_tests):
        path = os.path.join(root, rel)
        try:
            analysis = lizard.analyze_file(path)
        except Exception:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src_lines = fh.read().splitlines()
        except OSError:
            continue
        ext = os.path.splitext(rel)[1].lstrip(".")
        skip = (_rust_test_lines("\n".join(src_lines))
                if ext == "rs" and not include_tests else [])
        for fn in analysis.function_list:
            s, e = int(fn.start_line), int(fn.end_line)
            if any(a <= s <= b for a, b in skip):
                continue
            body_raw = "\n".join(src_lines[max(s - 1, 0):e])
            md = {"cc": int(fn.cyclomatic_complexity),
                  "nloc": int(getattr(fn, "nloc", 0) or 0),
                  "tokens": int(getattr(fn, "token_count", 0) or 0),
                  "params": int(getattr(fn, "parameter_count", 0) or 0),
                  "nesting": int(getattr(fn, "max_nesting_depth", 0) or 0),
                  "cognitive": _cognitive.cognitive_complexity(body_raw, ext)}
            raw.append((rel, _short(fn.name), md))
    if not raw:
        return {"funcs": {}, "wmc": {}}

    agg: dict = {}                      # fid -> complexity metrics, merged by max over overloads
    for rel, short, md in raw:
        fid = (rel, short)
        cur = agg.get(fid)
        if cur is None:
            agg[fid] = dict(md)
        else:
            for k, v in md.items():
                if v > cur.get(k, 0):
                    cur[k] = v

    wmc: dict = {}                      # per-file WMC (sum of method cyclomatic complexity)
    for rel, short, md in raw:
        wmc[rel] = wmc.get(rel, 0) + md["cc"]

    funcs: dict = {}
    for fid, md in agg.items():
        funcs[fid] = {"file": fid[0], "name": fid[1],
                      **{k: md.get(k, 0) for k in COMPLEXITY_FIELDS}}
    return {"funcs": funcs, "wmc": wmc}


def modified_z(values: list[float]):
    """Iglewicz-Hoaglin modified z-score function over the positive `values`."""
    xs = sorted(v for v in values if v > 0)
    n = len(xs)
    if n == 0:
        return lambda x: 0.0
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    dev = sorted(abs(x - med) for x in xs)
    mad = dev[n // 2] if n % 2 else (dev[n // 2 - 1] + dev[n // 2]) / 2
    if mad > 0:
        return lambda x: 0.6745 * (x - med) / mad
    mad2 = sum(abs(x - med) for x in xs) / n
    return (lambda x: (x - med) / (1.2533 * mad2)) if mad2 > 0 else (lambda x: 0.0)


OUTLIER_Z = 3.5
WMC_GOD = 47
