"""Synthetic true50 plus the two typed47 outcomes; no real outcomes or sampling."""

# pyright: basic
import copy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_run_arrival_sensitivity_remaining import fixture as previous_fixture

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_finish as m


def fixture(root, monkeypatch, *, repair_fails=False):
    f = previous_fixture(root, monkeypatch)
    parent = m.previous.verify_gate(root)
    w = parent["worker_admission"]
    # Synthetic model boundary; worker47 tests enforce the literal real job.
    repair_job = dict(
        id=f"ms5-{m.b.RUN_ID}-047-attempt-2",
        order=47,
        original_job=f.jobs[47],
        attempt=2,
        sampler={**m.repair.PROTOCOL, "seed": f.jobs[47]["seed"]},
    )

    def paths(root, job):
        return root / m.b.OUTPUT / "jobs" / job["id"], root / m.b.STORE / (job["id"] + ".nc")

    monkeypatch.setattr(
        m.repair,
        "repair_job",
        lambda original: (
            repair_job if original == f.jobs[47] else (_ for _ in ()).throw(ValueError("only47"))
        ),
    )
    monkeypatch.setattr(
        m.repair,
        "case_paths",
        lambda root, job: (
            paths(root, job) if job == repair_job else (_ for _ in ()).throw(ValueError("only47"))
        ),
    )
    prefix = copy.deepcopy(parent["accepted_prefix"])
    oldattempts = []

    def fabricate(job, specgate, authority, pins, failed=False):
        folder, raw = paths(root, job)
        if not folder.exists():
            folder.mkdir(parents=True)
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"synthetic unparsed raw")
            write_json(folder / "job.json", job)
            write_json(
                folder / "result.json",
                {
                    "status": "diagnostic_failure"
                    if failed
                    else "computed_pending_scientific_review"
                },
            )
        spec = folder.with_name(folder.name + "-spec.json")
        write_json(spec, job)
        folder.with_name(folder.name + ".log").write_text("synthetic process")
        write_json(
            folder.with_name(folder.name + ".supervisor.json"),
            dict(
                returncode=2 if failed else 0,
                reason="worker_exit",
                charged_slots=1,
                start_markers=1,
                job_sha256=sha256(spec),
                plan_sha256=sha256(root / m.c.PLAN),
                numerical_gate_sha256=pins[specgate],
                execution_authority_gate_sha256=authority,
                invocation_git_sha="a" * 40,
                monitor_failures=[],
            ),
        )
        write_json(
            folder / "inputs.json",
            dict(
                files=pins,
                original_job=job["original_job"],
                source_files={},
                base_prior={},
                wider_prior=None,
                run_id=m.RUN_ID if specgate == m.GATE else m.b.RUN_ID,
                source_gate=specgate,
                comparison_review="synthetic comparison",
                confirmation_outcomes_parsed=False,
                reserved_outcomes="sealed",
            ),
        )
        write_json(
            folder / "membership.json",
            dict(
                training=["synthetic record"],
                original_case_id=job["original_job"]["id"],
            ),
        )
        write_json(
            folder / "result.json",
            dict(
                status="diagnostic_failure" if failed else "computed_pending_scientific_review",
                job=job,
                original_job=job["original_job"],
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
                code_and_config=pins,
                confirmation_outcomes_parsed=False,
                reserved_outcomes="sealed",
                scoring_or_forecast_imputation=False,
            ),
        )
        write_json(folder / "sampling-start.json", job)
        write_json(
            folder / "worker-manifest.json",
            {
                q.name: sha256(q)
                for q in folder.iterdir()
                if q.is_file() and q.name not in ["worker-manifest.json", "attempt-evidence.json"]
            },
        )
        # Model the manifest-listed verifier, never glob unknown files into success.
        listed = m.read(root, str((folder / "worker-manifest.json").relative_to(root)))
        files = {str((folder / leaf).relative_to(root)): value for leaf, value in listed.items()}
        files.update(
            {
                str(q.relative_to(root)): sha256(q)
                for q in [
                    folder / "worker-manifest.json",
                    raw,
                    spec,
                    folder.with_name(folder.name + ".log"),
                    folder.with_name(folder.name + ".supervisor.json"),
                ]
            }
        )
        return files, folder / "attempt-evidence.json"

    for job in w["jobs"][1:11]:
        files, receipt = fabricate(
            job, m.b.GATE, parent["initial_files"][m.previous.GATE], w["initial_files"]
        )
        write_json(receipt, dict(case_id=job["original_job"]["id"], files=files))
        d = m.b.execution_descriptor(root, w, job, files, receipt)
        d.update(
            execution_gate=m.previous.GATE,
            worker_spec_gate=m.b.GATE,
            execution_authority_run_id=m.previous.RUN_ID,
        )
        prefix.append(d)
        name = m.previous.CONTROL + "/attempts/" + job["id"] + ".json"
        record = dict(
            case_id=d["case_id"],
            execution_job=job,
            charged_slots=1,
            start_markers=1,
            outcome="accepted",
            receipt=d["receipt"],
            receipt_sha256=d["receipt_sha256"],
            controller_receipt=name,
        )
        write_json(root / name, record)
        record["controller_receipt_sha256"] = sha256(root / name)
        oldattempts.append(record)
    job = w["jobs"][11]
    files, _ = fabricate(
        job, m.b.GATE, parent["initial_files"][m.previous.GATE], w["initial_files"], True
    )
    name = m.previous.CONTROL + "/attempts/" + job["id"] + ".json"
    record = dict(
        case_id=job["original_job"]["id"],
        execution_job=job,
        charged_slots=1,
        start_markers=1,
        outcome="needs_review",
        controller_receipt=name,
    )
    write_json(root / name, record)
    record["controller_receipt_sha256"] = sha256(root / name)
    oldattempts.append(record)
    failed47 = dict(
        case_id=job["original_job"]["id"],
        order=47,
        original_job=job["original_job"],
        execution_job=job,
        producer="numerical_protocol",
        source_role="numerical_protocol",
        attempt=1,
        charged_slots=1,
        start_markers=1,
        outcome="diagnostic_failure",
        files=files,
        physical_files=files,
        posterior=str(paths(root, job)[1].relative_to(root)),
        posterior_sha256=files[str(paths(root, job)[1].relative_to(root))],
        receipt=name,
        receipt_sha256=record["controller_receipt_sha256"],
    )
    failures = [*parent["failed_attempts"], failed47]
    baseline = copy.deepcopy(parent["baseline"])
    baseline.update(calls_charged=50, calls_started=50)
    baseline["remaining_sensitivity_runs"] = {
        m.previous.RUN_ID: dict(
            status="needs_review",
            current=job,
            next_job=10,
            accepted=prefix[36:],
            attempts=oldattempts,
        )
    }
    write_json(root / m.r.STATE, baseline)
    write_json(root / m.BASELINE, baseline)
    for name in m.repair.CONSUMED:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("new synthetic source")
    files = {
        str(q.relative_to(root)): sha256(q)
        for q in root.rglob("*")
        if q.is_file() and q != root / m.r.STATE
    }
    counters = dict(
        calls_charged=50,
        calls_started=50,
        planned_cases=55,
        accepted_logical_fits=46,
        unresolved_case_count=1,
        start_original_order=47,
        pending_repair_case=47,
        max_sampler_call_slots=110,
    )
    historical = dict(m.Counter(d["case_id"] for d in [*prefix, *failures]))
    refs = dict(
        baseline_state=m.BASELINE,
        baseline_registry=m.REGISTRY,
        baseline_review=m.REVIEW,
        original_plan=m.c.PLAN,
        worker_spec_gate=m.b.GATE,
        previous_execution_gate=m.previous.GATE,
    )
    common = {
        **counters,
        "historical_attempts_by_original_case": historical,
        "approved_repair_job": repair_job,
        "approved_remaining_jobs": w["jobs"][12:],
    }
    registry = dict(
        schema_version=4,
        status="frozen_partial_sensitivity_history_after_case47_failure",
        run_id=m.RUN_ID,
        **common,
        accepted_prefix=prefix,
        failed_attempts=failures,
        unresolved_cases=parent["unresolved_cases"],
        files=files,
    )
    registry.update(
        {k: v for k, v in refs.items() if k not in ["baseline_registry", "baseline_review"]}
    )
    registry.update(
        {
            k + "_sha256": sha256(root / v)
            for k, v in refs.items()
            if k not in ["baseline_registry", "baseline_review"]
        }
    )
    write_json(root / m.REGISTRY, registry)
    files = {**files, m.REGISTRY: sha256(root / m.REGISTRY)}
    review = dict(
        **common,
        status="accepted_late_sensitivity_repair_and_tail_plan",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        accepted_prefix_sha256=m.digest(prefix),
        failed_attempts_sha256=m.digest(failures),
        unresolved_cases_sha256=m.digest(parent["unresolved_cases"]),
        repair_protocol=m.repair.PROTOCOL,
        remaining_protocol=w["gate"]["protocol"],
        no_third_case36_attempt=True,
        no_third_case47_attempt=True,
        case47_disposition_required_before_remaining=True,
        proof_contract=m.proof_contract(),
        files=files,
    )
    review.update({k: v for k, v in refs.items() if k != "baseline_review"})
    review.update(
        {k + "_sha256": sha256(root / v) for k, v in refs.items() if k != "baseline_review"}
    )
    write_json(root / m.REVIEW, review)
    files = {**files, m.REVIEW: sha256(root / m.REVIEW)}
    gate = dict(
        status="accepted_sensitivity_case47_repair_and_final_seven_execution",
        independent_checker=True,
        run_id=m.RUN_ID,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
        **refs,
        **{k + "_sha256": sha256(root / v) for k, v in refs.items()},
        repair_job=repair_job,
        newremaining_jobs=w["jobs"][12:],
        jobs=[repair_job, *w["jobs"][12:]],
        repair_protocol=m.repair.PROTOCOL,
        remaining_protocol=w["gate"]["protocol"],
        resources=m.resources(),
        path_bindings=m.bindings(root),
        proof_contract=m.proof_contract(),
        parent_minimum_bytes=w["gate"]["parent_minimum_bytes"],
        external_reference_files=w["gate"]["external_reference_files"],
        calls_before=50,
        started_before=50,
        max_sampler_call_slots=110,
    )
    write_json(root / m.GATE, gate)

    def collect(root, job, pins, accepted=None, **kwargs):
        folder, raw = paths(root, job)
        listed = m.read(root, str((folder / "worker-manifest.json").relative_to(root)))
        values = {str((folder / n).relative_to(root)): h for n, h in listed.items()}
        values.update(
            {
                str(q.relative_to(root)): sha256(q)
                for q in [
                    folder / "worker-manifest.json",
                    raw,
                    *(
                        folder.with_name(folder.name + s)
                        for s in ["-spec.json", ".log", ".supervisor.json"]
                    ),
                ]
            }
        )
        m.c._unchanged(root, values)
        f.checks[job["id"]] += 1
        if accepted:
            assert accepted["files"] == values
        return dict(
            files=values,
            manifest=folder / "attempt-evidence.json",
            result={},
            posterior=raw,
            posterior_sha256=sha256(raw),
        )

    monkeypatch.setattr(m.repair, "case_artifacts", collect)
    f.api.case_artifacts = collect
    calls = []

    def simulate(command, log, stop, timeout):
        job = m.read(root, str(Path(command[command.index("--job") + 1]).relative_to(root)))
        a = m.verify_gate(root)
        specgate = m.GATE if job == repair_job else m.b.GATE
        pins = a["initial_files"] if specgate == m.GATE else w["initial_files"]
        calls.append(job)
        fabricate(
            job, specgate, a["initial_files"][m.GATE], pins, repair_fails and job == repair_job
        )
        # The supervisor belongs to the controller; let it write the exclusive file.
        folder, _ = paths(root, job)
        folder.with_name(folder.name + ".supervisor.json").unlink()
        return dict(returncode=2 if repair_fails and job == repair_job else 0, reason="worker_exit")

    monkeypatch.setattr(m, "supervise", simulate)
    monkeypatch.setattr(m, "git_sha", lambda root: "b" * 40)
    monkeypatch.setattr(m, "limit_worker_file_size", lambda n: None)
    f.checks.clear()
    return SimpleNamespace(
        old=f,
        baseline=copy.deepcopy(baseline),
        calls=calls,
        repair_job=repair_job,
        failures=failures,
    )


