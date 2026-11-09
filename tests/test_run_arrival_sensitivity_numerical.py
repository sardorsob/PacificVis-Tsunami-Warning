"""Synthetic reviewed-history conservation; no native data or sampler is used."""

# pyright: basic
import copy
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_numerical as m


def fixture(root, monkeypatch):
    jobs = [dict(id=f"ms5-fixture-{i}", order=i, seed=2886110800 + 1000 * i) for i in range(55)]
    protocol = dict(
        draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
    )
    executions = [
        dict(
            id=f"ms5-{m.RUN_ID}-{i:03d}-attempt-{2 if i == 36 else 1}",
            order=i,
            original_job=jobs[i],
            attempt=2 if i == 36 else 1,
            sampler={**protocol, "seed": jobs[i]["seed"]},
        )
        for i in range(36, 55)
    ]
    source = {}
    for name in [m.SELF, m.TEST, m.WORKER, m.CLI, m.WORKER_TEST, "frozen.py"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
        source[name] = sha256(path)
    floors = {}
    parents = m.r.parent_roots(root)
    for path in parents:
        path.mkdir(parents=True, exist_ok=True)
        (path / "floor").write_bytes(b"retained")
        floors[str(path.relative_to(root))] = m.r.byte_count(path)
    for name in m.c.external_reference_paths(root, parents):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"external reference")
        source[name] = sha256(path)
    write_json(root / m.c.PLAN, {"jobs": jobs, "files": source})
    source[m.c.PLAN] = sha256(root / m.c.PLAN)
    api = SimpleNamespace()
    calls, checks = [], Counter()

    def paths(root, job, admission=None):
        assert job in executions
        return root / m.OUTPUT / "jobs" / job["id"], root / m.STORE / (job["id"] + ".nc")

    api.case_paths = paths

    def fullpaths(kind, job):
        if kind == "original":
            return m.r.case_paths(root, job)
        folder, raw = (
            (
                root / m.old.REPAIR_OUTPUT / "jobs" / job["id"],
                root / m.old.REPAIR_STORE / (job["id"] + ".nc"),
            )
            if kind == "repair_v1"
            else paths(root, job)
        )
        return (
            folder,
            raw,
            *(
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ),
        )

    def collect(kind, job, accepted=None, **kwargs) -> dict[str, Any]:
        checks[job["id"]] += 1
        folder, raw, spec, log, process = fullpaths(kind, job)
        listed = json.loads((folder / "worker-manifest.json").read_text())
        files = {str((folder / name).relative_to(root)): h for name, h in listed.items()}
        files.update(
            {
                str(q.relative_to(root)): sha256(q)
                for q in [folder / "worker-manifest.json", raw, spec, log, process]
            }
        )
        m.c._unchanged(root, files)
        if kind == "numerical_protocol":
            supervisor = json.loads(process.read_text())
            assert supervisor["start_markers"] == supervisor["charged_slots"] == 1
            assert supervisor["numerical_gate_sha256"] == sha256(root / m.GATE)
        receipt = folder / "attempt-evidence.json"
        if accepted:
            assert accepted["files"] == files
        return dict(
            files=files, manifest=receipt, result={}, posterior=raw, posterior_sha256=sha256(raw)
        )

    api.case_artifacts = lambda root, job, pins, accepted=None, gate_path=None: collect(
        "numerical_protocol", job, accepted
    )

    def create(kind, job, *, failed=False, dispatched=False) -> Any:
        folder, raw, spec, log, process = fullpaths(kind, job)
        folder.mkdir(parents=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"synthetic unparsed raw")
        if not spec.exists():
            write_json(spec, job)
        log.write_text("synthetic worker")
        if not dispatched:
            write_json(process, {"retained": True})
        for leaf, value in [
            ("job.json", job),
            ("sampling-start.json", {"seed": job.get("seed", 0)}),
            ("inputs.json", {"files": source}),
            (
                "result.json",
                {
                    "status": "diagnostic_failure"
                    if failed
                    else "computed_pending_scientific_review"
                },
            ),
        ]:
            write_json(folder / leaf, value)
        write_json(
            folder / "worker-manifest.json",
            {q.name: sha256(q) for q in folder.iterdir() if q.is_file()},
        )
        if dispatched:
            return
        proof = collect(kind, job)
        files, receipt = proof["files"], proof["manifest"]
        original = job.get("original_job", job)
        write_json(receipt, {"case_id": original["id"], "files": files})
        return dict(
            case_id=original["id"],
            order=original["order"],
            original_job=original,
            execution_job=job,
            producer=kind,
            source_role="numerical_repair" if kind == "repair_v1" else "original",
            charged_slots=1,
            files=files,
            receipt=str(receipt.relative_to(root)),
            receipt_sha256=sha256(receipt),
            posterior=str(raw.relative_to(root)),
            posterior_sha256=sha256(raw),
        )

    prefix = []
    failed = []
    for i in range(37):
        if i in [34, 36]:
            d = create("original", jobs[i], failed=True)
            physical = {**d["files"], d["receipt"]: d["receipt_sha256"]}
            failed.append(
                {
                    **{k: v for k, v in d.items() if k not in ["producer", "source_role"]},
                    "physical_files": physical,
                    "attempt": 1,
                    "start_markers": 1,
                    "outcome": "diagnostic_failure",
                }
            )
        if i < 36:
            prefix.append(
                create("repair_v1", dict(id="era-pre2007-linear-attempt-2", original_job=jobs[i]))
                if i == 34
                else create("original", jobs[i])
            )
    baseline = dict(
        calls_charged=38,
        calls_started=38,
        status="needs_review",
        next_case=34,
        accepted=["original frozen34"],
        attempts=["original frozen35"],
        completion_v1={"current": jobs[36], "attempts": ["repair34", "original35", "failed36"]},
    )
    base = m.OUTPUT + "/baseline-state.json"
    registry = m.OUTPUT + "/baseline-registry.json"
    review = m.OUTPUT + "/baseline-review.json"
    write_json(root / base, baseline)
    allfiles = dict(source)
    for d in [*prefix, *failed]:
        allfiles.update(d["files"])
        allfiles[d["receipt"]] = d["receipt_sha256"]
    allfiles[base] = sha256(root / base)
    write_json(
        root / registry, dict(accepted_prefix=prefix, failed_attempts=failed, files=allfiles)
    )
    allfiles[registry] = sha256(root / registry)
    write_json(
        root / review,
        {"status": "accepted_sensitivity_remaining_numerical_protocol_plan", "files": allfiles},
    )
    allfiles[review] = sha256(root / review)
    gate = dict(
        status="accepted_sensitivity_remaining_numerical_protocol",
        independent_checker=True,
        run_id=m.RUN_ID,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=allfiles,
        resources=m.resources(),
        path_bindings=m.bindings(root, m.RUN_ID),
        proof_contract=m.proof_contract(),
        parent_minimum_bytes=floors,
        external_reference_files=m.c.external_reference_paths(root, parents),
        max_sampler_call_slots=110,
        calls_before=38,
        started_before=38,
        protocol=protocol,
        jobs=executions,
        baseline_state=base,
        baseline_state_sha256=sha256(root / base),
        baseline_registry=registry,
        baseline_registry_sha256=sha256(root / registry),
        baseline_review=review,
        baseline_review_sha256=sha256(root / review),
    )
    write_json(root / m.GATE, gate)
    write_json(root / m.r.STATE, baseline)

    def admission(root, gate_path=m.GATE):
        g = m.read(root, gate_path)
        return dict(
            gate=g,
            files={**g["files"], gate_path: sha256(root / gate_path)},
            original_admission={"gate": {"parent_minimum_bytes": floors}},
            original_jobs=jobs,
            baseline=baseline,
            accepted_prefix=prefix,
            failed_attempts=failed,
            jobs=executions,
            parents=parents,
        )

    api.verify_gate = admission

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        calls.append(job)
        create("numerical_protocol", job, dispatched=True)
        return dict(returncode=0, reason="worker_exit")

    monkeypatch.setattr(m, "worker_api", lambda: api)
    monkeypatch.setattr(m, "supervise", supervise)
    monkeypatch.setattr(m, "git_sha", lambda root: "a" * 40)
    monkeypatch.setattr(m, "limit_worker_file_size", lambda limit: None)
    checks.clear()
    return SimpleNamespace(
        jobs=jobs,
        executions=executions,
        baseline=copy.deepcopy(baseline),
        prefix=prefix,
        failed=failed,
        calls=calls,
        checks=checks,
        api=api,
        create=create,
        collect=collect,
        source=source,
    )


