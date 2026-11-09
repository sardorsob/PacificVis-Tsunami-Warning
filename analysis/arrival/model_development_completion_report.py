"""Read reviewed development tables while preserving the original failed score.

This adapter does not fit, score, simulate, or read posterior/NPZ arrays. The
statistical specification stays frozen; a separately reviewed numerical result
may supply the first check's aggregate alongside its unchanged predictions.
"""

# pyright: basic
from __future__ import annotations

import copy
import json
import math
import re
import tempfile
from pathlib import Path

from analysis.arrival import model_development_report as old
from analysis.arrival import model_development_score_resolution as numerical
from analysis.arrival import model_development_technical_completion as technical
from analysis.arrival.evidence import read_rows, sha256, write_json

data, fit, recovery = old.data, old.fit, old.recovery
GATE = old.GATE
CONTROL = old.CONTROL + "/completion-after-gap-v1"
LEGACY_CONTROL = old.CONTROL + "/completion-v1"
CASE1_REVIEW = data.ART + "development-check-diagnostics-v1/case-001/review-acceptance.json"
BASELINE = CONTROL + "/baseline-run-history.json"
BASELINE_SHA = "440d6e7a976d9a8709d7986d8b75b86279a9fce6ea70a311fe2305a7ff3072d4"
FAILED_STATE_SHA = "09e38b7765779348dc33945fddb1ca57b7ac072462a5e8e6d05f86451b6eaa57"
CASE0_REVIEW = data.ART + "development-score-resolution-v1/review-acceptance.json"
COLD_REVIEW = data.ART + "development-score-resolution-v1/cold-replay-review.json"
NUMERICAL_GATE = data.ART + "development-numerical-resolution-design-v1/review-acceptance.json"
SELF = "analysis/arrival/model_development_completion_report.py"
CLI = "scripts/summarize_arrival_completed_development.py"
TEST = "tests/test_arrival_model_development_completion_report.py"
PHASES = ("check", "full_design_recovery", "full_development")
AUTHORITY = {
    phase: str(Path(fit.GATE).parent / "completion-after-gap-v1" / phase / "review-acceptance.json")
    for phase in PHASES
}
SUMMARIES = {phase: CONTROL + "/" + phase + "-summary.json" for phase in PHASES}
CONSUMED = tuple(
    sorted(
        set(old.CONSUMED)
        | {
            SELF,
            CLI,
            TEST,
            technical.SELF,
            technical.CLI,
            technical.TEST,
            "scripts/run_arrival_development_completion.py",
            "tests/test_run_arrival_development_completion.py",
            "scripts/run_arrival_development_journal.py",
            "tests/test_run_arrival_development_journal.py",
            "analysis/arrival/model_development_score_resolution.py",
            "scripts/resolve_arrival_development_score.py",
            "tests/test_arrival_model_development_score_resolution.py",
        }
    )
)
require = old.require


