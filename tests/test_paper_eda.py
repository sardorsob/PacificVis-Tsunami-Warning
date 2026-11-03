"""Scientific invariants for descriptive EDA; no outcome or model assumptions."""

import numpy as np
import pytest

from analysis.arrival.eda import (
    bootstrap_median,
    distance_km,
    draw_split,
    frame_targets,
    median_polish,
    summarize,
)


def test_metadata_split_is_deterministic_and_forced_without_target_fields() -> None:
    data = [{"event_id": f"e{i}", "region": "r", "era": "early"} for i in range(9)]
    a = draw_split(data, 4, forced=("e0", "e1"))
    assert len(a["exploration"]) == 6 and len(a["confirmation"]) == 3
    assert {"e0", "e1"} <= set(a["exploration"])
    assert a == draw_split(list(reversed(data)), 4, forced=("e0", "e1"))
    assert a == draw_split(
        [r | {"irrelevant_outcome": "changed"} for r in data], 4, forced=("e0", "e1")
    )


def test_distance_handles_antimeridian_and_known_equator_pair() -> None:
    assert distance_km(0, 0, 1, 0) == pytest.approx(111.31949, rel=1e-6)
    assert distance_km(179, 0, -179, 0) == pytest.approx(222.63898, rel=1e-6)
    with pytest.raises(ValueError):
        distance_km(0, 91, 1, 0)


def test_median_polish_recovers_known_additive_effects() -> None:
    values = np.array([[8.0, 10.0, 12.0], [10.0, 12.0, 14.0], [12.0, 14.0, 16.0]])
    overall, events, sites, residual = median_polish(values)
    assert overall == pytest.approx(12)
    assert events.tolist() == pytest.approx([-2, 0, 2])
    assert sites.tolist() == pytest.approx([-2, 0, 2])
    assert np.max(np.abs(residual)) < 1e-8


def test_event_bootstrap_resamples_events_and_is_seeded() -> None:
    rows = [{"event_id": "a", "value": 0.0}] * 20 + [{"event_id": "b", "value": 10.0}]
    assert bootstrap_median(rows, "value", 100, 3) == bootstrap_median(rows, "value", 100, 3)
    low, high = bootstrap_median(rows, "value", 100, 3)
    assert low == 0 and high == 10


def test_summary_retains_nonfinite_accounting_and_small_samples() -> None:
    s = summarize([0.0, 1.0, float("nan"), float("inf")])
    assert s["n"] == 4 and s["finite_n"] == 2 and s["median"] == 0.5


def test_target_assembly_never_uses_unsupported_clocks_to_change_tcal() -> None:
    rows = [
        {
            "source_record_id": "r",
            "event_id": "dev",
            "physical_site_id": "s",
            "estimated_minus_observed_seconds": "-60",
            "observed_utc": "bad",
            "estimated_utc": "also bad",
        }
    ]
    sites = [{"physical_site_id": "s", "latitude": "0", "longitude": "1"}]
    meta = [{"event_id": "dev", "longitude": "0", "latitude": "0", "era": "early"}]
    a = frame_targets(rows, sites, meta, [], "T-CAL")
    assert a[0]["target_minutes"] == -1
    b = frame_targets([rows[0] | {"observed_utc": "changed"}], sites, meta, [], "T-CAL")
    assert a[0]["target_minutes"] == b[0]["target_minutes"]
    with pytest.raises(ValueError, match="duplicate"):
        frame_targets(rows, sites + sites, meta, [], "T-CAL")


def test_clock_heaping_is_separate_from_fractional_origin_duration() -> None:
    rows = [
        {
            "source_record_id": "r",
            "event_id": "dev",
            "physical_site_id": "s",
            "duration_minutes": "0.045",
            "observed_utc": "2010-01-01T00:01:00Z",
        }
    ]
    sites = [{"physical_site_id": "s", "latitude": "0", "longitude": "1"}]
    meta = [{"event_id": "dev", "longitude": "0", "latitude": "0"}]
    result = frame_targets(rows, sites, meta, [], "T-OBS")[0]
    assert result["observed_clock_second"] == 0
    assert result["target_minutes"] == 0.045
