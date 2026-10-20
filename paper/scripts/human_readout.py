#!/usr/bin/env python3
"""The MLCQ human-label sub-study, read to its pre-registered plan (PLAN.md, 'The MLCQ
sub-study'), from the reviewed units extract_mlcq.py reduced.

    paper/scripts/human_readout.py [--data paper/data/mlcq.json] [--out paper/data/human.json]

The harness's analysis of results/mlcq carries no human read-out (see extract_mlcq.py: its
registry predates the human definitions' registration), so this script performs the planned read-out
with the harness's statistics and the plan's constants (analyse.PLAN):

  * definition human_blob at class level, human_method_long_method at method level, each scored
    within the units MLCQ's reviewers reviewed, rules fitted on the repository's Java units;
  * the signal chosen on the EXPLORE half among the plan's human families (class: peak and
    density; method: structure and density) by the macro mean per-repository AUC over
    repositories with >= 3 positives, exactly as analyse.Run.choose does;
  * read on CONFIRM: macro per-repository AUC, pooled AUC standardised against raw with the
    paired bootstrap, the modified-z rule at its default (3.5) against the single absolute
    cutoff that maximised the pooled MCC on explore, and the tuned z cut as a secondary;
  * the decision on the MICRO arm alone (PLAN['human']['decide_on']), with the plan's margin
    rule, min(0.10, 0.30 x the explore-half macro MCC of the relative rule), the macro MCC and
    FPR arms reported but not decided on, the AUC floor and the effective-sample gate.

Two populations of repositories are read, and both are reported:
  all   every repository with at least one reviewed unit at that level (README, 'Analysing a
        run', rule 4: a repository where the definition marks nothing is kept; its reviewed
        units are negatives). This is the plan-faithful reading and the one the paper quotes.
  pos   only repositories with at least one positive among their reviewed units: the
        population analyse.Run.block would have produced had the registry carried the human
        definitions, since it keys a block on the positive label. Reported as a sensitivity.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import metrics, stats, PLAN, BOOT  # noqa: E402
from complexity_concentration_study.analyse import (_verdict, _verdict_lower_better, _RANK,  # noqa: E402
                                                     _threshold_free_reading, _pooled_auc_diff)

DEFINITIONS = {"class": "human_blob", "method": "human_method_long_method"}
Z_CUT = metrics.ALGORITHM_CONSTANTS["mad_z"]["cut"]


def repos_for(data: dict, level: str, variant: str) -> list[tuple[dict, dict]]:
    """(row, record) for every usable repository carrying the definition under `variant`."""
    out = []
    for row in data["rows"]:
        rec = data[level].get(row["repo"])
        if not rec or not rec["units"]:
            continue
        if variant == "pos" and not any(rec["human"]):
            continue
        out.append((row, rec))
    return out


def auc_of(rec: dict, sig: str, min_pos: int | None):
    raw = rec["raw"][sig]
    pos = [v for v, g in zip(raw, rec["human"]) if g]
    neg = [v for v, g in zip(raw, rec["human"]) if not g]
    if min_pos is not None and len(pos) < min_pos:
        return None
    return stats.auc(pos, neg) if pos and neg else None


def counts(rec: dict, flagged: list[bool]) -> dict:
    tp = sum(1 for f, g in zip(flagged, rec["human"]) if f and g)
    fp = sum(1 for f, g in zip(flagged, rec["human"]) if f and not g)
    fn = sum(1 for f, g in zip(flagged, rec["human"]) if not f and g)
    tn = len(flagged) - tp - fp - fn
    return {"n_univ": len(flagged), "n_out": tp + fp, "n_overlap": tp, "n_god_univ": tp + fn,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def flags_mad(rec, sig):
    return [z >= Z_CUT for z in rec["z"][sig]]


def flags_abs(rec, sig, cut):
    return [v >= cut for v in rec["raw"][sig]]


def flags_z(rec, sig, zcut):
    return [z >= zcut for z in rec["z"][sig]]


def macro(values):
    return stats.bootstrap_mean(values, b=BOOT["b"], seed=BOOT["seed"], min_n=2)


def macro_mcc(items, sig, flag_fn) -> dict:
    cs = [counts(rec, flag_fn(rec, sig)) for _, rec in items]
    per = [stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"]) for c in cs]
    fprs = [stats.fpr(c["fp"], c["tn"]) for c in cs]
    god_free = [c for c in cs if c["n_god_univ"] == 0]
    return {"macro": macro(per), "micro": stats.pooled_confusion(cs), "macro_fpr": macro(fprs),
            "n_repos": len(cs),
            "god_free": {"n_repos": len(god_free),
                         "mean_flags": (sum(c["n_out"] for c in god_free) / len(god_free)) if god_free else None},
            "flag_share_reviewed": (sum(c["n_out"] for c in cs) / sum(c["n_univ"] for c in cs))
            if cs else None}


def decision(items, sig, fn_rel, fn_abs, auc_c, n_auc_repos, explore_level, arms, p) -> dict:
    d = PLAN["decision"]
    pairs = [(counts(rec, fn_rel(rec, sig)), counts(rec, fn_abs(rec, sig))) for _, rec in items]
    pairs_pos = [(a, b) for a, b in pairs if a["n_god_univ"] > 0]
    m = lambda c: stats.mcc(c["tp"], c["fp"], c["fn"], c["tn"])

    def macro_diff(its):
        return sum(m(a) - m(b) for a, b in its) / len(its)

    def micro_diff(its):
        pa = stats.pooled_confusion([a for a, _ in its])["mcc"]
        pb = stats.pooled_confusion([b for _, b in its])["mcc"]
        return None if pa is None or pb is None else pa - pb

    def fpr_diff(its):
        ds = [(stats.fpr(a["fp"], a["tn"]), stats.fpr(b["fp"], b["tn"])) for a, b in its]
        ds = [x - y for x, y in ds if x is not None and y is not None]
        return sum(ds) / len(ds) if ds else None

    bs = {"macro_mcc": stats.bootstrap_paired(pairs_pos, macro_diff, **BOOT),
          "micro_mcc": stats.bootstrap_paired(pairs, micro_diff, **BOOT),
          "macro_fpr": stats.bootstrap_paired(pairs, fpr_diff, **BOOT)}
    ceiling = d["noninferiority_margin"]
    scaled = d["margin_fraction_of_explore_level"] * explore_level if explore_level is not None else None
    margin = min(ceiling, scaled) if scaled is not None else ceiling
    v = {"macro_mcc": _verdict(bs["macro_mcc"], margin), "micro_mcc": _verdict(bs["micro_mcc"], margin),
         "macro_fpr": _verdict_lower_better(bs["macro_fpr"], d["fpr_margin"])}
    decided = {k: v[k] for k in arms}
    overall = min(decided.values(), key=lambda x: _RANK[x])
    auc_ok = bool(auc_c) and auc_c["lo"] >= d["auc_floor"]
    powered = n_auc_repos >= d["min_confirm_repos_auc"] and len(pairs) >= d["min_confirm_repos_mcc"]
    p(f"   DECISION (pre-registered, human: micro arm; paired bootstrap over {len(pairs)} confirm "
      f"repositories, {len(pairs_pos)} with >= 1 positive; MCC margin {margin:.3f} = min({ceiling}, "
      f"{d['margin_fraction_of_explore_level']} x explore level {explore_level if explore_level is None else round(explore_level, 3)}); "
      f"FPR margin {d['fpr_margin']}):")
    for k, name in (("macro_mcc", "macro MCC"), ("micro_mcc", "micro MCC"), ("macro_fpr", "macro FPR")):
        b = bs[k]
        p(f"      relative - absolute, {name:10} "
          + (f"{b['value']:+.3f} [{b['lo']:+.3f}, {b['hi']:+.3f}] n={b['n']}" if b else "   n/a")
          + f"  -> {v[k]}" + ("" if k in arms else "  (reported, not decided on)"))
    p(f"      AUC floor {d['auc_floor']}: lower bound {auc_c['lo'] if auc_c else None} -> {'met' if auc_ok else 'NOT met'}")
    p(f"      effective sample: {n_auc_repos} repositories with >= {PLAN['min_positives']} positives "
      f"(need {d['min_confirm_repos_auc']}), {len(pairs)} carrying the definition (need "
      f"{d['min_confirm_repos_mcc']}) -> {'powered' if powered else 'UNDERPOWERED'}")
    notes = []
    if not powered:
        notes.append("underpowered: reported, not read as confirmatory")
    if not auc_ok:
        notes.append("AUC floor not met: the signal does not carry the definition")
    p(f"      verdict: {overall.upper()}" + "".join(f" ({n})" for n in notes))
    return {"paired": bs, "verdicts": v, "arms": list(arms), "overall": overall, "margin": margin,
            "margin_ceiling": ceiling, "explore_level": explore_level, "fpr_margin": d["fpr_margin"],
            "auc_floor_met": auc_ok, "powered": powered, "n_paired_repos": len(pairs),
            "n_paired_repos_macro": len(pairs_pos), "n_auc_repos": n_auc_repos, "notes": notes,
            "confirmatory": powered and auc_ok}


def readout(data: dict, level: str, variant: str, p) -> dict:
    oracle = DEFINITIONS[level]
    families = PLAN["human_families"][level]
    cands = [s for fam in families for s in metrics.FAMILIES[level][fam]]
    items = repos_for(data, level, variant)
    ex = [(r, rec) for r, rec in items if r["half"] == "explore"]
    co = [(r, rec) for r, rec in items if r["half"] == "confirm"]
    minp = PLAN["min_positives"]
    npos = {"explore": sum(sum(rec["human"]) for _, rec in ex), "confirm": sum(sum(rec["human"]) for _, rec in co)}
    nrev = {"explore": sum(len(rec["human"]) for _, rec in ex), "confirm": sum(len(rec["human"]) for _, rec in co)}
    nrep = {"explore": sum(1 for _, rec in ex if sum(rec["human"]) >= minp),
            "confirm": sum(1 for _, rec in co if sum(rec["human"]) >= minp)}
    p(f"\nHUMAN [{variant}]: {oracle}  [origin human, scope labelled, level {level}]")
    p(f"   repositories carrying the definition: {len(ex)} explore / {len(co)} confirm; reviewed units "
      f"{nrev['explore']} / {nrev['confirm']}; positives {npos['explore']} / {npos['confirm']}; "
      f"repositories with >= {minp} positives: {nrep['explore']} / {nrep['confirm']}")
    res = {"definition": oracle, "level": level, "variant": variant, "families": families,
           "repos_with_definition": {"explore": len(ex), "confirm": len(co)}, "reviewed_units": nrev,
           "positives": npos, "repos_with_min_positives": nrep}
    # explore choice: macro mean per-repo AUC over explore repos with >= min_positives
    scores = {}
    for s in cands:
        v = [auc_of(rec, s, minp) for _, rec in ex]
        v = [x for x in v if x is not None]
        pooled = stats.pooled_auc([(rec["z"][s], [k for k, g in enumerate(rec["human"]) if g]) for _, rec in ex])
        scores[s] = {"mean_auc": (sum(v) / len(v)) if v else None, "n": len(v),
                     "pooled_auc_standardised_explore": pooled["auc"],
                     "family": metrics.family_of(level, s)}
    ranked = sorted((s for s in scores if scores[s]["mean_auc"] is not None),
                    key=lambda s: (-scores[s]["mean_auc"], s))
    best = ranked[0] if ranked else None
    res.update({"explore_scores": scores, "chosen_signal": best})
    if best is None:
        p("   no candidate signal has a per-repository AUC on explore; nothing to read on confirm")
        return res
    p(f"   explore (macro mean per-repo AUC, {', '.join(families)} families; pooled standardised AUC beside it):")
    for s in ranked[:8]:
        sc = scores[s]
        p(f"      {s:16} {sc['mean_auc']:.3f}  (n={sc['n']}, {sc['family']}; pooled {sc['pooled_auc_standardised_explore']:.3f})")
    p(f"   -> chosen on explore: {best}")
    # confirm
    auc_c = macro([auc_of(rec, best, minp) for _, rec in co])
    std_blocks = [(rec["z"][best], [k for k, g in enumerate(rec["human"]) if g]) for _, rec in co]
    raw_blocks = [(rec["raw"][best], [k for k, g in enumerate(rec["human"]) if g]) for _, rec in co]
    pooled_std = {**stats.pooled_auc(std_blocks), "standardised": True}
    pooled_raw = stats.pooled_auc(raw_blocks)
    auc_diff = stats.bootstrap_paired(list(zip(std_blocks, raw_blocks)), _pooled_auc_diff, **BOOT)
    tf = _threshold_free_reading(auc_diff)
    rel = macro_mcc(co, best, flags_mad)
    ex_pairs = [(v, g) for _, rec in ex for v, g in zip(rec["raw"][best], rec["human"])]
    cut = stats.best_cutoff(ex_pairs)
    absd = macro_mcc(co, best, lambda rec, s: flags_abs(rec, s, cut["cut"])) if cut else None
    ex_zpairs = [(z, g) for _, rec in ex for z, g in zip(rec["z"][best], rec["human"])]
    zcut = stats.best_cutoff(ex_zpairs)
    relt = macro_mcc(co, best, lambda rec, s: flags_z(rec, s, zcut["cut"])) if zcut else None
    p(f"   CONFIRM, signal {best}:")
    p(f"      per-repo AUC, macro mean      {auc_c['mean']:.3f} [{auc_c['lo']:.3f}, {auc_c['hi']:.3f}] n={auc_c['n']}" if auc_c else "      per-repo AUC: too few repositories with >= 3 positives")
    p(f"      pooled AUC standardised       {pooled_std['auc']:.3f}  (pos {pooled_std['n_pos']}, neg {pooled_std['n_neg']}, god-free repos {pooled_std['n_blocks_no_god']})")
    p(f"      pooled AUC raw                {pooled_raw['auc']:.3f}")
    p(f"      standardised - raw            {auc_diff['value']:+.3f} [{auc_diff['lo']:+.3f}, {auc_diff['hi']:+.3f}]  -> {tf}")

    def line(name, m):
        mi = m["micro"]
        p(f"      MCC {name:44} macro {m['macro']['mean'] if m['macro'] else None} micro {mi['mcc']:.3f}  "
          f"P {mi['precision'] if mi['precision'] is None else round(mi['precision'], 3)} R {round(mi['recall'], 3)}  "
          f"flagged {mi['tp'] + mi['fp']} of {mi['n_univ']} reviewed; macro FPR "
          f"{round(m['macro_fpr']['mean'], 4) if m['macro_fpr'] else None}; FP in god-free repos {mi['fp_in_no_god']}/{mi['n_blocks_no_god']}")
    line("mad_z at default", rel)
    if absd:
        line(f"absolute {best} >= {cut['cut']:g} (tuned on explore)", absd)
    if relt:
        line(f"[secondary] modified z >= {zcut['cut']:.2f} (tuned on explore)", relt)
    res["confirm"] = {"auc_macro": auc_c, "pooled_auc_standardised": pooled_std, "pooled_auc_raw": pooled_raw,
                      "pooled_auc_difference": {"paired": auc_diff, "reading": tf},
                      "relative_default": rel,
                      "absolute_cutoff": {"cut": cut["cut"] if cut else None, "explore_mcc": cut and cut["mcc"],
                                          "confirm": absd},
                      "relative_tuned": {"z_cut": zcut["cut"] if zcut else None, "explore_mcc": zcut and zcut["mcc"],
                                         "confirm": relt}}
    # the whole-run flag rate of each rule on the chosen signal, over the reviewed units and
    # over the fitting population (where the extract kept every rule for this signal)
    rules = {}
    for rule in metrics.ALGORITHMS:
        flagged = 0
        n = 0
        fit_f = fit_n = 0
        for _, rec in items:
            fl = rec["flags"].get(best, {}).get(rule)
            if fl is None:
                continue
            flagged += sum(fl)
            n += len(fl)
            fit_f += rec["fit_flagged"][best][rule]
            fit_n += rec["n_fit"]
        if n:
            rules[rule] = {"reviewed_flag_share": flagged / n, "fit_flag_share": fit_f / fit_n}
    res["flag_rates"] = rules
    if cut:
        ex_level = [stats.mcc(**{k: counts(rec, flags_mad(rec, best))[k] for k in ("tp", "fp", "fn", "tn")})
                    for _, rec in ex if any(rec["human"])]
        explore_level = sum(ex_level) / len(ex_level) if ex_level else None
        res["decision"] = decision(co, best, flags_mad, lambda rec, s: flags_abs(rec, s, cut["cut"]),
                                   auc_c, nrep["confirm"], explore_level, PLAN["human"]["decide_on"], p)
    # every candidate's confirm read-out at the default rule and at an explore-tuned cut, so the
    # choice can be seen beside the alternatives (exploratory; the plan reads the chosen one)
    allc = {}
    for s in cands:
        r_ = macro_mcc(co, s, flags_mad)
        c_ = stats.best_cutoff([(v, g) for _, rec in ex for v, g in zip(rec["raw"][s], rec["human"])])
        a_ = macro_mcc(co, s, lambda rec, ss: flags_abs(rec, ss, c_["cut"])) if c_ else None
        pooled = stats.pooled_auc([(rec["z"][s], [k for k, g in enumerate(rec["human"]) if g]) for _, rec in co])
        allc[s] = {"pooled_auc_standardised": pooled["auc"], "mad_z_micro_mcc": r_["micro"]["mcc"],
                   "mad_z_precision": r_["micro"]["precision"], "mad_z_recall": r_["micro"]["recall"],
                   "abs_cut": c_["cut"] if c_ else None, "abs_micro_mcc": a_["micro"]["mcc"] if a_ else None}
    res["all_candidates_confirm"] = allc
    return res


def label_match(data: dict, p) -> dict:
    out = {}
    for key in ("blob", "blob_reviewed", "long_method@method", "long_method_reviewed@method"):
        lab = meas = 0
        for r in data["rows"]:
            h = (r.get("human_labels") or {}).get(key)
            if h:
                lab += h.get("labelled", 0)
                meas += h.get("measured", 0)
        out[key] = {"labelled": lab, "measured": meas, "rate": meas / lab if lab else None}
        p(f"   label match {key:28} {meas} of {lab} labelled units on a measured unit ({meas / lab if lab else 0:.3f})")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.path.join(common.DATA, "mlcq.json"))
    ap.add_argument("--out", default=os.path.join(common.DATA, "human.json"))
    args = ap.parse_args(argv)
    data = common.load_json(args.data)
    p = print
    p(f"=== human-label read-out of {data['results_dir']} (plan: analyse.PLAN; human arms "
      f"{PLAN['human']['decide_on']}) ===")
    out = {"source": args.data, "results_dir": data["results_dir"], "analysis_sha256": data["analysis_sha256"],
           "harness_commits": data["harness_commits"], "plan_human": PLAN["human"],
           "human_families": PLAN["human_families"],
           "computed_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "label_match": label_match(data, p), "readouts": {}}
    for level in ("class", "method"):
        for variant in ("all", "pos"):
            out["readouts"][f"{level}:{variant}"] = readout(data, level, variant, p)
    common.dump_json(out, args.out)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
