# Pre-registered analysis plan

This file and `complexity_concentration_study/analyse.py` (its `PLAN` constant is the single
machine-readable source of the choices below) are committed and tagged **before** the
confirmatory sample is drawn. A run's rows record the harness commit; a confirmatory run must
not record `-dirty`. Everything the report prints outside its PRIMARY section is secondary or
exploratory and is labelled as such.

## Primary estimand

- **Level:** class (unit = file). **Definition:** `pmd_GodClass` (origin: tool; Java).
- **Population:** the Java repositories of the confirm half. The per-repository AUC is a
  **conditional** estimand: the mean over confirm Java repositories with at least 3 PMD god
  classes, which selects larger repositories; the micro MCC and the false-positive rate below
  are read on **every** confirm Java repository carrying the definition, god-free ones
  included; the macro MCC is read on the confirm Java repositories with at least one positive
  (below, *Decision rule*).
- **Signal:** chosen on the explore half among the **peak** and **density** families only
  (never a size signal, never an ingredient of the definition), by the macro mean of the
  per-repository AUC over repositories with at least 3 positives. Read on confirm.
- **Rule:** `mad_z` at its literature default (modified z ≥ 3.5), fitted on the Java units.
- **Competitor:** the single absolute cutoff on the same signal that maximises the **pooled**
  MCC on explore (`stats.best_cutoff`), read on confirm. That one cut is read on every arm of
  the decision, the macro arms included, which mildly disadvantages the absolute rule there;
  the design is tilted toward the absolute rule everywhere else (README, *The claim under
  test*, point 3), and the asymmetry is stated rather than tuned away.
- **Confirm read-outs, in this order:** macro mean per-repository AUC with a bootstrap CI over
  repositories; the conditional AUC within files with WMC ≥ 47; the pooled AUC standardised
  versus raw, **and their paired difference** with a bootstrap CI over repositories (the
  threshold-free reading, below); MCC at the default cut, macro and micro, with the macro
  false-positive rate and the false positives in god-free repositories; the same for the tuned
  absolute cutoff; then the decision below. The tuned relative cut is secondary.

## Decision rule

The claim is read off **three paired comparisons** of the relative rule at its default minus
the tuned absolute cutoff, each on the **same** confirm repositories, each with a 95%
percentile bootstrap that resamples repositories (`stats.bootstrap_paired`, 2000 resamples,
seed 12345). The verdict is the **weakest** of the three arms.

| arm | statistic | population | better |
|---|---|---|---|
| macro MCC | mean per-repository MCC difference | confirm Java repositories with ≥ 1 positive | higher |
| micro MCC | pooled MCC difference | every confirm Java repository carrying the definition | higher |
| macro FPR | mean per-repository false-positive-rate difference | every confirm Java repository carrying the definition | lower |

