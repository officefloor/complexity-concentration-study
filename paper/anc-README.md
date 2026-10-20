# Ancillary data for the paper

*Complexity concentration as a god-class and god-method detector. A pre-registered test of a
scale-free outlier rule against tool definitions and human labels.* Daniel Sagenschneider, 2026.

This directory holds the data the paper is computed from, the paper's own analysis scripts, and
the key to every public repository involved. The raw per-unit data (the harness's
`study.json` and `study.units.jsonl`, several gigabytes per run) is **not** included: it
regenerates by running the harness on the sample files below, which pin every repository to its
commit. `REGENERATION.txt` maps every table, figure and inline number to the command that
produces it.

## The repositories

Everything is public and Apache-2.0 licensed unless stated.

| Repository | What it is |
|---|---|
| https://github.com/officefloor/complexity-concentration-study | **The harness and the paper.** The pre-registered plan (`PLAN.md`, tag `plan-v1`), the measurement harness (`complexity_concentration_study/`), the numbered step scripts, the samples it drew (`sample/`), the committed digests of every analysis (`analysis-hashes.txt`, `mlcq-hashes.txt`), the classpath validation's order and log, and the paper with its scripts (`paper/`). |
| https://github.com/officefloor/open-source-repository-sampler | **The sampler.** Drew the repositories (release 0.1.0, seed 2), independently of the study's code and outcomes; its `run` loop clones each one at its pinned commit for the harness. |
| https://github.com/officefloor/spring-petclinic-rest-long-degradation-test | **The companion study** (conservation of complexity under change; doi:10.5281/zenodo.23190619), whose finding motivates this one. |
| https://github.com/officefloor/concentration-divergence-study | **The follow-on study**, registered (tag `plan-v1`, 2026-10-20) before this paper's human-label read-out existed: does coupling divergence, what a unit hands on against what it receives, separate a complex leaf from a god unit among the units complexity alone flags? Its plan records what of this study it had seen. It also holds `mlcq-moved-repositories.csv`, the MLCQ repositories whose labelled commits have moved to another GitHub location, built from locations and commit SHAs alone. |
| https://github.com/officefloor/sinew-identification-study | An earlier coupling-study harness, on hold; the construct the follow-on study tests was first stated there. |
| https://zenodo.org/records/3666840 | **MLCQ 1.1** (Madeyski and Lewowski 2020), the human-labelled data set; downloaded by the harness and verified by sha256. |
| https://pmd.github.io | **PMD 7.27.0**, the GodClass, NPath, cyclomatic, cognitive and NCSS oracles. |
| https://github.com/mauricioaniche/ck | **CK 0.7.0**, the class counts the approximate DECOR Blob is composed from. |
| https://github.com/terryyin/lizard | **lizard 1.23.0**, the function parser. |

## What is here

### `main-run/` : the confirmatory seed-2 run (`results/2026-10-19` in the harness)

| File | What it is |
|---|---|
| `analysis.json`, `.sha256` | The confirmatory analysis, written once by `./step4_analyse.sh`; its digest is committed in `analysis-hashes.txt`. Every primary and secondary number of the paper's main run is read from it. |
| `analysis.exploratory.<utc>.json`, `.sha256` | The re-analysis after the classpath validation (`./step4c_reanalyse.sh`): identical numbers, the classpath bound applied; labelled exploratory because the validation ran after the confirm half was read. |
| `classpath/*.json` | The ten classpath-validation reports (`classpath-check`): PMD's findings without and with the built classpath. |
| `classpath-candidates.tsv`, `classpath-log.tsv` | The seeded order the validation worked down, and its append-only log of every attempt. |
| `halves.json` | The explore/confirm assignment, frozen before any repository was measured. |
| `oracles.json` | The definition registry: every definition's level, kind, origin, constant and ingredients; the signal families; the rules' constants; PMD's thresholds. |
| `results.csv` | One row per repository: identity, pinned commit, tier, stars, kind, counts, usability, the harness commit that measured it. |
| `run-log.jsonl` | The sampler's run log: every clone and its outcome. |
| `open-source-repository-sample*.csv`, `*.derivation.json` | The samples: every candidate drawn (usable, excluded with its reason, or error), pinned to its commit, and how each sample was drawn (command, parameters, every GitHub query and its count, the sampler's version and commit, the CSV's sha256). |
| `analysis-hashes.txt` | The committed digests of the files above. |

### `mlcq-run/` : the MLCQ human-label sub-study (`results/mlcq`)

| File | What it is |
|---|---|
| `analysis.json`, `.sha256` | The harness's analysis of the MLCQ run (the main plan re-read on MLCQ's population: PMD GodClass, NPath, DECOR Blob, Brain Method). It carries no human read-out; the paper's scripts compute that (Section 6). |
| `agreement.exploratory.<utc>.json` | The harness's step 5a output, scored over every Java class; superseded by the paper's agreement on the reviewed units. Kept as a record. |
| `halves.json`, `oracles.json`, `results.csv`, `run-log.jsonl` | As above. `oracles.json` here is the registry written at the end of the run, which does name the human definitions. |
| `mlcq-labels.csv`, `mlcq-repos.csv`, `mlcq-summary.json` | MLCQ converted by the harness (`mlcq --rule majority`): the labels (`blob`, `blob_reviewed`, `long_method`, `long_method_reviewed`, with lines), the repositories at their labelled commits as a sampler CSV, and the counts with the input's sha256. Derived from MLCQ 1.1 (CC BY 4.0). |
| `mlcq-hashes.txt` | The committed digests. |

### `paper/` : the paper's own read-outs and scripts

| File | What it is |
|---|---|
| `human.json`, `human_readout.log` | The pre-registered human-label read-out (Blob and Long Method, both populations: every repository with a reviewed unit, and only those with a positive), computed by `scripts/human_readout.py` from the reviewed units. |
| `agreement.json`, `agreement.log` | The exploratory agreement of tool definitions and the main run's rules with MLCQ's reviewers, on the reviewed units, by `scripts/agreement.py`. |
| `scripts/` | The paper's scripts: `extract_main.py`, `extract_mlcq.py` (stream the per-unit sidecars into `paper/data/*.json`), `check_extract.py` (checks the reduction against `analysis.json`), `human_readout.py`, `agreement.py`, `tables.py` (every table and inline number), `figures.py` (every figure), `common.py`. |

## Reproducing

From a clone of the harness repository:

    ./step1_setup.sh                                   # venv, pinned tools
    ./step3_run.sh --sample sample/open-source-repository-sample.csv \
                   --sample sample/open-source-repository-sample.java-supplement.csv
    ./step4_analyse.sh --results results/<date>        # analysis.json
    ./step4a_classpath_order.sh && ./step4b_classpath_check.sh && ./step4c_reanalyse.sh
    ./step5_mlcq.sh                                    # the MLCQ run
    cd paper && ./setup.sh && ./regenerate.sh && ./build.sh

`step2_sample.sh` draws fresh samples by the same method (seed 2); measuring the published sample
files instead measures exactly the repositories and commits this paper did, for as long as GitHub
serves those commits.
