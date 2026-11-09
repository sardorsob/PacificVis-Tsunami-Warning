"""Synthetic fixed-phase runtime contracts; no development tables or actual sampling."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_development as c


def fixture(root, monkeypatch, *, training=False):
    floors = {}
    for p in c.r.parent_roots(root):
        p.mkdir(parents=True, exist_ok=True)
        (p / "floor").write_bytes(b"original")
        floors[str(p.relative_to(root))] = c.r.byte_count(p)
    source = "frozen.py"
    for name in [source, c.SELF, c.TEST, c.fit.data.FREEZE, c.RECOVERY_SOURCE, c.RECOVERY_CLI]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen metadata/source")
    freeze = {"training_references": {}}
    specs = {f"target{i}:event:selected": (f"target{i}", {"role": "selected"}) for i in range(3)}
    base = {
        p: sha256(root / p)
        for p in [source, c.SELF, c.TEST, c.fit.data.FREEZE, c.RECOVERY_SOURCE, c.RECOVERY_CLI]
    }
    external = {}
    for name in c.external_paths(root, freeze):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original reference")
        external[name] = sha256(path)
    base.update(external)
    calls = []
    worker = SimpleNamespace()

    def verify(root, role=None):
        phase = (
            "check"
            if role == "check_training"
            else "full_development"
            if role
            else "full_design_recovery"
        )
        name = c.phase_gate(phase)
        gate = json.loads((root / name).read_text())
        return {
            "gate": gate,
            "files": {**gate["files"], name: sha256(root / name)},
            "freeze": freeze,
            "specs": specs,
        }

    def paths(root, job):
        phase = "check" if job["role"].startswith("check_") else job["role"]
        output = (
            c.fit.CHECK_OUTPUT
            if phase == "check"
            else c.RECOVERY_OUTPUT
            if phase == "full_design_recovery"
            else c.fit.FULL_OUTPUT
        )
        store = c.RECOVERY_STORE if phase == "full_design_recovery" else c.fit.STORE
        return root / output / "jobs" / job["id"], None if not c.cost(job) else root / store / (
            job["id"] + ".nc"
        )

    def proof(root, job, pins, accepted=None):
        folder, raw = paths(root, job)
        assert json.loads((folder / "result.json").read_text())["status"] == c.fit.SUCCESS
        manifest = json.loads((folder / "output-checksums.json").read_text())
        files = {
            str((folder / name).relative_to(root)): digest for name, digest in manifest.items()
        }
        files[str((folder / "output-checksums.json").relative_to(root))] = sha256(
            folder / "output-checksums.json"
        )
        c.previous._unchanged(root, files)
        if raw is not None:
            files[str(raw.relative_to(root))] = sha256(raw)
        if accepted is not None:
            assert accepted["files"] == files
        return {"files": files}

    worker.verify_gate, worker.case_paths, worker.case_artifacts = verify, paths, proof
    monkeypatch.setattr(c, "consumer", lambda phase: worker)
    monkeypatch.setattr(c, "git_sha", lambda root: "a" * 40)
    monkeypatch.setattr(c, "limit_worker_file_size", lambda *a: None)

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        state = json.loads((root / c.STATE).read_text())
        assert state["current"]["job_id"] == job["id"]
        calls.append(job)
        folder, raw = paths(root, job)
        folder.mkdir(parents=True)
        if raw is None:
            assert "--store" not in command
        else:
            assert command[command.index("--store") + 1] == str(raw)
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"synthetic posterior")
            write_json(folder / "sampling-start.json", job)
        write_json(folder / "job.json", job)
        write_json(folder / "result.json", {"status": c.fit.SUCCESS})
        write_json(
            folder / "output-checksums.json",
            {p.name: sha256(p) for p in folder.iterdir() if p.is_file()},
        )
        log.write_text("synthetic child")
        return {"returncode": 0, "reason": "worker_exit", "elapsed_seconds": 0.01}

    monkeypatch.setattr(c, "supervise", supervise)

    def gate(phase, inherited=0):
        jobs = []
        for i, key in enumerate(specs):
            if phase == "check" and training:
                jobs.append(
                    dict(
                        id=f"dev-train-{i}",
                        order=len(jobs),
                        role="check_training",
                        model_key=key,
                        seed=700 + i,
                        training_reference=None,
                    )
                )
            jobs.append(
                dict(
                    id=f"dev-{phase.replace('_', '-')}-{i}",
                    order=len(jobs),
                    role="check_evaluate" if phase == "check" else phase,
                    model_key=key,
                    seed=800 + i,
                    training_reference=(
                        {
                            "kind": "new_fit",
                            "job_id": f"dev-train-{i}",
                            "review": c.fit.CHECK_OUTPUT
                            + f"/jobs/dev-train-{i}/review-acceptance.json",
                        }
                        if training
                        else {"kind": "historical"}
                    )
                    if phase == "check"
                    else None,
                )
            )
        files = dict(base)
        for review in [c.fit.data.CHECK_REVIEW, c.RECOVERY_REVIEW]:
            if (root / review).is_file():
                value = json.loads((root / review).read_text())
                files.update(value["files"])
                files[review] = sha256(root / review)
        body = {
            "status": "accepted_frozen_arrival_development_recovery_execution"
            if phase == "full_design_recovery"
            else "accepted_frozen_arrival_development_execution",
            "independent_checker": True,
            "resources": c.fit.resources(),
            "path_bindings": c.bindings(root),
            "files": files,
            "max_sampler_call_slots": 12,
            "jobs": jobs,
            "inherited_calls": {"charged": inherited, "started": inherited},
            "parent_minimum_bytes": floors,
            "external_reference_files": external,
        }
        write_json(root / c.phase_gate(phase), body)
        return body

    gate("check")
    return gate, calls, worker


def state(root):
    return json.loads((root / c.STATE).read_text())


def review_phase(root, phase):
    s = state(root)
    entry = s["phases"][phase]
    files = {str(Path(c.CONTROL) / (phase + "-plan.json")): entry["plan_sha256"]}
    for a in entry["accepted"]:
        files.update(a["files"])
        files[a["receipt"]] = a["receipt_sha256"]
    path = c.fit.data.CHECK_REVIEW if phase == "check" else c.RECOVERY_REVIEW
    write_json(
        root / path,
        {
            "status": "accepted_frozen_arrival_development_check"
            if phase == "check"
            else "accepted_frozen_full_development_design_checks",
            "independent_checker": True,
            "completed_once": True,
            "no_retuning": True,
            "files": files,
            "specification_freeze_sha256": s["specification_freeze_sha256"],
        },
    )


def pilots(root):
    s = state(root)
    files = {}
    for phase, entry in s["phases"].items():
        for a in (entry or {}).get("accepted", []):
            if phase + ":" + a["job_id"] in s["sampler_pilot_job_ids"]:
                files.update(a["files"])
                files[a["receipt"]] = a["receipt_sha256"]
    write_json(
        root / c.PILOT_REVIEW,
        {
            "status": "accepted_development_two_sampler_runtime_pilots",
            "independent_checker": True,
            "sampler_pilot_job_ids": s["sampler_pilot_job_ids"],
            "specification_freeze_sha256": s["specification_freeze_sha256"],
            "files": files,
        },
    )


def test_zero_call_check_then_recovery_pilots_then_full_same_ledger(tmp_path, monkeypatch):
    gate, calls, _ = fixture(tmp_path, monkeypatch)
    c.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == s["calls_started"] == 0
    assert s["phases"]["check"]["next_job"] == 3 and len(calls) == 3
    check_plan = (tmp_path / c.CONTROL / "check-plan.json").read_bytes()
    review_phase(tmp_path, "check")
    gate("full_design_recovery")
    c.run(tmp_path, phase="full_design_recovery", resume=True)
    assert state(tmp_path)["calls_started"] == 2 and len(calls) == 5
    assert state(tmp_path)["status"] == "awaiting_sampler_pilot_review"
    pilots(tmp_path)
    c.run(tmp_path, phase="full_design_recovery", resume=True)
    assert state(tmp_path)["calls_started"] == 3
    review_phase(tmp_path, "full_design_recovery")
    gate("full_development", inherited=3)
    c.run(tmp_path, phase="full_development", resume=True)
    assert state(tmp_path)["calls_started"] == state(tmp_path)["calls_charged"] == 6
    assert (tmp_path / c.CONTROL / "check-plan.json").read_bytes() == check_plan
    before = (tmp_path / c.STATE).read_bytes()
    c.run(tmp_path, phase="full_development", resume=True)
    assert (tmp_path / c.STATE).read_bytes() == before


def test_missing_training_review_pauses_without_eval_dispatch_or_extra_cost(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch, training=True)
    c.run(tmp_path)
    assert (
        len(calls) == 1
        and state(tmp_path)["calls_charged"] == state(tmp_path)["calls_started"] == 1
    )
    assert state(tmp_path)["status"] == "awaiting_training_review"
    assert state(tmp_path)["phases"]["check"]["next_job"] == 1
    c.run(tmp_path, resume=True)
    assert len(calls) == 1


@pytest.mark.parametrize("bad", ["missing-gate", "source", "ceiling", "STOP", "inherited"])
def test_admission_failures_allocate_nothing(tmp_path, monkeypatch, bad):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    path = tmp_path / c.fit.GATE
    if bad == "missing-gate":
        path.unlink()
    elif bad == "source":
        (tmp_path / "frozen.py").write_text("drift")
    elif bad == "STOP":
        (tmp_path / c.r.OUTPUT).mkdir(parents=True, exist_ok=True)
        (tmp_path / c.r.OUTPUT / "STOP").write_text("stop")
    else:
        value = json.loads(path.read_text())
        if bad == "ceiling":
            value["max_sampler_call_slots"] = 98
        else:
            value["inherited_calls"]["charged"] = 1
        write_json(path, value)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert not calls and not (tmp_path / c.STATE).exists()


def test_zero_call_failure_stops_retains_attempt_and_never_omits(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    original = c.supervise

    def failed(*args):
        result = original(*args)
        return {**result, "returncode": 2}

    monkeypatch.setattr(c, "supervise", failed)
    with pytest.raises(ValueError, match="failed computation"):
        c.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == s["calls_started"] == 0 and len(calls) == 1
    assert s["status"] == "needs_review" and s["phases"]["check"]["next_job"] == 0
    assert len(s["phases"]["check"]["attempts"]) == 1
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)


def test_precharged_fit_failure_no_refund_and_current_interrupt_blocks(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch, training=True)
    monkeypatch.setattr(c, "supervise", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(ValueError):
        c.run(tmp_path)
    s = state(tmp_path)
    assert s["calls_charged"] == 1 and s["calls_started"] == 0 and not calls
    assert s["status"] == "needs_review"
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)


def test_mutated_proof_and_unknown_raw_reject_resume(tmp_path, monkeypatch):
    _, _, _ = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=1)
    a = state(tmp_path)["phases"]["check"]["accepted"][0]
    process = next(p for p in a["files"] if p.endswith(".supervisor.json"))
    (tmp_path / process).write_text("{}")
    before = (tmp_path / c.STATE).read_bytes()
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True)
    assert (tmp_path / c.STATE).read_bytes() == before


def test_source_change_inside_lease_and_before_launch_blocks(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch, training=True)
    atomic = c.atomic_state

    def drift(path, s):
        atomic(path, s)
        if s.get("current"):
            (tmp_path / "frozen.py").write_text("after precharge")

    monkeypatch.setattr(c, "atomic_state", drift)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    assert not calls and state(tmp_path)["calls_charged"] == 1
    assert state(tmp_path)["status"] == "needs_review"


@pytest.mark.parametrize("kind", ["raw", "job"])
def test_unknown_partial_inventory_stops_before_resume_dispatch(tmp_path, monkeypatch, kind):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=1)
    before = (tmp_path / c.STATE).read_bytes()
    path = tmp_path / (
        c.fit.STORE + "/unknown.nc" if kind == "raw" else c.fit.CHECK_OUTPUT + "/jobs/unknown.log"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"retained unknown partial")
    with pytest.raises(ValueError, match="partial"):
        c.run(tmp_path, resume=True)
    assert len(calls) == 1 and (tmp_path / c.STATE).read_bytes() == before
    assert path.is_file()


def test_training_dependency_review_identity_is_sealed_for_resume(tmp_path, monkeypatch):
    _, calls, worker = fixture(tmp_path, monkeypatch, training=True)
    c.run(tmp_path)
    a = state(tmp_path)["phases"]["check"]["accepted"][0]
    path = tmp_path / c.fit.CHECK_OUTPUT / "jobs" / "dev-train-0" / "review-acceptance.json"
    write_json(
        path,
        {
            "status": "accepted_frozen_development_training_posterior",
            "independent_checker": True,
            "job_id": "dev-train-0",
            "model_key": "target0:event:selected",
            "specification_freeze_sha256": state(tmp_path)["specification_freeze_sha256"],
            "files": {
                **worker.verify_gate(tmp_path, "check_training")["files"],
                **a["files"],
                a["receipt"]: a["receipt_sha256"],
            },
        },
    )
    c.run(tmp_path, resume=True, max_jobs=1)
    assert len(calls) == 2 and state(tmp_path)["calls_charged"] == 1
    before = (tmp_path / c.STATE).read_bytes()
    value = json.loads(path.read_text())
    value["unreviewed_change"] = True
    write_json(path, value)
    with pytest.raises(ValueError, match="identity changed"):
        c.run(tmp_path, resume=True)
    assert (tmp_path / c.STATE).read_bytes() == before and len(calls) == 2


def test_private_counter_refund_cannot_change_a_frozen_fit_role_cost(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch, training=True)
    c.run(tmp_path)
    value = state(tmp_path)
    value.update(calls_charged=0, calls_started=0, sampler_pilot_job_ids=[])
    for a in value["phases"]["check"]["accepted"] + value["phases"]["check"]["attempts"]:
        a.update(cost=0, start_markers=0)
    write_json(tmp_path / c.STATE, value)
    before = (tmp_path / c.STATE).read_bytes()
    with pytest.raises(ValueError, match="role-cost"):
        c.run(tmp_path, resume=True)
    assert len(calls) == 1 and (tmp_path / c.STATE).read_bytes() == before


def test_three_phase_resources_keep_oldstores_cache_job_and_floor_guards(tmp_path, monkeypatch):
    _, _, worker = fixture(tmp_path, monkeypatch)
    admission = c.admit(tmp_path, "check")
    assert c.quota(tmp_path, admission) is None
    original_working, original_bytes = c.r.working_bytes, c.r.byte_count
    monkeypatch.setattr(c.r, "working_bytes", lambda *a: 3072 * c.r.MIB)
    assert c.quota(tmp_path, admission) == "global_storage"
    monkeypatch.setattr(c.r, "working_bytes", original_working)
    cache_roots = (tmp_path / c.fit.STORE / "cache", tmp_path / c.RECOVERY_STORE / "cache")
    monkeypatch.setattr(
        c.r, "byte_count", lambda *a: c.r.MAX_CACHE + 1 if a == cache_roots else original_bytes(*a)
    )
    assert c.quota(tmp_path, admission) == "cache_storage"
    monkeypatch.setattr(c.r, "byte_count", original_bytes)
    job = {"id": "dev-current", "role": "check_training"}
    paths = c.paths(tmp_path, job, worker)
    raw = paths[1]
    raw.parent.mkdir(parents=True, exist_ok=True)
    with raw.open("wb") as stream:
        stream.truncate(c.r.MAX_JOB + 1)
    assert c.quota(tmp_path, admission, paths) == "combined_job_storage"
    with raw.open("wb") as stream:
        stream.truncate(c.r.FILE_MAX + 1)
    assert c.quota(tmp_path, admission) == "per_file_storage"
    raw.unlink()
    (c.r.parent_roots(tmp_path)[0] / "floor").unlink()
    assert c.quota(tmp_path, admission) == "parent_floor_or_storage_scan_failure"


def training_review(root, worker):
    a = state(root)["phases"]["check"]["accepted"][0]
    return {
        "status": "accepted_frozen_development_training_posterior",
        "independent_checker": True,
        "job_id": a["job_id"],
        "model_key": "target0:event:selected",
        "specification_freeze_sha256": state(root)["specification_freeze_sha256"],
        "files": {
            **worker.verify_gate(root, "check_training")["files"],
            **a["files"],
            a["receipt"]: a["receipt_sha256"],
        },
    }


@pytest.mark.parametrize(
    "bad", ["one-pin", "source", "worker", "process", "receipt", "model", "freeze"]
)
def test_incomplete_training_review_rejects_before_zero_call_dispatch(tmp_path, monkeypatch, bad):
    _, calls, worker = fixture(tmp_path, monkeypatch, training=True)
    c.run(tmp_path)
    a = state(tmp_path)["phases"]["check"]["accepted"][0]
    review = training_review(tmp_path, worker)
    if bad == "one-pin":
        review["files"] = {"frozen.py": sha256(tmp_path / "frozen.py")}
    elif bad == "source":
        del review["files"]["frozen.py"]
    elif bad == "worker":
        del review["files"][next(iter(a["worker_files"]))]
    elif bad == "process":
        del review["files"][next(p for p in a["files"] if p.endswith(".supervisor.json"))]
    elif bad == "receipt":
        del review["files"][a["receipt"]]
    elif bad == "model":
        review["model_key"] = "other:event:selected"
    else:
        review["specification_freeze_sha256"] = "0" * 64
    path = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-train-0/review-acceptance.json"
    write_json(path, review)
    with pytest.raises(ValueError):
        c.run(tmp_path, resume=True, max_jobs=1)
    s = state(tmp_path)
    assert len(calls) == 1 and s["phases"]["check"]["next_job"] == 1
    assert s["calls_charged"] == s["calls_started"] == 1


@pytest.mark.parametrize(
    "when,kind",
    [
        ("attempt", "small"),
        ("attempt", "large"),
        ("attempt", "source"),
        ("attempt", "listed"),
        ("attempt", "attempt-sibling"),
        ("summary", "small"),
        ("summary", "large"),
    ],
)
def test_late_unlisted_or_changed_artifact_never_returns_success(tmp_path, monkeypatch, when, kind):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    original = c.new_json
    injected = []

    def late(path, value):
        original(path, value)
        if injected or not (
            "attempts" in path.parts if when == "attempt" else path.name == "check-summary.json"
        ):
            return
        folder = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-check-0"
        if kind == "source":
            target = tmp_path / "frozen.py"
            target.write_text("late drift")
        elif kind == "listed":
            target = folder / "result.json"
            target.write_text("{}")
        elif kind == "attempt-sibling":
            target = path.with_name("unknown-attempt.json")
            target.write_text("{}")
        else:
            target = folder / "unlisted-late.bin"
            target.write_bytes(b"x" * (9000 if kind == "large" else 1))
        injected.append(target)

    monkeypatch.setattr(c, "new_json", late)
    if kind == "large":
        monkeypatch.setattr(c.r, "MAX_JOB", 8192)
    with pytest.raises(ValueError):
        c.run(tmp_path)
    s = state(tmp_path)
    assert s["status"] == "needs_review" and injected[0].exists()
    assert not (tmp_path / c.CONTROL / ".controller.lock").exists()
    assert s["calls_charged"] == s["calls_started"] == 0
    assert len(calls) == (1 if when == "attempt" else 3)
    if when == "attempt":
        assert s["phases"]["check"]["next_job"] == 0
        a = s["phases"]["check"]["attempts"][0]
        assert a["outcome"] == "needs_review" and (tmp_path / a["receipt"]).exists()


def test_attempt_receipt_counts_in_combined_job_cap(tmp_path, monkeypatch):
    _, _, worker = fixture(tmp_path, monkeypatch)
    original = c.new_json

    def cap_after_receipt(path, value):
        original(path, value)
        if "attempts" in path.parts and not path.name.endswith("-failure.json"):
            job = json.loads((tmp_path / c.fit.GATE).read_text())["jobs"][0]
            folder, raw, spec, log, process = c.paths(tmp_path, job, worker)
            before = c.r.byte_count(folder) + sum(
                p.stat().st_size for p in [raw, spec, log, process] if p is not None and p.is_file()
            )
            monkeypatch.setattr(c.r, "MAX_JOB", before + path.stat().st_size - 1)

    monkeypatch.setattr(c, "new_json", cap_after_receipt)
    with pytest.raises(ValueError):
        c.run(tmp_path, max_jobs=1)
    s = state(tmp_path)
    assert s["status"] == "needs_review" and s["phases"]["check"]["next_job"] == 0


@pytest.mark.parametrize("kind", ["unknown", "missing", "symlink", "directory", "review"])
def test_closed_job_literal_inventory_rejects_resume_without_dispatch(tmp_path, monkeypatch, kind):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    c.run(tmp_path, max_jobs=1)
    folder = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-check-0"
    if kind == "missing":
        (folder / "job.json").unlink()
    elif kind == "symlink":
        (folder / "unlisted").symlink_to(tmp_path / "frozen.py")
    elif kind == "directory":
        (folder / "unlisted-empty").mkdir()
    elif kind == "review":
        (folder / "review-acceptance.json").write_text("{}")
    else:
        (folder / "unlisted").write_bytes(b"retained")
    before = (tmp_path / c.STATE).read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        c.run(tmp_path, resume=True)
    assert len(calls) == 1 and (tmp_path / c.STATE).read_bytes() == before


def test_late_fit_failure_retains_charge_raw_evidence_and_releases_leases(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch, training=True)
    original = c.new_json

    def late(path, value):
        original(path, value)
        if path.name == "dev-train-0.json":
            folder = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-train-0"
            (folder / "unlisted-late.bin").write_bytes(b"retained")

    monkeypatch.setattr(c, "new_json", late)
    with pytest.raises(ValueError, match="failed computation"):
        c.run(tmp_path)
    s = state(tmp_path)
    a = s["phases"]["check"]["attempts"][0]
    assert len(calls) == s["calls_charged"] == s["calls_started"] == 1
    assert s["status"] == "needs_review" and s["phases"]["check"]["next_job"] == 0
    assert (tmp_path / c.fit.STORE / "dev-train-0.nc").is_file()
    assert (tmp_path / a["receipt"]).is_file() and (tmp_path / a["failure"]).is_file()
    assert not (tmp_path / c.CONTROL / ".controller.lock").exists()
    with c.r._leases(tmp_path):
        pass


def test_independent_parent_review_is_excluded_from_manifest_but_counts_toward_cap(
    tmp_path, monkeypatch
):
    _, calls, worker = fixture(tmp_path, monkeypatch, training=True)
    c.run(tmp_path)
    folder = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-train-0"
    review = training_review(tmp_path, worker)
    review["review_notes"] = "x" * 9000
    write_json(folder / "review-acceptance.json", review)
    monkeypatch.setattr(c.r, "MAX_JOB", 8192)
    with pytest.raises(ValueError, match="job resource"):
        c.run(tmp_path, resume=True)
    assert len(calls) == 1 and state(tmp_path)["calls_charged"] == 1


def test_late_change_to_earlier_accepted_job_blocks_current_acceptance(tmp_path, monkeypatch):
    _, calls, _ = fixture(tmp_path, monkeypatch)
    original = c.new_json

    def late(path, value):
        original(path, value)
        if "attempts" in path.parts and path.name == "dev-check-1.json":
            folder = tmp_path / c.fit.CHECK_OUTPUT / "jobs/dev-check-0"
            (folder / "unlisted-late.bin").write_bytes(b"retained earlier-job drift")

    monkeypatch.setattr(c, "new_json", late)
    with pytest.raises(ValueError, match="failed computation"):
        c.run(tmp_path)
    s = state(tmp_path)
    assert len(calls) == 2 and s["status"] == "needs_review"
    assert s["phases"]["check"]["next_job"] == 1
    assert s["current"]["job_id"] == "dev-check-1"
    assert len(s["phases"]["check"]["attempts"]) == 2


def test_sensitivity_repair_store_all_bytes_reach_global_budget(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    admission = c.admit(tmp_path, "check")
    repair = tmp_path / "data/processed/models/arrival-sensitivity-repair-v1"
    for name, size in [("repair.nc", 13), ("cache/compiled.bin", 17), ("unlisted.partial", 29)]:
        path = repair / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    external = sum(
        (tmp_path / name).stat().st_size for name in admission["gate"]["external_reference_files"]
    )
    working = (
        3072 * c.r.MIB - c.r.byte_count(*c.roots(tmp_path)) - external - c.r.byte_count(repair) + 1
    )
    monkeypatch.setattr(c.r, "working_bytes", lambda *args: working)
    assert c.quota(tmp_path, admission) == "global_storage"


@pytest.mark.parametrize("bad", ["large-file", "root-symlink", "child-symlink"])
def test_sensitivity_repair_store_shares_global_file_and_symlink_guards(tmp_path, monkeypatch, bad):
    fixture(tmp_path, monkeypatch)
    admission = c.admit(tmp_path, "check")
    repair = tmp_path / "data/processed/models/arrival-sensitivity-repair-v1"
    repair.parent.mkdir(parents=True, exist_ok=True)
    if bad == "root-symlink":
        target = tmp_path / "retained-repair-files"
        target.mkdir()
        repair.symlink_to(target, target_is_directory=True)
    else:
        repair.mkdir()
        if bad == "child-symlink":
            (repair / "unlisted.partial").symlink_to(tmp_path / "frozen.py")
        else:
            with (repair / "unlisted.partial").open("wb") as stream:
                stream.truncate(c.r.FILE_MAX + 1)
    assert c.quota(tmp_path, admission) == (
        "per_file_storage" if bad == "large-file" else "symlink_storage"
    )


def test_sensitivity_repair_store_counted_once_without_changing_local_or_phase_cache(
    tmp_path, monkeypatch
):
    fixture(tmp_path, monkeypatch)
    admission = c.admit(tmp_path, "check")
    repair = tmp_path / "data/processed/models/arrival-sensitivity-repair-v1"
    repair.mkdir(parents=True)
    (repair / "unlisted.partial").write_bytes(b"retained")
    original = c.r.byte_count
    # One historical store fits globally; counting it twice or locally exceeds a cap.
    historical = 2200 * c.r.MIB
    calls = []

    def count(*paths):
        calls.append(paths)
        return original(*paths) + (historical if repair in paths else 0)

    monkeypatch.setattr(c.r, "working_bytes", lambda *args: 0)
    monkeypatch.setattr(c.r, "byte_count", count)
    assert c.quota(tmp_path, admission) is None
    assert sum(repair in paths for paths in calls) == 1
    assert repair not in c.roots(tmp_path)
    assert (tmp_path / c.fit.STORE / "cache", tmp_path / c.RECOVERY_STORE / "cache") in calls


def test_sensitivity_repair_training_reference_is_not_counted_as_external_twice(tmp_path):
    raw = "data/processed/models/arrival-sensitivity-repair-v1/unexpected-reference.nc"
    baseline = c.external_paths(tmp_path, {"training_references": {}})
    actual = c.external_paths(tmp_path, {"training_references": {"example": {"raw": raw}}})
    assert actual == baseline
