"""Synthetic resource-only continuation: unchanged science, full proofs, restored bindings."""

# pyright: basic
from __future__ import annotations

import json
import threading

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_continuation as continuation
from tests.test_arrival_sensitivity_controller import accept_pilots, fixture

r = continuation.r


def setup(root, monkeypatch):
    jobs, science, old_pins, calls = fixture(root, monkeypatch)
    r.run(root, max_cases=2)
    accept_pilots(root)
    state = json.loads((root / r.STATE).read_text())
    write_json(root / continuation.BASELINE, state)
    snapshots = {}
    for i in range(12):
        name = continuation.DESIGN + f"/ledger-snapshots/{i:02d}.json"
        write_json(root / name, {"old_ledger": i, "counter": 128})
        snapshots[name] = sha256(root / name)
    for name in [
        continuation.SELF,
        continuation.TEST,
        "analysis/arrival/model_sensitivity_references.py",
    ]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen resource-only source")
    write_json(root / continuation.PROJECTION, {"planning_not_completion_guarantee": True})
    paths = continuation.external_reference_paths(root, r.parent_roots(root))
    assert len(paths) == 10
    external = {}
    for i, name in enumerate(paths):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        size = continuation.EXTERNAL_BYTES // 10 + (i == 0) * (continuation.EXTERNAL_BYTES % 10)
        path.write_bytes(b"x" * size)
        external[name] = sha256(path)
    required = {
        continuation.SELF,
        continuation.TEST,
        "analysis/arrival/model_sensitivity_references.py",
        continuation.PROJECTION,
        continuation.BASELINE,
        continuation.PLAN,
        r.PILOT_REVIEW,
    }
    pins = {**old_pins, **snapshots, **external, **{p: sha256(root / p) for p in required}}
    for entry in state["accepted"]:
        pins.update(entry["files"])
        pins[entry["receipt"]] = entry["receipt_sha256"]
    gate = {
        "status": "accepted_exploration_sensitivity_resource_continuation",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "resources": continuation.resources(),
        "path_bindings": r.path_bindings(root),
        "files": pins,
        "planning_projection": continuation.PROJECTION,
        "old_ledger_snapshots": snapshots,
        "external_reference_files": external,
        "original_gate_sha256": old_pins[r.GATE],
        "original_plan_sha256": sha256(root / continuation.PLAN),
        "pilot_review_sha256": sha256(root / r.PILOT_REVIEW),
    }
    write_json(root / continuation.GATE, gate)
    monkeypatch.setattr(continuation, "git_sha", lambda root: "a" * 40)
    return jobs, gate, calls


def reseal(root, gate, name):
    gate["files"][name] = sha256(root / name)
    write_json(root / continuation.GATE, gate)


