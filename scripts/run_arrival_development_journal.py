"""Fixed development continuation using immutable charges, attempts and dispositions.

No private state/cursor is created. Failed historical controllers remain frozen.
Only explicitly reviewed CHECK precision gaps may close a logical check slot;
resource/identity/fit failures and incomplete allocations always stop execution.
"""

# pyright: basic
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_development_score_resolution as numerical  # noqa: E402
from scripts import run_arrival_development_completion as c2  # noqa: E402

old, fit, data = c2.old, c2.old.fit, c2.old.fit.data
SELF, TEST = (
    "scripts/run_arrival_development_journal.py",
    "tests/test_run_arrival_development_journal.py",
)
CONTROL = old.CONTROL + "/completion-after-gap-v1"
DESIGN = str(Path(fit.GATE).parent) + "/completion-after-gap-v1"
BASELINE = CONTROL + "/baseline-run-history.json"
CASE0 = data.ART + "development-score-resolution-v1/review-acceptance.json"
CASE1 = data.ART + "development-check-diagnostics-v1/case-001/review-acceptance.json"
PILOT = CONTROL + "/sampler-pilot-review-acceptance.json"
PHASES = old.PHASES
require, load, merge = c2.require, c2.load, c2.merge


def gate_path(phase):
    require(phase in PHASES, "one fixed phase required")
    return DESIGN + "/" + phase + "/review-acceptance.json"


def plan_path(root, phase):
    return root / CONTROL / "plans" / (phase + ".json")


def allocation_path(root, phase, job):
    return root / CONTROL / "allocations" / phase / (job["id"] + ".json")


def attempt_path(root, phase, job):
    return root / CONTROL / "attempts" / phase / (job["id"] + ".json")


def summary_path(root, phase):
    return root / CONTROL / (phase + "-summary.json")


def gap_review_path(root, job):
    return root / CONTROL / "reviews/check" / job["id"] / "review-acceptance.json"


def disposition_path(root, job):
    return root / CONTROL / "dispositions/check" / (job["id"] + ".json")


def bindings(root):
    return {
        **old.bindings(root),
        "control": CONTROL,
        "state": None,
        "original_state": str(root / old.STATE),
        "failed_continuation_state": str(root / c2.STATE),
    }


def history(root, gate):
    for name, key in [
        (old.STATE, "original_state_sha256"),
        (c2.STATE, "failed_continuation_state_sha256"),
    ]:
        p = root / name
        require(
            p.resolve() == p and p.is_file() and old.sha256(p) == gate[key],
            "retained private history changed; never heal or copy its body",
        )


