# Complexity concentration → god classes and methods

A measurement harness for one question: at a single checkout, does an **unsupervised,
scale-free relative outlier** in a per-unit complexity measure mark the same classes and methods
that textbook, absolute-threshold god-class/method definitions (and, where supplied, human
experts) mark, and *which* complexity measure and *which* outlier rule do it best?

It is **identification, not prediction**, measured on freshly sampled repositories. The package
`complexity_concentration_study` measures per-unit code complexity, applies relative outlier
rules, and scores the flagged sets against a registry of god definitions. The analysis of a run
is the paper's job; this README states the rules that analysis must follow (below, *Analysing a
run*), and the harness ships the statistics it must use.

## The claim under test

A god class is **complexity concentrated** into one unit. Every textbook detector marks that
concentration with an **absolute threshold** on a raw scale: `WMC ≥ 47`, `CC ≥ 14`,
`cognitive ≥ 15`, `LOC ≥ 50`. Those constants are not arbitrary: Lanza and Marinescu's are
frozen percentiles of a 45-project corpus, DECOR's cohesion cut is box-plot derived, and the
benchmark-derived thresholds (Alves et al. 2010; Oliveira, Valente and Lima 2014) replace
expert opinion with a corpus percentile. Each still ships a raw-scale constant that has to be
re-fitted whenever the population moves.

A **relative outlier rule** standardises each unit by its own codebase's distribution (median
and MAD, quartiles, a fitted tail) and applies its constant on that standardised axis. The
question is therefore **a per-repository percentile against a corpus percentile**, and the
testable claim is:

> A scale-free relative outlier in a reasonable per-unit complexity measure recovers the
> classes and methods that tuned, absolute-threshold definitions mark, without a raw-scale
> constant and without a benchmark corpus; and it does so in measures that are not size, so
> the finding is about the *concentration* rather than about one metric.

It is falsifiable three ways, and the harness records what each needs. Read the limits with
each:

1. **Ranking quality.** The AUC of the raw signal against each headline definition within a
   repository, read out of sample (an explore/confirm split). AUC needs no cut. But a
   within-repository AUC is invariant to any monotone per-repository transform, so it is the
   same under the relative and the absolute view: it tests the *signal's* ranking, and says
   nothing about scale-freeness.
2. **Across measures.** Every signal belongs to a pre-assigned **family** (`oracles.json`,
   `families`): at class level *size* (every per-file sum, and `nom`), *peak* (every per-file
   max) and *density* (every per-file mean); at method level *size* (`nloc`, `tokens`, `hvol`),
   *structure* (`cc`, `cognitive`, `nesting`, `exit_points`) and *density* (`cyc_density`,
   `mi`, `params`). Every size signal is statistically collinear with a size clause whatever
   the ingredient list says, so a size signal recovering a definition whose first clause is a
   size threshold is "size recovers size". The cross-measure claim must hold in a family that
   is not size, and the matrix records each signal's AUC **within the units that already pass
   the definition's size clause** (`auc_given`): whether the signal carries anything beyond
   size.
3. **Relative versus tuned absolute.** The threshold-free form: the AUC of the units of all
   repositories pooled, once on the raw value (one absolute ranking) and once on the
   per-repository modified z (the relative ranking), `stats.pooled_auc`. The operating-point
   form: a per-repository relative rule at its **literature-default** constant against the
   single best raw-scale cutoff tuned on the explore half, both read on confirm. Every tool
   definition is itself an absolute threshold, so this comparison is tilted toward the absolute
   competitor: a relative win is strong evidence, a relative loss is weak evidence against
   relative rules in general. Expert labels (`--labels`) are the only definitions with no
   tool constant, which makes the human-label sub-study central to this claim, not optional.
   They are not scale-free either: MLCQ's reviewers graded code samples without the rest of
   the repository in view, so a human label is an absolute judgement by a reader's own budget
   rather than by a tool's constant.

   Per-repository standardisation discards exactly the information an absolute definition
   uses. In a repository of uniformly small classes the relative rule must still flag
   something and PMD marks nothing; in one of uniformly huge classes PMD marks many and the
   relative rule flags few. Agreement is therefore bounded by how homogeneous repositories
   are, and a relative loss cannot by itself separate "the rule is wrong" from "the constant
   does not fit this repository". The results report this bound (the false positives in
   god-free repositories) rather than arguing it away.

