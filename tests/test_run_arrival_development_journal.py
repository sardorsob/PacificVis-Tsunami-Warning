"""Journal tests use synthetic metadata/files and fake workers; never native Y or MCMC."""

# pyright: basic
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_development_journal as j


def fixture(root, monkeypatch):
    old = j.old
    pins = {}
    calls = []
    proofs = []

    def put(name, value):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            p.write_bytes(value)
        else:
            write_json(p, value)
        pins[name] = sha256(p)
        return pins[name]

    put(old.STATE, b"original failed private bytes")
    put(j.c2.STATE, b"second failed private bytes")
    # These are hash-only historical identities, not scientific files.
    states = {k: pins.pop(k) for k in [old.STATE, j.c2.STATE]}
    for name in [j.SELF, j.TEST, j.c2.SELF, j.c2.TEST, old.SELF, old.TEST]:
        put(name, b"fixed code")
    put(j.data.FREEZE, {"training_references": {}})
    original = [
        dict(
            id=f"dev-check-{i}",
            order=i,
            role="check_evaluate",
            model_key=f"t{i}:base:selected",
            seed=100 + i,
            training_reference={"kind": "historical"},
        )
        for i in range(6)
    ]
    put(j.fit.GATE, dict(jobs=original, files=dict(pins)))
    put("data/processed/reference.nc", b"outside reference")
    for original_job in original[:2]:
        put(
            j.fit.CHECK_OUTPUT + "/jobs/" + original_job["id"] + "/held-out-record-predictions.csv",
            b"record_id,prediction\nsynthetic,1\n",
        )
    put(j.numerical.CASE_OUTPUT + "/result.json", {"status": j.fit.SUCCESS})
    receipt = j.c2.CONTROL + "/attempts/check/failed-job1.json"
    oldfailed = dict(
        phase="check",
        job_id=original[1]["id"],
        role="check_evaluate",
        cost=0,
        start_markers=0,
        outcome="needs_review",
        files={j.fit.GATE: pins[j.fit.GATE]},
        receipt=receipt,
    )
    put(receipt, oldfailed)
    baseline = dict(
        schema_version=1,
        private_state_bodies_copied=False,
        calls_charged=0,
        calls_started=0,
        original_state_sha256=states[old.STATE],
        failed_continuation_state_sha256=states[j.c2.STATE],
        source_references={receipt: pins[receipt]},
        failed_attempt={**oldfailed, "receipt_sha256": pins[receipt]},
        unattempted_job_ids=[x["id"] for x in original[2:]],
    )
    put(j.BASELINE, baseline)
    for index, name in enumerate([j.CASE0, j.CASE1]):
        put(
            name,
            dict(
                status=j.c2.CASE0_STATUS
                if index == 0
                else "accepted_frozen_development_runner_up_numerical_gap",
                independent_checker=True,
                original_job=original[index],
                **(
                    {"case0_outcome": "accepted_resolution"}
                    if index == 0
                    else {"case1_outcome": "accepted_unresolved_gap"}
                ),
                original_state_sha256=states[old.STATE],
                failed_continuation_state_sha256=states[j.c2.STATE],
                specification_freeze_sha256=pins[j.data.FREEZE],
                primary_aggregate_available=index == 0,
                without_crossing_aggregate_available=False,
                resolved_result=j.numerical.CASE_OUTPUT + "/result.json" if index == 0 else None,
                resolved_result_sha256=pins[j.numerical.CASE_OUTPUT + "/result.json"]
                if index == 0
                else None,
                prediction_file=j.fit.CHECK_OUTPUT
                + "/jobs/"
                + original[index]["id"]
                + "/held-out-record-predictions.csv",
                prediction_sha256=pins[
                    j.fit.CHECK_OUTPUT
                    + "/jobs/"
                    + original[index]["id"]
                    + "/held-out-record-predictions.csv"
                ],
                original_attempt_receipt=receipt,
                original_attempt_receipt_sha256=pins[receipt],
                reserved_outcomes="sealed",
                files=dict(pins),
            ),
        )

    def numeric(root, pins):
        return dict(
            semantics_verified=True,
            proof_scope="independent_cold_replay_plus_fresh_complete_bytes",
            scientific_review=j.CASE0,
            scientific_review_sha256=pins[j.CASE0],
            original_job=original[0],
            review_files=json.loads((root / j.CASE0).read_text())["files"],
            files={
                j.numerical.CASE_OUTPUT + "/result.json": pins[
                    j.numerical.CASE_OUTPUT + "/result.json"
                ]
            },
            status=j.fit.SUCCESS,
        )

    monkeypatch.setattr(j.numerical, "case_artifacts", numeric)
    worker = SimpleNamespace()

    def paths(root, job):
        phase = "check" if job["role"] == "check_evaluate" else job["role"]
        output = {
            "check": j.fit.CHECK_OUTPUT,
            "full_design_recovery": old.RECOVERY_OUTPUT,
            "full_development": j.fit.FULL_OUTPUT,
        }[phase]
        store = old.RECOVERY_STORE if phase == "full_design_recovery" else j.fit.STORE
        return root / output / "jobs" / job["id"], None if phase == "check" else root / store / (
            job["id"] + ".nc"
        )

    worker.case_paths = paths

    def verify(root, role=None):
        phase = (
            "check"
            if role == "check_training"
            else ("full_development" if role else "full_design_recovery")
        )
        name = old.phase_gate(phase)
        gate = json.loads((root / name).read_text())
        return dict(
            gate=gate,
            files={**gate["files"], name: sha256(root / name)},
            freeze={"training_references": {}},
        )

    worker.verify_gate = verify

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
    monkeypatch.setattr(old, "external_paths", lambda root, freeze: ["data/processed/reference.nc"])
    monkeypatch.setattr(old.r, "parent_floors", lambda root, gate: None)
    monkeypatch.setattr(j.c2, "quota", lambda *args, **kwargs: None)
    monkeypatch.setattr(old, "git_sha", lambda root: "a" * 40)

    @contextmanager
    def parent_leases(root):
        lock = root / "parent.lock"
        lock.write_text("exclusive")
        try:
            yield
        finally:
            lock.unlink()

    monkeypatch.setattr(old.r, "_leases", parent_leases)
    behavior = {"exit": 0, "late": None}

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        calls.append(job)
        phase = "check" if job["role"] == "check_evaluate" else job["role"]
        allocation = j.allocation_path(root, phase, job)
        assert allocation.is_file() and json.loads(allocation.read_text())["cost"] == old.cost(job)
        folder, raw = paths(root, job)
        folder.mkdir(parents=True)
        if raw:
            assert "--store" in command
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"synthetic raw")
        else:
            assert "--store" not in command
        for name in j._producer_names(phase) - {"output-checksums.json"}:
            value = (
                job
                if name in {"job.json", "sampling-start.json"}
                else (
                    {
                        "status": "needs_numerical_review",
                        "job": job,
                        "prediction_rows": 1,
                        "scoring_performed": True,
                        "sampler_call_started": False,
                    }
                    if name == "result.json"
                    else {}
                )
            )
            if name == "event-results.json":
                value = {"events": [{"predictions": {"status": "computed_pending_review"}}]}
            if name.endswith(".json"):
                write_json(folder / name, value)
            else:
                (folder / name).write_bytes(b"synthetic producer")
        write_json(folder / "output-checksums.json", {p.name: sha256(p) for p in folder.iterdir()})
        log.write_text("fake worker, no MCMC")
        if behavior["late"]:
            behavior["late"](job, folder)
        return {"returncode": behavior["exit"], "reason": "worker_exit"}

    monkeypatch.setattr(old, "supervise", supervise)

    def current_files():
        result = dict(pins)
        # Every later authority closes prior ordinary journal history and SCI.
        for base in j.old.roots(root):
            for p in base.rglob("*"):
                if p.is_file():
                    result[str(p.relative_to(root))] = sha256(p)
        return result

    def gate(phase="check"):
        if phase == "check":
            jobs = original[2:]
        else:
            jobs = [
                dict(
                    id=f"dev-{phase.replace('_', '-')}-{i}",
                    order=i,
                    role=phase,
                    model_key="base",
                    seed=200 + i,
                )
                for i in range(6 if phase == "full_design_recovery" else 3)
            ]
            put(old.phase_gate(phase), dict(jobs=jobs, files=current_files()))
        files = current_files()
        name = j.gate_path(phase)
        value = dict(
            status="accepted_frozen_arrival_development_journal_execution",
            independent_checker=True,
            confirmation_outcomes_parsed=True,
            reserved_outcomes="sealed",
            phase=phase,
            resources=j.fit.resources(),
            path_bindings=j.bindings(root),
            max_sampler_call_slots=9,
            no_retuning=True,
            baseline_history=j.BASELINE,
            baseline_history_sha256=pins[j.BASELINE],
            original_state_sha256=states[old.STATE],
            failed_continuation_state_sha256=states[j.c2.STATE],
            worker_gate=old.phase_gate(phase),
            worker_gate_sha256=files[old.phase_gate(phase)],
            jobs=jobs,
            inherited_calls={
                "charged": 6 if phase == "full_development" else 0,
                "started": 6 if phase == "full_development" else 0,
            },
            check_gap_reviews={
                x["id"]: str(j.gap_review_path(root, x).relative_to(root)) for x in original[2:]
            },
            external_reference_files={
                "data/processed/reference.nc": pins["data/processed/reference.nc"]
            },
            files=files,
        )
        put(name, value)
        return value

    gate()
    return SimpleNamespace(
        put=put,
        pins=pins,
        states=states,
        original=original,
        calls=calls,
        proofs=proofs,
        worker=worker,
        behavior=behavior,
        gate=gate,
        current_files=current_files,
    )


