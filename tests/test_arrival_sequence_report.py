"""Reporting weights, sequence bootstrap and frozen prediction membership."""

# pyright: basic
import numpy as np
import pytest

from analysis.arrival.model_data import sequence_folds
from analysis.arrival.model_sequence_report import (
    event_weighted_pit_curve,
    predictive_statistics,
    validate_predictions,
)
from tests.test_arrival_models import tiny_lane


def predictions():
    return [
        {
            "record_id": str(i),
            "event_id": e,
            "sequence": g,
            "distance_km": 100.0,
            "observed_native_minutes": y,
            "seen_site": True,
            "pit": pit,
            "q05": 0.1,
            "q25": 1.0,
            "q50": 2.0,
            "q75": 3.0,
            "q95": 4.0,
        }
        for i, (e, g, y, pit) in enumerate(
            [("a", "x", 1.0, 0.1), ("a", "x", 1.0, 0.2), ("b", "x", 5.0, 0.8), ("c", "y", 2.0, 0.9)]
        )
    ]


def test_predictive_statistics_keep_equal_event_and_row_weights_distinct():
    d = predictive_statistics(predictions())
    assert d["records"] == 4 and d["events"] == 3 and d["sequences"] == 2
    assert d["record_coverage90"] == 0.75
    assert d["equal_event_coverage90"] == pytest.approx(2 / 3)
    assert d["record_coverage50"] == 0.75
    assert d["median_absolute_error_minutes"] == 1
    assert d["equal_event_mean_absolute_error_minutes"] == pytest.approx(4 / 3)
    assert d["record_mean_absolute_error_minutes"] == 1.25
    assert d["median_width90_minutes"] == 3.9
    assert d["coverage90_numerical_ambiguity_not_assessed_records"] == 4


def test_pit_curve_and_whole_sequence_bootstrap_match_independent_ratio_oracle():
    grid = np.array([0.0, 0.5, 1.0])
    out = event_weighted_pit_curve(predictions(), grid=grid, seed=39, replicates=200)
    np.testing.assert_allclose([r["equal_event_cdf"] for r in out], [0, 1 / 3, 1])
    # Sequence x has two events, y one. Resample sequence totals and event counts together.
    sample = np.random.default_rng(39).integers(0, 2, size=(200, 2))
    numerator = np.array([1.0, 0.0])[sample].sum(axis=1)
    denominator = np.array([2.0, 1.0])[sample].sum(axis=1)
    curves = numerator / denominator
    assert out[1]["bootstrap_pointwise_q025"] == np.quantile(curves, 0.025)
    assert out[1]["bootstrap_pointwise_q975"] == np.quantile(curves, 0.975)
    totals = np.array([[0, 0.5, 1, 2, 2, 2], [0, 0, 0, 0, 1, 1]])
    all_jumps = totals[sample].sum(axis=1) / denominator[:, None]
    empirical = (totals[0] + totals[1]) / 3
    expected = np.quantile(abs(all_jumps - empirical).max(axis=1), 0.95)
    assert out[1]["bootstrap_supnorm_radius95"] == expected


def test_pit_bootstrap_is_qualified_for_single_sequence():
    rows = predictions()[:3]
    out = event_weighted_pit_curve(rows, seed=39, replicates=100)
    assert all(r["bootstrap_pointwise_q025"] == "insufficient_sequences" for r in out)


def test_prediction_membership_response_and_site_support_are_verified():
    lane = tiny_lane()
    rows = []
    for fold in sequence_folds(lane):
        for i, seen in zip(fold.test, fold.seen_site, strict=True):
            rows.append(
                {
                    **predictions()[0],
                    "record_id": lane.record_ids[i],
                    "event_id": lane.event_ids[i],
                    "sequence": fold.sequence_id,
                    "distance_km": lane.distance_km[i],
                    "observed_native_minutes": lane.y[i],
                    "seen_site": bool(seen),
                }
            )
    validate_predictions(lane, rows)
    for key, value in [
        ("record_id", "wrong"),
        ("distance_km", 999.0),
        ("observed_native_minutes", 999.0),
        ("seen_site", False),
        ("sequence", "wrong"),
        ("q95", -999.0),
        ("q05", 0.0),
        ("target", "T-CAL"),
    ]:
        changed = [dict(r) for r in rows]
        changed[0][key] = value
        with pytest.raises(ValueError):
            validate_predictions(lane, changed)
    with pytest.raises(ValueError):
        validate_predictions(lane, rows[:-1])


def test_supremum_cannot_disappear_between_plotting_grid_points():
    first, second = [dict(r) for r in predictions()[:2]]
    first.update(event_id="a", sequence="x", pit=0.101)
    second.update(event_id="b", sequence="y", pit=0.109)
    curve = event_weighted_pit_curve([first, second], seed=39, replicates=200)
    assert all(r["bootstrap_supnorm_radius95"] == 0.5 for r in curve)
    assert curve[10]["equal_event_cdf"] == 0 and curve[11]["equal_event_cdf"] == 1
