"""Closed-prefix CV accounting and rehearsal gating, using dummy process receipts."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival import model_curvature_sequence as worker
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_validation_report import write_table
from scripts import run_arrival_curvature_sequences as runner


def fixture(root, monkeypatch, *, failure=None):
    cases = []
    members = {}
    for j in range(29):
        identity = f"fold-{j:03d}"
        n = [2, 3, 2][j] if j < 3 else 1
        events = [f"e{j}-{k}" for k in range(n)]
        records = {e: [f"r-{e}"] for e in events}
        cases.append(
            {
                "id": identity,
                "kind": "mean-curvature",
                "target": "NCEI-native-duration",
                "prior": "base",
                "sequence": f"q{j}",
                "draws": 2000,
                "tune": 1000,
                "cores": 2,
                "seed": 2856110800 + 1000 * j,
            }
        )
        members[identity] = {
            "train": ["training-record"],
            "test": [v[0] for v in records.values()],
            "held_events": events,
            "event_records": records,
            "sequence": f"q{j}",
            "charged_call_slots": 1 + n,
        }
    assert sum(v["charged_call_slots"] for v in members.values()) == 62
    for name in ["stub.py", runner.SELF]:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture-source")
    files = {p: sha256(root / p) for p in ["stub.py", runner.SELF]}
    parent = root / "parent"
    parent.mkdir()
    (parent / "retained").write_bytes(b"123")
    store = root / runner.STORE
    cache_env = {
        "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
        "NUMBA_CACHE_DIR": str(store / "cache/numba"),
        "MPLCONFIGDIR": str(store / "cache/matplotlib"),
    }
    gate = {
        "cases": cases,
        "memberships": members,
        "max_sampler_call_slots": runner.MAX_CALLS,
        "nominal_sampler_call_slots": 62,
        "global_max_bytes": runner.MAX_GLOBAL,
        "local_max_bytes": runner.MAX_LOCAL,
        "cache_max_bytes": runner.MAX_CACHE,
        "job_max_bytes": runner.MAX_JOB,
        "next_invocation_reserve_bytes": runner.RESERVE,
        "timeout_seconds": runner.TIMEOUT,
        "timeout_scope": "whole_fold_all_ensembles_and_scoring",
        "cache_environment": cache_env,
        "concurrency": 1,
        "automatic_retries": 0,
        "parent_minimum_bytes": {"parent": 3},
        "files": files,
    }
    write_json(root / worker.GATE, gate)
    pins = {**files, worker.GATE: sha256(root / worker.GATE)}
    monkeypatch.setattr(runner, "make_design", lambda r: (cases, members))
    monkeypatch.setattr(runner, "parent_roots", lambda r: [r / "parent"])
    monkeypatch.setattr(worker, "CONSUMED", ["stub.py"])
    monkeypatch.setattr(worker, "verify_gate", lambda *a: pins)
    monkeypatch.setattr(runner, "git_sha", lambda r: "fixture")
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda n: None)
    monkeypatch.setattr(runner, "os", SimpleNamespace(environ={}, getpid=lambda: 123))
    calls = []

    def simulated(command, log, stop, timeout):
        assert timeout == 1200
        case = json.loads(Path(command[command.index("--job") + 1]).read_text())
        attempt = Path(command[command.index("--output") + 1])
        raw = Path(command[command.index("--store") + 1])
        attempt.mkdir(parents=True)
        raw.mkdir(parents=True)
        log.write_text("dummy-process\n")
        calls.append(case["id"])
        membership = members[case["id"]]
        write_json(
            attempt / "sampling-starts/00.json",
            {**case, "phase": "training", "event": None, "seed": case["seed"]},
        )
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "runtime":
            (raw / "00-training.nc").write_bytes(b"partial")
            return {"returncode": 1, "reason": "worker_exit"}
        for k, event in enumerate([None, *membership["held_events"]]):
            phase = "training" if event is None else "augmented"
            spec = {**case, "phase": phase, "event": event, "seed": case["seed"] + k}
            folder = attempt / "ensembles" / f"{k:02d}-{phase}"
            posterior = raw / f"{k:02d}-{phase}.nc"
            posterior.write_bytes(b"dummy-NC")
            write_json(attempt / "sampling-starts" / f"{k:02d}.json", spec)
            write_json(folder / "job.json", spec)
            write_json(
                folder / "inputs.json",
                {
                    "files": {p: pins[p] for p in [*worker.CONSUMED, worker.GATE]},
                    "source_files": {"fixture": True},
                },
            )
            included = membership["train"] + (
                [] if event is None else membership["event_records"][event]
            )
            write_json(folder / "membership.json", {"included": included})
            write_json(
                folder / "result.json",
                {
                    "job": spec,
                    "posterior": str(posterior.relative_to(root)),
                    "posterior_sha256": sha256(posterior),
                    "diagnostics": {"screen_passed": True},
                },
            )
            (folder / "sampling-diagnostics.csv").write_text("fixture\n")
        arrays = raw / "bridge-arrays.npz"
        arrays.write_bytes(b"dummy-arrays")
        write_json(attempt / "job.json", case)
        write_json(attempt / "inputs.json", {"files": pins, "source_files": {"fixture": True}})
        write_json(
            attempt / "membership.json", {k: membership[k] for k in ["train", "test", "sequence"]}
        )
        predictions = [
            {"record_id": r, "event_id": e, "prediction_precision_passed": True}
            for e, records in membership["event_records"].items()
            for r in records
        ]
        write_table(attempt / "held-out-record-predictions.csv", predictions)
        scores = [
            {"event_id": e, "records": len(records), "precision_passed": True}
            for e, records in membership["event_records"].items()
        ]
        write_table(attempt / "event-joint-scores.csv", scores)
        write_json(
            attempt / "result.json",
            {
                "job": case,
                "status": "computed_pending_review",
                "sampler_calls_started": membership["charged_call_slots"],
                "score_precision_passed": True,
                "prediction_precision_passed": True,
                "observation_measure": "native_minutes_Jacobian_already_applied_once",
                "bridge_arrays_sha256": sha256(arrays),
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
                "events": scores,
            },
        )
        return {"returncode": 0, "reason": "worker_exit"}

    monkeypatch.setattr(runner, "supervise", simulated)
    return calls, cases, members


def accept_rehearsal(root):
    state = json.loads((root / runner.STATE).read_text())
    first = state["accepted"][0]
    files = {
        **first["files"],
        first["receipt"]: first["receipt_sha256"],
        runner.OUTPUT + "/plan.json": sha256(root / runner.OUTPUT / "plan.json"),
    }
    write_json(
        root / runner.REHEARSAL,
        {
            "status": "accepted_first_curvature_sequence",
            "independent_checker": True,
            "files": files,
        },
    )


def test_conserved62nominal_slots_requires_independent_rehearsal_before_continuation(
    tmp_path, monkeypatch
):
    calls, _, _ = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    with pytest.raises(ValueError, match="rehearsal required"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1
    accept_rehearsal(tmp_path)
    for _ in range(10):
        runner.run(tmp_path, resume=True, max_folds=3)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert len(calls) == state["next_fold"] == 29
    assert state["calls_started"] == state["calls_charged"] == 62
    assert state["status"] == "complete"


@pytest.mark.parametrize("failure", ["runtime", "interrupt"])
def test_failed_dispatch_charges_full_reserved_slots_retains_partial_and_never_retries(
    tmp_path, monkeypatch, failure
):
    calls, _, _ = fixture(tmp_path, monkeypatch, failure=failure)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert len(calls) == 1 and state["calls_charged"] == 3 and state["calls_started"] == 1
    assert (tmp_path / runner.OUTPUT / "jobs/fold-000.supervisor.json").exists()
    with pytest.raises(ValueError, match="reviewed reconciliation"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["omitted-proof", "charged-reset", "unknown-raw", "changed-file"]
)
def test_corrupted_or_omitted_prefix_cannot_dispatch_again(tmp_path, monkeypatch, change):
    calls, _, _ = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    accept_rehearsal(tmp_path)
    path = tmp_path / runner.STATE
    state = json.loads(path.read_text())
    if change == "omitted-proof":
        state["accepted"][0]["files"].clear()
        write_json(path, state)
    elif change == "charged-reset":
        state["accepted"][0]["charged_slots"] = 0
        state["calls_charged"] = 0
        state["calls_started"] = 0
        write_json(path, state)
    elif change == "unknown-raw":
        (tmp_path / runner.STORE / "unknown-partial.nc").write_bytes(b"partial")
    else:
        (tmp_path / runner.STORE / "fold-000/00-training.nc").write_bytes(b"changed")
    with pytest.raises(ValueError):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


def test_initial_invocation_cannot_skip_first_only_review_gate(tmp_path):
    with pytest.raises(ValueError, match="single first-fold"):
        runner.run(tmp_path, max_folds=3)


def test_inclusive_call_ceiling_stops_before_next_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_CALLS", 3)
    calls, _, _ = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    accept_rehearsal(tmp_path)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, resume=True, max_folds=3)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert (
        state["calls_charged"] == 3
        and len(calls) == 1
        and state["status"] == "stop_or_budget_failure"
    )


def test_parent_byte_floor_blocks_deleted_retained_data(tmp_path, monkeypatch):
    calls, _, _ = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    accept_rehearsal(tmp_path)
    (tmp_path / "parent/retained").unlink()
    with pytest.raises(ValueError, match="parent accounting"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 1


def test_missing_gate_cannot_reach_outcome_design_loader(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("outcomes reached before gate")

    monkeypatch.setattr(runner, "make_design", forbidden)
    with pytest.raises(FileNotFoundError):
        runner.run(tmp_path)


def test_local_headroom_is_reserved_before_a_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_LOCAL", runner.RESERVE)
    calls, _, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert not calls and state["calls_charged"] == 0 and state["status"] == "stop_or_budget_failure"


def test_post_summary_trip_updates_public_and_private_failure_status(tmp_path, monkeypatch):
    calls, _, _ = fixture(tmp_path, monkeypatch)

    def trip(root, *args):
        return "post_summary" if (root / runner.OUTPUT / "run-summary.json").exists() else None

    monkeypatch.setattr(runner, "quota_failure", trip)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    private = json.loads((tmp_path / runner.STATE).read_text())
    public = json.loads((tmp_path / runner.OUTPUT / "run-summary.json").read_text())
    assert len(calls) == 1 and private["status"] == public["status"] == "storage_failure"


def test_terminal_validation_is_read_only_and_still_checks_raw_and_rehearsal(tmp_path, monkeypatch):
    calls, _, _ = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    accept_rehearsal(tmp_path)
    for _ in range(10):
        runner.run(tmp_path, resume=True, max_folds=3)
    summary = tmp_path / runner.OUTPUT / "run-summary.json"
    before = summary.read_bytes()
    runner.run(tmp_path, resume=True)
    assert summary.read_bytes() == before and len(calls) == 29
    extra = tmp_path / runner.STORE / "unknown.nc"
    extra.write_bytes(b"unclosed")
    with pytest.raises(ValueError, match="unexpected raw"):
        runner.run(tmp_path, resume=True)
    extra.unlink()
    (tmp_path / runner.REHEARSAL).unlink()
    with pytest.raises(ValueError, match="rehearsal required"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 29
