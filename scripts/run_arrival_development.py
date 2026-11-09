"""Finite three-phase development execution; Gates authorize every job and call."""

# pyright: basic
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_development_fit as fit  # noqa: E402
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivity_continuation as previous  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

r = previous.r
SELF, TEST = "scripts/run_arrival_development.py", "tests/test_run_arrival_development.py"
STATE = "context/runs/arrival-model-fitting-v1/development-state.json"
CONTROL = fit.CHECK_OUTPUT + "/controller"
PHASES = ("check", "full_design_recovery", "full_development")
RECOVERY_OUTPUT = fit.data.ART + "full-development-recovery-v1"
RECOVERY_STORE = "data/processed/models/arrival-development-recovery-v1"
SENSITIVITY_REPAIR_STORE = "data/processed/models/arrival-sensitivity-repair-v1"
SENSITIVITY_NUMERICAL_STORE = "data/processed/models/arrival-sensitivity-numerical-protocol-v2"
RECOVERY_GATE = fit.data.ART + "full-development-recovery-design-v1/review-acceptance.json"
RECOVERY_REVIEW = RECOVERY_OUTPUT + "/review-acceptance.json"
RECOVERY_SOURCE = "analysis/arrival/model_development_recovery.py"
RECOVERY_CLI = "scripts/check_arrival_development_recovery.py"
PILOT_REVIEW = CONTROL + "/sampler-pilot-review-acceptance.json"
OUTER_CEILING = 97  # An upper source guard; only a prospective Gate authorizes an allocation.


def bindings(root):
    return {
        "project_root": str(root.resolve()),
        "state": str(root.resolve() / STATE),
        "control": CONTROL,
        "check_output": fit.CHECK_OUTPUT,
        "full_output": fit.FULL_OUTPUT,
        "recovery_output": RECOVERY_OUTPUT,
        "store": fit.STORE,
        "recovery_store": RECOVERY_STORE,
    }


def phase_gate(phase):
    return (
        fit.GATE
        if phase == "check"
        else RECOVERY_GATE
        if phase == "full_design_recovery"
        else fit.FULL_GATE
    )


def cost(job):
    if job["role"] not in {
        "check_training",
        "check_evaluate",
        "full_design_recovery",
        "full_development",
    }:
        raise ValueError("only four fixed roles; augmentation/repair is disabled")
    return int(job["role"] != "check_evaluate")


def consumer(phase) -> Any:
    if phase == "full_design_recovery":
        return importlib.import_module("analysis.arrival.model_development_recovery")
    return fit


def new_json(path, value):
    if path.resolve() != path:
        raise ValueError("literal nonsymlink output required")
    r.new_json(path, value)


def _merge(*maps):
    merged = {}
    for values in maps:
        if any(p in merged and merged[p] != h for p, h in values.items()):
            raise ValueError("conflicting frozen source identities")
        merged.update(values)
    return merged


def roots(root):
    return [
        root / p
        for p in [
            fit.CHECK_OUTPUT,
            fit.FULL_OUTPUT,
            fit.STORE,
            RECOVERY_OUTPUT,
            RECOVERY_STORE,
            str(Path(fit.GATE).parent),
            str(Path(fit.FULL_GATE).parent),
            str(Path(RECOVERY_GATE).parent),
        ]
    ]


def global_roots(root):
    # Retained MS5 repair bytes belong to the cumulative budget, outside development's local cap.
    return roots(root) + [root / SENSITIVITY_REPAIR_STORE, root / SENSITIVITY_NUMERICAL_STORE]


def external_paths(root, freeze):
    counted = previous.counted_roots(root, r.parent_roots(root)) + global_roots(root)
    names = {ref["raw"] for ref in previous.references.descriptors()}
    names.update(ref["raw"] for ref in freeze.get("training_references", {}).values())
    return sorted(
        p
        for p in names
        if not any(base == root / p or base in (root / p).parents for base in counted)
    )