def test_original_plan_resources_first_two_and_counters_preserved_with_new_receipts(
    tmp_path, monkeypatch
):
    jobs, gate, calls = setup(tmp_path, monkeypatch)
    original_plan = (tmp_path / continuation.PLAN).read_bytes()
    original_resources = r.resources()
    state = json.loads((tmp_path / r.STATE).read_text())
    first_two = state["accepted"][:2]
    bindings = {
        name: getattr(r, name)
        for name in [
            "working_bytes",
            "quota_failure",
            "supervise",
            "_proofs",
            "_unchanged",
            "_leases",
        ]
    }
    continuation.run(tmp_path, max_cases=2)
    assert len(calls) == 4
    state = json.loads((tmp_path / r.STATE).read_text())
    assert (state["next_case"], state["calls_charged"], state["calls_started"]) == (4, 4, 4)
    assert state["accepted"][:2] == first_two
    assert (tmp_path / continuation.PLAN).read_bytes() == original_plan
    assert r.resources() == original_resources
    assert all(getattr(r, name) is value for name, value in bindings.items())
    process = json.loads(r.case_paths(tmp_path, jobs[2])[-1].read_text())
    assert process["resource_amendment_gate_sha256"] == sha256(tmp_path / continuation.GATE)
    receipts = list((tmp_path / continuation.CONTROL / "receipts").glob("*"))
    assert len(receipts) == 1
    before, after = [
        json.loads((receipts[0] / name).read_text()) for name in ["before.json", "after.json"]
    ]
    assert before["state"]["next_case"] == 2 and after["after_state"]["next_case"] == 4
    assert before["invocation_git_sha"] == after["invocation_git_sha"] == "a" * 40
    assert after["postcondition_failure"] is None
    assert before["original_plan_sha256"] == gate["original_plan_sha256"]
    continuation.run(tmp_path, max_cases=1)
    assert len(calls) == 5  # Same resource gate admits any later validated successful prefix.


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "stale-source",
        "caps",
        "plan-binding",
        "snapshots",
        "external-set",
        "external-bytes",
        "state-pin",
        "current",
        "refund",
        "no-baseline",
        "STOP",
    ],
)
def test_missing_stale_or_reset_gate_rejected_before_mutations(tmp_path, monkeypatch, bad):
    _, gate, calls = setup(tmp_path, monkeypatch)
    if bad == "missing":
        (tmp_path / continuation.GATE).unlink()
    elif bad == "stale-source":
        (tmp_path / continuation.SELF).write_text("changed")
    elif bad == "caps":
        gate["resources"]["global_max_bytes"] += 1
    elif bad == "plan-binding":
        gate["original_plan_sha256"] = "0" * 64
    elif bad == "snapshots":
        gate["old_ledger_snapshots"].pop(next(iter(gate["old_ledger_snapshots"])))
    elif bad == "external-set":
        gate["external_reference_files"].pop(next(iter(gate["external_reference_files"])))
    elif bad == "external-bytes":
        path = next(iter(gate["external_reference_files"]))
        (tmp_path / path).write_bytes(b"x")
        digest = sha256(tmp_path / path)
        gate["external_reference_files"][path] = gate["files"][path] = digest
    elif bad == "state-pin":
        gate["files"][r.STATE] = sha256(tmp_path / r.STATE)
    elif bad in {"current", "refund"}:
        state = json.loads((tmp_path / r.STATE).read_text())
        state["current"] = "unreconciled" if bad == "current" else None
        if bad == "refund":
            state["calls_charged"] = 1
        write_json(tmp_path / r.STATE, state)
    elif bad == "no-baseline":
        gate["files"].pop(continuation.BASELINE)
    else:
        (tmp_path / r.OUTPUT / "STOP").write_text("stop")
    if bad != "missing":
        write_json(tmp_path / continuation.GATE, gate)
    before = (tmp_path / r.STATE).read_bytes()
    with pytest.raises(ValueError):
        continuation.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == before and len(calls) == 2
    assert not (tmp_path / continuation.CONTROL / "receipts").exists()