def test_real_journal_check_route_and_no_private_state(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path, max_jobs=4)
    a = j.admit(tmp_path, "check")
    r = j.journal_records(tmp_path, a)
    assert len(f.calls) == len(r["accepted_records"]) == 4 and len(f.proofs) == 8
    summary = json.loads(j.summary_path(tmp_path, "check").read_text())
    assert summary["calls_charged"] == summary["calls_started"] == 0
    assert [d["job_id"] for d in summary["logical_check_dispositions"]] == [
        x["id"] for x in f.original[:2]
    ]
    assert j.run(tmp_path, max_jobs=4) == r and len(f.calls) == 4
    assert all(sha256(tmp_path / name) == digest for name, digest in f.states.items())
    assert (
        not (tmp_path / j.CONTROL / ".journal.lock").exists()
        and not (tmp_path / "parent.lock").exists()
    )


def previous_review(root, f, phase):
    path = j.data.CHECK_REVIEW if phase == "check" else j.old.RECOVERY_REVIEW
    f.put(
        path,
        dict(
            status="accepted_frozen_arrival_development_check"
            if phase == "check"
            else "accepted_frozen_full_development_design_checks",
            independent_checker=True,
            specification_freeze_sha256=f.pins[j.data.FREEZE],
            completed_once=True,
            no_retuning=True,
            files=f.current_files(),
        ),
    )