### What "relative" does and does not mean

The rules are **scale-free, not constant-free**. The modified z-score flags `z ≥ 3.5`
(Iglewicz and Hoaglin), Tukey's fence uses `k = 1.5`, the top-percentile rule takes 1%, the
classic z-score `k = 3`. Those constants live on a standardised axis, so they transfer across
codebases and languages without re-fitting, which is the property under test. They are still
constants: every run records them in `oracles.json`, and the head-to-head in point 3 reads the
relative rule at those defaults first (the real-world use) and only then with its cut tuned on
explore with the same discipline as the absolute one.

Scale-free is also not **shape-free**. The modified z depends on the zero share of the signal,
and when more than half of a population ties at the median the MAD is zero and the rule falls
back to the mean absolute deviation. Every row therefore records, per level and signal, which
scale the modified z used and the share of zeros (`matrix.<level>.diag`), and the flagged
fraction is in every cell (`n_out / n_univ`). A rule whose flag rate swings widely across
repositories is not transferring its constant, whatever its accuracy.

### What this does not test

The motivation for a scale-free rule is that any raw-scale constant is a proxy for a reader's
comprehension budget, and that budget may move, for instance as AI agents read and maintain
more code. Nothing in this design measures readers, agents or comprehension. The study only
tests whether the scale-free rule recovers what the tuned definitions mark; agreement with a
definition cannot show that the definition's constant is drifting. That argument belongs in a
paper's discussion, hedged, not in its results.

Nor does it test **portability across languages**. Ten languages are sampled and every signal
and rule is computed in all of them, but every external god definition (PMD, CK, MLCQ) is a
Java tool or a Java data set, so the primary is a Java, class-level result. The only
cross-language definition is `brain_method`, which is the study's own signals thresholded:
a result on it is internal consistency. The other nine languages supply the flag-rate and
scale-kind diagnostics (does the rule's constant transfer?), the internal-consistency
secondary, and the per-language breakdowns; they do not supply recovery of an external
definition, and the paper may not present them as if they did.

## What the harness varies

- **signal**, a per-unit complexity definition, each oriented so higher means more god-like:
  `cc` (cyclomatic), `cognitive` (Campbell, a calibrated lexical estimator), `nloc`, `tokens`,
  `params`, `nesting` (maximum depth of nested control structures), `cyc_density` (`cc/nloc`),
  `exit_points`, `hvol` (Halstead volume, approximate) and `mi` (maintainability *burden*,
  `100 − MI`). `cyc_density` and `mi` are arithmetic functions of `cc`, `nloc` and `hvol`; the
  registry treats them as derived. At **class level** each is aggregated per file three ways,
  `{base}_sum`, `_mean`, `_max`; `cc_sum` *is* WMC (computed from the same records, so the two
  agree exactly) and `nom` (methods per class) is a class-level count.
- **algorithm**, the relative outlier rule: `mad_z`, `double_mad`, `iqr`, `adj_boxplot`,
  `evt_pot`, `pct_top1` and the parametric control `zscore`. Every rule is fitted on exactly the
  population it scores, the whole per-level universe with zeros included, never on a
  positive-only subset. The GPD rule's default `p = 1/n` is a deliberately strict floor and
  must be tuned on explore data before being read as representative of extreme-value methods.
- **definition (oracle)**, declared once in `study.ORACLES` and written to every run as
  `oracles.json`. Each entry carries its level, source, constant, scope, a **kind**, an
  **origin**, and its **ingredients**: the signals its own definition is built from, closed
  over derived signals and, at class level, every aggregation. A composite with a size clause
  names that clause as a registered component (`conditional_on`) for the conditional AUC.

| kind | meaning | examples |
|---|---|---|
| composite | a multi-clause textbook definition; may carry a headline | `pmd_GodClass` (ingredient `cc_*`, conditional on `wmc47`), `decor_blob` (ingredient `nom`, conditional on `ck_LargeClass`), `brain_method` (ingredients `nloc`, `cc`, `nesting`, `mi`, `cyc_density`) |
| tool | a tool measure none of our signals computes; may carry a headline | `pmd_method_NPath200` |
| human | expert labels supplied with `--labels`; may carry a headline | `human_blob` |
| self | one signal restated as a threshold; AUC ≈ 1 for that signal is a tautology | `wmc47`, `cc14`, `cognitive15`, `nesting5`, `loc50`, `params5` |
| calibration | PMD's own implementation of one of our signals; its value on every method is recorded, so the estimator is calibrated continuously | `pmd_method_CC10`, `pmd_method_Cognitive15`, `pmd_method_Ncss60` |
| component | one clause of a definition, not a god definition on its own; reported with its prevalence | PMD size and coupling rules, `ck_LCOM`, `ck_TCClow`, `ck_CBOhigh`, `ck_LargeClass` |

| origin | who computed the label | headline order |
|---|---|---|
| tool | an external tool's own rule (PMD, CK) | first |
| human | expert labels; the only origin with no built-in scale | first |
| composed | the study's composition of tool-computed values (`decor_blob`: CK counts with this study's 0.8 cut) | second |
| internal | the study's own signals thresholded (`brain_method`, every self definition) | last, and never presented as an external oracle |

