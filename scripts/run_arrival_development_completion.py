"""Explicit continuation after a retained zero-call development-check failure.

Old state/results never change. A separately reviewed case0 disposition precedes
five unchanged check jobs; reviewed check/G receipts precede the six smokes/three
full fits. This coordinator grants no statistical retuning or automatic retries.
"""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_arrival_development as old  # noqa: E402

SELF = "scripts/run_arrival_development_completion.py"
TEST = "tests/test_run_arrival_development_completion.py"
STATE = "context/runs/arrival-model-fitting-v1/development-completion-state.json"
CONTROL = old.CONTROL + "/completion-v1"
DESIGN = str(Path(old.fit.GATE).parent) + "/completion-v1"
PILOT = CONTROL + "/sampler-pilot-review-acceptance.json"
NUMERICAL_OUTPUT = old.fit.data.ART + "development-score-resolution-v1"
EXTRA_ROOTS = (
    NUMERICAL_OUTPUT,
    old.fit.data.ART + "development-numerical-resolution-design-v1",
    old.fit.data.ART + "development-check-diagnostics-v1",
)
CASE0_STATUS = "accepted_frozen_development_case0_resolution"
SUCCESS = "computed_pending_review"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def gate_path(phase):
    require(phase in old.PHASES, "one frozen phase required")
    return DESIGN + "/" + phase + "/review-acceptance.json"


def bindings(root):
    return {
        **old.bindings(root),
        "state": str(root / STATE),
        "control": CONTROL,
        "original_state": str(root / old.STATE),
    }


def load(root, name):
    return json.loads(old.previous._path(root, name).read_text())


def merge(*values):
    return old._merge(*values)


def baseline(root, gate, pins):
    """Read public frozen history, hash but never repair the old private state."""
    registry = load(root, gate["baseline_registry"])
    snapshot = load(root, gate["baseline_state"])
    require(
        pins[gate["baseline_registry"]] == gate["baseline_registry_sha256"]
        and pins[gate["baseline_state"]] == gate["baseline_state_sha256"]
        and gate["original_state_sha256"] == old.sha256(root / old.STATE),
        "original failed state must stay byte-identical",
    )
    old.previous._require(pins, registry["files"])
    require(
        set(snapshot)
        == {
            "schema_version",
            "status",
            "original_state_sha256",
            "calls_charged",
            "calls_started",
            "original_job",
            "failed_attempt",
            "source_references",
        }
        and snapshot["schema_version"] == 1
        and snapshot["status"] == "frozen_failed_development_check_history"
        and snapshot["original_state_sha256"]
        == registry["original_state_sha256"]
        == gate["original_state_sha256"]
        and snapshot["calls_charged"] == snapshot["calls_started"] == 0,
        "explicit public zero-call scientific run-history projection required",
    )
    old.previous._require(pins, snapshot["source_references"])
    attempt = snapshot["failed_attempt"]
    require(
        attempt == registry["failed_attempt"]
        and attempt["outcome"] != "accepted"
        and attempt["cost"] == attempt["start_markers"] == 0
        and attempt["job_id"] == snapshot["original_job"]["id"],
        "original failed immutable attempt must remain retained",
    )
    old.previous._require(pins, {attempt["receipt"]: attempt["receipt_sha256"]})
    body = load(root, attempt["receipt"])
    require(
        body == {k: v for k, v in attempt.items() if k != "receipt_sha256"},
        "original immutable attempt contents required",
    )
    released = registry["released_ephemeral_files"]
    lease = old.CONTROL + "/.controller.lock"
    require(
        set(released) == {lease}
        and released[lease]
        == {"sha256": attempt["files"][lease], "disposition": "released_exclusive_lease"}
        and lease not in pins
        and not (root / lease).exists()
        and not (root / lease).is_symlink(),
        "released historical lease is not a persistent proof",
    )
    old.previous._require(pins, {p: h for p, h in attempt["files"].items() if p != lease})
    return registry


def snapshot_job(root, gate):
    return load(root, gate["baseline_state"])["original_job"]