def test_full_three_phase_journal_with_two_actual_pilot_guard(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path, max_jobs=4)
    previous_review(tmp_path, f, "check")
    f.gate("full_design_recovery")
    j.run(tmp_path, phase="full_design_recovery", max_jobs=4)
    assert len(f.calls) == 6  # four cost0 checks and two actual synthetic starts
    a = j.admit(tmp_path, "full_design_recovery")
    rows, _, charged, started, pilots = j.all_records(tmp_path, a, {})
    assert charged == started == 2
    f.put(
        j.PILOT,
        dict(
            status="accepted_development_two_sampler_runtime_pilots",
            independent_checker=True,
            sampler_pilot_job_ids=pilots,
            specification_freeze_sha256=f.pins[j.data.FREEZE],
            files=f.current_files(),
        ),
    )
    j.run(tmp_path, phase="full_design_recovery", max_jobs=4)
    previous_review(tmp_path, f, "full_design_recovery")
    f.gate("full_development")
    j.run(tmp_path, phase="full_development", max_jobs=4)
    summary = json.loads(j.summary_path(tmp_path, "full_development").read_text())
    assert summary["calls_charged"] == summary["calls_started"] == 9 and len(f.calls) == 13
    assert (
        summary["logical_check_dispositions"]
        == json.loads(j.summary_path(tmp_path, "check").read_text())["logical_check_dispositions"]
    )
    assert all(sha256(tmp_path / name) == digest for name, digest in f.states.items())