def _ordinary_case(root, pins, admission, job, phase, reviewed, *, failed=False, program=None):
    require(not failed or phase == "check", "only CHECK precision gaps may be disposed")
    worker = recovery if phase == "full_design_recovery" else fit
    folder, raw = worker.case_paths(root, job)
    name = lambda leaf: str((folder / leaf).relative_to(root))  # noqa: E731
    legacy = (
        program is not None
        and phase == "full_design_recovery"
        and job == program["baseline"]["job"]
    )
    continued = program is not None and not legacy
    control = technical.CONTROL if continued else CONTROL
    authority_name = technical.authority_path(phase) if continued else AUTHORITY[phase]
    receipt = control + f"/attempts/{phase}/{job['id']}.json"
    plan_name = control + "/plans/" + phase + ".json"
    record, plan = [data._json(root, pins, n) for n in [receipt, plan_name]]
    authority = data._json(root, pins, authority_name)
    logical_record = None
    if program is not None:
        require(not failed and phase in technical.PHASES, "technical continuation is G/full only")
        data._require(pins, program["files"])
        data._require(reviewed, program["files"])
        matches = [
            entry
            for entry in program["accepted_records"]
            if (entry.get("job") == job if legacy else entry.get("job_id") == job["id"])
        ]
        require(len(matches) == 1, "one public logical computation descriptor required")
        logical_record = matches[0]
        if legacy:
            baseline = program["baseline"]
            require(
                logical_record.get("producer") == "legacy_G0_strict_revalidation"
                and logical_record.get("logical_outcome") == "accepted_under_strict_revalidation"
                and logical_record.get("original_controller_outcome") == "needs_review"
                and logical_record.get("original_receipt") == receipt
                and logical_record.get("original_receipt_sha256") == pins[receipt]
                and baseline.get("original_receipt") == receipt
                and baseline.get("original_controller_outcome") == "needs_review",
                "original failed G0 attempt and separate strict revalidation required",
            )
        else:
            require(
                logical_record == {**record, "receipt_sha256": pins[receipt]}
                and record.get("producer") == "strict_startup_execution",
                "exact public technical execution receipt required",
            )
    kernel_name = {
        "check": fit.GATE,
        "full_design_recovery": recovery.GATE,
        "full_development": fit.FULL_GATE,
    }[phase]
    require(
        record.get("receipt") == receipt
        and record.get("job_id") == job["id"]
        and record.get("phase") == phase
        and record.get("role") == job["role"]
        and record.get("outcome") == ("needs_review" if failed or legacy else "accepted")
        and (continued or record.get("gap_eligible") is failed)
        and type(record.get("cost")) is int
        and type(record.get("start_markers")) is int
        and record.get("cost") == record.get("start_markers") == int(raw is not None)
        and plan.get("phase") == phase
        and plan.get("authority_gate" if continued else "gate") == authority_name
        and plan.get("jobs") == authority["jobs"],
        "literal complete successful continuation process required",
    )
    data._require(reviewed, {n: pins[n] for n in [receipt, plan_name, authority_name]})
    data._require(reviewed, record.get("files"))
    data._require(pins, record["files"])
    data._require(pins, plan.get("files"))
    require(
        plan["files"] == {**authority["files"], authority_name: pins[authority_name]},
        "complete recorded execution admission required",
    )
    manifest = data._json(root, pins, name("output-checksums.json"))
    body = (
        {"event-results.json", "direct-score-arrays.npz", "held-out-record-predictions.csv"}
        if raw is None
        else {
            "summary.json",
            "prior-settings.json",
            "sampling-start.json",
            "diagnostics.json",
            "sampling-diagnostics.csv",
            *(n.replace("_", "-") + ".csv" for n in old.TABLES),
        }
    )
    if phase == "full_design_recovery":
        body |= {"numerical-oracles.json", "truth-quantiles.csv"}
    require(
        {"job.json", "inputs.json", "membership.json", "result.json", *body} == set(manifest),
        "complete unchanged worker manifest required",
    )
    worker_files = {name(n): digest for n, digest in manifest.items()}
    worker_files[name("output-checksums.json")] = pins[name("output-checksums.json")]
    if raw is not None:
        worker_files[str(raw.relative_to(root))] = pins[str(raw.relative_to(root))]
    require(
        record.get("worker_files") == ({} if failed or legacy else worker_files)
        and (
            not legacy
            or (program is not None and program["baseline"]["worker_files"] == worker_files)
        ),
        "exact worker inventory required",
    )
    data._require(record["files"], worker_files)
    spec, log, process = [
        folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]
    ]
    allocation_path = control + f"/allocations/{phase}/{job['id']}.json"
    require(
        record.get("allocation") == allocation_path
        and record.get("allocation_sha256") == pins.get(allocation_path),
        "literal prelaunch journal allocation required",
    )
    allocation = data._json(root, pins, allocation_path)
    expected_allocation = dict(
        phase=phase,
        job_id=job["id"],
        job=job,
        role=job["role"],
        cost=int(raw is not None),
        plan=plan_name,
        plan_sha256=pins[plan_name],
        authority_gate=authority_name,
        authority_gate_sha256=pins[authority_name],
        worker_gate=kernel_name,
        worker_gate_sha256=pins[kernel_name],
        spec=str(spec.relative_to(root)),
        spec_sha256=pins[str(spec.relative_to(root))],
    )
    require(
        all(allocation.get(k) == v for k, v in expected_allocation.items())
        and type(allocation.get("cost")) is int
        and isinstance(allocation.get("invocation_git_sha"), str)
        and re.fullmatch("[0-9a-f]{40}", allocation["invocation_git_sha"]) is not None,
        "exact prelaunch job/plan/dual-authority/execution-Git allocation required",
    )
    required_process = {str(p.relative_to(root)) for p in [spec, log, process]} | {allocation_path}
    if continued:
        proof = technical.proof_path(root, phase, job)
        proof_name = str(proof.relative_to(root))
        required_process |= {
            str(p.relative_to(root))
            for p in [proof, proof.with_name("proof.log"), proof.with_name("proof-process.json")]
        }
        strict = data._json(root, pins, proof_name)
        proof_process = data._json(
            root, pins, str(proof.with_name("proof-process.json").relative_to(root))
        )
        require(
            record.get("strict_proof") == proof_name
            and strict.get("status") == "strict_original_worker_artifacts_passed"
            and strict.get("job") == job
            and strict.get("worker_files") == worker_files
            and strict.get("sampler_calls") == 0
            and proof_process.get("returncode") == 0
            and proof_process.get("reason") == "worker_exit",
            "separate unchanged zero-sampler strict proof required",
        )
    require(
        set(record["files"]) == set(worker_files) | required_process,
        "exact retained worker/process inventory required",
    )
    actual = {str(p.relative_to(root)) for p in folder.rglob("*") if p.is_file()}
    require(
        actual == {name(n) for n in manifest} | {name("output-checksums.json")}
        and all(p.resolve() == p and p.is_file() for p in folder.rglob("*")),
        "exact regular flat worker physical inventory required",
    )
    supervisor = data._json(root, pins, str(process.relative_to(root)))
    require(
        data._json(root, pins, str(spec.relative_to(root))) == job
        and supervisor.get("returncode") == (2 if failed else 0)
        and supervisor.get("reason") == "worker_exit"
        and supervisor.get("monitor_failures") == []
        and type(supervisor.get("cost")) is int
        and type(supervisor.get("start_markers")) is int
        and supervisor.get("cost") == supervisor.get("start_markers") == int(raw is not None)
        and supervisor.get("job_sha256") == pins[str(spec.relative_to(root))]
        and supervisor.get("plan_sha256") == pins[plan_name]
        and supervisor.get("authority_gate_sha256") == pins[authority_name]
        and supervisor.get("worker_gate_sha256") == pins[kernel_name]
        and supervisor.get("allocation") == allocation_path
        and supervisor.get("allocation_sha256") == pins[allocation_path]
        and supervisor.get("invocation_git_sha") == allocation["invocation_git_sha"]
        and (
            not continued
            or supervisor.get("startup_environment") == technical.environment(root, phase)
        ),
        "exact worker/authority/source/cost supervision proof required",
    )
    result, inputs, membership = [
        data._json(root, pins, name(n)) for n in ["result.json", "inputs.json", "membership.json"]
    ]
    target, model = admission["specs"][job["model_key"]]
    require(
        result.get("job") == data._json(root, pins, name("job.json")) == job
        and result.get("status") == ("needs_numerical_review" if failed else fit.SUCCESS)
        and result.get("confirmation_outcomes_parsed") is True
        and result.get("reserved_outcomes") == "sealed"
        and inputs.get("files") == admission["files"]
        and inputs.get("model_spec") == model
        and (
            inputs.get("protocol") == recovery.protocol()
            if phase == "full_design_recovery"
            else inputs.get("specification_freeze_sha256") == pins[data.FREEZE]
        ),
        "unchanged successful frozen worker result required",
    )
    settings = None
    if raw is not None:
        require(
            result.get("posterior") == str(raw.relative_to(root))
            and result.get("posterior_sha256") == pins[str(raw.relative_to(root))]
            and result.get("diagnostics", {}).get("screen_passed") is True
            and data._json(root, pins, name("sampling-start.json")) == job,
            "literal sampled posterior and diagnostic proof required",
        )
        settings = data._json(root, pins, name("prior-settings.json"))
        base, wider, effective = fit._priors(root, target, model)
        require(
            settings == dict(base_prior=base, wider_prior=wider, **effective),
            "same priors required",
        )
    if phase == "full_design_recovery":
        require(
            result.get("sampler_call_started") is True
            and result.get("numerical_oracles_passed") is True
            and data._json(root, pins, name("numerical-oracles.json")).get("passed") is True
            and data._json(root, pins, name("diagnostics.json")) == result["diagnostics"]
            and membership.get("truth") == job["truth"]
            and result.get("scope") == recovery.protocol()["scope"]
            and result.get("calibration_or_coverage_claim") is False,
            "reviewed fixed-truth G smoke metadata required",
        )
    return dict(
        job=job,
        target=target,
        spec=model,
        folder=folder,
        result=result,
        membership=membership,
        settings=settings,
        files=record["files"],
        receipt=receipt,
        receipt_sha256=pins[receipt],
        public_record={**record, "receipt_sha256": pins[receipt]},
        program_record=logical_record,
        technical_revalidation=(
            dict(
                original_controller_outcome="needs_review",
                original_receipt=receipt,
                original_receipt_sha256=pins[receipt],
                technical_review=logical_record["technical_review"],
                technical_review_sha256=logical_record["technical_review_sha256"],
                strict_proof=logical_record["strict_proof"],
                strict_proof_sha256=logical_record["strict_proof_sha256"],
            )
            if legacy and logical_record is not None
            else None
        ),
        events_path=name("event-results.json"),
        prediction_path=name("held-out-record-predictions.csv"),
    )


