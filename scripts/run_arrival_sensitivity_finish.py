"""One final47 attempt and seven unchanged tails, preserving the true50-call history."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_sensitivity_repair47 as repair  # noqa: E402
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivity_remaining as previous  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

b, r, c, p, old = previous.b, previous.r, previous.c, previous.p, previous.old
require, read, canonical, digest = (
    previous.require,
    previous.read,
    previous.canonical,
    previous.digest,
)
SELF, TEST = repair.RUNNER, repair.RUNNER_TEST
RUN_ID, CONTROL, GATE = repair.RUN_ID, repair.CONTROL, repair.GATE
BASELINE, REGISTRY, REVIEW = [
    CONTROL + "/" + n
    for n in ["baseline-state.json", "baseline-registry.json", "baseline-review.json"]
]
CASE47_REVIEW = CONTROL + "/case47-review-acceptance.json"
SCIENTIFIC_REVIEW = CONTROL + "/scientific-review.json"
PLAN, COMPLETION_SUMMARY = CONTROL + "/plan.json", CONTROL + "/run-summary.json"
PUBLIC_COMPLETION_SUMMARY = COMPLETION_SUMMARY
resources, proof_contract = previous.resources, previous.proof_contract


def bindings(root):
    return dict(
        project_root=str(root.resolve()),
        state=str(root.resolve() / r.STATE),
        output=CONTROL,
        worker_output=b.OUTPUT,
        worker_store=b.STORE,
    )


def same(actual, expected, message):
    require(all(actual.get(k) == v for k, v in expected.items()), message)


def verify_gate(root):
    root = root.resolve()
    gate, pins = repair.preflight(root)
    parent = previous.verify_gate(root)
    w = parent["worker_admission"]
    c._require(pins, parent["files"])
    baseline, registry, review = [read(root, n) for n in [BASELINE, REGISTRY, REVIEW]]
    refs = dict(
        baseline_state=BASELINE,
        baseline_registry=REGISTRY,
        baseline_review=REVIEW,
        original_plan=c.PLAN,
        worker_spec_gate=b.GATE,
        previous_execution_gate=previous.GATE,
    )
    for key, name in refs.items():
        require(
            gate.get(key) == name and gate.get(key + "_sha256") == pins.get(name),
            "literal genuine50 authority references required",
        )
    c._require(pins, registry.get("files"))
    c._require(pins, review.get("files"))
    c._require(
        review["files"], {**registry["files"], REGISTRY: pins[REGISTRY], BASELINE: pins[BASELINE]}
    )
    original = w["original_jobs"][47]
    job = repair.repair_job(original)
    tails = w["jobs"][12:]
    require(
        len(tails) == 7 and [j["order"] for j in tails] == list(range(48, 55)),
        "only seven original unattempted tails",
    )
    prefix, failures, unresolved = [
        registry.get(k) for k in ["accepted_prefix", "failed_attempts", "unresolved_cases"]
    ]
    legacy = baseline.get("remaining_sensitivity_runs", {}).get(previous.RUN_ID, {})
    require(
        isinstance(prefix, list)
        and len(prefix) == 46
        and prefix[:36] == parent["accepted_prefix"]
        and prefix[36:] == legacy.get("accepted")
        and [d["order"] for d in prefix] == [i for i in range(47) if i != 36]
        and isinstance(failures, list)
        and len(failures) == 4
        and failures[:3] == parent["failed_attempts"]
        and unresolved == parent["unresolved_cases"],
        "46 reviewed fits/four failures/unresolved36 history required",
    )
    counts = dict(
        calls_charged=50,
        calls_started=50,
        planned_cases=55,
        accepted_logical_fits=46,
        unresolved_case_count=1,
        start_original_order=47,
        pending_repair_case=47,
        max_sampler_call_slots=110,
    )
    historical = dict(Counter(d["case_id"] for d in [*prefix, *failures]))
    require(sum(historical.values()) == 50, "all historical attempts conserved")
    core = {
        **counts,
        "historical_attempts_by_original_case": historical,
        "approved_repair_job": job,
        "approved_remaining_jobs": tails,
    }
    same(
        registry,
        dict(
            schema_version=4,
            status="frozen_partial_sensitivity_history_after_case47_failure",
            run_id=RUN_ID,
            **core,
        ),
        "true50 registry schema/counters/jobs required",
    )
    for key in ["baseline_state", "original_plan", "worker_spec_gate", "previous_execution_gate"]:
        same(
            registry,
            {key: refs[key], key + "_sha256": pins[refs[key]]},
            "same immutable parents required",
        )
    expected_review = {
        **core,
        **{k: v for k, v in refs.items() if k != "baseline_review"},
        **{k + "_sha256": pins[v] for k, v in refs.items() if k != "baseline_review"},
        "status": "accepted_late_sensitivity_repair_and_tail_plan",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "accepted_prefix_sha256": digest(prefix),
        "failed_attempts_sha256": digest(failures),
        "unresolved_cases_sha256": digest(unresolved),
        "repair_protocol": repair.PROTOCOL,
        "remaining_protocol": w["gate"]["protocol"],
        "no_third_case36_attempt": True,
        "no_third_case47_attempt": True,
        "case47_disposition_required_before_remaining": True,
        "proof_contract": proof_contract(),
    }
    same(review, expected_review, "independent exact final47/tail numerical plan required")
    same(
        gate,
        dict(
            repair_job=job,
            newremaining_jobs=tails,
            jobs=[job, *tails],
            repair_protocol=repair.PROTOCOL,
            remaining_protocol=w["gate"]["protocol"],
            resources=resources(),
            path_bindings=bindings(root),
            proof_contract=proof_contract(),
            parent_minimum_bytes=w["gate"]["parent_minimum_bytes"],
            external_reference_files=w["gate"]["external_reference_files"],
            calls_before=50,
            started_before=50,
            max_sampler_call_slots=110,
        ),
        "only final47 then unchanged seven within existing caps",
    )
    require(
        baseline.get("calls_charged") == baseline.get("calls_started") == 50
        and legacy.get("status") == "needs_review"
        and legacy.get("current") == w["jobs"][11]
        and legacy.get("next_job") == 10
        and len(legacy.get("attempts", [])) == 11,
        "true failed47 namespace remains unhealed",
    )

    def untouched(state):
        return {
            k: v
            for k, v in state.items()
            if k not in {"calls_charged", "calls_started", "remaining_sensitivity_runs"}
        }

    require(
        untouched(baseline) == untouched(parent["baseline"]),
        "whole original39 history must remain intact",
    )
    failure = failures[-1]
    last = legacy["attempts"][-1]
    same(
        failure,
        dict(
            case_id=original["id"],
            order=47,
            original_job=original,
            execution_job=w["jobs"][11],
            producer="numerical_protocol",
            attempt=1,
            charged_slots=1,
            start_markers=1,
            receipt=last["controller_receipt"],
            receipt_sha256=last["controller_receipt_sha256"],
        ),
        "literal first failed47 call required",
    )
    for failed in failures:
        c._require(pins, failed["files"])
        c._require(pins, failed["physical_files"])
    c._unchanged(root, pins)
    repair_admission = dict(
        gate=gate,
        gate_path=GATE,
        files=pins,
        initial_files=pins,
        jobs=[job, *tails],
        repair_job=job,
        original_admission=w["original_admission"],
    )
    return dict(
        gate=gate,
        gate_path=GATE,
        files=pins,
        initial_files=dict(pins),
        baseline=baseline,
        registry=registry,
        accepted_prefix=prefix,
        failed_attempts=failures,
        unresolved_cases=unresolved,
        repair_job=job,
        newremaining_jobs=tails,
        remaining_jobs=tails,
        jobs=[job, *tails],
        worker_admission=w,
        repair_admission=repair_admission,
        original_admission=w["original_admission"],
        parents=w["parents"],
    )


def entry_of(state):
    return state.get("finish_runs", {}).get(RUN_ID)


def route(root, a, job):
    if job == a["repair_job"]:
        folder, raw = repair.case_paths(root, job)
        return repair, folder, raw, GATE, a["initial_files"], repair.CLI
    require(job in a["newremaining_jobs"], "only exact seven tails after final47")
    folder, raw = a["worker_admission"]["api"].case_paths(
        root, job, admission=a["worker_admission"]
    )
    return (
        a["worker_admission"]["api"],
        folder,
        raw,
        b.GATE,
        a["worker_admission"]["initial_files"],
        b.CLI,
    )


def case_paths(root, a, d):
    if d.get("producer") == "repair47":
        folder, raw = repair.case_paths(root, d["execution_job"])
        return (
            folder,
            raw,
            *(
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ),
        )
    return previous.case_paths(root, a, d)


def descriptor(a, job, files, receipt, root):
    _, folder, raw, spec, _, _ = route(root, a, job)
    return dict(
        case_id=job["original_job"]["id"],
        order=job["order"],
        original_job=job["original_job"],
        execution_job=job,
        producer="repair47" if job == a["repair_job"] else "numerical_protocol",
        source_role="numerical_repair" if job == a["repair_job"] else "numerical_protocol",
        run_id=b.RUN_ID,
        execution_authority_run_id=RUN_ID,
        execution_gate=GATE,
        worker_spec_gate=spec,
        charged_slots=1,
        posterior=str(raw.relative_to(root)),
        posterior_sha256=files[str(raw.relative_to(root))],
        files=files,
        receipt=str(receipt.relative_to(root)),
        receipt_sha256=sha256(receipt),
    )


def new_provenance(root, a, d):
    job = d["execution_job"]
    _, folder, raw, spec_gate, source_pins, _ = route(root, a, job)
    healthy_repair = job == a["repair_job"]
    same(
        d,
        dict(
            case_id=job["original_job"]["id"],
            order=job["order"],
            original_job=job["original_job"],
            producer="repair47" if healthy_repair else "numerical_protocol",
            source_role="numerical_repair" if healthy_repair else "numerical_protocol",
            run_id=b.RUN_ID,
            execution_authority_run_id=RUN_ID,
            execution_gate=GATE,
            worker_spec_gate=spec_gate,
            posterior=str(raw.relative_to(root)),
            posterior_sha256=d["files"].get(str(raw.relative_to(root))),
            charged_slots=1,
        ),
        "exact job-specific descriptor/source authority required",
    )
    paths = [
        folder.with_name(folder.name + "-spec.json"),
        folder.with_name(folder.name + ".supervisor.json"),
        folder / "job.json",
        folder / "sampling-start.json",
        folder / "inputs.json",
    ]
    names = [str(p.relative_to(root)) for p in paths]
    c._require(d["files"], {n: sha256(c._path(root, n)) for n in names})
    specification, process, recorded, start, inputs = [read(root, n) for n in names]
    require(
        specification == recorded == start == job
        and inputs.get("files") == source_pins
        and inputs.get("original_job") == job["original_job"],
        "literal source/job/start metadata required",
    )
    same(
        process,
        dict(
            returncode=0,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=d["files"][names[0]],
            plan_sha256=a["initial_files"][c.PLAN],
            numerical_gate_sha256=source_pins[spec_gate],
            execution_authority_gate_sha256=a["initial_files"][GATE],
            monitor_failures=[],
        ),
        "dual spec/execution authority/process proof required",
    )
    require(
        b.re.fullmatch("[0-9a-f]{40}", process.get("invocation_git_sha", "")) is not None,
        "literal invocation Git required",
    )


def validate_state(state, a):
    base = a["baseline"]
    entry = entry_of(state)
    exclude = {"calls_charged", "calls_started", "finish_runs"}
    require(
        {k: v for k, v in state.items() if k not in exclude}
        == {k: v for k, v in base.items() if k not in exclude},
        "entire50 history immutable",
    )
    prior = dict(state.get("finish_runs", {}))
    prior.pop(RUN_ID, None)
    require(prior == base.get("finish_runs", {}), "other finish namespaces immutable")
    if entry is None:
        require(state == base, "initial canonical STATE equals frozen50")
        return
    attempts = entry.get("attempts", [])
    require(
        entry.get("gate_sha256") == a["initial_files"][GATE]
        and entry.get("baseline_sha256") == a["initial_files"][BASELINE]
        and state["calls_charged"]
        == 50
        + len(attempts)
        + (1 if entry.get("current") and len(attempts) == entry.get("next_job") else 0)
        and 50 <= state["calls_started"] <= state["calls_charged"] <= 110,
        "finish source/call accounting conserved",
    )
    failed = entry.get("status") == "needs_review"
    require(
        not failed
        or entry.get("current") == a["repair_job"]
        and len(attempts) == 1
        and attempts[0]["outcome"] == "needs_review",
        "only reviewed exhausted47 may resume; any tailfailure stops",
    )
    require(
        entry.get("status")
        in {"checkpoint", "awaiting_case47_review", "computed_pending_review", "needs_review"},
        "idle/reviewed finish status required",
    )
    require(
        all(x.get("charged_slots") == 1 and x.get("start_markers") in {0, 1} for x in attempts)
        and state["calls_started"] == 50 + sum(x["start_markers"] for x in attempts)
        and entry.get("next_job") == len(attempts) - (1 if failed else 0)
        and all(
            x.get("outcome") == "accepted" or i == 0 and x.get("outcome") == "needs_review"
            for i, x in enumerate(attempts)
        )
        and (
            not attempts
            or attempts[0]["outcome"] == "accepted"
            or failed
            or entry.get("case47_review_sha256") is not None
        ),
        "literal attempt starts and next-job cursor conserved",
    )
    if not failed:
        require(
            entry.get("current") is None and state["calls_started"] == state["calls_charged"],
            "successful idle finish prefix required",
        )
    require(
        [x["execution_job"] for x in attempts] == a["jobs"][: len(attempts)],
        "exact ordered final47/tails attempts",
    )
    require(
        [d["execution_job"] for d in entry.get("accepted", [])]
        == [x["execution_job"] for x in attempts if x["outcome"] == "accepted"],
        "every successful attempt represented exactly once",
    )
    for d in entry.get("accepted", []):
        require(d["execution_job"] in a["jobs"], "exact new job")
        same(
            d,
            dict(
                execution_gate=GATE,
                worker_spec_gate=GATE if d["execution_job"] == a["repair_job"] else b.GATE,
                execution_authority_run_id=RUN_ID,
            ),
            "descriptor source relabelling rejected",
        )


def failed_repair_provenance(root, a, failed, attempt):
    """Bind an exhausted disposition to the literal retained failed47 producer."""
    job = a["repair_job"]
    folder, raw = repair.case_paths(root, job)
    raw_name = str(raw.relative_to(root))
    raw_sha = sha256(c._path(root, raw_name))
    same(
        failed,
        dict(
            case_id=job["original_job"]["id"],
            order=47,
            original_job=job["original_job"],
            execution_job=job,
            attempt=2,
            producer="repair47",
            source_role="numerical_repair",
            run_id=b.RUN_ID,
            execution_authority_run_id=RUN_ID,
            execution_gate=GATE,
            worker_spec_gate=GATE,
            posterior=raw_name,
            posterior_sha256=raw_sha,
            charged_slots=1,
            start_markers=1,
            receipt=attempt["controller_receipt"],
            receipt_sha256=attempt["controller_receipt_sha256"],
        ),
        "literal exhausted47 raw/source descriptor required",
    )
    actual = physical_files(root, folder, raw)
    require(
        failed.get("physical_files") == actual
        and attempt.get("retained_files") == actual
        and b.re.fullmatch("[0-9a-f]{64}", raw_sha) is not None,
        "complete exhausted47 physical inventory required",
    )
    c._require(failed.get("files"), actual)
    require(
        failed["files"].get(raw_name) == raw_sha,
        "failed raw must be explicitly pinned; no foreign/null posterior",
    )
    spec, log, process = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    mandatory = [
        raw,
        spec,
        log,
        process,
        *[
            folder / leaf
            for leaf in [
                "job.json",
                "sampling-start.json",
                "inputs.json",
                "membership.json",
                "result.json",
            ]
        ],
    ]
    c._require(
        actual,
        {
            str(q.relative_to(root)): sha256(c._path(root, str(q.relative_to(root))))
            for q in mandatory
        },
    )
    require(
        all(
            read(root, str(q.relative_to(root))) == job
            for q in [spec, folder / "job.json", folder / "sampling-start.json"]
        ),
        "failed47 native job/start/spec must be exact",
    )
    old_folder = case_paths(root, a, a["failed_attempts"][-1])[0]
    old_inputs = read(root, str((old_folder / "inputs.json").relative_to(root)))
    expected_inputs = {
        **old_inputs,
        "files": a["initial_files"],
        "run_id": RUN_ID,
        "source_gate": GATE,
    }
    require(
        read(root, str((folder / "inputs.json").relative_to(root))) == expected_inputs
        and read(root, str((folder / "membership.json").relative_to(root)))
        == read(root, str((old_folder / "membership.json").relative_to(root))),
        "unchanged failed47 cohort/prior/input sources required",
    )
    result = read(root, str((folder / "result.json").relative_to(root)))
    same(
        result,
        dict(
            job=job,
            original_job=job["original_job"],
            posterior=raw_name,
            posterior_sha256=raw_sha,
            code_and_config=a["initial_files"],
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            scoring_or_forecast_imputation=False,
        ),
        "retained failed47 result must bind native raw and admitted sources",
    )
    require(
        result.get("status")
        in {"diagnostic_failure", "sampling_or_evaluation_failure", "summary_nonfinite_failure"}
        and failed.get("outcome") == result["status"],
        "failed47 disposition cannot promote a successful/foreign result",
    )
    runtime = read(root, str(process.relative_to(root)))
    same(
        runtime,
        dict(
            returncode=2,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec),
            plan_sha256=a["initial_files"][c.PLAN],
            numerical_gate_sha256=a["initial_files"][GATE],
            execution_authority_gate_sha256=a["initial_files"][GATE],
            monitor_failures=[],
        ),
        "failed47 dual-authority process proof required",
    )
    require(
        b.re.fullmatch("[0-9a-f]{40}", runtime.get("invocation_git_sha", "")) is not None,
        "failed47 literal invocation Git required",
    )
    require(
        read(root, failed["receipt"]) == receipt_body(attempt)
        and sha256(root / failed["receipt"]) == failed["receipt_sha256"],
        "failed47 must retain its exact controller receipt",
    )
    c._unchanged(root, failed["files"])


def disposition(root, a, entry):
    if not (root / CASE47_REVIEW).exists():
        require(entry.get("case47_review_sha256") is None, "sealed47 review missing")
        return None
    require(len(entry.get("attempts", [])) >= 1, "47 review cannot precede attempt")
    review = read(root, CASE47_REVIEW)
    outcome = review.get("case47_outcome")
    require(outcome in {"accepted_repair", "exhausted_unresolved"}, "typed47 disposition only")
    same(
        review,
        dict(
            status="accepted_sensitivity_case47_disposition",
            independent_checker=True,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            repair_job=a["repair_job"],
            execution_authority_gate_sha256=a["initial_files"][GATE],
            repair_spec_gate_sha256=a["initial_files"][GATE],
            calls_charged=51,
            calls_started=51,
        ),
        "independent literal47 disposition required",
    )
    same(
        review.get("remaining_authorization", {}),
        dict(
            status="accepted_sensitivity_final_seven_execution",
            authorized=True,
            jobs=a["newremaining_jobs"],
            calls_before=51,
            started_before=51,
            resources=resources(),
            path_bindings=bindings(root),
            max_sampler_call_slots=110,
        ),
        "explicit seven-tail authority required",
    )
    attempt = entry["attempts"][0]
    needed = p.merge(
        a["initial_files"],
        {
            PLAN: entry["plan_sha256"],
            attempt["controller_receipt"]: attempt["controller_receipt_sha256"],
        },
    )
    if attempt.get("failure_receipt"):
        needed = p.merge(needed, {attempt["failure_receipt"]: attempt["failure_receipt_sha256"]})
    if outcome == "accepted_repair":
        require(
            attempt["outcome"] == "accepted"
            and entry.get("accepted")
            and entry["accepted"][0]["execution_job"] == a["repair_job"],
            "healthy47 cannot relabel failure",
        )
        d = entry["accepted"][0]
        require(review.get("accepted") == d, "exact healthy47 proof")
        needed = p.merge(needed, d["files"], {d["receipt"]: d["receipt_sha256"]})
    else:
        require(
            attempt["outcome"] == "needs_review"
            and attempt["start_markers"] == 1
            and not any(d["order"] == 47 for d in entry.get("accepted", [])),
            "exhausted47 cannot relabel success/omit a start",
        )
        failed = review.get("failed_attempt", {})
        u = review.get("unresolved_case", {})
        same(
            failed,
            dict(
                case_id=a["repair_job"]["original_job"]["id"],
                order=47,
                attempt=2,
                execution_job=a["repair_job"],
                original_job=a["repair_job"]["original_job"],
                producer="repair47",
                charged_slots=1,
                start_markers=1,
                receipt=attempt["controller_receipt"],
                receipt_sha256=attempt["controller_receipt_sha256"],
            ),
            "exact exhausted47 failure proof",
        )
        require(
            failed.get("outcome") != "accepted"
            and u.get("case_id") == failed["case_id"]
            and u.get("order") == 47
            and u.get("original_job") == failed["original_job"]
            and u.get("status") == "computationally_unresolved"
            and u.get("failed_attempts") == [a["failed_attempts"][-1], failed]
            and u.get("posterior") is None
            and u.get("no_third_attempt") is True,
            "exhausted47 has two failures and no usable posterior/third call",
        )
        failed_repair_provenance(root, a, failed, attempt)
        needed = p.merge(needed, failed["files"], failed["physical_files"])
    require(r.STATE not in review.get("files", {}), "no private STATE in public disposition")
    c._require(review.get("files"), needed)
    pins = p.merge(a["files"], review["files"], {CASE47_REVIEW: sha256(root / CASE47_REVIEW)})
    c._unchanged(root, pins)
    require(
        entry.get("case47_review_sha256") in {None, pins[CASE47_REVIEW]},
        "sealed47 disposition changed",
    )
    return review, pins


class Proofs:
    def __init__(self, root, a):
        self.root, self.a, self.identity, self.memo = root, a, digest(a["initial_files"]), {}

    def rebind(self, root, a):
        require(
            root == self.root and digest(a["initial_files"]) == self.identity,
            "foreground source migration",
        )
        self.a = a

    def case(self, d, new=False):
        root, a = self.root, self.a
        paths = case_paths(root, a, d)
        old.physical(root, paths, d["files"], d["receipt"])
        require(
            sha256(root / d["receipt"]) == d["receipt_sha256"]
            and read(root, d["receipt"]) == dict(case_id=d["case_id"], files=d["files"]),
            "literal immutable worker receipt",
        )
        if new:
            new_provenance(root, a, d)
            key = canonical(d)
            identity = d["execution_job"]["id"]
            if identity not in self.memo:
                api, _, _, spec, pins, _ = route(root, a, d["execution_job"])
                proof = (
                    api.case_artifacts(root, d["execution_job"], pins, d)
                    if spec == GATE
                    else api.case_artifacts(root, d["execution_job"], pins, d, gate_path=spec)
                )
                require(proof["files"] == d["files"], "full new job verifier required")
                self.memo[identity] = key
            require(self.memo[identity] == key, "numerical memo identity migration")
            new_provenance(root, a, d)

    def all(self, state, current=None):
        a, root = self.a, self.root
        c._unchanged(root, a["files"])
        for d in a["accepted_prefix"]:
            self.case(d)
        for d in (entry_of(state) or {}).get("accepted", []):
            self.case(d, True)
        failed = list(a["failed_attempts"])
        if a.get("case47_review", {}).get("case47_outcome") == "exhausted_unresolved":
            failed.append(a["case47_review"]["failed_attempt"])
        for d in failed:
            old.physical(root, case_paths(root, a, d), d["physical_files"])
            c._unchanged(root, d["files"])
            require(
                sha256(root / d["receipt"]) == d["receipt_sha256"],
                "retained failed receipt changed",
            )
        for record in (entry_of(state) or {}).get("attempts", []):
            if record.get("failure_receipt"):
                c._unchanged(root, {record["failure_receipt"]: record["failure_receipt_sha256"]})
            require(
                sha256(root / record["controller_receipt"]) == record["controller_receipt_sha256"]
                and read(root, record["controller_receipt"]) == receipt_body(record),
                "immutable finish attempt changed",
            )
        inventory(root, a, state, current)
        c._unchanged(root, a["files"])


def all_cases(a, state, current=None):
    values = [
        *a["accepted_prefix"],
        *a["failed_attempts"],
        *((entry_of(state) or {}).get("accepted", [])),
    ]
    if a.get("case47_review", {}).get("case47_outcome") == "exhausted_unresolved":
        values.append(a["case47_review"]["failed_attempt"])
    if current and not any(d["execution_job"] == current for d in values):
        values.append(
            dict(
                producer="repair47" if current == a["repair_job"] else "numerical_protocol",
                execution_job=current,
            )
        )
    return values


def inventory(root, a, state, current=None):
    paths = [case_paths(root, a, d) for d in all_cases(a, state, current)]
    for store in b.stores(root, a["worker_admission"]):
        require(store.resolve() == store, "symlink store")
        actual = set()
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
            "unknown case/process path",
        )
    allowed = set(a["files"]) | {
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
    for rec in (entry_of(state) or {}).get("attempts", []):
        allowed.add(rec["controller_receipt"])
        if rec.get("failure_receipt"):
            allowed.add(rec["failure_receipt"])
    if current:
        allowed.add(CONTROL + "/attempts/" + current["id"] + ".json")
    if (entry_of(state) or {}).get("status") == "computed_pending_review":
        allowed.add(SCIENTIFIC_REVIEW)
    for q in (root / CONTROL).rglob("*"):
        require(
            q.resolve() == q
            and (
                (q.is_file() and str(q.relative_to(root)) in allowed)
                or (q.is_dir() and any(q in (root / n).parents for n in allowed))
            ),
            "unknown finish evidence",
        )

    for base in [root / previous.CONTROL, root / b.OUTPUT]:
        for q in base.rglob("*"):
            if base == root / b.OUTPUT and (q == base / "jobs" or base / "jobs" in q.parents):
                continue
            require(
                q.resolve() == q
                and (
                    (q.is_file() and str(q.relative_to(root)) in a["initial_files"])
                    or (q.is_dir() and any(q in (root / n).parents for n in a["initial_files"]))
                ),
                "old failed controller evidence must remain frozen",
            )


def quota(root, a, state, current=None, *, reserve=False):
    reason = b.quota(root, a["worker_admission"], state, reserve=reserve)
    if reason:
        return reason
    try:
        for d in all_cases(a, state, current):
            folder, *siblings = case_paths(root, a, d)
            evidence = {
                root / base / "attempts" / (d["execution_job"]["id"] + suffix)
                for base in [old.OUTPUT, b.OUTPUT, previous.CONTROL, CONTROL]
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
        r.new_json(path, dict(pid=os.getpid()))
        try:
            yield
        finally:
            path.unlink()


def plan_value(a):
    return dict(
        files=a["initial_files"],
        repair_job=a["repair_job"],
        remaining_jobs=a["newremaining_jobs"],
        jobs=a["jobs"],
        proof_contract=proof_contract(),
    )


def controller_summary(root, a, state):
    e = entry_of(state)
    review = a["case47_review"]
    healthy = review["case47_outcome"] == "accepted_repair"
    accepted = sorted([*a["accepted_prefix"], *e["accepted"]], key=lambda d: d["order"])
    failed = [*a["failed_attempts"], *([] if healthy else [review["failed_attempt"]])]
    unresolved = [*a["unresolved_cases"], *([] if healthy else [review["unresolved_case"]])]
    require(
        len(accepted) == (54 if healthy else 53)
        and len(failed) == (4 if healthy else 5)
        and len(unresolved) == (1 if healthy else 2)
        and state["calls_charged"] == state["calls_started"] == 58
        and e["next_job"] == 8,
        "all55 original dispositions/58 actual calls required",
    )
    require(
        sorted([d["order"] for d in accepted] + [d["order"] for d in unresolved])
        == list(range(55)),
        "no original probe lost/zero-filled",
    )
    files = dict(a["files"])
    for d in accepted:
        files = p.merge(files, d["files"], {d["receipt"]: d["receipt_sha256"]})
    for record in e["attempts"]:
        files[record["controller_receipt"]] = record["controller_receipt_sha256"]
    files[PLAN] = e["plan_sha256"]
    require(r.STATE not in files, "no privateSTATE in public summary")
    by_order = {d["order"]: d for d in accepted}
    mapping = {}
    for order in [34, *([47] if healthy else [])]:
        d = by_order[order]
        failure = next(f for f in failed if f["order"] == order)
        mapping[d["case_id"]] = dict(
            execution_job=d["execution_job"],
            producer=d["producer"],
            posterior=d["posterior"],
            posterior_sha256=d["posterior_sha256"],
            receipt=d["receipt"],
            receipt_sha256=d["receipt_sha256"],
            failed_attempt_receipt=failure["receipt"],
            failed_attempt_receipt_sha256=failure["receipt_sha256"],
        )
    return dict(
        schema_version=4,
        status="sensitivity_program_complete_with_unresolved_cases",
        run_id=RUN_ID,
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=len(accepted),
        unresolved_case_count=len(unresolved),
        actual_sampler_calls=58,
        calls_charged=58,
        calls_started=58,
        retained_failed_calls=len(failed),
        max_sampler_call_slots=110,
        accepted=accepted,
        retained_failures=failed,
        unresolved_cases=unresolved,
        successful_numerical_repair_mapping=mapping,
        case47_outcome=review["case47_outcome"],
        case47_disposition_review=CASE47_REVIEW,
        case47_disposition_review_sha256=e["case47_review_sha256"],
        repair_job=a["repair_job"],
        remaining_jobs=a["newremaining_jobs"],
        completion_attempts=e["attempts"],
        protocol_amendment=dict(
            protocol=a["worker_admission"]["gate"]["protocol"],
            first_attempt_original_case_ids=[
                j["original_job"]["id"] for j in a["worker_admission"]["jobs"][1:]
            ],
            execution_jobs=a["worker_admission"]["jobs"][1:],
            case47_final_repair=dict(
                execution_job=a["repair_job"],
                protocol=repair.PROTOCOL,
                worker_spec_gate=GATE,
                worker_spec_gate_sha256=a["initial_files"][GATE],
            ),
            remaining_execution_jobs=a["newremaining_jobs"],
        ),
        worker_spec_gate=b.GATE,
        worker_spec_gate_sha256=a["initial_files"][b.GATE],
        repair_spec_gate=GATE,
        repair_spec_gate_sha256=a["initial_files"][GATE],
        execution_authority_gate=GATE,
        execution_authority_gate_sha256=a["initial_files"][GATE],
        baseline_state=BASELINE,
        baseline_state_sha256=a["initial_files"][BASELINE],
        baseline_registry=REGISTRY,
        baseline_registry_sha256=a["initial_files"][REGISTRY],
        baseline_review=REVIEW,
        baseline_review_sha256=a["initial_files"][REVIEW],
        original_plan=c.PLAN,
        original_plan_sha256=a["initial_files"][c.PLAN],
        proof_contract=proof_contract(),
        monitor_failures=[],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
    )


def receipt_body(record):
    omitted = {
        "controller_receipt_sha256",
        "failure_receipt",
        "failure_receipt_sha256",
        "primary_outcome",
    }
    value = {k: v for k, v in record.items() if k not in omitted}
    if "primary_outcome" in record:
        value["outcome"] = record["primary_outcome"]
    return value


def physical_files(root, folder, raw):
    values = [
        *folder.rglob("*"),
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    ]
    return {
        str(q.relative_to(root)): sha256(c._path(root, str(q.relative_to(root))))
        for q in values
        if q.is_file()
    }


def verify_completion_sources(root, summary_path=COMPLETION_SUMMARY):
    root = root.resolve()
    require(summary_path == COMPLETION_SUMMARY, "literal finish summary required")
    stamp = sha256(c._path(root, summary_path))
    summary = read(root, summary_path)
    a = verify_gate(root)
    require(
        r.STATE not in summary.get("files", {}) and summary_path not in summary["files"],
        "public sources independent of privateSTATE",
    )
    c._require(summary["files"], a["initial_files"])
    c._unchanged(root, summary["files"])
    accepted = summary.get("accepted", [])[46:]
    entry: dict[str, Any] = dict(
        gate_sha256=a["initial_files"][GATE],
        baseline_sha256=a["initial_files"][BASELINE],
        plan_sha256=summary["files"].get(PLAN),
        status="computed_pending_review",
        current=None,
        next_job=8,
        accepted=accepted,
        attempts=summary.get("completion_attempts", []),
        case47_review_sha256=summary.get("case47_disposition_review_sha256"),
        case47_outcome=summary.get("case47_outcome"),
    )
    state = {
        **a["baseline"],
        "calls_charged": summary.get("calls_charged"),
        "calls_started": summary.get("calls_started"),
        "finish_runs": {**a["baseline"].get("finish_runs", {}), RUN_ID: entry},
    }
    validate_state(state, a)
    require(read(root, PLAN) == plan_value(a), "immutable public finish plan")
    extra = disposition(root, a, entry)
    require(extra is not None, "typed actual47 disposition required")
    assert extra is not None
    a["case47_review"], a["files"] = extra
    proofs = Proofs(root, a)
    proofs.memo = {d["execution_job"]["id"]: canonical(d) for d in accepted}
    proofs.all(state)
    require(
        summary == controller_summary(root, a, state), "exact branch-derived final58-call history"
    )
    c._unchanged(root, {**summary["files"], summary_path: stamp})
    return dict(admission=a, summary=summary, files={**summary["files"], summary_path: stamp})


def run(root, *, resume=False, max_cases=4, _session=None, _expected_state_sha256=None):
    require(
        type(max_cases) is int and 1 <= max_cases <= 4, "one to four jobs per closed invocation"
    )
    root = root.resolve()
    a = verify_gate(root)
    state_path = c._path(root, r.STATE)
    owned = state_path.read_bytes()
    state = json.loads(owned)
    require(
        _expected_state_sha256 is None
        or hashlib.sha256(owned).hexdigest() == _expected_state_sha256,
        "foreign STATE during source admission",
    )
    validate_state(state, a)
    require(resume == (entry_of(state) is not None), "explicit allocation/resume required")
    if resume:
        entry = entry_of(state)
        require(
            sha256(root / PLAN) == entry["plan_sha256"] and read(root, PLAN) == plan_value(a),
            "immutable finish plan",
        )
        if entry["attempts"]:
            extra = disposition(root, a, entry)
            if extra:
                a["case47_review"], a["files"] = extra
            elif entry["status"] == "needs_review":
                raise ValueError("failed47 STOP; explicit exhausted disposition required")
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
        require(state_path.read_bytes() == owned, "foreign canonical STATE; never overwrite")
        value = (json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        atomic_state(state_path, state)
        owned = value
        require(state_path.read_bytes() == owned, "foreign STATE after write")

    with leases(root):
        require(state_path.read_bytes() == owned, "foreign STATE before lease")
        proofs.all(state)
        require(
            not any(q.exists() or q.is_symlink() for q in stops)
            and not quota(root, a, state, reserve=True),
            "fresh under-lease source/quota/STOP admission required before allocation",
        )
        require(state_path.read_bytes() == owned, "foreign STATE during under-lease admission")
        if not resume:
            r.new_json(root / PLAN, plan_value(a))
            state.setdefault("finish_runs", {})[RUN_ID] = dict(
                gate_sha256=a["initial_files"][GATE],
                baseline_sha256=a["initial_files"][BASELINE],
                plan_sha256=sha256(root / PLAN),
                status="checkpoint",
                current=None,
                next_job=0,
                accepted=[],
                attempts=[],
                case47_review_sha256=None,
                case47_outcome=None,
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
        if entry["attempts"]:
            extra = disposition(root, a, entry)
            if extra is None:
                entry["status"] = "awaiting_case47_review"
                save()
                return hashlib.sha256(owned).hexdigest()
            a["case47_review"], a["files"] = extra
            entry["case47_review_sha256"] = a["files"][CASE47_REVIEW]
            entry["case47_outcome"] = a["case47_review"]["case47_outcome"]
            if entry.get("current"):
                require(
                    entry["current"] == a["repair_job"]
                    and entry["case47_outcome"] == "exhausted_unresolved",
                    "no automatic failed-tail disposition",
                )
                entry["reviewed_failed_current"] = entry["current"]
                entry["current"] = None
                entry["next_job"] = 1
            entry["status"] = "checkpoint"
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
                entry["next_job"] : entry["next_job"] + (max_cases if entry["next_job"] else 1)
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
                api, folder, raw, spec_gate, pins, cli = route(root, a, job)
                spec, log, process = [
                    folder.with_name(folder.name + s)
                    for s in ["-spec.json", ".log", ".supervisor.json"]
                ]
                require(
                    all(
                        q.resolve() == q and not q.exists() and not q.is_symlink()
                        for q in [folder, raw, spec, log, process]
                    ),
                    "new paths only; preserve all partials/no retry",
                )
                r.new_json(spec, job)
                entry["current"] = current[0] = job
                state["calls_charged"] += 1
                save()
                invocation_git = git_sha(root)
                command = [
                    sys.executable,
                    str(root / cli),
                    "--job",
                    str(spec),
                    "--output",
                    str(folder),
                    "--store",
                    str(raw),
                    "--max-output-bytes",
                    str(r.FILE_MAX),
                ]
                if spec_gate != GATE:
                    command += ["--gate", spec_gate]
                try:
                    c._unchanged(root, a["files"])
                    runtime = supervise(command, log, stops[-1], 600)
                except BaseException as error:
                    runtime = dict(
                        returncode=None, reason="supervisor_failure", error=type(error).__name__
                    )
                require(
                    state_path.read_bytes() == owned,
                    "foreign STATE after child; preserve without overwrite",
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
                        "numerical_gate_sha256": pins[spec_gate],
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
                        "one successful invocation required",
                    )
                    proof = (
                        api.case_artifacts(root, job, pins)
                        if spec_gate == GATE
                        else api.case_artifacts(root, job, pins, gate_path=spec_gate)
                    )
                    manifest = Path(proof["manifest"])
                    require(manifest == folder / "attempt-evidence.json", "literal worker manifest")
                    r.new_json(
                        manifest, dict(case_id=job["original_job"]["id"], files=proof["files"])
                    )
                    accepted = descriptor(a, job, proof["files"], manifest, root)
                    proofs.memo[job["id"]] = canonical(accepted)
                    proofs.case(accepted, True)
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
                    record.update(
                        error=error_text, retained_files=physical_files(root, folder, raw)
                    )
                r.new_json(evidence, record)
                record["controller_receipt_sha256"] = sha256(evidence)
                try:
                    require(
                        record["outcome"] == "accepted",
                        "failed computation retained; no automatic retry/skip",
                    )
                    proofs.all(state, job)
                    proofs.case(accepted, True)
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
                        dict(
                            error=str(error),
                            controller_receipt_sha256=record["controller_receipt_sha256"],
                        ),
                    )
                    record.update(
                        primary_outcome=record["outcome"],
                        outcome="needs_review",
                        failure_receipt=str(failure.relative_to(root)),
                        failure_receipt_sha256=sha256(failure),
                    )
                    entry["attempts"].append(record)
                    raise ValueError(
                        "failed computation STOP; only independent47 exhausted review "
                        "can authorize tails"
                    ) from error
                entry["attempts"].append(record)
                entry["accepted"].append(accepted)
                entry["next_job"] += 1
                entry["status"] = (
                    "awaiting_case47_review" if entry["next_job"] == 1 else "checkpoint"
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
            if entry["next_job"] == 8:
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
        and 1 <= invocations <= 3
        and (invocations == 1 or pause_between_batches),
        "bounded acknowledged finish invocations",
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
                    "exact owned ACK/state",
                )
            expected = run(
                root,
                resume=resume or i > 0,
                max_cases=max_cases,
                _session=session,
                _expected_state_sha256=expected,
            )
            if entry_of(read(root.resolve(), r.STATE))["status"] in {
                "awaiting_case47_review",
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
