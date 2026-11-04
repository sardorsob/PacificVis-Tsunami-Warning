"""Scientific dispositions preserve uncertainty and the frozen replication rule."""

from analysis.arrival.timing_data_and_descriptive_statistics import Record
from scripts.build_arrival_timing_eda_report import replication


def test_opposite_direction_cannot_be_called_confirmed() -> None:
    a: Record = {"triggered": True, "scalar": 0.5, "detail": {}}
    b: Record = {"scalar": -0.5, "detail": {}}
    assert replication("B1", a, b).startswith("contradicted")


def test_degenerate_bootstrap_blocks_confirmation_even_if_ratios_match() -> None:
    a: Record = {"triggered": True, "scalar": 3.0, "detail": {"two_key_bootstrap_stability": False}}
    b: Record = {"scalar": 3.0, "detail": {"two_key_bootstrap_stability": True}}
    assert replication("B3", a, b).startswith("tentative")


def test_missing_confirmation_is_unidentified_not_zero_or_contradicted() -> None:
    a: Record = {"triggered": True, "scalar": 0.5, "detail": {}}
    assert replication("B1", a, {"scalar": "unknown"}).startswith("tentative")