def admit(root, phase):
    name = gate_path(phase)
    gate = load(root, name)
    require(
        gate.get("status") == "accepted_frozen_arrival_development_completion_execution"
        and gate.get("independent_checker") is True
        and gate.get("phase") == phase
        and gate.get("path_bindings") == bindings(root)
        and gate.get("resources") == old.fit.resources()
        and gate.get("max_sampler_call_slots") == 9
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("no_retuning") is True,
        "exact bounded continuation authority required",
    )
    pins = merge(gate["files"], {name: old.sha256(root / name)})
    require(
        {
            SELF,
            TEST,
            old.SELF,
            old.TEST,
            old.fit.data.FREEZE,
            gate["baseline_state"],
            gate["baseline_registry"],
            gate["case0_review"],
        }
        <= set(pins)
        and STATE not in pins
        and old.STATE not in pins,
        "complete source/public baseline closure; no private state pins",
    )
    old.previous._unchanged(root, pins)
    registry = baseline(root, gate, pins)
    require(gate["worker_gate"] == old.phase_gate(phase), "literal old worker Gate required")
    old.previous._require(pins, {gate["worker_gate"]: gate["worker_gate_sha256"]})
    kernel_metadata = load(root, gate["worker_gate"])
    old.previous._require(pins, kernel_metadata["files"])
    old.previous._unchanged(root, pins)
    worker = old.consumer(phase)
    kernel = (
        worker.verify_gate(root)
        if phase == "full_design_recovery"
        else worker.verify_gate(root, "check_training" if phase == "check" else "full_development")
    )
    old.previous._require(pins, kernel["files"])
    require(
        gate["worker_gate"] == old.phase_gate(phase)
        and gate["worker_gate_sha256"] == pins[gate["worker_gate"]],
        "unchanged worker kernel Gate and separate execution authority required",
    )
    original = load(root, old.fit.GATE)
    require(
        len(original["jobs"]) == 6
        and all(
            j["role"] == "check_evaluate" and j["training_reference"] == {"kind": "historical"}
            for j in original["jobs"]
        ),
        "original six zero-call frozen check jobs required",
    )
    case0 = load(root, gate["case0_review"])
    outcome = case0.get("case0_outcome")
    require(
        case0.get("status") == CASE0_STATUS
        and case0.get("independent_checker") is True
        and outcome in {"accepted_resolution", "accepted_unresolved_gap"}
        and case0.get("original_job") == original["jobs"][0]
        and case0.get("original_state_sha256") == gate["original_state_sha256"]
        and case0.get("specification_freeze_sha256") == pins[old.fit.data.FREEZE]
        and case0.get("primary_aggregate_available") is (outcome == "accepted_resolution")
        and (
            isinstance(case0.get("resolved_result"), str)
            if outcome == "accepted_resolution"
            else case0.get("resolved_result") is None
        ),
        "independently typed case0 disposition required",
    )
    require(snapshot_job(root, gate) == original["jobs"][0], "baseline original job0 required")
    old.previous._require(pins, case0["files"])
    old.previous._require(case0["files"], registry["files"])
    prediction = str(
        Path(old.fit.CHECK_OUTPUT)
        / "jobs"
        / original["jobs"][0]["id"]
        / "held-out-record-predictions.csv"
    )
    require(
        case0.get("prediction_file") == prediction
        and case0.get("prediction_sha256") == pins.get(prediction),
        "original unchanged151 prediction pointer required",
    )
    if outcome == "accepted_resolution":
        old.previous._require(pins, {case0["resolved_result"]: case0["resolved_result_sha256"]})
    expected_calls = 6 if phase == "full_development" else 0
    require(
        gate.get("inherited_calls") == {"charged": expected_calls, "started": expected_calls},
        "exact cumulative inherited sampler counters required",
    )
    jobs = original["jobs"][1:] if phase == "check" else kernel["gate"]["jobs"]
    require(
        gate["jobs"] == jobs
        and len(jobs) == {"check": 5, "full_design_recovery": 6, "full_development": 3}[phase],
        "exact remaining5/smoke6/selected3 jobs required",
    )
    if phase != "check":
        for review_name, status in [
            (old.fit.data.CHECK_REVIEW, "accepted_frozen_arrival_development_check")
        ]:
            old.previous._require(pins, {review_name: old.sha256(root / review_name)})
            review = load(root, review_name)
            require(
                review.get("status") == status
                and review.get("independent_checker") is True
                and review.get("completed_once") is True
                and review.get("no_retuning") is True
                and review.get("specification_freeze_sha256") == pins[old.fit.data.FREEZE]
                and review.get("case0_review") == gate["case0_review"]
                and review.get("case0_review_sha256") == pins[gate["case0_review"]],
                "reviewed six check dispositions required before G/full",
            )
            old.previous._require(pins, review["files"])
    if phase == "full_development":
        old.previous._require(pins, {old.RECOVERY_REVIEW: old.sha256(root / old.RECOVERY_REVIEW)})
        review = load(root, old.RECOVERY_REVIEW)
        require(
            review.get("status") == "accepted_frozen_full_development_design_checks"
            and review.get("independent_checker") is True
            and review.get("specification_freeze_sha256") == pins[old.fit.data.FREEZE],
            "independent G6 review required before full selected fits",
        )
        old.previous._require(pins, review["files"])
    require(
        set(gate["external_reference_files"]) == set(old.external_paths(root, kernel["freeze"])),
        "exact outside-reference inventory required",
    )
    old.previous._require(pins, gate["external_reference_files"])
    old.r.parent_floors(root, gate)
    return dict(
        gate=gate,
        files=pins,
        kernel=kernel,
        worker=worker,
        phase=phase,
        case0=case0,
        registry=registry,
    )


