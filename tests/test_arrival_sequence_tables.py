"""Report tables preserve native-source contrasts and distinct uncertainty measures."""

# pyright: basic
from copy import deepcopy

import pytest

from analysis.arrival.model_sequence_tables import comparison_tables, prediction_strata


def test_fixed_distance_boundaries_and_site_support_preserve_every_record():
    rows = [
        {"distance_km": d, "seen_site": i % 2 == 0} for i, d in enumerate([499, 500, 2000, 5000])
    ]
    strata = dict(prediction_strata(rows))
    assert [
        len(strata[s])
        for s in [
            "under-500km",
            "500-to-2000km",
            "2000-to-5000km",
            "5000km-and-above",
        ]
    ] == [1, 1, 1, 1]
    assert sum(len(strata[s]) for s in ["seen-geographic-site", "unseen-geographic-site"]) == 4


def model(target, kind, scores, error):
    events = [
        {
            "event_id": f"e{i}",
            "sequence": f"s{i}",
            "records": i + 1,
            "target": target,
            "cohort_sha256": "a" * 64,
            "record_membership_sha256": str(i + 1) * 64,
            "normalized_event_score": score,
            "joint_log_predictive": score * (i + 1),
            "precision_passed": True,
        }
        for i, score in enumerate(scores)
    ]
    rows = [
        {
            "record_id": f"r{i}{j}",
            "event_id": f"e{i}",
            "sequence": f"s{i}",
            "distance_km": 3000,
            "seen_site": True,
            "observed_native_minutes": 10,
            "q05": 5,
            "q25": 8,
            "q50": 10,
            "q75": 12,
            "q95": 15,
            "pit": 0.3 + 0.2 * i,
        }
        for i in range(2)
        for j in range(i + 1)
    ]
    return {
        "events": events,
        "predictions": rows,
        "summary": {
            "records": 3,
            "events": 2,
            "equal_event_score": sum(scores) / 2,
            "row_weighted_joint_score": sum(e["joint_log_predictive"] for e in events) / 3,
            "monte_carlo_used": kind == "event",
            "monte_carlo_standard_error": error,
            "mean_numerical_error_estimate": 1e-9,
            "cohort_sha256": "a" * 64,
        },
    }


def test_paired_comparison_is_within_source_and_equal_event_not_record_weighted():
    models = {
        (t, k): model(t, k, s, e)
        for t, k, s, e in [
            ("T-OBS", "pooled", [-3, -8], 0),
            ("T-OBS", "event", [-2, -4], 0.001),
            ("T-CAL", "pooled", [-20, -20], 0),
            ("T-CAL", "event", [-19, -19], 0.002),
        ]
    }
    before = deepcopy(models)
    tables = comparison_tables(models, bootstrap_replicates=100)
    assert models == before
    pairs = {r["target"]: r for r in tables["paired-score-differences"]}
    assert len(pairs) == 2 and pairs["T-OBS"]["paired_mean_difference"] == 2.5
    assert pairs["T-CAL"]["paired_mean_difference"] == 1
    assert pairs["T-OBS"]["paired_numerical_mcse"] == 0.001
    assert pairs["T-CAL"]["paired_deterministic_error_estimate_sum"] == pytest.approx(2e-9)
    rows = tables["model-scores"]
    assert rows[0]["equal_event_score"] == -5.5
    assert rows[0]["row_weighted_joint_score_secondary"] == pytest.approx(-19 / 3)
    assert len(tables["sequence-score-influence"]) == 4