`brain_method` is the only cross-language composite, and it is **internal**: a conjunction of
the harness's own `nloc`, `cc` and `nesting` at cuts the study chose. A result on it is a
statement about internal consistency across measures, not recovery of an external definition.
The external method-level headline is `pmd_method_NPath200` (Java).

Signal quality is scored threshold-free by **AUC**; rule quality by **MCC** of the flagged set.

### Units

The method-level unit is a function, keyed by file, name and start line, so overloads and
same-named functions in one file are distinct units. The class-level unit is a **file**. That
holds roughly for Java (one public top-level class per file) and only loosely elsewhere; the
Java CK pass counts the classes in every measured file and each row records
`java_files_multi_class`, so the size of the approximation is measured, not assumed. PMD and CK
findings are mapped to files by path, never by basename.

A definition with scope `java` is scored on the **Java units only**: its relative rules are
fitted on the Java units and its cells count over them (`n_univ_scope`, `oracle_scope`), so a
Kotlin, Scala or Groovy file in a Java repository, which PMD and CK never evaluated, is not a
forced negative. The per-unit sidecar lists every unit; a Java-scoped analysis filters by the
unit's path.

**What leaves the universe is counted.** Test files, vendored trees and root build directories
are not measured (the same filters as the sampler, so the floor the sample was drawn on is the
floor the harness re-applies). Generated files (`*.pb.go`, `*_pb2.py`, `*.min.js`, ...) and
files over 1 MB are kept out of the universe and counted per row (`files_skipped`), as are
files lizard failed on. The oversize and unparsed **Java** files are still handed to PMD, and CK
sees the whole tree, so a god class in one of them is recorded as a positive **outside the
universe** (`god_outside_univ`, `ck_def_outside`) rather than vanishing.

## The sample

