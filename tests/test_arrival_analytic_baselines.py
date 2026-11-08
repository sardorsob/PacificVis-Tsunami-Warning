"""Exact Gaussian baseline folds keep native units and frozen membership."""

# pyright: basic
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival import model_analytic_baselines as code
from analysis.arrival.evidence import read_rows
from tests.test_arrival_models import tiny_lane


@pytest.mark.parametrize("target", ["T-OBS", "T-CAL"])
def test_analytic_folds_preserve_sequence_purge_native_units_and_partial_status(
    tmp_path, monkeypatch, target
):
    root = tmp_path
    (root / "source.py").write_text("fixture")
    gate = root / "gate.json"
    gate.write_text("{}")
    config = root / "config/arrival-model-scoring-v1.toml"
    config.parent.mkdir()
    config.write_bytes(Path("config/arrival-model-scoring-v1.toml").read_bytes())
    monkeypatch.setattr(code, "CONSUMED", ["source.py", "config/arrival-model-scoring-v1.toml"])
    monkeypatch.setattr(code, "verify_computational_gate", lambda *_a: None)
    monkeypatch.setattr(
        code,
        "read_prior",
        lambda *_a: {
            "alpha_sd": 30.0 if target == "T-CAL" else 0.5,
            "beta_sd": 0.25,
            "sigma_sd": 30.0 if target == "T-CAL" else 0.4,
        },
    )
    monkeypatch.setattr(code.subprocess, "check_output", lambda *_a, **_kw: "fixture-git")
    lane = tiny_lane()
    if target == "T-CAL":
        lane = replace(
            lane,
            target=target,
            y=np.array([-10.0, -2.0, 3.0]),
            response=np.array([-10.0, -2.0, 3.0]),
        )
    monkeypatch.setattr(code, "load_lanes", lambda _r: ({target: lane}, {"inputs": {}}))
    out = root / "fits"
    store = root / "draws"
    code.run_analytic_baseline(root, target, "pooled", gate, out, store)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["complete"] and summary["eligible_for_comparison"] and summary["events"] == 3
    assert not summary["monte_carlo_used"]
    membership = json.loads((out / "sequence-membership.json").read_text())
    assert membership["q1"]["train"] == ["r1"] and membership["q1"]["test"] == ["r0", "r2"]
    rows = read_rows(out / "held-out-record-predictions.csv")
    assert len(rows) == 3 and {r["record_id"] for r in rows} == {"r0", "r1", "r2"}
    if target == "T-CAL":
        assert any(float(r["q05"]) < 0 for r in rows)
    else:
        assert all(float(r["q05"]) > 0 for r in rows)
    code.run_analytic_baseline(
        root, target, "pooled", gate, root / "partial", root / "partial-draws", max_folds=1
    )
    assert not json.loads((root / "partial/summary.json").read_text())["eligible_for_comparison"]
    with pytest.raises(ValueError, match="new"):
        code.run_analytic_baseline(root, target, "pooled", gate, out, store)
