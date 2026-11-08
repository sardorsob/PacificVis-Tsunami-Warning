"""No retry or budget reset; preserve old raw stores and every failed node."""

# pyright: basic
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sequence_path as runner


def fixture(root, monkeypatch):
    (root / "stub.py").write_text("fixture")
    (root / "manifest.json").write_text("{}")
    (root / "prior").mkdir()
    (root / "prior/past.nc").write_bytes(b"old")
    (root / "external.nc").write_bytes(b"external")
    design = {
        "spec": {"seed_base": 2326220800, "sequence": "s", "event_id": "e"},
        "files": {"stub.py": sha256(root / "stub.py")},
        "record_count": 49,
        "jacobian": 0.0,
        "parent_calls": 43,
        "parent_call_ceiling": 352,
        "prior_raw_stores": ["prior"],
        "external_endpoint": "external.nc",
        "max_raw_bytes": 2 * 1024**3,
        "endpoint_metadata": [{"posterior_sha256": "training-hash"}],
        "endpoint_logs": {
            ("primary", 0): np.full((4, 2000), -10.0),
            ("primary", 16): np.full((4, 2000), -10.0),
        },
    }
    monkeypatch.setattr(runner, "prepare_sequence_path", lambda *_: design)
    monkeypatch.setattr(runner, "check_live_parent_budget", lambda *_: None)
    monkeypatch.setattr(runner, "git_sha", lambda *_: "fixture-sha")
    seen = []

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        seen.append(job)
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True)
        raw = Path(command[command.index("--store") + 1])
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"mock posterior")
        write_json(output / "sampling-start.json", job)
        write_json(
            output / "result.json",
            {"job": job, "status": "node_computed_pending_review", "posterior_sha256": sha256(raw)},
        )
        return {"reason": "worker_exit", "returncode": 0}

    monkeypatch.setattr(runner, "supervise", supervise)
    monkeypatch.setattr(runner, "read_sequence_node", lambda *_: np.full((4, 2000), -10.0))
    return seen, design


def run(root, **kw):
    runner.run_sequence_path(
        root, root / "manifest.json", root / "out", root / "store", root / "state.json", **kw
    )


def test_thirtytwo_calls_conserve_global_seventyfive_and_use_independent_repeat(
    tmp_path, monkeypatch
):
    seen, _ = fixture(tmp_path, monkeypatch)
    run(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text())
    summary = json.loads((tmp_path / "out/run-summary.json").read_text())
    assert state["status"] == "computations_complete" and state["next_case"] == 32
    assert len(seen) == state["calls_used"] == 32 and len({j["seed"] for j in seen}) == 32
    assert summary["remaining_global_calls"] == 277 and summary["parent_call_slots"] == 43
    assert json.loads((tmp_path / "out/independent-repeat-check.json").read_text())[
        "agreement_passed"
    ]
    assert json.loads((tmp_path / "out/repeat-path-result.json").read_text())[
        "source_training_posterior_sha"
    ] == sha256(tmp_path / "store/repeat-node-00.nc")


def test_first_failed_edge_retains_node_and_cannot_auto_resume(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch)
    original = runner.bridge_score

    def reject(*a, **kw):
        score, one, two = original(*a, **kw)
        score["precision_passed"] = False
        return score, one, two

    monkeypatch.setattr(runner, "bridge_score", reject)
    run(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["status"] == "needs_review" and state["calls_used"] == 1 and len(seen) == 1
    with pytest.raises(ValueError):
        run(tmp_path, resume=True)
    assert len(seen) == 1


def test_changed_store_or_combined_influence_cache_blocks_resume(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch)
    run(tmp_path, max_cases=15)
    with pytest.raises(ValueError, match="store"):
        runner.run_sequence_path(
            tmp_path,
            tmp_path / "manifest.json",
            tmp_path / "out",
            tmp_path / "other",
            tmp_path / "state.json",
            resume=True,
        )
    (tmp_path / "store/primary-combined-influences.npz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="retained"):
        run(tmp_path, resume=True)
    assert len(seen) == 15


def test_parent_budget_cannot_be_reset_even_with_a_rehashed_plan(tmp_path, monkeypatch):
    seen, _ = fixture(tmp_path, monkeypatch)
    run(tmp_path, max_cases=1)
    plan = json.loads((tmp_path / "out/plan.json").read_text())
    plan["parent_calls"] = 0
    write_json(tmp_path / "out/plan.json", plan)
    state = json.loads((tmp_path / "state.json").read_text())
    state["plan_sha256"] = sha256(tmp_path / "out/plan.json")
    write_json(tmp_path / "state.json", state)
    with pytest.raises(ValueError, match="plan"):
        run(tmp_path, resume=True)
    assert len(seen) == 1


def test_shared_raw_reservation_stops_before_a_call(tmp_path, monkeypatch):
    seen, design = fixture(tmp_path, monkeypatch)
    design["max_raw_bytes"] = 2 * 64 * 1024**2 + 1
    run(tmp_path)
    assert (
        not seen and json.loads((tmp_path / "state.json").read_text())["status"] == "budget_limit"
    )


def test_live_parent_counter_change_rejects_before_sampling(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    write_json(parent / "run-summary.json", {"global": 43})
    write_json(tmp_path / "copy.json", {"global": 43})
    design = {"spec": {"parent_output": "parent", "budget_snapshot": "copy.json"}}
    runner.check_live_parent_budget(tmp_path, design)
    write_json(parent / "run-summary.json", {"global": 44})
    with pytest.raises(ValueError, match="parent budget"):
        runner.check_live_parent_budget(tmp_path, design)


def test_immediate_checks_use_each_nonuniform_temperature_increment(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    original = runner.bridge_score
    seen = []

    def spy(first, second, **kw):
        seen.append((first.copy(), second.copy()))
        return original(first, second, **kw)

    monkeypatch.setattr(runner, "bridge_score", spy)
    run(tmp_path, max_cases=2)
    assert len(seen) == 2
    for (a, b), delta in zip(seen, [1 / 256, 3 / 256], strict=True):
        np.testing.assert_array_equal(a, np.full((4, 2000), -10 * delta))
        np.testing.assert_array_equal(b, np.full((4, 2000), -10 * delta))
