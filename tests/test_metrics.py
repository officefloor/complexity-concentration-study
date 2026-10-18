"""Hand-worked self-tests for the comparison-matrix math in complexity_concentration_study.metrics:
the threshold-free AUC/AP, the skew-adjusted-boxplot medcouple, the outlier rules (fitted on the
whole population they score, zeros included), the signal registries and class aggregation.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import extract, halstead, metrics


def test_auc_perfect_separation():
    vals = {"a": 10, "b": 9, "c": 2, "d": 1}
    auc, ap, ng, n = metrics.auc_ap(vals, {"a", "b"}, set(vals))
    assert auc == 1.0 and ap == 1.0 and (ng, n) == (2, 4), (auc, ap, ng, n)


def test_auc_reversed_is_zero():
    vals = {"a": 1, "b": 2, "c": 9, "d": 10}
    auc, _, _, _ = metrics.auc_ap(vals, {"a", "b"}, set(vals))
    assert auc == 0.0, auc


def test_auc_all_ties_is_half():
    vals = {k: 5 for k in "abcd"}
    auc, _, _, _ = metrics.auc_ap(vals, {"a", "b"}, set(vals))
    assert abs(auc - 0.5) < 1e-9, auc


def test_auc_no_gods_is_none_but_counts_are_kept():
    vals = {"a": 1, "b": 2}
    auc, ap, ng, n = metrics.auc_ap(vals, set(), set(vals))
    assert auc is None and ap is None and (ng, n) == (0, 2)


def test_medcouple_symmetric_near_zero():
    assert abs(metrics._medcouple([1, 2, 3, 4, 5, 6, 7, 8, 9])) <= 0.01


def test_medcouple_right_skew_positive():
    assert metrics._medcouple(sorted([1, 1, 1, 1, 2, 2, 3, 5, 20, 100])) > 0


def test_signal_value_reads_the_field():
    r = {"cc": 4, "cognitive": 5, "nloc": 12}
    assert metrics.signal_value("cc", r) == 4
    assert metrics.signal_value("missing", r) == 0


def test_concentration_even_vs_piled():
    even, conc = metrics.entropy_norm([5, 5, 5, 5]), metrics.entropy_norm([100, 1, 1, 1])
    assert even > 0.99 and conc < 0.5, (even, conc)
    assert metrics.gini([5, 5, 5, 5]) < 1e-9 and metrics.gini([0, 0, 0, 10]) > 0.5


def test_mad_z_flags_the_extreme_with_zeros_in_the_population():
    # mostly-zero signal (e.g. params / cognitive): zeros are part of the fit, the MAD is 0,
    # the mean-absolute-deviation fallback applies, and the single big value is still flagged
    vmap = {f"f{i}": 0 for i in range(30)}
    vmap.update({"g1": 1, "g2": 1, "big": 40})
    out = metrics.mad_z(vmap)
    assert "big" in out and "g1" not in out and "f0" not in out, out


def test_rules_fit_on_what_they_are_given_not_positives_only():
    # a population that is half zeros: Tukey's fence is Q3 + 1.5 IQR over ALL values
    vmap = {f"z{i}": 0 for i in range(10)}
    vmap.update({f"p{i}": v for i, v in enumerate([1, 1, 2, 2, 3, 3, 4, 4, 5, 60])})
    assert metrics.iqr_fence(vmap) == {"p9"}


def test_all_algorithms_return_sets_and_have_declared_constants():
    vmap = {f"f{i}": i + 1 for i in range(50)}
    for name, algo in metrics.ALGORITHMS.items():
        assert isinstance(algo(vmap), set), name
    assert set(metrics.ALGORITHM_CONSTANTS) == set(metrics.ALGORITHMS)
    assert metrics.ALGORITHM_CONSTANTS["mad_z"]["cut"] == extract.OUTLIER_Z == 3.5


def test_zscore_control_masks_the_second_extreme_but_mad_z_does_not():
    # a spread body (1..40) so the MAD is non-zero, one huge value and one merely big one:
    # the huge value inflates the SD so the classic z-score misses `big`; the MAD does not move
    vmap = {f"f{i}": i for i in range(1, 41)}
    vmap.update({"huge": 1000, "big": 100})
    assert "big" not in metrics.zscore_classic(vmap) and "huge" in metrics.zscore_classic(vmap)
    assert {"big", "huge"} <= metrics.mad_z(vmap)


def test_signal_registries():
    for f in ("cc", "cognitive", "nloc", "tokens", "params", "nesting",
              "cyc_density", "exit_points", "hvol", "mi"):
        assert f in metrics.METHOD_SIGNALS, f
    assert metrics.METHOD_SIGNALS == extract.COMPLEXITY_FIELDS
    assert "nom" in metrics.CLASS_SIGNALS and "nom" not in metrics.METHOD_SIGNALS
    for base in extract.COMPLEXITY_FIELDS:
        for agg in ("sum", "mean", "max"):
            assert f"{base}_{agg}" in metrics.CLASS_SIGNALS, (base, agg)
    assert len(metrics.CLASS_SIGNALS) == 3 * len(extract.COMPLEXITY_FIELDS) + 1
    assert "cc_sum" in metrics.CLASS_SIGNALS            # == WMC, the size reference


def _rec(file, **kw):
    r = {b: 0 for b in extract.COMPLEXITY_FIELDS}
    r.update({"file": file, "name": "f", "start_line": 1, "end_line": 1}, **kw)
    return r


def test_class_aggregation_is_sum_mean_max_and_restricted_to_the_universe():
    funcs = {("f.py", "a@1"): _rec("f.py", cc=2), ("f.py", "b@5"): _rec("f.py", cc=8),
             ("g.py", "c@1"): _rec("g.py", cc=0)}              # cc 0: outside the method universe
    mx = metrics.matrix_outliers(funcs, {"f.py": 10, "g.py": 0})
    v = mx["class"]["_vals"]
    assert v["cc_sum"]["f.py"] == 10 and v["cc_mean"]["f.py"] == 5 and v["cc_max"]["f.py"] == 8
    assert v["nom"]["f.py"] == 2
    assert mx["method"]["universe"] == {("f.py", "a@1"), ("f.py", "b@5")}
    assert mx["class"]["universe"] == {"f.py"}
    for algo_sets in (mx["method"]["cc"], mx["class"]["cc_sum"]):
        for name, flagged in algo_sets.items():
            assert ("g.py", "c@1") not in flagged and "g.py" not in flagged, name


def test_signal_families_partition_every_signal_and_diagnostics_are_recorded():
    for lvl, pool in (("method", metrics.METHOD_SIGNALS), ("class", metrics.CLASS_SIGNALS)):
        fams = metrics.FAMILIES[lvl]
        covered = [s for sigs in fams.values() for s in sigs]
        assert sorted(covered) == sorted(pool), (lvl, set(pool) ^ set(covered))
        assert all(metrics.family_of(lvl, s) for s in pool)
    assert metrics.family_of("class", "nloc_sum") == "size"
    assert metrics.family_of("class", "cc_mean") == "density"
    assert metrics.family_of("method", "cyc_density") == "density"
    funcs = {("f.py", f"a@{i}"): _rec("f.py", cc=1, params=0, start_line=i) for i in range(1, 12)}
    funcs[("f.py", "z@99")] = _rec("f.py", cc=30, params=0, start_line=99)
    mx = metrics.matrix_outliers(funcs, {"f.py": 41})
    d = mx["method"]["_diag"]
    assert d["cc"]["scale"] == "mean_ad" and d["cc"]["zero_frac"] == 0.0     # MAD of cc is 0
    assert d["params"]["scale"] == "constant" and d["params"]["zero_frac"] == 1.0


def test_halstead_volume_grows_with_vocabulary_and_is_zero_when_trivial():
    assert halstead.halstead_volume("") == 0.0
    assert halstead.halstead_volume("x") == 0.0               # single token, vocab < 2
    small = halstead.halstead_volume("a = b + c;")
    big = halstead.halstead_volume("result = alpha + beta * gamma - delta / epsilon + zeta;")
    assert 0 < small < big, (small, big)


def test_maintainability_burden_is_bounded_and_rises_with_complexity():
    simple = extract.maintainability_burden(hvol=50, cc=1, nloc=5)
    gnarly = extract.maintainability_burden(hvol=5000, cc=40, nloc=400)
    assert 0.0 <= simple <= 100.0 and 0.0 <= gnarly <= 100.0
    assert gnarly > simple, (simple, gnarly)
    assert extract.maintainability_burden(hvol=0, cc=5, nloc=10) == 0.0   # degenerate body


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
