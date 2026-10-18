"""Language-agnostic Halstead volume (Halstead, 1977), approximate.

Computed over one function's source text by a parser-free lexer, the same substrate the
cognitive estimator uses. It is NOT a certified per-language Halstead implementation: it
classifies tokens into OPERATORS (symbolic operators, separators and a small universal set
of control keywords) and OPERANDS (identifiers, numbers, string/char literals) with one set
of rules for every language. For a relative concentration spike, consistency across units
matters more than matching a language-specific tool's exact operator table.

From the four Halstead counts

    n1 = distinct operators   N1 = total operators
    n2 = distinct operands    N2 = total operands

the vocabulary is n = n1 + n2, the length N = N1 + N2 and the VOLUME is

    V = N * log2(n)                       (bits; 0 for an empty/degenerate body)

Volume is the only Halstead measure taken here; it feeds the signal `hvol` directly and the
Maintainability Index in extract. Difficulty/effort are deliberately left out (they add
per-language operator-table sensitivity for signals that correlate with what V already
carries).
"""
from __future__ import annotations

import math
import re

# Strings/chars first (each literal is ONE operand), then comments (dropped), then numbers,
# identifiers and operator symbols. Multi-char operators precede single so `==`/`&&`/`->`
# tokenise whole. The set is the C-family union and is applied to every language; this is the
# approximation the module docstring flags.
_TOK = re.compile(
    r'"""(?:\\.|[^\\])*?"""|\'\'\'(?:\\.|[^\\])*?\'\'\''        # python triple strings
    r'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'  # strings / template / char
    r'|(?P<cmt>//[^\n]*|/\*.*?\*/|\#[^\n]*)'                    # comments (operator group 0)
    r'|(?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?)'                     # numbers (operand)
    r'|(?P<id>[A-Za-z_$][A-Za-z0-9_$]*)'                        # identifiers / keywords
    r'|(?P<op><<=|>>=|\*\*=|\.\.\.|<=>|->|=>|::|\?\?|\?\.|&&|\|\||==|!=|<=|>=|<<|>>'
    r'|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\*\*|\.\.'
    r'|[-+*/%=<>!&|^~?:.,;()\[\]{}@])',                         # operator symbols
    re.S)

# Alphabetic tokens that are OPERATORS, not operands -- a small, universal control set. Kept
# deliberately small: only words that act as operators in essentially every curly/scripting
# language, so the classification does not drift per language.
_KW_OPERATORS = {
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "goto", "try", "catch", "finally",
    "throw", "throws", "new", "delete", "in", "and", "or", "not",
}


def halstead_volume(source: str, ext: str = "") -> float:
    """Approximate Halstead volume of one function's source text. `ext` is accepted for a
    uniform signature with the other estimators; the lexer is language-neutral so it is unused.
    Returns 0.0 for an empty or single-token body (log2(1) = 0)."""
    if not source or not source.strip():
        return 0.0
    operators: dict[str, int] = {}
    operands: dict[str, int] = {}
    for m in _TOK.finditer(source):
        if m.lastgroup == "cmt":
            continue
        if m.lastgroup == "num":
            operands[m.group()] = operands.get(m.group(), 0) + 1
        elif m.lastgroup == "id":
            tok = m.group()
            bucket = operators if tok in _KW_OPERATORS else operands
            bucket[tok] = bucket.get(tok, 0) + 1
        elif m.lastgroup == "op":
            operators[m.group()] = operators.get(m.group(), 0) + 1
        else:                                   # a string / char literal: one operand
            lit = m.group()
            operands[lit] = operands.get(lit, 0) + 1
    n1, n2 = len(operators), len(operands)
    big_n = sum(operators.values()) + sum(operands.values())
    vocab = n1 + n2
    if vocab < 2 or big_n == 0:
        return 0.0
    return round(big_n * math.log2(vocab), 2)


# Maintainability Index constants (classic three-metric form; see extract.maintainability_burden).
MI_A, MI_B, MI_C, MI_D = 171.0, 5.2, 0.23, 16.2