def state(root):
    return m.read(root, m.r.STATE)


def entry(root):
    return state(root)["numerical_protocol_runs"][m.RUN_ID]


def accept_pilot(root):
    checked = m.verify_gate(root)
    e = entry(root)
    first = e["accepted"][0]
    files = m.p.merge(
        checked["initial_files"],
        first["files"],
        {
            first["receipt"]: first["receipt_sha256"],
            m.OUTPUT + "/plan.json": e["plan_sha256"],
            e["attempts"][0]["controller_receipt"]: e["attempts"][0]["controller_receipt_sha256"],
        },
    )
    review = dict(
        status="accepted_sensitivity_numerical_protocol_pilot",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        run_id=m.RUN_ID,
        gate_sha256=checked["initial_files"][m.GATE],
        baseline_registry_sha256=checked["gate"]["baseline_registry_sha256"],
        accepted=first,
        calls_charged=39,
        calls_started=39,
        files=files,
        remaining_authorization=dict(
            status="accepted_sensitivity_numerical_protocol_remaining",
            authorized=True,
            jobs=checked["jobs"][1:],
            calls_before=39,
            started_before=39,
            protocol=checked["gate"]["protocol"],
            resources=m.resources(),
            path_bindings=m.bindings(root, m.RUN_ID),
            max_sampler_call_slots=110,
        ),
    )
    write_json(root / m.OUTPUT / "pilot-review-acceptance.json", review)
    return review