Repositories are drawn by [open-source-repository-sampler](https://github.com/officefloor/open-source-repository-sampler),
a separate tool pinned in `pyproject.toml`, so the population is chosen independently of this
study's code and outcomes. `./step2_sample.sh` draws **two** samples with the same seed and
criteria:

- the **main sample**: every language in `study.SAMPLED_LANGUAGES` × three popularity tiers
  (`high` > 5000 stars, `mid` 1000–5000, `low` 200–999), grown until each language has 30 usable
  repositories;
- the **Java supplement**: Java only, grown to 150 usable repositories. Every composite
  class-level definition and every tool method-level definition is Java-only, so the class-level
  headline's effective sample is the number of *Java* repositories, not the number of
  repositories. With the same seed the supplement's draw order repeats the main sample's Java
  draw, so its first 30 usable repositories are normally the main sample's. That holds only
  while both enumerations of GitHub return the same candidate set: the seeded shuffle runs over
  the sorted set, so a repository gained or lost between the two draws permutes the order. If
  they differ, the Java population is the union of the two draws. Step 3 measures each
  repository once and records which sample drew it, and the diagnostics report how many Java
  rows each sample contributed.

A repository is **usable** on size alone, decided before any detection outcome: at least 50
functions in at least 15 source files with a function (the same floor `study.is_usable` applies
to the measured row). The author's own ecosystem is excluded. Each repository is pinned to the
commit its default branch was on when drawn, and only that commit is measured.

**Ruby is not sampled.** The pinned parser closes a Ruby function at the `end` of a `case`,
`unless` or `until` block inside it, so every per-unit number after that point is wrong.
`study.ruby_parser_bounds_ok()` demonstrates the defect on a fixture at every preflight and
reports whether the installed parser still has it; the harness keeps a Ruby cognitive and
nesting scanner and fixture so Ruby can be re-admitted once a pinned parser bounds it
correctly.

## Running it

Numbered scripts, each printing the next. Prerequisites the scripts do **not** install:
`python3`, `git`, **Java (JRE 17+)**, and the **`gh` CLI authenticated** for step 2.

    ./step1_setup.sh                       # venv + pinned deps (incl. the sampler) + PMD/CK into ./lib
    ./step2_sample.sh                      # draw the main sample and the Java supplement -> sample/
                                           # (seed 2, pre-registered and shared with the coupling
                                           # study; --seed N overrides, 1 drew the pilot and is refused)
    ./step3_run.sh                         # measure both samples -> results/<date>/
    ./step4_analyse.sh --results results/<date>
    ./step5_mlcq.sh                        # optional: the MLCQ human-label sub-study -> results/mlcq/
    ./step6_paper_readouts.sh              # the paper's read-outs and the blinded false-positive sample
    ./step6a_fp_prepare.sh                 # fetch the sample, prepare the author's reading
    ./step6b_fp_author_reading.sh          # the author's reading, by hand; checks it is complete
    ./step6c_fp_model_reading.sh           # the model's blind reading (claude -p), recorded
    ./step6d_paper_build.sh                # merge the readings, build the paper and the arXiv bundle

`pip` pins **lizard 1.23.0** (1.24.x returns no functions for annotated Java classes), and
`study.py` pins **PMD 7.27.0** and the **CK 0.7.0** jar by sha256.

**Step 3** verifies each sample against its derivation, assigns every usable repository its
explore/confirm half from the sample CSVs alone (stratified by language and tier, written to
`halves.json` and recorded in each row **before any repository is measured**), then the
sampler's run loop shallow-clones each usable repository at its pinned commit, the study
measures it, and the clone is deleted. Pass `--sample` more than once to measure several samples (a repository in two is
measured once), `--out-dir` to choose the results directory, `--labels` to add human labels:

    ./step3_run.sh --sample sample/open-source-repository-sample.csv \
                   --sample sample/open-source-repository-sample.java-supplement.csv \
                   --labels labels/mlcq-blob.csv --out-dir results/my-run

**Human labels.** `--labels` takes a CSV with columns `repo` (GitHub URL or `owner/name`),
`commit`, `path` (repo-relative file), `label` and, optionally, `line`. A row without a line
becomes a class-level definition `human_<label>` (the file); a row with one becomes a
method-level definition `human_method_<label>` (the function containing that line). Labels
apply only to repositories whose sampled commit equals the label's commit; a label at another
commit is recorded as `labels_commit_mismatch` and not applied. A label `<x>_reviewed`, listing
every unit the experts looked at, becomes the universe of `<x>`: an unreviewed unit is unknown,
not a negative, and the analysis scores the human definition within the reviewed units.

The MLCQ data set (Madeyski and Lewowski 2020, Zenodo 3666840: Blob at class level, Long
Method at function level, several reviews per sample) is one script, `./step5_mlcq.sh`: it
downloads the file from Zenodo and verifies its sha256 against the datasheet's, converts it
with a pre-registered aggregation rule (strict majority of reviews with any severity above
`none`, so *minor* counts as positive; `--rule any|all` are labelled sensitivity runs) and one
commit per repository, measures every labelled repository at its labelled commit, and prints
the report to the sub-study's own plan (PLAN.md, *The MLCQ sub-study*: decided on the micro
arm alone, since the reviewed universe of a repository is a handful of classes). In MLCQ 1.1 that is 522 Java repositories, 254 Blob and 276 Long Method positives
among 2334 and 2430 reviewed samples, so the run is a few hours of cloning; it is resumable.
The pieces are also separate commands:

    .venv/bin/python -m complexity_concentration_study.cli mlcq --download --out-dir labels
    .venv/bin/python -m complexity_concentration_study.cli study --sample labels/mlcq-repos.csv \
        --labels labels/mlcq-labels.csv --out-dir results/mlcq

