"""Language-agnostic Cognitive Complexity (Campbell, 2018) and maximum nesting depth.

A deliberately simple estimator computed over one function's source text. It is NOT the
certified SonarSource implementation; it is a faithful approximation whose numbers are
calibrated against PMD's CognitiveComplexity on Java fixtures in tests/test_cognitive.py, and
checked in the field by the `pmd_method_Cognitive15` calibration oracle (study.ORACLES). For a
relative concentration spike, consistency across units matters more than matching a third
party's exact value.

`analyze(source, ext)` returns (cognitive, max_nesting): the two are produced by one walk,
because nesting depth is exactly the quantity Campbell's rules increment.

Method (the parts of Campbell's rules a parser-free scan can carry faithfully):

  * +1 (plus the current NESTING level) for each control-flow structure that nests:
    ``if``/``unless``, ``for``/``foreach``, ``while``/``until``, ``do``, ``switch``/``case``/
    ``match``/``select``, ``catch``/``except``/``rescue``, ``guard``, ``loop``, ``repeat``,
    and a ternary ``a ? b : c``.
  * +1 (with NO nesting increment) for a continuation: ``else``, ``else if`` / ``elif`` /
    ``elsif`` / ``elseif``.
  * +1 for each run of like boolean operators (a run of ``&&`` is one, a run of ``||`` is
    one; switching operator starts a new run). ``and``/``or`` are the same operators.
  * NESTING increases inside every one of those blocks, inside nested ternaries, and inside a
    lambda / block body (``->`` / ``=>`` bodies, Ruby ``do ... end`` and ``{ |x| }`` blocks,
    nested Python ``def``), so control flow inside a callback is charged for its depth.
  * ``try``/``with``/``finally``/``ensure``/``begin`` neither score nor nest (Campbell).

Three scanners, picked by file extension: braces (C family: Java, C/C++, C#, Go, JS/TS, PHP,
Rust, Swift, Kotlin ...), indentation (Python), and ``end``-matched keyword blocks (Ruby).
Known approximations: a brace-less nested statement (``if (a) if (b) x;``) does not add depth;
a Ruby ``{ ... }`` is taken as a block only after ``)`` / an identifier / ``do``-less call forms.
"""
from __future__ import annotations

import re

# Languages whose nesting is indentation-based rather than brace-based.
_PY_EXTS = {"py", "pyw", "pyi"}
_RB_EXTS = {"rb", "rake", "gemspec"}

_STRIP = re.compile(
    r'"""(?:\\.|[^\\])*?"""|\'\'\'(?:\\.|[^\\])*?\'\'\''      # python triple strings
    r'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''                # normal strings/chars
    r'|`(?:\\.|[^`\\])*`'                                     # JS/TS template strings
    r'|//[^\n]*|/\*.*?\*/'                                    # C-family comments
    r'|#[^\n]*',                                              # python/shell comments
    re.S)