def state(root):
    return m.read(root, m.r.STATE)


def entry(root):
    return state(root)["finish_runs"][m.RUN_ID]


def review47(root, healthy=True) -> dict[str, Any]:
    a = m.verify_gate(root)
    e = entry(root)
    attempt = e["attempts"][0]
    files = m.p.merge(
        a["initial_files"],
        {
            m.PLAN: e["plan_sha256"],
            attempt["controller_receipt"]: attempt["controller_receipt_sha256"],
        },
    )
    if attempt.get("failure_receipt"):
        files[attempt["failure_receipt"]] = attempt["failure_receipt_sha256"]
    review = dict(
        status="accepted_sensitivity_case47_disposition",
        case47_outcome="accepted_repair" if healthy else "exhausted_unresolved",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        repair_job=a["repair_job"],
        execution_authority_gate_sha256=a["initial_files"][m.GATE],
        repair_spec_gate_sha256=a["initial_files"][m.GATE],
        calls_charged=51,
        calls_started=51,
        remaining_authorization=dict(
            status="accepted_sensitivity_final_seven_execution",
            authorized=True,
            jobs=a["newremaining_jobs"],
            calls_before=51,
            started_before=51,
            resources=m.resources(),
            path_bindings=m.bindings(root),
            max_sampler_call_slots=110,
        ),
    )
    if healthy:
        d = e["accepted"][0]
        review["accepted"] = d
        files = m.p.merge(files, d["files"], {d["receipt"]: d["receipt_sha256"]})
    else:
        job = a["repair_job"]
        folder, raw = m.repair.case_paths(root, job)
        physical = m.physical_files(root, folder, raw)
        failed = dict(
            case_id=job["original_job"]["id"],
            order=47,
            attempt=2,
            execution_job=job,
            original_job=job["original_job"],
            producer="repair47",
            source_role="numerical_repair",
            run_id=m.b.RUN_ID,
            execution_authority_run_id=m.RUN_ID,
            execution_gate=m.GATE,
            worker_spec_gate=m.GATE,
            charged_slots=1,
            start_markers=1,
            outcome="diagnostic_failure",
            files=physical,
            physical_files=physical,
            posterior=str(raw.relative_to(root)),
            posterior_sha256=sha256(raw),
            receipt=attempt["controller_receipt"],
            receipt_sha256=attempt["controller_receipt_sha256"],
        )
        review["failed_attempt"] = failed
        review["unresolved_case"] = dict(
            case_id=failed["case_id"],
            order=47,
            original_job=failed["original_job"],
            status="computationally_unresolved",
            failed_attempts=[a["failed_attempts"][-1], failed],
            posterior=None,
            no_third_attempt=True,
        )
        files = m.p.merge(files, physical)
    review["files"] = files
    write_json(root / m.CASE47_REVIEW, review)
    return review


