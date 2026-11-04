"""Every registered OR-trigger is exercised independently of actual event outcomes."""

from analysis.arrival.timing_data_and_descriptive_statistics import Record
from analysis.arrival.timing_followup_diagnostics import branches


def frames() -> dict[str, list[Record]]:
    rows: list[Record] = [
        {
            "event_id": "a",
            "r0": float(v),
            "distance_km": 1000.0,
            "precision_seconds": p,
            "measurement_family": "coastal",
            "reference_minutes": 90.0,
            "native_distance_km": float("nan"),
        }
        for p, values in [("60", [-1, 0, 1, 0, 2]), ("unknown", [-10, 0, 10, 0, 20])]
        for v in values
    ]
    return {"T-OBS": rows, "NCEI-native-duration": rows}


def test_precision_alone_triggers_heteroskedasticity_branch() -> None:
    result, _ = branches(frames(), {"C3": {k: {} for k in frames()}}, "B5")
    assert result["T-OBS"]["triggered"]


def test_format_alone_triggers_availability_branch() -> None:
    core: Record = {
        "C3": {k: {} for k in frames()},
        "C6": {
            "tables": {
                "availability-era": [{"group": "same", "accepted_rows": 10, "availability": 0.5}],
                "availability-header_family": [
                    {"group": "a", "accepted_rows": 5, "availability": 0.0},
                    {"group": "b", "accepted_rows": 5, "availability": 1.0},
                ],
                "within-event-peak-size": [],
                "within-event-peak-presence": [],
            }
        },
    }
    result, _ = branches(frames(), core, "B7")
    assert result["NTWC-reports"]["triggered"]


def test_group_spread_influence_alone_triggers_branch() -> None:
    core: Record = {
        "C3": {k: {} for k in frames()},
        "C7": {
            k: {
                "loo": [
                    {
                        "event_id": "e",
                        "relative_change": 0.1,
                        "sign_flip": False,
                        "maximum_effect_mad_relative_change": 0.9,
                    }
                ]
            }
            for k in frames()
        },
    }
    result, _ = branches(frames(), core, "B8")
    assert result["T-OBS"]["triggered"]


def test_monotone_bins_trigger_without_near_far_departure() -> None:
    c3 = {
        "near": {"median": 0.0},
        "far": {"median": 0.0},
        "bins": [{"median": v, "finite_n": 10} for v in [0.0, 0.2, 0.4]],
    }
    core: Record = {"C3": {k: c3 for k in frames()}}
    result, _ = branches(frames(), core, "B1")
    assert result["T-OBS"]["triggered"]


def test_within_event_tier_contrast_can_trigger_source_offset_check() -> None:
    rows = [
        {
            "event_id": e,
            "target_minutes": v,
            "identity_tier": tier,
            "time_evidence_tier": "same",
            "precision_seconds": "60",
            "header_family": "same",
            "measurement_family": "NTWC",
            "physical_site_id": tier,
        }
        for e in ["a", "b", "c"]
        for tier, v in [("A", 10.0), ("B", 15.0)]
    ]
    result, _ = branches(
        {"T-OBS": rows, "NCEI-native-duration": []},
        {"C5": {"linked": {"ci_low": "unknown", "ci_high": "unknown"}}},
        "B6",
    )
    assert result["T-OBS"]["triggered"]
    assert result["T-OBS"]["scalar"] == 5


def test_frozen_availability_route_cannot_switch_to_peak_after_confirmation() -> None:
    core: Record = {
        "_routes": {"B7": {"NTWC-reports": "era"}},
        "C6": {
            "tables": {
                "availability-era": [{"accepted_rows": 10, "availability": 0.5}],
                "availability-header_family": [{"accepted_rows": 10, "availability": 0.5}],
                "within-event-peak-size": [{"native_median_difference": 10.0}],
                "within-event-peak-presence": [],
            }
        },
    }
    result, _ = branches(frames(), core, "B7")
    assert not result["NTWC-reports"]["triggered"]


def test_zero_baseline_does_not_hide_finite_group_influence() -> None:
    core: Record = {
        "C7": {
            k: {
                "loo": [
                    {
                        "event_id": "e",
                        "relative_change": float("nan"),
                        "sign_flip": False,
                        "maximum_effect_mad_relative_change": 0.9,
                    }
                ]
            }
            for k in frames()
        }
    }
    result, _ = branches(frames(), core, "B8")
    assert result["T-OBS"]["triggered"]


def test_source_contrast_influence_is_included_in_influence_screen() -> None:
    core: Record = {
        "C7": {
            k: {
                "loo": [
                    {
                        "event_id": "e",
                        "relative_change": 0.1,
                        "sign_flip": False,
                        "maximum_effect_mad_relative_change": 0.1,
                        "source_contrast_max_relative_change": 0.8,
                    }
                ]
            }
            for k in frames()
        }
    }
    result, _ = branches(frames(), core, "B8")
    assert result["T-OBS"]["triggered"]