def admit(root, phase):
    """Metadata/source admission only; no C2 state validators or lane loaders."""
    name = gate_path(phase)
    gate = load(root, name)
    require(
        gate.get("status") == "accepted_frozen_arrival_development_journal_execution"
        and gate.get("independent_checker") is True
        and gate.get("phase") == phase
        and gate.get("resources") == fit.resources()
        and gate.get("path_bindings") == bindings(root)
        and gate.get("max_sampler_call_slots") == 9
        and gate.get("no_retuning") is True
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("confirmation_outcomes_parsed") is True,
        "exact journal execution authority required",
    )
    pins = merge(gate["files"], {name: old.sha256(root / name)})
    require(
        {
            SELF,
            TEST,
            c2.SELF,
            c2.TEST,
            old.SELF,
            old.TEST,
            BASELINE,
            CASE0,
            CASE1,
            data.FREEZE,
            fit.GATE,
            gate["worker_gate"],
        }
        <= set(pins)
        and not {old.STATE, c2.STATE} & set(pins),
        "complete immutable source/history closure required",
    )
    old.previous._unchanged(root, pins)
    history(root, gate)
    baseline = load(root, BASELINE)
    require(
        gate.get("baseline_history") == BASELINE
        and gate.get("baseline_history_sha256") == pins[BASELINE]
        and baseline.get("schema_version") == 1
        and baseline.get("private_state_bodies_copied") is False
        and baseline.get("calls_charged") == baseline.get("calls_started") == 0
        and all(
            baseline.get(k) == gate[k]
            for k in ["original_state_sha256", "failed_continuation_state_sha256"]
        ),
        "public zero-call frozen history required",
    )
    old.previous._require(pins, baseline["source_references"])
    failed = baseline["failed_attempt"]
    old.previous._require(pins, failed["files"])
    require(
        failed["cost"] == failed["start_markers"] == 0
        and failed["outcome"] != "accepted"
        and pins[failed["receipt"]] == failed["receipt_sha256"]
        and load(root, failed["receipt"])
        == {k: v for k, v in failed.items() if k != "receipt_sha256"},
        "retained runner-up failed attempt required",
    )
    kernel_name = old.phase_gate(phase)
    require(
        gate["worker_gate"] == kernel_name and gate["worker_gate_sha256"] == pins[kernel_name],
        "literal worker kernel and distinct authority required",
    )
    old.previous._require(pins, load(root, kernel_name)["files"])
    worker = old.consumer(phase)
    kernel = (
        worker.verify_gate(root)
        if phase == "full_design_recovery"
        else worker.verify_gate(root, "check_training" if phase == "check" else "full_development")
    )
    old.previous._require(pins, kernel["files"])
    original = load(root, fit.GATE)["jobs"]
    remaining = original[2:]
    require(
        len(original) == 6
        and len(remaining) == 4
        and baseline["unattempted_job_ids"] == [j["id"] for j in remaining]
        and all(
            j["role"] == "check_evaluate" and j["training_reference"] == {"kind": "historical"}
            for j in original
        ),
        "exact original six frozen historical check jobs required",
    )
    reviews = [load(root, p) for p in [CASE0, CASE1]]
    for review in reviews:
        old.previous._require(pins, review["files"])
    require(
        reviews[0].get("status") == c2.CASE0_STATUS
        and reviews[0].get("independent_checker") is True
        and reviews[0].get("original_job") == original[0]
        and reviews[0].get("case0_outcome") in {"accepted_resolution", "accepted_unresolved_gap"}
        and reviews[1].get("status") == "accepted_frozen_development_runner_up_numerical_gap"
        and reviews[1].get("independent_checker") is True
        and reviews[1].get("original_job") == original[1]
        and reviews[1].get("case1_outcome") == "accepted_unresolved_gap"
        and reviews[1].get("primary_aggregate_available") is False
        and reviews[1].get("without_crossing_aggregate_available") is False
        and reviews[1].get("resolved_result") is None
        and reviews[1].get("resolved_result_sha256") is None,
        "independent baseline score resolution and runner-up numerical gap required",
    )
    for review in reviews:
        require(
            review.get("specification_freeze_sha256") == pins[data.FREEZE]
            and review.get("original_state_sha256") == gate["original_state_sha256"]
            and review.get("reserved_outcomes") == "sealed",
            "same frozen baseline dispositions required",
        )
    require(
        reviews[1].get("failed_continuation_state_sha256")
        == gate["failed_continuation_state_sha256"],
        "runner-up disposition must bind failed second controller",
    )
    # Reuse the resolver's compact independent cold-replay anchor, never its stream.
    proof = numerical.case_artifacts(root, pins)
    require(
        proof.get("semantics_verified") is True
        and proof.get("proof_scope") == "independent_cold_replay_plus_fresh_complete_bytes"
        and proof.get("scientific_review") == CASE0
        and proof.get("scientific_review_sha256") == pins[CASE0]
        and proof.get("original_job") == original[0],
        "strict anchored numerical admission required",
    )
    old.previous._require(pins, proof["review_files"])
    r0, r1 = reviews
    require(
        r0.get("primary_aggregate_available") is (r0["case0_outcome"] == "accepted_resolution"),
        "typed primary availability must match resolution",
    )
    if r0["case0_outcome"] == "accepted_resolution":
        result = numerical.CASE_OUTPUT + "/result.json"
        require(
            r0.get("resolved_result") == result
            and r0.get("resolved_result_sha256") == pins.get(result) == proof["files"].get(result)
            and proof.get("status") == fit.SUCCESS,
            "literal accepted numerical result and SHA required",
        )
    else:
        require(
            r0.get("resolved_result") is None
            and r0.get("resolved_result_sha256") is None
            and proof.get("status") == numerical.UNRESOLVED,
            "null unresolved numeric result required",
        )
    for job, review in zip(original[:2], reviews, strict=True):
        prediction = str(
            Path(fit.CHECK_OUTPUT) / "jobs" / job["id"] / "held-out-record-predictions.csv"
        )
        require(
            review.get("prediction_file") == prediction
            and review.get("prediction_sha256") == pins.get(prediction),
            "literal unchanged original marginal prediction pointer required",
        )
    require(
        r1.get("original_attempt_receipt") == failed["receipt"]
        and r1.get("original_attempt_receipt_sha256") == failed["receipt_sha256"],
        "runner-up typed gap must anchor its exact failed attempt",
    )
    old.previous._require(
        r1["files"], merge(failed["files"], {failed["receipt"]: failed["receipt_sha256"]})
    )
    jobs = remaining if phase == "check" else kernel["gate"]["jobs"]
    require(
        gate["jobs"] == jobs
        and len(jobs) == {"check": 4, "full_design_recovery": 6, "full_development": 3}[phase]
        and gate.get("inherited_calls")
        == {
            "charged": 6 if phase == "full_development" else 0,
            "started": 6 if phase == "full_development" else 0,
        },
        "exact frozen program and inherited counters required",
    )
    expected_reviews = {j["id"]: str(gap_review_path(root, j).relative_to(root)) for j in remaining}
    require(
        gate.get("check_gap_reviews") == expected_reviews,
        "four literal, explicit check-only review paths required",
    )
    for review_name, status in (
        [(data.CHECK_REVIEW, "accepted_frozen_arrival_development_check")]
        if phase != "check"
        else []
    ) + (
        [(old.RECOVERY_REVIEW, "accepted_frozen_full_development_design_checks")]
        if phase == "full_development"
        else []
    ):
        require(review_name in pins, "previous phase review required before consumer")
        review = load(root, review_name)
        old.previous._require(pins, review["files"])
        require(
            review.get("status") == status
            and review.get("independent_checker") is True
            and review.get("specification_freeze_sha256") == pins[data.FREEZE],
            "same-freeze previous phase SCI required",
        )
        if review_name == data.CHECK_REVIEW:
            require(
                review.get("completed_once") is True and review.get("no_retuning") is True,
                "once-only complete six-check dispositions required",
            )
    require(
        set(gate["external_reference_files"]) == set(old.external_paths(root, kernel["freeze"])),
        "exact outside reference inventory required",
    )
    old.previous._require(pins, gate["external_reference_files"])
    old.r.parent_floors(root, gate)
    return dict(
        root=root,
        gate=gate,
        files=pins,
        worker=worker,
        kernel=kernel,
        phase=phase,
        baseline=baseline,
        case0_outcome=reviews[0]["case0_outcome"],
        case1_outcome=reviews[1]["case1_outcome"],
        baseline_dispositions=[
            dict(
                job_id=j["id"],
                job=j,
                outcome=r[k],
                review=n,
                review_sha256=pins[n],
                primary_aggregate_available=r.get("primary_aggregate_available"),
            )
            for j, r, k, n in zip(
                original[:2],
                reviews,
                ["case0_outcome", "case1_outcome"],
                [CASE0, CASE1],
                strict=True,
            )
        ],
    )