def admit(root, phase):
    name = phase_gate(phase)
    gate = json.loads(previous._path(root, name).read_text())
    needed = {SELF, TEST, fit.data.FREEZE}
    if phase == "full_design_recovery":
        needed |= {RECOVERY_SOURCE, RECOVERY_CLI}
    if (
        gate.get("status")
        != (
            "accepted_frozen_arrival_development_recovery_execution"
            if phase == "full_design_recovery"
            else "accepted_frozen_arrival_development_execution"
        )
        or gate.get("independent_checker") is not True
        or not needed <= set(gate.get("files", {}))
        or STATE in gate.get("files", {})
        or gate.get("path_bindings") != bindings(root)
        or gate.get("resources") != fit.resources()
        or type(gate.get("max_sampler_call_slots")) is not int
        or not 1 <= gate["max_sampler_call_slots"] <= OUTER_CEILING
    ):
        raise ValueError("exact bounded source/path/resource execution Gate required")
    pins = {**gate["files"], name: sha256(root / name)}
    previous._unchanged(root, pins)  # Before lazy import or any scientific consumer.
    if phase != "check":
        review = json.loads(previous._path(root, fit.data.CHECK_REVIEW).read_text())
        if (
            pins.get(fit.data.CHECK_REVIEW) != sha256(root / fit.data.CHECK_REVIEW)
            or review.get("status") != "accepted_frozen_arrival_development_check"
            or review.get("independent_checker") is not True
            or review.get("completed_once") is not True
            or review.get("no_retuning") is not True
            or review.get("specification_freeze_sha256") != pins[fit.data.FREEZE]
        ):
            raise ValueError("accepted once-only same-freeze development check required")
        previous._require(pins, review.get("files"))
    if phase == "full_development":
        review = json.loads(previous._path(root, RECOVERY_REVIEW).read_text())
        if (
            pins.get(RECOVERY_REVIEW) != sha256(root / RECOVERY_REVIEW)
            or review.get("status") != "accepted_frozen_full_development_design_checks"
            or review.get("independent_checker") is not True
            or review.get("specification_freeze_sha256") != pins[fit.data.FREEZE]
        ):
            raise ValueError("accepted same-freeze full-design recovery required")
        previous._require(pins, review.get("files"))
    worker = consumer(phase)
    admission = (
        worker.verify_gate(root)
        if phase == "full_design_recovery"
        else worker.verify_gate(root, "check_training" if phase == "check" else "full_development")
    )
    if admission["gate"] != gate:
        raise ValueError("identical frozen worker/controller Gate required")
    previous._require(pins, admission["files"])
    external = gate.get("external_reference_files", {})
    if set(external) != set(external_paths(root, admission["freeze"])):
        raise ValueError("exact outside-only declared reference NC closure required")
    previous._require(pins, external)
    r.parent_floors(root, gate)
    jobs = gate["jobs"]
    if phase == "check":
        models = set(admission["specs"])
        evaluated = [j["model_key"] for j in jobs if j["role"] == "check_evaluate"]
        trained = [j["model_key"] for j in jobs if j["role"] == "check_training"]
        if (
            set(evaluated) != models
            or len(evaluated) != len(models)
            or len(set(trained)) != len(trained)
        ):
            raise ValueError(
                "one evaluation per frozen model and no redundant training fits required"
            )
        for job in jobs:
            ref = job["training_reference"]
            if job["role"] == "check_evaluate" and ref["kind"] == "new_fit":
                matches = [
                    p
                    for p in jobs[: job["order"]]
                    if p["id"] == ref["job_id"]
                    and p["role"] == "check_training"
                    and p["model_key"] == job["model_key"]
                ]
                if len(matches) != 1:
                    raise ValueError("new training dependency must precede its evaluation")
        if set(trained) != {
            j["model_key"]
            for j in jobs
            if j["role"] == "check_evaluate" and j["training_reference"]["kind"] == "new_fit"
        }:
            raise ValueError("every training call must serve one declared evaluation")
    elif phase == "full_development":
        selected = {k for k, (_, spec) in admission["specs"].items() if spec["role"] == "selected"}
        if len(jobs) != len(selected) or {j["model_key"] for j in jobs} != selected:
            raise ValueError("exact selected-only full-development jobs required")
    if any(cost(j) != 1 for j in jobs if phase != "check"):
        raise ValueError("recovery/full phases contain only fixed fit jobs")
    previous._unchanged(root, pins)
    return {**admission, "files": pins, "worker": worker, "phase": phase}


