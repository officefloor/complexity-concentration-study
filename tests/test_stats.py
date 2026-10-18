"""The analysis statistics, checked against published values (Demsar 2006) and hand-worked
confusion counts."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import stats


def test_nemenyi_quantiles_match_demsar_table_5():
    # Demsar 2006, Table 5(a): q_0.05 for k = 2..10 (already divided by sqrt 2)
    table = {2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102,
             10: 3.164}
    for k, q in table.items():
        assert abs(stats.studentized_range_q(k) / math.sqrt(2) - q) < 0.002, k
    # beyond any short table: the value for 31 methods is computed, not a fallback
    assert 3.70 < stats.studentized_range_q(31) / math.sqrt(2) < 3.82


def test_friedman_iman_davenport_matches_demsar_worked_example():
    # Demsar 2006, Sec. 3.2.2: 4 classifiers over 14 data sets with these average ranks give
    # chi2_F = 9.28, F_F = 3.69 and (alpha=0.05) CD = 1.25
    mr = {"C4.5": 3.143, "C4.5+m": 2.000, "C4.5+cf": 2.893, "C4.5+m+cf": 1.964}
    r = stats.friedman_from_mean_ranks(mr, 14)
    assert abs(r["chi2"] - 9.28) < 0.01 and abs(r["F"] - 3.69) < 0.01, r
    assert abs(r["cd_05"] - 1.25) < 0.01
    assert 0.01 < r["p_F"] < 0.03                     # F(3, 39) critical 2.85 at 0.05


def test_exact_survival_functions():
    assert abs(stats.chi2_sf(3.841, 1) - 0.05) < 1e-3
    assert abs(stats.chi2_sf(16.919, 9) - 0.05) < 1e-3
    assert abs(stats.f_sf(4.26, 1, 4) - 0.108) < 2e-3
    assert stats.chi2_sf(0, 3) == 1.0 and stats.f_sf(0, 2, 10) == 1.0


def test_friedman_over_score_rows_ranks_ties_and_rejects_ragged_blocks():
    rows = [{"a": 0.9, "b": 0.8, "c": 0.7}] * 10 + [{"a": 0.5, "b": 0.5, "c": 0.9}] * 2
    r = stats.friedman(rows)
    assert r["n"] == 12 and r["k"] == 3
    assert r["mean_rank"]["a"] < r["mean_rank"]["c"]            # a is better (rank 1 = best)
    assert stats.ranks({"a": 1, "b": 1, "c": 0}) == {"a": 1.5, "b": 1.5, "c": 3}
    assert stats.friedman([{"a": 1}]) is None
    try:
        stats.friedman([{"a": 1, "b": 2}, {"a": 1, "c": 2}])
        assert False, "ragged blocks must be rejected"
    except ValueError:
        pass


def test_pooled_confusion_keeps_blocks_with_no_god():
    cells = [{"n_univ": 10, "n_out": 2, "n_overlap": 1, "n_god_univ": 1},
             {"n_univ": 10, "n_out": 1, "n_overlap": 0, "n_god_univ": 0},   # a god-free repo
             None, {"n_univ": 0}]                                            # ignored
    p = stats.pooled_confusion(cells)
    assert (p["n_blocks"], p["n_blocks_no_god"], p["fp_in_no_god"]) == (2, 1, 1)
    assert (p["tp"], p["fp"], p["fn"], p["tn"]) == (1, 2, 0, 17)
    assert abs(p["precision"] - 1 / 3) < 1e-9 and p["recall"] == 1.0
    assert abs(p["fpr"] - 2 / 19) < 1e-9
    assert abs(p["mcc"] - stats.mcc(1, 2, 0, 17)) < 1e-12
    # dropping the god-free block (the earlier draft's behaviour) inflates precision
    assert stats.pooled_confusion(cells[:1])["precision"] == 0.5


def test_pooled_auc_standardised_differs_from_raw_across_scales():
    # two repositories on different raw scales: in each, the god is its own top unit. Pooled
    # RAW, repo B's ordinary units outrank repo A's god; pooled STANDARDISED, both gods lead.
    a = ([1, 1, 2, 2, 3, 3, 4, 10], [7])
    b = ([100, 100, 200, 200, 300, 300, 400, 1000], [7])
    raw = stats.pooled_auc([a, b])
    rel = stats.pooled_auc([a, b], standardise=True)
    assert raw["n_pos"] == 2 and raw["n_neg"] == 14 and raw["n_blocks"] == 2
    assert rel["auc"] == 1.0 and raw["auc"] < 1.0, (raw, rel)
    # a god-free block is kept: its units are negatives
    z = stats.pooled_auc([a, b, ([5, 5, 5, 50], [])], standardise=True)
    assert z["n_blocks_no_god"] == 1 and z["n_neg"] == 18
    assert stats.pooled_auc([([1, 2], [])])["auc"] is None
    assert stats.auc([2, 2], [1, 2]) == 0.75


def test_bootstrap_mean_over_repositories():
    r = stats.bootstrap_mean([0.9, 0.8, 0.7, 0.6, 0.5, None])
    assert r["n"] == 5 and abs(r["mean"] - 0.7) < 1e-12 and r["lo"] <= 0.7 <= r["hi"]
    assert stats.bootstrap_mean([0.5, 0.6]) is None
    assert stats.bootstrap_mean([0.9] * 10)["lo"] == 0.9


def test_assign_halves_is_stratified_and_deterministic():
    items = [(f"https://github.com/o/r{i}", ("java" if i < 30 else "go", "low" if i % 3 else "mid"))
             for i in range(60)]
    h = stats.assign_halves(items, stratum_of=lambda it: it[1], key_of=lambda it: it[0])
    assert len(h) == 60 and set(h.values()) == {"explore", "confirm"}
    for stratum in {it[1] for it in items}:
        keys = [it[0] for it in items if it[1] == stratum]
        n_ex = sum(1 for k in keys if h[k] == "explore")
        assert abs(n_ex - (len(keys) - n_ex)) <= 1, (stratum, n_ex, len(keys))
    assert h == stats.assign_halves(reversed(items), stratum_of=lambda it: it[1],
                                    key_of=lambda it: it[0])


def test_fpr_is_defined_where_mcc_is_not():
    # a god-free repository: MCC is 0 whether the rule flagged nothing or three files
    assert stats.mcc(0, 0, 0, 100) == 0.0 and stats.mcc(0, 3, 0, 97) == 0.0
    assert stats.fpr(0, 100) == 0.0 and abs(stats.fpr(3, 97) - 0.03) < 1e-12
    assert stats.fpr(0, 0) is None


def test_bootstrap_paired_is_on_the_difference_and_seeded():
    items = [(0.6 + 0.01 * i, 0.5 + 0.01 * i) for i in range(30)]   # a is always 0.1 above b
    diff = lambda its: sum(a - b for a, b in its) / len(its)
    r = stats.bootstrap_paired(items, diff, b=500, seed=1)
    assert abs(r["value"] - 0.1) < 1e-12 and abs(r["lo"] - 0.1) < 1e-9 and abs(r["hi"] - 0.1) < 1e-9
    assert r["n"] == 30 and r["n_dropped"] == 0
    # two SEPARATE intervals would overlap widely here; the paired one is tight
    assert stats.bootstrap_mean([a for a, _ in items], b=500)["hi"] > stats.bootstrap_mean([b for _, b in items], b=500)["lo"]
    assert r == stats.bootstrap_paired(items, diff, b=500, seed=1)
    assert stats.bootstrap_paired(items[:3], diff) is None
    assert stats.bootstrap_paired(items, lambda its: None) is None


def test_friedman_drops_all_tied_blocks_and_counts_them():
    informative = [{"a": 0.9, "b": 0.8, "c": 0.7}] * 10
    tied = [{"a": 0.0, "b": 0.0, "c": 0.0}] * 20                   # god-free repositories
    r = stats.friedman(informative + tied)
    assert r["n"] == 10 and r["n_tied_dropped"] == 20
    assert r == {**stats.friedman(informative), "n_tied_dropped": 20}
    assert stats.friedman(tied) is None


def test_mcc_hand_values():
    assert stats.mcc(5, 0, 0, 5) == 1.0
    assert stats.mcc(0, 5, 5, 0) == -1.0
    assert stats.mcc(0, 0, 3, 7) == 0.0                 # undefined marginal -> 0


if __name__ == "__main__":
    ok = True
    for k, fn in sorted(globals().items()):
        if k.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                ok = False
                print(f"  [FAIL] {fn.__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
