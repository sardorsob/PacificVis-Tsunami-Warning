"""Fit routing and conditional simulation checks never fit historical outcomes."""

# pyright: basic
import json
import sys

import numpy as np
import pytest

from analysis.arrival import model_curvature_fit as fitting
from analysis.arrival.evidence import sha256
from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_scale_fit import conditional_scale_replicates
from scripts import fit_arrival_curvature as cli


def test_conditional_curvature_replication_keeps_noise_and_event_sharing():
    hyper = {
        "alpha": np.array([0.1, 0.2]),
        "beta": np.array([0.05, -0.1]),
        "sigma_anchor": np.array([[0.5, 0.4, 0.2], [0.6, 0.5, 0.3]]),
    }
    u = np.array([[0.1, 0.2], [-0.1, -0.2]])
    group = np.array([0, 0, 1])
    distance = np.array([20.0, 1000.0, 7000.0])
    reference = np.array([2.0, 90.0, 600.0])
    baseline, native = conditional_scale_replicates(hyper, u, group, distance, reference, seed=100)
    response, actual = fitting.conditional_curvature_replicates(
        {**hyper, "gamma": np.zeros(2)}, u, group, distance, reference, seed=100
    )
    np.testing.assert_allclose(response, baseline, rtol=0, atol=1e-14)
    np.testing.assert_allclose(actual, native, rtol=1e-14)
    gamma = np.array([0.5, -0.5])
    response, actual = fitting.conditional_curvature_replicates(
        {**hyper, "gamma": gamma}, u, group, distance, reference, seed=100
    )
    shift = gamma[:, None] * curvature_basis(distance)
    np.testing.assert_allclose(response - baseline, shift, rtol=0, atol=1e-14)
    np.testing.assert_allclose(actual, native * np.exp(shift), rtol=1e-14)


def test_missing_inference_gate_blocks_before_historical_loader(tmp_path, monkeypatch):
    def forbidden(*a):
        raise AssertionError("historical outcomes must not be read")

    monkeypatch.setattr(fitting, "load_lanes", forbidden)
    job = {
        "kind": "mean-curvature",
        "target": "NCEI-native-duration",
        "prior": "base",
        "draws": 2000,
        "tune": 1000,
        "cores": 2,
        "seed": 11,
    }
    with pytest.raises(FileNotFoundError):
        fitting.fit_exploration_curvature(tmp_path, job, tmp_path / "attempt", tmp_path / "raw.nc")


def test_stop_receipt_cannot_be_overwritten_before_gate_or_worker(tmp_path, monkeypatch):
    output = tmp_path / "attempt"
    receipt = output.with_suffix(".supervisor.json")
    receipt.write_text('{"reason":"stop_before_launch"}')
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "scripts/fit.py"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fit",
            "--job",
            str(tmp_path / "job.json"),
            "--output",
            str(output),
            "--store",
            str(tmp_path / "raw.nc"),
        ],
    )
    with pytest.raises(ValueError, match="new project-local"):
        cli.main()
    assert json.loads(receipt.read_text())["reason"] == "stop_before_launch"


def test_interrupt_writes_explicit_supervisor_receipt(tmp_path, monkeypatch):
    job = tmp_path / "job.json"
    job.write_text("{}")
    gate = tmp_path / "gate.json"
    gate.write_text("fixture")
    output = tmp_path / "attempt"
    monkeypatch.setattr(fitting, "FIT_GATE", "gate.json")
    monkeypatch.setattr(fitting, "CONSUMED", [])
    monkeypatch.setattr(fitting, "verify_fit_gate", lambda *a: {"gate.json": sha256(gate)})
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "scripts/fit.py"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["fit", "--job", str(job), "--output", str(output), "--store", str(tmp_path / "raw.nc")],
    )

    def interrupted(*a):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "supervise", interrupted)
    with pytest.raises(SystemExit):
        cli.main()
    receipt = json.loads(output.with_suffix(".supervisor.json").read_text())
    assert receipt["reason"] == "interrupt" and receipt["returncode"] == 130