def paths(root, job, worker):
    folder, raw = worker.case_paths(root, job)
    return (
        folder,
        raw,
        folder.with_name(folder.name + "-spec.json"),
        folder.with_name(folder.name + ".log"),
        folder.with_name(folder.name + ".supervisor.json"),
    )


def validate_state(state):
    if (
        state.get("schema_version") != 1
        or state.get("current") is not None
        or state.get("status") == "needs_review"
    ):
        raise ValueError("conserved idle successful prefix required; no reset/retry")
    attempts = [
        a for phase in PHASES for a in (state["phases"].get(phase) or {}).get("attempts", [])
    ]
    if (
        type(state["calls_charged"]) is not int
        or type(state["calls_started"]) is not int
        or state["calls_charged"] != sum(a["cost"] for a in attempts)
        or state["calls_started"] != sum(a["start_markers"] for a in attempts)
        or not 0 <= state["calls_started"] <= state["calls_charged"] <= OUTER_CEILING
        or any(a["outcome"] != "accepted" or a["start_markers"] != a["cost"] for a in attempts)
    ):
        raise ValueError("all role-cost charges and actual starts must be conserved")
    pilots = [a["phase"] + ":" + a["job_id"] for a in attempts if a["start_markers"]][:2]
    if state["sampler_pilot_job_ids"] != pilots:
        raise ValueError("first two actual sampler starts must remain the pilots")
    for entry in state["phases"].values():
        if entry is not None and (
            entry["next_job"] != len(entry["accepted"])
            or entry["next_job"] != len(entry["attempts"])
        ):
            raise ValueError("complete conserved job prefix includes zero-call evaluations")


def dependency(root, job, admission, state):
    if job["role"] != "check_evaluate" or job["training_reference"]["kind"] == "historical":
        return {}
    ref = job["training_reference"]
    parents = [
        p
        for p in admission["gate"]["jobs"][: job["order"]]
        if p["id"] == ref["job_id"]
        and p["role"] == "check_training"
        and p["model_key"] == job["model_key"]
    ]
    accepted = [a for a in state["phases"]["check"]["accepted"] if a["job_id"] == ref["job_id"]]
    if len(parents) != 1 or len(accepted) != 1:
        raise ValueError("same prefix-verified accepted training parent required")
    folder, _ = admission["worker"].case_paths(root, parents[0])
    if ref["review"] != str((folder / "review-acceptance.json").relative_to(root)):
        raise ValueError("literal declared parent training review required")
    path = root / ref["review"]
    if not path.exists():
        return None
    review = json.loads(previous._path(root, ref["review"]).read_text())
    if (
        review.get("status") != "accepted_frozen_development_training_posterior"
        or review.get("independent_checker") is not True
        or not isinstance(review.get("files"), dict)
        or review.get("job_id") != ref["job_id"]
        or review.get("model_key") != job["model_key"]
        or review.get("specification_freeze_sha256") != admission["files"][fit.data.FREEZE]
    ):
        raise ValueError("exact independently reviewed declared training posterior required")
    parent = accepted[0]
    previous._require(
        review.get("files"),
        _merge(admission["files"], parent["files"], {parent["receipt"]: parent["receipt_sha256"]}),
    )
    result = _merge(admission["files"], review["files"], {ref["review"]: sha256(path)})
    previous._unchanged(root, result)
    return {p: h for p, h in result.items() if p not in admission["files"]}


def attempt_path(root, job):
    phase = "check" if job["role"].startswith("check_") else job["role"]
    return root / CONTROL / "attempts" / phase / (job["id"] + ".json")


def case_inventory(root, job, worker, files, jobs):
    folder, raw, spec, log, process = paths(root, job, worker)
    allowed_review = set()
    for child in jobs:
        ref = child.get("training_reference")
        if (
            job["role"] == "check_training"
            and child["role"] == "check_evaluate"
            and child["model_key"] == job["model_key"]
            and ref["kind"] == "new_fit"
            and ref["job_id"] == job["id"]
        ):
            literal = str((folder / "review-acceptance.json").relative_to(root))
            if ref["review"] != literal:
                raise ValueError("literal declared independent training review required")
            allowed_review.add(literal)
    actual = set()
    for path in [folder, *folder.rglob("*"), raw, spec, log, process]:
        if path is None:
            continue
        name = str(path.relative_to(root))
        if path.resolve() != path or not path.exists():
            raise ValueError("literal nonsymlink job inventory required")
        if path.is_file():
            previous._path(root, name)
            actual.add(name)
        elif path.is_dir():
            if path != folder and not any(path in (root / name).parents for name in files):
                raise ValueError("unknown job directory; retain for review")
        else:
            raise ValueError("nonregular job artifact; retain for review")
    if actual - allowed_review != set(files):
        raise ValueError("exact literal worker/process artifact inventory required")
    previous._unchanged(root, files)