@pytest.mark.parametrize(
    "fault", ["source", "old_state", "new_state", "stop", "unknown", "directory", "symlink"]
)
def test_prelaunch_boundary_no_allocation(tmp_path, monkeypatch, fault):
    f = fixture(tmp_path, monkeypatch)
    if fault == "source":
        (tmp_path / j.SELF).write_text("changed")
    elif fault == "old_state":
        (tmp_path / j.old.STATE).write_text("changed")
    elif fault == "new_state":
        (tmp_path / j.c2.STATE).write_text("changed")
    elif fault == "stop":
        f.put(j.CONTROL + "/STOP", b"stop")
    elif fault == "unknown":
        f.put(j.CONTROL + "/unknown.json", {})
    elif fault == "directory":
        (tmp_path / j.CONTROL / "empty").mkdir()
    else:
        (tmp_path / j.CONTROL / "alias").symlink_to(tmp_path / j.BASELINE)
    with pytest.raises((ValueError, OSError)):
        j.run(tmp_path)
    assert not f.calls and not (tmp_path / j.CONTROL / "allocations").exists()


def test_partial_allocation_is_charged_and_never_retried(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)

    def crash(*args):
        raise KeyboardInterrupt("stopped")

    monkeypatch.setattr(j.old, "supervise", crash)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert j.allocation_path(tmp_path, "check", f.original[2]).exists()
    assert (
        json.loads(j.attempt_path(tmp_path, "check", f.original[2]).read_text())["outcome"]
        == "needs_review"
    )
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert not f.calls


def gap_review(root, f):
    a = j.admit(root, "check")
    rows = j.journal_records(root, a, pending=True)
    r = rows["attempt_records"][-1]
    job = a["gate"]["jobs"][len(rows["attempt_records"]) - 1]
    name = str(j.gap_review_path(root, job).relative_to(root))
    f.put(
        name,
        dict(
            status="accepted_frozen_development_check_numerical_gap",
            independent_checker=True,
            confirmation_outcomes_parsed=True,
            reserved_outcomes="sealed",
            original_job=job,
            failure_kind="numerical_precision_only",
            fully_computed_same_source=True,
            prediction_rows_precision_passed=1,
            prediction_file=str(
                (
                    j.old.paths(root, job, a["worker"])[0] / "held-out-record-predictions.csv"
                ).relative_to(root)
            ),
            prediction_sha256=r["files"][
                str(
                    (
                        j.old.paths(root, job, a["worker"])[0] / "held-out-record-predictions.csv"
                    ).relative_to(root)
                )
            ],
            primary_aggregate_available=False,
            without_crossing_aggregate_available=False,
            resolved_result=None,
            resolved_result_sha256=None,
            specification_freeze_sha256=f.pins[j.data.FREEZE],
            attempt=r["receipt"],
            attempt_sha256=r["receipt_sha256"],
            files={**a["files"], **r["files"], r["receipt"]: r["receipt_sha256"]},
        ),
    )
    return job, name


