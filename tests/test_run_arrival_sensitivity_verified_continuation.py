"""Synthetic transparent proof capture, fresh-byte reuse and foreground session guards."""

# pyright: basic
import copy
import json
import os

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivity_verified_continuation as p
from tests.test_arrival_sensitivity_controller import accept_pilots
from tests.test_run_arrival_sensitivity_continuation import setup as resource_fixture

c, r = p.c, p.r
NAMES = [
    "job.json",
    "inputs.json",
    "membership.json",
    "sampling-start.json",
    "result.json",
    "diagnostics.json",
    "sampling-diagnostics.csv",
    "summary.json",
    "parameters.csv",
    "derived.csv",
    "curves.csv",
    "conditional-ppc.csv",
    "record-intervals.csv",
]


def fixture(root, monkeypatch):
    jobs, gate, calls = resource_fixture(root, monkeypatch)
    original = r.case_artifacts
    delegated = []
    returned = []

    def complete(root, job, pins, accepted=None):
        folder = r.case_paths(root, job)[0]
        for name in NAMES:
            path = folder / name
            if not path.exists():
                path.write_text("synthetic stable scientific artifact")
        result = original(root, job, pins, accepted)
        delegated.append((job["id"], accepted is None))
        returned.append(result)
        return result

    # Build a synthetic closed two-case fixture with the complete real mandatory inventory.
    state = json.loads((root / r.STATE).read_text())
    for job, accepted, attempt in zip(jobs[:2], state["accepted"], state["attempts"], strict=True):
        files, manifest = complete(root, job, gate["files"], None)
        write_json(manifest, {"case_id": job["id"], "files": files})
        accepted.update(files=files, receipt_sha256=sha256(manifest))
        attempt["receipt_sha256"] = sha256(manifest)
    write_json(root / r.STATE, state)
    write_json(root / c.BASELINE, state)
    accept_pilots(root)
    gate["pilot_review_sha256"] = sha256(root / r.PILOT_REVIEW)
    gate["files"].update(
        {c.BASELINE: sha256(root / c.BASELINE), r.PILOT_REVIEW: sha256(root / r.PILOT_REVIEW)}
    )
    for a in state["accepted"]:
        gate["files"].update(a["files"])
        gate["files"][a["receipt"]] = a["receipt_sha256"]
    write_json(root / c.GATE, gate)
    monkeypatch.setattr(r, "case_artifacts", complete)
    c.run(root, max_cases=4)
    state = json.loads((root / r.STATE).read_text())
    assert state["next_case"] == 6
    write_json(root / p.BASELINE, state)
    for name in [p.SELF, p.TEST]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen proof-reuse source")
    checked = c.verify_continuation(root)
    pins = {
        **checked["files"],
        p.BASELINE: sha256(root / p.BASELINE),
        p.SELF: sha256(root / p.SELF),
        p.TEST: sha256(root / p.TEST),
    }
    for a in state["accepted"]:
        pins.update(a["files"])
        pins[a["receipt"]] = a["receipt_sha256"]
    performance = {
        "status": "accepted_sensitivity_in_memory_proof_reuse",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "resources": c.resources(),
        "path_bindings": r.path_bindings(root),
        "proof_contract": p.CONTRACT,
        "files": pins,
        "original_science_gate_sha256": pins[r.GATE],
        "resource_gate_sha256": pins[c.GATE],
        "original_plan_sha256": pins[c.PLAN],
    }
    write_json(root / p.PERFORMANCE_GATE, performance)
    delegated.clear()
    returned.clear()
    return jobs, calls, delegated, returned


def current(root):
    return json.loads((root / r.STATE).read_text())


def cache(root):
    checked = p.verify_gate(root)
    return p.ProofCache(root, checked, r.case_artifacts, c._unchanged), checked


def test_transparent_capture_preserves_original_arguments_and_tuple_identity(tmp_path, monkeypatch):
    jobs, _, delegated, returned = fixture(tmp_path, monkeypatch)
    proof, checked = cache(tmp_path)
    accepted = current(tmp_path)["accepted"][0]
    result = proof.capture(tmp_path, jobs[0], checked["resource"]["old_pins"], accepted=accepted)
    assert result is returned[-1] and delegated == [(jobs[0]["id"], False)]
    assert proof.counts["full_proofs"] == 1
    proof.clear()
    assert not proof.pending and not proof.accepted