def proof(root, job, worker, pins, jobs, accepted=None):
    result = worker.case_artifacts(
        root, job, pins, None if accepted is None else {"files": accepted["worker_files"]}
    )
    folder, raw, spec, log, process = paths(root, job, worker)
    receipt = json.loads(previous._path(root, str(process.relative_to(root))).read_text())
    phase = "check" if job["role"].startswith("check_") else job["role"]
    if (
        receipt.get("returncode") != 0
        or receipt.get("reason") != "worker_exit"
        or receipt.get("cost") != cost(job)
        or receipt.get("start_markers") != cost(job)
        or receipt.get("job_sha256") != sha256(spec)
        or receipt.get("plan_sha256") != sha256(root / CONTROL / (phase + "-plan.json"))
        or receipt.get("monitor_failures")
        or json.loads(spec.read_text()) != job
    ):
        raise ValueError("complete successful exact-cost process proof required")
    files = _merge(
        result["files"], {str(p.relative_to(root)): sha256(p) for p in [spec, log, process]}
    )
    case_inventory(root, job, worker, files, jobs)
    if accepted is not None and files != accepted["files"]:
        raise ValueError("immutable process/worker artifact closure changed")
    return result["files"], files


def prefix_proofs(root, state):
    combined = {}
    for phase in PHASES:
        entry = state["phases"].get(phase)
        if entry is None:
            continue
        plan_path = root / CONTROL / (phase + "-plan.json")
        if sha256(plan_path) != entry["plan_sha256"]:
            raise ValueError("immutable phase plan changed")
        plan = json.loads(plan_path.read_text())
        admission = admit(root, phase)
        if plan["files"] != admission["files"] or plan["jobs"] != admission["gate"]["jobs"]:
            raise ValueError("phase source or ordered job identity changed")
        if [a["job_id"] for a in entry["accepted"]] != [
            j["id"] for j in plan["jobs"][: entry["next_job"]]
        ]:
            raise ValueError("ordered complete accepted prefix required")
        combined = _merge(combined, admission["files"])
        for job, accepted, attempt in zip(
            plan["jobs"][: entry["next_job"]], entry["accepted"], entry["attempts"], strict=True
        ):
            source = _merge(admission["files"], accepted["dependency_files"])
            previous._unchanged(root, source)
            proof(root, job, admission["worker"], source, plan["jobs"], accepted)
            if quota(root, admission, paths(root, job, admission["worker"])):
                raise ValueError("closed accepted job resource failure")
            if any(
                attempt[k] != accepted[k] for k in ["job_id", "cost", "receipt", "receipt_sha256"]
            ):
                raise ValueError("attempt and accepted receipt identity changed")
            if sha256(root / accepted["receipt"]) != accepted["receipt_sha256"]:
                raise ValueError("attempt receipt changed")
            if (
                accepted["cost"] != cost(job)
                or attempt["cost"] != cost(job)
                or attempt["start_markers"] != cost(job)
                or json.loads((root / accepted["receipt"]).read_text())
                != {k: v for k, v in accepted.items() if k != "receipt_sha256"}
            ):
                raise ValueError("immutable role-cost and attempt receipt contents required")
            combined = _merge(combined, source)
    return combined


