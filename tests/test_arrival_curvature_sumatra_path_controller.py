"""Same-ledger path allocation, failure retention, bounded batches and no duplicate calls."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_curvature_sumatra_path as runner


def fixture(root, monkeypatch, *, failure=False):
    parent = root / runner.PARENT_OUTPUT
    parent.mkdir(parents=True)
    (root / runner.PARENT_STORE).mkdir(parents=True)
    write_json(
        parent / "plan.json",
        {
            "cases": [{"id": "fold-000"}, {"id": "fold-001"}],
            "memberships": {"fold-000": {}, "fold-001": {}},
            "files": {},
        },
    )
    state = {
        "status": "cv_needs_review",
        "calls_charged": 77,
        "calls_started": 77,
        "next_fold": 19,
        "current": None,
        "accepted": [{}] * 17,
        "rehearsal_sha256": "r",
        "plan_sha256": sha256(parent / "plan.json"),
    }
    write_json(root / runner.STATE, state)
    source = root / "source.py"
    source.write_text("frozen")
    resources = {
        "global_max_bytes": runner.MAX_GLOBAL,
        "local_max_bytes": runner.MAX_LOCAL,
        "cache_max_bytes": runner.MAX_CACHE,
        "job_max_bytes": runner.MAX_JOB,
        "next_invocation_reserve_bytes": runner.RESERVE,
        "per_file_bytes": 64 * runner.MIB,
        "per_node_seconds": 600,
        "whole_active_allocation_seconds": 1200,
        "concurrency": 1,
        "automatic_retries": 0,
        "max_nodes_per_invocation": 3,
    }
    gate = {
        "resources": resources,
        "path_bindings": runner.bindings(
            root, root / runner.OUTPUT, root / runner.STORE, root / runner.STATE
        ),
        "parent_minimum_bytes": {},
        "parent_checkpoint": {
            k: state[k]
            for k in ["status", "calls_charged", "calls_started", "next_fold", "current"]
        },
    }
    design = {
        "gate": gate,
        "files": {"source.py": sha256(source)},
        "held": np.array([0]),
        "lane": SimpleNamespace(y=np.array([2.0])),
    }
    monkeypatch.setattr(runner, "load_design", lambda *a: design)
    monkeypatch.setattr(runner, "parent_roots", lambda *a: [])
    monkeypatch.setattr(runner, "verify_rehearsal", lambda *a: "r")
    monkeypatch.setattr(runner, "case_artifacts", lambda *a: None)
    monkeypatch.setattr(runner, "conserved_parent", lambda *a: None)
    monkeypatch.setattr(runner, "parent_floors", lambda *a: [])
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda *a: None)
    monkeypatch.setattr(runner, "read_endpoint", lambda *a: (np.full((4, 2000), -10.0), "a" * 64))
    monkeypatch.setattr(runner, "read_node", lambda *a: np.full((4, 2000), -10.0))
    calls = []

    def supervise(command, log, stop, timeout):
        calls.append((command, timeout))
        spec = Path(command[command.index("--job") + 1])
        output = Path(command[command.index("--output") + 1])
        raw = Path(command[command.index("--store") + 1])
        job = json.loads(spec.read_text())
        output.mkdir(parents=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"posterior")
        raw.with_suffix(".loglikelihood.npz").write_bytes(b"array")
        log.write_text("worker")
        write_json(output / "sampling-start.json", job)
        write_json(output / "job.json", job)
        write_json(output / "inputs.json", {"fixture": True})
        write_json(output / "membership.json", {"fixture": True})
        (output / "sampling-diagnostics.csv").write_text("r_hat\n1.0\n")
        write_json(output / "result.json", {"posterior_sha256": sha256(raw)})
        return {"returncode": 2 if failure else 0, "reason": "worker_exit", "elapsed_seconds": 0.01}

    monkeypatch.setattr(runner, "supervise", supervise)
    return calls


def test_three_node_invocations_charge32_once_and_preserve_original77(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=3)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (109, 80, 19)
    assert s["sumatra_path_amendment"]["next_node"] == 3 and s["status"] == "path_checkpoint"
    runner.run(tmp_path, resume=True, max_nodes=3)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert s["calls_charged"] == 109 and s["calls_started"] == 83
    assert len(calls) == 6 and all(1 <= v[1] <= 600 for v in calls)


def test_failed_node_retains_partial_and_all_reserved_slots_without_retry(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch, failure=True)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert (
        s["status"] == "path_needs_review"
        and s["calls_charged"] == 109
        and s["calls_started"] == 78
    )
    assert s["sumatra_path_amendment"]["next_node"] == 0
    assert s["sumatra_path_amendment"]["attempts"][0]["outcome"] == "runtime_failure"
    with pytest.raises(ValueError, match="requires reviewed reconciliation"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1 and list((tmp_path / runner.STORE).glob("*.nc"))


def test_changed_prefix_stops_before_another_sampler(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=1)
    path = tmp_path / runner.OUTPUT / "jobs/primary-node-01.log"
    path.write_text("changed")
    with pytest.raises(ValueError, match="closure changed"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


def test_complete_path_replays_without_rewriting_frozen_summary(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=3)
    for _ in range(10):
        runner.run(tmp_path, resume=True, max_nodes=3)
    assert len(calls) == 32
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert (
        s["status"] == "path_computations_complete"
        and s["calls_charged"] == s["calls_started"] == 109
    )
    summary = tmp_path / runner.OUTPUT / "run-summary.json"
    digest = sha256(summary)
    runner.run(tmp_path, resume=True, max_nodes=3)
    assert sha256(summary) == digest and len(calls) == 32


def test_invalid_invocation_limit_is_rejected_before_design_or_outcome_loading(tmp_path):
    with pytest.raises(ValueError, match="one through three"):
        runner.run(tmp_path, max_nodes=4)


def test_changed_primary_aggregate_blocks_repeat_before_another_sampler(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=3)
    for _ in range(4):
        runner.run(tmp_path, resume=True, max_nodes=3)
    assert len(calls) == 15
    p = tmp_path / runner.OUTPUT / "primary-path-result.json"
    p.write_text("{}")
    with pytest.raises(ValueError, match="aggregate score"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 15


def test_reset_private_active_time_is_refused_by_retained_receipt(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=1)
    p = tmp_path / runner.STATE
    s = json.loads(p.read_text())
    s["sumatra_path_amendment"]["active_seconds"] = 0.0
    write_json(p, s)
    with pytest.raises(ValueError, match="cannot be reset"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


def test_removed_mandatory_diagnostics_cannot_be_hidden_in_private_map(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=1)
    removed = tmp_path / runner.OUTPUT / "jobs/primary-node-01/sampling-diagnostics.csv"
    removed.unlink()
    p = tmp_path / runner.STATE
    s = json.loads(p.read_text())
    s["sumatra_path_amendment"]["attempts"][0]["files"].pop(str(removed.relative_to(tmp_path)))
    write_json(p, s)
    with pytest.raises(ValueError, match="mandatory node"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field",
    [
        "path_amendment",
        "continuation",
        "precision_amendment",
        "completion",
        "accepted",
        "plan_sha256",
        "rehearsal_sha256",
        "next_fold",
    ],
)
def test_every_inherited_proof_is_bound_before_a_new_node(tmp_path, field):
    state = {
        "path_amendment": {},
        "continuation": {},
        "precision_amendment": {},
        "completion": {},
        "accepted": [{"case_id": "old"}],
        "plan_sha256": "plan",
        "rehearsal_sha256": "review",
        "next_fold": 19,
    }
    design = {
        "files": {},
        "gate": {"inherited_parent_sha256": runner.inherited_parent_sha256(state)},
    }
    if isinstance(state[field], dict):
        state[field]["changed"] = True
    elif isinstance(state[field], list):
        state[field].append({"changed": True})
    else:
        state[field] = "changed"
    with pytest.raises(ValueError, match="four inherited ledgers"):
        runner.conserved_parent(tmp_path, state, design)


def test_preexisting_global_stop_keeps_all77_slots_and_parent_bytes(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    path = tmp_path / runner.STATE
    before = path.read_bytes()
    (tmp_path / runner.PARENT_OUTPUT / "STOP").write_text("stop")
    with pytest.raises(ValueError, match="STOP present"):
        runner.run(tmp_path)
    assert path.read_bytes() == before and calls == []
    assert not (tmp_path / runner.OUTPUT).exists()


def test_current_job_limit_counts_raw_file_as_well_as_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "quota_failure", lambda *args: None)
    monkeypatch.setattr(runner, "parent_floors", lambda *args: [])
    current = tmp_path / runner.OUTPUT / "jobs/primary-node-01"
    current.mkdir(parents=True)
    raw = tmp_path / runner.STORE / "primary-node-01.nc"
    raw.parent.mkdir(parents=True)
    with raw.open("wb") as stream:
        stream.truncate(runner.MAX_JOB + 1)
    assert runner.path_quota_failure(tmp_path, [], current, gate={}) == "sumatra_path_job_storage"


def test_final_metadata_overshoot_cannot_retain_success(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    summary = tmp_path / runner.OUTPUT / "run-summary.json"
    monkeypatch.setattr(
        runner, "path_quota_failure", lambda *args, **kw: "late" if summary.exists() else None
    )
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_nodes=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert state["calls_charged"] == 109 and state["calls_started"] == 78
    assert state["status"] == json.loads(summary.read_text())["status"] == "path_storage_failure"
    assert len(calls) == 1


@pytest.mark.parametrize("role", ["primary", "repeat"])
def test_new_aggregate_json_cannot_overwrite_a_racing_file(tmp_path, monkeypatch, role):
    fixture(tmp_path, monkeypatch)
    (tmp_path / runner.STORE).mkdir(parents=True, exist_ok=True)
    nodes = {(r, j): np.full((4, 2000), -10.0) for r in ["primary", "repeat"] for j in range(17)}
    design = {"held": np.array([0]), "lane": SimpleNamespace(y=np.array([2.0]))}
    if role == "repeat":
        runner.summarize_path(tmp_path, design, nodes, "primary")
        write_json(
            tmp_path / runner.OUTPUT / "jobs/repeat-node-00/result.json",
            {"posterior_sha256": "b" * 64},
        )
    target = (
        tmp_path
        / runner.OUTPUT
        / ("primary-path-result.json" if role == "primary" else "independent-repeat-check.json")
    )
    original_open = Path.open

    def racing_open(path, mode="r", *args, **kw):
        if path == target and mode == "x":
            with original_open(path, "w") as stream:
                stream.write("racing evidence")
        return original_open(path, mode, *args, **kw)

    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(FileExistsError):
        runner.summarize_path(tmp_path, design, nodes, role)
    assert target.read_text() == "racing evidence"
    if role == "primary":
        assert not (tmp_path / runner.STORE / "primary-combined-influences.npz").exists()
