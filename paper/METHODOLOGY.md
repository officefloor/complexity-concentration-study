# Complexity concentration → god classes/methods — methodology and caveats

This note governs the comparison produced by `study.analyse` (the `matrix` block in each
`study.json` row) and rendered by `paper/analyse.py`. It exists so the comparison is
read honestly rather than as a fishing expedition.

## Hypothesis and motivation

A god class is **complexity concentrated** into one unit. Textbook detectors mark that
concentration with **absolute thresholds** — `WMC ≥ 47`, `CC ≥ 14`, `cognitive ≥ 15`,
`LOC ≥ 50` — each a proxy for *a human's* comprehension budget. That budget is not fixed: as AI
agents take over reading and maintaining code the effective "developer" grows more capable, and
every such constant drifts out of calibration (a method that overwhelmed a human is routine for
an agent). Keeping absolute-threshold metrics honest therefore means **re-deriving each constant
whenever the reader's capability changes** — including the benchmark-derived thresholds (Alves et
al. 2010; Oliveira–Valente–Lima 2014; Ferreira/Fontana), which replace expert opinion with a
corpus percentile but still ship **a constant** that must be re-fitted as the population moves.

A **relative outlier carries no constant.** It asks only whether a unit is unusually
concentrated *relative to its own codebase*, which means the same thing to any reader, in any
era. So the hypothesis is:

> An unsupervised, **threshold-free** relative outlier in *any* reasonable complexity measure
> identifies the same god classes a tuned, absolute-threshold tool marks — because, under
> **conservation of complexity**, a god is the *concentration*, not the absolute level. The act
> of finding the outlier matters more than the measure, so the detector needs no settings, no
> benchmark, and no re-tuning as capability rises.

This is what the breadth of the design serves. We deliberately include **largely-redundant
measures** (cyclomatic, Halstead, LOC and the rest are known to correlate): if the result holds
across them, it is a statement about concentration itself, not about one metric, and the reader
may pick whichever measure they like. The study makes the claim falsifiable in three ways:

1. **Threshold-free recovery.** AUC of the raw relative signal against the tool oracle, out of
   sample (explore/confirm). High AUC with *no threshold chosen* is the hypothesis holding.
2. **Across measures (conservation).** The cross-measure correlation and the spread of AUC over
   measures: if many uncorrelated-in-name measures all recover the oracle, concentration is the
   common cause. `paper/analyse.py` reports this.
3. **Relative beats a tuned constant.** The head-to-head of the per-repo relative rule against
   the single best *global* absolute cutoff (the Alves-style calibrated constant). If the
   self-calibrating rule matches or beats an optimally-tuned fixed threshold, the constant was
   never needed. This uses the per-unit data written to the run's `*.units.jsonl` sidecar.

## The question

This is **identification**, not prediction: at a single checkout, does a relative
**complexity-concentration spike** mark the same classes/methods that a textbook god-class
definition marks? We vary three things and hold the repo fixed:

- **signal** — each per-unit complexity definition, every one oriented so higher == more
  god-like: `cc` (cyclomatic), `cognitive` (Campbell), `nloc`, `tokens`, `params`, `nesting`,
  `cyc_density` (cc/nloc), `exit_points`, `hvol` (Halstead volume, approximate) and `mi`
  (maintainability *burden* = `100 − MI`, inverted so higher is worse like the rest). The
  measures are deliberately largely-redundant — cyclomatic, Halstead and LOC are known to
  correlate strongly — because the claim under test is that *concentration* (the outlier), not
  the choice of measure, is what marks a god (conservation of complexity). At **class level**
  each base measure is aggregated per file three ways, `{base}_sum / _mean / _max`, so the
  matrix compares measure AND aggregation; `cc_sum` = WMC and `nom` (methods per class) is a
  class-level-only count.
- **algorithm** — the relative outlier rule that turns a signal into a flagged set: `mad_z`
  (Iglewicz–Hoaglin), `double_mad`, `iqr` (Tukey), `adj_boxplot` (Hubert–Vandervieren),
  `evt_pot` (peaks-over-threshold GPD), `pct_top1`, `zscore` (classic, parametric control).
- **definition (oracle)** — at class level `WMC≥47`, the PMD design panel, and the CK
  cohesion/coupling definitions (`ck_LCOM`, `ck_TCClow`, `ck_CBOhigh`) plus an approximate
  DECOR `decor_blob`. At method level the single-metric thresholds `CC≥14`, `cognitive≥15`,
  `nesting≥5`, `nloc≥50`, `params≥5` and the composite `brain_method` — the conjunction of
  long, high-CC and deeply-nested (a faithful-but-partial Lanza–Marinescu Brain Method,
  omitting the NOAV clause, as `decor_blob` omits DECOR's data-class clause).

Both method and class/file level.

## Two metrics, kept separate on purpose

A signal is continuous; an algorithm thresholds it. Mixing them confounds "is this a better
signal" with "was its threshold set tighter". So:

- **Signal quality = AUC** of the raw signal value against the definition's label, over the
  common universe — **threshold-free, no algorithm** (Mann–Whitney AUC, tie-corrected; AP for
  the rare-class view).
- **Algorithm quality = MCC** of the flagged set at the algorithm's own threshold (Matthews
  correlation, the balanced choice for imbalanced labels; Chicco & Jurman 2020).

