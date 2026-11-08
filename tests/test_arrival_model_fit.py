"""Predictive mechanisms and stage gates before fitting actual reported durations."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_fit import (
    conditional_replicates,
    validate_fit_job,
    verify_computational_gate,
)


def test_conditional_replicates_share_effects_and_keep_native_units() -> None:
    hyper = {"alpha": np.zeros(100), "beta": np.zeros(100), "sigma": np.zeros(100)}
    effects = np.column_stack([np.full(100, 0.2), np.full(100, -0.1)])
    x = np.array([0.0, 1.0, 2.0])
    reference = np.array([10.0, 20.0, 30.0])
    response, native = conditional_replicates(
        hyper, effects, np.array([0, 0, 1]), x, reference, target="NCEI-native-duration", seed=17
    )
    np.testing.assert_allclose(response, np.broadcast_to([0.2, 0.2, -0.1], (100, 3)))
    np.testing.assert_allclose(native, np.exp(response) * reference)
    _, signed = conditional_replicates(
        hyper, effects, np.array([0, 0, 1]), x, reference, target="T-CAL", seed=17
    )
    np.testing.assert_array_equal(signed, response)


def test_fit_allocation_and_unapproved_lane_fail_before_sampling() -> None:
    job = {
        "target": "NCEI-native-duration",
        "kind": "event",
        "draws": 2000,
        "tune": 1000,
        "cores": 2,
        "seed": 20261108,
    }
    validate_fit_job(job)
    with pytest.raises(ValueError):
        validate_fit_job({**job, "draws": 100000})
    with pytest.raises(ValueError):
        validate_fit_job({**job, "target": "pooled-all-sources"})


def test_fit_gate_requires_review_and_exact_source_specific_identities(tmp_path: Path) -> None:
    files = [
        "analysis/arrival/models.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/model_validation.py",
        "config/arrival-model-priors-v1.toml",
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
    ]
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture")
    gate = tmp_path / "acceptance.json"
    record = {
        "schema_version": "arrival_ms2_acceptance_v1",
        "status": "accepted",
        "targets": ["NCEI-native-duration"],
        "independent_checker": "fixture_checker",
        "reserved_outcomes": "sealed",
        "files": {p: sha256(tmp_path / p) for p in files},
    }
    write_json(gate, record)
    verify_computational_gate(tmp_path, gate, "NCEI-native-duration")
    with pytest.raises(ValueError, match="source-specific"):
        verify_computational_gate(tmp_path, gate, "T-CAL")
    (tmp_path / files[0]).write_text("changed")
    with pytest.raises(ValueError, match="identity"):
        verify_computational_gate(tmp_path, gate, "NCEI-native-duration")
    write_json(gate, {**record, "status": "pending"})
    with pytest.raises(ValueError, match="gate required"):
        verify_computational_gate(tmp_path, gate, "NCEI-native-duration")


@pytest.mark.parametrize("failure", ["interrupt", "input-change"])
def test_fit_cli_persists_interrupt_and_input_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    spec = importlib.util.spec_from_file_location("fit_cli", "scripts/fit_arrival_model.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    job, gate = tmp_path / "job.json", tmp_path / "gate.json"
    job.write_text("{}")
    gate.write_text("{}")
    output = tmp_path / "fit"

    def fail(*_args: object) -> dict[str, object]:
        if failure == "interrupt":
            raise KeyboardInterrupt
        job.write_text('{"changed":true}')
        return {"returncode": 0, "reason": "worker_exit"}

    monkeypatch.setattr(cli, "supervise", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fit_arrival_model.py",
            "--job",
            str(job),
            "--gate",
            str(gate),
            "--output",
            str(output),
            "--store",
            str(tmp_path / "fit.nc"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == (130 if failure == "interrupt" else 1)
    receipt = json.loads(output.with_suffix(".supervisor.json").read_text())
    assert receipt["reason"] == ("interrupt" if failure == "interrupt" else "worker_exit")
    assert receipt["input_identity_unchanged"] == (failure == "interrupt")