_STRIP_C = re.compile(                                        # no '#': C preprocessor/JS private
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*.*?\*/', re.S)
_STRIP_RB = re.compile(                                       # no '//': Ruby has no such comment
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|#[^\n]*|=begin.*?=end', re.S)


def _blank(rx: re.Pattern, source: str) -> str:
    """Blank strings and comments but keep every newline (line structure matters to Python/Ruby)."""
    return rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)


# ---------------------------------------------------------------------------
# C family (braces)
# ---------------------------------------------------------------------------
# Control-flow keywords shared across the curly-brace languages: +1 + nesting, opens a block.
_NEST_KW = {"if", "for", "foreach", "while", "switch", "catch", "match", "select", "guard",
            "loop", "repeat"}
# Order matters: the multi-char '?' forms come before the bare '?' so TS optional chaining (?.),
# nullish (??) and optional-member (?:) are tokenised out and do NOT count as ternaries. Lambda
# arrows (-> for Java, => for JS/TS/C#/PHP) are tokens too, so a lambda body adds a nesting level.
_C_TOKEN = re.compile(r"\?\?|\?\.|\?:|->|=>|&&|\|\||[?{}();:]|[A-Za-z_$][A-Za-z0-9_$]*")


class _CScan:
    """Mutable state for the C-family cognitive walk."""

    def __init__(self) -> None:
        self.score = 0
        self.nesting = 0
        self.max_nesting = 0
        self._brace: list[int] = []      # per '{': the nesting it added (0 or 1)
        self._pending = 0                # nesting to attach to the next '{'
        self._last_bool: str | None = None
        self.prev: str | None = None     # previous token (for do-while tails)
        self._arrow = False              # previous token was a lambda arrow (-> / =>)
        self.parens = 0                  # '(' depth, so a ';' inside for(...) is not a statement end
        self.ternaries = 0               # open ternaries in the current statement
        self.header_open = False         # between a control keyword and its block: a Go/Rust
                                         # `for a := 0; a < x; a++ {` has ';' in the header
        self._pending_do = False         # the next '{' opens a do-block
        self._do_blocks: list[bool] = []  # per '{': is it a do-block (its '}' is followed by `while`)
        self.while_tail = False          # the previous token closed a do-block

    def boolean(self, op: str) -> None:
        if op != self._last_bool:        # a run of like operators counts once
            self.score += 1
        self._last_bool = op

    def end_bool_run(self) -> None:
        self._last_bool = None

    def ternary(self) -> None:           # a ? b : c -- +1 + depth (+1 per enclosing ternary)
        self.score += 1 + self.nesting + self.ternaries
        self.ternaries += 1
        self.max_nesting = max(self.max_nesting, self.nesting + self.ternaries)

    def statement_end(self) -> None:     # ';' at paren depth 0
        self.end_bool_run()
        if not self.header_open:         # a brace-less `if (x) return;` opens no block ...
            self._pending = 0            # ... but a ';' inside a paren-less Go header does not end it
        self.ternaries = 0

    def open_brace(self, lambda_block: bool = False) -> None:
        add = 1 if (self._pending or lambda_block) else 0   # control block or lambda body nests
        self._brace.append(add)
        self._do_blocks.append(self._pending_do)
        self._pending_do = False
        self.nesting += add
        self.max_nesting = max(self.max_nesting, self.nesting)
        self._pending = 0
        self.header_open = False
        self.ternaries = 0

    def close_brace(self) -> None:
        if self._brace:
            self.nesting -= self._brace.pop()
            self.while_tail = self._do_blocks.pop()      # `} while (...)` of a do-block
        self.ternaries = 0

    def nest(self, do_block: bool = False) -> None:   # if/for/while/switch/catch/do: +1 + depth
        self.score += 1 + self.nesting
        self._pending = 1
        self._pending_do = do_block
        self.header_open = not do_block

    def cont(self) -> None:              # else / else-if: +1, no depth, block nests
        self.score += 1
        self._pending = 1
        self.header_open = True


def _c_walk(source: str) -> tuple[int, int]:
    """Brace-nested cognitive complexity and max nesting for the C family."""
    toks = _C_TOKEN.findall(_blank(_STRIP_C, source))
    s = _CScan()
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        arrow = s._arrow                 # did a lambda arrow immediately precede this token?
        s._arrow = False
        tail = s.while_tail              # did a do-block's '}' immediately precede this token?
        s.while_tail = False
        if t in ("&&", "||"):            # boolean run -- operands between operators don't break it
            s.boolean(t)
        elif t == "?":                   # ternary (bare '?'; ?. ?? ?: are separate tokens, ignored)
            s.end_bool_run(); s.ternary()
        elif t in ("->", "=>"):          # lambda arrow: the block it opens adds a nesting level
            s._arrow = True
        elif t == "(":
            s.parens += 1
        elif t == ")":
            s.parens = max(0, s.parens - 1)
            if s.parens == 0:
                s.header_open = False    # `if (...)` header complete: a ';' now ends a statement
        elif t == "{":
            s.end_bool_run(); s.open_brace(lambda_block=arrow)
        elif t == "}":
            s.end_bool_run(); s.close_brace()
        elif t == "do":
            s.end_bool_run(); s.nest(do_block=True)
        elif t in ("else", "elseif"):
            s.end_bool_run(); s.cont()
            if t == "else" and i + 1 < n and toks[i + 1] == "if":
                i += 1                    # consume the `if` of `else if`
        elif t in _NEST_KW and not (t == "while" and tail):      # skip the do{}while tail
            s.end_bool_run(); s.nest()
        elif t == ";" and s.parens == 0:
            s.statement_end()
        s.prev = t
        i += 1
    return max(s.score, 0), s.max_nesting


# ---------------------------------------------------------------------------
# Python (indentation)
# ---------------------------------------------------------------------------
_PY_NEST_KW = {"if", "for", "while", "except"}            # +1 + nesting, opens a nesting block
_PY_CONT_KW = {"elif", "else"}                            # +1, no increment; block nests
_PY_SCOPE_KW = {"try", "finally", "with", "async"}        # no score, block does NOT nest
_PY_DEF_KW = {"def", "class", "lambda"}                   # nested function/class: nests, no score
_PY_LEAD = re.compile(r"^(\s*)(\w+)")
_PY_BOOL = re.compile(r"\b(and|or)\b")
_PY_TERNARY = re.compile(r"\bif\b.*\belse\b")


def _py_walk(source: str) -> tuple[int, int]:
    """Indentation-nested cognitive complexity and max nesting for Python-like languages."""
    text = _blank(_STRIP, source)
    score = 0
    max_nesting = 0
    # stack of (indent_of_block_body, contributes_nesting) for open blocks
    stack: list[tuple[int, int]] = []
    seen_def = False
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        m = _PY_LEAD.match(raw)
        if not m:
            continue
        indent = len(m.group(1).expandtabs())
        kw = m.group(2)
        if kw == "async":                                 # `async for` / `async with` / `async def`
            rest = raw[m.end():].strip()
            kw = rest.split(" ", 1)[0] if rest else kw
        # pop blocks we have dedented out of
        while stack and indent < stack[-1][0]:
            stack.pop()
        nesting = sum(c for _, c in stack)
        if kw in _PY_DEF_KW:
            if seen_def:                                  # a NESTED def/class: its body nests
                stack.append((indent + 1, 1))
                max_nesting = max(max_nesting, nesting + 1)
            else:
                seen_def = True
                stack.append((indent + 1, 0))
        elif kw in _PY_NEST_KW:
            score += 1 + nesting
            stack.append((indent + 1, 1))
            max_nesting = max(max_nesting, nesting + 1)
        elif kw in _PY_CONT_KW:
            score += 1
            stack.append((indent + 1, 1))
            max_nesting = max(max_nesting, nesting + 1)
        elif kw in _PY_SCOPE_KW:
            stack.append((indent + 1, 0))
        else:
            # a conditional expression `a if c else b` on a plain line is a ternary
            if _PY_TERNARY.search(raw) and not raw.rstrip().endswith(":"):
                score += 1 + nesting
        # boolean-operator runs on the line (a run of `and` = 1, of `or` = 1)
        last = None
        for bm in _PY_BOOL.finditer(raw):
            op = bm.group(1)
            if op != last:
                score += 1
            last = op
    return max(score, 0), max_nesting


# ---------------------------------------------------------------------------
# Ruby (keyword blocks closed by `end`)
# ---------------------------------------------------------------------------
_RB_TOKEN = re.compile(r"&&|\|\||[{}();|]|\?(?=\s)|[A-Za-z_][A-Za-z0-9_]*[?!]?")
_RB_NEST = {"if", "unless", "while", "until", "for", "case"}   # +1 + nesting; block or modifier
_RB_CONT = {"elsif", "else"}                                    # +1, no increment
_RB_RESCUE = {"rescue"}                                         # like catch: +1 + nesting
_RB_SCOPE = {"def", "class", "module", "begin", "ensure", "when", "then"}
# A control keyword is the BLOCK form when it starts a statement: first token on its line, or
# preceded by one of these. Otherwise (`return s if x`, `s += 1 unless y`) it is a modifier.
_RB_STMT_START = {";", "=", "(", ",", "then", "else", "do", "{", "||", "&&", "and", "or",
                  "not", "elsif", "when", "begin", "|"}


def _rb_walk(source: str) -> tuple[int, int]:
    """`end`-matched cognitive complexity and max nesting for Ruby."""
    score = 0
    nesting = 0
    max_nesting = 0
    stack: list[int] = []                 # per open block: the nesting it added
    last_bool = None
    for line in _blank(_STRIP_RB, source).split("\n"):
        toks = _RB_TOKEN.findall(line)
        prev = None
        opened_loop = False               # a while/until/for on this line takes an optional `do`
        for i, t in enumerate(toks):
            if t in ("&&", "||", "and", "or"):
                op = "&&" if t in ("&&", "and") else "||"
                if op != last_bool:
                    score += 1
                last_bool = op
            elif t == "?":                # ternary (a bare `?` followed by whitespace)
                score += 1 + nesting
            elif t in _RB_NEST:
                last_bool = None
                score += 1 + nesting
                if prev is None or prev in _RB_STMT_START:      # block form: nests until `end`
                    stack.append(1)
                    nesting += 1
                    max_nesting = max(max_nesting, nesting)
                    opened_loop = t in ("while", "until", "for")
            elif t in _RB_CONT:
                last_bool = None
                score += 1
            elif t in _RB_RESCUE:
                last_bool = None
                score += 1 + nesting
            elif t == "do":
                last_bool = None
                if opened_loop:                               # `while cond do`: same block
                    opened_loop = False
                else:                                         # a do-block: nests like a lambda
                    stack.append(1)
                    nesting += 1
                    max_nesting = max(max_nesting, nesting)
            elif t in _RB_SCOPE:
                last_bool = None
                if t in ("def", "class", "module", "begin"):
                    stack.append(0)
            elif t == "{":
                last_bool = None
                block = prev is not None and (prev == ")" or prev[0].isalpha() or prev == "|")
                stack.append(1 if block else 0)
                if block:
                    nesting += 1
                    max_nesting = max(max_nesting, nesting)
            elif t in ("}", "end"):
                last_bool = None
                if stack:
                    nesting -= stack.pop()
            elif t == ";":
                last_bool = None
            prev = t
        last_bool = None
    return max(score, 0), max_nesting


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def analyze(source: str, ext: str = "") -> tuple[int, int]:
    """(cognitive complexity, max nesting depth) of one function's source text. `ext` is the
    file extension (no dot) used only to pick the scanner; unknown extensions use the
    brace-based C-family scanner, the right default for curly-brace languages."""
    if not source or not source.strip():
        return 0, 0
    e = ext.lower()
    if e in _PY_EXTS:
        return _py_walk(source)
    if e in _RB_EXTS:
        return _rb_walk(source)
    return _c_walk(source)


def cognitive_complexity(source: str, ext: str = "") -> int:
    """Estimate the Cognitive Complexity of one function's source text."""
    return analyze(source, ext)[0]


def max_nesting_depth(source: str, ext: str = "") -> int:
    """Maximum depth of nested control structures (and lambda/block bodies) in one function."""
    return analyze(source, ext)[1]