Signals are ranked by AUC; algorithms by MCC.

## Independent vs self-referential oracles

Some oracles are a single signal restated as a threshold, so a matching signal scoring AUC≈1
on them is a **tautology, not a result**: `wmc47` is Sum(`cc`) at class level, and at method
level `cc14`/`cognitive15`/`loc50`/`params5`/`nesting5` ARE the signal thresholded. The
reporter lists those separately and never lets them drive the headline. The real targets are
the **composite** definitions, which no single signal defines: at class level `pmd_GodClass`
and `decor_blob`; at method level `brain_method`. A composite is a fair target because
recovering it from one measure is a genuine finding (as `nom` recovering `pmd_GodClass` is).
`brain_method` is built from `nloc`, `cc` and `nesting`, so those three are its **ingredients**
— their AUC on it is partly built in, the reporter marks them (`*`), and the headline is taken
from the best *non-ingredient* signal; `tokens`, `cognitive`, `params`, `hvol`, `mi`,
`cyc_density` and `exit_points` recovering `brain_method` are the clean cross-signal tests of
concentration. CK cohesion/coupling and the PMD size panel are supporting, tool-derived
(Java-only) targets.

## Aggregation and the explore/confirm split

Per the standard for comparing many methods over many data sets (Demšar 2006): the Friedman
block is the **repository**. Within a repo, a signal's AUC (or an algorithm's MCC) is first
averaged over the definitions of the group it has, then signals are ranked per repo, the ranks
averaged, and Friedman + the Nemenyi critical difference read next to the plain mean.

`analyse.py` splits the usable repositories (the headline substance floor) into an
EXPLORE and a CONFIRM half by a hash of the repository URL. Data-driven choices — which signals
are dropped as degenerate, which complexity signal is strongest — are made on EXPLORE; the
best signal's AUC is then read on the held-out CONFIRM half, so the headline is out of sample.

## Caveats (read every headline number against these)

1. **Multiple comparisons.** 6–7 signals × 7 algorithms × ~11 definitions × 2 levels is a
   large search; the single best cell is upward-biased. Prefer the explore/confirm number, and
   read sections 2–4 as exploratory.
2. **Correlated definitions.** `WMC`, `TooManyMethods`, `NcssCount`, `ExcessiveClassLength`,
   `TooManyFields` are all essentially size — several votes for one dimension. They are
   therefore **grouped** (size/complexity, cohesion, coupling, composite) and never averaged
   into one number; a size signal winning the size group is tautological, not a finding.
3. **Type-aware oracle vs type-blind signal.** PMD and CK parse Java and resolve
   inheritance/dispatch; the complexity signals are lexical and type-blind. On
   abstraction/polymorphism the oracle can mark a god the signal structurally cannot, so a
   signal's measured AUC is a **floor**, not its true ceiling.
4. **Java-only panel.** Beyond `WMC`, every definition (PMD, CK, DECOR) is Java-only, so the
   multi-definition comparison is a **Java** result; the other languages contribute only the
   size definitions.
5. **No human ground truth.** Every oracle is tool-derived and itself imperfect. This measures
   **agreement between detectors**, not correctness. `decor_blob` omits DECOR's data-class
   association clause, so it is a faithful-but-partial Blob, not the certified Ptidej rule.
6. **Cognitive complexity** is a faithful approximation, not the certified SonarSource value;
   fine for a relative spike, read as an estimate.
7. **Method-level composite vs ingredients.** The five single-metric method definitions are
   each a signal thresholded (AUC≈1 is tautological), so the method-level result rests on the
   composite `brain_method`. Because it is the conjunction of long ∧ high-CC ∧ deeply-nested,
   `nloc`/`cc`/`nesting` are its ingredients and get a built-in advantage (flagged and kept out
   of the headline); the honest method-level claim is whether the *other* measures recover it.
   A fully signal-independent method oracle (e.g. PMD's own `CyclomaticComplexity` /
   `NPathComplexity` / `ExcessiveMethodLength` / `CognitiveComplexity`, Java-only) would further
   harden it and is the natural next addition.
8. **Halstead volume and MI are approximate and language-neutral.** `hvol` uses a parser-free
   operator/operand lexer with one rule set for every language (not a per-language operator
   table), and `mi` is the classic three-metric Maintainability Index built on it; both are
   faithful relative estimates, not certified tool values, and `mi` is stored inverted as a
   burden so higher means worse.

## References

- D. Chicco, G. Jurman. *The advantages of the Matthews correlation coefficient (MCC) over F1
  score and accuracy in binary classification evaluation.* BMC Genomics, 2020.
- J. Demšar. *Statistical Comparisons of Classifiers over Multiple Data Sets.* JMLR 7, 2006.
- M. Hubert, E. Vandervieren. *An adjusted boxplot for skewed distributions.* CSDA, 2008.
- N. Moha et al. *DECOR: A Method for the Specification and Detection of Code and Design
  Smells.* IEEE TSE 36(1), 2010.