def stop_paths(root):
    return [
        root / p
        for p in [
            old.r.OLD_OUTPUT + "/STOP",
            old.r.OUTPUT + "/STOP",
            old.CONTROL + "/STOP",
            CONTROL + "/STOP",
        ]
    ]


def safe(root, admission, current=None, reserve=False, known_files=None):
    old.previous._unchanged(root, merge(admission["files"], known_files or {}))
    require(
        old.sha256(root / old.STATE) == admission["gate"]["original_state_sha256"],
        "foreign change of retained original state",
    )
    require(not any(p.exists() or p.is_symlink() for p in stop_paths(root)), "STOP present")
    reason = quota(root, admission, current, reserve=reserve, known_files=known_files)
    require(reason is None, "storage/floor failure: " + str(reason))


def extra_inventory(root, pins):
    """All numerical histories/SCI are closed, including unsuccessful outputs."""
    for name in EXTRA_ROOTS:
        base = root / name
        if not base.exists() and not base.is_symlink():
            continue
        require(base.resolve() == base and base.is_dir(), "literal numerical root required")
        for path in [base, *base.rglob("*")]:
            require(
                path.resolve() == path and (path.is_file() or path.is_dir()),
                "symlink/special numerical artifact",
            )
            if path.is_file():
                require(path.stat().st_size <= old.r.FILE_MAX, "numerical file cap")
                require(str(path.relative_to(root)) in pins, "unknown numerical file")
            else:
                require(
                    any(path in (root / p).parents for p in pins),
                    "unknown/empty numerical directory",
                )


def outside_roots(root, counted):
    extras = []
    for name in EXTRA_ROOTS:
        candidate = root / name
        if any(p == candidate or p in candidate.parents for p in [*counted, *extras]):
            continue
        require(
            not any(candidate in p.parents for p in counted),
            "unexpected partially overlapping numerical budget roots",
        )
        extras.append(candidate)
    return extras