def test_quota_new_bounds_and_reserve_keep_old_constants_and_complete_checks(tmp_path, monkeypatch):
    jobs, gate, _ = setup(tmp_path, monkeypatch)
    checked = continuation.verify_continuation(tmp_path)
    parents, old_gate = checked["parents"], checked["old_gate"]
    old_caps = r.MAX_GLOBAL, r.MAX_LOCAL, r.MAX_CACHE, r.MAX_JOB

    def quota(working, reserve=False, current=None):
        return continuation.quota_failure(
            tmp_path, parents, old_gate, current, reserve=reserve, working=lambda *args: working
        )

    assert quota(2500 * r.MIB) is None  # New global ceiling, not old2GiB.
    assert quota(continuation.GLOBAL_MAX + 1) == "global_storage"
    assert quota(continuation.GLOBAL_MAX - r.RESERVE + 1, reserve=True) == "global_storage"
    assert old_caps == (r.MAX_GLOBAL, r.MAX_LOCAL, r.MAX_CACHE, r.MAX_JOB)
    original_count = r.byte_count

    def local(*roots):
        if len(roots) == 3 and roots[0] == tmp_path / r.DESIGN:
            return continuation.LOCAL_MAX + 1
        return original_count(*roots)

    monkeypatch.setattr(r, "byte_count", local)
    assert quota(0) == "local_storage"

    def cache(*roots):
        return (
            r.MAX_CACHE + 1 if roots == (tmp_path / r.STORE / "cache",) else original_count(*roots)
        )

    monkeypatch.setattr(r, "byte_count", cache)
    assert quota(0) == "cache_storage"
    monkeypatch.setattr(r, "byte_count", original_count)
    folder, raw, *_ = r.case_paths(tmp_path, jobs[2])
    folder.mkdir()
    with raw.open("wb") as stream:
        stream.truncate(r.MAX_JOB + 1)
    assert quota(0, current=jobs[2]) == "combined_job_storage"
    raw.unlink()
    oversized = folder / "oversize.bin"
    with oversized.open("wb") as stream:
        stream.truncate(r.FILE_MAX + 1)
    assert quota(0) == "per_file_storage"
    oversized.unlink()
    (folder / "link").symlink_to(tmp_path / continuation.PLAN)
    assert quota(0) == "symlink_storage"
    (folder / "link").unlink()
    (parents[0] / "floor.bin").unlink()
    assert quota(0) == "parent_floor_or_storage_scan_failure"


def test_override_restoration_on_failed_worker_and_no_refund(tmp_path, monkeypatch):
    _, _, calls = setup(tmp_path, monkeypatch)
    before = r.supervise

    def failed(*args, **kwargs):
        value = before(*args, **kwargs)
        return {**value, "returncode": 2, "reason": "worker_exit"}

    monkeypatch.setattr(r, "supervise", failed)
    saved = {
        name: getattr(r, name)
        for name in [
            "working_bytes",
            "quota_failure",
            "supervise",
            "_proofs",
            "_unchanged",
            "_leases",
        ]
    }
    with pytest.raises(SystemExit):
        continuation.run(tmp_path, max_cases=1)
    assert all(getattr(r, name) is value for name, value in saved.items())
    state = json.loads((tmp_path / r.STATE).read_text())
    assert len(calls) == 3 and state["calls_charged"] == state["calls_started"] == 3
    assert state["next_case"] == 2 and state["status"] == "sensitivity_needs_review"
    with pytest.raises(ValueError):
        continuation.run(tmp_path)