def test_explicit_check_gap_retains_failure_then_continues(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    f.behavior["exit"] = 2
    with pytest.raises(ValueError):
        j.run(tmp_path)
    job, name = gap_review(tmp_path, f)
    oldreceipt = sha256(j.attempt_path(tmp_path, "check", job))
    assert json.loads(j.attempt_path(tmp_path, "check", job).read_text())["gap_eligible"]
    j.run(tmp_path, apply_check_gap=job["id"])
    assert len(f.calls) == 1 and oldreceipt == sha256(j.attempt_path(tmp_path, "check", job))
    f.behavior["exit"] = 0
    j.run(tmp_path, max_jobs=4)
    s = json.loads(j.summary_path(tmp_path, "check").read_text())
    assert (
        len(s["accepted_records"]) == 3
        and len(s["attempt_records"]) == 4
        and len(s["logical_check_dispositions"]) == 3
    )
    assert s["logical_check_dispositions"][-1]["review"] == name


@pytest.mark.parametrize("fault", ["unknown", "source", "marker", "jobcap"])
def test_late_failure_retained_and_no_automatic_resume(tmp_path, monkeypatch, fault):
    f = fixture(tmp_path, monkeypatch)

    def late(job, folder):
        if fault == "unknown":
            (folder / "unlisted").write_bytes(b"x")
        if fault == "source":
            (tmp_path / j.SELF).write_text("drift")
        if fault == "marker":
            write_json(folder / "sampling-start.json", job)
        if fault == "jobcap":
            (folder / "result.json").write_bytes(b"x" * 512)
            monkeypatch.setattr(j.old.r, "MAX_JOB", 128)

    f.behavior["late"] = late
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1 and j.allocation_path(tmp_path, "check", f.original[2]).exists()
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1


@pytest.mark.parametrize("mutation", ["order", "cost", "receipt", "authority", "worker"])
def test_resealed_allocation_or_attempt_not_adopted(tmp_path, monkeypatch, mutation):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path)
    job = f.original[2]
    allocation = j.allocation_path(tmp_path, "check", job)
    attempt = j.attempt_path(tmp_path, "check", job)
    path = allocation if mutation in {"order", "cost", "authority", "worker"} else attempt
    value = json.loads(path.read_text())
    if mutation == "order":
        value["job"] = f.original[3]
    elif mutation == "cost":
        value["cost"] = 1
    elif mutation == "receipt":
        value["receipt"] = "elsewhere.json"
    elif mutation == "authority":
        value["authority_gate_sha256"] = "0" * 64
    else:
        value["worker_gate_sha256"] = "0" * 64
    write_json(path, value)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1


@pytest.mark.parametrize("fault", ["primary", "result", "prediction", "unanchored"])
def test_case0_strict_metadata_trust_required_before_plan(tmp_path, monkeypatch, fault):
    f = fixture(tmp_path, monkeypatch)
    if fault == "unanchored":
        original = j.numerical.case_artifacts
        monkeypatch.setattr(
            j.numerical,
            "case_artifacts",
            lambda *args: {**original(*args), "semantics_verified": False},
        )
    else:
        value = json.loads((tmp_path / j.CASE0).read_text())
        if fault == "primary":
            value["primary_aggregate_available"] = False
        if fault == "result":
            value["resolved_result"] = "foreign/result.json"
        if fault == "prediction":
            value["prediction_file"] = "foreign/predictions.csv"
        f.put(j.CASE0, value)
        f.gate()
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert not f.calls and not j.plan_path(tmp_path, "check").exists()


def test_inside_lease_drift_cannot_allocate(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)

    @contextmanager
    def leases(root):
        (root / j.SELF).write_text("changed under parent leases")
        yield

    monkeypatch.setattr(j.old.r, "_leases", leases)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert not f.calls and not j.plan_path(tmp_path, "check").exists()


