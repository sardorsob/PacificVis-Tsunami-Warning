"""Finite sequence-controller conservation and repair rules, without sampling."""

# pyright: basic
import importlib.util
import json
from pathlib import Path

import pytest


def setup(root: Path, monkeypatch, outcomes):
    spec = importlib.util.spec_from_file_location(
        "sequence_batch", "scripts/run_arrival_sequence_batch.py"
    )
    assert spec and spec.loader
    code = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(code)
    monkeypatch.setattr(code, "CV_CONSUMED", ["source.py"])
    for p in [code.CONTROLLER, "scripts/run_arrival_model_batch.py", "source.py", "gate.json"]:
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(code, "git_sha", lambda _r: "fixture-git-sha")
    cases = [
        {
            "id": f"case-{i}",
            "job": {
                "seed": 1000 + i * 100,
                "draws": 2000,
                "tune": 1000,
                "cores": 2,
                "gate": "gate.json",
                "kind": "event",
                "target": "T-OBS",
                "sequence": f"q{i}",
            },
        }
        for i in range(2)
    ]
    monkeypatch.setattr(code, "make_sequence_cases", lambda *_a: cases)
    calls = []

    def worker(command, log, _stop, timeout):
        assert "--worker" in command and timeout == 600
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        out = Path(command[command.index("--output") + 1])
        out.mkdir()
        store = Path(command[command.index("--store") + 1])
        store.parent.mkdir(exist_ok=True, parents=True)
        store.write_text("mock chains, not inference evidence")
        log.write_text("mock worker")
        status = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(job)
        diagnostics = {
            "screen_passed": status != "diagnostic_failure",
            "finite_diagnostics": True,
            "divergences": 1 if status == "diagnostic_failure" else 0,
            "maxdepth_reached": 0,
            "min_bfmi": 1.0,
            "max_rhat": 1.0,
        }
        (out / "result.json").write_text(
            json.dumps(
                {
                    "job": job,
                    "diagnostics": diagnostics,
                    "status": status,
                    "score_precision_passed": status == "computed_pending_review",
                    "code_and_config": {
                        p: code.sha256(root / p) for p in ["source.py", "gate.json"]
                    },
                    "posterior": str(store.relative_to(root)),
                    "posterior_sha256": code.sha256(store),
                }
            )
        )
        return {"returncode": 0, "reason": "worker_exit"}

    monkeypatch.setattr(code, "supervise", worker)
    return code, calls


def test_sequence_repair_retains_same_data_seed_and_conserves_resume(tmp_path, monkeypatch):
    code, calls = setup(
        tmp_path, monkeypatch, ["score_precision_failure", "computed_pending_review"]
    )
    out, store, state = tmp_path / "fits", tmp_path / "draws", tmp_path / "state.json"
    code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, max_cases=1)
    saved = json.loads(state.read_text())
    assert saved["calls_used"] == 2 and saved["next_case"] == 1
    assert (
        calls[0]["seed"] == calls[1]["seed"]
        and calls[1]["draws"] == 4000
        and calls[1]["tune"] == 2000
    )
    assert [a["outcome"] for a in saved["attempts"]] == ["precision_failure", "accepted"]
    code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, resume=True)
    saved = json.loads(state.read_text())
    assert saved["calls_used"] == 3 and saved["next_case"] == 2
    assert saved["status"] == "computations_complete" and len(calls) == 3
    (store / "case-0-attempt-1.nc").write_text("corrupt retained failed attempt")
    with pytest.raises(ValueError, match="changed or is missing"):
        code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, resume=True)
    assert len(calls) == 3


def test_sequence_unsafe_diagnostics_stop_and_never_auto_resume(tmp_path, monkeypatch):
    code, calls = setup(tmp_path, monkeypatch, ["diagnostic_failure"])
    out, store, state = tmp_path / "fits", tmp_path / "draws", tmp_path / "state.json"
    code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state)
    saved = json.loads(state.read_text())
    assert saved["status"] == "needs_review"
    assert saved["calls_used"] == 1 and saved["next_case"] == 0
    with pytest.raises(ValueError, match="explicit review"):
        code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, resume=True)
    assert len(calls) == 1


def test_sequence_resume_rejects_changed_sources_before_new_worker(tmp_path, monkeypatch):
    code, calls = setup(tmp_path, monkeypatch, ["computed_pending_review"])
    out, store, state = tmp_path / "fits", tmp_path / "draws", tmp_path / "state.json"
    code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, max_cases=1)
    (tmp_path / "source.py").write_text("changed")
    with pytest.raises(ValueError, match="changed or unfinished"):
        code.run_sequence_batch(tmp_path, "T-OBS", ["event"], out, store, state, resume=True)
    assert len(calls) == 1