def test_each_new_dispatch_full_once_then_pending_promotes_with_fresh_bytes(tmp_path, monkeypatch):
    jobs, calls, delegated, _ = fixture(tmp_path, monkeypatch)
    checked = p.verify_gate(tmp_path)
    bindings = (
        r.case_artifacts,
        r._proofs,
        r._unchanged,
        r.supervise,
        r._leases,
        c.parallel_proofs,
        c._unchanged,
    )
    with p.session(tmp_path, checked) as proof:
        proof.expected_state_sha256 = sha256(tmp_path / r.STATE)
        c.run(tmp_path, max_cases=4)
        assert len(calls) == 10 and proof.counts["full_proofs"] == 10
        assert proof.counts["pending_captures"] == proof.counts["pending_promotions"] == 4
        assert all(
            sum(name == j["id"] and pending for name, pending in delegated) == 1 for j in jobs[6:10]
        )
        assert all(sum(name == j["id"] for name, _ in delegated) == 1 for j in jobs[:10])
        assert proof.counts["warm_checks"] > 0
        process = json.loads(r.case_paths(tmp_path, jobs[6])[-1].read_text())
        assert process["performance_gate_sha256"] == sha256(tmp_path / p.PERFORMANCE_GATE)
        assert process["resource_amendment_gate_sha256"] == sha256(tmp_path / c.GATE)
    assert (
        r.case_artifacts,
        r._proofs,
        r._unchanged,
        r.supervise,
        r._leases,
        c.parallel_proofs,
        c._unchanged,
    ) == bindings
    assert not proof.pending and not proof.accepted


@pytest.mark.parametrize(
    "category",
    [
        "raw",
        "spec",
        "log",
        "supervisor",
        "summary",
        "csv",
        "manifest",
        "added",
        "deleted",
        "symlink",
        "directory",
        "accepted",
        "attempt",
        "job",
        "pins",
        "resigned",
    ],
)
def test_warm_proof_never_trusts_mtime_size_or_incomplete_inventory(
    tmp_path, monkeypatch, category
):
    jobs, _, _, _ = fixture(tmp_path, monkeypatch)
    proof, checked = cache(tmp_path)
    s = current(tmp_path)
    pins = checked["resource"]["old_pins"]
    proof.proofs(tmp_path, s, jobs, pins)
    folder, raw, spec, log, process = r.case_paths(tmp_path, jobs[0])
    target = {
        "raw": raw,
        "spec": spec,
        "log": log,
        "supervisor": process,
        "summary": folder / "summary.json",
        "csv": folder / "curves.csv",
        "manifest": folder / "attempt-evidence.json",
    }.get(category)
    if target is not None:
        stat = target.stat()
        payload = target.read_bytes()
        target.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert (
            target.stat().st_size == stat.st_size and target.stat().st_mtime_ns == stat.st_mtime_ns
        )
    elif category == "added":
        (folder / "unknown.bin").write_bytes(b"unknown")
    elif category == "deleted":
        (folder / "curves.csv").unlink()
    elif category == "symlink":
        (folder / "curves.csv").unlink()
        (folder / "curves.csv").symlink_to(folder / "parameters.csv")
    elif category == "directory":
        (folder / "empty-unrecorded").mkdir()
    elif category == "accepted":
        s["accepted"][0]["extra"] = "changed"
    elif category == "attempt":
        s["attempts"][0]["extra"] = "changed"
    elif category == "job":
        jobs = copy.deepcopy(jobs)
        jobs[0]["seed"] += 1
    elif category == "pins":
        pins = {**pins, "changed-pin": "0" * 64}
    else:
        path = folder / "attempt-evidence.json"
        value = json.loads(path.read_text())
        path.write_text(json.dumps(value, separators=(",", ":")))
        s["accepted"][0]["receipt_sha256"] = s["attempts"][0]["receipt_sha256"] = sha256(path)
    with pytest.raises((ValueError, AssertionError)):
        proof.proofs(tmp_path, s, jobs, pins)


def test_failed_cold_original_and_two_thread_exception_do_not_cache_success(tmp_path, monkeypatch):
    jobs, _, _, _ = fixture(tmp_path, monkeypatch)
    proof, checked = cache(tmp_path)

    def failed(*args, **kwargs):
        raise ValueError("original proof failed")

    proof.original = failed
    with pytest.raises(ValueError, match="original proof failed"):
        proof.proofs(tmp_path, current(tmp_path), jobs, checked["resource"]["old_pins"])
    assert not proof.pending and not proof.accepted


@pytest.mark.parametrize("failure", ["STOP", "source", "quota", "receipt", "interruption"])
def test_successful_dispatch_verifier_is_only_pending_until_all_acceptance_guards(
    tmp_path, monkeypatch, failure
):
    jobs, _, _, _ = fixture(tmp_path, monkeypatch)
    proof, checked = cache(tmp_path)
    s = current(tmp_path)
    accepted = s["accepted"][0]
    result = proof.capture(tmp_path, jobs[0], checked["resource"]["old_pins"], None)
    assert result and not proof.accepted and jobs[0]["id"] in proof.pending
    if failure == "STOP":
        (tmp_path / r.OUTPUT / "STOP").write_text("stop")
    elif failure == "source":
        (tmp_path / p.SELF).write_text("changed source")
    elif failure == "quota":
        monkeypatch.setattr(c, "quota_failure", lambda *a, **k: "global_storage")
    elif failure == "receipt":
        (tmp_path / accepted["receipt"]).unlink()
    else:
        s["current"] = jobs[0]["id"]
        s["status"] = "sensitivity_needs_review"
    with pytest.raises(ValueError):
        proof.proofs(tmp_path, s, jobs, checked["resource"]["old_pins"])
    assert jobs[0]["id"] not in proof.accepted


