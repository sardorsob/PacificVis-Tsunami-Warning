"""Synthetic one-repair completion; no original data, posterior reads, or sampling."""

# pyright: basic
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_completion as m


def fixture(root, monkeypatch):
    floors = {}
    for path in m.r.parent_roots(root):
        path.mkdir(parents=True, exist_ok=True)
        (path / "floor").write_bytes(b"retained parent")
        floors[str(path.relative_to(root))] = m.r.byte_count(path)
    names = {
        m.SELF,
        m.TEST,
        m.REPAIR_SOURCE,
        m.REPAIR_CLI,
        m.REPAIR_TEST,
        "frozen.py",
        m.c.SELF,
        m.c.TEST,
        m.p.SELF,
        m.p.TEST,
        "analysis/arrival/model_sensitivity_references.py",
        *m.r.RUNTIME,
    }
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
    source = {name: sha256(root / name) for name in names}
    external = {}
    for name in m.c.external_reference_paths(root, m.r.parent_roots(root)):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic external reference")
        external[name] = sha256(path)
    jobs = [
        dict(
            id=f"ms5-synthetic-{j}",
            order=j,
            seed=2886110800 + 1000 * j,
            target="NCEI-native-duration",
            kind="distance-scale",
            prior_variant="base",
        )
        for j in range(55)
    ]
    science = dict(files=source, jobs=jobs, parent_minimum_bytes=floors, max_sampler_call_slots=110)
    write_json(root / m.r.GATE, science)
    old_pins = {**source, m.r.GATE: sha256(root / m.r.GATE)}
    write_json(
        root / m.c.PLAN,
        dict(
            files=old_pins,
            jobs=jobs,
            resources=m.r.resources(),
            path_bindings=m.r.path_bindings(root),
            parent_minimum_bytes=floors,
            gate_sha256=old_pins[m.r.GATE],
        ),
    )
    plan_sha = sha256(root / m.c.PLAN)
    repair_job = dict(
        id="era-pre2007-linear-attempt-2",
        role="numerical_repair",
        attempt=2,
        original_job=jobs[34],
        sampler=dict(
            seed=jobs[34]["seed"],
            draws=2000,
            tune=2000,
            chains=4,
            cores=2,
            target_accept=0.99,
            nuts_sampler="nutpie",
        ),
    )
    api = SimpleNamespace()

    def repair_paths(root, job):
        assert job == repair_job
        return root / m.REPAIR_OUTPUT / "jobs" / job["id"], root / m.REPAIR_STORE / (
            job["id"] + ".nc"
        )

    api.case_paths = repair_paths

    def paths(kind, job):
        if kind == "original":
            return m.r.case_paths(root, job)
        folder, raw = repair_paths(root, job)
        return (
            folder,
            raw,
            folder.with_name(folder.name + "-spec.json"),
            folder.with_name(folder.name + ".log"),
            folder.with_name(folder.name + ".supervisor.json"),
        )

    def create(kind, job, *, failed=False):
        folder, raw, spec, log, process = paths(kind, job)
        folder.mkdir(parents=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"synthetic posterior bytes; never parsed")
        if not spec.exists():
            write_json(spec, job)
        log.write_text("synthetic process")
        write_json(
            process,
            dict(
                returncode=2 if failed else 0,
                reason="worker_exit",
                charged_slots=1,
                start_markers=1,
                job_sha256=sha256(spec),
                plan_sha256=plan_sha,
                monitor_failures=[],
            ),
        )
        for leaf, value in [
            ("job.json", job),
            ("sampling-start.json", job),
            ("inputs.json", dict(files=old_pins)),
            ("membership.json", dict(records=["fixture-record"])),
            (
                "result.json",
                dict(status="failed" if failed else "computed_pending_scientific_review", job=job),
            ),
        ]:
            write_json(folder / leaf, value)
        write_json(
            folder / "worker-manifest.json",
            {q.name: sha256(q) for q in folder.iterdir() if q.is_file()},
        )
        return collect(kind, job)[0]

    calls, proof_calls = [], Counter()

    def collect(kind, job, accepted=None):
        folder, raw, spec, log, process = paths(kind, job)
        listed = json.loads((folder / "worker-manifest.json").read_text())
        files = {str((folder / name).relative_to(root)): digest for name, digest in listed.items()}
        files.update(
            {
                str(q.relative_to(root)): sha256(q)
                for q in [folder / "worker-manifest.json", raw, spec, log, process]
            }
        )
        m.c._unchanged(root, files)
        manifest = folder / "attempt-evidence.json"
        if accepted is not None:
            assert accepted["files"] == files and accepted["receipt_sha256"] == sha256(manifest)
            assert json.loads(manifest.read_text()) == {
                "case_id": accepted["case_id"],
                "files": files,
            }
        return files, manifest

    accepted, attempts = [], []
    for job in jobs[:35]:
        failed = job["order"] == 34
        files = create("original", job, failed=failed)
        manifest = root / m.r.OUTPUT / "jobs" / job["id"] / "attempt-evidence.json"
        if failed:
            # Original failed retention intentionally includes all earlier raw files.
            files = {**files, **{a["posterior"]: a["posterior_sha256"] for a in accepted}}
        write_json(manifest, dict(case_id=job["id"], files=files))
        descriptor = dict(
            case_id=job["id"],
            charged_slots=1,
            receipt=str(manifest.relative_to(root)),
            receipt_sha256=sha256(manifest),
        )
        attempts.append(
            {
                **descriptor,
                "start_markers": 1,
                "outcome": "runtime_failure" if failed else "accepted",
            }
        )
        if not failed:
            accepted.append(
                {
                    **descriptor,
                    "files": files,
                    "posterior": str(paths("original", job)[1].relative_to(root)),
                    "posterior_sha256": sha256(paths("original", job)[1]),
                }
            )
    # Old accepted schema contains only the original five provenance fields.
    for entry in accepted:
        entry.pop("posterior")
        entry.pop("posterior_sha256")
    pilot_files = {m.c.PLAN: plan_sha}
    for entry in accepted[:2]:
        pilot_files.update(entry["files"])
        pilot_files[entry["receipt"]] = entry["receipt_sha256"]
    write_json(
        root / m.r.PILOT_REVIEW,
        dict(
            status="accepted_sensitivity_two_case_runtime_and_prior_pilots",
            independent_checker=True,
            files=pilot_files,
        ),
    )

    def snapshot(n, failed=False):
        return dict(
            status="sensitivity_needs_review" if failed else "sensitivity_checkpoint",
            next_case=n,
            calls_charged=35 if failed else n,
            calls_started=35 if failed else n,
            current=None,
            accepted=accepted[:n],
            attempts=attempts[: 35 if failed else n],
            plan_sha256=plan_sha,
            pilot_review_sha256=sha256(root / m.r.PILOT_REVIEW),
        )

    baseline = snapshot(34, True)
    for name in [m.BASELINE, m.REPAIR_BASELINE, m.r.STATE]:
        write_json(root / name, baseline)
    write_json(root / m.c.BASELINE, snapshot(2))
    write_json(root / m.p.BASELINE, snapshot(10))
    ledgers = {}
    for j in range(12):
        path = root / f"old-ledgers/{j}.json"
        write_json(path, {"frozen": j})
        ledgers[str(path.relative_to(root))] = sha256(path)
    write_json(root / m.c.PROJECTION, {"synthetic_projection": True})
    resource_files = {
        **old_pins,
        **ledgers,
        m.c.PLAN: plan_sha,
        m.c.BASELINE: sha256(root / m.c.BASELINE),
        m.c.PROJECTION: sha256(root / m.c.PROJECTION),
        m.r.PILOT_REVIEW: sha256(root / m.r.PILOT_REVIEW),
        **external,
    }
    resource = dict(
        status="accepted_exploration_sensitivity_resource_continuation",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        resources=m.c.resources(),
        path_bindings=m.r.path_bindings(root),
        files=resource_files,
        old_ledger_snapshots=ledgers,
        original_gate_sha256=old_pins[m.r.GATE],
        original_plan_sha256=plan_sha,
        pilot_review_sha256=sha256(root / m.r.PILOT_REVIEW),
    )
    write_json(root / m.c.GATE, resource)
    resource_pins = {**resource_files, m.c.GATE: sha256(root / m.c.GATE)}
    perf_files = {**resource_pins, m.p.BASELINE: sha256(root / m.p.BASELINE)}
    performance = dict(
        status="accepted_sensitivity_in_memory_proof_reuse",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        resources=m.c.resources(),
        path_bindings=m.r.path_bindings(root),
        files=perf_files,
        proof_contract=m.p.CONTRACT,
        original_science_gate_sha256=old_pins[m.r.GATE],
        resource_gate_sha256=resource_pins[m.c.GATE],
        original_plan_sha256=plan_sha,
    )
    write_json(root / m.p.PERFORMANCE_GATE, performance)
    perf_pins = {**perf_files, m.p.PERFORMANCE_GATE: sha256(root / m.p.PERFORMANCE_GATE)}

    def state_receipt(value):
        return m.c._state_receipt(
            (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        )

    previous = None
    history_files = {
        m.c.BASELINE: sha256(root / m.c.BASELINE),
        m.p.BASELINE: sha256(root / m.p.BASELINE),
    }
    segments = [(j, j + 4, False) for j in range(2, 34, 4)] + [(34, 34, True)]
    for start, end, failed in segments:
        before, after = state_receipt(snapshot(start)), state_receipt(snapshot(end, failed))
        folder = root / m.c.CONTROL / "receipts" / f"{start:03d}-{before['sha256']}"
        common = {
            **m.c._receipt_common(resource_pins),
            "invocation_git_sha": "a" * 40,
            "previous_after_receipt_sha256": previous,
        }
        write_json(folder / "before.json", {**common, "state": before})
        write_json(
            folder / "after.json",
            {
                **common,
                "before_state": before,
                "after_state": after,
                "before_receipt_sha256": sha256(folder / "before.json"),
                "controller_exception": None,
                "postcondition_failure": None,
            },
        )
        previous = sha256(folder / "after.json")
        history_files.update({str(q.relative_to(root)): sha256(q) for q in folder.iterdir()})
        if start >= 10:
            folder = root / m.p.CONTROL / "sessions" / folder.name
            common = dict(
                performance_gate_sha256=perf_pins[m.p.PERFORMANCE_GATE],
                source_closure_sha256=m.p.digest(perf_pins),
                invocation_git_sha="a" * 40,
            )
            write_json(folder / "before.json", {**common, "state": before})
            write_json(
                folder / "after.json",
                {
                    **common,
                    "before_state": before,
                    "after_state": after,
                    "expected_owned_after_sha256": None if failed else after["sha256"],
                    "exception": "ValueError" if failed else None,
                },
            )
            history_files.update({str(q.relative_to(root)): sha256(q) for q in folder.iterdir()})
    closed = {**resource_pins, **perf_pins, **history_files}
    for entry in accepted:
        closed.update(entry["files"])
        closed[entry["receipt"]] = entry["receipt_sha256"]
    failed_paths = paths("original", jobs[34])
    folder = failed_paths[0]
    failed_files = {
        str(q.relative_to(root)): sha256(q)
        for q in [*folder.iterdir(), *failed_paths[1:]]
        if q.is_file()
    }
    closed.update(failed_files)
    bindings = {
        "original_plan_sha256": plan_sha,
        "original_science_gate_sha256": old_pins[m.r.GATE],
        "resource_gate_sha256": resource_pins[m.c.GATE],
        "performance_gate_sha256": perf_pins[m.p.PERFORMANCE_GATE],
    }
    write_json(
        root / m.PREFIX_REVIEW,
        dict(
            status="accepted_sensitivity_thirty_four_case_checkpoint",
            independent_checker=True,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            accepted_total_cases=34,
            files=closed,
            **bindings,
        ),
    )
    closed[m.PREFIX_REVIEW] = sha256(root / m.PREFIX_REVIEW)
    closed.update({name: sha256(root / name) for name in [m.BASELINE, m.REPAIR_BASELINE]})
    write_json(
        root / m.FAILURE_REVIEW,
        dict(
            status="accepted_sensitivity_same_case_numerical_repair_plan",
            independent_checker=True,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            original_job=jobs[34],
            baseline_state_sha256=sha256(root / m.BASELINE),
            files=closed,
        ),
    )
    closed[m.FAILURE_REVIEW] = sha256(root / m.FAILURE_REVIEW)
    write_json(root / m.REPAIR_GATE, dict(job=repair_job, files=closed))
    repair_pins = {**closed, m.REPAIR_GATE: sha256(root / m.REPAIR_GATE)}
    repair_admission = dict(
        gate=read(root, m.REPAIR_GATE),
        files=repair_pins,
        original_admission=dict(gate=science, files=old_pins),
        original_job=jobs[34],
        job=repair_job,
    )
    api.verify_gate = lambda root: repair_admission

    def original_proof(root, job, pins, accepted=None):
        assert pins == old_pins and job != jobs[34]
        proof_calls[("original", job["id"])] += 1
        return collect("original", job, accepted)

    def repair_proof(root, job, pins, accepted=None):
        assert pins == repair_pins
        proof_calls[("repair", job["id"])] += 1
        files, manifest = collect("repair", job, accepted)
        return dict(
            files=files,
            manifest=manifest,
            result=manifest.parent / "result.json",
            posterior=str(paths("repair", job)[1].relative_to(root)),
            posterior_sha256=sha256(paths("repair", job)[1]),
        )

    api.case_artifacts = repair_proof
    monkeypatch.setattr(m, "repair_api", lambda: api)
    monkeypatch.setattr(
        m.r, "_admit", lambda root: (science, old_pins, jobs, m.r.parent_roots(root))
    )
    monkeypatch.setattr(m.r.fit, "case_artifacts", original_proof)
    monkeypatch.setattr(
        m.r,
        "working_bytes",
        lambda root, parents: m.r.byte_count(
            *parents, root / m.r.DESIGN, root / m.r.OUTPUT, root / m.r.STORE
        ),
    )
    monkeypatch.setattr(m, "limit_worker_file_size", lambda *a: None)
    monkeypatch.setattr(m, "git_sha", lambda root: "b" * 40)

    def supervise(command, log, stop, timeout):
        job = read(root, str(Path(command[command.index("--job") + 1]).relative_to(root)))
        kind = "repair" if job.get("role") == "numerical_repair" else "original"
        before = state(root)
        assert before["completion_v1"]["current"]["job_id"] == job["id"]
        assert before["calls_charged"] == 36 + len(calls)
        calls.append((kind, job))
        create(kind, job)
        paths(kind, job)[-1].unlink()  # Controller alone writes the process receipt.
        return dict(returncode=0, reason="worker_exit", elapsed_seconds=0.01)

    monkeypatch.setattr(m, "supervise", supervise)
    gate = dict(
        status="accepted_sensitivity_failed_case_completion_execution",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        resources=m.resources(),
        path_bindings=m.bindings(root),
        max_sampler_call_slots=110,
        files=repair_pins,
        remaining_jobs=jobs[35:],
        repair_job=repair_job,
        parent_minimum_bytes=floors,
        baseline_state=m.BASELINE,
        repair_baseline_state=m.REPAIR_BASELINE,
        original_baseline_sha256=sha256(root / m.BASELINE),
        prefix_review=m.PREFIX_REVIEW,
        failure_review=m.FAILURE_REVIEW,
        repair_gate=m.REPAIR_GATE,
        external_reference_files=external,
        history_files=history_files,
        failed_files=failed_files,
        **bindings,
    )
    write_json(root / m.GATE, gate)
    return SimpleNamespace(
        gate=gate,
        jobs=jobs,
        repair_job=repair_job,
        baseline=baseline,
        calls=calls,
        proof_calls=proof_calls,
        paths=paths,
    )


def read(root, name):
    return json.loads((root / name).read_text())


def state(root):
    return read(root, m.r.STATE)


def approve(root):
    checked = m.verify_gate(root)
    s = state(root)
    entry = s["completion_v1"]
    repair = entry["repair"]
    files = m.p.merge(
        checked["files"],
        repair["files"],
        {
            repair["receipt"]: repair["receipt_sha256"],
            m.PLAN: entry["plan_sha256"],
            entry["attempts"][0]["completion_receipt"]: entry["attempts"][0][
                "completion_receipt_sha256"
            ],
        },
    )
    review = dict(
        status="accepted_sensitivity_same_model_numerical_repair",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        original_job=checked["jobs"][34],
        repair_job=checked["repair_job"],
        posterior=str(
            m.case_paths(root, checked, "repair", checked["repair_job"])[1].relative_to(root)
        ),
        posterior_sha256=repair["files"][
            str(m.case_paths(root, checked, "repair", checked["repair_job"])[1].relative_to(root))
        ],
        original_baseline_sha256=checked["files"][m.BASELINE],
        original_plan_sha256=checked["files"][m.c.PLAN],
        repair_gate_sha256=checked["files"][m.REPAIR_GATE],
        completion_gate_sha256=checked["files"][m.GATE],
        files=files,
        remaining_completion=dict(
            status="accepted_sensitivity_original_remaining_completion",
            authorized=True,
            jobs=checked["jobs"][35:],
            inherited_calls=dict(charged=36, started=36),
            resources=m.resources(),
            path_bindings=m.bindings(root),
            max_sampler_call_slots=110,
        ),
    )
    write_json(root / m.REPAIR_REVIEW, review)
    return review


def test_one_repair_then_explicit_review_then20_original_calls_and_public55(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    assert len(f.calls) == 1 and f.calls[0] == ("repair", f.repair_job)
    s = state(tmp_path)
    assert s["calls_charged"] == s["calls_started"] == 36
    assert s["completion_v1"]["status"] == "awaiting_repair_review"
    m.run(tmp_path, resume=True)
    assert len(f.calls) == 1
    approve(tmp_path)
    for _batch in range(5):
        before = len(f.calls)
        m.run(tmp_path, resume=True)
        assert len(f.calls) - before == 4
    s = state(tmp_path)
    entry = s["completion_v1"]
    assert s["calls_charged"] == s["calls_started"] == 56 and entry["next_original_order"] == 55
    assert {
        k: v for k, v in s.items() if k not in {"calls_charged", "calls_started", "completion_v1"}
    } == {k: v for k, v in f.baseline.items() if k not in {"calls_charged", "calls_started"}}
    assert f.calls[1:] == [("original", job) for job in f.jobs[35:]]
    summary = read(tmp_path, m.COMPLETION_SUMMARY)
    assert summary["logical_cases"] == 55 and summary["actual_sampler_calls"] == 56
    assert summary["accepted"][34]["execution_job"] == f.repair_job
    assert summary["accepted"][34]["posterior"].startswith(m.REPAIR_STORE)
    assert len(summary["numerical_repair_mapping"]) == 1 and m.r.STATE not in summary["files"]
    before = (tmp_path / m.r.STATE).read_bytes()
    m.run(tmp_path, resume=True)
    assert (tmp_path / m.r.STATE).read_bytes() == before
    # Public admission cannot depend on private current STATE.
    (tmp_path / m.r.STATE).unlink()
    assert m.verify_completion_sources(tmp_path)["summary"] == summary
    summary_bytes = (tmp_path / m.COMPLETION_SUMMARY).read_bytes()
    review_bytes = (tmp_path / m.REPAIR_REVIEW).read_bytes()
    for bad in ["mapping", "raw", "attempt", "review-closure", "retained-failure"]:
        changed = json.loads(summary_bytes)
        if bad == "mapping":
            changed["numerical_repair_mapping"] = {}
        elif bad == "raw":
            changed["accepted"][34]["posterior"] = str(
                f.paths("original", f.jobs[34])[1].relative_to(tmp_path)
            )
        elif bad == "attempt":
            changed["completion_attempts"][0]["charged_slots"] = 0
        elif bad == "review-closure":
            review = json.loads(review_bytes)
            review["files"] = {"frozen.py": sha256(tmp_path / "frozen.py")}
            write_json(tmp_path / m.REPAIR_REVIEW, review)
            identity = sha256(tmp_path / m.REPAIR_REVIEW)
            changed["files"][m.REPAIR_REVIEW] = identity
            changed["repair_review_sha256"] = identity
            changed["numerical_repair_mapping"][f.jobs[34]["id"]]["repair_review_sha256"] = identity
        else:
            write_json(tmp_path / m.COMPLETION_FAILURE, {"status": "needs_review"})
        write_json(tmp_path / m.COMPLETION_SUMMARY, changed)
        with pytest.raises(ValueError):
            m.verify_completion_sources(tmp_path)
        (tmp_path / m.COMPLETION_SUMMARY).write_bytes(summary_bytes)
        (tmp_path / m.REPAIR_REVIEW).write_bytes(review_bytes)
        if (tmp_path / m.COMPLETION_FAILURE).exists():
            (tmp_path / m.COMPLETION_FAILURE).unlink()


@pytest.mark.parametrize(
    "bad", ["gate", "source", "prefix", "failure", "baseline", "history", "ledger", "repair-job"]
)
def test_admission_corruption_blocks_before_any_worker_proof_or_call(tmp_path, monkeypatch, bad):
    f = fixture(tmp_path, monkeypatch)
    before = (tmp_path / m.r.STATE).read_bytes()
    if bad == "gate":
        (tmp_path / m.GATE).unlink()
    elif bad == "source":
        (tmp_path / "frozen.py").write_text("drift")
    else:
        gate = read(tmp_path, m.GATE)
        if bad == "prefix":
            gate["files"].pop(m.PREFIX_REVIEW)
        elif bad == "failure":
            gate["failure_review"] = "elsewhere.json"
        elif bad == "baseline":
            gate["original_baseline_sha256"] = "0" * 64
        elif bad == "history":
            gate["history_files"].pop(next(iter(gate["history_files"])))
        elif bad == "ledger":
            gate["files"].pop("old-ledgers/0.json")
        else:
            gate["repair_job"] = {**gate["repair_job"], "attempt": 3}
        write_json(tmp_path / m.GATE, gate)
    with pytest.raises((ValueError, FileNotFoundError)):
        m.run(tmp_path)
    assert not f.calls and not f.proof_calls and (tmp_path / m.r.STATE).read_bytes() == before


@pytest.mark.parametrize(
    "bad", ["missing-files", "wrong-jobs", "inherited", "ceiling", "unauthorized"]
)
def test_repair_review_cannot_launch_remaining_without_full_prospective_admission(
    tmp_path, monkeypatch, bad
):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    review = approve(tmp_path)
    if bad == "missing-files":
        review["files"] = {"frozen.py": sha256(tmp_path / "frozen.py")}
    elif bad == "wrong-jobs":
        review["remaining_completion"]["jobs"] = f.jobs[36:]
    elif bad == "inherited":
        review["remaining_completion"]["inherited_calls"]["charged"] = 35
    elif bad == "ceiling":
        review["remaining_completion"]["max_sampler_call_slots"] = 111
    else:
        review["remaining_completion"]["authorized"] = False
    write_json(tmp_path / m.REPAIR_REVIEW, review)
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 1 and state(tmp_path)["calls_charged"] == 36


def test_failed_repair_retains_raw_one_charge_and_all_three_leases_release(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.supervise

    def failed(*args):
        return {**original(*args), "returncode": 2}

    monkeypatch.setattr(m, "supervise", failed)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == s["calls_started"] == 36 and len(f.calls) == 1
    assert s["completion_v1"]["status"] == "needs_review" and s["completion_v1"]["repair"] is None
    assert f.paths("repair", f.repair_job)[1].is_file()
    assert (tmp_path / m.COMPLETION_FAILURE).is_file()
    assert not (tmp_path / m.OUTPUT / ".controller.lock").exists()
    with m.r._leases(tmp_path):
        pass
    with pytest.raises(ValueError):
        m.run(tmp_path, resume=True)


@pytest.mark.parametrize("kind", ["current", "old", "source", "large"])
def test_late_evidence_mutation_never_accepts_or_refunds(tmp_path, monkeypatch, kind):
    f = fixture(tmp_path, monkeypatch)
    original = m.r.new_json
    changed = []

    def late(path, value):
        original(path, value)
        if changed or path != tmp_path / m.OUTPUT / "attempts" / (f.repair_job["id"] + ".json"):
            return
        if kind == "source":
            target = tmp_path / "frozen.py"
        elif kind == "old":
            target = f.paths("original", f.jobs[0])[0] / "unlisted.bin"
        else:
            target = f.paths("repair", f.repair_job)[0] / "unlisted.bin"
        target.write_bytes(b"x" * (9000 if kind == "large" else 1))
        changed.append(target)
        if kind == "large":
            monkeypatch.setattr(m.r, "MAX_JOB", 8192)

    monkeypatch.setattr(m.r, "new_json", late)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    entry = s["completion_v1"]
    assert s["calls_charged"] == s["calls_started"] == 36 and entry["repair"] is None
    assert entry["attempts"][0]["outcome"] == "needs_review"
    assert (tmp_path / entry["attempts"][0]["completion_receipt"]).is_file()
    assert changed[0].is_file() and not (tmp_path / m.OUTPUT / ".controller.lock").exists()


def test_foreign_state_after_child_is_preserved_byte_for_byte(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.supervise
    foreign = []

    def changed(*args):
        result = original(*args)
        value = state(tmp_path)
        value["foreign_owner"] = True
        write_json(tmp_path / m.r.STATE, value)
        foreign.append((tmp_path / m.r.STATE).read_bytes())
        return result

    monkeypatch.setattr(m, "supervise", changed)
    with pytest.raises(ValueError, match="foreign"):
        m.run(tmp_path)
    assert (tmp_path / m.r.STATE).read_bytes() == foreign[0] and len(f.calls) == 1
    assert (tmp_path / m.OUTPUT / "foreign-state-failure.json").is_file()
    with m.r._leases(tmp_path):
        pass


def test_precharge_interrupt_preserves_unstarted_slot(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "supervise", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == 36 and s["calls_started"] == 35 and not f.calls
    assert s["completion_v1"]["status"] == "needs_review"


def test_unknown_raw_and_review_sha_drift_reject_before_next_dispatch(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    approve(tmp_path)
    m.run(tmp_path, resume=True, max_cases=1)
    review = read(tmp_path, m.REPAIR_REVIEW)
    review["unreviewed_change"] = True
    write_json(tmp_path / m.REPAIR_REVIEW, review)
    before = (tmp_path / m.r.STATE).read_bytes()
    with pytest.raises(ValueError, match="identity changed"):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 2 and (tmp_path / m.r.STATE).read_bytes() == before


def test_warm_process_proofs_do_not_repeat34_numeric_replays_within_batch(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    approve(tmp_path)
    f.proof_calls.clear()
    m.run(tmp_path, resume=True, max_cases=4)
    assert all(f.proof_calls[("original", job["id"])] == 1 for job in f.jobs[:34])


@pytest.mark.parametrize("where", ["old", "original", "completion"])
def test_stop_before_dispatch_or_after_child_never_launches_more(tmp_path, monkeypatch, where):
    f = fixture(tmp_path, monkeypatch)
    stop = tmp_path / (
        {"old": m.r.OLD_OUTPUT, "original": m.r.OUTPUT, "completion": m.OUTPUT}[where] + "/STOP"
    )
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("explicit stop")
    with pytest.raises(ValueError, match="STOP"):
        m.run(tmp_path)
    assert not f.calls and state(tmp_path) == f.baseline


def test_completion_receipt_bytes_count_in_repair_job_cap(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.r.new_json

    def cap(path, value):
        original(path, value)
        if path == tmp_path / m.OUTPUT / "attempts" / (f.repair_job["id"] + ".json"):
            folder, *siblings = f.paths("repair", f.repair_job)
            before = m.r.byte_count(folder) + sum(q.stat().st_size for q in siblings if q.is_file())
            monkeypatch.setattr(m.r, "MAX_JOB", before + path.stat().st_size - 1)

    monkeypatch.setattr(m.r, "new_json", cap)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == s["calls_started"] == 36 and s["completion_v1"]["repair"] is None


def test_completion_attempt_receipt_mutation_and_unknown_new_raw_block_resume(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    attempt = state(tmp_path)["completion_v1"]["attempts"][0]
    path = tmp_path / attempt["completion_receipt"]
    path.write_text("{}")
    before = (tmp_path / m.r.STATE).read_bytes()
    with pytest.raises(ValueError, match="attempt evidence"):
        m.run(tmp_path, resume=True)
    assert len(f.calls) == 1 and (tmp_path / m.r.STATE).read_bytes() == before


def test_source_change_after_precharge_blocks_launch_and_keeps_charge(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    original = m.atomic_state

    def drift(path, value):
        original(path, value)
        if value.get("completion_v1", {}).get("current"):
            (tmp_path / "frozen.py").write_text("source drift")

    monkeypatch.setattr(m, "atomic_state", drift)
    with pytest.raises(ValueError):
        m.run(tmp_path)
    s = state(tmp_path)
    assert not f.calls and s["calls_charged"] == 36 and s["calls_started"] == 35
    assert s["completion_v1"]["status"] == "needs_review"


def test_common_resource_envelope_counts_repair_store_cache_and_reserve(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    checked = m.verify_gate(tmp_path)
    assert m.quota(tmp_path, checked, f.baseline) is None
    original_working = m.r.working_bytes
    monkeypatch.setattr(m.r, "working_bytes", lambda *args: m.resources()["global_max_bytes"])
    assert m.quota(tmp_path, checked, f.baseline) == "global_storage"
    external = sum(
        (tmp_path / name).stat().st_size for name in checked["gate"]["external_reference_files"]
    )
    monkeypatch.setattr(
        m.r,
        "working_bytes",
        lambda *args: m.resources()["global_max_bytes"] - m.r.RESERVE - external + 1,
    )
    assert m.quota(tmp_path, checked, f.baseline, reserve=True) == "global_storage"
    assert m.quota(tmp_path, checked, f.baseline) is None
    monkeypatch.setattr(m.r, "working_bytes", original_working)
    original_bytes = m.r.byte_count
    cache_roots = (tmp_path / m.r.STORE / "cache", tmp_path / m.REPAIR_STORE / "cache")
    monkeypatch.setattr(
        m.r,
        "byte_count",
        lambda *paths: m.r.MAX_CACHE + 1 if paths == cache_roots else original_bytes(*paths),
    )
    assert m.quota(tmp_path, checked, f.baseline) == "cache_storage"
    monkeypatch.setattr(m.r, "byte_count", original_bytes)
    raw = f.paths("repair", f.repair_job)[1]
    raw.parent.mkdir(parents=True, exist_ok=True)
    with raw.open("wb") as stream:
        stream.truncate(m.r.MAX_JOB + 1)
    assert (
        m.quota(tmp_path, checked, f.baseline, ("repair", f.repair_job)) == "combined_job_storage"
    )
    with raw.open("wb") as stream:
        stream.truncate(m.r.FILE_MAX + 1)
    assert m.quota(tmp_path, checked, f.baseline) == "per_file_storage"


def trace_cache(monkeypatch):
    original = m.Proofs
    seen = []

    class Traced(original):
        def __init__(self, root, checked):
            super().__init__(root, checked)
            self.rebinds = 0
            seen.append(self)

        def rebind(self, root, checked):
            assert m.REPAIR_REVIEW in checked["files"]
            super().rebind(root, checked)
            self.rebinds += 1

    monkeypatch.setattr(m, "Proofs", Traced)
    return seen


def test_foreground_five_closed_batches_reuse_full_proofs_and_rebind_fresh_review(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    approve(tmp_path)
    f.proof_calls.clear()
    seen = trace_cache(monkeypatch)
    acks = []
    monkeypatch.setattr("builtins.input", lambda prompt: acks.append(prompt) or "ACK")
    owned = m.foreground(tmp_path, resume=True, invocations=5, pause_between_batches=True)
    assert owned == sha256(tmp_path / m.r.STATE) and len(f.calls) == 21 and len(acks) == 4
    assert all(f.proof_calls[("original", job["id"])] == 1 for job in f.jobs[:34])
    assert len(seen) == 1 and seen[0].rebinds == 4 and seen[0].verified == {}
    assert read(tmp_path, m.COMPLETION_SUMMARY)["logical_cases"] == 55
    before = (tmp_path / m.r.STATE).read_bytes()
    assert m.foreground(tmp_path, resume=True) == owned
    assert (tmp_path / m.r.STATE).read_bytes() == before and len(f.calls) == 21


@pytest.mark.parametrize("where", ["after-ACK", "during-admission"])
def test_foreground_rejects_foreign_valid_advance_and_preserves_new_state(
    tmp_path, monkeypatch, where
):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    approve(tmp_path)
    seen = trace_cache(monkeypatch)
    original_verify = m.verify_gate
    foreign = []
    admissions = []

    def advance():
        with monkeypatch.context() as scoped:
            scoped.setattr(m, "verify_gate", original_verify)
            m.run(tmp_path, resume=True, max_cases=1)
        foreign.append((tmp_path / m.r.STATE).read_bytes())

    def admitted(root):
        checked = original_verify(root)
        admissions.append(checked)
        if len(admissions) == 2:
            advance()
        return checked

    if where == "during-admission":
        monkeypatch.setattr(m, "verify_gate", admitted)
        monkeypatch.setattr("builtins.input", lambda prompt: "ACK")
    else:
        monkeypatch.setattr("builtins.input", lambda prompt: advance() or "ACK")
    with pytest.raises(ValueError, match="foreign valid STATE"):
        m.foreground(tmp_path, resume=True, invocations=5, pause_between_batches=True)
    assert len(f.calls) == 6 and (tmp_path / m.r.STATE).read_bytes() == foreign[0]
    assert state(tmp_path)["calls_charged"] == 41
    assert seen[0].verified == {}


@pytest.mark.parametrize("stop", ["EOF", "source"])
def test_foreground_pause_error_clears_memo_without_new_calls(tmp_path, monkeypatch, stop):
    f = fixture(tmp_path, monkeypatch)
    m.run(tmp_path)
    approve(tmp_path)
    seen = trace_cache(monkeypatch)

    def paused(prompt):
        if stop == "EOF":
            raise EOFError("closed synthetic input")
        (tmp_path / "frozen.py").write_text("changed during pause")
        return "ACK"

    monkeypatch.setattr("builtins.input", paused)
    with pytest.raises(EOFError if stop == "EOF" else ValueError):
        m.foreground(tmp_path, resume=True, invocations=5, pause_between_batches=True)
    assert len(f.calls) == 5 and state(tmp_path)["calls_charged"] == 40
    assert state(tmp_path)["completion_v1"]["status"] == "checkpoint"
    assert all(cache.verified == {} for cache in seen)


def test_foreground_initial_repair_stops_for_review_and_requires_pause_contract(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    seen = trace_cache(monkeypatch)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(AssertionError("no ACK before repair QA")),
    )
    with pytest.raises(ValueError):
        m.foreground(tmp_path, invocations=7, pause_between_batches=True)
    with pytest.raises(ValueError):
        m.foreground(tmp_path, invocations=2)
    m.foreground(tmp_path, invocations=6, pause_between_batches=True)
    assert (
        len(f.calls) == 1 and state(tmp_path)["completion_v1"]["status"] == "awaiting_repair_review"
    )
    assert seen[0].verified == {}


def test_foreground_pending_review_noop_returns_owned_sha(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    owned = m.foreground(tmp_path)
    before = (tmp_path / m.r.STATE).read_bytes()
    assert m.foreground(tmp_path, resume=True) == owned
    assert (tmp_path / m.r.STATE).read_bytes() == before and len(f.calls) == 1