def stops(root):
    return [*c2.stop_paths(root), root / CONTROL / "STOP"]


def safe(root, a, current=None, extra=None, reserve=True):
    old.previous._unchanged(root, merge(a["files"], extra or {}))
    history(root, a["gate"])
    require(not any(p.exists() or p.is_symlink() for p in stops(root)), "STOP")
    require(
        c2.quota(root, a, reserve=reserve, known_files=extra) is None,
        "storage/floor/closed numerical inventory failure",
    )
    if current:
        job, paths = current
        folder, raw, spec, log, process = paths
        evidence = [allocation_path(root, a["phase"], job), attempt_path(root, a["phase"], job)]
        require(
            old.r.byte_count(folder)
            + sum(
                p.stat().st_size
                for p in [raw, spec, log, process, *evidence]
                if p is not None and p.is_file()
            )
            <= old.r.MAX_JOB,
            "combined job/evidence32MiB cap",
        )


def phase_plan(root, a):
    return dict(
        phase=a["phase"], gate=gate_path(a["phase"]), files=a["files"], jobs=a["gate"]["jobs"]
    )


def _worker_files(root, a, job, cache):
    key = (a["phase"], job["id"])
    source = a["kernel"]["files"]
    if key not in cache:
        cache[key] = (
            copy.deepcopy(job),
            source.copy(),
            a["worker"].case_artifacts(root, job, source)["files"],
        )
    saved, previous, files = cache[key]
    require(saved == job and previous == source, "memo job/source changed")
    old.previous._unchanged(root, merge(a["files"], files))
    return files


def _check_files():
    return {
        "job.json",
        "inputs.json",
        "membership.json",
        "result.json",
        "event-results.json",
        "direct-score-arrays.npz",
        "held-out-record-predictions.csv",
        "output-checksums.json",
    }


def _producer_names(phase):
    if phase == "check":
        return _check_files()
    names = set(fit.FIT_FILES) | {"summary.json", "output-checksums.json"}
    names |= {
        k.replace("_", "-") + ".csv"
        for k in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]
    }
    return names | (
        {"numerical-oracles.json", "truth-quantiles.csv"}
        if phase == "full_design_recovery"
        else set()
    )


def process_proof(root, a, job, allocation, cache):
    worker_files = _worker_files(root, a, job, cache)
    folder, raw, spec, log, process = old.paths(root, job, a["worker"])
    control = {str(p.relative_to(root)): old.sha256(p) for p in [spec, log, process]}
    p = load(root, str(process.relative_to(root)))
    require(
        p.get("returncode") == 0
        and p.get("reason") == "worker_exit"
        and p.get("monitor_failures") == []
        and p.get("cost") == p.get("start_markers") == old.cost(job)
        and p.get("job_sha256") == old.sha256(spec)
        and p.get("plan_sha256") == old.sha256(plan_path(root, a["phase"]))
        and p.get("authority_gate_sha256") == a["files"][gate_path(a["phase"])]
        and p.get("worker_gate_sha256") == a["files"][old.phase_gate(a["phase"])]
        and p.get("allocation") == str(allocation.relative_to(root))
        and p.get("allocation_sha256") == old.sha256(allocation)
        and p.get("invocation_git_sha")
        == load(root, str(allocation.relative_to(root)))["invocation_git_sha"]
        and load(root, str(spec.relative_to(root))) == job,
        "exact successful dual-authority process proof required",
    )
    files = merge(worker_files, control)
    old.case_inventory(root, job, a["worker"], files, a["gate"]["jobs"])
    require(
        {p.name for p in folder.iterdir()} == _producer_names(a["phase"]),
        "exact declared producer artifacts required",
    )
    files[str(allocation.relative_to(root))] = old.sha256(allocation)
    return worker_files, files