def quota(root, admission, current=None, *, reserve=False, known_files=None):
    reason = old.quota(root, admission, current, reserve=reserve)
    if reason:
        return reason
    try:
        known = merge(admission["files"], known_files or {})
        extra_inventory(root, known)
        parents = old.r.parent_roots(root)
        counted = old.previous.counted_roots(root, parents) + old.global_roots(root)
        global_extra = old.r.byte_count(*outside_roots(root, counted))
        local_extra = old.r.byte_count(*outside_roots(root, old.roots(root)))
        external = sum(
            (root / p).stat().st_size for p in admission["gate"]["external_reference_files"]
        )
        reserve_bytes = old.r.RESERVE if reserve else 0
        if (
            old.r.working_bytes(root, parents)
            + old.r.byte_count(*old.global_roots(root))
            + external
            + global_extra
            + reserve_bytes
            > 3072 * old.r.MIB
        ):
            return "numerical_global_storage"
        if old.r.byte_count(*old.roots(root)) + local_extra + reserve_bytes > 2048 * old.r.MIB:
            return "numerical_local_storage"
        case = root / NUMERICAL_OUTPUT / "case-000"
        if old.r.byte_count(case) > old.r.MAX_JOB:
            return "numerical_case_job_cap"
    except (ValueError, OSError):
        return "numerical_inventory_or_storage_failure"
    if current:
        folder, raw, spec, log, process = current
        evidence = attempt_path(root, admission["phase"], {"id": folder.name})
        try:
            size = old.r.byte_count(folder) + sum(
                p.stat().st_size
                for p in [raw, spec, log, process, evidence, evidence.with_suffix(".failure.json")]
                if p is not None and p.is_file()
            )
            if size > old.r.MAX_JOB:
                return "combined_new_attempt_job_cap"
        except OSError:
            return "job_storage_scan_failure"
    return None


def attempt_path(root, phase, job):
    return root / CONTROL / "attempts" / phase / (job["id"] + ".json")


def plan_path(root, phase):
    return root / CONTROL / (phase + "-plan.json")


def inventory(root, admission, state, current=None):
    known = set(admission["files"])
    for entry in state["phases"].values():
        known.add(entry["plan"])
        if "summary" in entry:
            known.add(entry["summary"])
        for record in entry["attempts"]:
            known.update(record["files"])
            known.add(record["receipt"])
            if record.get("failure"):
                known.add(record["failure"])
    known.add(CONTROL + "/.controller.lock")
    if (root / PILOT).is_file():
        known.add(PILOT)  # Bytes are separately bound by pilot() before a third actual start.
    if current:
        folder, raw, spec, log, process = current
        known.update(str(p.relative_to(root)) for p in [raw, spec, log, process] if p is not None)
        known.update(str(p.relative_to(root)) for p in folder.rglob("*") if p.is_file())
    extra_inventory(root, admission["files"])
    for base in old.roots(root):
        for path in base.rglob("*"):
            require(
                path.resolve() == path and (path.is_file() or path.is_dir()),
                "symlink/special runtime artifact",
            )
            if any(
                root / s / "cache" == path or root / s / "cache" in path.parents
                for s in [old.fit.STORE, old.RECOVERY_STORE]
            ):
                continue
            name = str(path.relative_to(root))
            require(
                (name in known)
                if path.is_file()
                else any(path in (root / p).parents for p in known),
                "unknown or missing runtime inventory entry: " + name,
            )


def summary_value(state, phase, admission, entry):
    prior = old.PHASES[: old.PHASES.index(phase) + 1]
    attempts = [a for p in prior for a in state["phases"].get(p, {}).get("attempts", [])]
    return dict(
        phase=phase,
        status="computed_pending_independent_review",
        calls_charged=sum(a["cost"] for a in attempts),
        calls_started=sum(a["start_markers"] for a in attempts),
        case0_outcome=admission["case0"]["case0_outcome"],
        plan_sha256=entry["plan_sha256"],
        specification_freeze_sha256=state["specification_freeze_sha256"],
        accepted_records=entry["accepted"],
        jobs=admission["gate"]["jobs"],
        authority_gate=gate_path(phase),
        authority_gate_sha256=admission["files"][gate_path(phase)],
        worker_gate=old.phase_gate(phase),
        worker_gate_sha256=admission["files"][old.phase_gate(phase)],
    )