@pytest.mark.parametrize("healthy", [True, False])
def test_two_actual_review_branches_complete55_without_old_history_healing(
    tmp_path, monkeypatch, healthy
):
    f = fixture(tmp_path, monkeypatch, repair_fails=not healthy)
    if healthy:
        m.run(tmp_path)
    else:
        with pytest.raises(ValueError):
            m.run(tmp_path)
    assert (
        len(f.calls) == 1
        and state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 51
    )
    assert state(tmp_path)["remaining_sensitivity_runs"] == f.baseline["remaining_sensitivity_runs"]
    if not healthy:
        with pytest.raises(ValueError):
            m.run(tmp_path, resume=True)
        assert len(f.calls) == 1
    review47(tmp_path, healthy)
    monkeypatch.setattr("builtins.input", lambda prompt: "ACK " + sha256(tmp_path / m.r.STATE))
    m.foreground(tmp_path, resume=True, invocations=2, pause_between_batches=True)
    summary = m.read(tmp_path, m.COMPLETION_SUMMARY)
    assert len(f.calls) == 8 and [j["order"] for j in f.calls] == list(range(47, 55))
    assert (
        summary["calls_charged"]
        == summary["calls_started"]
        == summary["actual_sampler_calls"]
        == 58
    )
    assert summary["accepted_logical_fits"] == (54 if healthy else 53) and summary[
        "unresolved_case_count"
    ] == (1 if healthy else 2)
    assert summary["retained_failed_calls"] == (4 if healthy else 5)
    assert {d["order"] for d in summary["accepted"]} == set(range(55)) - {36} - (
        {47} if not healthy else set()
    )
    assert state(tmp_path)["remaining_sensitivity_runs"] == f.baseline["remaining_sensitivity_runs"]
    before = dict(f.old.checks)
    assert m.verify_completion_sources(tmp_path)["summary"] == summary
    assert dict(f.old.checks) == before
    assert not (tmp_path / m.previous.COMPLETION_SUMMARY).exists()