def _gap(root, a, job, record):
    name = str(gap_review_path(root, job).relative_to(root))
    review = load(root, name)
    require(
        a["phase"] == "check"
        and record.get("gap_eligible") is True
        and review.get("status") == "accepted_frozen_development_check_numerical_gap"
        and review.get("independent_checker") is True
        and review.get("original_job") == job
        and review.get("failure_kind") == "numerical_precision_only"
        and record["cost"] == record["start_markers"] == 0
        and record["outcome"] == "needs_review"
        and review.get("fully_computed_same_source") is True
        and review.get("confirmation_outcomes_parsed") is True
        and review.get("reserved_outcomes") == "sealed"
        and review.get("primary_aggregate_available") is False
        and review.get("without_crossing_aggregate_available") is False
        and review.get("resolved_result") is None
        and review.get("resolved_result_sha256") is None
        and review.get("specification_freeze_sha256") == a["files"][data.FREEZE]
        and review.get("attempt") == record["receipt"]
        and review.get("attempt_sha256") == record["receipt_sha256"],
        "individually reviewed, fully computed CHECK-only numerical gap required",
    )
    folder, _, _, _, process = old.paths(root, job, a["worker"])
    result = load(root, str((folder / "result.json").relative_to(root)))
    events = load(root, str((folder / "event-results.json").relative_to(root)))
    prediction = str((folder / "held-out-record-predictions.csv").relative_to(root))
    require(
        review.get("prediction_file") == prediction
        and review.get("prediction_sha256") == record["files"].get(prediction)
        and type(result.get("prediction_rows")) is int
        and result["prediction_rows"] > 0
        and review.get("prediction_rows_precision_passed") == result["prediction_rows"]
        and result.get("status") == "needs_numerical_review"
        and result.get("scoring_performed") is True
        and result.get("sampler_call_started") is False
        and events.get("events")
        and all(
            e.get("predictions", {}).get("status") == "computed_pending_review"
            for e in events["events"]
        ),
        "gap may waive only joint-score precision, never marginal predictions",
    )
    require(
        load(root, str(process.relative_to(root))).get("monitor_failures") == [],
        "no runtime failure waiver",
    )
    needed = merge(a["files"], record["files"], {record["receipt"]: record["receipt_sha256"]})
    old.previous._require(review["files"], needed)
    old.previous._unchanged(root, review["files"])
    return name, review, merge(review["files"], {name: old.sha256(root / name)})


def journal_records(root, a, cache=None, pending=False) -> dict[str, Any]:
    """Derive one phase from immutable allocations; never project a successful state."""
    cache = {} if cache is None else cache
    phase = a["phase"]
    records = []
    passed = []
    gaps = []
    extra = {}
    require(
        not (root / CONTROL / "failures").exists(),
        "retained interrupted/late controller failure; no automatic resume",
    )
    plan = plan_path(root, phase)
    if plan.exists():
        require(
            load(root, str(plan.relative_to(root))) == phase_plan(root, a),
            "immutable phase plan changed",
        )
    for index, job in enumerate(a["gate"]["jobs"]):
        charge = allocation_path(root, phase, job)
        attempt = attempt_path(root, phase, job)
        if not charge.exists():
            require(not attempt.exists(), "attempt without allocation")
            require(
                not any(
                    allocation_path(root, phase, j).exists() for j in a["gate"]["jobs"][index + 1 :]
                ),
                "journal allocation gap",
            )
            break
        require(plan.exists(), "allocation without plan")
        allocation = load(root, str(charge.relative_to(root)))
        require(
            allocation["job"] == job
            and allocation["cost"] == old.cost(job)
            and type(allocation["cost"]) is int
            and allocation["phase"] == phase
            and allocation.get("job_id") == job["id"]
            and allocation.get("role") == job["role"]
            and allocation.get("plan") == str(plan.relative_to(root))
            and allocation.get("authority_gate") == gate_path(phase)
            and allocation.get("worker_gate") == old.phase_gate(phase)
            and allocation.get("spec")
            == str(old.paths(root, job, a["worker"])[2].relative_to(root))
            and allocation.get("spec_sha256") == old.sha256(old.paths(root, job, a["worker"])[2])
            and load(root, allocation["spec"]) == job
            and isinstance(allocation.get("invocation_git_sha"), str)
            and re.fullmatch(r"[0-9a-f]{40}", allocation["invocation_git_sha"]) is not None
            and allocation["plan_sha256"] == old.sha256(plan)
            and allocation["authority_gate_sha256"] == a["files"][gate_path(phase)]
            and allocation["worker_gate_sha256"] == a["files"][old.phase_gate(phase)],
            "immutable charge/job/source identity changed",
        )
        require(attempt.exists(), "incomplete allocation retained; never retry or resume")
        body = load(root, str(attempt.relative_to(root)))
        record = {**body, "receipt_sha256": old.sha256(attempt)}
        require(
            record["job_id"] == job["id"]
            and record["phase"] == phase
            and record["role"] == job["role"]
            and record["cost"] == old.cost(job)
            and record["allocation"] == str(charge.relative_to(root))
            and record["allocation_sha256"] == old.sha256(charge)
            and record["receipt"] == str(attempt.relative_to(root)),
            "immutable attempt/allocation identity changed",
        )
        old.previous._unchanged(root, record["files"])
        require(
            record["files"].get(record["allocation"]) == old.sha256(charge),
            "allocation must remain in exact proof",
        )
        records.append(record)
        if record["outcome"] == "accepted":
            worker, files = process_proof(root, a, job, charge, cache)
            require(
                worker == record["worker_files"] and files == record["files"],
                "accepted producer bytes changed",
            )
            passed.append(record)
        else:
            disposition = disposition_path(root, job)
            if disposition.exists():
                name, review, pins = _gap(root, a, job, record)
                value = load(root, str(disposition.relative_to(root)))
                require(
                    value
                    == dict(
                        job=job,
                        outcome="accepted_unresolved_gap",
                        attempt=record["receipt"],
                        attempt_sha256=record["receipt_sha256"],
                        review=name,
                        review_sha256=pins[name],
                    ),
                    "append-only gap disposition changed",
                )
                extra = merge(
                    extra, pins, {str(disposition.relative_to(root)): old.sha256(disposition)}
                )
                gaps.append(
                    dict(
                        job_id=job["id"],
                        job=job,
                        outcome="accepted_unresolved_gap",
                        review=name,
                        review_sha256=pins[name],
                        primary_aggregate_available=False,
                        disposition=str(disposition.relative_to(root)),
                        disposition_sha256=old.sha256(disposition),
                    )
                )
            elif not (pending and index == len(records) - 1):
                raise ValueError(
                    "failed attempt retained; explicit individually reviewed disposition required"
                )
            else:
                break
    return dict(
        attempt_records=records,
        accepted_records=passed,
        logical_check_dispositions=gaps,
        completed=len(passed) + len(gaps),
        files=extra,
    )