def validate(state):
    require(
        state.get("schema_version") == 1
        and state.get("current") is None
        and state.get("status") != "needs_review",
        "idle conserved continuation only; no repair/resume",
    )
    attempts = [a for entry in state["phases"].values() for a in entry["attempts"]]
    require(
        type(state["calls_charged"]) is int
        and type(state["calls_started"]) is int
        and state["calls_charged"] == sum(a["cost"] for a in attempts)
        and state["calls_started"] == sum(a["start_markers"] for a in attempts)
        and 0 <= state["calls_started"] <= state["calls_charged"] <= 9,
        "all actual sampler charges/starts must be conserved",
    )
    require(
        state["sampler_pilot_job_ids"]
        == [a["phase"] + ":" + a["job_id"] for a in attempts if a["start_markers"]][:2],
        "actual first-two pilots required",
    )
    for entry in state["phases"].values():
        require(
            entry["next_job"] == len(entry["accepted"]) == len(entry["attempts"]),
            "complete successful prefix required; no skip/retry",
        )


class Proofs:
    """One-invocation scientific proof memo; every reuse hashes complete bytes."""

    def __init__(self):
        self.cache = {}

    def case(self, root, admission, job, record=None):
        key = (admission["phase"], job["id"])
        worker = admission["worker"]
        if key not in self.cache:
            value = worker.case_artifacts(root, job, admission["kernel"]["files"])
            self.cache[key] = (
                job.copy(),
                admission["kernel"]["files"].copy(),
                value["files"].copy(),
            )
        saved_job, source, worker_files = self.cache[key]
        require(
            saved_job == job and source == admission["kernel"]["files"],
            "memo source/job identity changed",
        )
        old.previous._unchanged(root, merge(admission["files"], worker_files))
        folder, raw, spec, log, process = old.paths(root, job, worker)
        receipt = load(root, str(process.relative_to(root)))
        entry_plan = CONTROL + "/" + admission["phase"] + "-plan.json"
        require(
            receipt.get("returncode") == 0
            and receipt.get("reason") == "worker_exit"
            and receipt.get("cost") == receipt.get("start_markers") == old.cost(job)
            and receipt.get("job_sha256") == old.sha256(spec)
            and receipt.get("plan_sha256") == old.sha256(root / entry_plan)
            and receipt.get("authority_gate_sha256")
            == admission["files"][gate_path(admission["phase"])]
            and receipt.get("worker_gate_sha256")
            == admission["files"][old.phase_gate(admission["phase"])]
            and receipt.get("monitor_failures") == []
            and load(root, str(spec.relative_to(root))) == job,
            "complete dual-authority successful process proof required",
        )
        files = merge(
            worker_files, {str(p.relative_to(root)): old.sha256(p) for p in [spec, log, process]}
        )
        old.case_inventory(root, job, worker, files, admission["gate"]["jobs"])
        if record:
            require(
                record["files"] == files and record["worker_files"] == worker_files,
                "immutable case proof changed",
            )
        return worker_files, files

    def prefix(self, root, state, scope=None):
        for phase, entry in state["phases"].items():
            admission = admit(root, phase)
            require(old.sha256(root / entry["plan"]) == entry["plan_sha256"], "phase plan changed")
            plan = load(root, entry["plan"])
            require(
                plan
                == {
                    "phase": phase,
                    "gate": gate_path(phase),
                    "files": admission["files"],
                    "jobs": admission["gate"]["jobs"],
                },
                "phase admission identity changed",
            )
            require(
                entry["next_job"] <= len(admission["gate"]["jobs"]),
                "phase cursor cannot exceed exact jobs",
            )
            if entry["status"] == SUCCESS:
                require(
                    entry["next_job"] == len(admission["gate"]["jobs"]) and "summary" in entry,
                    "completed phase must retain every original job disposition",
                )
            if "summary" in entry:
                require(
                    old.sha256(root / entry["summary"]) == entry["summary_sha256"]
                    and load(root, entry["summary"])
                    == summary_value(state, phase, admission, entry),
                    "immutable completed phase summary changed",
                )
            for index, record in enumerate(entry["accepted"]):
                job = admission["gate"]["jobs"][index]
                require(
                    record["job_id"] == job["id"]
                    and record == entry["attempts"][index]
                    and record["outcome"] == "accepted"
                    and record["cost"] == record["start_markers"] == old.cost(job)
                    and old.sha256(root / record["receipt"]) == record["receipt_sha256"]
                    and load(root, record["receipt"])
                    == {k: v for k, v in record.items() if k != "receipt_sha256"},
                    "accepted immutable attempt identity required",
                )
                self.case(root, admission, job, record)
                safe(
                    root,
                    admission,
                    old.paths(root, job, admission["worker"]),
                    known_files=None if scope is None else scope["files"],
                )