def test_outer_foreground_pause_EOF_clears_hooks_and_new_process_is_cold(tmp_path, monkeypatch):
    _, _, delegated, _ = fixture(tmp_path, monkeypatch)
    saved = r.case_artifacts, c.parallel_proofs, c._unchanged, r._unchanged, r.supervise, r._leases
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError()))
    with pytest.raises(EOFError):
        p.run(tmp_path, invocations=2, pause_between_batches=True)
    assert (
        r.case_artifacts,
        c.parallel_proofs,
        c._unchanged,
        r._unchanged,
        r.supervise,
        r._leases,
    ) == saved
    assert current(tmp_path)["next_case"] == 10
    before = len(delegated)
    proof, checked = cache(tmp_path)
    proof.proofs(
        tmp_path, current(tmp_path), checked["resource"]["jobs"], checked["resource"]["old_pins"]
    )
    assert len(delegated) - before == 10


def test_foreign_STATE_pause_and_explicit_multi_batch_guard(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="pause flag"):
        p.run(tmp_path, invocations=2)

    def foreign(prompt):
        s = current(tmp_path)
        s["foreign_owner"] = True
        write_json(tmp_path / r.STATE, s)
        return ""

    monkeypatch.setattr("builtins.input", foreign)
    with pytest.raises(ValueError, match="foreign STATE"):
        p.run(tmp_path, invocations=2, pause_between_batches=True)
    assert current(tmp_path)["next_case"] == 10