def _resolved_case(root, pins, admission, disposition):
    job = admission["gate"]["jobs"][0]
    folder, _ = fit.case_paths(root, job)
    name = lambda leaf: str((folder / leaf).relative_to(root))  # noqa: E731
    require(
        disposition.get("status") == "accepted_frozen_development_case0_resolution"
        and disposition.get("independent_checker") is True
        and disposition.get("reserved_outcomes") == "sealed"
        and disposition.get("original_job") == job
        and disposition.get("specification_freeze_sha256") == pins[data.FREEZE]
        and disposition.get("case0_outcome") in {"accepted_resolution", "accepted_unresolved_gap"}
        and disposition.get("primary_aggregate_available")
        is (disposition["case0_outcome"] == "accepted_resolution")
        and disposition.get("prediction_file") == name("held-out-record-predictions.csv")
        and disposition.get("prediction_sha256") == pins[name("held-out-record-predictions.csv")],
        "typed independently reviewed original check disposition required",
    )
    data._require(pins, disposition.get("files"))
    original = data._json(root, pins, name("result.json"))
    require(
        original.get("job") == job
        and original.get("status") == "needs_numerical_review"
        and original.get("confirmation_outcomes_parsed") is True
        and original.get("sampler_call_started") is False,
        "original zero-call precision failure must remain unchanged",
    )
    # The resolver owns the one trust contract: metadata admission, exact byte
    # inventory, acyclic independent cold replay and typed science anchors.
    # This compact API never integrates or opens native/posterior/NPZ arrays.
    require(
        disposition == data._json(root, pins, CASE0_REVIEW),
        "literal pinned typed science review required",
    )
    proof = numerical.case_artifacts(root, pins)
    require(
        proof.get("semantics_verified") is True
        and proof.get("proof_scope") == "independent_cold_replay_plus_fresh_complete_bytes"
        and proof.get("scientific_review") == CASE0_REVIEW
        and proof.get("scientific_review_sha256") == pins[CASE0_REVIEW]
        and proof.get("original_job") == job,
        "strict independently anchored numerical byte admission required",
    )
    data._require(pins, proof["review_files"])
    derived = None
    if disposition["case0_outcome"] == "accepted_resolution":
        path = numerical.CASE_OUTPUT + "/result.json"
        require(
            disposition.get("resolved_result") == path
            and disposition.get("resolved_result_sha256")
            == proof["files"].get(path)
            == pins.get(path)
            and proof.get("status") == fit.SUCCESS,
            "literal cold-replayed derived result required",
        )
        derived = data._json(root, pins, path)
        primary = derived.get("aggregates", {}).get("primary")
        require(
            derived.get("status") == fit.SUCCESS
            and derived.get("aggregates", {}).get("available") is True
            and isinstance(primary, dict)
            and _aggregate_view(primary) is not None,
            "resolved primary aggregate must contain an actual passing score",
        )
    else:
        require(
            disposition.get("resolved_result") is None
            and disposition.get("resolved_result_sha256") is None
            and proof.get("status") == numerical.UNRESOLVED,
            "unresolved score must retain null result and SHA",
        )
    target, model = admission["specs"][job["model_key"]]
    return dict(
        job=job,
        target=target,
        spec=model,
        folder=folder,
        result=original,
        membership=data._json(root, pins, name("membership.json")),
        settings=None,
        events_path=name("event-results.json"),
        prediction_path=disposition["prediction_file"],
        resolution=derived,
        disposition=disposition["case0_outcome"],
    )