def test_parallel_proof_coverage_two_threads_and_failure_propagation(tmp_path, monkeypatch):
    jobs, _, _ = setup(tmp_path, monkeypatch)
    checked = continuation.verify_continuation(tmp_path)
    seen, threads, lock = [], set(), threading.Lock()
    barrier = threading.Barrier(2)

    def proof(root, job, pins, accepted):
        with lock:
            seen.append(job["id"])
            threads.add(threading.get_ident())
        barrier.wait(timeout=2)

    monkeypatch.setattr(r, "case_artifacts", proof)
    continuation.parallel_proofs(tmp_path, checked["state"], jobs, checked["old_pins"])
    assert sorted(seen) == sorted(j["id"] for j in jobs[:2]) and len(threads) == 2

    def bad_proof(*args):
        raise ValueError("synthetic proof failure")

    monkeypatch.setattr(r, "case_artifacts", bad_proof)
    with pytest.raises(ValueError, match="proof failure"):
        continuation.parallel_proofs(tmp_path, checked["state"], jobs, checked["old_pins"])
    monkeypatch.setattr(r, "case_artifacts", lambda *args: None)
    checked["state"]["attempts"][0]["receipt_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="identities changed"):
        continuation.parallel_proofs(tmp_path, checked["state"], jobs, checked["old_pins"])


def test_ambiguous_prior_receipt_and_late_source_failure_cannot_success(tmp_path, monkeypatch):
    _, _, calls = setup(tmp_path, monkeypatch)
    checked = continuation.verify_continuation(tmp_path)
    name = f"002-{continuation._state_receipt(checked['snapshot'])['sha256']}"
    folder = tmp_path / continuation.CONTROL / "receipts" / name
    folder.mkdir(parents=True)
    before = (tmp_path / r.STATE).read_bytes()
    with pytest.raises(ValueError, match="receipt"):
        continuation.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == before and len(calls) == 2
    folder.rmdir()

    def source_drift(root, *, resume, max_cases):
        assert resume is True
        with r._leases(root):
            (root / continuation.SELF).write_text("drift during run")

    monkeypatch.setattr(r, "run", source_drift)
    saved = r._unchanged
    with pytest.raises(ValueError, match="postcondition"):
        continuation.run(tmp_path)
    assert r._unchanged is saved
    assert json.loads((tmp_path / r.STATE).read_text())["status"] == "sensitivity_needs_review"
    assert (tmp_path / r.OUTPUT / "STOP").is_file()
    assert json.loads((folder / "after.json").read_text())["postcondition_failure"]


def test_working_bytes_adds_only_exact_outside_references_and_projection_is_planning(
    tmp_path, monkeypatch
):
    _, _, _ = setup(tmp_path, monkeypatch)
    checked = continuation.verify_continuation(tmp_path)
    old = r.working_bytes(tmp_path, checked["parents"])
    original_resources = r.resources()
    with continuation.overrides(tmp_path, checked):
        assert r.working_bytes(tmp_path, checked["parents"]) == old + continuation.EXTERNAL_BYTES
        assert r.resources() == original_resources
        assert r.quota_failure(tmp_path, checked["parents"], checked["old_gate"]) is None
    projection = continuation.storage_projection(tmp_path, checked)
    assert projection["planning_not_completion_guarantee"] is True
    assert projection["remaining_cases"] == 53
    assert projection["hard_job_envelope_plus_reserve_bytes"] > continuation.LOCAL_MAX
    assert projection["outside_reference_bytes"] == continuation.EXTERNAL_BYTES


def test_pilot_transitive_closure_mandatory_before_proof_loader(tmp_path, monkeypatch):
    _, gate, calls = setup(tmp_path, monkeypatch)
    state = json.loads((tmp_path / r.STATE).read_text())
    missing = next(iter(state["accepted"][0]["files"]))
    gate["files"].pop(missing)
    write_json(tmp_path / continuation.GATE, gate)
    monkeypatch.setattr(r, "case_artifacts", lambda *a: pytest.fail("early science proof loader"))
    with pytest.raises(ValueError, match="closure"):
        continuation.run(tmp_path)
    assert len(calls) == 2


def test_receipt_ancestor_symlink_prevents_write(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    alternate = tmp_path / "alternate-receipts"
    alternate.mkdir()
    (tmp_path / continuation.CONTROL / "receipts").symlink_to(alternate)
    before = (tmp_path / r.STATE).read_bytes()
    with pytest.raises(ValueError, match="receipt"):
        continuation.run(tmp_path)
    assert not list(alternate.iterdir()) and (tmp_path / r.STATE).read_bytes() == before


def test_private_state_race_before_original_lease_refuses_overwrite(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    raced = []

    def changed(root, *, resume, max_cases):
        state = json.loads((root / r.STATE).read_text())
        state["external_owner"] = "changed"
        write_json(root / r.STATE, state)
        raced.append((root / r.STATE).read_bytes())
        with r._leases(root):
            pytest.fail("changed private state admitted")

    monkeypatch.setattr(r, "run", changed)
    old_bindings = r._leases, r.quota_failure
    with pytest.raises(ValueError, match="private state changed"):
        continuation.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == raced[0]
    assert (r._leases, r.quota_failure) == old_bindings
    assert not (tmp_path / continuation.CONTROL / "receipts").exists()


def test_late_receipt_cap_failure_stops_without_success_and_restores_bindings(
    tmp_path, monkeypatch
):
    setup(tmp_path, monkeypatch)

    def no_dispatch(root, *, resume, max_cases):
        with r._leases(root):
            pass

    monkeypatch.setattr(r, "run", no_dispatch)
    checks = []

    def late(*args, **kwargs):
        checks.append(1)
        return "global_storage" if len(checks) > 1 else None

    monkeypatch.setattr(continuation, "quota_failure", late)
    saved = r._leases, r.quota_failure, r._unchanged
    with pytest.raises(ValueError, match="postcondition"):
        continuation.run(tmp_path)
    assert (r._leases, r.quota_failure, r._unchanged) == saved
    state = json.loads((tmp_path / r.STATE).read_text())
    assert state["calls_charged"] == state["calls_started"] == state["next_case"] == 2
    assert state["status"] == "sensitivity_needs_review"
    failures = list((tmp_path / continuation.CONTROL / "receipts").glob("*/failure.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())["reason"] == "global_storage"
    assert (tmp_path / r.OUTPUT / "STOP").is_file()


@pytest.mark.parametrize("unclosed", [True, False])
def test_earlier_prefix_unclosed_or_changed_receipt_blocks_later_resume(
    tmp_path, monkeypatch, unclosed
):
    _, _, calls = setup(tmp_path, monkeypatch)
    continuation.run(tmp_path, max_cases=1)
    state = (tmp_path / r.STATE).read_bytes()
    folder = next((tmp_path / continuation.CONTROL / "receipts").iterdir())
    after = folder / "after.json"
    if unclosed:
        after.unlink()  # Simulate death after state advanced but before receipt closed.
    else:
        value = json.loads(after.read_text())
        value["before_state"]["sha256"] = "f" * 64
        write_json(after, value)
    with pytest.raises(ValueError, match="receipt chain"):
        continuation.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == state and len(calls) == 3
    assert len(list((tmp_path / continuation.CONTROL / "receipts").iterdir())) == 1


def test_new_source_drift_inside_acquired_leases_blocks_before_receipt_write(tmp_path, monkeypatch):
    from contextlib import contextmanager

    _, _, calls = setup(tmp_path, monkeypatch)
    original = r._leases

    @contextmanager
    def race(root):
        with original(root):
            (root / continuation.SELF).write_text("changed after lease acquisition")
            yield

    monkeypatch.setattr(r, "_leases", race)
    before = (tmp_path / r.STATE).read_bytes()
    with pytest.raises(ValueError, match="source identity changed"):
        continuation.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == before and len(calls) == 2
    assert not (tmp_path / continuation.CONTROL / "receipts").exists()
    assert r._leases is race
    assert not (tmp_path / r.OUTPUT / ".controller.lock").exists()
    assert not (tmp_path / r.OLD_OUTPUT / ".controller.lock").exists()


def test_immediate_prechild_new_source_guard_preserves_charge_without_launch(tmp_path, monkeypatch):
    _, _, calls = setup(tmp_path, monkeypatch)
    original = r.atomic_state

    def race(path, state):
        original(path, state)
        if state.get("current") is not None:
            (tmp_path / continuation.SELF).write_text("changed after spec and precharge")

    monkeypatch.setattr(r, "atomic_state", race)
    saved = r.supervise, r._leases, r._unchanged
    with pytest.raises(SystemExit):
        continuation.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / r.STATE).read_text())
    assert len(calls) == 2 and state["calls_charged"] == 3
    assert state["calls_started"] == state["next_case"] == 2
    assert state["status"] == "sensitivity_needs_review"
    assert (r.supervise, r._leases, r._unchanged) == saved
    assert (tmp_path / r.OUTPUT / "STOP").is_file()
    with pytest.raises(ValueError):
        continuation.run(tmp_path)