def pilot(root, state, admission):
    if state["calls_started"] < 2:
        return True
    if not (root / PILOT).is_file():
        return False
    review = load(root, PILOT)
    require(
        review.get("status") == "accepted_development_two_sampler_runtime_pilots"
        and review.get("independent_checker") is True
        and review.get("sampler_pilot_job_ids") == state["sampler_pilot_job_ids"]
        and review.get("specification_freeze_sha256") == admission["files"][old.fit.data.FREEZE],
        "independent actual-two-start pilot required",
    )
    needed = {
        p: h
        for e in state["phases"].values()
        for a in e["accepted"]
        if a["phase"] + ":" + a["job_id"] in state["sampler_pilot_job_ids"]
        for p, h in {**a["files"], a["receipt"]: a["receipt_sha256"]}.items()
    }
    old.previous._require(review["files"], needed)
    old.previous._unchanged(root, review["files"])
    require(
        state.get("pilot_review_sha256") in {None, old.sha256(root / PILOT)},
        "pilot identity changed",
    )
    state["pilot_review_sha256"] = old.sha256(root / PILOT)
    return True


@contextmanager
def leases(root, pins):
    with old.r._leases(root):
        old.previous._unchanged(root, pins)
        path = root / CONTROL / ".controller.lock"
        old.new_json(path, {"pid": os.getpid()})
        try:
            yield
        finally:
            path.unlink()


def owned(path, expected):
    with expected[1]:
        require(
            (path.read_bytes() if path.exists() else None) == expected[0],
            "foreign continuation state change",
        )


def save(path, state, expected):
    with expected[1]:
        owned(path, expected)
        old.atomic_state(path, state)
        expected[0] = path.read_bytes()