def all_records(root, current, cache, pending=False):
    result = {}
    extra = {}
    charged = started = 0
    pilots = []
    for phase in PHASES[: PHASES.index(current["phase"]) + 1]:
        a = current if phase == current["phase"] else admit(root, phase)
        rows = journal_records(root, a, cache, pending=pending and phase == current["phase"])
        result[phase] = rows
        extra = merge(extra, a["files"], rows["files"])
        for record in rows["attempt_records"]:
            require(
                type(record["start_markers"]) is int and record["start_markers"] == record["cost"],
                "exact actual sampler starts required",
            )
            safe(
                root,
                a,
                (
                    next(j for j in a["gate"]["jobs"] if j["id"] == record["job_id"]),
                    old.paths(
                        root,
                        next(j for j in a["gate"]["jobs"] if j["id"] == record["job_id"]),
                        a["worker"],
                    ),
                ),
                extra,
            )
            charged += record["cost"]
            started += record["start_markers"]
            if record["start_markers"]:
                pilots.append(phase + ":" + record["job_id"])
        if phase != current["phase"]:
            require(rows["completed"] == len(a["gate"]["jobs"]), "previous phase incomplete")
            summary = load(root, str(summary_path(root, phase).relative_to(root)))
            require(
                summary == summary_value(a, rows, charged, started),
                "completed phase summary changed",
            )
            review_name = data.CHECK_REVIEW if phase == "check" else old.RECOVERY_REVIEW
            review = load(root, review_name)
            needed = {
                str(summary_path(root, phase).relative_to(root)): old.sha256(
                    summary_path(root, phase)
                )
            }
            for record in rows["attempt_records"]:
                needed = merge(
                    needed, record["files"], {record["receipt"]: record["receipt_sha256"]}
                )
            old.previous._require(review["files"], needed)
    require(0 <= started <= charged <= 9, "cumulative actual calls cannot be reset/refunded")
    require(
        journal_counters(root) == dict(charged=charged, started=started),
        "all charges and starts, including partials, must remain conserved",
    )
    return result, extra, charged, started, pilots[:2]


def journal_counters(root):
    """Charges include partial allocations; starts come only from literal markers."""
    charged = started = 0
    for phase in PHASES:
        for path in (root / CONTROL / "allocations" / phase).glob("*.json"):
            value = load(root, str(path.relative_to(root)))
            job = value["job"]
            require(
                path == allocation_path(root, phase, job)
                and value["phase"] == phase
                and type(value["cost"]) is int
                and value["cost"] == old.cost(job),
                "exact allocation accounting required",
            )
            plan = load(root, str(plan_path(root, phase).relative_to(root)))
            require(
                job in plan["jobs"] and value["plan_sha256"] == old.sha256(plan_path(root, phase)),
                "partial allocation must retain exact immutable plan",
            )
            charged += value["cost"]
            folder, _ = old.consumer(phase).case_paths(root, job)
            markers = list(folder.glob("sampling-start*.json"))
            require(
                len(markers) <= value["cost"]
                and all(load(root, str(p.relative_to(root))) == job for p in markers),
                "literal actual marker accounting required",
            )
            started += len(markers)
    require(0 <= started <= charged <= 9, "inclusive allocation ceiling")
    return dict(charged=charged, started=started)


