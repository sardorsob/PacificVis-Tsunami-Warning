"""Recovery uncertainty and rank calibration arithmetic with cache-free synthetic results."""

import math
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import xarray as xr

from analysis.arrival.evidence import sha256, write_json, write_rows
from analysis.arrival.model_validation_report import (
    calibration_summary,
    collect_batch,
    csv_rows,
    recovery_summary,
    wilson_interval,
)


def test_coverage_uncertainty_and_zero_boundary_are_explicit() -> None:
    low, high = wilson_interval(27, 30)
    assert low == pytest.approx(0.7437891742) and high == pytest.approx(0.9654001113)
    rows = [
        {
            "scenario": "reference",
            "parameter": "alpha",
            "truth": 0.0,
            "mean": 0.1,
            "q05": -0.1,
            "q95": 0.3,
            "covered90": True,
            "zero_variance_boundary": False,
        },
        {
            "scenario": "no-event-variation",
            "parameter": "tau_event",
            "truth": 0.0,
            "mean": 0.01,
            "q05": 0.001,
            "q95": 0.03,
            "covered90": None,
            "zero_variance_boundary": True,
        },
    ]
    summary = recovery_summary(rows, {"alpha": 2.0, "tau_event": 0.4})
    assert summary[0]["coverage90"] is None
    assert summary[0]["mean_q95_upper_bound"] == 0.03
    assert summary[1]["mean_error"] == 0.1
    assert summary[1]["mean_error_mcse"] is None
    assert summary[1]["mean_interval_width_contraction"] == pytest.approx(0.8)


def test_sbc_bands_account_for_quantities_and_detect_extreme_ranks() -> None:
    uniform = [
        {"parameter": "alpha", "randomized_rank_pit": (i + 0.5) / 200, "rank_ready": True}
        for i in range(200)
    ]
    good = calibration_summary(uniform, planned_quantities=6)
    assert good[0]["ks_distance"] == pytest.approx(0.0025)
    assert good[0]["simultaneous_epsilon"] == pytest.approx(math.sqrt(math.log(240) / 400))
    assert not good[0]["outside_reference_band"]
    bad = calibration_summary(
        [{**r, "randomized_rank_pit": 0.99} for r in uniform], planned_quantities=6
    )
    assert bad[0]["outside_reference_band"] and bad[0]["ks_distance"] > 0.9
    with pytest.raises(ValueError, match="rank"):
        calibration_summary([{**uniform[0], "rank_ready": False}], planned_quantities=6)


def test_recovery_simulation_mcse_matches_independent_calculation() -> None:
    rows = [
        {
            "scenario": "reference",
            "parameter": "beta",
            "truth": 0.1,
            "mean": float(value),
            "q05": 0.0,
            "q95": 0.2,
            "covered90": True,
            "zero_variance_boundary": False,
        }
        for value in [0.05, 0.12, 0.15]
    ]
    summary = recovery_summary(rows, {"beta": 0.5})[0]
    assert summary["mean_error_mcse"] == pytest.approx(
        np.std([-0.05, 0.02, 0.05], ddof=1) / math.sqrt(3)
    )
    assert summary["datasets"] == 3


def test_collect_conserves_cases_despite_csv_sort_and_rejects_corruption(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    cases: list[dict[str, Any]] = [
        {
            "id": identity,
            "scenario": identity,
            "replicate": 1,
            "job": {"draws": 1000, "tune": 1000, "seed": seed},
        }
        for identity, seed in [("z-first", 1), ("a-second", 2)]
    ]
    write_json(batch / "plan.json", {"cases": cases, "base_git_sha": "fixture"})
    dispositions: list[dict[str, str]] = []
    for case in cases:
        name = case["id"] + "-attempt-1"
        output = batch / "jobs" / name
        output.mkdir(parents=True)
        posterior = tmp_path / (name + ".nc")
        cast(Any, xr.DataTree).from_dict(
            {
                "posterior": xr.Dataset(
                    {
                        "alpha": (
                            ("chain", "draw"),
                            0.1 + np.linspace(-0.01, 0.01, 40).reshape(4, 10),
                        )
                    }
                )
            }
        ).to_netcdf(posterior)
        write_json(batch / "jobs" / (name + "-spec.json"), case["job"])
        write_json(
            output / "result.json",
            {
                "job": case["job"],
                "synthetic_only": True,
                "posterior": posterior.name,
                "posterior_sha256": sha256(posterior),
                "elapsed_seconds": 1,
                "diagnostics": {"screen_passed": True},
                "estimates": [{"parameter": "alpha", "mean": 0.1, "truth": 0.0, "covered90": None}],
            },
        )
        dispositions.append({"case_id": case["id"], "attempt": "1", "outcome": "accepted"})
    write_rows(batch / "trial-dispositions.csv", dispositions)
    write_json(
        batch / "run-summary.json",
        {
            "calls_used": 2,
            "completed_datasets": 2,
            "status": "computations_complete",
            "plan_sha256": sha256(batch / "plan.json"),
        },
    )
    status, estimates, diagnostics, pins = collect_batch(tmp_path, batch)
    assert status["complete"] and len(estimates) == len(diagnostics) == 2
    assert len(pins) == 9
    write_rows(tmp_path / "mixed.csv", csv_rows(estimates))
    next(tmp_path.glob("*.nc")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="posterior identity"):
        collect_batch(tmp_path, batch)
