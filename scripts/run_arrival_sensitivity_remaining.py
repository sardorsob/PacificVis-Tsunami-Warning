"""Run only the reviewed remaining probes; retain the unresolved case and all history."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivity_numerical as b  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

r, c, p, old = b.r, b.c, b.p, b.old
require, read, canonical, digest = b.require, b.read, b.canonical, b.digest
SELF, TEST = (
    "scripts/run_arrival_sensitivity_remaining.py",
    "tests/test_run_arrival_sensitivity_remaining.py",
)
RUN_ID = "remaining-sensitivities-v1"
CONTROL = OUTPUT = r.OUTPUT + "/" + RUN_ID
GATE = r.DESIGN + "/" + RUN_ID + "/review-acceptance.json"
BASELINE, REGISTRY, DISPOSITION = [
    CONTROL + "/" + leaf
    for leaf in ["baseline-state.json", "baseline-registry.json", "disposition-review.json"]
]
PILOT, SCIENTIFIC_REVIEW = (
    CONTROL + "/pilot-review-acceptance.json",
    CONTROL + "/scientific-review.json",
)
PLAN, COMPLETION_SUMMARY = CONTROL + "/plan.json", CONTROL + "/run-summary.json"
PUBLIC_COMPLETION_SUMMARY = COMPLETION_SUMMARY
resources, proof_contract = b.resources, b.proof_contract


def bindings(root):
    return dict(
        project_root=str(root.resolve()),
        state=str(root.resolve() / r.STATE),
        output=CONTROL,
        worker_output=b.OUTPUT,
        worker_store=b.STORE,
    )


def verify_gate(root):
    """Admit execution authority separately from the unchanged worker specification."""
    root = root.resolve()
    gate = read(root, GATE)
    require(
        gate.get("status") == "accepted_remaining_sensitivity_execution_after_unresolved_case"
        and gate.get("independent_checker") is True
        and gate.get("run_id") == RUN_ID
        and gate.get("confirmation_outcomes_parsed") is False
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("resources") == resources()
        and gate.get("path_bindings") == bindings(root)
        and gate.get("proof_contract") == proof_contract()
        and gate.get("max_sampler_call_slots") == 110
        and {
            SELF,
            TEST,
            b.SELF,
            b.TEST,
            b.WORKER,
            b.CLI,
            b.WORKER_TEST,
            BASELINE,
            REGISTRY,
            DISPOSITION,
            b.GATE,
        }
        <= set(gate.get("files", {}))
        and r.STATE not in gate["files"],
        "complete independent remaining execution authority required",
    )
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    c._unchanged(root, pins)
    worker = b.verify_gate(root, b.GATE)  # This never consults canonical private STATE.
    c._require(pins, worker["files"])
    baseline, registry, review = [read(root, name) for name in [BASELINE, REGISTRY, DISPOSITION]]
    refs = {
        "baseline_state": BASELINE,
        "baseline_registry": REGISTRY,
        "disposition_review": DISPOSITION,
        "worker_spec_gate": b.GATE,
        "original_plan": c.PLAN,
    }
    for field, name in refs.items():
        require(
            gate.get(field) == name and gate.get(field + "_sha256") == pins[name],
            "literal remaining authority/source binding required",
        )
    c._require(pins, registry.get("files"))
    c._require(pins, review.get("files"))
    c._require(
        review["files"], {**registry["files"], REGISTRY: pins[REGISTRY], BASELINE: pins[BASELINE]}
    )
    prefix, failed, unresolved = [
        registry.get(k) for k in ["accepted_prefix", "failed_attempts", "unresolved_cases"]
    ]
    require(
        registry.get("schema_version") == 3
        and registry.get("status") == "frozen_partial_sensitivity_history_with_unresolved_case"
        and prefix == worker["accepted_prefix"]
        and len(prefix) == 36
        and isinstance(failed, list)
        and len(failed) == 3
        and [
            {k: v for k, v in f.items() if k not in {"producer", "source_role"}} for f in failed[:2]
        ]
        == worker["failed_attempts"]
        and isinstance(unresolved, list)
        and len(unresolved) == 1,
        "reviewed36 valid/three retained failures/one unresolved registry required",
    )
    historical = registry.get("historical_attempts_by_original_case")
    expected_history = dict(worker["gate"]["historical_attempts_by_original_case"])
    unresolved_job = worker["original_jobs"][36]
    expected_history[unresolved_job["id"]] += 1
    require(
        historical == expected_history
        and sum(historical.values()) == 39
        and unresolved[0].get("case_id") == unresolved_job["id"]
        and unresolved[0].get("order") == 36
        and unresolved[0].get("original_job") == unresolved_job
        and unresolved[0].get("failed_attempts") == [f for f in failed if f["order"] == 36]
        and unresolved[0].get("status") == "computationally_unresolved"
        and unresolved[0].get("no_third_attempt") is True
        and unresolved[0].get("posterior") is None,
        "case36 has exactly two failed attempts, no accepted posterior or third attempt",
    )
    counters = dict(
        calls_charged=39,
        calls_started=39,
        planned_cases=55,
        accepted_logical_fits=36,
        unresolved_case_count=1,
        start_original_order=37,
    )
    for field, value in {
        **counters,
        "historical_attempts_by_original_case": historical,
        "worker_spec_gate": b.GATE,
        "worker_spec_gate_sha256": pins[b.GATE],
        "original_plan": c.PLAN,
        "original_plan_sha256": pins[c.PLAN],
        "baseline_state": BASELINE,
        "baseline_state_sha256": pins[BASELINE],
    }.items():
        require(registry.get(field) == value, "exact frozen39 registry identity required")
    require(
        baseline.get("calls_charged") == baseline.get("calls_started") == 39
        and review.get("status") == "accepted_sensitivity_unresolved_case_disposition"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is False
        and review.get("reserved_outcomes") == "sealed",
        "independent unresolved disposition required",
    )
    for field, value in {
        **counters,
        **{k: gate[k] for k in refs},
        **{k + "_sha256": pins[v] for k, v in refs.items() if k != "disposition_review"},
        "historical_attempts_by_original_case": historical,
        "accepted_prefix_sha256": digest(prefix),
        "failed_attempts_sha256": digest(failed),
        "unresolved_cases_sha256": digest(unresolved),
        "approved_jobs": worker["jobs"][1:],
        "protocol": worker["gate"]["protocol"],
        "max_sampler_call_slots": 110,
        "no_third_case36_attempt": True,
        "proof_contract": proof_contract(),
    }.items():
        if field != "disposition_review":
            require(
                review.get(field) == value,
                "complete explicit disposition and exact18-job authority required",
            )
    require(
        gate.get("jobs") == worker["jobs"][1:]
        and gate.get("protocol") == worker["gate"]["protocol"]
        and gate.get("calls_before") == gate.get("started_before") == 39
        and gate.get("no_third_case36_attempt") is True
        and gate.get("parent_minimum_bytes") == worker["gate"]["parent_minimum_bytes"]
        and gate.get("external_reference_files") == worker["gate"]["external_reference_files"],
        "only original37..54, unchanged numerical protocol and resource floors admitted",
    )
    # The entire actual failed v2 namespace must be present, without making an old-compatible state.
    projection = {
        k: v
        for k, v in baseline.items()
        if k not in {"calls_charged", "calls_started", "numerical_protocol_runs"}
    }
    prior_projection = {
        k: v
        for k, v in worker["baseline"].items()
        if k not in {"calls_charged", "calls_started", "numerical_protocol_runs"}
    }
    extension = baseline.get("numerical_protocol_runs", {}).get(b.RUN_ID, {})
    require(
        projection == prior_projection
        and extension.get("status") == "needs_review"
        and extension.get("current") == worker["jobs"][0]
        and extension.get("accepted") == []
        and extension.get("next_job") == 0
        and len(extension.get("attempts", [])) == 1,
        "true failed39 history must remain intact",
    )
    third = failed[2]
    failed_raw = str(
        worker["api"].case_paths(root, worker["jobs"][0], admission=worker)[1].relative_to(root)
    )
    attempt = extension["attempts"][0]
    require(
        third.get("producer") == "numerical_protocol"
        and third.get("source_role") == "numerical_repair"
        and third.get("original_job") == unresolved_job
        and third.get("execution_job") == worker["jobs"][0]
        and third.get("attempt") == 2
        and third.get("charged_slots") == third.get("start_markers") == 1
        and third.get("outcome") != "accepted"
        and third.get("posterior") == failed_raw
        and third.get("posterior_sha256") == pins.get(failed_raw)
        and third.get("receipt") == attempt.get("controller_receipt")
        and third.get("receipt_sha256")
        == attempt.get("controller_receipt_sha256")
        == pins.get(third.get("receipt")),
        "third retained call is exactly failed case36 attempt2, never accepted/relabelled",
    )
    for failure in failed:
        c._require(pins, failure.get("files"))
        c._require(pins, failure.get("physical_files"))
    c._unchanged(root, pins)
    return dict(
        gate=gate,
        files=pins,
        initial_files=dict(pins),
        baseline=baseline,
        registry=registry,
        accepted_prefix=prefix,
        failed_attempts=failed,
        unresolved_cases=unresolved,
        jobs=gate["jobs"],
        worker_admission=worker,
        original_admission=worker["original_admission"],
        parents=worker["parents"],
    )


def entry_of(state):
    return state.get("remaining_sensitivity_runs", {}).get(RUN_ID)


def _new_descriptor(admission, descriptor):
    job = descriptor.get("execution_job")
    require(job in admission["jobs"], "new descriptor must be an exact remaining job")
    original = job["original_job"]
    require(
        descriptor.get("case_id") == original["id"]
        and descriptor.get("order") == job["order"] == original["order"]
        and descriptor.get("original_job") == original
        and job["attempt"] == 1
        and descriptor.get("producer") == descriptor.get("source_role") == "numerical_protocol"
        and descriptor.get("charged_slots") == 1
        and descriptor.get("run_id") == admission["worker_admission"]["gate"]["run_id"]
        and descriptor.get("execution_gate") == GATE
        and descriptor.get("worker_spec_gate") == b.GATE
        and descriptor.get("execution_authority_run_id") == RUN_ID,
        "literal new descriptor/worker namespace/execution authority required",
    )
    return job


def new_case_provenance(root, admission, descriptor):
    job = _new_descriptor(admission, descriptor)
    folder, raw, spec, _, process = case_paths(root, admission, descriptor)
    metadata = [
        spec,
        process,
        folder / "job.json",
        folder / "sampling-start.json",
        folder / "inputs.json",
    ]
    names = [str(path.relative_to(root)) for path in metadata]
    c._require(descriptor["files"], {name: sha256(c._path(root, name)) for name in names})
    specification, sidecar, recorded_job, start, inputs = [read(root, name) for name in names]
    worker = admission["worker_admission"]
    require(
        specification == recorded_job == start == job
        and inputs.get("files") == worker["initial_files"]
        and inputs.get("original_job") == job["original_job"]
        and descriptor.get("posterior") == str(raw.relative_to(root))
        and descriptor.get("posterior_sha256")
        == descriptor["files"].get(str(raw.relative_to(root)))
        and sidecar.get("returncode") == 0
        and sidecar.get("reason") == "worker_exit"
        and sidecar.get("charged_slots") == sidecar.get("start_markers") == 1
        and sidecar.get("job_sha256") == descriptor["files"][names[0]]
        and sidecar.get("plan_sha256") == admission["initial_files"][c.PLAN]
        and sidecar.get("numerical_gate_sha256") == worker["initial_files"][b.GATE]
        and sidecar.get("execution_authority_gate_sha256") == admission["initial_files"][GATE]
        and re.fullmatch(r"[0-9a-f]{40}", sidecar.get("invocation_git_sha", "")) is not None
        and sidecar.get("monitor_failures") == [],
        "dual worker specification/execution authority/source/process provenance required",
    )


def validate_state(state, admission):
    baseline, entry = admission["baseline"], entry_of(state)
    clean = {
        k: v
        for k, v in state.items()
        if k not in {"calls_charged", "calls_started", "remaining_sensitivity_runs"}
    }
    original = {
        k: v
        for k, v in baseline.items()
        if k not in {"calls_charged", "calls_started", "remaining_sensitivity_runs"}
    }
    prior_runs = dict(state.get("remaining_sensitivity_runs", {}))
    prior_runs.pop(RUN_ID, None)
    require(
        clean == original and prior_runs == baseline.get("remaining_sensitivity_runs", {}),
        "whole39 history is immutable",
    )
    if entry is None:
        require(state == baseline, "initial STATE must equal frozen39 baseline")
        return
    accepted, attempts = entry.get("accepted", []), entry.get("attempts", [])
    require(
        entry.get("gate_sha256") == admission["initial_files"][GATE]
        and entry.get("baseline_sha256") == admission["initial_files"][BASELINE]
        and entry.get("current") is None
        and entry.get("status")
        in {"checkpoint", "awaiting_pilot_review", "computed_pending_review"}
        and entry.get("next_job") == len(accepted) <= 18
        and len(accepted) == len(attempts)
        and [d["execution_job"] for d in accepted] == admission["jobs"][: len(accepted)]
        and state["calls_charged"] == state["calls_started"] == 39 + len(accepted) <= 110,
        "idle successful remaining prefix required; no failed resume/refund",
    )
    for d, a in zip(accepted, attempts, strict=True):
        _new_descriptor(admission, d)
        require(
            a.get("outcome") == "accepted"
            and a.get("charged_slots") == a.get("start_markers") == 1
            and a.get("execution_job") == d["execution_job"]
            and all(a.get(k) == d[k] for k in ["case_id", "receipt", "receipt_sha256"]),
            "every remaining charge/start/receipt must reconcile",
        )


def pilot_review(root, admission, entry):
    if not (root / PILOT).exists():
        require(entry.get("pilot_review_sha256") is None, "sealed pilot missing")
        return None
    first = entry["accepted"][0]
    review = read(root, PILOT)
    require(
        review.get("status") == "accepted_remaining_sensitivity_execution_pilot"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is False
        and review.get("reserved_outcomes") == "sealed"
        and review.get("calls_charged") == review.get("calls_started") == 40
        and review.get("accepted") == first
        and review.get("worker_spec_gate_sha256") == admission["initial_files"][b.GATE]
        and review.get("execution_authority_gate_sha256") == admission["initial_files"][GATE]
        and review.get("remaining_authorization")
        == dict(
            status="accepted_remaining_sensitivity_execution_remaining",
            authorized=True,
            jobs=admission["jobs"][1:],
            calls_before=40,
            started_before=40,
            protocol=admission["gate"]["protocol"],
            resources=resources(),
            path_bindings=bindings(root),
            max_sampler_call_slots=110,
        ),
        "independent healthy pilot and exact17-job continuation required",
    )
    needed = p.merge(
        admission["initial_files"],
        first["files"],
        {
            first["receipt"]: first["receipt_sha256"],
            PLAN: entry["plan_sha256"],
            entry["attempts"][0]["controller_receipt"]: entry["attempts"][0][
                "controller_receipt_sha256"
            ],
        },
    )
    require(r.STATE not in review.get("files", {}), "pilot cannot pin mutable STATE")
    c._require(review.get("files"), needed)
    pins = p.merge(admission["files"], review["files"], {PILOT: sha256(root / PILOT)})
    c._unchanged(root, pins)
    require(entry.get("pilot_review_sha256") in {None, pins[PILOT]}, "sealed healthy pilot drift")
    return pins


class Proofs:
    """Compose stateless existing case checks; never call the old state machine."""

    def __init__(self, root, admission):
        self.root, self.admission, self.identity = (
            root,
            admission,
            digest(admission["initial_files"]),
        )
        self.cases = b.Proofs(root, admission["worker_admission"])

    def rebind(self, root, admission):
        require(
            root == self.root and digest(admission["initial_files"]) == self.identity,
            "foreground authority identity migration",
        )
        self.admission = admission
        self.cases.rebind(root, admission["worker_admission"])

    def case(self, descriptor):
        new_case_provenance(self.root, self.admission, descriptor)
        self.cases.case(descriptor)
        new_case_provenance(self.root, self.admission, descriptor)

    def all(self, state, current=None):
        root, a = self.root, self.admission
        c._unchanged(root, a["files"])
        for d in a["accepted_prefix"]:
            self.cases.case(d)
        for d in (entry_of(state) or {}).get("accepted", []):
            self.case(d)
        for failed in a["failed_attempts"]:
            paths = (
                b.paths_for(root, a["worker_admission"], failed)
                if failed.get("producer")
                else r.case_paths(root, failed["original_job"])
            )
            old.physical(root, paths, failed["physical_files"])
            c._unchanged(root, failed["files"])
            require(
                sha256(c._path(root, failed["receipt"])) == failed["receipt_sha256"],
                "retained failure receipt drift",
            )
        for record in (entry_of(state) or {}).get("attempts", []):
            require(
                sha256(c._path(root, record["controller_receipt"]))
                == record["controller_receipt_sha256"]
                and read(root, record["controller_receipt"])
                == {k: v for k, v in record.items() if k != "controller_receipt_sha256"},
                "immutable remaining receipt drift",
            )
        inventory(root, a, state, current)
        c._unchanged(root, a["files"])


def descriptors(admission, state, current=None):
    values = [
        *admission["accepted_prefix"],
        *admission["failed_attempts"],
        *((entry_of(state) or {}).get("accepted", [])),
    ]
    if current and not any(d["execution_job"] == current for d in values):
        values.append(dict(producer="numerical_protocol", execution_job=current))
    return values


def case_paths(root, admission, d):
    return (
        b.paths_for(root, admission["worker_admission"], d)
        if d.get("producer")
        else r.case_paths(root, d["original_job"])
    )


def inventory(root, admission, state, current=None):
    paths = [case_paths(root, admission, d) for d in descriptors(admission, state, current)]
    for store in b.stores(root, admission["worker_admission"]):
        actual = set()
        require(store.resolve() == store, "symlink store")
        for q in store.rglob("*"):
            require(q.resolve() == q, "raw/cache symlink")
            if q == store / "cache" or store / "cache" in q.parents:
                continue
            require(q.is_file(), "unknown raw directory")
            actual.add(str(q.relative_to(root)))
        require(
            actual
            == {
                str(v[1].relative_to(root)) for v in paths if v[1].parent == store and v[1].exists()
            },
            "unknown retained raw partial",
        )
    for base in [
        root / r.OUTPUT / "jobs",
        root / old.REPAIR_OUTPUT / "jobs",
        root / b.OUTPUT / "jobs",
    ]:
        ids = {v[0].name for v in paths if v[0].parent == base}
        allowed = ids | {n + s for n in ids for s in ["-spec.json", ".log", ".supervisor.json"]}
        require(
            base.resolve() == base
            and all(q.resolve() == q and q.name in allowed for q in base.glob("*")),
            "unknown case/process inventory",
        )
    allowed = set(admission["files"]) | {
        CONTROL + "/" + n
        for n in [
            "plan.json",
            "run-summary.json",
            ".controller.lock",
            "STOP",
            "failure.json",
            "foreign-state-failure.json",
        ]
    }
    for record in (entry_of(state) or {}).get("attempts", []):
        allowed.add(record["controller_receipt"])
        if record.get("failure_receipt"):
            allowed.add(record["failure_receipt"])
    if current:
        allowed.add(CONTROL + "/attempts/" + current["id"] + ".json")
    if (entry_of(state) or {}).get("status") == "computed_pending_review":
        allowed.add(SCIENTIFIC_REVIEW)
    for q in (root / CONTROL).rglob("*"):
        require(q.resolve() == q, "remaining output symlink")
        require(
            (q.is_file() and str(q.relative_to(root)) in allowed)
            or (q.is_dir() and any(q in (root / n).parents for n in allowed)),
            "unknown remaining evidence",
        )
    # The old failed v2 controller remains frozen; only native job paths may grow.
    for q in (root / b.OUTPUT).rglob("*"):
        if root / b.OUTPUT / "jobs" in q.parents or q == root / b.OUTPUT / "jobs":
            continue
        require(
            q.resolve() == q
            and (
                (q.is_file() and str(q.relative_to(root)) in admission["initial_files"])
                or (q.is_dir() and any(q in (root / n).parents for n in admission["initial_files"]))
            ),
            "old v2 controller evidence must remain frozen",
        )


def quota(root, admission, state, current=None, *, reserve=False):
    # Reuse only the read-only resource scan with the TRUE state, never its state machine.
    reason = b.quota(root, admission["worker_admission"], state, current, reserve=reserve)
    if reason:
        return reason
    try:
        for d in descriptors(admission, state, current):
            folder, *siblings = case_paths(root, admission, d)
            evidence = {
                root / base / "attempts" / (d["execution_job"]["id"] + suffix)
                for base in [old.OUTPUT, b.OUTPUT, CONTROL]
                for suffix in [".json", "-failure.json"]
            }
            if d.get("receipt") and folder not in (root / d["receipt"]).parents:
                evidence.add(root / d["receipt"])
            if (
                r.byte_count(folder)
                + sum(q.stat().st_size for q in set(siblings) | evidence if q.is_file())
                > r.MAX_JOB
            ):
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


@contextmanager
def leases(root):
    with r._leases(root):
        path = root / CONTROL / ".controller.lock"
        r.new_json(path, {"pid": os.getpid()})
        try:
            yield
        finally:
            path.unlink()


def plan_value(admission):
    return dict(
        files=admission["initial_files"],
        jobs=admission["jobs"],
        worker_spec_gate=b.GATE,
        execution_authority_gate=GATE,
        proof_contract=proof_contract(),
    )


def controller_summary(root, admission, state):
    entry = entry_of(state)
    accepted = [*admission["accepted_prefix"], *entry["accepted"]]
    require(
        len(accepted) == 54
        and [d["order"] for d in accepted] == [i for i in range(55) if i != 36]
        and state["calls_charged"] == state["calls_started"] == 57,
        "54 valid plus one unresolved probe/57 actual calls required",
    )
    files = dict(admission["files"])
    for d in accepted:
        files = p.merge(files, d["files"], {d["receipt"]: d["receipt_sha256"]})
    for record in entry["attempts"]:
        files[record["controller_receipt"]] = record["controller_receipt_sha256"]
    files[PLAN] = entry["plan_sha256"]
    repaired = accepted[34]
    failure = admission["failed_attempts"][0]
    mapping = {
        repaired["case_id"]: dict(
            execution_job=repaired["execution_job"],
            posterior=repaired["posterior"],
            posterior_sha256=repaired["posterior_sha256"],
            receipt=repaired["receipt"],
            receipt_sha256=repaired["receipt_sha256"],
            failed_attempt_receipt=failure["receipt"],
            failed_attempt_receipt_sha256=failure["receipt_sha256"],
        )
    }
    require(r.STATE not in files, "public summary cannot pin private STATE")
    return dict(
        schema_version=3,
        status="sensitivity_program_complete_with_unresolved_case",
        run_id=RUN_ID,
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=54,
        unresolved_case_count=1,
        actual_sampler_calls=57,
        calls_charged=57,
        calls_started=57,
        retained_failed_calls=3,
        max_sampler_call_slots=110,
        accepted=accepted,
        unresolved_cases=admission["unresolved_cases"],
        retained_failures=admission["failed_attempts"],
        successful_numerical_repair_mapping=mapping,
        completion_attempts=entry["attempts"],
        protocol_amendment=dict(
            protocol=admission["gate"]["protocol"],
            first_attempt_original_case_ids=[j["original_job"]["id"] for j in admission["jobs"]],
            execution_jobs=admission["jobs"],
        ),
        worker_spec_gate=b.GATE,
        worker_spec_gate_sha256=admission["initial_files"][b.GATE],
        execution_authority_gate=GATE,
        execution_authority_gate_sha256=admission["initial_files"][GATE],
        baseline_state=BASELINE,
        baseline_state_sha256=admission["initial_files"][BASELINE],
        baseline_registry=REGISTRY,
        baseline_registry_sha256=admission["initial_files"][REGISTRY],
        disposition_review=DISPOSITION,
        disposition_review_sha256=admission["initial_files"][DISPOSITION],
        original_plan=c.PLAN,
        original_plan_sha256=admission["initial_files"][c.PLAN],
        pilot_review=PILOT,
        pilot_review_sha256=entry["pilot_review_sha256"],
        proof_contract=proof_contract(),
        monitor_failures=[],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
    )


def verify_completion_sources(root, summary_path=COMPLETION_SUMMARY):
    root = root.resolve()
    require(summary_path == COMPLETION_SUMMARY, "literal remaining public summary required")
    summary_sha = sha256(c._path(root, summary_path))
    summary = read(root, summary_path)
    a = verify_gate(root)
    require(
        r.STATE not in summary.get("files", {}) and summary_path not in summary["files"],
        "public closure independent of private STATE",
    )
    c._require(summary["files"], a["initial_files"])
    c._unchanged(root, summary["files"])
    entry = dict(
        gate_sha256=a["initial_files"][GATE],
        baseline_sha256=a["initial_files"][BASELINE],
        status="computed_pending_review",
        current=None,
        next_job=18,
        accepted=summary.get("accepted", [])[36:],
        attempts=summary.get("completion_attempts", []),
        plan_sha256=summary["files"].get(PLAN),
        pilot_review_sha256=summary.get("pilot_review_sha256"),
    )
    # This is a public-history projection for validation, never written as an old controller STATE.
    state = {
        **a["baseline"],
        "calls_charged": summary.get("calls_charged"),
        "calls_started": summary.get("calls_started"),
        "remaining_sensitivity_runs": {
            **a["baseline"].get("remaining_sensitivity_runs", {}),
            RUN_ID: entry,
        },
    }
    validate_state(state, a)
    require(read(root, PLAN) == plan_value(a), "public remaining plan drift")
    pins = pilot_review(root, a, entry)
    require(pins is not None, "accepted remaining pilot required")
    a["files"] = pins
    proofs = Proofs(root, a)
    proofs.cases.verified = {d["execution_job"]["id"]: canonical(d) for d in entry["accepted"]}
    proofs.all(state)
    require(
        summary == controller_summary(root, a, state),
        "exact complete54-valid/one-unresolved public history required",
    )
    c._unchanged(root, {**summary["files"], summary_path: summary_sha})
    return dict(admission=a, summary=summary, files={**summary["files"], summary_path: summary_sha})


def run(root, *, resume=False, max_cases=4, _session=None, _expected_state_sha256=None):
    require(
        type(max_cases) is int and 1 <= max_cases <= 4, "one to four remaining jobs per invocation"
    )
    root = root.resolve()
    a = verify_gate(root)
    state_path = c._path(root, r.STATE)
    owned = state_path.read_bytes()
    state = json.loads(owned)
    require(
        _expected_state_sha256 is None
        or hashlib.sha256(owned).hexdigest() == _expected_state_sha256,
        "foreign STATE during admission",
    )
    validate_state(state, a)
    require(resume == (entry_of(state) is not None), "explicit allocation/resume required")
    if resume:
        entry = entry_of(state)
        require(
            sha256(root / PLAN) == entry["plan_sha256"] and read(root, PLAN) == plan_value(a),
            "immutable remaining plan required",
        )
        if entry["accepted"]:
            extra = pilot_review(root, a, entry)
            if extra:
                a["files"] = extra
    proofs = None if _session is None else _session.get("proofs")
    if proofs is None:
        proofs = Proofs(root, a)
        if _session is not None:
            _session["proofs"] = proofs
    else:
        proofs.rebind(root, a)
    proofs.all(state)
    stops = [root / n for n in [r.OLD_OUTPUT + "/STOP", r.OUTPUT + "/STOP", CONTROL + "/STOP"]]
    require(not any(q.exists() or q.is_symlink() for q in stops), "STOP before allocation")

    def save():
        nonlocal owned
        require(state_path.read_bytes() == owned, "foreign canonical STATE; do not overwrite")
        expected = (json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        atomic_state(state_path, state)
        owned = expected
        require(state_path.read_bytes() == owned, "foreign STATE after write")

    with leases(root):
        require(state_path.read_bytes() == owned, "foreign STATE before lease")
        if not resume:
            r.new_json(root / PLAN, plan_value(a))
            state.setdefault("remaining_sensitivity_runs", {})[RUN_ID] = dict(
                gate_sha256=a["initial_files"][GATE],
                baseline_sha256=a["initial_files"][BASELINE],
                plan_sha256=sha256(root / PLAN),
                status="checkpoint",
                current=None,
                next_job=0,
                accepted=[],
                attempts=[],
                pilot_review_sha256=None,
            )
            save()
        entry = entry_of(state)
        if entry["status"] == "computed_pending_review":
            require(
                sha256(root / COMPLETION_SUMMARY) == entry["summary_sha256"]
                and not quota(root, a, state),
                "terminal summary/resources changed",
            )
            verify_completion_sources(root)
            return hashlib.sha256(owned).hexdigest()
        if entry["accepted"]:
            extra = pilot_review(root, a, entry)
            if extra is None:
                entry["status"] = "awaiting_pilot_review"
                save()
                return hashlib.sha256(owned).hexdigest()
            a["files"] = extra
            entry["pilot_review_sha256"] = extra[PILOT]
            save()
        ended, failures = threading.Event(), []
        current: list[Any] = [None]

        def monitor():
            while not ended.wait(0.1):
                reason = quota(root, a, state, current[0])
                if any(q.exists() or q.is_symlink() for q in stops):
                    reason = reason or "STOP"
                if reason:
                    failures.append(reason)
                    try:
                        with stops[-1].open("x") as stream:
                            stream.write(reason)
                    except FileExistsError:
                        pass
                    return

        cache = root / b.STORE / "cache"
        os.environ.update(
            PYTENSOR_FLAGS=(
                f"floatX=float64,base_compiledir={cache / 'pytensor'},"
                f"compiledir={cache / 'pytensor/compiled'}"
            ),
            NUMBA_CACHE_DIR=str(cache / "numba"),
            MPLCONFIGDIR=str(cache / "matplotlib"),
        )
        limit_worker_file_size(r.FILE_MAX)
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            for job in a["jobs"][
                entry["next_job"] : entry["next_job"] + (max_cases if entry["accepted"] else 1)
            ]:
                proofs.all(state)
                require(state_path.read_bytes() == owned, "foreign STATE before dispatch")
                require(
                    not failures
                    and not any(q.exists() or q.is_symlink() for q in stops)
                    and not quota(root, a, state, reserve=True)
                    and state["calls_charged"] < 110,
                    "source/quota/STOP/call guard",
                )
                folder, raw, spec, log, process = b.paths_for(
                    root,
                    a["worker_admission"],
                    dict(producer="numerical_protocol", execution_job=job),
                )
                require(
                    all(
                        q.resolve() == q and not q.exists() and not q.is_symlink()
                        for q in [folder, raw, spec, log, process]
                    ),
                    "new paths only; never retry/overwrite",
                )
                r.new_json(spec, job)
                entry["current"] = current[0] = job
                state["calls_charged"] += 1
                save()
                invocation_git = git_sha(root)
                try:
                    c._unchanged(root, a["files"])
                    runtime = supervise(
                        [
                            sys.executable,
                            str(root / b.CLI),
                            "--gate",
                            b.GATE,
                            "--job",
                            str(spec),
                            "--output",
                            str(folder),
                            "--store",
                            str(raw),
                            "--max-output-bytes",
                            str(r.FILE_MAX),
                        ],
                        log,
                        stops[-1],
                        600,
                    )
                except BaseException as error:
                    runtime = dict(
                        returncode=None, reason="supervisor_failure", error=type(error).__name__
                    )
                require(
                    state_path.read_bytes() == owned, "foreign STATE after child; do not overwrite"
                )
                markers = len(list(folder.rglob("sampling-start*.json")))
                state["calls_started"] += markers
                r.new_json(
                    process,
                    {
                        **runtime,
                        "charged_slots": 1,
                        "start_markers": markers,
                        "job_sha256": sha256(spec),
                        "plan_sha256": a["initial_files"][c.PLAN],
                        "numerical_gate_sha256": a["initial_files"][b.GATE],
                        "execution_authority_gate_sha256": a["initial_files"][GATE],
                        "invocation_git_sha": invocation_git,
                        "monitor_failures": list(failures),
                    },
                )
                accepted, error_text = None, None
                try:
                    require(
                        markers == 1
                        and runtime.get("returncode") == 0
                        and runtime.get("reason") == "worker_exit",
                        "one successful sampler invocation required",
                    )
                    w = a["worker_admission"]
                    proof = w["api"].case_artifacts(root, job, w["initial_files"], gate_path=b.GATE)
                    manifest = Path(proof["manifest"])
                    require(
                        manifest == folder / "attempt-evidence.json",
                        "literal worker receipt required",
                    )
                    r.new_json(
                        manifest, {"case_id": job["original_job"]["id"], "files": proof["files"]}
                    )
                    accepted = b.execution_descriptor(root, w, job, proof["files"], manifest)
                    accepted.update(
                        execution_gate=GATE,
                        worker_spec_gate=b.GATE,
                        execution_authority_run_id=RUN_ID,
                    )
                    proofs.cases.verified[job["id"]] = canonical(accepted)
                    proofs.case(accepted)
                except Exception as error:
                    error_text = str(error)
                evidence = root / CONTROL / "attempts" / (job["id"] + ".json")
                record = dict(
                    case_id=job["original_job"]["id"],
                    execution_job=job,
                    charged_slots=1,
                    start_markers=markers,
                    outcome="accepted" if accepted and not error_text else "needs_review",
                    controller_receipt=str(evidence.relative_to(root)),
                )
                if accepted:
                    record.update({k: accepted[k] for k in ["receipt", "receipt_sha256"]})
                if error_text:
                    record["error"] = error_text
                r.new_json(evidence, record)
                record["controller_receipt_sha256"] = sha256(evidence)
                try:
                    require(
                        record["outcome"] == "accepted",
                        "failed computation retained; no auto retry/skip",
                    )
                    proofs.all(state, job)
                    proofs.case(accepted)
                    require(
                        not failures
                        and not any(q.exists() or q.is_symlink() for q in stops)
                        and not quota(root, a, state, job),
                        "post-evidence quota/STOP failure",
                    )
                    c._unchanged(
                        root, {record["controller_receipt"]: record["controller_receipt_sha256"]}
                    )
                except Exception as error:
                    failure = evidence.with_name(job["id"] + "-failure.json")
                    r.new_json(
                        failure,
                        {
                            "error": str(error),
                            "controller_receipt_sha256": record["controller_receipt_sha256"],
                        },
                    )
                    record.update(
                        outcome="needs_review",
                        failure_receipt=str(failure.relative_to(root)),
                        failure_receipt_sha256=sha256(failure),
                    )
                    entry["attempts"].append(record)
                    raise ValueError("failed computation retained; no retry/refund") from error
                entry["attempts"].append(record)
                entry["accepted"].append(accepted)
                entry["next_job"] += 1
                entry["status"] = (
                    "awaiting_pilot_review" if entry["next_job"] == 1 else "checkpoint"
                )
                entry["current"] = current[0] = None
                save()
            ended.set()
            watcher.join(timeout=2)
            validate_state(state, a)
            proofs.all(state)
            require(
                not failures
                and not any(q.exists() or q.is_symlink() for q in stops)
                and not quota(root, a, state),
                "final source/quota/STOP failure",
            )
            if entry["next_job"] == 18:
                r.new_json(root / COMPLETION_SUMMARY, controller_summary(root, a, state))
                entry.update(
                    status="computed_pending_review",
                    summary_sha256=sha256(root / COMPLETION_SUMMARY),
                )
            proofs.all(state)
            require(not quota(root, a, state), "late final quota failure")
            save()
        except BaseException as error:
            if not (root / CONTROL / "failure.json").exists():
                r.new_json(
                    root / CONTROL / "failure.json",
                    dict(
                        status="needs_review",
                        error=str(error),
                        calls_charged=state["calls_charged"],
                        calls_started=state["calls_started"],
                    ),
                )
            if state_path.read_bytes() == owned:
                entry["status"] = "needs_review"
                save()
            elif not (root / CONTROL / "foreign-state-failure.json").exists():
                r.new_json(
                    root / CONTROL / "foreign-state-failure.json",
                    dict(
                        expected_state_sha256=hashlib.sha256(owned).hexdigest(),
                        actual_state_sha256=sha256(state_path),
                        canonical_state_overwritten=False,
                    ),
                )
            raise
        finally:
            ended.set()
            watcher.join(timeout=2)
    return hashlib.sha256(owned).hexdigest()


def foreground(root, *, resume=False, max_cases=4, invocations=1, pause_between_batches=False):
    require(
        type(invocations) is int
        and 1 <= invocations <= 6
        and (invocations == 1 or pause_between_batches),
        "bounded acknowledged foreground batches required",
    )
    session, expected = {}, None
    try:
        for i in range(invocations):
            if i:
                require(
                    sha256(c._path(root.resolve(), r.STATE)) == expected, "foreign STATE before ACK"
                )
                answer = input(f"Closed batch STATE {expected}; enter ACK {expected} to continue: ")
                require(
                    answer == f"ACK {expected}"
                    and sha256(c._path(root.resolve(), r.STATE)) == expected,
                    "exact owned ACK/STATE required",
                )
            expected = run(
                root,
                resume=resume or i > 0,
                max_cases=max_cases,
                _session=session,
                _expected_state_sha256=expected,
            )
            if entry_of(read(root.resolve(), r.STATE))["status"] in {
                "awaiting_pilot_review",
                "computed_pending_review",
            }:
                break
        return expected
    finally:
        session.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--foreground-invocations", type=int, default=1)
    parser.add_argument("--pause-between-batches", action="store_true")
    args = parser.parse_args()
    foreground(
        args.root,
        resume=args.resume,
        max_cases=args.max_cases,
        invocations=args.foreground_invocations,
        pause_between_batches=args.pause_between_batches,
    )


if __name__ == "__main__":
    main()
