# Complexity concentration → god classes/methods — methodology and caveats

This note governs the comparison produced by `study.analyse` (the `matrix` block in each
`study.json` row) and rendered by `paper/god_complexity.py`. It exists so the comparison is
read honestly rather than as a fishing expedition.

## The question

This is **identification**, not prediction: at a single checkout, does a relative
**complexity-concentration spike** mark the same classes/methods that a textbook god-class
definition marks? We vary three things and hold the repo fixed:

- **signal** — each per-unit complexity definition: `cc` (cyclomatic), `cognitive`
  (Campbell), `nloc`, `tokens`, `params`, `nesting`; plus `nom` (methods per class) at class
  level. Class-level value of a signal is the per-file sum of its per-method values.
- **algorithm** — the relative outlier rule that turns a signal into a flagged set: `mad_z`
  (Iglewicz–Hoaglin), `double_mad`, `iqr` (Tukey), `adj_boxplot` (Hubert–Vandervieren),
  `evt_pot` (peaks-over-threshold GPD), `pct_top1`, `zscore` (classic, parametric control).
- **definition (oracle)** — `WMC≥47`, the PMD design panel, and the CK cohesion/coupling
  definitions (`ck_LCOM`, `ck_TCClow`, `ck_CBOhigh`) plus an approximate DECOR `decor_blob`;
  at method level `CC≥14`, `cognitive≥15`, `nesting≥5`, `nloc≥50`, `params≥5`.

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

Some oracles are a signal restated as a threshold, so a matching signal scoring AUC≈1 on them
is a **tautology, not a result**: `wmc47` is Sum(`cc`) at class level, and at method level
`cc14`/`cognitive15`/`loc50`/`params5`/`nesting5` ARE the signal thresholded. The reporter
lists those separately and never lets them drive the headline. The real god-class targets are
the composite tool definitions `pmd_GodClass` and `decor_blob`; CK cohesion/coupling and the
PMD size panel are supporting, tool-derived (Java-only) targets.

## Aggregation and the explore/confirm split

Per the standard for comparing many methods over many data sets (Demšar 2006): the Friedman
block is the **repository**. Within a repo, a signal's AUC (or an algorithm's MCC) is first
averaged over the definitions of the group it has, then signals are ranked per repo, the ranks
averaged, and Friedman + the Nemenyi critical difference read next to the plain mean.

`god_complexity.py` splits the usable repositories (the headline substance floor) into an
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
6. **Cognitive complexity** is ImpactGate's faithful approximation, not the certified
   SonarSource value; fine for a relative spike, read as an estimate.
7. **Method level needs an independent oracle.** Every method-level definition in the current
   run is one of the signals thresholded, so method-level AUC≈1 is tautological. An independent
   method oracle (e.g. PMD's own `CyclomaticComplexity` / `NPathComplexity` /
   `ExcessiveMethodLength` / `CognitiveComplexity`) is the first thing to add for a real
   method-level result.

## References

- D. Chicco, G. Jurman. *The advantages of the Matthews correlation coefficient (MCC) over F1
  score and accuracy in binary classification evaluation.* BMC Genomics, 2020.
- J. Demšar. *Statistical Comparisons of Classifiers over Multiple Data Sets.* JMLR 7, 2006.
- M. Hubert, E. Vandervieren. *An adjusted boxplot for skewed distributions.* CSDA, 2008.
- N. Moha et al. *DECOR: A Method for the Specification and Detection of Code and Design
  Smells.* IEEE TSE 36(1), 2010.