def test_first_only_and_frozen_history(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    old = m.c._path(tmp_path, m.GATE).read_bytes()
    result = m.run(tmp_path)
    assert result == sha256(tmp_path / m.r.STATE)
    assert (
        len(f.calls) == 1
        and state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 39
    )
    assert entry(tmp_path)["status"] == "awaiting_pilot_review"
    assert state(tmp_path)["completion_v1"] == f.baseline["completion_v1"]
    assert state(tmp_path)["accepted"] == f.baseline["accepted"]
    assert old == (tmp_path / m.GATE).read_bytes()
    assert not any(
        p.exists()
        for p in [
            tmp_path / m.r.OLD_OUTPUT / ".controller.lock",
            tmp_path / m.r.OUTPUT / ".controller.lock",
            tmp_path / m.OUTPUT / ".controller.lock",
        ]
    )
    assert not any(k in f.checks for k in [j["id"] for j in f.jobs[:36]])
    assert m.run(tmp_path, resume=True) == sha256(tmp_path / m.r.STATE)
    assert len(f.calls) == 1


def test_final55_57calls_public_metadata(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)
    for _ in range(5):
        m.run(tmp_path, resume=True)
    summary = m.read(tmp_path, m.COMPLETION_SUMMARY)
    assert len(f.calls) == 19 and len(summary["accepted"]) == 55
    assert (
        summary["calls_charged"]
        == summary["calls_started"]
        == summary["actual_sampler_calls"]
        == 57
    )
    assert summary["retained_failures"] == f.failed
    assert summary["accepted"][:36] == f.prefix
    assert [d["producer"] for d in summary["accepted"][-19:]] == ["numerical_protocol"] * 19
    assert len(summary["numerical_repair_mapping"]) == 2
    assert len(summary["protocol_amendment"]["first_attempt_original_case_ids"]) == 18
    assert summary["accepted"][36]["execution_gate"] == m.GATE
    before = dict(f.checks)
    checked = m.verify_completion_sources(tmp_path)
    assert checked["admission"]["original_jobs"] == f.jobs
    assert checked["summary"] == summary and f.checks == before
    assert m.r.STATE not in checked["files"]
    # A later independent review is an explicitly declared publication artifact.
    write_json(tmp_path / m.OUTPUT / "scientific-review.json", {"independent_checker": True})
    assert m.verify_completion_sources(tmp_path)["summary"] == summary
    unknown = tmp_path / m.OUTPUT / "unlisted-publication.json"
    write_json(unknown, {"unapproved": True})
    with pytest.raises(ValueError, match="unknown numerical evidence"):
        m.verify_completion_sources(tmp_path)
    unknown.unlink()
    changed = copy.deepcopy(summary)
    changed["accepted"][36]["posterior"] = f.prefix[0]["posterior"]
    write_json(tmp_path / m.COMPLETION_SUMMARY, changed)
    with pytest.raises((ValueError, AssertionError)):
        m.verify_completion_sources(tmp_path)
    write_json(tmp_path / m.COMPLETION_SUMMARY, summary)
    assert m.run(tmp_path, resume=True) == sha256(tmp_path / m.r.STATE)


@pytest.mark.parametrize("mutation", ["source", "incomplete", "resource", "symlink"])
def test_preflight_before_worker_or_dispatch(tmp_path, monkeypatch, mutation):
    f = fixture(tmp_path, monkeypatch)
    if mutation == "source":
        (tmp_path / "frozen.py").write_text("changed")
    elif mutation == "symlink":
        (tmp_path / "frozen.py").unlink()
        (tmp_path / "frozen.py").symlink_to(tmp_path / m.SELF)
    else:
        gate = m.read(tmp_path, m.GATE)
        if mutation == "incomplete":
            gate["files"].pop(m.WORKER)
        else:
            gate["resources"]["global_max_bytes"] += 1
        write_json(tmp_path / m.GATE, gate)
    monkeypatch.setattr(
        m, "worker_api", lambda: pytest.fail("must not import worker before source admission")
    )
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not f.calls and state(tmp_path) == f.baseline


@pytest.mark.parametrize("mutation", ["incomplete", "wrongjob", "authorization", "source", "drift"])
def test_pilot_review_blocks_before_second_dispatch(tmp_path, monkeypatch, mutation):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review = accept_pilot(tmp_path)
    if mutation == "incomplete":
        review["files"] = {"frozen.py": f.source["frozen.py"]}
    elif mutation == "wrongjob":
        review["accepted"]["case_id"] = "wrong"
    elif mutation == "authorization":
        review["remaining_authorization"]["jobs"] = []
    elif mutation == "source":
        (tmp_path / "frozen.py").write_text("drift")
    else:
        m.run(tmp_path, resume=True, max_cases=1)
        review["extra"] = "re-sealedreviewdrift"
    write_json(tmp_path / m.OUTPUT / "pilot-review-acceptance.json", review)
    count = len(f.calls)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == count


@pytest.mark.parametrize("failure", ["worker", "start", "proof", "latefile", "latequota", "source"])
def test_failure_retains_charge_raw_history_no_retry(tmp_path, monkeypatch, failure):
    f = fixture(tmp_path, monkeypatch)
    if failure in ["worker", "start", "proof", "source"]:
        oldsuper = m.supervise

        def bad(*args):
            result = oldsuper(*args)
            folder, _ = f.api.case_paths(tmp_path, f.executions[0])
            if failure == "worker":
                result["returncode"] = 2
            elif failure == "start":
                (folder / "sampling-start.json").unlink()
            elif failure == "proof":
                (folder / "result.json").write_text("corrupt")
            else:
                (tmp_path / "frozen.py").write_text("drift")
            return result

        monkeypatch.setattr(m, "supervise", bad)
    else:
        original = m.r.new_json

        def late(path, value):
            original(path, value)
            if (
                path.parent == tmp_path / m.OUTPUT / "attempts"
                and path.name.endswith(".json")
                and "failure" not in path.name
            ):
                folder, _ = f.api.case_paths(tmp_path, f.executions[0])
                (folder / "unlisted.bin").write_bytes(
                    b"x" * (100001 if failure == "latequota" else 1)
                )

        monkeypatch.setattr(m.r, "new_json", late)
        if failure == "latequota":
            frozen_resources = m.resources()
            monkeypatch.setattr(m.r, "MAX_JOB", 100000)
            monkeypatch.setattr(m, "resources", lambda: frozen_resources)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == 39 and s["calls_started"] == (38 if failure == "start" else 39)
    assert (
        entry(tmp_path)["status"] == "needs_review"
        and entry(tmp_path)["current"] == f.executions[0]
    )
    assert s["completion_v1"] == f.baseline["completion_v1"]
    assert f.api.case_paths(tmp_path, f.executions[0])[1].exists()
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 1
    assert not (tmp_path / m.OUTPUT / ".controller.lock").exists()


@pytest.mark.parametrize("what", ["oldraw", "failedraw", "unknownraw", "unknowncase", "receipt"])
def test_reviewed_prefix_fresh_complete_bytes(tmp_path, monkeypatch, what):
    f = fixture(tmp_path, monkeypatch)
    if what == "oldraw":
        (tmp_path / f.prefix[0]["posterior"]).write_bytes(b"changed")
    elif what == "failedraw":
        (tmp_path / f.failed[-1]["posterior"]).write_bytes(b"changed")
    elif what == "unknownraw":
        (tmp_path / m.old.REPAIR_STORE / "unlisted.nc").write_bytes(b"partial")
    elif what == "unknowncase":
        (tmp_path / m.r.OUTPUT / "jobs" / "unknown").mkdir()
    else:
        (tmp_path / f.prefix[0]["receipt"]).write_text("changed")
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert not f.calls and state(tmp_path) == f.baseline


def test_storage_all_three_stores_and_per_job_receipt(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    checked = m.verify_gate(tmp_path)
    assert m.quota(tmp_path, checked, state(tmp_path)) is None
    for store in [m.old.REPAIR_STORE, m.STORE]:
        path = tmp_path / store / "cache" / "overflow"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)
    monkeypatch.setattr(m.r, "MAX_CACHE", 199)
    assert m.quota(tmp_path, checked, state(tmp_path)) == "cache_storage"


def test_foreground_warm_rebind_and_exact_ack(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)

    def ack(prompt):
        return "ACK " + sha256(tmp_path / m.r.STATE)

    monkeypatch.setattr("builtins.input", ack)
    m.foreground(tmp_path, resume=True, invocations=3, pause_between_batches=True, max_cases=2)
    assert len(f.calls) == 7
    assert f.checks[f.executions[0]["id"]] == 2  # One new-process replay of the pilot.
    assert all(f.checks[j["id"]] == 1 for j in f.calls[1:])


@pytest.mark.parametrize("failure", ["eof", "foreign", "source", "gate"])
def test_foreground_ack_or_fresh_admission_failure(tmp_path, monkeypatch, failure):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)

    def ack(prompt):
        expected = sha256(tmp_path / m.r.STATE)
        if failure == "eof":
            raise EOFError
        if failure == "foreign":
            s = state(tmp_path)
            s["foreign"] = True
            write_json(tmp_path / m.r.STATE, s)
        elif failure == "source":
            (tmp_path / "frozen.py").write_text("changed")
        else:
            g = m.read(tmp_path, m.GATE)
            g["unapproved"] = True
            write_json(tmp_path / m.GATE, g)
        return "ACK " + expected

    monkeypatch.setattr("builtins.input", ack)
    with pytest.raises((ValueError, EOFError)):
        m.foreground(tmp_path, resume=True, invocations=2, pause_between_batches=True, max_cases=1)
    assert len(f.calls) == 2


