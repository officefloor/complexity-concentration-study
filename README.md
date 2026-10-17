# Complexity concentration → god classes and methods

Can an **unsupervised, relative complexity outlier** — a single-snapshot concentration
spike in a per-unit complexity definition — reproduce a **tool-defined god class/method**,
and if so, *which* complexity definition and *which* outlier rule do it best?

A standalone complexity-concentration study. The Python package is `god_complexity`; it
measures only per-unit code complexity (cyclomatic, cognitive, lines, tokens, parameters,
nesting; method count at class level) and tests how well a relative outlier in each agrees
with tool-defined god-class/method definitions (PMD, CK, DECOR, WMC and standard thresholds).

## Result (as it stands)

On the frozen run in `paper/data/2026-10-17/study.json` (619 repos measured, 385 over the
substance floor, 201 explore / 184 confirm), at **class level**, against the composite
god-class definitions (PMD `GodClass` + DECOR `Blob`):

- A relative complexity outlier is a **strong ranker** of god classes — AUC ≈ **0.94**, and
  it holds **out of sample** (best signal chosen on explore, read on the held-out confirm
  half).
- **`nom` (method count) and `cc` (cyclomatic) tie for best** (AUC ≈ 0.94), `nloc` close;
  **cognitive complexity is the weakest** separator everywhere.
- It is a **loose detector at a fixed threshold**: best operating point (`nom` + `mad_z`) is
  recall 0.64 / precision 0.33 / MCC 0.43 — good ranker, modest classifier.
- Best outlier rule: **`mad_z`** (Iglewicz–Hoaglin modified z), `iqr` a close second,
  `evt_pot` useless.
- Caveats: the composite god targets are **Java-only, N≈34 repos**; `wmc47` is ΣCC so its
  AUC≈0.99 with `cc` is tautological and reported apart.

Open gap: at **method level** every god oracle in the run is one of our own signals
thresholded (`cc14`, `cognitive15`, `loc50`, `params5`, `nesting5`), so AUC≈1.0 is a
tautology and the method-level question is **not yet evaluable**. Adding an *independent*
method oracle (PMD's own `CyclomaticComplexity` / `NPathComplexity` /
`ExcessiveMethodLength` / `CognitiveComplexity`) is the first real task here.

## Where things are

- `paper/god_complexity.py` — the complexity detector report (class & method level), the
  self-contained analysis of the matrix.
- `paper/GOD_COMPLEXITY_NOTES.md` — methodology, grouping, oracles, and caveats.
- `god_complexity/` — extraction (`extract.py`), outlier algorithms and AUC/MCC math
  (`metrics.py`), the god-oracle wiring and matrix (`study.py`: PMD/CK/DECOR), and the
  seeded sampler (`sample.py`, `grow.py`).
- `paper/data/2026-10-17/study.json` — the frozen run (the evidence; gitignored, on disk).

The reporters are **pure standard library** — read the existing run on any `python3`:

`python3 paper/god_complexity.py paper/data/2026-10-17/study.json --level class`

To **regenerate** a run you need a venv with **lizard 1.23.0** (1.24.x has a Java regression
that returns no functions for annotated classes), plus PMD 7.x and the CK jar for the Java
oracle panel. This project ships no `.venv` (virtualenvs are not path-portable); create one
with `python3 -m venv .venv && .venv/bin/pip install 'lizard==1.23.0'`.