def test_partial_fit_cost_survives_without_start_or_terminal_receipt(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path, max_jobs=4)
    previous_review(tmp_path, f, "check")
    f.gate("full_design_recovery")
    a = j.admit(tmp_path, "full_design_recovery")
    job = a["gate"]["jobs"][0]
    plan = j.plan_path(tmp_path, a["phase"])
    j.old.new_json(plan, j.phase_plan(tmp_path, a))
    spec = j.old.paths(tmp_path, job, a["worker"])[2]
    j.old.new_json(spec, job)
    j.old.new_json(
        j.allocation_path(tmp_path, a["phase"], job),
        dict(
            job=job,
            phase=a["phase"],
            cost=1,
            plan_sha256=sha256(plan),
            authority_gate_sha256=a["files"][j.gate_path(a["phase"])],
            worker_gate_sha256=a["files"][j.old.phase_gate(a["phase"])],
            job_id=job["id"],
            role=job["role"],
            plan=str(plan.relative_to(tmp_path)),
            authority_gate=j.gate_path(a["phase"]),
            worker_gate=j.old.phase_gate(a["phase"]),
            spec=str(j.old.paths(tmp_path, job, a["worker"])[2].relative_to(tmp_path)),
            spec_sha256=sha256(spec),
            invocation_git_sha="a" * 40,
        ),
    )
    assert j.journal_counters(tmp_path) == {"charged": 1, "started": 0}
    with pytest.raises(ValueError):
        j.run(tmp_path, phase="full_design_recovery")
    assert len(f.calls) == 4 and j.journal_counters(tmp_path)["charged"] == 1


@pytest.mark.parametrize("fault", ["predictions", "runtime", "source", "forged_role"])
def test_future_gap_cannot_waive_other_failure(tmp_path, monkeypatch, fault):
    f = fixture(tmp_path, monkeypatch)
    f.behavior["exit"] = 2
    with pytest.raises(ValueError):
        j.run(tmp_path)
    job, name = gap_review(tmp_path, f)
    value = json.loads((tmp_path / name).read_text())
    if fault == "predictions":
        value["prediction_rows_precision_passed"] = 0
    elif fault == "runtime":
        value["fully_computed_same_source"] = False
    elif fault == "source":
        value["files"].pop(j.SELF)
    else:
        value["original_job"] = {**job, "role": "full_development"}
    f.put(name, value)
    with pytest.raises(ValueError):
        j.run(tmp_path, apply_check_gap=job["id"])
    assert len(f.calls) == 1 and not j.disposition_path(tmp_path, job).exists()


