"""Same-ledger path allocation, failure retention, bounded batches and no duplicate calls."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_curvature_path as runner


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
        "status": "precision_or_diagnostic_failure",
        "calls_charged": 6,
        "calls_started": 6,
        "next_fold": 2,
        "current": None,
        "accepted": [{}, {}],
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


def test_three_node_invocations_charge32_once_and_preserve_original_six(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_nodes=3)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (38, 9, 2)
    assert s["path_amendment"]["next_node"] == 3 and s["status"] == "path_checkpoint"
    runner.run(tmp_path, resume=True, max_nodes=3)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert s["calls_charged"] == 38 and s["calls_started"] == 12
    assert len(calls) == 6 and all(1 <= v[1] <= 600 for v in calls)


def test_failed_node_retains_partial_and_all_reserved_slots_without_retry(tmp_path, monkeypatch):
    calls = fixture(tmp_path, monkeypatch, failure=True)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    s = json.loads((tmp_path / runner.STATE).read_text())
    assert (
        s["status"] == "path_needs_review" and s["calls_charged"] == 38 and s["calls_started"] == 7
    )
    assert s["path_amendment"]["next_node"] == 0
    assert s["path_amendment"]["attempts"][0]["outcome"] == "runtime_failure"
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
        and s["calls_charged"] == s["calls_started"] == 38
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
    s["path_amendment"]["active_seconds"] = 0.0
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
    s["path_amendment"]["attempts"][0]["files"].pop(str(removed.relative_to(tmp_path)))
    write_json(p, s)
    with pytest.raises(ValueError, match="mandatory node"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1
