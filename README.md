# Complexity concentration → god classes and methods

A test harness for one question: at a single checkout, does an **unsupervised, relative
complexity outlier** — a concentration spike in a per-unit complexity definition — mark the
same classes/methods that a tool-defined god-class/method definition marks, and *which*
complexity definition and *which* outlier rule do it best?

It is **identification, not prediction**, measured on freshly sampled repositories. The
package is `god_complexity`; it measures only per-unit code complexity and compares a relative
outlier in it against textbook god definitions.

## What the harness varies

- **signal** — each per-unit complexity definition: `cc` (cyclomatic), `cognitive`, `nloc`,
  `tokens`, `params`, `nesting`; plus `nom` (methods per class) at class level. A class-level
  signal is the per-file sum of its per-method values.
- **algorithm** — the relative outlier rule that turns a signal into a flagged set: `mad_z`,
  `double_mad`, `iqr`, `adj_boxplot`, `evt_pot`, `pct_top1`, `zscore`.
- **definition (oracle)** — `WMC≥47`, the PMD design panel, the CK cohesion/coupling
  definitions and an approximate DECOR Blob (Java only); at method level `CC≥14`,
  `cognitive≥15`, `nesting≥5`, `nloc≥50`, `params≥5`.

Signal quality is scored threshold-free by **AUC**; algorithm quality by **MCC**; repositories
are split into explore/confirm so the headline is out of sample. See
`paper/GOD_COMPLEXITY_NOTES.md` for the methodology and caveats.

## Where things are

- `god_complexity/` — extraction (`extract.py`), outlier algorithms and AUC/MCC math
  (`metrics.py`), the god-oracle wiring and per-repo matrix (`study.py`: PMD/CK/DECOR), and the
  seeded sampler (`sample.py`, `grow.py`).
- `paper/god_complexity.py` — the analysis report over the matrix (class & method level), pure
  standard library.
- `paper/GOD_COMPLEXITY_NOTES.md` — methodology, grouping, oracles, and caveats.

## Running it

Set up the environment (needs **lizard 1.23.0** — 1.24.x has a Java regression that returns no
functions for annotated classes; the package pins it and the harness fails closed if the parser
is blind):

    python3 -m venv .venv && .venv/bin/pip install -e .     # installs lizard==1.23.0

Draw a sample and measure it. Needs the `gh` CLI; PMD 7.x and the CK jar add the Java
PMD/CK/DECOR oracle panels (omit them to run with the WMC/threshold oracles only). The seed
fixes the draw — a different seed draws a different, independent sample:

    .venv/bin/python -m god_complexity.cli grow --seed 1 \
      -O  paper/data/run/study.json \
      -m  paper/data/run/sampling-manifest.json \
      -o  paper/data/run/repos.txt \
      --anc paper/data/run/anc/ \
      --pmd /path/to/pmd --ck /path/to/ck.jar

It clones hundreds of repositories (PMD + CK on every Java one) and is resumable — re-running
the same command skips repositories already recorded. A configured PMD or CK that cannot run
aborts at preflight before any clone, and any repository a configured tool fails on is flagged
per-repo and in the summary, so a run never carries silent oracle holes.

Analyse the matrix (any `python3`, no dependencies):

    python3 paper/god_complexity.py paper/data/run/study.json --level class

## Results stay off GitHub

Everything a run produces — `study.json`, the CSV, the sample, the ancillary package — is
written under `paper/data/` and is **git-ignored**. Results are never committed; a curated
subset is published as the paper's ancillary data. This keeps the repository to the harness.