The converter writes the labels file, the sample CSV (the sampler's columns, so the run loop
accepts it; the published SSH URLs are normalised to HTTPS so clones need no keys) and a
summary with the input's sha256. A labelled commit that no longer exists on GitHub is a clone
error in the run log and the summary, not a silent gap. The MLCQ population is MLCQ's choice
(Java, 2019 commits), so this run is reported beside the main run, never pooled with it.
Other sources (Landfill, Palomba et al.; the Fontana et al. Qualitas labels read with the Di
Nucci et al. 2018 critique in hand) need their own converter to the same columns.

**Outputs** in `results/<date>/`: `study.json` (one row per repository, the lean matrix),
`study.units.jsonl` (per-unit values, god membership and PMD's values), `oracles.json` (the
definition registry, families, signal pools, rule constants and PMD thresholds), `halves.json`
(the frozen split), `study.csv`, `run-log.jsonl`, and the ancillary package `anc/` (results
table, registry, README and every sample file). **Step 4** (`complexity-concentration-study
analyse`) prints the report to the rules below and to `PLAN.md`, and writes `analysis.json`
beside the run **once**: a second run refuses unless `--exploratory`, which writes a dated
`analysis.exploratory.<utc>.json` and labels its report exploratory.

**The classpath validation** (README, *The classpath validation sub-study*) is one command per
built Java checkout:

    .venv/bin/python -m complexity_concentration_study.cli classpath-check --repo path/to/checkout \
        --classpath-file cp.txt --out results/classpath/<name>.json

where `cp.txt` is Maven's `dependency:build-classpath` output (the checkout's own compiled
classes are added automatically). It reports every class finding that flips with the
classpath and the GodClass flip rate.

### Guarantees the harness enforces

- **Preflight fails loud before any clone** on: a parser blind to annotated Java; a dead
  complexity signal in any sampled language (every signal must separate a deeply nested fixture
  function from a one-liner in all ten languages, and `cc_sum` must equal WMC); missing `git`;
  a configured PMD or CK that does not run, returns no class panel, or returns no method-level
  finding on a synthetic god class; and any tool version off its pin.
- **Every row records its instruments**: the lizard, PMD and CK versions and the **harness
  commit** (with `-dirty` if uncommitted changes were present, and a loud warning at the start
  of the run), so the analysis plan frozen in git before the run is auditable against the data.
- **The split is frozen before the data exist**: `halves.json` is written from the sample CSVs
  before the first clone, every row records its half, and a resumed run refuses a different
  split. The analysis reads the recorded half and flags a run without one as not confirmatory.
- **PMD's values, not only its verdicts.** The four metric rules run at report level 1, so
  every Java method's cyclomatic, cognitive, NPath and NCSS value is recorded in the sidecar
  (`pmd_values`) and the registered thresholds are applied by the harness (`pmd_thresholds` in
  `oracles.json`). The lexical estimators are calibrated against PMD continuously, per
  repository, not at one cut.
- **No forced negatives**: a Java-only definition is scored on Java units only.
- **No silent holes**: a Java row missing a configured panel is announced per repository and
  in the summary; PMD method findings that fall outside every measured function are counted;
  files that left the universe, and definition positives outside it, are counted per row and
  totalled in the summary; a repository drawn as usable that fails the harness floor is named.
- **No lost rows**: `study.json` is written atomically after every repository; a results
  directory whose log or sidecar records work but whose `study.json` is missing or unreadable is
  refused, not resumed.
- **Every repository is in the matrix**, including those where a definition marks nothing:
  those cells carry `n_god_univ == 0` and the per-unit sidecar carries an empty `god_idx`.
- **Diagnostics travel with every row**: per-signal scale kind and zero share, the share of
  trivial units (cyclomatic 1) and of lizard's anonymous units, and the file counts above, so
  the analysis can report them before any accuracy number.

