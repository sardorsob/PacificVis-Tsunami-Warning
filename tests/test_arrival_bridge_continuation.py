"""Continuation must retain the nineteen-call debit and both stopped-run stores."""

# pyright: basic
import json

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_bridge_continuation as runner
from tests.test_arrival_bridge_batch import fixture as original_fixture


def fixture(root, monkeypatch, outcomes):
    seen = original_fixture(root, monkeypatch, outcomes)
    # The fixture patches the old controller; explicitly share only its fake worker.
    from scripts import run_arrival_bridge_batch as original

    monkeypatch.setattr(runner, "supervise", original.supervise)
    monkeypatch.setattr(runner, "git_sha", original.git_sha)
    monkeypatch.setattr(runner, "FOLD_CONSUMED", ["stub.py"])
    monkeypatch.setattr(runner, "CONTROLLER", "controller.py")
    (root / "prior-store").mkdir()
    (root / "prior-store/retained.nc").write_bytes(b"retained")
    (root / "external-endpoint.nc").write_bytes(b"external")
    design = {
        "cases": original.make_bridge_cases(root),
        "files": {"stub.py": sha256(root / "stub.py")},
        "prior_calls": 19,
        "global_call_ceiling": 352,
        "remaining_calls": 333,
        "prior_raw_stores": ["prior-store"],
        "external_endpoint": "external-endpoint.nc",
        "max_raw_bytes": 2 * 1024**3,
        "logical_fold_total": 83,
        "completed_parent_folds": 2,
    }
    monkeypatch.setattr(runner, "continuation_design", lambda *_: design)
    return seen, design


def test_same_seed_repair_conserves_prior_and_new_calls(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch, ["mild", "pass", "pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_continuation(tmp_path, out, store, state)
    d = json.loads(state.read_text())
    summary = json.loads((out / "run-summary.json").read_text())
    assert d["status"] == "computations_complete" and d["next_case"] == 2
    assert len(seen) == 3 and d["sampler_call_slots_used"] == 6
    assert summary["global_calls_reserved"] == 25
    assert summary["remaining_global_calls"] == 327
    assert [j["draws"] for j in seen] == [2000, 4000, 2000]
    assert seen[0]["seed"] == seen[1]["seed"]


def test_call_and_shared_raw_limits_stop_before_a_new_fit(tmp_path, monkeypatch):
    seen, design = fixture(tmp_path, monkeypatch, [])
    design["remaining_calls"] = 1
    runner.run_continuation(tmp_path, tmp_path / "out", tmp_path / "store", tmp_path / "s.json")
    assert not seen
    assert json.loads((tmp_path / "s.json").read_text())["status"] == "budget_limit"


def test_shared_old_and_external_raw_bytes_are_counted(tmp_path, monkeypatch):
    seen, design = fixture(tmp_path, monkeypatch, [])
    design["max_raw_bytes"] = 3 * 64 * 1024**2 + 1
    runner.run_continuation(tmp_path, tmp_path / "out", tmp_path / "store", tmp_path / "s.json")
    assert not seen  # Old + external bytes exceed the remaining reservation.


def test_bad_result_is_retained_and_cannot_auto_resume(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch, ["unsafe"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_continuation(tmp_path, out, store, state)
    assert len(seen) == 1 and json.loads(state.read_text())["status"] == "needs_review"
    with pytest.raises(ValueError):
        runner.run_continuation(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_resume_rejects_changed_store_raw_and_debit_even_with_rehashed_plan(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch, ["pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_continuation(tmp_path, out, store, state, max_cases=1)
    with pytest.raises(ValueError, match="store"):
        runner.run_continuation(tmp_path, out, tmp_path / "other", state, resume=True)
    plan = json.loads((out / "plan.json").read_text())
    plan["prior_calls"] = 0
    write_json(out / "plan.json", plan)
    d = json.loads(state.read_text())
    d["plan_sha256"] = sha256(out / "plan.json")
    write_json(state, d)
    with pytest.raises(ValueError, match="plan"):
        runner.run_continuation(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_corrupted_new_posterior_blocks_the_next_fold(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch, ["pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_continuation(tmp_path, out, store, state, max_cases=1)
    next(store.rglob("posterior.nc")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="retained"):
        runner.run_continuation(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1
