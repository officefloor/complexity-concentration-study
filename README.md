# Complexity concentration → god classes and methods

A test harness for one question: at a single checkout, does an **unsupervised, relative
complexity outlier** — a concentration spike in a per-unit complexity definition — mark the
same classes/methods that a tool-defined god-class/method definition marks, and *which*
complexity definition and *which* outlier rule do it best?

It is **identification, not prediction**, measured on freshly sampled repositories. The
package is `god_complexity`; it measures only per-unit code complexity and compares a relative
outlier in it against textbook god definitions.

## What this is looking to achieve

A god class is **complexity concentrated** — one unit holding what should be spread across
many. Every textbook detector marks that concentration with an **absolute threshold**:
`WMC ≥ 47`, `CC ≥ 14`, `cognitive ≥ 15`, `LOC ≥ 50`. Those constants are proxies for *a human's*
comprehension budget — the point past which a person can no longer hold the unit in their head.

That budget is no longer fixed. As AI agents read, write and maintain code, the effective
"developer" gets steadily more capable, and every one of those constants drifts out of
calibration: a method that overwhelmed a 2015 human is routine for a 2025 agent, so a fixed
`CC ≥ 14` increasingly flags units that are not problems, and will keep being wrong in a moving
way. Keeping absolute-threshold metrics honest means **re-deriving every constant each time the
reader's capability changes** — a treadmill with no end.

This harness tests a detector that steps off that treadmill. A **relative complexity outlier**
carries **no absolute constant**: it asks only whether a unit is *unusually concentrated
relative to its own codebase*. That question means the same thing whether the reader is a 1970s
human or a 2030 agent — the detector **self-calibrates to each codebase** and needs no settings,
no benchmark corpus, and no re-tuning, ever. Point it at a repository and it names the
concentration with no assistance.

The hypothesis under test:

> An unsupervised, **threshold-free** relative outlier in *any* reasonable complexity measure
> identifies the same god classes a tuned, absolute-threshold tool marks — because, under
> **conservation of complexity**, a god is defined by the *concentration*, not by the absolute
> level, so the act of finding the outlier matters more than which measure is used.

That is why the harness varies the complexity measure and the outlier rule as widely as it does
(below): if the result holds across measures, the finding is about concentration itself, and the
reader is free to pick whichever measure they like — the paper reports which ones, and which
outlier rules, do it best.

## What the harness varies

- **signal** — each per-unit complexity definition: `cc` (cyclomatic), `cognitive`, `nloc`,
  `tokens`, `params`, `nesting`, `cyc_density` (cc/nloc), `exit_points`, `hvol` (Halstead
  volume, approximate) and `mi` (maintainability *burden*, `100 − MI`, so higher is worse).
  At **class level** each is aggregated three ways — `{base}_sum`, `_mean`, `_max` — so the
  matrix shows which complexity measure *and* which aggregation concentrates onto god classes;
  `cc_sum` is WMC, and `nom` (methods per class) is a class-level-only count.
- **algorithm** — the relative outlier rule that turns a signal into a flagged set: `mad_z`,
  `double_mad`, `iqr`, `adj_boxplot`, `evt_pot`, `pct_top1`, `zscore`.
- **definition (oracle)** — at class level `WMC≥47`, the PMD design panel, the CK
  cohesion/coupling definitions and an approximate DECOR Blob (Java only); at method level the
  single-metric thresholds `CC≥14`, `cognitive≥15`, `nesting≥5`, `nloc≥50`, `params≥5` and the
  composite, language-neutral `brain_method` (long ∧ complex ∧ deeply nested — a
  faithful-but-partial Lanza–Marinescu Brain Method).

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

Draw a sample and measure it. Needs the `gh` CLI (authenticated); **PMD 7.27.0** and the CK jar
add the Java PMD/CK/DECOR oracle panels (omit them to run with the WMC/threshold/`brain_method`
oracles only). The seed fixes the draw — a different seed draws a different, independent sample:

    .venv/bin/python -m god_complexity.cli grow --seed 1 \
      -O  paper/data/run/study.json \
      -m  paper/data/run/sampling-manifest.json \
      -o  paper/data/run/repos.txt \
      --anc paper/data/run/anc/ \
      --pmd /path/to/pmd-bin-7.27.0/bin/pmd --ck /path/to/ck.jar

It clones hundreds of repositories (PMD + CK on every Java one) and is resumable — re-running
the same command skips repositories already recorded. Alongside the lean `study.json` it writes
an append-only `study.units.jsonl` sidecar with each repo's per-unit values and god membership —
the substrate for the conservation and no-calibration analyses.

**No silent missing data, no version drift.** A single preflight runs before any clone and
fails loud on: a blind lizard parser, missing `git`, an unauthenticated `gh`, or a configured
PMD/CK that does not actually run and return a non-empty panel on a synthetic god class. It also
enforces the **exact tool pins** — lizard `1.23.0`, PMD `7.27.0`, the CK `0.7.0` jar by sha256 —
as a **hard failure**, not a warning, so every run and every independent review uses identical
tools and the numbers are comparable. To use a different version deliberately, change the pin in
`god_complexity/study.py`: that makes the choice a git-auditable code change, and any difference
in the results is then traceable to it. An omitted panel is announced explicitly, never silent.

Analyse the matrix (any `python3`, no dependencies):

    python3 paper/god_complexity.py paper/data/run/study.json --level class

The report covers: the out-of-sample AUC headline (with a bootstrap CI), the signal and
outlier-rule rankings, the **conservation** check (do different complexity measures rank the
same units?) and the **no-calibration head-to-head** (the self-calibrating per-repo relative
rule vs the best single tuned global threshold). The last two appear when the `.units.jsonl`
sidecar is beside the study file; it is found automatically, or pass `--units`.

## Results stay off GitHub

Everything a run produces — `study.json`, the `study.units.jsonl` sidecar, the CSV, the sample,
the ancillary package — is written under `paper/data/` and is **git-ignored**. Results are never
committed; a curated subset is published as the paper's ancillary data. This keeps the
repository to the harness.
