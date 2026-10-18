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
  classes, which selects larger repositories; the MCC and the decision rule below are read on
  **every** confirm Java repository carrying the definition, god-free ones included.
- **Signal:** chosen on the explore half among the **peak** and **density** families only
  (never a size signal, never an ingredient of the definition), by the macro mean of the
  per-repository AUC over repositories with at least 3 positives. Read on confirm.
- **Rule:** `mad_z` at its literature default (modified z ≥ 3.5), fitted on the Java units.
- **Competitor:** the single absolute cutoff on the same signal that maximises the pooled MCC
  on explore (`stats.best_cutoff`), read on confirm.
- **Confirm read-outs, in this order:** macro mean per-repository AUC with a bootstrap CI over
  repositories; the conditional AUC within files with WMC ≥ 47; the pooled AUC standardised
  versus raw; MCC at the default cut, macro and micro, with the macro false-positive rate and
  the false positives in god-free repositories; the same for the tuned absolute cutoff; then
  the decision below. The tuned relative cut is secondary.

## Decision rule

The claim is read off **one paired comparison**: relative rule at its default minus the tuned
absolute cutoff, on the **same** confirm repositories, with a 95% percentile bootstrap that
resamples repositories (`stats.bootstrap_paired`, 2000 resamples, seed 12345).

- **Non-inferiority margin: 0.05 MCC.** The relative rule is *non-inferior* if the lower bound
  of the interval on the difference is above −0.05, *superior* if it is above 0, *inferior* if
  the upper bound is below −0.05, and *inconclusive* otherwise.
- **Both averages must agree.** The verdict is the weaker of the macro-MCC verdict and the
  micro-MCC verdict. The macro MCC is 0 in a god-free repository whatever was flagged, so it is
  blind to the false positives a relative rule must produce there; the micro MCC sees them.
  The macro false-positive rate, which is defined in god-free repositories, is reported beside
  them but is not decided on.
- **AUC floor: 0.70.** Whatever the verdict, the signal is said to carry the definition only
  if the lower bound of the macro per-repository AUC on confirm is at least 0.70.
- **Effective-sample gate.** The primary is read as confirmatory only if the confirm half holds
  at least **20** Java repositories with ≥ 3 positives (for the AUC) and at least **40** Java
  repositories carrying the definition (for the paired MCC). Below either, the numbers are
  reported with the verdict marked *underpowered*, and the paper says so.

**Power, stated in advance.** The half-width of the paired interval is about 1.96·s/√n, where
s is the per-repository standard deviation of the MCC difference. At n = 40 the margin of 0.05
is resolvable (a true difference of 0 is declared non-inferior) when s ≤ 0.16; at n = 60 when
s ≤ 0.19. For the AUC, 20 repositories with a per-repository standard deviation of 0.15 give a
half-width of about 0.07, so a true mean of 0.80 clears the floor. The Java supplement target
of 120 usable repositories is set from the pilot's median of about two PMD god classes per Java
repository: about 60 confirm Java repositories, of which roughly 20 to 25 are expected to clear
the 3-positive floor. If the realised s is larger than assumed, the verdict will be
*inconclusive*, which is the honest outcome, not a failure of the rule.

## Secondary definitions, in headline order

1. `pmd_method_NPath200` (tool, Java, method level): structure and density families.
2. `human_*` definitions when labels are supplied (human): fitted on the labelled repository's
   own language and scored within the reviewed units; the share of labels that landed on a
   measured unit is reported first.
3. `decor_blob` (composed, Java, class level): peak and density families, conditional on
   `ck_LargeClass`.
4. `brain_method` (internal, all languages, method level): structure and density families,
   excluding its ingredients; reported as internal consistency, not recovery.

Each secondary gets the same read-outs and the same paired decision, labelled secondary; no
multiplicity correction is applied across them, and none of them can change the primary
verdict.

## Fixed in advance

- **Explore/confirm split:** `stats.assign_halves`, stratified by (language, tier), assigned by
  `study.run` from the sample CSVs **before any repository is measured**, written to
  `halves.json` in the results directory and recorded in every row (`half`). The analysis
  reads the recorded half and flags a run whose rows carry none as not confirmatory.
- **Sample seed:** `step2_sample.sh` requires `--seed N` and refuses seed 1, which drew the
  pilot (`pilot/run-v1-repos.txt`, 522 repositories). The diagnostics report the overlap of
  any run with the pilot list.
- **All-language statistics** (every definition whose scope is not Java) are read on the
  **main sample** only; the Java supplement enters Java-scoped statistics only.
- Minimum positives for a per-repository AUC to count: 3. Repositories with fewer are kept in
  every pooled and MCC statistic.
- Friedman tests: signals `nloc_sum, nom, cc_max, cognitive_max, cc_mean, mi_mean` (class) and
  `nloc, hvol, cc, cognitive, cyc_density, mi` (method); rules `mad_z, double_mad, iqr,
  adj_boxplot, pct_top1`. `zscore` is a control and `evt_pot` needs tuning; both are
  exploratory. Blocks in which every method ties (every rule scoring 0 in a god-free
  repository) are dropped and counted.
- Bootstrap: 2000 resamples, seed 12345, for every interval.
- Diagnostics are read first: the split's provenance, the pilot overlap, calibration of the
  estimators against PMD's values, the scale kinds and zero shares, flag rates per rule and
  language, trivial and anonymous unit shares, files and positives outside the universe,
  usable flips.

## Procedure

1. Commit this plan and the analysis script; tag the commit (`plan-v1`).
2. Draw the confirmatory sample with a fresh seed (`./step2_sample.sh --seed N`, N ≠ 1).
3. Run `./step3_run.sh`; confirm no row records `-dirty` and that `halves.json` was written
   before the first repository was measured.
4. **Before reading confirm:** run the classpath validation (`classpath-check`) on the
   buildable Java repositories of the **explore** half (`halves.json` names them), at least
   ten. If more than 10% of PMD GodClass verdicts flip with the classpath, the primary
   definition is under-counted by a material amount: the paper reports the flip rate as an
   explicit bound on the headline and makes no recovery claim beyond it. The classpath check
   never touches confirm repositories.
5. Run `./step4_analyse.sh` once. It writes `analysis.json` and refuses to overwrite it; any
   later run needs `--exploratory` and is written to a dated file and labelled exploratory.
6. The MLCQ sub-study (`./step5_mlcq.sh`) is reported beside the primary result, never pooled
   with it. Its reviewers graded code samples without the repository in view, so its labels
   are absolute judgements too; they are external, not scale-free.