@pytest.mark.parametrize("bad", ["source", "review", "job47", "tail", "state"])
def test_preflight_blocks_before_any_dispatch(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    if bad == "source":
        (tmp_path / m.repair.CONSUMED[0]).write_text("drift")
    elif bad == "state":
        changed = state(tmp_path)
        changed["remaining_sensitivity_runs"][m.previous.RUN_ID]["current"] = None
        write_json(tmp_path / m.r.STATE, changed)
    else:
        g = m.read(tmp_path, m.GATE)
        if bad == "review":
            g["baseline_review_sha256"] = "0" * 64
        elif bad == "job47":
            g["repair_job"]["sampler"]["target_accept"] = 0.99
        else:
            g["newremaining_jobs"] = []
        write_json(tmp_path / m.GATE, g)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not f.calls


@pytest.mark.parametrize("bad", ["incomplete", "outcome", "tail-authority", "drift"])
def test_typed_review_cannot_skip_or_relabel47(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review = review47(tmp_path)
    if bad == "incomplete":
        review["files"] = {m.GATE: sha256(tmp_path / m.GATE)}
    elif bad == "outcome":
        review["case47_outcome"] = "exhausted_unresolved"
    elif bad == "tail-authority":
        review["remaining_authorization"]["jobs"] = []
    else:
        m.run(tmp_path, resume=True, max_cases=1)
        review["extra"] = "changed"
    write_json(tmp_path / m.CASE47_REVIEW, review)
    before = len(f.calls)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == before


def test_any_tail_failure_stops_no_extra47_attempt(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review47(tmp_path)
    original = m.supervise

    def fail(*args):
        return {**original(*args), "returncode": 2}

    monkeypatch.setattr(m, "supervise", fail)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert entry(tmp_path)["current"]["order"] == 48 and state(tmp_path)["calls_charged"] == 52
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 2
    # A changed status/cursor cannot turn a retained tail failure into a new admission.
    value = state(tmp_path)
    e = value["finish_runs"][m.RUN_ID]
    e.update(status="checkpoint", current=None, next_job=len(e["attempts"]))
    write_json(tmp_path / m.r.STATE, value)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 2


@pytest.mark.parametrize(
    "field", ["execution_authority_gate_sha256", "numerical_gate_sha256", "invocation_git_sha"]
)
def test_initial_repair_process_provenance_cannot_be_resealed(tmp_path, monkeypatch, field):
    fixture(tmp_path, monkeypatch)
    original = m.repair.case_artifacts

    def bad(root, job, pins, **kwargs):
        proof = original(root, job, pins, **kwargs)
        folder, _ = m.repair.case_paths(root, job)
        path = folder.with_name(folder.name + ".supervisor.json")
        value = m.read(root, str(path.relative_to(root)))
        value[field] = "0" * 64
        write_json(path, value)
        proof["files"][str(path.relative_to(root))] = sha256(path)
        return proof

    monkeypatch.setattr(m.repair, "case_artifacts", bad)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not entry(tmp_path)["accepted"] and state(tmp_path)["calls_charged"] == 51


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize(
    "field", ["execution_gate", "worker_spec_gate", "execution_authority_run_id"]
)
def test_cold_and_warm_descriptor_relabelling_blocks_dispatch(tmp_path, monkeypatch, warm, field):
    f = fixture(tmp_path, monkeypatch)
    session = {} if warm else None
    m.run(tmp_path, _session=session)
    value = state(tmp_path)
    value["finish_runs"][m.RUN_ID]["accepted"][0][field] = "foreign-authority"
    write_json(tmp_path / m.r.STATE, value)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True, _session=session)
    assert len(f.calls) == 1 and state(tmp_path)["calls_charged"] == 51


@pytest.mark.parametrize("bad", ["unlisted", "source"])
def test_post_evidence_mutation_retained_before_promotion(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    original = m.r.new_json

    def write(path, body):
        original(path, body)
        if path == tmp_path / m.CONTROL / "attempts" / (f.repair_job["id"] + ".json"):
            if bad == "unlisted":
                folder, _ = m.repair.case_paths(tmp_path, f.repair_job)
                (folder / "unlisted-late.bin").write_bytes(b"late unlisted bytes")
            else:
                (tmp_path / "frozen.py").write_text("late source mutation")

    monkeypatch.setattr(m.r, "new_json", write)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    e = entry(tmp_path)
    assert len(f.calls) == 1 and e["accepted"] == [] and e["status"] == "needs_review"
    assert e["attempts"][0]["primary_outcome"] == "accepted"
    assert (tmp_path / e["attempts"][0]["controller_receipt"]).exists()
    assert (tmp_path / e["attempts"][0]["failure_receipt"]).exists()
    assert state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 51
    assert not (tmp_path / m.CONTROL / ".controller.lock").exists()


def test_pending_review_noop_and_complete_cache_rebind(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    session = {}
    stamp = m.run(tmp_path, _session=session)
    assert m.run(tmp_path, resume=True, _session=session) == stamp
    assert len(f.calls) == 1
    review = review47(tmp_path)
    m.run(tmp_path, resume=True, max_cases=1, _session=session)
    assert len(f.calls) == 2 and session["proofs"].a["files"][m.CASE47_REVIEW] == sha256(
        tmp_path / m.CASE47_REVIEW
    )
    assert session["proofs"].a["case47_review"] == review
    assert f.old.checks[f.repair_job["id"]] == 1


def test_per_job_quota_counts_new_repair_raw_and_retained_failed_tail(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    a = m.verify_gate(tmp_path)
    failed = a["failed_attempts"][-1]
    raw = tmp_path / failed["posterior"]
    with raw.open("r+b") as stream:
        stream.truncate(m.r.MAX_JOB + 1)
    assert m.quota(tmp_path, a, state(tmp_path)) == "combined_job_storage"


def test_foreign_state_after_ack_is_preserved(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review47(tmp_path)
    foreign = None

    def ack(prompt):
        nonlocal foreign
        stamp = sha256(tmp_path / m.r.STATE)
        value = state(tmp_path)
        value["foreign_writer"] = True
        write_json(tmp_path / m.r.STATE, value)
        foreign = (tmp_path / m.r.STATE).read_bytes()
        return "ACK " + stamp

    monkeypatch.setattr("builtins.input", ack)
    with pytest.raises(ValueError, match="owned ACK"):
        m.foreground(tmp_path, resume=True, invocations=2, pause_between_batches=True)
    assert len(f.calls) == 5 and (tmp_path / m.r.STATE).read_bytes() == foreign


@pytest.mark.parametrize("field", ["next_job", "calls_started"])
def test_cursor_or_start_counter_cannot_dispatch_out_of_order(tmp_path, monkeypatch, field):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    value = state(tmp_path)
    if field == "next_job":
        value["finish_runs"][m.RUN_ID][field] = 7
    else:
        value[field] -= 1
    write_json(tmp_path / m.r.STATE, value)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 1


@pytest.mark.parametrize("bad", ["source", "stop", "quota"])
def test_admission_is_fresh_under_leases_before_initial_allocation(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    before = (tmp_path / m.r.STATE).read_bytes()
    original = m.leases

    @contextmanager
    def leases(root):
        with original(root):
            if bad == "source":
                (root / "frozen.py").write_text("source changed inside lease")
            elif bad == "stop":
                (root / m.CONTROL / "STOP").write_text("stop before allocation")
            else:
                monkeypatch.setattr(m, "quota", lambda *a, **kw: "under_lease_quota")
            yield

    monkeypatch.setattr(m, "leases", leases)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert (tmp_path / m.r.STATE).read_bytes() == before and not f.calls
    assert not (tmp_path / m.PLAN).exists()
    assert not (tmp_path / m.CONTROL / "failure.json").exists()
    assert not (tmp_path / m.CONTROL / ".controller.lock").exists()


def test_exhausted47_foreign_raw_cannot_be_resealed_into_review(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, repair_fails=True)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    review = review47(tmp_path, False)
    review["failed_attempt"].update(
        posterior="data/processed/models/FOREIGN.nc", posterior_sha256="0" * 64
    )
    review["unresolved_case"]["failed_attempts"][-1] = copy.deepcopy(review["failed_attempt"])
    write_json(tmp_path / m.CASE47_REVIEW, review)
    before = (tmp_path / m.r.STATE).read_bytes()
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True, max_cases=1)
    assert len(f.calls) == 1 and (tmp_path / m.r.STATE).read_bytes() == before


@pytest.mark.parametrize("mode", ["cold", "warm", "public"])
def test_exhausted47_complete_provenance_replayed_on_every_admission(tmp_path, monkeypatch, mode):
    f = fixture(tmp_path, monkeypatch, repair_fails=True)
    session = {} if mode == "warm" else None
    with pytest.raises(ValueError):
        m.run(tmp_path, _session=session)
    original_review = review47(tmp_path, False)
    if mode == "public":
        m.run(tmp_path, resume=True)
        m.run(tmp_path, resume=True)
        original_summary = m.read(tmp_path, m.COMPLETION_SUMMARY)
        assert m.verify_completion_sources(tmp_path)["summary"] == original_summary
    else:
        original_summary = None
    before_calls = len(f.calls)
    before_state = (tmp_path / m.r.STATE).read_bytes()
    mutations = (
        [
            ("descriptor", key)
            for key in [
                "posterior",
                "posterior_sha256",
                "run_id",
                "source_role",
                "execution_gate",
                "worker_spec_gate",
                "execution_authority_run_id",
            ]
        ]
        + [
            ("process", key)
            for key in [
                "numerical_gate_sha256",
                "execution_authority_gate_sha256",
                "job_sha256",
                "plan_sha256",
                "invocation_git_sha",
                "start_markers",
            ]
        ]
        + [
            ("inputs", "files"),
            ("inputs", "base_prior"),
            ("membership", "training"),
            ("result", "posterior"),
            ("result", "code_and_config"),
            ("result", "status"),
            ("physical", "raw_pin"),
        ]
    )
    for group, key in mutations:
        review = copy.deepcopy(original_review)
        failed = review["failed_attempt"]
        changed_path, original_bytes = None, None
        if group == "descriptor":
            failed[key] = "FOREIGN" if key != "posterior_sha256" else "0" * 64
        elif group == "physical":
            failed["files"].pop(failed["posterior"])
        else:
            folder, _ = m.repair.case_paths(tmp_path, f.repair_job)
            changed_path = (
                folder.with_name(folder.name + ".supervisor.json")
                if group == "process"
                else folder / (group + ".json")
            )
            original_bytes = changed_path.read_bytes()
            name = str(changed_path.relative_to(tmp_path))
            value = m.read(tmp_path, name)
            value[key] = (
                0
                if key == "start_markers"
                else {"forged": True}
                if key == "base_prior"
                else {}
                if key in {"files", "code_and_config"}
                else ["FOREIGN"]
                if key == "training"
                else "FOREIGN"
            )
            write_json(changed_path, value)
            for pins in [failed["files"], failed["physical_files"], review["files"]]:
                pins[name] = sha256(changed_path)
        review["unresolved_case"]["failed_attempts"][-1] = copy.deepcopy(failed)
        write_json(tmp_path / m.CASE47_REVIEW, review)
        if mode == "public":
            assert original_summary is not None
            summary = copy.deepcopy(original_summary)
            summary["case47_disposition_review_sha256"] = sha256(tmp_path / m.CASE47_REVIEW)
            summary["files"][m.CASE47_REVIEW] = sha256(tmp_path / m.CASE47_REVIEW)
            if changed_path:
                summary["files"][str(changed_path.relative_to(tmp_path))] = sha256(changed_path)
            write_json(tmp_path / m.COMPLETION_SUMMARY, summary)
        try:
            with pytest.raises(ValueError):
                if mode == "public":
                    m.verify_completion_sources(tmp_path)
                else:
                    m.run(tmp_path, resume=True, _session=session)
        finally:
            if changed_path and original_bytes is not None:
                changed_path.write_bytes(original_bytes)
            write_json(tmp_path / m.CASE47_REVIEW, original_review)
            if original_summary:
                write_json(tmp_path / m.COMPLETION_SUMMARY, original_summary)
        assert len(f.calls) == before_calls and (tmp_path / m.r.STATE).read_bytes() == before_state