def summary_value(a, rows, charged, started):
    return dict(
        phase=a["phase"],
        status="computed_pending_independent_review",
        jobs=a["gate"]["jobs"],
        accepted_records=rows["accepted_records"],
        attempt_records=rows["attempt_records"],
        logical_check_dispositions=(
            a["baseline_dispositions"] + rows["logical_check_dispositions"]
            if a["phase"] == "check"
            else load(a["root"], str(summary_path(a["root"], "check").relative_to(a["root"])))[
                "logical_check_dispositions"
            ]
        ),
        case0_outcome=a["case0_outcome"],
        case1_outcome=a["case1_outcome"],
        calls_charged=charged,
        calls_started=started,
        plan_sha256=old.sha256(plan_path(a["root"], a["phase"])),
        authority_gate=gate_path(a["phase"]),
        authority_gate_sha256=a["files"][gate_path(a["phase"])],
        worker_gate=old.phase_gate(a["phase"]),
        worker_gate_sha256=a["files"][old.phase_gate(a["phase"])],
        specification_freeze_sha256=a["files"][data.FREEZE],
    )


def snapshot(root):
    values = {}
    for p in (root / CONTROL).rglob("*"):
        require(
            p.resolve() == p and (p.is_file() or p.is_dir()),
            "literal regular journal entries required",
        )
        if p.is_file() and p.name != ".journal.lock":
            values[str(p.relative_to(root))] = old.sha256(p)
    return values


class Ownership:
    """Only this process's exclusive writes may advance the journal fingerprint."""

    def __init__(self, root):
        self.root = root
        self.expected = snapshot(root)
        self.lease_check: Callable[[], None] | None = None

    def check(self):
        if self.lease_check is not None:
            self.lease_check()
        require(snapshot(self.root) == self.expected, "foreign journal mutation; never adopt")

    def write(self, path, value):
        self.check()
        old.new_json(path, value)
        if root_relative(path, self.root).startswith(CONTROL + "/"):
            self.expected[root_relative(path, self.root)] = old.sha256(path)
        self.check()


def root_relative(path, root):
    return str(path.relative_to(root))


def inventory(root, a, rows, current=None):
    known = set(a["files"])
    allowed = {CONTROL + "/.journal.lock"}
    for phase, recordset in rows.items():
        known.add(str(plan_path(root, phase).relative_to(root)))
        if summary_path(root, phase).exists():
            known.add(str(summary_path(root, phase).relative_to(root)))
        known.update(recordset["files"])
        for record in recordset["attempt_records"]:
            known.update(record["files"])
            known.add(record["receipt"])
    if current:
        job, paths = current
        folder, raw, spec, log, process = paths
        known.update(str(p.relative_to(root)) for p in [raw, spec, log, process] if p is not None)
        known.add(str(allocation_path(root, a["phase"], job).relative_to(root)))
        allowed.update(str((folder / n).relative_to(root)) for n in _producer_names(a["phase"]))
    if (root / PILOT).exists():
        allowed.add(PILOT)
    for base in old.roots(root):
        for p in base.rglob("*"):
            require(
                p.resolve() == p and (p.is_file() or p.is_dir()), "symlink/special runtime artifact"
            )
            if any(
                root / s / "cache" == p or root / s / "cache" in p.parents
                for s in [fit.STORE, old.RECOVERY_STORE]
            ):
                continue
            name = str(p.relative_to(root))
            require(
                name in known | allowed
                if p.is_file()
                else any(p in (root / q).parents for q in known | allowed),
                "unknown runtime file/directory",
            )


@contextmanager
def leases(root, pins):
    with old.r._leases(root):
        old.previous._unchanged(root, pins)
        lock = root / CONTROL / ".journal.lock"
        old.new_json(lock, {"pid": os.getpid(), "owner": os.urandom(16).hex()})
        original = lock.read_bytes()
        identity = lock.stat()

        def owned():
            require(
                lock.resolve() == lock and lock.is_file(), "owned journal lease missing/replaced"
            )
            actual = lock.stat()
            require(
                (actual.st_dev, actual.st_ino, actual.st_size)
                == (identity.st_dev, identity.st_ino, len(original))
                and lock.read_bytes() == original,
                "foreign journal lease replacement preserved",
            )

        try:
            owned()
            yield owned
        finally:
            owned()  # Never unlink another owner's replacement or modified bytes.
            lock.unlink()