def inventory(root, state, current=None):
    known = {
        p
        for phase in state["phases"].values()
        if phase
        for a in phase["accepted"]
        for p in a["files"]
        if p.startswith(fit.STORE + "/") or p.startswith(RECOVERY_STORE + "/")
    }
    if current is not None and current[1] is not None:
        known.add(str(current[1].relative_to(root)))
    for store in [root / fit.STORE, root / RECOVERY_STORE]:
        actual = set()
        for p in store.rglob("*"):
            if p.is_symlink():
                raise ValueError("raw/cache symlink is not admitted")
            if store / "cache" == p or store / "cache" in p.parents:
                continue
            if p.is_dir():
                raise ValueError("unknown raw directory; no automatic resume")
            if p.is_file():
                actual.add(str(p.relative_to(root)))
        if actual != {p for p in known if p.startswith(str(store.relative_to(root)) + "/")}:
            raise ValueError("unknown/missing raw partial; retain for review")
    for phase, output in zip(
        PHASES, [fit.CHECK_OUTPUT, RECOVERY_OUTPUT, fit.FULL_OUTPUT], strict=True
    ):
        identities = {a["job_id"] for a in (state["phases"].get(phase) or {}).get("accepted", [])}
        if current is not None and current[0].parent == root / output / "jobs":
            identities.add(current[0].name)
        allowed = identities | {
            name + suffix
            for name in identities
            for suffix in ["-spec.json", ".log", ".supervisor.json"]
        }
        if any(p.name not in allowed or p.is_symlink() for p in (root / output / "jobs").glob("*")):
            raise ValueError("unknown job partial; retain for review")
    evidence = {
        name
        for phase in state["phases"].values()
        if phase
        for record in phase["attempts"]
        for name in [record["receipt"], record.get("failure")]
        if name is not None
    }
    if current is not None:
        folder = current[0]
        phase = (
            "check"
            if folder.parent.parent == root / fit.CHECK_OUTPUT
            else "full_design_recovery"
            if folder.parent.parent == root / RECOVERY_OUTPUT
            else "full_development"
        )
        evidence.add(str(Path(CONTROL) / "attempts" / phase / (folder.name + ".json")))
    for path in (root / CONTROL / "attempts").rglob("*"):
        name = str(path.relative_to(root))
        if (
            path.resolve() != path
            or not (path.is_file() or path.is_dir())
            or (path.is_file() and name not in evidence)
            or (path.is_dir() and not any(path in (root / p).parents for p in evidence))
        ):
            raise ValueError("unknown attempt evidence; retain for review")


def quota(root, admission, current=None, *, reserve=False):
    try:
        parents = r.parent_floors(root, admission["gate"])
        for base in global_roots(root):
            if base.is_symlink():
                return "symlink_storage"
            for p in base.rglob("*"):
                if p.is_symlink():
                    return "symlink_storage"
                if p.is_file() and p.stat().st_size > r.FILE_MAX:
                    return "per_file_storage"
        external = sum(
            previous._path(root, p).stat().st_size
            for p in admission["gate"]["external_reference_files"]
        )
        extra = r.RESERVE if reserve else 0
        if (
            r.working_bytes(root, parents) + r.byte_count(*global_roots(root)) + external + extra
            > 3072 * r.MIB
        ):
            return "global_storage"
        if r.byte_count(*roots(root)) + extra > 2048 * r.MIB:
            return "local_storage"
        if r.byte_count(root / fit.STORE / "cache", root / RECOVERY_STORE / "cache") > r.MAX_CACHE:
            return "cache_storage"
        if current is not None:
            folder, raw, spec, log, process = current
            phase = (
                "check"
                if folder.parent.parent == root / fit.CHECK_OUTPUT
                else "full_design_recovery"
                if folder.parent.parent == root / RECOVERY_OUTPUT
                else "full_development"
            )
            evidence = root / CONTROL / "attempts" / phase / (folder.name + ".json")
            if (
                r.byte_count(folder)
                + sum(
                    p.stat().st_size
                    for p in [
                        raw,
                        spec,
                        log,
                        process,
                        evidence,
                        evidence.with_name(folder.name + "-failure.json"),
                    ]
                    if p is not None and p.is_file()
                )
                > r.MAX_JOB
            ):
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


