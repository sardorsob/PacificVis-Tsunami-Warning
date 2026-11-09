"""Synthetic39-call history only; never interpret native or posterior bytes."""

# pyright: basic
import copy
from pathlib import Path
from typing import Any

import pytest
from test_run_arrival_sensitivity_numerical import fixture as prior_fixture

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_remaining as m


def fixture(root, monkeypatch):
    f = prior_fixture(root, monkeypatch)
    spec = m.read(root, m.b.GATE)
    historical = {j["id"]: 2 if j["order"] == 34 else 1 for j in f.jobs[:37]}
    spec["historical_attempts_by_original_case"] = historical
    write_json(root / m.b.GATE, spec)
    original = m.b.supervise
    worker = m.b.verify_gate(root)
    job = f.executions[0]
    folder, raw = f.api.case_paths(root, job)
    f.create("numerical_protocol", job, dispatched=True)
    spec_path = folder.with_name(folder.name + "-spec.json")
    process = folder.with_name(folder.name + ".supervisor.json")
    write_json(
        process,
        dict(
            returncode=2,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec_path),
            plan_sha256=sha256(root / m.c.PLAN),
            numerical_gate_sha256=sha256(root / m.b.GATE),
            invocation_git_sha="a" * 40,
            monitor_failures=[],
        ),
    )
    write_json(root / m.b.OUTPUT / "plan.json", m.b.plan_value(worker))
    evidence = m.b.OUTPUT + "/attempts/" + job["id"] + ".json"
    record = dict(
        case_id=job["original_job"]["id"],
        execution_job=job,
        charged_slots=1,
        start_markers=1,
        outcome="needs_review",
        controller_receipt=evidence,
    )
    write_json(root / evidence, record)
    record["controller_receipt_sha256"] = sha256(root / evidence)
    baseline = copy.deepcopy(f.baseline)
    baseline.update(
        calls_charged=39,
        calls_started=39,
        numerical_protocol_runs={
            m.b.RUN_ID: dict(
                schema_version=2,
                gate_path=m.b.GATE,
                gate_sha256=sha256(root / m.b.GATE),
                baseline_sha256=worker["gate"]["baseline_state_sha256"],
                registry_sha256=worker["gate"]["baseline_registry_sha256"],
                plan_sha256=sha256(root / m.b.OUTPUT / "plan.json"),
                status="needs_review",
                current=job,
                next_job=0,
                accepted=[],
                attempts=[record],
                pilot_review_sha256=None,
            )
        },
    )
    write_json(root / m.r.STATE, baseline)
    failed = [{**value, "producer": "original", "source_role": "original"} for value in f.failed]
    job = f.executions[0]
    folder, raw = f.api.case_paths(root, job)
    proof = f.collect("numerical_protocol", job)
    record = baseline["numerical_protocol_runs"][m.b.RUN_ID]["attempts"][0]
    third = dict(
        case_id=f.jobs[36]["id"],
        order=36,
        original_job=f.jobs[36],
        execution_job=job,
        producer="numerical_protocol",
        source_role="numerical_repair",
        attempt=2,
        charged_slots=1,
        start_markers=1,
        outcome="diagnostic_failure",
        files=proof["files"],
        physical_files=proof["files"],
        posterior=str(raw.relative_to(root)),
        posterior_sha256=sha256(raw),
        receipt=record["controller_receipt"],
        receipt_sha256=record["controller_receipt_sha256"],
    )
    failed.append(third)
    unresolved = [
        dict(
            case_id=f.jobs[36]["id"],
            order=36,
            original_job=f.jobs[36],
            status="computationally_unresolved",
            failed_attempts=[failed[1], third],
            no_third_attempt=True,
            posterior=None,
        )
    ]
    for name in [m.SELF, m.TEST]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic new authority source")
    write_json(root / m.BASELINE, baseline)
    files = {
        str(q.relative_to(root)): sha256(q)
        for q in root.rglob("*")
        if q.is_file() and q != root / m.r.STATE
    }
    historical = {**historical, f.jobs[36]["id"]: 2}
    counters = dict(
        calls_charged=39,
        calls_started=39,
        planned_cases=55,
        accepted_logical_fits=36,
        unresolved_case_count=1,
        start_original_order=37,
    )
    registry = dict(
        schema_version=3,
        status="frozen_partial_sensitivity_history_with_unresolved_case",
        accepted_prefix=f.prefix,
        failed_attempts=failed,
        unresolved_cases=unresolved,
        historical_attempts_by_original_case=historical,
        **counters,
        files=files,
        baseline_state=m.BASELINE,
        baseline_state_sha256=sha256(root / m.BASELINE),
        worker_spec_gate=m.b.GATE,
        worker_spec_gate_sha256=sha256(root / m.b.GATE),
        original_plan=m.c.PLAN,
        original_plan_sha256=sha256(root / m.c.PLAN),
    )
    write_json(root / m.REGISTRY, registry)
    files = {**files, m.REGISTRY: sha256(root / m.REGISTRY)}
    review = dict(
        status="accepted_sensitivity_unresolved_case_disposition",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        **counters,
        baseline_state=m.BASELINE,
        baseline_state_sha256=sha256(root / m.BASELINE),
        baseline_registry=m.REGISTRY,
        baseline_registry_sha256=sha256(root / m.REGISTRY),
        worker_spec_gate=m.b.GATE,
        worker_spec_gate_sha256=sha256(root / m.b.GATE),
        original_plan=m.c.PLAN,
        original_plan_sha256=sha256(root / m.c.PLAN),
        accepted_prefix_sha256=m.digest(f.prefix),
        failed_attempts_sha256=m.digest(failed),
        unresolved_cases_sha256=m.digest(unresolved),
        historical_attempts_by_original_case=historical,
        approved_jobs=f.executions[1:],
        protocol=spec["protocol"],
        max_sampler_call_slots=110,
        no_third_case36_attempt=True,
        proof_contract=m.proof_contract(),
        files=files,
    )
    write_json(root / m.DISPOSITION, review)
    files = {**files, m.DISPOSITION: sha256(root / m.DISPOSITION)}
    gate = dict(
        status="accepted_remaining_sensitivity_execution_after_unresolved_case",
        independent_checker=True,
        run_id=m.RUN_ID,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
        resources=m.resources(),
        path_bindings=m.bindings(root),
        proof_contract=m.proof_contract(),
        max_sampler_call_slots=110,
        baseline_state=m.BASELINE,
        baseline_state_sha256=sha256(root / m.BASELINE),
        baseline_registry=m.REGISTRY,
        baseline_registry_sha256=sha256(root / m.REGISTRY),
        disposition_review=m.DISPOSITION,
        disposition_review_sha256=sha256(root / m.DISPOSITION),
        worker_spec_gate=m.b.GATE,
        worker_spec_gate_sha256=sha256(root / m.b.GATE),
        original_plan=m.c.PLAN,
        original_plan_sha256=sha256(root / m.c.PLAN),
        calls_before=39,
        started_before=39,
        no_third_case36_attempt=True,
        jobs=f.executions[1:],
        protocol=spec["protocol"],
        parent_minimum_bytes=spec["parent_minimum_bytes"],
        external_reference_files=spec["external_reference_files"],
    )
    write_json(root / m.GATE, gate)

    def current_worker(*args):
        runtime = original(*args)
        command = args[0]
        spec_path = Path(command[command.index("--job") + 1])
        job = m.read(root, str(spec_path.relative_to(root)))
        folder, _ = f.api.case_paths(root, job)
        inputs = m.read(root, str((folder / "inputs.json").relative_to(root)))
        inputs.update(files=worker["initial_files"], original_job=job["original_job"])
        write_json(folder / "inputs.json", inputs)
        write_json(folder / "sampling-start.json", job)
        write_json(
            folder / "worker-manifest.json",
            {
                q.name: sha256(q)
                for q in folder.iterdir()
                if q.is_file() and q.name != "worker-manifest.json"
            },
        )
        return runtime

    monkeypatch.setattr(m, "supervise", current_worker)
    monkeypatch.setattr(m, "git_sha", lambda root: "b" * 40)
    monkeypatch.setattr(m, "limit_worker_file_size", lambda limit: None)
    f.calls.clear()
    f.checks.clear()
    f.baseline39, f.failed39, f.unresolved = copy.deepcopy(baseline), failed, unresolved
    return f