def _case1_gap(root, pins, admission):
    """Retain the independently reviewed second check without promoting its scores."""
    job = admission["gate"]["jobs"][1]
    folder, raw = fit.case_paths(root, job)
    require(raw is None and job["order"] == 1, "original zero-call second check required")
    name = lambda leaf: str((folder / leaf).relative_to(root))  # noqa: E731
    review = data._json(root, pins, CASE1_REVIEW)
    receipt = LEGACY_CONTROL + f"/attempts/check/{job['id']}.json"
    plan_path = LEGACY_CONTROL + "/check-plan.json"
    authority_path = str(Path(fit.GATE).parent / "completion-v1/check/review-acceptance.json")
    expected = dict(
        status="accepted_frozen_development_runner_up_numerical_gap",
        independent_checker=True,
        original_job=job,
        case1_outcome="accepted_unresolved_gap",
        original_result_status="needs_numerical_review",
        original_worker_result_status="needs_numerical_review",
        controller_attempt_outcome="needs_review",
        primary_aggregate_available=False,
        without_crossing_aggregate_available=False,
        resolved_result=None,
        resolved_result_sha256=None,
        original_state_sha256=numerical.ORIGINAL_STATE_SHA,
        failed_continuation_state_sha256=FAILED_STATE_SHA,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        no_retuning=True,
        no_model_or_prior_change=True,
        no_observation_change=True,
        no_retry_or_additional_integration=True,
        completed_six_check_protocol_accepted=False,
        curvature_winner_claimed=False,
        equivalence_claimed=False,
        model_rejected=False,
    )
    require(
        all(
            key in review
            and (review[key] is value if isinstance(value, bool) else review[key] == value)
            for key, value in expected.items()
        )
        and all(
            type(review.get(key)) is int and review[key] == 0
            for key in ["sampler_calls_charged", "sampler_calls_started", "new_sampler_calls"]
        ),
        "typed independent zero-call runner-up numerical gap required",
    )
    data._require(pins, review.get("files"))
    data._require(review["files"], admission["files"])
    require(CASE1_REVIEW not in review["files"], "gap review must not pin itself")
    for key, path in [
        ("baseline_history", BASELINE),
        ("original_attempt_receipt", receipt),
        ("plan", plan_path),
        ("execution_authority_gate", authority_path),
        ("worker_gate", fit.GATE),
        ("original_result", name("result.json")),
        ("specification_freeze", data.FREEZE),
        ("case0_review", CASE0_REVIEW),
    ]:
        require(
            review.get(key) == path and review.get(key + "_sha256") == pins.get(path),
            "literal retained second-check lineage required: " + key,
        )
        data._require(review["files"], {path: pins[path]})
    prediction = name("held-out-record-predictions.csv")
    require(
        review.get("prediction_file") == prediction
        and review.get("prediction_sha256") == pins[prediction]
        and pins[BASELINE] == BASELINE_SHA,
        "unchanged second-check prediction pointer and frozen baseline required",
    )
    manifest_path = name("output-checksums.json")
    manifest = data._json(root, pins, manifest_path)
    leaves = {
        "job.json",
        "inputs.json",
        "membership.json",
        "result.json",
        "event-results.json",
        "direct-score-arrays.npz",
        "held-out-record-predictions.csv",
    }
    require(set(manifest) == leaves, "exact original failed check worker manifest required")
    worker = {name(leaf): digest for leaf, digest in manifest.items()}
    worker[manifest_path] = pins[manifest_path]
    spec, log, process = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    persistent = {
        **worker,
        **{
            str(path.relative_to(root)): pins[str(path.relative_to(root))]
            for path in [spec, log, process]
        },
    }
    require(
        review.get("original_attempt_persistent_files") == persistent
        and {p.name for p in folder.iterdir()} == leaves | {"output-checksums.json"}
        and all(p.resolve() == p and p.is_file() for p in folder.iterdir()),
        "all eleven original persistent regular artifacts required",
    )
    data._require(review["files"], persistent)
    record = data._json(root, pins, receipt)
    baseline = data._json(root, pins, BASELINE)
    require(
        record
        == dict(
            job_id=job["id"],
            phase="check",
            role="check_evaluate",
            cost=0,
            start_markers=0,
            outcome="needs_review",
            receipt=receipt,
            files=persistent,
            worker_files={},
        )
        and baseline.get("status") == "frozen_failed_development_continuation_history"
        and baseline.get("schema_version") == 1
        and baseline.get("original_state_sha256") == numerical.ORIGINAL_STATE_SHA
        and baseline.get("failed_continuation_state_sha256") == FAILED_STATE_SHA
        and baseline.get("calls_charged") == baseline.get("calls_started") == 0
        and baseline.get("reserved_outcomes") == "sealed"
        and baseline.get("private_state_bodies_copied") is False
        and baseline.get("failed_attempt") == {**record, "receipt_sha256": pins[receipt]}
        and baseline.get("unattempted_job_ids") == [j["id"] for j in admission["gate"]["jobs"][2:]],
        "unchanged public zero-call failed history required",
    )
    data._require(review["files"], baseline.get("source_references"))
    plan = data._json(root, pins, plan_path)
    authority = data._json(root, pins, authority_path)
    require(
        plan.get("phase") == "check"
        and plan.get("gate") == authority_path
        and plan.get("jobs") == authority.get("jobs") == admission["gate"]["jobs"][1:]
        and plan.get("files") == {**authority["files"], authority_path: pins[authority_path]},
        "original pre-gap plan and authority required",
    )
    data._require(review["files"], plan["files"])
    supervisor = data._json(root, pins, str(process.relative_to(root)))
    require(
        data._json(root, pins, str(spec.relative_to(root))) == job
        and supervisor.get("returncode") == 2
        and supervisor.get("reason") == "worker_exit"
        and supervisor.get("monitor_failures") == []
        and supervisor.get("cost") == supervisor.get("start_markers") == 0
        and supervisor.get("job_sha256") == pins[str(spec.relative_to(root))]
        and supervisor.get("plan_sha256") == pins[plan_path]
        and supervisor.get("authority_gate_sha256") == pins[authority_path]
        and supervisor.get("worker_gate_sha256") == pins[fit.GATE],
        "retained numerical failure process and zero starts required",
    )
    result = data._json(root, pins, name("result.json"))
    inputs = data._json(root, pins, name("inputs.json"))
    target, model = admission["specs"][job["model_key"]]
    require(
        result.get("job") == data._json(root, pins, name("job.json")) == job
        and result.get("status") == "needs_numerical_review"
        and result.get("sampler_call_started") is False
        and result.get("confirmation_outcomes_parsed") is True
        and result.get("reserved_outcomes") == "sealed"
        and all(
            result.get(key, {}).get("status") == "needs_numerical_review"
            and result[key].get("precision_passed") is False
            for key in ["aggregate", "aggregate_without_crossing_event"]
        )
        and type(result.get("prediction_rows")) is int
        and result["prediction_rows"] > 0
        and review.get("prediction_rows") == result["prediction_rows"]
        and review.get("prediction_rows_precision_passed") == result["prediction_rows"]
        and inputs.get("files") == admission["files"]
        and inputs.get("model_spec") == model
        and inputs.get("specification_freeze_sha256") == pins[data.FREEZE],
        "unchanged failed scores, frozen priors and model inputs required",
    )
    return dict(
        job=job,
        target=target,
        spec=model,
        folder=folder,
        result=result,
        membership=data._json(root, pins, name("membership.json")),
        settings=None,
        events_path=name("event-results.json"),
        prediction_path=prediction,
        resolution=None,
        disposition="accepted_unresolved_gap",
        gap_review=CASE1_REVIEW,
        public_record={**record, "receipt_sha256": pins[receipt]},
    )