def test_late_summary_write_failure_blocks_journal(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    real = j.old.new_json

    def write(path, value):
        real(path, value)
        if path == j.summary_path(tmp_path, "check"):
            (path.parent / "late-unknown").write_bytes(b"x")

    monkeypatch.setattr(j.old, "new_json", write)
    with pytest.raises(ValueError):
        j.run(tmp_path, max_jobs=4)
    assert len(f.calls) == 4 and (tmp_path / j.CONTROL / "failures").exists()
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 4


def test_post_lease_cleanup_drift_rejects_and_retains(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)

    @contextmanager
    def leases(root):
        try:
            yield
        finally:
            (root / j.old.STATE).write_text("foreign bytes preserved")

    monkeypatch.setattr(j.old.r, "_leases", leases)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1 and (tmp_path / j.old.STATE).read_text() == "foreign bytes preserved"
    assert (tmp_path / j.CONTROL / "failures").exists() and not (
        tmp_path / j.CONTROL / ".journal.lock"
    ).exists()


def test_gap_disposition_propagates_through_recovery_summary(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    f.behavior["exit"] = 2
    with pytest.raises(ValueError):
        j.run(tmp_path)
    job, _ = gap_review(tmp_path, f)
    j.run(tmp_path, apply_check_gap=job["id"])
    f.behavior["exit"] = 0
    j.run(tmp_path, max_jobs=4)
    previous_review(tmp_path, f, "check")
    f.gate("full_design_recovery")
    j.run(tmp_path, phase="full_design_recovery", max_jobs=2)
    a = j.admit(tmp_path, "full_design_recovery")
    _, _, _, _, pilots = j.all_records(tmp_path, a, {})
    f.put(
        j.PILOT,
        dict(
            status="accepted_development_two_sampler_runtime_pilots",
            independent_checker=True,
            sampler_pilot_job_ids=pilots,
            specification_freeze_sha256=f.pins[j.data.FREEZE],
            files=f.current_files(),
        ),
    )
    j.run(tmp_path, phase="full_design_recovery", max_jobs=4)
    check = json.loads(j.summary_path(tmp_path, "check").read_text())
    recovery = json.loads(j.summary_path(tmp_path, "full_design_recovery").read_text())
    assert recovery["logical_check_dispositions"] == check["logical_check_dispositions"]
    assert len(recovery["logical_check_dispositions"]) == 3


@pytest.mark.parametrize("phase", ["full_design_recovery", "full_development"])
def test_previous_phase_science_required_before_any_allocation(tmp_path, monkeypatch, phase):
    f = fixture(tmp_path, monkeypatch)
    f.gate(phase)
    with pytest.raises((ValueError, KeyError, OSError)):
        j.run(tmp_path, phase=phase)
    assert not f.calls and not (tmp_path / j.CONTROL / "allocations").exists()


def test_real_supervisor_timeout_retains_allocation_and_leases(tmp_path, monkeypatch):
    import sys

    from scripts.run_arrival_model_validation import supervise

    f = fixture(tmp_path, monkeypatch)

    def timeout(command, log, stop, seconds):
        return supervise([sys.executable, "-c", "import time;time.sleep(5)"], log, stop, 1)

    monkeypatch.setattr(j.old, "supervise", timeout)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    record = json.loads(j.attempt_path(tmp_path, "check", f.original[2]).read_text())
    process = tmp_path / (j.fit.CHECK_OUTPUT + "/jobs/" + f.original[2]["id"] + ".supervisor.json")
    assert (
        record["outcome"] == "needs_review"
        and json.loads(process.read_text())["reason"] == "timeout"
    )
    assert j.journal_counters(tmp_path) == {"charged": 0, "started": 0}
    assert (
        not (tmp_path / j.CONTROL / ".journal.lock").exists()
        and not (tmp_path / "parent.lock").exists()
    )
    with pytest.raises(ValueError):
        j.run(tmp_path)


def test_accepted_receipt_after_write_cap_failure_never_resumes(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    real = j.old.new_json

    def write(path, value):
        real(path, value)
        if path == j.attempt_path(tmp_path, "check", f.original[2]):
            monkeypatch.setattr(j.old.r, "MAX_JOB", 16)

    monkeypatch.setattr(j.old, "new_json", write)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1 and (tmp_path / j.CONTROL / "failures").exists()
    monkeypatch.setattr(j.old.r, "MAX_JOB", 32 * 1024**2)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 1


# Durable regressions from the independent four-group review.


@pytest.mark.parametrize(
    "field",
    [
        "job_id",
        "role",
        "plan",
        "authority_gate",
        "worker_gate",
        "spec",
        "spec_sha256",
        "invocation_git_sha",
    ],
)
def test_combined_guard_resealed_complete_allocation_identity_must_reject(
    tmp_path, monkeypatch, field
):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path, max_jobs=1)
    job = f.original[2]
    allocation = j.allocation_path(tmp_path, "check", job)
    attempt = j.attempt_path(tmp_path, "check", job)
    folder, _, _, _, process = j.old.paths(tmp_path, job, f.worker)
    value = json.loads(allocation.read_text())
    value[field] = "wrong" if field != "spec_sha256" else "f" * 64
    write_json(allocation, value)
    supervisor = json.loads(process.read_text())
    supervisor["allocation_sha256"] = sha256(allocation)
    if field == "invocation_git_sha":
        supervisor[field] = value[field]
    write_json(process, supervisor)
    record = json.loads(attempt.read_text())
    record["allocation_sha256"] = sha256(allocation)
    for path in [allocation, process]:
        record["files"][str(path.relative_to(tmp_path))] = sha256(path)
    write_json(attempt, record)
    with pytest.raises(ValueError):
        j.run(tmp_path, max_jobs=1)
    assert len(f.calls) == 1


def test_combined_guard_truthful_after_gap_exposure_admission(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    gate_path = j.gate_path("check")
    gate = json.loads((tmp_path / gate_path).read_text())
    gate["confirmation_outcomes_parsed"] = True
    f.put(gate_path, gate)
    admitted = j.admit(tmp_path, "check")
    assert admitted["gate"]["confirmation_outcomes_parsed"] is True


@pytest.mark.parametrize("drift", ["source", "unknown"])
def test_combined_guard_late_gap_disposition_failure_cannot_resume_after_bytes_restored(
    tmp_path, monkeypatch, drift
):
    f = fixture(tmp_path, monkeypatch)
    f.behavior["exit"] = 2
    with pytest.raises(ValueError):
        j.run(tmp_path)
    job, _ = gap_review(tmp_path, f)
    real = j.old.new_json
    original = (tmp_path / j.SELF).read_bytes()
    extra = tmp_path / j.CONTROL / "late-unlisted.json"

    def write(path, value):
        real(path, value)
        if path == j.disposition_path(tmp_path, job):
            if drift == "source":
                (tmp_path / j.SELF).write_bytes(b"late source drift")
            else:
                extra.write_bytes(b"unknown late bytes")

    monkeypatch.setattr(j.old, "new_json", write)
    with pytest.raises(ValueError):
        j.run(tmp_path, apply_check_gap=job["id"])
    assert j.disposition_path(tmp_path, job).exists()
    assert len(f.calls) == 1
    monkeypatch.setattr(j.old, "new_json", real)
    (tmp_path / j.SELF).write_bytes(original)
    if extra.exists():
        extra.unlink()
    f.behavior["exit"] = 0
    with pytest.raises(ValueError):
        j.run(tmp_path, max_jobs=1)
    assert len(f.calls) == 1


def test_combined_guard_foreign_journal_lease_is_preserved_and_cannot_return_success(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    lock = tmp_path / j.CONTROL / ".journal.lock"
    foreign = b'{"pid":999999,"owner":"foreign"}\n'

    def mutate(job, folder):
        lock.write_bytes(foreign)

    f.behavior["late"] = mutate
    with pytest.raises(ValueError):
        j.run(tmp_path, max_jobs=1)
    assert lock.exists() and lock.read_bytes() == foreign
    assert len(f.calls) == 1


def test_false_exposure_after_two_frozen_checks_is_rejected(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    name = j.gate_path("check")
    gate = json.loads((tmp_path / name).read_text())
    gate["confirmation_outcomes_parsed"] = False
    f.put(name, gate)
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert not f.calls and not j.plan_path(tmp_path, "check").exists()


def test_same_bytes_foreign_lease_replacement_is_not_unlinked(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    lock = tmp_path / j.CONTROL / ".journal.lock"
    saved = []

    def replacement(job, folder):
        saved.append(lock.read_bytes())
        other = lock.with_name("foreign-replacement")
        other.write_bytes(saved[0])
        other.replace(lock)

    f.behavior["late"] = replacement
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert lock.read_bytes() == saved[0] and len(f.calls) == 1


def test_late_gap_terminal_summary_failure_blocks_without_new_allocation(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    j.run(tmp_path, max_jobs=3)
    f.behavior["exit"] = 2
    with pytest.raises(ValueError):
        j.run(tmp_path)
    job, _ = gap_review(tmp_path, f)
    real = j.old.new_json
    original = (tmp_path / j.SELF).read_bytes()

    def write(path, value):
        real(path, value)
        if path == j.summary_path(tmp_path, "check"):
            (tmp_path / j.SELF).write_bytes(b"late source")

    monkeypatch.setattr(j.old, "new_json", write)
    with pytest.raises(ValueError):
        j.run(tmp_path, apply_check_gap=job["id"])
    assert j.disposition_path(tmp_path, job).exists() and j.summary_path(tmp_path, "check").exists()
    (tmp_path / j.SELF).write_bytes(original)
    monkeypatch.setattr(j.old, "new_json", real)
    assert (tmp_path / j.CONTROL / "failures/check/post-write.json").exists()
    with pytest.raises(ValueError):
        j.run(tmp_path)
    assert len(f.calls) == 4
