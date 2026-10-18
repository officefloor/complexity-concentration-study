# Pre-registered analysis plan

This file and `complexity_concentration_study/analyse.py` (its `PLAN` constant is the single
machine-readable source of the choices below) are committed and tagged **before** the
confirmatory sample is drawn. A run's rows record the harness commit; a confirmatory run must
not record `-dirty`. Everything the report prints outside its PRIMARY section is secondary or
exploratory and is labelled as such.

## Primary estimand

- **Level:** class (unit = file). **Definition:** `pmd_GodClass` (origin: tool; Java).
- **Signal:** chosen on the explore half among the **peak** and **density** families only
  (never a size signal, never an ingredient of the definition), by the macro mean of the
  per-repository AUC over repositories with at least 3 positives. Read on confirm.
- **Rule:** `mad_z` at its literature default (modified z ≥ 3.5), fitted on the Java units.
- **Confirm read-outs, in this order:** macro mean per-repository AUC with a bootstrap CI over
  repositories; the conditional AUC within files with WMC ≥ 47; the pooled AUC standardised
  versus raw; MCC at the default cut, macro and micro, with false positives in god-free
  repositories; the absolute cutoff on the same signal tuned on explore, read on confirm, macro
  and micro. The tuned relative cut is secondary.

## Secondary definitions, in headline order

1. `pmd_method_NPath200` (tool, Java, method level): structure and density families.
2. `human_*` definitions when labels are supplied (human): scored within the reviewed units.
3. `decor_blob` (composed, Java, class level): peak and density families, conditional on
   `ck_LargeClass`.
4. `brain_method` (internal, all languages, method level): structure and density families,
   excluding its ingredients; reported as internal consistency, not recovery.

## Fixed in advance

- Explore/confirm split: `stats.assign_halves`, stratified by language and tier.
- Minimum positives for a per-repository AUC to count: 3. Repositories with fewer are kept in
  every pooled and MCC statistic.
- Friedman tests: signals `nloc_sum, nom, cc_max, cognitive_max, cc_mean, mi_mean` (class) and
  `nloc, hvol, cc, cognitive, cyc_density, mi` (method); rules `mad_z, double_mad, iqr,
  adj_boxplot, pct_top1`. `zscore` is a control and `evt_pot` needs tuning; both are
  exploratory.
- Bootstrap: 2000 resamples, seed 12345.
- Diagnostics are read first: calibration of the estimators against PMD's values, the scale
  kinds and zero shares, flag rates per rule and language, trivial and anonymous unit shares,
  files and positives outside the universe, usable flips.

## Procedure

1. Commit this plan and the analysis script; tag the commit.
2. Draw the confirmatory sample with a seed no analysis has seen (`./step2_sample.sh --seed N`).
3. Run `./step3_run.sh`; confirm no row records `-dirty`.
4. Run `./step4_analyse.sh` once. Later runs of the report are exploratory.
5. The classpath validation (`classpath-check` on about ten built Java repositories) and the
   MLCQ sub-study (`mlcq`, then a labelled run) are reported beside the primary result.