def _journal_gap(root, pins, admission, job, logical, reviewed):
    case = _ordinary_case(root, pins, admission, job, "check", reviewed, failed=True)
    review_path = CONTROL + f"/reviews/check/{job['id']}/review-acceptance.json"
    disposition_path = CONTROL + f"/dispositions/check/{job['id']}.json"
    review = data._json(root, pins, review_path)
    disposition = data._json(root, pins, disposition_path)
    require(
        logical
        == dict(
            job_id=job["id"],
            job=job,
            outcome="accepted_unresolved_gap",
            review=review_path,
            review_sha256=pins[review_path],
            primary_aggregate_available=False,
            disposition=disposition_path,
            disposition_sha256=pins[disposition_path],
        )
        and disposition
        == dict(
            job=job,
            outcome="accepted_unresolved_gap",
            attempt=case["receipt"],
            attempt_sha256=case["receipt_sha256"],
            review=review_path,
            review_sha256=pins[review_path],
        )
        and review.get("status") == "accepted_frozen_development_check_numerical_gap"
        and review.get("independent_checker") is True
        and review.get("original_job") == job
        and review.get("failure_kind") == "numerical_precision_only"
        and review.get("fully_computed_same_source") is True
        and review.get("primary_aggregate_available") is False
        and review.get("without_crossing_aggregate_available") is False
        and review.get("resolved_result") is None
        and review.get("resolved_result_sha256") is None
        and review.get("specification_freeze_sha256") == pins[data.FREEZE]
        and review.get("attempt") == case["receipt"]
        and review.get("attempt_sha256") == case["receipt_sha256"]
        and review.get("prediction_file") == case["prediction_path"]
        and review.get("prediction_sha256") == pins[case["prediction_path"]]
        and type(case["result"].get("prediction_rows")) is int
        and case["result"]["prediction_rows"] > 0
        and review.get("prediction_rows_precision_passed") == case["result"]["prediction_rows"],
        "individually reviewed immutable CHECK-only gap disposition required",
    )
    require(review_path not in review["files"], "gap review must not pin itself")
    authority = data._json(root, pins, AUTHORITY["check"])
    needed = {
        **authority["files"],
        AUTHORITY["check"]: pins[AUTHORITY["check"]],
        **case["files"],
        case["receipt"]: case["receipt_sha256"],
    }
    data._require(review["files"], needed)
    data._require(pins, review["files"])
    data._require(
        reviewed, {review_path: pins[review_path], disposition_path: pins[disposition_path]}
    )
    require(
        case["result"].get("sampler_call_started") is False
        and all(
            case["result"].get(k, {}).get("precision_passed") is False
            for k in ["aggregate", "aggregate_without_crossing_event"]
        ),
        "failed aggregates must remain unavailable",
    )
    return {
        **case,
        "resolution": None,
        "disposition": "accepted_unresolved_gap",
        "gap_review": review_path,
    }