def test_foreign_state_after_child_never_overwritten(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.supervise

    def foreign(*args):
        result = original(*args)
        write_json(tmp_path / m.r.STATE, {"foreign": "retained"})
        return result

    monkeypatch.setattr(m, "supervise", foreign)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert state(tmp_path) == {"foreign": "retained"}
    assert (tmp_path / m.OUTPUT / "foreign-state-failure.json").exists()
    assert len(f.calls) == 1


@pytest.mark.parametrize("field", ["completion_v1", "accepted", "attempts", "calls_started"])
def test_original_history_and_counters_are_immutable(tmp_path, monkeypatch, field):
    fixture(tmp_path, monkeypatch)
    changed = state(tmp_path)
    changed[field] = "tampered"
    write_json(tmp_path / m.r.STATE, changed)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    assert state(tmp_path) == changed


def test_stop_before_allocation_and_global_local_repair_bytes(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    stop = tmp_path / m.OUTPUT / "STOP"
    stop.write_text("review")
    with pytest.raises(ValueError, match="unknown numerical evidence|STOP"):
        m.run(tmp_path)
    assert state(tmp_path) == f.baseline and not f.calls
    stop.unlink()
    checked = m.verify_gate(tmp_path)
    caps = m.resources()
    # The two new stores are outside frozen r.working_bytes and must each count once.
    monkeypatch.setattr(m.r, "working_bytes", lambda root, parents: 0)
    additional = sum(m.r.byte_count(q) for q in m.stores(tmp_path, checked)[1:])
    outside = sum(
        (tmp_path / n).stat().st_size for n in checked["gate"]["external_reference_files"]
    )
    monkeypatch.setattr(
        m, "resources", lambda: {**caps, "global_max_bytes": additional + outside - 1}
    )
    assert m.quota(tmp_path, checked, state(tmp_path)) == "global_storage"
    monkeypatch.setattr(m, "resources", lambda: {**caps, "global_max_bytes": additional + outside})
    assert m.quota(tmp_path, checked, state(tmp_path)) is None
    bases = [tmp_path / m.r.DESIGN, tmp_path / m.r.OUTPUT, *m.stores(tmp_path, checked)]
    monkeypatch.setattr(
        m, "resources", lambda: {**caps, "local_max_bytes": m.r.byte_count(*bases) - 1}
    )
    assert m.quota(tmp_path, checked, state(tmp_path)) == "local_storage"


def test_late_summary_write_rechecks_all_job_caps(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    accept_pilot(tmp_path)
    for _ in range(4):
        m.run(tmp_path, resume=True)
    original = m.r.new_json
    caps = m.resources()

    def late(path, value):
        original(path, value)
        if path == tmp_path / m.COMPLETION_SUMMARY:
            monkeypatch.setattr(m.r, "MAX_JOB", 100000)
            monkeypatch.setattr(m, "resources", lambda: caps)
            folder, _ = f.api.case_paths(tmp_path, f.executions[0])
            (folder / "unlisted-final.bin").write_bytes(b"x" * 100001)

    monkeypatch.setattr(m.r, "new_json", late)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert entry(tmp_path)["status"] == "needs_review"
    assert state(tmp_path)["calls_charged"] == 57
    assert (tmp_path / m.COMPLETION_SUMMARY).exists()
    assert (tmp_path / m.OUTPUT / "failure.json").exists()
    assert not (tmp_path / m.OUTPUT / ".controller.lock").exists()
