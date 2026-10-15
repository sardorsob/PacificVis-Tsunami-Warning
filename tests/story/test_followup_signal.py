"""Signal support cannot be promoted into physical arrival validation."""

from pathlib import Path

from analysis.story.followups import FollowupInputs
from analysis.story.signal_followups import signal_references
from analysis.story.signal_plots import control_crossing_hours, plot_signal_diagnostics


def test_signal_references_preserve_all_frozen_settings_and_conflict(
    inputs: FollowupInputs,
) -> None:
    tables = signal_references(inputs)
    settings = tables["setting-reference"]
    assert settings == inputs.shared["picks"]
    assert len([r for r in settings if r["window"] == "event"]) == 80
    assert len([r for r in settings if r["window"] == "control"]) == 80
    rows = {r["station_id"]: r for r in tables["signal-support"]}
    assert len(rows) == 10
    assert rows["21418"]["mechanical_screen_pass"] is True
    assert rows["21418"]["external_validation"] == "conflicts_approximate_publisher_reference"
    assert rows["21418"]["physical_onset_status"] == "unvalidated"
    assert rows["saip"]["control_unevaluable"] == 8
    assert rows["saip"]["event_unevaluable"] == 8
    assert rows["saip"]["event_baseline_ineligible"] == 8
    assert rows["saip"]["event_no_detection"] == 0
    assert rows["9461380"]["control_crossings"] == 4
    assert all(r["modeled_arrival_status"] == "unavailable" for r in rows.values())


def test_source_qc_and_approximate_reference_keep_identity(inputs: FollowupInputs) -> None:
    tables = signal_references(inputs)
    qc = tables["source-qc-reference"]
    assert len(qc) == 140
    zero = next(r for r in qc if r["observation_id"] == "valp-2011-03-12T01:30:00Z")
    assert zero["raw_value"] == "0.0" and zero["out_of_range"] == "T"
    assert zero["source_time"] == "2011-03-12 01:30:00"
    reference = tables["source-references"][0]
    assert reference["precision"] == "approximate"
    assert reference["physical_pick_utc"] == "unknown"
    assert reference["reported_elapsed_minutes_approx"] == 25
    dart = [r for r in tables["signal-windows"] if r["station_id"] == "21418"]
    assert dart and all(r["field"] == "residual" for r in dart)
    assert {r["units"] for r in dart} == {"m water column"}


def test_signal_plots_export_all_three_pairs(inputs: FollowupInputs, tmp_path: Path) -> None:
    tables = signal_references(inputs)
    plot_signal_diagnostics(inputs, tables, tmp_path)
    for stem in (
        "05_signal_support_matrix",
        "06_early_crossing_context",
        "07_control_and_qc_context",
    ):
        assert (tmp_path / f"{stem}.png").stat().st_size > 1000
        assert (tmp_path / f"{stem}.svg").stat().st_size > 1000
    matrix = (tmp_path / "05_signal_support_matrix.svg").read_text()
    assert "8 unevaluable" in matrix


def test_control_plot_uses_origin_not_control_search_elapsed(inputs: FollowupInputs) -> None:
    hours = control_crossing_hours(inputs, signal_references(inputs), "9461380")
    assert len(hours) == 1
    assert abs(hours[0] - (-2544.12 / 3600)) < 1e-12