def _inherited_ledger_references(root, pins):
    """Allow only the freeze's 12 immutable ledger hashes; never parse their bodies."""
    require(
        sha256(data._path(root, data.FREEZE)) == pins[data.FREEZE],
        "pinned specification freeze required before ledger admission",
    )
    freeze = data._json(root, pins, data.FREEZE)
    inherited = {p: h for p, h in freeze.get("files", {}).items() if p.startswith("context/")}
    actual = {p: h for p, h in pins.items() if "context/" in p}
    live = {
        old.PRIVATE_STATE,
        "context/runs/arrival-model-fitting-v1/development-completion-state.json",
    }
    require(
        len(inherited) == 12
        and all(p.endswith(".json") for p in inherited)
        and not live.intersection(inherited)
        and actual == inherited,
        "exact12 inherited immutable ledger SHA references required; no live STATE",
    )


def verify_report_sources(root):
    root = root.resolve()
    gate = json.loads(data._path(root, GATE).read_text())
    needed = set(CONSUMED) | {
        data.FREEZE,
        data.MS5_REVIEW,
        data.CHECK_REVIEW,
        old.SMOKE_REVIEW,
        fit.GATE,
        fit.FULL_GATE,
        recovery.GATE,
        CASE0_REVIEW,
        CASE1_REVIEW,
        BASELINE,
        AUTHORITY["check"],
        SUMMARIES["check"],
        technical.BASELINE,
        *(technical.authority_path(phase) for phase in technical.PHASES),
        *(str(technical.summary_path(root, phase).relative_to(root)) for phase in technical.PHASES),
    }
    require(
        gate.get("status") == "accepted_frozen_full_development_fits"
        and gate.get("independent_checker") is True
        and gate.get("confirmation_outcomes_parsed") is True
        and gate.get("development_check_previously_inspected") is True
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("reserved_outcomes_parsed") is False
        and needed <= set(gate.get("files", {}))
        and old.PRIVATE_STATE not in gate["files"]
        and "context/runs/arrival-model-fitting-v1/development-completion-state.json"
        not in gate["files"],
        "complete accepted completion closure required before result tables",
    )
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    _inherited_ledger_references(root, pins)
    data._unchanged(root, pins)
    full, check = [fit.verify_gate(root, role) for role in ["full_development", "check_evaluate"]]
    smoke = recovery.verify_gate(root)
    for admission in [full, check, smoke]:
        data._require(pins, admission["files"])
    freeze = full["freeze"]
    require(
        check["freeze"] == smoke["freeze"] == freeze
        and gate.get("specification_freeze") == data.FREEZE
        and gate.get("specification_freeze_sha256") == pins[data.FREEZE],
        "same scientific freeze required",
    )
    reviews = [data._json(root, pins, name) for name in [data.CHECK_REVIEW, old.SMOKE_REVIEW]]
    for review in reviews:
        data._require(pins, review.get("files"))
    require(
        reviews[0].get("completed_once") is True
        and reviews[0].get("status") == "accepted_frozen_arrival_development_check"
        and reviews[0].get("independent_checker") is True
        and reviews[0].get("no_retuning") is True
        and reviews[0].get("case0_review") == CASE0_REVIEW
        and reviews[0].get("case0_review_sha256") == pins[CASE0_REVIEW],
        "completed once-only check with explicit numerical disposition required",
    )
    require(
        reviews[1].get("status") == "accepted_frozen_full_development_design_checks"
        and reviews[1].get("independent_checker") is True
        and reviews[1].get("specification_freeze_sha256") == pins[data.FREEZE],
        "accepted same-freeze G6 required",
    )
    jobs = {
        "check": check["gate"]["jobs"][2:],
        "full_design_recovery": smoke["gate"]["jobs"],
        "full_development": full["gate"]["jobs"],
    }
    summaries, programs = {}, {}
    for phase in PHASES:
        if phase in technical.PHASES:
            program = technical.read_program_metadata(root, phase)
            data._require(pins, program["files"])
            summary_name = str(technical.summary_path(root, phase).relative_to(root))
            summary = data._json(root, pins, summary_name)
            require(
                program.get("phase") == phase
                and program.get("complete") is True
                and program.get("jobs") == jobs[phase]
                and program.get("dispatch_jobs")
                == (jobs[phase][1:] if phase == "full_design_recovery" else jobs[phase])
                and program.get("calls_charged")
                == program.get("calls_started")
                == {"full_design_recovery": 6, "full_development": 9}[phase]
                and program.get("authority_gate") == technical.authority_path(phase)
                and pins.get(summary_name) == program["files"].get(summary_name)
                and summary == technical.summary_value(program),
                "complete public technical continuation metadata required",
            )
            programs[phase], summaries[phase] = program, summary
            continue
        authority = data._json(root, pins, AUTHORITY[phase])
        summary = data._json(root, pins, SUMMARIES[phase])
        kernel = {
            "check": fit.GATE,
            "full_design_recovery": recovery.GATE,
            "full_development": fit.FULL_GATE,
        }[phase]
        require(
            authority.get("status") == "accepted_frozen_arrival_development_journal_execution"
            and authority.get("independent_checker") is True
            and authority.get("phase") == phase
            and authority.get("no_retuning") is True
            and authority.get("reserved_outcomes") == "sealed"
            and authority.get("max_sampler_call_slots") == 9
            and authority.get("worker_gate") == kernel
            and authority.get("worker_gate_sha256") == pins[kernel]
            and authority.get("jobs") == summary.get("jobs") == jobs[phase]
            and summary.get("case0_outcome")
            == data._json(root, pins, CASE0_REVIEW).get("case0_outcome")
            and summary.get("case1_outcome") == "accepted_unresolved_gap"
            and summary.get("plan_sha256") == pins[CONTROL + "/plans/" + phase + ".json"]
            and summary.get("status") == "computed_pending_independent_review"
            and summary.get("specification_freeze_sha256") == pins[data.FREEZE]
            and summary.get("authority_gate") == AUTHORITY[phase]
            and summary.get("authority_gate_sha256") == pins[AUTHORITY[phase]]
            and summary.get("worker_gate") == kernel
            and summary.get("worker_gate_sha256") == pins[kernel]
            and summary.get("calls_charged")
            == summary.get("calls_started")
            == {"check": 0, "full_design_recovery": 6, "full_development": 9}[phase]
            and [r.get("job_id") for r in summary.get("attempt_records", [])]
            == [j["id"] for j in jobs[phase]],
            "complete exact-cost reviewed continuation chronology required",
        )
        data._require(pins, authority.get("files"))
        summaries[phase] = summary
    require(
        len(jobs["full_design_recovery"]) == 6 and len(jobs["full_development"]) == 3,
        "six smokes and three selected fits required",
    )
    selected = {
        f"{target}:{specs[0]['kind']}:selected" for target, specs in freeze["models"].items()
    }
    require(
        {j["model_key"] for j in jobs["full_development"]} == selected,
        "selected-only full fits required",
    )
    smokes = [
        _ordinary_case(
            root,
            pins,
            smoke,
            job,
            "full_design_recovery",
            reviews[1]["files"],
            program=programs["full_design_recovery"],
        )
        for job in jobs["full_design_recovery"]
    ]
    require(
        [case["program_record"] for case in smokes]
        == summaries["full_design_recovery"]["accepted_records"]
        and summaries["full_design_recovery"]["attempt_records"]
        == summaries["full_design_recovery"]["accepted_records"][1:]
        and sum(case["program_record"]["cost"] for case in smokes) == 6
        and sum(case["program_record"]["start_markers"] for case in smokes) == 6,
        "all six exact reviewed smoke process/attempt proofs required",
    )
    cases = [
        _ordinary_case(
            root,
            pins,
            full,
            j,
            "full_development",
            gate["files"],
            program=programs["full_development"],
        )
        for j in jobs["full_development"]
    ]
    require(
        [case["public_record"] for case in cases]
        == summaries["full_development"]["accepted_records"]
        == summaries["full_development"]["attempt_records"],
        "full phase summary must preserve exact public attempts",
    )
    descriptors = gate.get("accepted", [])
    require(len(descriptors) == 3, "three literal final fit descriptors required")
    for case, descriptor in zip(cases, descriptors, strict=True):
        require(
            descriptor.get("job") == case["job"]
            and descriptor.get("files") == case["files"]
            and descriptor.get("receipt") == case["receipt"]
            and descriptor.get("receipt_sha256") == case["receipt_sha256"],
            "exact final selected fit descriptor required",
        )
    disposition = data._json(root, pins, CASE0_REVIEW)
    checks = [_resolved_case(root, pins, check, disposition), _case1_gap(root, pins, check)]
    baseline = [
        dict(
            job_id=case["job"]["id"],
            job=case["job"],
            outcome=outcome,
            review=path,
            review_sha256=pins[path],
            primary_aggregate_available=available,
        )
        for case, path, outcome, available in [
            (checks[0], CASE0_REVIEW, "accepted_resolution", True),
            (checks[1], CASE1_REVIEW, "accepted_unresolved_gap", False),
        ]
    ]
    require(
        checks[0]["disposition"] == "accepted_resolution", "original reviewed resolution retained"
    )
    logical = summaries["check"].get("logical_check_dispositions")
    require(
        isinstance(logical, list)
        and logical[:2] == baseline
        and all(s.get("logical_check_dispositions") == logical for s in summaries.values()),
        "all phase summaries must preserve ordered baseline and CHECK gap dispositions",
    )
    extra = {entry["job_id"]: entry for entry in logical[2:]}
    require(len(extra) == len(logical) - 2, "unique explicitly reviewed gap slots required")
    passed, gaps = [], []
    for job, record in zip(jobs["check"], summaries["check"]["attempt_records"], strict=True):
        if record.get("outcome") == "accepted":
            case = _ordinary_case(root, pins, check, job, "check", reviews[0]["files"])
            passed.append(case["public_record"])
        else:
            require(job["id"] in extra, "failed check requires its own scientific disposition")
            case = _journal_gap(root, pins, check, job, extra[job["id"]], reviews[0]["files"])
            gaps.append(extra[job["id"]])
        require(case["public_record"] == record, "exact journal attempt must remain immutable")
        checks.append(case)
    require(
        passed == summaries["check"]["accepted_records"] and logical == baseline + gaps,
        "passed attempts and separately reviewed gaps must partition all check slots",
    )
    require(
        len(checks) == len(check["specs"]) == 6
        and {c["job"]["model_key"] for c in checks} == set(check["specs"])
        and [c["job"] for c in checks] == check["gate"]["jobs"],
        "all six original frozen check models must remain represented",
    )
    sensitivity = old._sensitivity_history(root, pins)
    data._unchanged(root, pins)
    return dict(
        root=root,
        files=pins,
        freeze=freeze,
        full=cases,
        checks=checks,
        smokes=smokes,
        sensitivity=sensitivity,
        technical_completion=dict(
            baseline_review=technical.BASELINE,
            baseline_review_sha256=pins[technical.BASELINE],
            original_G0_controller_outcome="needs_review",
            G0_logical_outcome="accepted_under_strict_revalidation",
            G0_sampler_calls=1,
            no_additional_G0_sampling=True,
        ),
    )