## Analysing a run

These are the rules the paper's analysis must follow; `complexity_concentration_study/stats.py`
provides the tested statistics. They exist because an earlier draft of the analysis broke each
of them.

1. **Headline by origin.** A headline AUC or MCC is read against definitions whose registry
   `kind` is composite, tool or human, in the registry's `headline_order`: tool and human
   first, composed second, internal last and labelled as internal. Self definitions are
   tautological for their signal; calibration definitions measure the estimator; components are
   reported with their prevalence (TCC < 1/3 alone marks most classes).
2. **Exclude ingredients.** A signal in a definition's `ingredients` list may not be the
   headline signal for that definition. `nom` may not headline `decor_blob`; `cc_sum` may not
   headline `pmd_GodClass`; `nloc`, `cc`, `nesting`, `mi` and `cyc_density` may not headline
   `brain_method`.
3. **Report by family, and conditionally.** Every signal has a family (`families` in
   `oracles.json`). Report the best signal of each family, never one "best signal" over the
   pool, and state the cross-measure claim only for families that are not size. For a
   composite with a size clause, report `auc_given` next to `auc`: the AUC within the units
   that already pass the clause. If the density and peak families carry nothing beyond size,
   say so.
4. **Keep god-free repositories, and use a statistic that can see them.** A relative rule is
   fitted to each repository's own distribution, so it can flag units in a repository where a
   definition finds nothing (the top-percentile rule always does; the modified z and the
   fences usually do), and those repositories are where its false positives live. Pool with
   `stats.pooled_confusion`, which keeps `n_god_univ == 0` blocks and reports `fp_in_no_god`
   and the false-positive rate; never filter on "has gods". The **macro MCC cannot see them**:
   `stats.mcc` is 0 whenever a marginal is empty, so a god-free repository scores 0 whether the
   rule flagged nothing or twenty files, and a paired difference of two rules there is an
   uninformative 0 − 0 that only narrows the interval. The macro MCC arm of the decision is
   therefore read over repositories with at least one positive, and the false positives in
   god-free repositories are decided on through the micro MCC and the macro false-positive
   rate (`stats.fpr`, defined there), with its own margin (PLAN.md, *Decision rule*). The
   pooled AUC (`stats.pooled_auc`) keeps god-free blocks too; a within-repository AUC cannot,
   so say that the per-repository AUC conditions on at least one positive.
5. **Split once, before measuring; tune on explore, read on confirm.** The half of every
   repository is assigned by `study.run` from the sample CSV with `stats.assign_halves`,
   stratified by language and tier, before any repository is measured, and recorded in the
   row. Choose the signal, the rule's cut and the absolute cutoff on explore; read all of them
   on confirm. Pre-specify **one** primary estimand (one definition, one level, one family)
   **and the decision rule that reads it** (the paired comparisons, their margins, an AUC floor
   and the minimum effective sample) before the run; every other confirm number is secondary.
6. **Relative at defaults first.** The primary head-to-head is the relative rule at its
   literature constant against the absolute cutoff tuned on explore, since "no re-tuning" is the
   claim. The tuned-relative comparison is secondary. Report the threshold-free form as well:
   `stats.pooled_auc` on the sidecar, standardised against raw, **with a paired bootstrap over
   repositories of the difference**; two point estimates without an interval cannot be read.
7. **Macro before micro, paired for comparisons; say the effective sample.** One repository,
   one vote: `stats.bootstrap_mean` over per-repository statistics is the descriptive form;
   a comparison of two rules read on the same repositories is a **paired** bootstrap of their
   difference (`stats.bootstrap_paired`), never two separate intervals. For Java-only
   definitions the sample is the number of Java repositories in the half being read, and the
   number of positive units; say both. Set the minimum number of positives for a
   per-repository AUC to count, and the minimum number of repositories below which the primary
   is underpowered, before the run. All-language statistics are read on the **main sample**:
   the Java supplement would otherwise make Java a third of every pooled cross-language
   number.