def pilot_review(root, state):
    if state["calls_started"] < 2:
        return {}
    path = previous._path(root, PILOT_REVIEW)
    review = json.loads(path.read_text())
    if (
        review.get("status") != "accepted_development_two_sampler_runtime_pilots"
        or review.get("independent_checker") is not True
        or review.get("sampler_pilot_job_ids") != state["sampler_pilot_job_ids"]
        or review.get("specification_freeze_sha256") != state["specification_freeze_sha256"]
    ):
        raise ValueError("independent first-two-actual-sampler pilot review required")
    needed = {}
    for phase in PHASES:
        for a in (state["phases"].get(phase) or {}).get("accepted", []):
            if phase + ":" + a["job_id"] in state["sampler_pilot_job_ids"]:
                needed.update(a["files"])
                needed[a["receipt"]] = a["receipt_sha256"]
    previous._require(review["files"], needed)
    pins = _merge(review["files"], {PILOT_REVIEW: sha256(path)})
    previous._unchanged(root, pins)
    if state["pilot_review_sha256"] not in {None, pins[PILOT_REVIEW]}:
        raise ValueError("pilot review identity changed")
    state["pilot_review_sha256"] = pins[PILOT_REVIEW]
    return pins


@contextmanager
def leases(root, pins):
    with r._leases(root):
        previous._unchanged(root, pins)
        path = root / CONTROL / ".controller.lock"
        new_json(path, {"pid": os.getpid()})
        try:
            yield
        finally:
            path.unlink()