def state(root):
    return m.read(root, m.r.STATE)


def entry(root):
    return state(root)["remaining_sensitivity_runs"][m.RUN_ID]


def accept_pilot(root) -> dict[str, Any]:
    a = m.verify_gate(root)
    e = entry(root)
    first = e["accepted"][0]
    files = m.p.merge(
        a["initial_files"],
        first["files"],
        {
            first["receipt"]: first["receipt_sha256"],
            m.PLAN: e["plan_sha256"],
            e["attempts"][0]["controller_receipt"]: e["attempts"][0]["controller_receipt_sha256"],
        },
    )
    review = dict(
        status="accepted_remaining_sensitivity_execution_pilot",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        calls_charged=40,
        calls_started=40,
        accepted=first,
        worker_spec_gate_sha256=a["initial_files"][m.b.GATE],
        execution_authority_gate_sha256=a["initial_files"][m.GATE],
        files=files,
        remaining_authorization=dict(
            status="accepted_remaining_sensitivity_execution_remaining",
            authorized=True,
            jobs=a["jobs"][1:],
            calls_before=40,
            started_before=40,
            protocol=a["gate"]["protocol"],
            resources=m.resources(),
            path_bindings=m.bindings(root),
            max_sampler_call_slots=110,
        ),
    )
    write_json(root / m.PILOT, review)
    return review