- **Why the macro MCC excludes god-free repositories.** In a repository where the definition
  marks nothing the MCC is 0 for both rules by convention, whatever either flagged. Such 0 − 0
  pairs carry no information about the rules yet narrow the interval on the mean difference
  (about a quarter of the pilot's Java repositories were god-free), so they would make
  non-inferiority easier to reach for no reason. The false positives in those repositories are
  seen by the micro arm (they enter the pooled counts) and by the FPR arm (the rate is defined
  there), which is why both arms decide.
- **MCC margin.** On the two MCC arms the relative rule is *non-inferior* if the lower bound of
  the interval on the difference is above −margin, *superior* if it is above 0, *inferior* if
  the upper bound is below −margin, and *inconclusive* otherwise. The margin read is
  **min(0.10, 0.30 × the explore-half macro MCC of `mad_z` on the chosen signal over
  repositories with ≥ 1 positive)**. 0.10 is the ceiling the pilot's spread makes resolvable
  (below). The scaling exists because the pilot measured only per-file **sums** at class level
  (its class signals were `cc`, `nloc`, `tokens`, `nom`, `cognitive`, `nesting`, `params` as
  sums): the MCC level of a **peak** or **density** signal, the only families the primary may
  use, is unknown until explore, and a fixed 0.10 could be most of it. Choosing the margin on
  explore is tuning on explore, which the plan allows; the margin actually read is recorded in
  `analysis.json` beside both inputs.
- **FPR margin: 0.05.** On the FPR arm the relative rule is *non-inferior* if the upper bound of
  (relative FPR − absolute FPR) is below +0.05, *superior* if it is below 0, *inferior* if the
  lower bound is above +0.05, and *inconclusive* otherwise. In the pilot `mad_z` flagged 5–7%
  of the non-god files of a Java repository on every sum signal, so a rule that flags five
  points more non-gods than the tuned cut flags roughly twice as many: it is not transferring
  its constant, whatever its MCC. The pilot's paired FPR difference between two relative rules
  had a standard deviation of 0.03–0.05, so 0.05 is resolvable at 40 repositories.
- **AUC floor: 0.70.** Whatever the verdict, the signal is said to carry the definition only
  if the lower bound of the macro per-repository AUC on confirm is at least 0.70.
- **Effective-sample gate.** The primary is read as confirmatory only if the confirm half holds
  at least **20** Java repositories with ≥ 3 positives (for the AUC) and at least **40** Java
  repositories carrying the definition (for the paired MCC). Below either, the numbers are
  reported with the verdict marked *underpowered*, and the paper says so.
- **Classpath bound (step 4 below).** The primary is read as confirmatory only if the
  classpath validation found a GodClass flip rate of at most **10%** on at least **10**
  explore repositories. Above the bound, or with the validation missing, the verdict is
  reported marked *oracle-bounded* and is not read as confirmatory: the paper's class-level
  headline is then the flip rate itself, and the recovery result is reported as exploratory.
- **Threshold-free reading (reported beside the verdict, not part of it).** The pooled AUC on
  the per-repository modified z minus the pooled AUC on the raw value, over the same confirm
  repositories, as a paired bootstrap: lower bound above 0 reads *relative ranking better*,
  upper bound below 0 *absolute ranking better*, otherwise *no difference resolved*. It
  answers a different question (ranking, not a cut), so it does not change the verdict.

**Power, stated in advance, from the pilot.** The pilot (`pilot/run-v1-repos.txt`, 36 Java
repositories with a PMD panel) gives: median 2 PMD god classes per Java repository, 25%
god-free, 42% with 3 or more; a per-repository MCC of `mad_z` against PMD GodClass on its sum
signals with mean 0.33–0.37 over all repositories and 0.44–0.49 over repositories with at least
one positive (standard deviation 0.23–0.30); and a standard deviation of the **paired**
per-repository MCC difference between two relative rules of 0.07–0.16. The half-width of the
paired interval is about 1.96·s/√n. With s = 0.25 it is 0.077 at n = 40, 0.063 at n = 60 and
0.057 at n = 75; with s = 0.30 it is 0.093, 0.076 and 0.068. A margin of 0.05 is therefore
**not** resolvable at any sample this study can afford (a true difference of 0 would read
*inconclusive*), and 0.10 is resolvable from about 60 confirm repositories even at s = 0.30.
The Java supplement target of **150** usable repositories gives about 75 confirm Java
repositories, of which about 56 are expected to carry at least one positive (the macro MCC
arm) and about 31 to clear the 3-positive floor (gate: 20). For the AUC, 20 repositories with a
per-repository standard deviation of 0.11 (the pilot's largest) give a half-width of about
0.05. The pilot's size signals reach a per-repository AUC of about 0.95 against PMD GodClass,
so the 0.70 floor is a precondition that the chosen peak or density signal carries the
definition at all, not the claim; the paper states the size level beside it. If the realised s
is larger than the pilot's, or the explore level of the chosen signal is low enough that the
scaled margin is small, the verdict will be *inconclusive*, which is the honest outcome, not a
failure of the rule.

## Secondary definitions, in headline order

1. `pmd_method_NPath200` (tool, Java, method level): structure and density families.
2. `human_*` definitions when labels are supplied (human): fitted on the labelled repository's
   own language and scored within the reviewed units; the share of labels that landed on a
   measured unit is reported first. Decided on the **micro arm only** (below, *The MLCQ
   sub-study*).
3. `decor_blob` (composed, Java, class level): peak and density families, conditional on
   `ck_LargeClass`.
4. `brain_method` (internal, all languages, method level): structure and density families,
   excluding its ingredients; reported as internal consistency, not recovery.

Each secondary gets the same read-outs and the same paired decision, labelled secondary; no
multiplicity correction is applied across them, and none of them can change the primary
verdict. The primary is Java and class-level, and the only cross-language definition is
internal, so **no result of this run supports a cross-language claim about recovering an
external god definition**; the paper's discussion may motivate scale-freeness by portability
but may not present it as shown.

## The MLCQ sub-study

The human-label run (`./step5_mlcq.sh`) is a separate population (MLCQ's Java repositories at
their 2019 commits) and is reported beside the primary, never pooled with it. Its plan:

- **Definition:** `human_blob` (class level, the labelled file), scored within the reviewed
  units (`human_blob_reviewed`); `human_method_long_method` (method level) is its secondary.
- **Aggregation rule:** a sample is positive when a **strict majority** of its reviews grade
  the smell above `none`, so *minor* counts as positive. The `any` and `all` rules are run as
  labelled sensitivity analyses, never as the headline.
- **Signal and competitor:** chosen and tuned on the MLCQ run's own explore half (the harness
  splits every run the same way), read on its confirm half.
- **Decision:** the **micro MCC arm alone**, with the same MCC margin rule. MLCQ reviewed a
  handful of classes per repository, so a per-repository MCC or FPR over the reviewed units is
  mostly noise; the pooled arm over the reviewed units of the confirm half is the one that
  carries information. The macro arms and the FPR arm are reported, not decided on. The
  effective-sample gate applies with the same constants.

## Fixed in advance

- **Explore/confirm split:** `stats.assign_halves`, stratified by (language, tier), assigned by
  `study.run` from the sample CSVs **before any repository is measured**, written to
  `halves.json` in the results directory and recorded in every row (`half`). The analysis
  reads the recorded half and flags a run whose rows carry none as not confirmatory.
- **Sample seed:** `step2_sample.sh` requires `--seed N` and refuses seed 1, which drew the
  pilot (`pilot/run-v1-repos.txt`, 522 repositories).
- **Pilot overlap:** the confirmatory sample is drawn from the same population as the pilot,
  so some overlap is expected. Overlapping repositories are **retained**: the plan was shaped
  on the pilot's aggregates (levels, spreads, prevalences), not on any repository. The
  diagnostics report the overlap, and the primary decision is **re-read on the confirm half
  without the pilot repositories** as a labelled sensitivity analysis.
- **Java supplement:** the supplement's draw repeats the main sample's Java draw only if both
  enumerations of GitHub returned the same candidate set; otherwise the Java population is the
  union of the two draws. The diagnostics report how many Java rows each sample drew.
- **All-language statistics** (every definition whose scope is not Java) are read on the
  **main sample** only; the Java supplement enters Java-scoped statistics only.
- **Owner concentration** is a diagnostic: repositories of one GitHub owner are not independent
  draws and the bootstrap resamples repositories, so the number of distinct owners, the rows
  that share an owner and the largest owners are reported before any accuracy number.
- Minimum positives for a per-repository AUC to count: 3. Repositories with fewer are kept in
  every pooled and MCC statistic.
- Friedman tests: signals `nloc_sum, nom, cc_max, cognitive_max, cc_mean, mi_mean` (class) and
  `nloc, hvol, cc, cognitive, cyc_density, mi` (method); rules `mad_z, double_mad, iqr,
  adj_boxplot, pct_top1`. `zscore` is a control and `evt_pot` needs tuning; both are
  exploratory. Blocks in which every method ties (every rule scoring 0 in a god-free
  repository) are dropped and counted.
- Bootstrap: 2000 resamples, seed 12345, for every interval.
- Diagnostics are read first: the split's provenance, the pilot overlap, the Java rows per
  sample, the owner concentration, the classpath reports, calibration of the estimators
  against PMD's values, the scale kinds and zero shares, flag rates per rule and language,
  trivial and anonymous unit shares, files and positives outside the universe, usable flips.

## Procedure

1. Commit this plan and the analysis script; tag the commit (`plan-v1`).
2. Draw the confirmatory sample with a fresh seed (`./step2_sample.sh --seed N`, N ≠ 1).
3. Run `./step3_run.sh`; confirm no row records `-dirty` and that `halves.json` was written
   before the first repository was measured.
4. **Before reading confirm:** run the classpath validation (`classpath-check --url
   owner/name --out results/<run>/classpath/<name>.json`) on the buildable Java repositories
   of the **explore** half (`halves.json` names them), at least ten. The analysis aggregates
   the reports under `results/<run>/classpath/`, checks every named repository against the
   split, and applies the classpath bound above: more than 10% of GodClass verdicts flipping
   means the primary definition is under-counted by a material amount, and the primary verdict
   is marked *oracle-bounded* and not read as confirmatory. The classpath check never touches
   confirm repositories; a report that names one makes the run not confirmatory.
5. Run `./step4_analyse.sh` once. It writes `analysis.json`, refuses to overwrite it, and prints
   the file's sha256 (also written to `analysis.json.sha256`). **Commit that digest** to the
   repository (for example in `analysis-hashes.txt`) so the confirmatory analysis is auditable
   against the file the paper quotes; any later run needs `--exploratory` and is written to a
   dated file and labelled exploratory.
6. The MLCQ sub-study (`./step5_mlcq.sh`) is reported beside the primary result, never pooled
   with it, to its own plan above. Its reviewers graded code samples without the repository in
   view, so its labels are absolute judgements too; they are external, not scale-free.
