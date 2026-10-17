# Complexity concentration → god classes and methods

Can an **unsupervised, relative complexity outlier** — a single-snapshot concentration
spike in a per-unit complexity definition — reproduce a **tool-defined god class/method**,
and if so, *which* complexity definition and *which* outlier rule do it best?

A standalone complexity-concentration study. The Python package is `god_complexity`; it
measures only per-unit code complexity (cyclomatic, cognitive, lines, tokens, parameters,
nesting; method count at class level) and tests how well a relative outlier in each agrees
with tool-defined god-class/method definitions (PMD, CK, DECOR, WMC and standard thresholds).

This repository ships **no run data** — it starts a fresh, independently sampled study each
time (see *Running the study*). Nothing is pre-selected; the sampler picks the repositories.

## The hypothesis (to be tested by this experiment)

Earlier exploratory work on a *separate* sample (not included here) suggested that a relative
complexity outlier is a **strong ranker** of tool-defined god classes — roughly AUC ≈ 0.94 at
class level against PMD `GodClass` + DECOR `Blob`, holding out of sample — with **method count
(`nom`) and cyclomatic complexity (`cc`) tied best**, cognitive complexity the weakest, and the
**modified-z** rule (`mad_z`) the best outlier detector but a *loose* classifier at a fixed
threshold. This study re-tests that from scratch on a freshly drawn sample.

**Open gap to resolve.** At method level the only god oracles are our own signals thresholded
(`cc14`, `cognitive15`, `loc50`, `params5`, `nesting5`), so AUC ≈ 1.0 is tautological — the
method-level question needs an *independent* oracle (e.g. PMD's `CyclomaticComplexity`,
`NPathComplexity`, `ExcessiveMethodLength`, `CognitiveComplexity`).

## Where things are

- `god_complexity/` — extraction (`extract.py`), outlier algorithms and AUC/MCC math
  (`metrics.py`), the god-oracle wiring and per-repo matrix (`study.py`: PMD/CK/DECOR), and
  the seeded sampler (`sample.py`, `grow.py`).
- `paper/god_complexity.py` — the complexity detector report (class & method level): the
  self-contained analysis of the matrix. Pure standard library.
- `paper/GOD_COMPLEXITY_NOTES.md` — methodology, grouping, oracles, and caveats.

## Running the study

Set up the environment (needs **lizard 1.23.0** — 1.24.x has a Java regression that returns no
functions for annotated classes; the package pins it, and the study fails closed if the parser
is blind):

    python3 -m venv .venv && .venv/bin/pip install -e .     # installs lizard==1.23.0

Draw a fresh sample and measure it. Needs the `gh` CLI; PMD 7.x and the CK jar add the Java
PMD/CK/DECOR oracle panels (omit them to run with the WMC/threshold oracles only). Pick a seed
to fix the draw — a different seed draws a different, independent sample:

    .venv/bin/python -m god_complexity.cli grow --seed 1 \
      -O  paper/data/run/study.json \
      -m  paper/data/run/sampling-manifest.json \
      -o  paper/data/run/repos.txt \
      --anc paper/data/run/anc/ \
      --pmd /path/to/pmd --ck /path/to/ck.jar

It clones hundreds of repositories (PMD + CK on every Java one), runs for hours, and is
resumable — re-running the same command skips repositories already recorded. A configured PMD
or CK that cannot run aborts at preflight before any clone, and any repository a configured tool
fails on is flagged per-repo and in the summary, so the run never has silent oracle holes.

Then analyse the matrix (any `python3`, no dependencies):

    python3 paper/god_complexity.py paper/data/run/study.json --level class

Run outputs live under `paper/data/` and are **git-ignored** — regenerate them, or publish a
curated subset as the paper's ancillary data; they are never committed.