def test_final_telemetry_storage_failure_marks_review_and_restores(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    saved = r.case_artifacts, c.parallel_proofs, c._unchanged
    original = p.ProofCache.runtime

    def late(self):
        if list((tmp_path / p.CONTROL / "sessions").glob("*/after.json")):
            raise ValueError("late telemetry storage")
        return original(self)

    monkeypatch.setattr(p.ProofCache, "runtime", late)
    with pytest.raises(ValueError, match="late telemetry"):
        p.run(tmp_path)
    assert current(tmp_path)["status"] == "sensitivity_needs_review"
    assert (r.case_artifacts, c.parallel_proofs, c._unchanged) == saved
    assert list((tmp_path / p.CONTROL / "sessions").glob("*/failure.json"))


def test_transparent_keyword_arguments_are_identical_to_original(tmp_path, monkeypatch):
    jobs, _, _, _ = fixture(tmp_path, monkeypatch)
    proof, checked = cache(tmp_path)
    original = proof.original
    seen, results = [], []

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        value = original(*args, **kwargs)
        results.append(value)
        return value

    proof.original = spy
    accepted = current(tmp_path)["accepted"][0]
    pins = checked["resource"]["old_pins"]
    value = proof.capture(root=tmp_path, job=jobs[0], pins=pins, accepted=accepted)
    assert value is results[0] and seen[0][0] == ()
    assert seen[0][1]["root"] is tmp_path and seen[0][1]["job"] is jobs[0]
    assert seen[0][1]["pins"] is pins and seen[0][1]["accepted"] is accepted


@pytest.mark.parametrize("failure", ["STOP", "source", "quota", "receipt", "interruption"])
def test_real_old_dispatch_late_failures_never_promote_pending(tmp_path, monkeypatch, failure):
    jobs, calls, _, _ = fixture(tmp_path, monkeypatch)
    original = r.case_artifacts

    def late(root, job, pins, accepted=None):
        result = original(root, job, pins, accepted)
        if accepted is None:
            if failure == "STOP":
                (root / r.OUTPUT / "STOP").write_text("after full verifier")
            elif failure == "source":
                (root / p.SELF).write_text("after full verifier")
            elif failure == "quota":
                monkeypatch.setattr(c, "quota_failure", lambda *a, **k: "late_quota")
            elif failure == "interruption":
                raise KeyboardInterrupt
        return result

    monkeypatch.setattr(r, "case_artifacts", late)
    if failure == "receipt":
        writer = r.new_json

        def interrupted(path, value):
            if path.name == "attempt-evidence.json" and path.parent.name == jobs[6]["id"]:
                raise OSError("synthetic receipt write failure")
            return writer(path, value)

        monkeypatch.setattr(r, "new_json", interrupted)
    checked = p.verify_gate(tmp_path)
    saved = r.case_artifacts, r._proofs, r._unchanged, r._leases, c._unchanged
    with p.session(tmp_path, checked) as proof:
        with pytest.raises((ValueError, SystemExit, KeyboardInterrupt, OSError)):
            c.run(tmp_path, max_cases=4)
        assert jobs[6]["id"] not in proof.accepted
        assert current(tmp_path)["calls_charged"] == 7
        assert current(tmp_path)["status"] == "sensitivity_needs_review"
        assert len(calls) == 7
    assert (r.case_artifacts, r._proofs, r._unchanged, r._leases, c._unchanged) == saved
    assert not proof.pending and not proof.accepted


@pytest.mark.parametrize("when", ["initial", "after_pause"])
def test_valid_foreign_advance_is_never_adopted_as_owned_checkpoint(tmp_path, monkeypatch, when):
    _, calls, _, _ = fixture(tmp_path, monkeypatch)
    original_verify, original_leases = c.verify_continuation, r._leases
    checks, acknowledged, advanced = [], [], []

    def raced(root):
        admitted = original_verify(root)
        checks.append(1)
        trigger = len(checks) == 2 if when == "initial" else bool(acknowledged)
        if trigger and not advanced:
            advanced.append(1)
            # A real valid old-controller call represents a separate foreground process.
            with monkeypatch.context() as foreign:
                foreign.setattr(r, "_leases", original_leases)
                c.run(root, max_cases=1)
        return admitted

    def ack(prompt):
        acknowledged.append(1)
        return "ACK"

    monkeypatch.setattr(c, "verify_continuation", raced)
    monkeypatch.setattr("builtins.input", ack)
    saved = r.case_artifacts, r._leases, c.parallel_proofs, c._unchanged
    with pytest.raises(ValueError, match="foreign STATE"):
        p.run(
            tmp_path,
            invocations=1 if when == "initial" else 2,
            pause_between_batches=when == "after_pause",
        )
    expected = 7 if when == "initial" else 11
    assert len(calls) == current(tmp_path)["next_case"] == expected
    assert (r.case_artifacts, r._leases, c.parallel_proofs, c._unchanged) == saved
    assert len(list((tmp_path / p.CONTROL / "sessions").glob("*/before.json"))) == (
        0 if when == "initial" else 1
    )


def test_final_failure_preserves_foreign_precharge_bytes_and_only_signals_STOP(
    tmp_path, monkeypatch
):
    fixture(tmp_path, monkeypatch)
    original = p.ProofCache.runtime
    foreign_bytes = []

    def late(self):
        if list((tmp_path / p.CONTROL / "sessions").glob("*/after.json")) and not foreign_bytes:
            foreign = current(tmp_path)
            foreign.update(
                current="foreign-precharge",
                status="sensitivity_running",
                calls_charged=foreign["calls_charged"] + 1,
            )
            write_json(tmp_path / r.STATE, foreign)
            foreign_bytes.append((tmp_path / r.STATE).read_bytes())
            raise ValueError("late quota with foreign precharge")
        return original(self)

    monkeypatch.setattr(p.ProofCache, "runtime", late)
    with pytest.raises(ValueError, match="foreign precharge"):
        p.run(tmp_path)
    assert (tmp_path / r.STATE).read_bytes() == foreign_bytes[0]
    failure = next((tmp_path / p.CONTROL / "sessions").glob("*/failure.json"))
    record = json.loads(failure.read_text())
    assert (
        record["canonical_state_marked"] is False and "foreign STATE" in record["ownership_error"]
    )
    assert (tmp_path / r.OUTPUT / "STOP").is_file()
    assert not (tmp_path / r.OUTPUT / ".controller.lock").exists()
    assert not (tmp_path / r.OLD_OUTPUT / ".controller.lock").exists()


def test_normal_inner_return_needs_review_stops_without_ACK_or_another_child(tmp_path, monkeypatch):
    _, calls, _, _ = fixture(tmp_path, monkeypatch)
    original = c.run
    failed_bytes = []

    def diagnostic_failure(root, *, max_cases):
        original(root, max_cases=1)
        failed = current(root)
        failed["status"] = "sensitivity_needs_review"
        write_json(root / r.STATE, failed)
        failed_bytes.append((root / r.STATE).read_bytes())

    monkeypatch.setattr(c, "run", diagnostic_failure)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("ACK after failed normal return"))
    saved = r.case_artifacts, c.parallel_proofs, c._unchanged, r._leases
    with pytest.raises(ValueError):
        p.run(tmp_path, invocations=2, pause_between_batches=True)
    assert len(calls) == 7 and (tmp_path / r.STATE).read_bytes() == failed_bytes[0]
    assert (r.case_artifacts, c.parallel_proofs, c._unchanged, r._leases) == saved
    after = next((tmp_path / p.CONTROL / "sessions").glob("*/after.json"))
    assert json.loads(after.read_text())["exception"] is not None
