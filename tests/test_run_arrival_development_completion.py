"""Synthetic metadata/runtime tests. No real native tables, posterior or sampler."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_development_completion as c


def fixture(root, monkeypatch, outcome="accepted_resolution"):
    old = c.old
    for p in old.r.parent_roots(root):
        p.mkdir(parents=True, exist_ok=True)
        (p / "floor").write_bytes(b"retained")
    oldstate = root / old.STATE
    oldstate.parent.mkdir(parents=True, exist_ok=True)
    oldstate.write_bytes(b"PRIVATE original failed history stays byte-identical")
    pins = {}

    def put(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            write_json(path, value)
        pins[name] = sha256(path)

    for n in [c.SELF, c.TEST, old.SELF, old.TEST]:
        put(n, b"immutable runtime source")
    freeze = {"training_references": {}}
    put(old.fit.data.FREEZE, freeze)
    jobs: list[dict[str, Any]] = [
        dict(
            id=f"dev-check-{i}",
            order=i,
            role="check_evaluate",
            model_key=f"t{i}:distance:selected",
            seed=700 + i,
            training_reference={"kind": "historical"},
        )
        for i in range(6)
    ]
    external = old.external_paths(root, freeze)
    for name in external:
        put(name, b"external reference metadata bytes")
    kernel_files = dict(pins)
    put(old.fit.GATE, {"jobs": jobs, "files": kernel_files})
    prediction = (
        old.fit.CHECK_OUTPUT + "/jobs/" + jobs[0]["id"] + "/held-out-record-predictions.csv"
    )
    put(prediction, b"original predictions unchanged")
    lease = old.CONTROL + "/.controller.lock"
    failed = dict(
        phase="check",
        job_id=jobs[0]["id"],
        cost=0,
        start_markers=0,
        outcome="needs_review",
        files={prediction: pins[prediction], lease: "a" * 64},
        receipt=old.CONTROL + "/attempts/check/first.json",
    )
    put(failed["receipt"], failed)
    failed["receipt_sha256"] = pins[failed["receipt"]]
    baseline_name = c.CONTROL + "/baseline-state.json"
    put(
        baseline_name,
        dict(
            schema_version=1,
            status="frozen_failed_development_check_history",
            original_state_sha256=sha256(oldstate),
            calls_charged=0,
            calls_started=0,
            original_job=jobs[0],
            failed_attempt=failed,
            source_references={old.fit.GATE: pins[old.fit.GATE]},
        ),
    )
    registry_name = c.CONTROL + "/baseline-registry.json"
    registry_files = dict(pins)
    put(
        registry_name,
        dict(
            files=registry_files,
            original_state_sha256=sha256(oldstate),
            failed_attempt=failed,
            released_ephemeral_files={
                lease: {"sha256": "a" * 64, "disposition": "released_exclusive_lease"}
            },
        ),
    )
    resolved = c.NUMERICAL_OUTPUT + "/case-000/result.json"
    if outcome == "accepted_resolution":
        put(resolved, {"source_role": "frozen_check_numerical_resolution", "original_job": jobs[0]})
    review_name = c.CONTROL + "/case0-review.json"
    put(
        review_name,
        dict(
            status=c.CASE0_STATUS,
            independent_checker=True,
            case0_outcome=outcome,
            original_job=jobs[0],
            original_state_sha256=sha256(oldstate),
            specification_freeze_sha256=pins[old.fit.data.FREEZE],
            primary_aggregate_available=outcome == "accepted_resolution",
            resolved_result=resolved if outcome == "accepted_resolution" else None,
            resolved_result_sha256=pins.get(resolved),
            prediction_file=prediction,
            prediction_sha256=pins[prediction],
            files=dict(pins),
        ),
    )
    worker = SimpleNamespace()
    calls, proofs = [], []

    def verify(root, role=None):
        phase = (
            "check"
            if role == "check_training"
            else "full_development"
            if role
            else "full_design_recovery"
        )
        name = old.phase_gate(phase)
        gate = json.loads((root / name).read_text())
        return dict(
            gate=gate, files={**gate["files"], name: sha256(root / name)}, freeze=freeze, specs={}
        )

    worker.verify_gate = verify

    def paths(root, job):
        phase = "check" if job["role"] == "check_evaluate" else job["role"]
        output = {
            "check": old.fit.CHECK_OUTPUT,
            "full_design_recovery": old.RECOVERY_OUTPUT,
            "full_development": old.fit.FULL_OUTPUT,
        }[phase]
        store = old.RECOVERY_STORE if phase == "full_design_recovery" else old.fit.STORE
        return root / output / "jobs" / job["id"], None if phase == "check" else root / store / (
            job["id"] + ".nc"
        )

    worker.case_paths = paths

    def case(root, job, source):
        proofs.append(job["id"])
        folder, raw = paths(root, job)
        manifest = json.loads((folder / "output-checksums.json").read_text())
        files = {str((folder / n).relative_to(root)): h for n, h in manifest.items()}
        files[str((folder / "output-checksums.json").relative_to(root))] = sha256(
            folder / "output-checksums.json"
        )
        if raw:
            files[str(raw.relative_to(root))] = sha256(raw)
        old.previous._unchanged(root, files)
        return {"files": files}

    worker.case_artifacts = case
    monkeypatch.setattr(old, "consumer", lambda phase: worker)
    monkeypatch.setattr(old, "git_sha", lambda root: "a" * 40)

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        calls.append(job)
        state = json.loads((root / c.STATE).read_text())
        assert state["current"]["job_id"] == job["id"]
        folder, raw = paths(root, job)
        folder.mkdir(parents=True)
        if raw:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"synthetic raw")
            write_json(folder / "sampling-start.json", job)
        else:
            assert "--store" not in command
        write_json(folder / "job.json", job)
        write_json(folder / "result.json", {"status": old.fit.SUCCESS})
        write_json(folder / "output-checksums.json", {p.name: sha256(p) for p in folder.iterdir()})
        log.write_text("synthetic child")
        return {"returncode": 0, "reason": "worker_exit"}

    monkeypatch.setattr(old, "supervise", supervise)

    def gate(phase="check"):
        history = {}
        if (root / c.STATE).is_file():
            state = json.loads((root / c.STATE).read_text())
            for entry in state["phases"].values():
                history[entry["plan"]] = entry["plan_sha256"]
                if "summary" in entry:
                    history[entry["summary"]] = entry["summary_sha256"]
                for record in entry["accepted"]:
                    history.update(record["files"])
                    history[record["receipt"]] = record["receipt_sha256"]
        pins.update(history)
        if phase != "check":
            count = 6 if phase == "full_design_recovery" else 3
            other = [
                dict(id=f"{phase}-{i}", order=i, role=phase, seed=100 + i) for i in range(count)
            ]
            put(old.phase_gate(phase), {"jobs": other, "files": kernel_files})
        else:
            other = jobs[1:]
        if phase != "check" and not (root / old.fit.data.CHECK_REVIEW).exists():
            put(
                old.fit.data.CHECK_REVIEW,
                dict(
                    status="accepted_frozen_arrival_development_check",
                    independent_checker=True,
                    completed_once=True,
                    no_retuning=True,
                    specification_freeze_sha256=pins[old.fit.data.FREEZE],
                    case0_review=review_name,
                    case0_review_sha256=pins[review_name],
                    files={**pins},
                ),
            )
        if phase == "full_development":
            put(
                old.RECOVERY_REVIEW,
                dict(
                    status="accepted_frozen_full_development_design_checks",
                    independent_checker=True,
                    specification_freeze_sha256=pins[old.fit.data.FREEZE],
                    files={**pins},
                ),
            )
        body = dict(
            status="accepted_frozen_arrival_development_completion_execution",
            independent_checker=True,
            phase=phase,
            path_bindings=c.bindings(root),
            resources=old.fit.resources(),
            max_sampler_call_slots=9,
            inherited_calls={
                "charged": 6 if phase == "full_development" else 0,
                "started": 6 if phase == "full_development" else 0,
            },
            reserved_outcomes="sealed",
            no_retuning=True,
            baseline_registry=registry_name,
            baseline_registry_sha256=pins[registry_name],
            baseline_state=baseline_name,
            baseline_state_sha256=pins[baseline_name],
            original_state_sha256=sha256(oldstate),
            case0_review=review_name,
            worker_gate=old.phase_gate(phase),
            worker_gate_sha256=pins[old.phase_gate(phase)],
            jobs=other,
            parent_minimum_bytes={
                str(p.relative_to(root)): old.r.byte_count(p) for p in old.r.parent_roots(root)
            },
            external_reference_files={p: pins[p] for p in external},
            files=dict(pins),
        )
        put(c.gate_path(phase), body)
        return body

    gate()
    return SimpleNamespace(
        gate=gate,
        calls=calls,
        proofs=proofs,
        pins=pins,
        jobs=jobs,
        original=oldstate.read_bytes(),
        baseline=baseline_name,
        registry=registry_name,
        review=review_name,
        worker=worker,
    )


@pytest.mark.parametrize("outcome", ["accepted_resolution", "accepted_unresolved_gap"])
def test_remaining_five_zero_call_jobs_preserve_failure_and_original_state(
    tmp_path, monkeypatch, outcome
):
    f = fixture(tmp_path, monkeypatch, outcome)
    first = c.run(tmp_path, max_jobs=4)
    assert first["calls_charged"] == first["calls_started"] == 0
    state = c.run(tmp_path, resume=True, max_jobs=4)
    assert state["phases"]["check"]["status"] == c.SUCCESS
    assert [j["id"] for j in f.calls] == [j["id"] for j in f.jobs[1:]]
    assert (tmp_path / c.old.STATE).read_bytes() == f.original
    assert not (tmp_path / c.old.CONTROL / ".controller.lock").exists()
    before = (tmp_path / c.STATE).read_bytes()
    c.run(tmp_path, resume=True)
    assert (tmp_path / c.STATE).read_bytes() == before


def test_g_first_two_actual_starts_pause_until_pilot_and_full_phase_gated(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    c.run(tmp_path, resume=True, max_jobs=4)
    f.gate("full_design_recovery")
    state = c.run(tmp_path, phase="full_design_recovery", resume=True, max_jobs=4)
    assert state["calls_charged"] == state["calls_started"] == 2
    assert state["phases"]["full_design_recovery"]["status"] == "awaiting_sampler_pilot_review"
    needed = {
        p: h
        for a in state["phases"]["full_design_recovery"]["accepted"]
        for p, h in {**a["files"], a["receipt"]: a["receipt_sha256"]}.items()
    }
    write_json(
        tmp_path / c.PILOT,
        dict(
            status="accepted_development_two_sampler_runtime_pilots",
            independent_checker=True,
            sampler_pilot_job_ids=state["sampler_pilot_job_ids"],
            specification_freeze_sha256=f.pins[c.old.fit.data.FREEZE],
            files=needed,
        ),
    )
    state = c.run(tmp_path, phase="full_design_recovery", resume=True, max_jobs=4)
    assert state["calls_started"] == 6
    f.gate("full_development")
    state = c.run(tmp_path, phase="full_development", resume=True, max_jobs=4)
    assert state["calls_charged"] == state["calls_started"] == 9
    assert (tmp_path / c.old.STATE).read_bytes() == f.original


@pytest.mark.parametrize(
    "fault", ["unreviewed", "prediction", "counter", "private_body", "lease", "original_drift"]
)
def test_admission_rejects_unsafe_baseline_or_disposition_before_dispatch(
    tmp_path, monkeypatch, fault
):
    f = fixture(tmp_path, monkeypatch)
    name = f.review
    if fault == "original_drift":
        (tmp_path / c.old.STATE).write_bytes(b"foreign")
    elif fault == "lease":
        q = tmp_path / c.old.CONTROL / ".controller.lock"
        q.write_bytes(b"not recreated proof")
    else:
        name = f.baseline if fault == "private_body" else f.review
        body = json.loads((tmp_path / name).read_text())
        if fault == "private_body":
            body["phases"] = {}
        elif fault == "unreviewed":
            body["independent_checker"] = False
        elif fault == "prediction":
            body["prediction_sha256"] = "0" * 64
        else:
            body["primary_aggregate_available"] = False
        write_json(tmp_path / name, body)
        gate = json.loads((tmp_path / c.gate_path("check")).read_text())
        gate["files"][name] = sha256(tmp_path / name)
        if name == f.baseline:
            gate["baseline_state_sha256"] = sha256(tmp_path / name)
        write_json(tmp_path / c.gate_path("check"), gate)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert f.calls == [] and not (tmp_path / c.STATE).exists()


def test_old_stop_prevents_any_plan_or_state_write(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    p = tmp_path / c.old.CONTROL / "STOP"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("stop")
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert not (tmp_path / c.STATE).exists() and not f.calls


def test_failed_child_retains_charge_raw_and_cannot_resume(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    c.run(tmp_path, resume=True, max_jobs=4)
    f.gate("full_design_recovery")
    original = c.old.supervise

    def fail(*args):
        result = original(*args)
        return {**result, "returncode": 2}

    monkeypatch.setattr(c.old, "supervise", fail)
    with pytest.raises(ValueError):
        c.run(tmp_path, phase="full_design_recovery", resume=True)
    state = json.loads((tmp_path / c.STATE).read_text())
    assert state["calls_charged"] == state["calls_started"] == 1 and state["current"] is not None
    raw = tmp_path / c.old.RECOVERY_STORE / "full_design_recovery-0.nc"
    assert raw.is_file()
    with pytest.raises(ValueError):
        c.run(tmp_path, phase="full_design_recovery", resume=True)
    assert len(f.calls) == 6


def test_foreign_state_after_child_preserved_and_no_next_dispatch(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = c.old.supervise

    def foreign(*args):
        value = original(*args)
        (tmp_path / c.STATE).write_bytes(b"FOREIGN")
        return value

    monkeypatch.setattr(c.old, "supervise", foreign)
    with pytest.raises(ValueError):
        c.run(tmp_path, max_jobs=4)
    assert (tmp_path / c.STATE).read_bytes() == b"FOREIGN" and len(f.calls) == 1


def test_new_prefix_late_unlisted_file_rejected_and_source_drift_before_child_retained(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    original = c.old.supervise

    def extra(*args):
        value = original(*args)
        folder, _ = f.worker.case_paths(tmp_path, f.calls[-1])
        (folder / "extra").write_bytes(b"late")
        return value

    monkeypatch.setattr(c.old, "supervise", extra)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert json.loads((tmp_path / c.STATE).read_text())["status"] == "needs_review"
    assert len(f.calls) == 1


def test_warm_cache_fresh_bytes_and_actual_new_case_full_verification(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    assert all(f.proofs.count(j["id"]) == 1 for j in f.jobs[1:5])
    state = json.loads((tmp_path / c.STATE).read_text())
    record = state["phases"]["check"]["accepted"][0]
    name = next(p for p in record["worker_files"] if p.endswith("result.json"))
    (tmp_path / name).write_bytes(b"same path changed bytes")
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)
    assert len(f.calls) == 4


def test_source_drift_inside_leases_prevents_plan_and_charge(tmp_path, monkeypatch):
    from contextlib import contextmanager

    f = fixture(tmp_path, monkeypatch)
    original = c.old.r._leases

    @contextmanager
    def leases(root):
        with original(root):
            (root / c.SELF).write_bytes(b"changed after admission")
            yield

    monkeypatch.setattr(c.old.r, "_leases", leases)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert not (tmp_path / c.STATE).exists() and not f.calls
    assert not c.plan_path(tmp_path, "check").exists()


def test_source_failure_after_precharge_keeps_charge_without_child(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    c.run(tmp_path, resume=True, max_jobs=4)
    f.gate("full_design_recovery")
    original = c.save

    def save(path, state, expected):
        original(path, state, expected)
        if state["current"] is not None:
            (tmp_path / c.SELF).write_bytes(b"changed after allocation")

    monkeypatch.setattr(c, "save", save)
    with pytest.raises(ValueError):
        c.run(tmp_path, phase="full_design_recovery", resume=True)
    state = json.loads((tmp_path / c.STATE).read_text())
    assert state["calls_charged"] == 1 and state["calls_started"] == 0
    assert state["current"] is not None and len(f.calls) == 5


def test_new_attempt_bytes_participate_in_job_cap(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path)
    state = json.loads((tmp_path / c.STATE).read_text())
    job = f.calls[0]
    admission = c.admit(tmp_path, "check")
    paths = c.old.paths(tmp_path, job, f.worker)
    monkeypatch.setattr(c.old, "quota", lambda *a, **kw: None)
    before = sum(p.stat().st_size for p in paths[2:]) + c.old.r.byte_count(paths[0])
    monkeypatch.setattr(c.old.r, "MAX_JOB", before + 1)
    assert c.attempt_path(tmp_path, "check", job).stat().st_size > 1
    with pytest.raises(ValueError, match="combined"):
        c.safe(tmp_path, admission, paths)
    assert state["calls_started"] == 0


def test_late_summary_extra_retains_closed_attempts_but_forbids_success(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    original = c.old.new_json

    def write(path, value):
        original(path, value)
        if path.name == "check-summary.json":
            (path.parent / "unlisted").write_bytes(b"late")

    monkeypatch.setattr(c.old, "new_json", write)
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)
    state = json.loads((tmp_path / c.STATE).read_text())
    assert state["status"] == "needs_review" and len(state["phases"]["check"]["attempts"]) == 5
    assert len(f.calls) == 5 and (tmp_path / c.old.STATE).read_bytes() == f.original


@pytest.mark.parametrize("mode", ["timeout", "storage_stop"])
def test_real_process_group_timeout_or_storage_stop_retains_partial_and_releases_leases(
    tmp_path, monkeypatch, mode
):
    import os
    import sys
    import time

    from scripts.run_arrival_model_validation import supervise as real_supervise

    f = fixture(tmp_path, monkeypatch)
    pid_file = tmp_path / c.old.fit.CHECK_OUTPUT / "jobs" / f.jobs[1]["id"] / "descendant.txt"
    original_quota = c.old.quota

    def quota(*args, **kw):
        if mode == "storage_stop" and pid_file.exists():
            return "injected_storage_limit"
        return original_quota(*args, **kw)

    monkeypatch.setattr(c.old, "quota", quota)
    child = (
        "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\n"
        "while True:\n p.write_text(str(time.monotonic_ns()))\n time.sleep(.03)\n"
    )
    code = (
        "import pathlib,subprocess,sys,time; "
        "p=pathlib.Path(sys.argv[1]);p.mkdir(parents=True); "
        f"d=subprocess.Popen([sys.executable,'-c',{child!r},str(p/'heartbeat.txt')]); "
        "(p/'descendant.txt').write_text(str(d.pid)); "
        "(p/'partial').write_text('retained'); time.sleep(60)"
    )

    def supervise(command, log, stop, timeout):
        folder = Path(command[command.index("--output") + 1])
        return real_supervise(
            [sys.executable, "-c", code, str(folder)], log, stop, 1 if mode == "timeout" else 5
        )

    monkeypatch.setattr(c.old, "supervise", supervise)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    state = json.loads((tmp_path / c.STATE).read_text())
    assert (
        state["status"] == "needs_review" and state["calls_started"] == state["calls_charged"] == 0
    )
    assert (pid_file.parent / "partial").read_text() == "retained"
    pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        # A terminated orphan may remain a zombie briefly. Its previously live
        # heartbeat must stop; an alive descendant would keep changing bytes.
        heartbeat = pid_file.parent / "heartbeat.txt"
        before = heartbeat.read_bytes()
        time.sleep(0.2)
        assert heartbeat.read_bytes() == before
    assert not (tmp_path / c.CONTROL / ".controller.lock").exists()
    assert not any(
        (tmp_path / p / ".controller.lock").exists() for p in [c.old.r.OLD_OUTPUT, c.old.r.OUTPUT]
    )
    assert (tmp_path / c.old.STATE).read_bytes() == f.original


def test_incomplete_check_cannot_be_relabeled_complete_to_enter_g(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    c.run(tmp_path)
    state = json.loads((tmp_path / c.STATE).read_text())
    state["phases"]["check"]["status"] = c.SUCCESS
    write_json(tmp_path / c.STATE, state)
    f.gate("full_design_recovery")
    with pytest.raises(ValueError, match="completed phase"):
        c.run(tmp_path, phase="full_design_recovery", resume=True)
    assert len(f.calls) == 1


def test_missing_case0_review_pin_rejects_before_worker_boundary(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    gate = json.loads((tmp_path / c.gate_path("check")).read_text())
    gate["files"].pop(f.review)
    write_json(tmp_path / c.gate_path("check"), gate)

    def forbidden(*args):
        raise AssertionError("worker must not be consulted")

    monkeypatch.setattr(c.old, "consumer", forbidden)
    with pytest.raises(ValueError):
        c.admit(tmp_path, "check")
    assert not f.calls


def test_completed_summary_cannot_be_changed_and_resealed_in_private_state(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=4)
    c.run(tmp_path, resume=True, max_jobs=4)
    state = json.loads((tmp_path / c.STATE).read_text())
    entry = state["phases"]["check"]
    summary = json.loads((tmp_path / entry["summary"]).read_text())
    summary["calls_started"] = 1
    write_json(tmp_path / entry["summary"], summary)
    entry["summary_sha256"] = sha256(tmp_path / entry["summary"])
    write_json(tmp_path / c.STATE, state)
    with pytest.raises(ValueError, match="summary"):
        c.run(tmp_path, resume=True)


@pytest.mark.parametrize("outcome", ["accepted_resolution", "accepted_unresolved_gap"])
@pytest.mark.parametrize("fault", ["unknown-file", "empty-directory", "symlink", "fifo"])
def test_all_retained_numerical_roots_are_closed_even_after_resume_and_gap(
    tmp_path, monkeypatch, outcome, fault
):
    import os

    f = fixture(tmp_path, monkeypatch, outcome)
    c.run(tmp_path)
    before = (tmp_path / c.STATE).read_bytes()
    root = tmp_path / c.NUMERICAL_OUTPUT
    root.mkdir(exist_ok=True)
    path = root / "unreviewed"
    if fault == "unknown-file":
        path.write_bytes(b"retained unknown failure")
    elif fault == "empty-directory":
        path.mkdir()
    elif fault == "symlink":
        path.symlink_to(tmp_path / c.SELF)
    else:
        os.mkfifo(path)
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)
    assert (tmp_path / c.STATE).read_bytes() == before and len(f.calls) == 1


@pytest.mark.parametrize("scope", c.EXTRA_ROOTS)
def test_numeric_design_and_failure_science_parents_participate_in_inventory(
    tmp_path, monkeypatch, scope
):
    f = fixture(tmp_path, monkeypatch)
    root = tmp_path / scope
    root.mkdir(exist_ok=True, parents=True)
    (root / "unknown-empty").mkdir()
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert not f.calls and not (tmp_path / c.STATE).exists()


@pytest.mark.parametrize("cap", ["file", "case", "global", "local"])
def test_reviewed_numerical_files_are_counted_for_actual_caps(tmp_path, monkeypatch, cap):
    f = fixture(tmp_path, monkeypatch)
    root = tmp_path / c.NUMERICAL_OUTPUT
    file = root / "case-000" / "retained-large.bin"
    size = {
        "file": c.old.r.FILE_MAX + 1,
        "case": c.old.r.MAX_JOB + 1,
        "global": 4 * 1024**2,
        "local": 2200 * 1024,
    }[cap]
    with file.open("wb") as stream:
        stream.truncate(size)
    gate = json.loads((tmp_path / c.gate_path("check")).read_text())
    gate["files"][str(file.relative_to(tmp_path))] = sha256(file)
    write_json(tmp_path / c.gate_path("check"), gate)
    admission = c.admit(tmp_path, "check")
    if cap in {"global", "local"}:
        monkeypatch.setattr(c.old.r, "MIB", 1024)
    reason = c.quota(tmp_path, admission)
    assert reason is not None
    if cap == "case":
        assert reason == "numerical_case_job_cap"
    if cap == "local":
        assert reason == "numerical_local_storage"
    assert not f.calls


def test_numerical_roots_are_not_double_counted_when_already_in_old_budgets(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    file = tmp_path / c.NUMERICAL_OUTPUT / "case-000" / "retained.bin"
    with file.open("wb") as stream:
        stream.truncate(1100 * 1024)
    gate = json.loads((tmp_path / c.gate_path("check")).read_text())
    gate["files"][str(file.relative_to(tmp_path))] = sha256(file)
    write_json(tmp_path / c.gate_path("check"), gate)
    admission = c.admit(tmp_path, "check")
    old_roots, global_roots = c.old.roots, c.old.global_roots
    monkeypatch.setattr(c.old, "roots", lambda root: old_roots(root) + [root / c.NUMERICAL_OUTPUT])
    monkeypatch.setattr(
        c.old, "global_roots", lambda root: global_roots(root) + [root / c.NUMERICAL_OUTPUT]
    )
    monkeypatch.setattr(c.old.r, "MIB", 1024)
    assert c.quota(tmp_path, admission) is None
    assert not f.calls
