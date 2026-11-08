"""Absolute path budget, immediate failed-edge stop and retained-node resume safety."""

# pyright: basic
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_bridge_path as runner


def fixture(root, monkeypatch, diagnostic_failure=False):
    (root / "stub.py").write_text("fixture")
    (root / "parent").mkdir()
    (root / "parent/retained.nc").write_text("existing")
    monkeypatch.setattr(runner, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(
        runner,
        "prepare_path",
        lambda *_: {
            "files": {"stub.py": sha256(root / "stub.py")},
            "record_count": 100,
            "jacobian": 0.0,
            "parent_calls": 4,
            "parent_call_ceiling": 352,
            "parent_raw_store": root / "parent",
            "extra_endpoint_bytes": 0,
            "max_raw_bytes": 2 * 1024**3,
            "endpoint_metadata": {"fixture": True},
            "endpoint_logs": {
                ("primary", 0): np.full((4, 2000), -10.0),
                ("primary", 8): np.full((4, 2000), -10.0),
                ("repeat", 8): np.full((4, 2000), -10.0),
            },
        },
    )
    monkeypatch.setattr(runner, "git_sha", lambda *_: "fixture-sha")
    seen = []

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        seen.append(job)
        out = Path(command[command.index("--output") + 1])
        raw = Path(command[command.index("--store") + 1])
        out.mkdir(parents=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("mock-posterior")
        write_json(out / "sampling-start.json", job)
        write_json(
            out / "result.json",
            {
                "job": job,
                "status": "diagnostic_failure"
                if diagnostic_failure
                else "node_computed_pending_review",
                "diagnostics": {"screen_passed": not diagnostic_failure},
            },
        )
        return {"returncode": 2 if diagnostic_failure else 0, "reason": "worker_exit"}

    monkeypatch.setattr(runner, "supervise", supervise)
    monkeypatch.setattr(runner, "read_node", lambda *_: np.full((4, 2000), -10.0))
    return seen


def test_fixed_fifteen_calls_have_no_retry_and_keep_parent_debit(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state)
    d = json.loads(state.read_text())
    assert len(seen) == d["calls_used"] == d["next_case"] == 15
    assert d["status"] == "computations_complete"
    assert json.loads((out / "run-summary.json").read_text())["remaining_global_calls"] == 333
    assert json.loads((out / "primary-path-result.json").read_text())[
        "normalized_event_score"
    ] == pytest.approx(-0.1)


def test_first_bad_edge_stops_and_never_consumes_unused_calls(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch)
    original = runner.bridge_score

    def reject(*a, **kw):
        score, first, second = original(*a, **kw)
        score.update(precision_passed=False, overlap=0.001)
        return score, first, second

    monkeypatch.setattr(runner, "bridge_score", reject)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state)
    d = json.loads(state.read_text())
    assert d["status"] == "needs_review" and d["calls_used"] == 1 and d["next_case"] == 0
    assert len(seen) == 1 and d["attempts"][0]["outcome"] == "edge_failure"
    with pytest.raises(ValueError):
        runner.run_path(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_changed_store_or_retained_node_blocks_resume(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state, max_cases=1)
    with pytest.raises(ValueError, match="store"):
        runner.run_path(tmp_path, out, tmp_path / "other", state, resume=True)
    next(store.glob("*.nc")).write_text("corrupted")
    with pytest.raises(ValueError, match="retained"):
        runner.run_path(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_combined_influence_cache_is_part_of_the_retained_checkpoint(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state, max_cases=7)
    (store / "primary-combined-influences.npz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="retained"):
        runner.run_path(tmp_path, out, store, state, resume=True)
    assert len(seen) == 7


def test_parent_budget_fields_cannot_be_changed_with_a_new_plan_hash(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state, max_cases=1)
    plan = json.loads((out / "plan.json").read_text())
    plan["global_call_ceiling"] = 999
    write_json(out / "plan.json", plan)
    snapshot = json.loads(state.read_text())
    snapshot["plan_sha256"] = sha256(out / "plan.json")
    write_json(state, snapshot)
    with pytest.raises(ValueError, match="plan"):
        runner.run_path(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_failed_sampler_is_retained_without_another_call(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, diagnostic_failure=True)
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    runner.run_path(tmp_path, out, store, state)
    d = json.loads(state.read_text())
    assert len(seen) == d["calls_used"] == 1 and d["status"] == "needs_review"
    assert d["attempts"][0]["outcome"] == "diagnostic_failure"
