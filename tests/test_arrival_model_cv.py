"""Cache-free sequence orchestration tests; mock samples are not inference evidence."""

# pyright: basic
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_cv as cv
from analysis.arrival.evidence import sha256
from tests.test_arrival_models import tiny_lane


@pytest.mark.parametrize("target", ["T-OBS", "T-CAL"])
def test_sequence_worker_purges_training_and_keeps_native_target(tmp_path, monkeypatch, target):
    root = tmp_path
    source = root / "stub-source.py"
    source.write_text("fixture only")
    config = root / "config/arrival-model-scoring-v1.toml"
    config.parent.mkdir()
    config.write_bytes(Path("config/arrival-model-scoring-v1.toml").read_bytes())
    gate = root / "gate.json"
    gate.write_text("{}")
    lane = tiny_lane()
    if target == "T-CAL":
        lane = replace(
            lane,
            target=target,
            y=np.array([-10.0, -2.0, 3.0]),
            response=np.array([-10.0, -2.0, 3.0]),
        )
    monkeypatch.setattr(cv, "CONSUMED", ["stub-source.py", "config/arrival-model-scoring-v1.toml"])
    monkeypatch.setattr(
        cv, "load_lanes", lambda _r: ({target: lane}, {"fixture": "no real outcomes"})
    )
    monkeypatch.setattr(cv, "verify_prediction_gate", lambda *_a: None)
    monkeypatch.setattr(cv, "read_prior", lambda *_a: {})
    monkeypatch.setattr(cv.subprocess, "check_output", lambda *_a, **_kw: "fixture-git-sha")
    seen = []

    class Model:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def build(_lane, _prior, **kw):
        seen.append(kw["indices"].copy())
        return Model()

    monkeypatch.setattr(cv, "build_model", build)

    def sample(**_kw):
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    {
                        "alpha": (("chain", "draw"), np.full((4, 1000), -0.1)),
                        "sigma": (
                            ("chain", "draw"),
                            np.full((4, 1000), 20.0 if target == "T-CAL" else 0.4),
                        ),
                    }
                )
            }
        )

    monkeypatch.setattr(cv.pm, "sample", sample)

    class Table:
        def to_csv(self, p, **_kw):
            Path(p).write_text("mock diagnostics")

    diagnostics = {"screen_passed": True}
    monkeypatch.setattr(cv, "sampling_diagnostics", lambda _tree: (diagnostics, Table()))
    job = {
        "kind": "pooled",
        "target": target,
        "draws": 1000,
        "tune": 1000,
        "cores": 2,
        "seed": 103,
        "gate": "gate.json",
        "sequence": "q1",
    }
    out = root / "fit"
    store = root / "draws.nc"
    cv.fit_sequence_job(root, job, out, store)
    np.testing.assert_array_equal(seen[0], [1])
    membership = json.loads((out / "membership.json").read_text())
    assert membership["train"] == ["r1"] and membership["test"] == ["r0", "r2"]
    result = json.loads((out / "result.json").read_text())
    assert result["status"] == "computed_pending_review" and result["heldout_events"] == 2
    assert sha256(store) == result["posterior_sha256"]
    with xr.open_dataset(store, group="heldout_event_density", engine="h5netcdf") as d:
        assert d.native_log_density.shape == (2, 4, 1000)
    cv.summarize_sequence_scores(root, [out], root / "partial-summary")
    summary = json.loads((root / "partial-summary/summary.json").read_text())
    assert not summary["complete"] and not summary["eligible_for_comparison"]
    cv.fit_sequence_job(
        root, {**job, "sequence": "q2", "seed": 203}, root / "other", root / "other.nc"
    )
    cv.summarize_sequence_scores(root, [out, root / "other"], root / "complete-summary")
    summary = json.loads((root / "complete-summary/summary.json").read_text())
    assert summary["complete"] and summary["eligible_for_comparison"] and summary["events"] == 3
    with pytest.raises(ValueError, match="inconsistent"):
        cv.summarize_sequence_scores(root, [out, out], root / "duplicate")
    with pytest.raises(ValueError, match="new paths"):
        cv.fit_sequence_job(root, job, out, store)
    diagnostics["screen_passed"] = False
    cv.fit_sequence_job(root, job, root / "failed", root / "failed.nc")
    assert json.loads((root / "failed/result.json").read_text())["status"] == "diagnostic_failure"
    diagnostics["screen_passed"] = True
    original = cv.event_score

    def imprecise(*a, **kw):
        result, influence = original(*a, **kw)
        result["normalized_mcse"] = 0.1
        return result, influence

    monkeypatch.setattr(cv, "event_score", imprecise)
    cv.fit_sequence_job(root, job, root / "imprecise", root / "imprecise.nc")
    assert (
        json.loads((root / "imprecise/result.json").read_text())["status"]
        == "score_precision_failure"
    )

    def reject(*_a):
        raise ValueError("gate rejected")

    monkeypatch.setattr(cv, "verify_prediction_gate", reject)
    with pytest.raises(ValueError, match="gate rejected"):
        cv.fit_sequence_job(root, job, root / "never", root / "never.nc")
    assert not (root / "never").exists()


def test_candidate_gate_requires_prior_data_environment_and_report_hashes(tmp_path):
    root = tmp_path
    files = {
        "analysis/arrival/model_scale.py": "fixture",
        "analysis/arrival/model_scale_validation.py": "fixture",
    }
    gate = {
        "status": "accepted",
        "schema_version": "arrival_ms4_scale_acceptance_v1",
        "independent_checker": "fixture",
        "reserved_outcomes": "sealed",
        "files": files,
        "prior_variant": "base",
    }
    p = root / "gate.json"
    p.write_text(json.dumps(gate))
    with pytest.raises(ValueError, match="candidate-specific"):
        cv.verify_prediction_gate(root, p, "NCEI-native-duration", "distance-scale")
    for name in [
        "analysis/arrival/model_data.py",
        "analysis/arrival/models.py",
        "analysis/arrival/model_validation.py",
        "config/arrival-model-priors-v1.toml",
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
        "artifacts/models/arrival-timing/distance-scale-prior-v1/review-acceptance.json",
        *[
            f"artifacts/models/arrival-timing/distance-scale-validation-report-v1/{phase}/output-checksums.json"
            for phase in ["recovery", "sbc"]
        ],
    ]:
        files[name] = "fixture"
    for name in files:
        q = root / name
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text("fixture")
        files[name] = sha256(q)
    p.write_text(json.dumps(gate))
    cv.verify_prediction_gate(root, p, "NCEI-native-duration", "distance-scale")
    (root / "config/arrival-model-priors-v1.toml").write_text("changed")
    with pytest.raises(ValueError, match="identity changed"):
        cv.verify_prediction_gate(root, p, "NCEI-native-duration", "distance-scale")


def test_exact_public_sequence_cli_help():
    result = subprocess.run(
        [sys.executable, "scripts/fit_arrival_sequence.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and "--job" in result.stdout and "--store" in result.stdout