def _aggregate_view(value):
    if value is None or value.get("precision_passed") is not True:
        return None
    bound = value.get("mcse_triangle_bound")
    require(
        value.get("status") == fit.SUCCESS
        and type(value.get("equal_event_score")) in {int, float}
        and math.isfinite(value["equal_event_score"])
        and type(bound) in {int, float}
        and math.isfinite(bound)
        and bound >= 0,
        "finite saved conservative MCSE estimate required",
    )
    return {
        **value,
        "source_status": value["status"],
        "status": "computed_pending_review",
        "mcse_equal_event_score": bound,
        "mcse_kind": "conservative_sum_of_estimated_MCSEs",
    }


def render_markdown(summary):
    text = old.render_markdown(summary)
    note = (
        "The first NCEI check retained an original numerical precision failure. "
        "Its predictions remain unchanged. A separate, reviewed integration of the same "
        "frozen predictive density supplies a score only when its numerical checks pass. "
        "The linear NCEI runner-up has a separately reviewed numerical gap: both aggregate "
        "score views remain unavailable while its original marginal predictions are retained. "
        "This gap establishes neither model rejection nor superiority or equivalence. "
        "Unresolved scores remain unavailable. The first recovery smoke retains its original "
        "controller failure and was independently accepted under strict revalidation of the "
        "same saved computation; no additional sampler call was made. "
        "Mixed-method aggregate uncertainty sums the "
        "shared-draw MCSE estimate and the weighted integration MCSE estimate, without "
        "assuming independence; this is not a finite-bias bound. Model selection stays frozen."
    )
    text = text.replace("\n## ", "\n" + note + "\n\n## ", 1)
    for lane in summary["lanes"]:
        for check in lane["checks"]:
            for key in ["aggregate", "aggregate_without_crossing_event"]:
                value = check[key]
                if value and value.get("mcse_kind") == "conservative_sum_of_estimated_MCSEs":
                    before = old._score(value)
                    text = text.replace(
                        before, before.removesuffix(" MCSE") + " (sum of MCSE estimates)"
                    )
    return text


