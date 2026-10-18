"""Hand-worked self-tests for the comparison-matrix math in complexity_concentration_study.metrics:
the threshold-free AUC/AP, the skew-adjusted-boxplot medcouple, the signal value, the
outlier algorithms, and the concentration measures. Every expected value is derived by hand.
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


def test_auc_no_gods_is_none():
    vals = {"a": 1, "b": 2}
    auc, ap, _, _ = metrics.auc_ap(vals, set(), set(vals))
    assert auc is None and ap is None


def test_medcouple_symmetric_near_zero():
    assert abs(metrics._medcouple([1, 2, 3, 4, 5, 6, 7, 8, 9])) <= 0.01


def test_medcouple_right_skew_positive():
    assert metrics._medcouple(sorted([1, 1, 1, 1, 2, 2, 3, 5, 20, 100])) > 0


def test_signal_value_reads_the_field():
    r = {"cc": 4, "cognitive": 5, "nloc": 12}
    assert metrics.signal_value("cc", r) == 4
    assert metrics.signal_value("cognitive", r) == 5
    assert metrics.signal_value("nloc", r) == 12
    assert metrics.signal_value("missing", r) == 0


def test_concentration_even_vs_piled():
    even, conc = metrics.entropy_norm([5, 5, 5, 5]), metrics.entropy_norm([100, 1, 1, 1])
    assert even > 0.99 and conc < 0.5, (even, conc)
    assert metrics.gini([5, 5, 5, 5]) < 1e-9 and metrics.gini([0, 0, 0, 10]) > 0.5


def test_mad_z_flags_the_extreme():
    vmap = {f"f{i}": 1 for i in range(20)}
    vmap["big"] = 100
    assert "big" in metrics.mad_z(vmap)


def test_all_algorithms_return_sets():
    vmap = {f"f{i}": i + 1 for i in range(50)}
    for name, algo in metrics.ALGORITHMS.items():
        assert isinstance(algo(vmap), set), name


def test_signal_registries():
    # method signals are the raw per-function complexity fields, including the derived ones
    for f in ("cc", "cognitive", "nloc", "tokens", "params", "nesting",
              "cyc_density", "exit_points", "hvol", "mi"):
        assert f in metrics.METHOD_SIGNALS, f
    assert metrics.METHOD_SIGNALS == extract.COMPLEXITY_FIELDS
    # class signals are each base measure aggregated sum/mean/max, plus nom; no flow signal
    assert "nom" in metrics.CLASS_SIGNALS and "nom" not in metrics.METHOD_SIGNALS
    for base in extract.COMPLEXITY_FIELDS:
        for agg in ("sum", "mean", "max"):
            assert f"{base}_{agg}" in metrics.CLASS_SIGNALS, (base, agg)
    assert len(metrics.CLASS_SIGNALS) == 3 * len(extract.COMPLEXITY_FIELDS) + 1
    assert "cc_sum" in metrics.CLASS_SIGNALS            # == WMC, the size reference
    assert not any(s.startswith("div") for s in metrics.CLASS_SIGNALS)


def test_class_aggregation_is_sum_mean_max():
    # one file, two methods with cc 2 and 8: sum=10, mean=5, max=8; nom=2
    funcs = {("f.py", "a"): {b: 0 for b in extract.COMPLEXITY_FIELDS},
             ("f.py", "b"): {b: 0 for b in extract.COMPLEXITY_FIELDS}}
    funcs[("f.py", "a")]["cc"] = 2
    funcs[("f.py", "b")]["cc"] = 8
    mx = metrics.matrix_outliers(funcs, {"f.py": 10})
    v = mx["class"]["_vals"]
    assert v["cc_sum"]["f.py"] == 10 and v["cc_mean"]["f.py"] == 5 and v["cc_max"]["f.py"] == 8
    assert v["nom"]["f.py"] == 2


def test_halstead_volume_grows_with_vocabulary_and_is_zero_when_trivial():
    assert halstead.halstead_volume("") == 0.0
    assert halstead.halstead_volume("x") == 0.0               # single token, vocab < 2
    small = halstead.halstead_volume("a = b + c;")
    big = halstead.halstead_volume("result = alpha + beta * gamma - delta / epsilon + zeta;")
    assert 0 < small < big, (small, big)


def test_maintainability_burden_is_bounded_and_rises_with_complexity():
    # higher Halstead volume, CC and length => lower MI => higher burden; always within [0,100]
    simple = extract.maintainability_burden(hvol=50, cc=1, nloc=5)
    gnarly = extract.maintainability_burden(hvol=5000, cc=40, nloc=400)
    assert 0.0 <= simple <= 100.0 and 0.0 <= gnarly <= 100.0
    assert gnarly > simple, (simple, gnarly)
    assert extract.maintainability_burden(hvol=0, cc=5, nloc=10) == 0.0   # degenerate body


if __name__ == "__main__":
    ok = True
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            ok = False
            print(f"  [FAIL] {fn.__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