def run(root, *, phase="check", resume=False, max_jobs=4):
    if phase not in PHASES or type(max_jobs) is not int or not 1 <= max_jobs <= 4:
        raise ValueError("one fixed phase and1..4jobs required")
    root = root.resolve()
    admission = admit(root, phase)
    gate, worker = admission["gate"], admission["worker"]
    state_path, plan_path = root / STATE, root / CONTROL / (phase + "-plan.json")
    snapshot = state_path.read_bytes() if state_path.exists() else None
    if resume != (snapshot is not None):
        raise ValueError("new state only once; exact explicit resume required thereafter")
    state = (
        json.loads(snapshot)
        if snapshot is not None
        else {
            "schema_version": 1,
            "specification_freeze_sha256": admission["files"][fit.data.FREEZE],
            "phase": "check",
            "status": "checkpoint",
            "calls_charged": 0,
            "calls_started": 0,
            "current": None,
            "sampler_pilot_job_ids": [],
            "pilot_review_sha256": None,
            "phases": {p: None for p in PHASES},
        }
    )
    validate_state(state)
    if state["specification_freeze_sha256"] != admission["files"][fit.data.FREEZE]:
        raise ValueError("same immutable scientific freeze required across all phases")
    moving = phase != state["phase"]
    if moving and (
        PHASES.index(phase) != PHASES.index(state["phase"]) + 1
        or state["phases"][state["phase"]] is None
        or state["phases"][state["phase"]]["status"] != "computed_pending_review"
    ):
        raise ValueError("completed preceding phase and prospective next Gate required")
    old_sources = prefix_proofs(root, state)
    sources = _merge(old_sources, admission["files"])
    inherited = gate.get("inherited_calls")
    entry = state["phases"][phase]
    expected_inherited = (
        {"charged": state["calls_charged"], "started": state["calls_started"]}
        if entry is None
        else entry["inherited_calls"]
    )
    if inherited != expected_inherited:
        raise ValueError("prospective phase must conserve inherited cumulative calls")
    expected_plan = {
        "phase": phase,
        "gate": phase_gate(phase),
        "files": admission["files"],
        "jobs": gate["jobs"],
        "inherited_calls": inherited,
        "call_ceiling": gate["max_sampler_call_slots"],
        "specification_freeze_sha256": state["specification_freeze_sha256"],
    }
    if entry is not None and (
        sha256(plan_path) != entry["plan_sha256"]
        or json.loads(plan_path.read_text()) != expected_plan
    ):
        raise ValueError("exact immutable phase plan required")
    if inherited["charged"] + sum(cost(j) for j in gate["jobs"]) > gate["max_sampler_call_slots"]:
        raise ValueError("all phase jobs must fit the explicitly authorized cumulative ceiling")
    inventory(root, state)
    stops = [root / p for p in [r.OLD_OUTPUT + "/STOP", r.OUTPUT + "/STOP", CONTROL + "/STOP"]]
    if any(p.exists() or p.is_symlink() for p in stops):
        raise ValueError("STOP present before allocation")
    with leases(root, sources):
        previous._unchanged(root, sources)
        if (state_path.read_bytes() if state_path.exists() else None) != snapshot:
            raise ValueError("private state changed before exclusive leases")
        if entry is not None and entry["status"] == "computed_pending_review":
            if sha256(root / entry["summary"]) != entry["summary_sha256"] or quota(root, admission):
                raise ValueError("immutable terminal summary changed")
            return
        if entry is None:
            if phase == "check" and resume:
                raise ValueError("cannot reset a missing original check phase")
            new_json(plan_path, expected_plan)
            entry = {
                "plan_sha256": sha256(plan_path),
                "inherited_calls": inherited,
                "next_job": 0,
                "accepted": [],
                "attempts": [],
                "status": "checkpoint",
            }
            state["phases"][phase], state["phase"] = entry, phase
            atomic_state(state_path, state)
        store = root / (RECOVERY_STORE if phase == "full_design_recovery" else fit.STORE)
        os.environ.update(
            PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
            NUMBA_CACHE_DIR=str(store / "cache/numba"),
            MPLCONFIGDIR=str(store / "cache/matplotlib"),
        )
        limit_worker_file_size(r.FILE_MAX)
        ended, failures = threading.Event(), []
        current: list[Any] = [None]

        def monitor():
            while not ended.wait(0.1):
                reason = quota(root, admission, current[0])
                if any(p.exists() for p in stops):
                    reason = reason or "STOP"
                if reason:
                    failures.append(reason)
                    try:
                        with stops[-1].open("x") as stream:
                            stream.write(reason)
                    except FileExistsError:
                        pass
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            for _ in range(min(max_jobs, len(gate["jobs"]) - entry["next_job"])):
                sources = _merge(sources, prefix_proofs(root, state))
                previous._unchanged(root, sources)
                inventory(root, state)
                job = gate["jobs"][entry["next_job"]]
                extra = dependency(root, job, admission, state)
                if extra is None:
                    state["status"] = entry["status"] = "awaiting_training_review"
                    break
                if cost(job) and state["calls_started"] >= 2:
                    if not (root / PILOT_REVIEW).exists():
                        state["status"] = entry["status"] = "awaiting_sampler_pilot_review"
                        break
                    sources = _merge(sources, pilot_review(root, state))
                sources = _merge(sources, extra)
                if (
                    failures
                    or any(p.exists() for p in stops)
                    or quota(root, admission, reserve=True)
                ):
                    raise ValueError("storage/STOP before dispatch")
                if state["calls_charged"] + cost(job) > gate["max_sampler_call_slots"]:
                    raise ValueError("cumulative call ceiling")
                job_paths = paths(root, job, worker)
                folder, raw, spec, log, process = job_paths
                if any(
                    p is not None and (p.exists() or p.is_symlink() or p.resolve() != p)
                    for p in job_paths
                ):
                    raise ValueError("new job paths only; no overwrite or retry")
                new_json(spec, job)
                state["current"] = {"phase": phase, "job_id": job["id"], "cost": cost(job)}
                state["calls_charged"] += cost(job)
                atomic_state(state_path, state)
                current[0] = job_paths
                receipt = {}
                try:
                    previous._unchanged(root, sources)
                    command = [
                        sys.executable,
                        str(
                            root
                            / (
                                RECOVERY_CLI
                                if phase == "full_design_recovery"
                                else "scripts/fit_arrival_development.py"
                            )
                        ),
                        "--job",
                        str(spec),
                        "--output",
                        str(folder),
                        "--max-output-bytes",
                        str(r.FILE_MAX),
                    ]
                    if raw is not None:
                        command.extend(["--store", str(raw)])
                    receipt = supervise(command, log, stops[-1], 600)
                except KeyboardInterrupt:
                    receipt = {"returncode": 130, "reason": "interrupt"}
                except Exception as error:
                    receipt = {
                        "returncode": None,
                        "reason": "supervisor_failure",
                        "error": str(error),
                    }
                markers = len(list(folder.rglob("sampling-start*.json")))
                state["calls_started"] += markers
                if markers and len(state["sampler_pilot_job_ids"]) < 2:
                    state["sampler_pilot_job_ids"].append(phase + ":" + job["id"])
                new_json(
                    process,
                    {
                        **receipt,
                        "cost": cost(job),
                        "start_markers": markers,
                        "job_sha256": sha256(spec),
                        "plan_sha256": entry["plan_sha256"],
                        "invocation_git_sha": git_sha(root),
                        "monitor_failures": list(failures),
                    },
                )
                outcome, worker_files, files = "needs_review", {}, {}
                try:
                    if markers != cost(job):
                        raise ValueError("exact role-specific sampling marker count required")
                    worker_files, files = proof(root, job, worker, sources, gate["jobs"])
                    previous._unchanged(root, sources)
                    inventory(root, state, job_paths)
                    if (
                        failures
                        or quota(root, admission, job_paths)
                        or any(p.exists() for p in stops)
                    ):
                        raise ValueError("late monitor/resource/STOP failure")
                    outcome = "accepted"
                except Exception:
                    files = {
                        str(p.relative_to(root)): sha256(p)
                        for base in roots(root)
                        for p in base.rglob("*")
                        if p.is_file()
                        and not p.is_symlink()
                        and "cache" not in p.relative_to(base).parts
                    }
                evidence = attempt_path(root, job)
                record = {
                    "phase": phase,
                    "job_id": job["id"],
                    "role": job["role"],
                    "cost": cost(job),
                    "files": files,
                    "worker_files": worker_files,
                    "dependency_files": extra,
                    "outcome": outcome,
                    "start_markers": markers,
                    "receipt": str(evidence.relative_to(root)),
                }
                new_json(evidence, record)
                record["receipt_sha256"] = sha256(evidence)
                if outcome == "accepted":
                    try:
                        previous._unchanged(
                            root,
                            _merge(sources, files, {record["receipt"]: record["receipt_sha256"]}),
                        )
                        if json.loads(evidence.read_text()) != {
                            k: v for k, v in record.items() if k != "receipt_sha256"
                        }:
                            raise ValueError("immutable attempt evidence contents required")
                        case_inventory(root, job, worker, files, gate["jobs"])
                        inventory(root, state, job_paths)
                        prefix_proofs(root, state)
                        if (
                            failures
                            or quota(root, admission, job_paths)
                            or any(p.exists() for p in stops)
                        ):
                            raise ValueError("post-evidence resource/STOP failure")
                    except Exception as error:
                        failure = evidence.with_name(job["id"] + "-failure.json")
                        new_json(
                            failure,
                            {
                                "outcome": "needs_review",
                                "error": str(error),
                                "receipt": record["receipt"],
                                "receipt_sha256": record["receipt_sha256"],
                            },
                        )
                        record.update(
                            outcome="needs_review",
                            failure=str(failure.relative_to(root)),
                            failure_sha256=sha256(failure),
                        )
                        outcome = "needs_review"
                entry["attempts"].append(record)
                if outcome != "accepted":
                    raise ValueError("failed computation retained; no omission/retry")
                entry["accepted"].append(record)
                state["current"], current[0] = None, None
                entry["next_job"] += 1
                state["status"] = entry["status"] = "checkpoint"
                atomic_state(state_path, state)
            ended.set()
            watcher.join(timeout=2)
            if failures or quota(root, admission) or any(p.exists() for p in stops):
                raise ValueError("final resource/STOP failure")
            validate_state(state)
            prefix_proofs(root, state)
            if entry["next_job"] == len(gate["jobs"]):
                summary = root / CONTROL / (phase + "-summary.json")
                new_json(
                    summary,
                    {
                        "phase": phase,
                        "status": "computed_pending_independent_review",
                        "calls_charged": state["calls_charged"],
                        "calls_started": state["calls_started"],
                        "plan_sha256": entry["plan_sha256"],
                        "specification_freeze_sha256": state["specification_freeze_sha256"],
                    },
                )
                entry.update(
                    status="computed_pending_review",
                    summary=str(summary.relative_to(root)),
                    summary_sha256=sha256(summary),
                )
            previous._unchanged(root, sources)
            prefix_proofs(root, state)
            inventory(root, state)
            atomic_state(state_path, state)
            prefix_proofs(root, state)
            inventory(root, state)
            if quota(root, admission) or any(p.exists() for p in stops):
                raise ValueError("late final write storage/STOP failure")
        except BaseException:
            state["status"] = entry["status"] = "needs_review"
            atomic_state(state_path, state)
            raise
        finally:
            ended.set()
            watcher.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, default="check")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=4)
    args = parser.parse_args()
    run(
        Path(__file__).resolve().parents[1],
        phase=args.phase,
        resume=args.resume,
        max_jobs=args.max_jobs,
    )
