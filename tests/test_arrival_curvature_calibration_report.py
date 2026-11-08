"""Coverage uncertainty is across datasets and stays separate by scenario and quantity."""

# pyright: basic
import pytest

from analysis.arrival.evidence import write_json
from scripts.run_arrival_curvature_calibration import OUTPUT, make_cases
from scripts.summarize_arrival_curvature_calibration import report, summarize_groups


def test_recovery_summary_keeps_independent_denominators_and_median_errors():
    rows = [
        {
            "scenario": scenario,
            "parameter": parameter,
            "covered90": j != 0,
            "median": j + 1.0,
            "truth": float(j),
            "posterior_prior_sd_ratio": 0.5,
            "recovery_z": -0.2,
        }
        for scenario in ["positive", "negative"]
        for parameter in ["gamma", "log_median_ratio_100km"]
        for j in range(10)
    ]
    result = summarize_groups(rows)
    assert len(result) == 4
    for row in result:
        assert row["datasets"] == 10 and row["covered90_count"] == 9
        assert row["covered90_proportion"] == 0.9
        assert 0.59 < row["wilson95_low"] < 0.60
        assert 0.98 < row["wilson95_high"] < 0.99
        assert row["mean_median_error"] == row["median_estimate_rmse"] == 1
        assert row["mean_median_error_dataset_mcse"] == 0
        assert row["mean_posterior_standardized_mean_error"] == pytest.approx(-0.2)


def test_report_rejects_existing_output_before_reading_any_outcomes(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    with pytest.raises(ValueError, match="new project-local"):
        report(tmp_path, "recovery", output)


def test_report_cannot_replace_frozen_method_hash_with_current_bytes(tmp_path):
    source = tmp_path / "analysis/arrival/model_curvature_curve_checks.py"
    source.parent.mkdir(parents=True)
    source.write_text("changed method")
    write_json(
        tmp_path / OUTPUT / "plan.json",
        {
            "cases": make_cases(),
            "files": {
                "analysis/arrival/model_curvature_curve_checks.py": "0" * 64,
            },
        },
    )
    with pytest.raises(ValueError, match="frozen input changed"):
        report(tmp_path, "recovery", tmp_path / "report")
