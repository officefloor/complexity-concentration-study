# Complexity concentration → god classes and methods

A test harness for one question: at a single checkout, does an **unsupervised, relative
complexity outlier** — a concentration spike in a per-unit complexity definition — mark the
same classes/methods that a tool-defined god-class/method definition marks, and *which*
complexity definition and *which* outlier rule do it best?

It is **identification, not prediction**, measured on freshly sampled repositories. The
package is `complexity_concentration_study`; it measures only per-unit code complexity and compares a relative
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
`paper/METHODOLOGY.md` for the methodology and caveats.

## Where things are

- `complexity_concentration_study/` — extraction (`extract.py`), outlier algorithms and AUC/MCC math
  (`metrics.py`), and the god-oracle wiring and per-repo matrix (`study.py`: PMD/CK/DECOR).
- Sampling is not in this repository. The population is drawn, and each repository cloned at its
  pinned commit, by [open-source-repository-sampler](https://github.com/officefloor/open-source-repository-sampler)
  (pinned in `pyproject.toml`). This study only measures.
- `paper/analyse.py` — the analysis report over the matrix (class & method level), pure
  standard library.
- `paper/METHODOLOGY.md` — methodology, grouping, oracles, and caveats.

## Running it

Four numbered scripts, each printing the next. Prerequisites the scripts do **not** install:
`python3`, `git`, **Java (JRE 17+)**, and the **`gh` CLI authenticated** (`gh auth login`) for
the sampling in step 2.

    ./step1_setup.sh                                  # venv + pinned deps (incl. the sampler) + PMD/CK into ./lib
    ./step2_sample.sh                                 # draw the sample -> sample/
    ./step3_run.sh --sample sample/open-source-repository-sample.csv   # measure it -> results/<date>/
    ./step4_analyse.sh --results results/<date>       # the full report, class and method level

Each script ends by printing the exact next command, so you can follow it top to bottom.
`./step1_setup.sh` is a thin alias for the clean `./setup.sh` that also prints the next step.
`pip` pins **lizard 1.23.0** (1.24.x has a Java regression that returns no functions for
annotated classes) and the sampler's release.

**Step 2 — the sample.** `./step2_sample.sh` runs
[open-source-repository-sampler](https://github.com/officefloor/open-source-repository-sampler)
with this study's criteria, written out in the script: all 11 languages × 3 popularity tiers,
grown until each language has 30 usable repositories, the analysis's substance floor (≥ 50
functions in ≥ 15 files with a function), the author's own ecosystem excluded, seed 1. It writes
two files into `sample/`:

- `open-source-repository-sample.csv` — every candidate drawn, usable or excluded with its
  reason, each pinned to the commit that met the criteria;
- `open-source-repository-sample.derivation.json` — how the sample was drawn and how to redo it.

They are the study population, and go into the paper's ancillary data unchanged. Extra flags pass
through to the sampler (for example, `--seed 2` draws a different, independent sample).

**Skip step 2** to measure an existing sample: the one published with the paper, or another
study's, so that both studies measure exactly the same code. Pass it to step 3 with `--sample`.

**Step 3 — the measurement.** `./step3_run.sh` verifies the sample against its derivation. The
sampler's run loop then shallow-clones each usable repository at its pinned commit, the study
measures it, and the clone is deleted, so disk use stays at one repository at a time. Output
defaults to `results/<date>/` (override with `--out-dir`), and PMD/CK default to `./lib`
(override with `--lib`/`$CCS_LIB`, or exact `--pmd`/`--ck`):

    ./step3_run.sh --sample sample/open-source-repository-sample.csv --out-dir results/my-run

It measures hundreds of repositories (PMD + CK on every Java one) and is resumable: re-running
with the same `--out-dir` skips the repositories its `run-log.jsonl` records as done. Alongside the
lean `study.json` it writes an append-only `study.units.jsonl` sidecar with each repo's per-unit
values and god membership, which the conservation and no-calibration analyses use. It also writes
the ancillary package to `<out-dir>/anc/`: `results.csv`, `README.txt` and the sample's two files.

**No silent missing data, no version drift.** A single preflight runs before any clone and fails
loud on any of these: a blind lizard parser, missing `git`, or a configured PMD/CK that does not
actually run and return a non-empty panel on a synthetic god class. It also enforces the
**exact tool pins** — lizard `1.23.0`, PMD `7.27.0`, the CK `0.7.0` jar by sha256 — as a
**hard failure**, not a warning, so every run and every independent review uses identical tools and
the numbers are comparable. To use a different version deliberately, change the pin in
`complexity_concentration_study/study.py`: that makes the choice a git-auditable code change, and any difference in
the results is then traceable to it. An omitted panel is announced explicitly, never silent.

Analyse a run (any `python3`, no dependencies) — point it at a results directory, or let it pick
the latest:

    python3 paper/analyse.py --results results/<date> --level class
    python3 paper/analyse.py --level class          # uses the latest results/<date>

The report covers: the out-of-sample AUC headline (with a bootstrap CI), the signal and
outlier-rule rankings, the **conservation** check (do different complexity measures rank the same
units?) and the **no-calibration head-to-head** (the self-calibrating per-repo relative rule vs
the best single tuned global threshold). The last two appear when the `study.units.jsonl` sidecar
is in the results directory. Further scripts that build the paper's tables from a results
directory also live in `paper/` (added as the write-up is done).

## What is and isn't committed

Code, plus the sample once drawn (`sample/`, two small files, worth committing so the study
population is pinned in the repository). Both **dependencies** (`./lib`) and **results**
(`results/<date>/` — `study.json`, the `study.units.jsonl` sidecar, the CSV, the run log, the
ancillary package) are **git-ignored**:
every machine downloads the exact pinned tools itself, and results are regenerated by running the
study (a curated subset is published as the paper's ancillary data). This keeps the repository to
the harness and makes the method fully inspectable in code.