def _run(root, *, phase="check", max_jobs=1, apply_check_gap=None) -> Any:
    require(type(max_jobs) is int and 1 <= max_jobs <= 4, "one to four fixed jobs only")
    root = root.resolve()
    a = admit(root, phase)
    a["root"] = root
    cache = {}
    rows, extra, charged, started, pilots = all_records(
        root, a, cache, pending=apply_check_gap is not None
    )
    owner = Ownership(root)
    safe(root, a, extra=extra, reserve=True)
    store = root / (old.RECOVERY_STORE if phase == "full_design_recovery" else fit.STORE)
    os.environ.update(
        PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
        NUMBA_CACHE_DIR=str(store / "cache/numba"),
        MPLCONFIGDIR=str(store / "cache/matplotlib"),
    )
    with leases(root, extra) as lease_check:
        owner.lease_check = lease_check
        owner.check()
        safe(root, a, extra=extra, reserve=True)
        if apply_check_gap:
            require(
                phase == "check" and rows[phase]["attempt_records"],
                "CHECK-only explicit failed slot required",
            )
            record = rows[phase]["attempt_records"][-1]
            job = a["gate"]["jobs"][len(rows[phase]["attempt_records"]) - 1]
            require(
                job["id"] == apply_check_gap and record["outcome"] != "accepted",
                "only last fully-computed failed CHECK slot",
            )
            name, review, pins = _gap(root, a, job, record)
            owner.write(
                disposition_path(root, job),
                dict(
                    job=job,
                    outcome="accepted_unresolved_gap",
                    attempt=record["receipt"],
                    attempt_sha256=record["receipt_sha256"],
                    review=name,
                    review_sha256=pins[name],
                ),
            )
            rows, extra, charged, started, pilots = all_records(root, a, cache)
            if rows[phase]["completed"] == len(a["gate"]["jobs"]):
                owner.write(
                    summary_path(root, phase), summary_value(a, rows[phase], charged, started)
                )
            inventory(root, a, rows)
            safe(root, a, extra=extra)
            owner.check()
            max_jobs = 0
        inventory(root, a, rows)
        if rows[phase]["completed"] == len(a["gate"]["jobs"]):
            require(
                summary_path(root, phase).exists()
                and load(root, str(summary_path(root, phase).relative_to(root)))
                == summary_value(a, rows[phase], charged, started),
                "exact immutable completed summary required",
            )
            max_jobs = 0
        plan = plan_path(root, phase)
        if max_jobs and not plan.exists():
            owner.write(plan, phase_plan(root, a))
        for _ in range(min(max_jobs, len(a["gate"]["jobs"]) - rows[phase]["completed"])):
            rows, extra, charged, started, pilots = all_records(root, a, cache)
            if started >= 2:
                if not (root / PILOT).exists():
                    break
                review = load(root, PILOT)
                require(
                    review.get("status") == "accepted_development_two_sampler_runtime_pilots"
                    and review.get("independent_checker") is True
                    and review.get("sampler_pilot_job_ids") == pilots
                    and review.get("specification_freeze_sha256") == a["files"][data.FREEZE],
                    "actual first-two pilot SCI required",
                )
                needed = {
                    p: h
                    for r in rows.values()
                    for x in r["attempt_records"]
                    if x["phase"] + ":" + x["job_id"] in pilots
                    for p, h in {**x["files"], x["receipt"]: x["receipt_sha256"]}.items()
                }
                old.previous._require(review["files"], needed)
                safe(
                    root, a, extra=merge(extra, review["files"], {PILOT: old.sha256(root / PILOT)})
                )
            job = a["gate"]["jobs"][rows[phase]["completed"]]
            cost = old.cost(job)
            require(charged + cost <= 9, "nine-call cumulative ceiling")
            paths = old.paths(root, job, a["worker"])
            folder, raw, spec, log, process = paths
            require(
                all(
                    p is None or (not p.exists() and not p.is_symlink() and p.resolve() == p)
                    for p in paths
                ),
                "new job paths only",
            )
            inventory(root, a, rows)
            safe(root, a, extra=extra, reserve=True)
            owner.check()
            old.new_json(spec, job)
            allocation = allocation_path(root, phase, job)
            owner.write(
                allocation,
                dict(
                    phase=phase,
                    job_id=job["id"],
                    job=job,
                    role=job["role"],
                    cost=cost,
                    plan=str(plan.relative_to(root)),
                    plan_sha256=old.sha256(plan),
                    authority_gate=gate_path(phase),
                    authority_gate_sha256=a["files"][gate_path(phase)],
                    worker_gate=old.phase_gate(phase),
                    worker_gate_sha256=a["files"][old.phase_gate(phase)],
                    spec=str(spec.relative_to(root)),
                    spec_sha256=old.sha256(spec),
                    invocation_git_sha=old.git_sha(root),
                ),
            )
            ended, failures = threading.Event(), []

            def watch(ended=ended, failures=failures, job=job, paths=paths, extra=extra, rows=rows):
                while not ended.wait(0.1):
                    try:
                        owner.check()
                        safe(root, a, (job, paths), extra)
                        inventory(root, a, rows, (job, paths))
                    except Exception as exc:
                        failures.append(str(exc))
                        try:
                            with (root / CONTROL / "STOP").open("x") as f:
                                f.write(str(exc))
                        except FileExistsError:
                            pass
                        return

            thread = threading.Thread(target=watch, daemon=True)
            thread.start()
            try:
                owner.check()
                safe(root, a, (job, paths), extra)
                inventory(root, a, rows, (job, paths))
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
                    command += ["--store", str(raw)]
                try:
                    process_result = old.supervise(command, log, root / CONTROL / "STOP", 600)
                except BaseException as exc:
                    process_result = {
                        "returncode": 130 if isinstance(exc, KeyboardInterrupt) else None,
                        "reason": "supervisor_failure",
                        "error": str(exc),
                    }
                ended.set()
                thread.join()
                markers = list(folder.glob("sampling-start*.json"))
                old.new_json(
                    process,
                    {
                        **process_result,
                        "cost": cost,
                        "start_markers": len(markers),
                        "job_sha256": old.sha256(spec),
                        "plan_sha256": old.sha256(plan),
                        "authority_gate_sha256": a["files"][gate_path(phase)],
                        "worker_gate_sha256": a["files"][old.phase_gate(phase)],
                        "allocation": str(allocation.relative_to(root)),
                        "allocation_sha256": old.sha256(allocation),
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
                    gap_eligible=False,
                    worker_files={},
                    files={},
                    allocation=str(allocation.relative_to(root)),
                    allocation_sha256=old.sha256(allocation),
                    receipt=str(attempt_path(root, phase, job).relative_to(root)),
                )
                try:
                    require(
                        len(markers) == cost
                        and (not markers or load(root, str(markers[0].relative_to(root))) == job),
                        "literal start marker count required",
                    )
                    safe(root, a, (job, paths), extra)
                    require(not failures, "runtime monitor failure")
                    record["worker_files"], record["files"] = process_proof(
                        root, a, job, allocation, cache
                    )
                    inventory(root, a, rows, (job, paths))
                    record["outcome"] = "accepted"
                except Exception:
                    record["files"] = {
                        str(p.relative_to(root)): old.sha256(p)
                        for base in [
                            folder,
                            allocation,
                            *[x for x in [raw, spec, log, process] if x is not None],
                        ]
                        for p in ([base] if base.is_file() else base.rglob("*"))
                        if p.is_file() and not p.is_symlink()
                    }
                    try:
                        safe(root, a, (job, paths), extra)
                        inventory(root, a, rows, (job, paths))
                        result = load(root, str((folder / "result.json").relative_to(root)))
                        record["gap_eligible"] = bool(
                            phase == "check"
                            and cost == len(markers) == 0
                            and not failures
                            and process_result.get("returncode") == 2
                            and process_result.get("reason") == "worker_exit"
                            and result.get("status") == "needs_numerical_review"
                            and result.get("job") == job
                            and result.get("scoring_performed") is True
                            and result.get("sampler_call_started") is False
                            and {p.name for p in folder.iterdir()} == _check_files()
                        )
                    except Exception:
                        pass
                owner.write(attempt_path(root, phase, job), record)
                safe(root, a, (job, paths), extra)
                require(
                    record["outcome"] == "accepted",
                    "failed attempt retained; no automatic waiver/retry",
                )
                rows, extra, charged, started, pilots = all_records(root, a, cache)
                inventory(root, a, rows)
                safe(root, a, (job, paths), extra)
            finally:
                ended.set()
                thread.join(timeout=2)
        rows, extra, charged, started, pilots = all_records(root, a, cache)
        if (
            rows[phase]["completed"] == len(a["gate"]["jobs"])
            and not summary_path(root, phase).exists()
        ):
            owner.write(summary_path(root, phase), summary_value(a, rows[phase], charged, started))
        inventory(root, a, rows)
        safe(root, a, extra=extra)
        owner.check()
    owner.lease_check = None
    owner.check()
    safe(root, a, extra=extra)
    inventory(root, a, rows)
    require(not (root / CONTROL / ".journal.lock").exists(), "journal lease cleanup failed")
    return rows[phase]


def run(root, **kwargs) -> Any:
    """Retain late/partial failures so restored bytes cannot silently resume."""
    root = root.resolve()
    phase = kwargs.get("phase", "check")
    before = snapshot(root)
    try:
        return _run(root, **kwargs)
    except BaseException as exc:
        # No foreign/private bytes are ever modified. An immutable failure sidecar
        # blocks this journal after a partial allocation or late accepted-proof failure.
        post_writes = [
            path
            for path in [
                summary_path(root, phase),
                *(root / CONTROL / "dispositions/check").glob("*.json"),
            ]
            if str(path.relative_to(root)) not in before and path.exists()
        ]
        if post_writes:
            failure = root / CONTROL / "failures" / phase / "post-write.json"
            if not failure.exists():
                old.new_json(
                    failure,
                    dict(
                        error=repr(exc),
                        writes={
                            str(path.relative_to(root)): old.sha256(path)
                            for path in post_writes
                            if path.resolve() == path and path.is_file()
                        },
                    ),
                )
        allocations = list((root / CONTROL / "allocations" / phase).glob("*.json"))
        for allocation in allocations:
            name = str(allocation.relative_to(root))
            if name in before:
                continue
            value = load(root, name)
            attempt = attempt_path(root, phase, value["job"])
            if (
                attempt.exists()
                and load(root, str(attempt.relative_to(root))).get("outcome") == "needs_review"
            ):
                continue
            failure = root / CONTROL / "failures" / phase / (value["job"]["id"] + ".json")
            if not failure.exists():
                old.new_json(
                    failure,
                    dict(
                        error=repr(exc), allocation=name, allocation_sha256=old.sha256(allocation)
                    ),
                )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=PHASES, default="check")
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--apply-check-gap")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root,
                phase=args.phase,
                max_jobs=args.max_jobs,
                apply_check_gap=args.apply_check_gap,
            )
        )
    )


if __name__ == "__main__":
    main()
