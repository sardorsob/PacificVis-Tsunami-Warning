"""Finite synthetic trial counts, seed isolation and conservative checkpoint recovery."""

# pyright: basic
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "validation_batch", "scripts/run_arrival_model_batch.py"
    )
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_trial_plan_is_finite_and_random_channels_never_overlap() -> None:
    code = module()
    recovery = code.make_cases("recovery")
    sbc = code.make_cases("sbc")
    assert len(recovery) == 270 and len(sbc) == 200
    seeds = [case["job"]["seed"] for case in recovery + sbc]
    assert len(set(seeds)) == 470
    channels = [seed + channel for seed in seeds for channel in range(20)]
    assert len(set(channels)) == len(channels)
    assert all(
        case["job"]["cores"] == 2 and case["job"]["parameterization"] == "marginal"
        for case in recovery + sbc
    )


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    code = module()
    real = Path.cwd()
    root = tmp_path / "repo"
    for name in code.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((real / name).read_bytes())
    monkeypatch.setattr(code, "git_sha", lambda _root: "fixture")
    calls: list[dict[str, Any]] = []

    def worker(command: list[str], log: Path, _stop: Path, _timeout: int) -> dict[str, Any]:
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        output = Path(command[command.index("--output") + 1])
        output.mkdir()
        posterior = Path(command[command.index("--store") + 1])
        posterior.parent.mkdir(parents=True, exist_ok=True)
        posterior.write_bytes(b"test fixture, not scientific NetCDF")
        calls.append(job)
        (output / "result.json").write_text(
            json.dumps(
                {
                    "job": job,
                    "synthetic_only": True,
                    "posterior": str(posterior.relative_to(root)),
                    "posterior_sha256": code.sha256(posterior),
                    "code_and_config": {
                        p: code.sha256(root / p)
                        for p in code.CONSUMED
                        if p != "scripts/run_arrival_model_batch.py"
                    },
                    "diagnostics": {
                        "screen_passed": True,
                        "divergences": 0,
                        "maxdepth_reached": 0,
                        "finite_diagnostics": True,
                        "min_bfmi": 1.0,
                        "max_rhat": 1.0,
                    },
                }
            )
        )
        log.write_text("synthetic worker fixture, no sampling")
        return {"returncode": 0, "reason": "worker_exit", "elapsed_seconds": 0.0}

    monkeypatch.setattr(code, "supervise", worker)
    return code, root, calls


def test_case_limit_resume_and_no_duplicate_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "recovery", output, store, state, max_cases=1)
    code.run_batch(root, "recovery", output, store, state, max_cases=1, resume=True)
    checkpoint = json.loads(state.read_text())
    assert checkpoint["next_case"] == 2 and checkpoint["calls_used"] == 2
    assert len(calls) == 2 and calls[0]["seed"] != calls[1]["seed"]


def test_incomplete_attempt_refuses_automatic_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "sbc", output, store, state, max_cases=0)
    checkpoint = json.loads(state.read_text())
    checkpoint["current"] = {"id": "unfinished"}
    state.write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="incomplete"):
        code.run_batch(root, "sbc", output, store, state, max_cases=0, resume=True)
    assert not calls


def test_corrupt_completed_count_cannot_skip_datasets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, _ = setup(tmp_path, monkeypatch)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "sbc", output, store, state, max_cases=0)
    checkpoint = json.loads(state.read_text())
    checkpoint["next_case"] = 2
    state.write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="conservation"):
        code.run_batch(root, "sbc", output, store, state, max_cases=0, resume=True)


def test_unsafe_failure_is_not_blindly_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    normal_worker = code.supervise

    def unsafe(command: list[str], log: Path, stop: Path, timeout: int) -> dict[str, Any]:
        receipt = normal_worker(command, log, stop, timeout)
        path = Path(command[command.index("--output") + 1]) / "result.json"
        result = json.loads(path.read_text())
        result["diagnostics"].update({"screen_passed": False, "divergences": 1})
        path.write_text(json.dumps(result))
        return receipt

    monkeypatch.setattr(code, "supervise", unsafe)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "sbc", output, store, state, max_cases=1)
    assert len(calls) == 1 and json.loads(state.read_text())["status"] == "needs_review"
    with pytest.raises(ValueError, match="review"):
        code.run_batch(root, "sbc", output, store, state, max_cases=0, resume=True)


def test_precision_repair_keeps_the_same_dataset_and_both_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    normal_worker = code.supervise

    def imprecise_once(command, log, stop, timeout):
        receipt = normal_worker(command, log, stop, timeout)
        if len(calls) == 1:
            path = Path(command[command.index("--output") + 1]) / "result.json"
            result = json.loads(path.read_text())
            result["diagnostics"].update({"screen_passed": False, "max_rhat": 1.015})
            path.write_text(json.dumps(result))
        return receipt

    monkeypatch.setattr(code, "supervise", imprecise_once)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "recovery", output, store, state, max_cases=1)
    checkpoint = json.loads(state.read_text())
    assert checkpoint["next_case"] == 1 and checkpoint["calls_used"] == 2
    assert [a["outcome"] for a in checkpoint["attempts"]] == ["precision_failure", "accepted"]
    assert calls[0]["seed"] == calls[1]["seed"] and calls[0]["truth"] == calls[1]["truth"]
    assert calls[1]["draws"] == calls[0]["draws"] * 2 and calls[1]["tune"] == 2000
    assert len(list(store.glob("*.nc"))) == 2


def test_result_identity_and_source_drift_require_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    normal_worker = code.supervise

    def wrong_identity(command, log, stop, timeout):
        receipt = normal_worker(command, log, stop, timeout)
        path = Path(command[command.index("--output") + 1]) / "result.json"
        result = json.loads(path.read_text())
        result["posterior_sha256"] = "incorrect"
        path.write_text(json.dumps(result))
        return receipt

    monkeypatch.setattr(code, "supervise", wrong_identity)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "sbc", output, store, state, max_cases=1)
    checkpoint = json.loads(state.read_text())
    assert checkpoint["next_case"] == 0 and len(calls) == 1
    assert checkpoint["attempts"][0]["outcome"] == "identity_failure"
    (root / code.CONSUMED[-1]).write_text("changed lock")
    with pytest.raises(ValueError, match="source/phase changed"):
        code.run_batch(root, "sbc", output, store, state, resume=True)


def test_resume_revalidates_saved_posterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, root, calls = setup(tmp_path, monkeypatch)
    output, store, state = (
        root / "artifacts/run",
        root / "data/processed/models/run",
        tmp_path / "state.json",
    )
    code.run_batch(root, "recovery", output, store, state, max_cases=1)
    next(store.glob("*.nc")).unlink()
    with pytest.raises(ValueError, match="retained attempt"):
        code.run_batch(root, "recovery", output, store, state, max_cases=1, resume=True)
    assert len(calls) == 1