def test_only37_pilot_dual_authority_and_true_history(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    result = m.run(tmp_path)
    assert result == sha256(tmp_path / m.r.STATE) and len(f.calls) == 1
    assert f.calls[0] == f.executions[1]
    assert state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 40
    assert state(tmp_path)["numerical_protocol_runs"] == f.baseline39["numerical_protocol_runs"]
    assert state(tmp_path)["completion_v1"] == f.baseline39["completion_v1"]
    accepted = entry(tmp_path)["accepted"][0]
    assert accepted["execution_gate"] == m.GATE and accepted["worker_spec_gate"] == m.b.GATE
    folder, _ = f.api.case_paths(tmp_path, f.executions[1])
    supervisor = m.read(
        tmp_path, str(folder.with_name(folder.name + ".supervisor.json").relative_to(tmp_path))
    )
    assert supervisor["numerical_gate_sha256"] == sha256(tmp_path / m.b.GATE)
    assert supervisor["execution_authority_gate_sha256"] == sha256(tmp_path / m.GATE)
    assert m.run(tmp_path, resume=True) == sha256(tmp_path / m.r.STATE) and len(f.calls) == 1
    assert f.executions[0]["id"] not in f.checks


def test_final54_valid_one_unresolved_57calls_and_metadata_only(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "ACK " + sha256(tmp_path / m.r.STATE))
    m.foreground(tmp_path, resume=True, invocations=5, pause_between_batches=True)
    summary = m.read(tmp_path, m.COMPLETION_SUMMARY)
    assert (
        summary["schema_version"] == 3
        and summary["status"] == "sensitivity_program_complete_with_unresolved_case"
    )
    assert len(f.calls) == 18 and f.calls == f.executions[1:]
    assert (
        summary["actual_sampler_calls"]
        == summary["calls_charged"]
        == summary["calls_started"]
        == 57
    )
    assert summary["planned_cases"] == summary["completed_probes"] == 55
    assert summary["accepted_logical_fits"] == len(summary["accepted"]) == 54
    assert [d["order"] for d in summary["accepted"]] == [i for i in range(55) if i != 36]
    assert (
        summary["unresolved_cases"] == f.unresolved and summary["retained_failures"] == f.failed39
    )
    assert list(summary["successful_numerical_repair_mapping"]) == [f.jobs[34]["id"]]
    before = dict(f.checks)
    checked = m.verify_completion_sources(tmp_path)
    assert checked["summary"] == summary and f.checks == before
    assert checked["admission"]["worker_admission"]["jobs"] == f.executions
    assert m.r.STATE not in checked["files"]
    altered = copy.deepcopy(summary)
    altered["accepted"][-1]["execution_gate"] = m.b.GATE
    write_json(tmp_path / m.COMPLETION_SUMMARY, altered)
    with pytest.raises(ValueError, match="descriptor/worker namespace/execution authority"):
        m.verify_completion_sources(tmp_path)
    write_json(tmp_path / m.COMPLETION_SUMMARY, summary)
    write_json(tmp_path / m.SCIENTIFIC_REVIEW, {"independent_checker": True})
    assert m.run(tmp_path, resume=True) == sha256(tmp_path / m.r.STATE)
    assert not (tmp_path / m.b.COMPLETION_SUMMARY).exists()


@pytest.mark.parametrize(
    "bad",
    [
        "missing-authority",
        "source",
        "old-state-healing",
        "third-attempt",
        "wrong-spec",
        "review-closure",
    ],
)
def test_authority_before_any_child_or_worker_case(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    if bad == "missing-authority":
        (tmp_path / m.GATE).unlink()
    elif bad == "source":
        (tmp_path / "frozen.py").write_text("drift")
    elif bad == "old-state-healing":
        changed = state(tmp_path)
        changed["numerical_protocol_runs"][m.b.RUN_ID]["current"] = None
        write_json(tmp_path / m.r.STATE, changed)
    else:
        gate = m.read(tmp_path, m.GATE)
        if bad == "third-attempt":
            gate["jobs"] = [f.executions[0], *gate["jobs"]]
        elif bad == "wrong-spec":
            gate["worker_spec_gate_sha256"] = "0" * 64
        else:
            review = m.read(tmp_path, m.DISPOSITION)
            review["files"] = {m.b.GATE: sha256(tmp_path / m.b.GATE)}
            write_json(tmp_path / m.DISPOSITION, review)
            gate["files"][m.DISPOSITION] = gate["disposition_review_sha256"] = sha256(
                tmp_path / m.DISPOSITION
            )
        write_json(tmp_path / m.GATE, gate)
    with pytest.raises((ValueError, FileNotFoundError)):
        m.run(tmp_path)
    assert not f.calls and not f.checks


@pytest.mark.parametrize("bad", ["incomplete", "unresolved-retry", "authority", "drift"])
def test_healthy_pilot_must_explicitly_authorize17_and_seal(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review = accept_pilot(tmp_path)
    if bad == "incomplete":
        review["files"] = {m.GATE: sha256(tmp_path / m.GATE)}
    elif bad == "unresolved-retry":
        review["remaining_authorization"]["jobs"] = [f.executions[0]]
    elif bad == "authority":
        review["execution_authority_gate_sha256"] = sha256(tmp_path / m.b.GATE)
    else:
        m.run(tmp_path, resume=True, max_cases=1)
        review["extra"] = "drift"
    write_json(tmp_path / m.PILOT, review)
    count = len(f.calls)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == count


@pytest.mark.parametrize(
    "bad", ["worker", "proof", "missing-start", "source", "late-unlisted", "late-cap"]
)
def test_new_failure_retains_charge_start_raw_and_blocks_retry(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    if bad in {"worker", "proof", "missing-start", "source"}:
        original = m.supervise

        def fail(*args):
            runtime = original(*args)
            folder, _ = f.api.case_paths(tmp_path, f.executions[1])
            if bad == "worker":
                runtime["returncode"] = 2
            elif bad == "proof":
                (folder / "result.json").write_text("changed")
            elif bad == "missing-start":
                (folder / "sampling-start.json").unlink()
            else:
                (tmp_path / "frozen.py").write_text("source drift")
            return runtime

        monkeypatch.setattr(m, "supervise", fail)
    else:
        original = m.r.new_json

        def late(path, value):
            original(path, value)
            if path.parent == tmp_path / m.CONTROL / "attempts" and "failure" not in path.name:
                folder, _ = f.api.case_paths(tmp_path, f.executions[1])
                (folder / "unlisted").write_bytes(b"x" * (100001 if bad == "late-cap" else 1))

        monkeypatch.setattr(m.r, "new_json", late)
        if bad == "late-cap":
            caps = m.resources()
            monkeypatch.setattr(m.r, "MAX_JOB", 100000)
            monkeypatch.setattr(m, "resources", lambda: caps)
            monkeypatch.setattr(m.b, "resources", lambda: caps)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert state(tmp_path)["calls_charged"] == 40
    assert state(tmp_path)["calls_started"] == (39 if bad == "missing-start" else 40)
    assert (
        entry(tmp_path)["status"] == "needs_review"
        and entry(tmp_path)["current"] == f.executions[1]
    )
    assert state(tmp_path)["numerical_protocol_runs"] == f.baseline39["numerical_protocol_runs"]
    assert f.api.case_paths(tmp_path, f.executions[1])[1].exists()
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 1 and not (tmp_path / m.CONTROL / ".controller.lock").exists()


@pytest.mark.parametrize("bad", ["failed36raw", "unknown-raw", "old-evidence", "new-empty-dir"])
def test_all_reviewed_prefix_failed_bytes_and_inventories_are_fresh(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    if bad == "failed36raw":
        (tmp_path / f.failed39[-1]["posterior"]).write_bytes(b"changed")
    elif bad == "unknown-raw":
        (tmp_path / m.b.STORE / "unknown.nc").write_bytes(b"retained")
    elif bad == "old-evidence":
        (tmp_path / m.b.OUTPUT / "unknown.json").write_text("unlisted")
    else:
        (tmp_path / m.CONTROL / "unknown-empty").mkdir()
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not f.calls


@pytest.mark.parametrize("bad", ["EOF", "foreign", "source"])
def test_warm_batches_reject_ack_or_fresh_source_drift(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)

    def ack(prompt):
        expected = sha256(tmp_path / m.r.STATE)
        if bad == "EOF":
            raise EOFError
        if bad == "foreign":
            changed = state(tmp_path)
            changed["foreign"] = True
            write_json(tmp_path / m.r.STATE, changed)
        else:
            (tmp_path / "frozen.py").write_text("changed")
        return "ACK " + expected

    monkeypatch.setattr("builtins.input", ack)
    with pytest.raises((ValueError, EOFError)):
        m.foreground(tmp_path, resume=True, invocations=2, pause_between_batches=True, max_cases=1)
    assert len(f.calls) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_authority_gate_sha256", "0" * 64),
        ("numerical_gate_sha256", "0" * 64),
        ("plan_sha256", "0" * 64),
        ("job_sha256", "0" * 64),
        ("invocation_git_sha", "foreign"),
        ("monitor_failures", ["unapproved"]),
    ],
)
def test_initial_full_worker_proof_cannot_bless_false_process_provenance(
    tmp_path, monkeypatch, field, value
):
    f = fixture(tmp_path, monkeypatch)
    original = f.api.case_artifacts

    def tamper(root, job, pins, **kwargs):
        proof = original(root, job, pins, **kwargs)
        folder, _ = f.api.case_paths(root, job)
        process = folder.with_name(folder.name + ".supervisor.json")
        sidecar = m.read(root, str(process.relative_to(root)))
        sidecar[field] = value
        write_json(process, sidecar)
        proof["files"][str(process.relative_to(root))] = sha256(process)
        return proof

    f.api.case_artifacts = tamper
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 40
    assert not entry(tmp_path)["accepted"] and entry(tmp_path)["status"] == "needs_review"


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_gate", m.b.GATE),
        ("worker_spec_gate", m.GATE),
        ("execution_authority_run_id", "foreign"),
        ("run_id", m.RUN_ID),
        ("source_role", "original"),
        ("producer", "original"),
        ("case_id", "foreign"),
        ("order", 36),
    ],
)
def test_cold_resume_rejects_relabelled_new_descriptor(tmp_path, monkeypatch, field, value):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)
    m.run(tmp_path, resume=True, max_cases=1)
    changed = state(tmp_path)
    changed["remaining_sensitivity_runs"][m.RUN_ID]["accepted"][-1][field] = value
    write_json(tmp_path / m.r.STATE, changed)
    before = len(f.calls)
    with pytest.raises(ValueError, match="descriptor/worker namespace/execution authority"):
        m.run(tmp_path, resume=True, max_cases=1)
    assert len(f.calls) == before