8. **Compare methods properly.** Rank per repository, then use `stats.friedman` (Friedman
   with the Iman–Davenport correction) and `stats.nemenyi_cd`. Pre-specify at most eight signals
   (one or two per family) and at most five rules for this test; 31 class signals on 32 blocks
   is underpowered. A block in which every method ties (every rule scoring 0 in a god-free
   repository) carries no ranking information and is dropped and counted, not left to shrink
   the critical difference.
9. **Break results down** by language, tier and `kind`; a cross-language claim needs the
   per-language numbers.
10. **Read the diagnostics first.** Before any accuracy number: the continuous calibration of
    `cc`, `cognitive` and `nloc` against `pmd_values` (Spearman per repository, then the
    threshold AUC on the calibration definitions); the scale kind and zero share per signal and
    language; the flag rate of every rule per language; `trivial_frac` and `anon_frac`;
    `files_skipped` and `god_outside_univ`; the usable flips the summary names. A weak signal
    cannot be interpreted until its estimator and its population have been.
11. **Say what the constants are.** Quote `oracles.json`: every rule's standardised-axis
    constant, every definition's raw-scale constant, and `pmd_thresholds`.

### Pre-registration

A confirmatory run is one where the analysis could not have been shaped by its data. The
analysis script is `complexity_concentration_study/analyse.py`; its `PLAN` constant is the
machine-readable plan and `PLAN.md` its prose, and the two are tested against each other:

1. Fix `PLAN` (the primary estimand, the decision rule, the families, the minimum positives,
   the Friedman subsets) and commit it with the harness.
2. Tag that commit. `./step3_run.sh` records the harness commit in every row and warns loudly
   if the tree is dirty; a confirmatory run's rows must not say `-dirty`.
3. Draw the confirmatory sample with the pre-registered seed 2 (`step2_sample.sh`'s default;
   seed 1, which drew the pilot, is refused). Seed 2 is shared with the companion coupling
   study, `sinew-identification-study`, so the two studies draw one Java population by design
   (PLAN.md, *Sample seed*). The pilot's repositories are
   listed in `pilot/run-v1-repos.txt`; the diagnostics report any run's overlap with them,
   overlapping repositories are retained (the plan was shaped on pilot aggregates, not on
   repositories), and the primary is re-read without them as a labelled sensitivity analysis.
4. Run the classpath validation on explore-half Java repositories only, writing each report
   into `results/<run>/classpath/` with `--url` (PLAN.md, step 4). The analysis aggregates them
   and applies the pre-registered bound: above a 10% GodClass flip rate, or with the validation
   missing, the primary verdict is marked *oracle-bounded* and is not read as confirmatory.
5. Run, then analyse once: `analysis.json` is written once and never overwritten, and its
   sha256 is printed and written beside it; commit that digest so the file the paper quotes is
   auditable. Everything after that is exploratory, needs `--exploratory`, and is labelled
   exploratory.

### The classpath validation sub-study

PMD and CK run without an auxiliary classpath, so ATFD and CBO see only what the sources
declare and `pmd_GodClass` is under-counted by an unknown amount. Before the confirmatory
analysis, on at least ten Java repositories of the **explore half** (`halves.json`) that build
with Maven or Gradle: build, run PMD with `--aux-classpath` on the built classpath over the
same file list, and report the number of GodClass verdicts that flip. The pre-registered
bound is 10% on at least ten repositories: above it, or with the validation missing, the
primary verdict is marked *oracle-bounded* and not read as confirmatory, the class-level
headline becomes the flip rate itself, and the recovery result is reported as exploratory
(PLAN.md, *Decision rule* and step 4). Confirm repositories are never built or inspected for
this; each report names its repository (`--url`) so the analysis can check that against the
frozen split.

## Threats to validity

**Construct.** Every tool definition is itself imperfect and itself an absolute threshold;
without `--labels` this measures agreement between detectors, not correctness, on terms that
favour the absolute competitor. `decor_blob` omits DECOR's association clause and uses this
study's 0.8 LCOM* cut; `brain_method` omits NOAV and is internal; `cognitive`, `hvol`, `mi` and
`nesting` are lexical estimators (calibrated against PMD on Java fixtures in
`tests/test_cognitive.py`, and continuously in the field through `pmd_values`). The class-level
unit is a file. The constants in `ck_LCOM` (0.8) and `ck_CBOhigh` (14) are the study's own
choices and are marked as components for that reason. Size collinearity is addressed by
families and the conditional AUC, not removed.