def report(root: Path, output: Path):
    root, output = root.resolve(), Path(output).absolute()
    require(
        output.resolve() == output and output.is_relative_to(root) and not output.exists(),
        "new literal report output required",
    )
    bundle = verify_report_sources(root)
    for case in bundle["full"]:
        case["summary"] = data._json(
            root, bundle["files"], str((case["folder"] / "summary.json").relative_to(root))
        )
        for key in old.TABLES:
            old._match_table(
                case["folder"] / (key.replace("_", "-") + ".csv"), case["summary"][key]
            )
    for case in bundle["checks"]:
        case["events"] = copy.deepcopy(data._json(root, bundle["files"], case["events_path"]))
        case["predictions"] = read_rows(data._path(root, case["prediction_path"]))
        if "disposition" in case:
            derived = case["resolution"]
            aggregates = derived["aggregates"] if derived else {}
            case["result"] = {
                **case["result"],
                "aggregate": _aggregate_view(aggregates.get("primary")),
                "aggregate_without_crossing_event": _aggregate_view(
                    aggregates.get("without_crossing_event")
                ),
            }
            case["events"]["aggregate"] = case["result"]["aggregate"]
            case["events"]["aggregate_without_crossing_event"] = case["result"][
                "aggregate_without_crossing_event"
            ]
    summary = old.report_tables(bundle)
    summary["technical_completion"] = bundle["technical_completion"]
    summary["numerical_resolution"] = dict(
        review=CASE0_REVIEW,
        review_sha256=bundle["files"][CASE0_REVIEW],
        original_failure_retained=True,
        unchanged_predictions=True,
        method="reviewed_same_estimand_integration_or_explicit_unresolved_gap",
    )
    summary["numerical_check_gaps"] = [
        dict(
            job=case["job"],
            outcome=case["disposition"],
            review=case["gap_review"],
            review_sha256=bundle["files"][case["gap_review"]],
            prediction_file=case["prediction_path"],
            prediction_sha256=bundle["files"][case["prediction_path"]],
            primary_aggregate_available=False,
            without_crossing_aggregate_available=False,
        )
        for case in bundle["checks"]
        if "gap_review" in case
    ]
    text = render_markdown(summary)
    json.dumps(summary, allow_nan=False)
    data._unchanged(root, bundle["files"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=".completed-development-report-"
    ) as directory:
        stage = Path(directory)
        (stage / "findings.md").write_text(text)
        write_json(stage / "summary.json", summary)
        write_json(
            stage / "inputs.json",
            dict(
                files=bundle["files"],
                review=GATE,
                specification_freeze_sha256=bundle["files"][data.FREEZE],
                method="accepted_saved_tables_only_no_new_scores_or_simulation",
            ),
        )
        write_json(
            stage / "output-checksums.json",
            {name: sha256(stage / name) for name in ["findings.md", "summary.json", "inputs.json"]},
        )
        data._unchanged(root, bundle["files"])
        require(not output.exists(), "output appeared before publication")
        stage.rename(output)