def reseal_new_sidecar(root, changed, field, value):
    e = changed["remaining_sensitivity_runs"][m.RUN_ID]
    d = e["accepted"][-1]
    folder = root / Path(d["receipt"]).parent
    process = folder.with_name(folder.name + ".supervisor.json")
    body = m.read(root, str(process.relative_to(root)))
    body[field] = value
    write_json(process, body)
    d["files"][str(process.relative_to(root))] = sha256(process)
    write_json(root / d["receipt"], {"case_id": d["case_id"], "files": d["files"]})
    d["receipt_sha256"] = sha256(root / d["receipt"])
    a = e["attempts"][-1]
    a["receipt_sha256"] = d["receipt_sha256"]
    write_json(
        root / a["controller_receipt"],
        {k: v for k, v in a.items() if k != "controller_receipt_sha256"},
    )
    a["controller_receipt_sha256"] = sha256(root / a["controller_receipt"])
    return changed


@pytest.mark.parametrize("warm", [False, True])
def test_resealed_sidecar_is_semantically_rechecked_on_cold_and_warm_reuse(
    tmp_path, monkeypatch, warm
):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)
    m.run(tmp_path, resume=True, max_cases=1)
    checked = m.verify_gate(tmp_path)
    checked["files"] = m.pilot_review(tmp_path, checked, entry(tmp_path))
    proofs = m.Proofs(tmp_path, checked)
    if warm:
        proofs.all(state(tmp_path))
    changed = reseal_new_sidecar(
        tmp_path, state(tmp_path), "execution_authority_gate_sha256", "0" * 64
    )
    write_json(tmp_path / m.r.STATE, changed)
    before = len(f.calls)
    with pytest.raises(ValueError, match="dual worker specification/execution authority"):
        if warm:
            proofs.all(changed)
        else:
            m.run(tmp_path, resume=True, max_cases=1)
    assert len(f.calls) == before


def test_sidecar_changed_after_proof_and_receipt_is_never_promoted(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.r.new_json

    def late(path, value):
        original(path, value)
        if path.parent == tmp_path / m.CONTROL / "attempts" and "failure" not in path.name:
            folder, _ = f.api.case_paths(tmp_path, f.executions[1])
            process = folder.with_name(folder.name + ".supervisor.json")
            body = m.read(tmp_path, str(process.relative_to(tmp_path)))
            body["execution_authority_gate_sha256"] = "0" * 64
            write_json(process, body)

    monkeypatch.setattr(m.r, "new_json", late)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not entry(tmp_path)["accepted"] and entry(tmp_path)["status"] == "needs_review"
    assert state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 40