**Internal.** PMD and CK run without an auxiliary classpath (see the validation sub-study).
Test code is excluded by directory and naming conventions that can miss or over-match.
Generated files, files over 1 MB and files lizard fails on leave the universe; their counts,
and the definition positives among them, are recorded. The relative rules are fitted on the
whole universe, zeros included, which makes zero-heavy signals (`params`, `cognitive` on trivial
functions) fall back to a mean-absolute-deviation scale; the scale kind is recorded. lizard
reports every anonymous JavaScript and TypeScript callback as a unit, which inflates those
method universes with trivial functions; `trivial_frac` and `anon_frac` size the effect.

**External.** GitHub repositories with 200 or more stars, ten languages, one commit each, drawn
with equal allocation across three popularity tiers, so pooled numbers are unweighted over
strata, not population estimates. Popularity tier is a proxy for maintenance intensity, not
quality; application versus library is a post-hoc heuristic. Repositories of one GitHub owner
are not independent draws, and the bootstrap resamples repositories; the owner concentration
of the sample is reported with the diagnostics. Non-size definitions are Java-only, so the
class-level composite result is a Java result until human labels or a second language's
composite oracle are added. Re-running the sampler reproduces the method, not necessarily the
list; the published samples, pinned to commits, are the record of the population.

**Conclusion.** The matrix is a large search (signals × rules × definitions × levels); the
single best cell is upward-biased, which is why one primary estimand and one decision rule are
pre-specified, chosen on explore and read on confirm, and why sections that rank everything
are exploratory. The within-repository AUC is identical under the relative and the absolute
view, so it is evidence about the signal, never about scale-freeness; only the pooled
standardised-versus-raw AUC and the operating-point comparison speak to the relative claim.
With a median of about two PMD god classes per Java repository, per-repository AUCs are
coarse; hence rules 7 and 10 above and the effective-sample gate in PLAN.md.

## Where things are

- `complexity_concentration_study/extract.py`: per-function complexity records and per-file WMC
  (lizard for functions, CC, lines and tokens; the harness's own scanners for cognitive,
  nesting, Halstead, MI, exit points; a lexical PHP parameter count because lizard's is wrong).
- `complexity_concentration_study/cognitive.py`: the cognitive-complexity and nesting scanner
  (braces, indentation, Ruby `end` blocks).
- `complexity_concentration_study/metrics.py`: the relative outlier rules, their constants, the
  signal pools, AUC/AP, and the per-repo matrix.
- `complexity_concentration_study/study.py`: the oracle registry, PMD/CK/human oracle wiring,
  preflight, pins, the resumable run.
- `complexity_concentration_study/stats.py`: pooled confusion including god-free blocks, the
  pooled standardised-versus-raw AUC, the bootstrap over repositories, the stratified
  explore/confirm split, Spearman, the tuned absolute cutoff, Friedman and Iman–Davenport with
  exact p-values, the computed Nemenyi critical difference.
- `complexity_concentration_study/analyse.py`: the report, to the rules above and `PLAN.md`;
  one code path from the sidecar for every accuracy number.
- `complexity_concentration_study/classpath_check.py`: the classpath validation on one checkout.
- `complexity_concentration_study/mlcq.py`: the MLCQ converter.
- `PLAN.md`: the pre-registered plan, in prose.
- `pilot/run-v1-repos.txt`: every repository the pilot measured, so overlap is reported.
- `tests/`: hand-worked and PMD-calibrated tests for all of the above. Run them with
  `.venv/bin/python tests/test_<name>.py` (each file is its own runner, nothing to install) or
  with pytest after `.venv/bin/pip install -e '.[test]'`.
- `paper/`: the write-up (its old analysis script is superseded by the package's `analyse`).

## What is and isn't committed

Code, plus the samples once drawn (`sample/`, four small files, worth committing so the study
population is pinned in the repository). Dependencies (`./lib`) and results (`results/<date>/`)
are git-ignored: every machine downloads the exact pinned tools itself, and results are
regenerated by running the study. The ancillary package under `results/<date>/anc/` is what a
paper attaches.