def run(root, *, phase="check", resume=False, max_jobs=1):
    require(type(max_jobs) is int and 1 <= max_jobs <= 4, "one to four fixed jobs only")
    root = root.resolve()
    admission = admit(root, phase)
    path = root / STATE
    snapshot = path.read_bytes() if path.exists() else None
    require(resume == (snapshot is not None), "explicit once-only state/resume required")
    state: dict[str, Any] = (
        json.loads(snapshot)
        if snapshot is not None
        else dict(
            schema_version=1,
            original_state_sha256=admission["gate"]["original_state_sha256"],
            baseline_registry_sha256=admission["gate"]["baseline_registry_sha256"],
            specification_freeze_sha256=admission["files"][old.fit.data.FREEZE],
            calls_charged=0,
            calls_started=0,
            sampler_pilot_job_ids=[],
            pilot_review_sha256=None,
            status="checkpoint",
            current=None,
            phases={},
        )
    )
    expected = [snapshot, threading.RLock()]
    validate(state)
    require(
        state["original_state_sha256"] == admission["gate"]["original_state_sha256"]
        and state["baseline_registry_sha256"] == admission["gate"]["baseline_registry_sha256"]
        and state["specification_freeze_sha256"] == admission["files"][old.fit.data.FREEZE],
        "original history/freeze binding cannot change",
    )
    previous_phase = old.PHASES[old.PHASES.index(phase) - 1] if phase != "check" else None
    if previous_phase:
        require(
            state["phases"].get(previous_phase, {}).get("status") == SUCCESS,
            "previous phase must complete before transition",
        )
    if previous_phase:
        previous_entry = state["phases"][previous_phase]
        require(
            "summary" in previous_entry
            and previous_entry["next_job"]
            == {"check": 5, "full_design_recovery": 6}[previous_phase],
            "completed phase must retain every original job disposition",
        )
        review_name = (
            old.fit.data.CHECK_REVIEW if previous_phase == "check" else old.RECOVERY_REVIEW
        )
        review = load(root, review_name)
        needed = {
            previous_entry["plan"]: previous_entry["plan_sha256"],
            previous_entry["summary"]: previous_entry["summary_sha256"],
        }
        for record in previous_entry["accepted"]:
            needed = merge(needed, record["files"], {record["receipt"]: record["receipt_sha256"]})
        old.previous._require(review["files"], needed)
    proofs = Proofs()
    proofs.prefix(root, state, admission)
    inventory(root, admission, state)
    safe(root, admission, reserve=True)
    with leases(root, admission["files"]):
        require(
            (path.read_bytes() if path.exists() else None) == snapshot,
            "foreign state changed before lease",
        )
        proofs.prefix(root, state, admission)
        safe(root, admission, reserve=True)
        inventory(root, admission, state)
        entry: Any = state["phases"].get(phase)
        if entry and entry["status"] == SUCCESS:
            return state  # Strictly read-only terminal revisit.
        require(not entry or entry["status"] not in {"needs_review"}, "failed phase cannot resume")
        if entry is None:
            require(
                admission["gate"]["inherited_calls"]
                == {"charged": state["calls_charged"], "started": state["calls_started"]},
                "new phase cannot reset or refund inherited counters",
            )
            plan = CONTROL + "/" + phase + "-plan.json"
            old.new_json(
                root / plan,
                {
                    "phase": phase,
                    "gate": gate_path(phase),
                    "files": admission["files"],
                    "jobs": admission["gate"]["jobs"],
                },
            )
            entry = dict(
                plan=plan,
                plan_sha256=old.sha256(root / plan),
                next_job=0,
                accepted=[],
                attempts=[],
                status="checkpoint",
            )
            state["phases"][phase] = entry
            save(path, state, expected)
        ended, failures = threading.Event(), []
        current: list[Any] = [None]

        def monitor():
            while not ended.wait(0.1):
                reason = quota(root, admission, current[0])
                with expected[1]:
                    if (path.read_bytes() if path.exists() else None) != expected[0]:
                        reason = reason or "foreign_STATE"
                if any(p.exists() or p.is_symlink() for p in stop_paths(root)):
                    reason = reason or "STOP"
                if reason:
                    failures.append(reason)
                    try:
                        (root / CONTROL / "STOP").open("x").write(reason)
                    except FileExistsError:
                        pass
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            for _ in range(min(max_jobs, len(admission["gate"]["jobs"]) - entry["next_job"])):
                if not pilot(root, state, admission):
                    state["status"] = entry["status"] = "awaiting_sampler_pilot_review"
                    break
                owned(path, expected)
                proofs.prefix(root, state, admission)
                inventory(root, admission, state)
                safe(root, admission, reserve=True)
                job = admission["gate"]["jobs"][entry["next_job"]]
                cost = old.cost(job)
                require(state["calls_charged"] + cost <= 9, "cumulative nine-call ceiling")
                job_paths = old.paths(root, job, admission["worker"])
                folder, raw, spec, log, process = job_paths
                require(
                    all(
                        p is None or (not p.exists() and not p.is_symlink() and p.resolve() == p)
                        for p in job_paths
                    ),
                    "new job paths only; no overwrite or retry",
                )
                old.new_json(spec, job)
                state["current"] = {"phase": phase, "job_id": job["id"], "cost": cost}
                state["calls_charged"] += cost
                save(path, state, expected)
                current[0] = job_paths
                receipt = {}
                try:
                    owned(path, expected)
                    safe(root, admission, job_paths)
                    command = [
                        sys.executable,
                        str(
                            root
                            / (
                                old.RECOVERY_CLI
                                if phase == "full_design_recovery"
                                else "scripts/fit_arrival_development.py"
                            )
                        ),
                        "--job",
                        str(spec),
                        "--output",
                        str(folder),
                        "--max-output-bytes",
                        str(old.r.FILE_MAX),
                    ]
                    if raw is not None:
                        command.extend(["--store", str(raw)])
                    receipt = old.supervise(command, log, root / CONTROL / "STOP", 600)
                except BaseException as error:
                    receipt = {
                        "returncode": 130 if isinstance(error, KeyboardInterrupt) else None,
                        "reason": "supervisor_failure",
                        "error": str(error),
                    }
                markers = list(folder.glob("sampling-start*.json"))
                state["calls_started"] += len(markers)
                if markers and len(state["sampler_pilot_job_ids"]) < 2:
                    state["sampler_pilot_job_ids"].append(phase + ":" + job["id"])
                old.new_json(
                    process,
                    {
                        **receipt,
                        "cost": cost,
                        "start_markers": len(markers),
                        "job_sha256": old.sha256(spec),
                        "plan_sha256": entry["plan_sha256"],
                        "authority_gate_sha256": admission["files"][gate_path(phase)],
                        "worker_gate_sha256": admission["files"][old.phase_gate(phase)],
                        "invocation_git_sha": old.git_sha(root),
                        "monitor_failures": list(failures),
                    },
                )
                record = dict(
                    phase=phase,
                    job_id=job["id"],
                    role=job["role"],
                    cost=cost,
                    start_markers=len(markers),
                    outcome="needs_review",
                    files={},
                    worker_files={},
                    receipt=str(attempt_path(root, phase, job).relative_to(root)),
                )
                try:
                    require(
                        len(markers) == cost
                        and (not markers or load(root, str(markers[0].relative_to(root))) == job),
                        "literal role-specific original job start marker required",
                    )
                    record["worker_files"], record["files"] = proofs.case(root, admission, job)
                    safe(root, admission, job_paths)
                    inventory(root, admission, state, job_paths)
                    require(not failures, "runtime monitor failure")
                    record["outcome"] = "accepted"
                except Exception:
                    record["files"] = {
                        str(p.relative_to(root)): old.sha256(p)
                        for base in [
                            folder,
                            *[q for q in [raw, spec, log, process] if q is not None],
                        ]
                        for p in ([base] if base.is_file() else base.rglob("*"))
                        if p.is_file() and not p.is_symlink()
                    }
                old.new_json(root / record["receipt"], record)
                record["receipt_sha256"] = old.sha256(root / record["receipt"])
                entry["attempts"].append(record)
                require(
                    record["outcome"] == "accepted", "failed computation retained; no resume/retry"
                )
                entry["accepted"].append(record)
                entry["next_job"] += 1
                state["current"], current[0] = None, None
                state["status"] = entry["status"] = "checkpoint"
                save(path, state, expected)
                safe(root, admission, job_paths)
                proofs.prefix(root, state, admission)
                inventory(root, admission, state)
            if entry["next_job"] == len(admission["gate"]["jobs"]):
                summary = CONTROL + "/" + phase + "-summary.json"
                old.new_json(
                    root / summary,
                    summary_value(state, phase, admission, entry),
                )
                entry.update(
                    status=SUCCESS, summary=summary, summary_sha256=old.sha256(root / summary)
                )
            validate(state)
            proofs.prefix(root, state, admission)
            inventory(root, admission, state)
            safe(root, admission)
            owned(path, expected)
            save(path, state, expected)
            proofs.prefix(root, state, admission)
            inventory(root, admission, state)
            safe(root, admission)
        except BaseException:
            state["status"] = entry["status"] = "needs_review"
            if (path.read_bytes() if path.exists() else None) == expected[0]:
                save(path, state, expected)
            raise
        finally:
            ended.set()
            watcher.join(timeout=2)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=old.PHASES, default="check")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=1)
    args = parser.parse_args()
    run(args.root, phase=args.phase, resume=args.resume, max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()
