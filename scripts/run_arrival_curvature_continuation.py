"""Conserve the curvature ledger while completing the remaining original sequence folds."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_path_sampling import GATE as PATH_GATE  # noqa: E402
from analysis.arrival.model_curvature_path_sampling import OUTPUT as PATH_OUTPUT  # noqa: E402
from analysis.arrival.model_curvature_path_sampling import path_jobs  # noqa: E402
from analysis.arrival.model_curvature_resolution_io import REVIEW as PATH_REVIEW  # noqa: E402
from analysis.arrival.model_curvature_resolution_io import verified_path  # noqa: E402
from analysis.arrival.model_curvature_sequence import GATE as WORKER_GATE  # noqa: E402
from analysis.arrival.model_curvature_sequence import verify_gate  # noqa: E402
from scripts.run_arrival_curvature_path import (
    attempt_files as path_attempt_files,
)
from scripts.run_arrival_curvature_path import (  # noqa: E402
    validate_aggregates,
    validate_timings,
)
from scripts.run_arrival_curvature_pilot import bindings  # noqa: E402
from scripts.run_arrival_curvature_sequences import (
    DESIGN as ORIGINAL_DESIGN,
)
from scripts.run_arrival_curvature_sequences import (  # noqa: E402
    MAX_CACHE,
    MAX_CALLS,
    MAX_GLOBAL,
    MAX_JOB,
    MAX_LOCAL,
    MIB,
    OUTPUT,
    RESERVE,
    STATE,
    STORE,
    byte_count,
    case_artifacts,
    make_design,
    parent_floors,
    quota_failure,
    verify_rehearsal,
)
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

SELF = "scripts/run_arrival_curvature_continuation.py"
CONTINUATION = OUTPUT + "/continuation-v1"
DESIGN = "artifacts/models/arrival-timing/mean-curvature-continuation-design-v1"
GATE = DESIGN + "/review-acceptance.json"
DERIVED = PATH_OUTPUT + "/resolved-fold-v1"
DERIVED_REVIEW = DERIVED + "/review-acceptance.json"
REHEARSAL = CONTINUATION + "/rehearsal-review-acceptance.json"


def resources():
    return {
        "global_max_bytes": MAX_GLOBAL,
        "local_max_bytes": MAX_LOCAL,
        "cache_max_bytes": MAX_CACHE,
        "job_max_bytes": MAX_JOB,
        "next_invocation_reserve_bytes": RESERVE,
        "per_file_bytes": 64 * MIB,
        "whole_fold_seconds": 1200,
        "concurrency": 1,
        "cores": 2,
        "automatic_retries": 0,
        "max_folds_per_invocation": 3,
        "max_sampler_call_slots": 248,
        "inherited_charged_slots": 38,
    }


def working_bytes(root, parents):
    return byte_count(
        *parents,
        root / OUTPUT,
        root / STORE,
        root / ORIGINAL_DESIGN,
        (root / PATH_GATE).parent,
        root / DESIGN,
    )


def storage_failure(root, parents, current=None):
    return quota_failure(root, parents, current) or (
        "global_storage_including_continuation_designs"
        if working_bytes(root, parents) > MAX_GLOBAL
        else None
    )


def admit_continuation(root):
    """Admit every source and resolution before any new outcome-table loading."""
    gate = json.loads((root / GATE).read_text())
    required = {
        SELF,
        WORKER_GATE,
        OUTPUT + "/plan.json",
        PATH_REVIEW,
        DERIVED_REVIEW,
        "scripts/run_arrival_curvature_path.py",
        "analysis/arrival/model_curvature_resolution_io.py",
    }
    if (
        gate.get("status") != "accepted_curvature_continuation_rehearsal"
        or gate.get("independent_checker") is not True
        or gate.get("resources") != resources()
        or gate.get("path_bindings")
        != bindings(root, root / CONTINUATION, root / STORE, root / STATE)
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not required.issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independently accepted continuation design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for p, h in pins.items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("continuation source or accepted evidence changed")

    def require(entries):
        if not entries or any(pins.get(p) != h for p, h in entries.items()):
            raise ValueError("complete reviewed reference closure required before outcome loading")

    require(verified_path(root))
    review = json.loads((root / DERIVED_REVIEW).read_text())
    if (
        review.get("status") != "accepted_same_model_curvature_fold_resolution"
        or review.get("independent_checker") is not True
        or review.get("confirmation_outcomes_parsed") is not False
        or review.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("complete independently accepted same-model fold resolution required")
    require(review.get("files", {}))
    oldplan = json.loads((root / OUTPUT / "plan.json").read_text())
    require(oldplan.get("files", {}))
    worker_pins = verify_gate(root, oldplan["cases"][0])
    require(worker_pins)
    if worker_pins != oldplan["files"]:
        raise ValueError("original worker source proof identity changed")
    result_path = DERIVED + "/result.json"
    prediction = OUTPUT + "/jobs/fold-002/held-out-record-predictions.csv"
    if (
        result_path not in pins
        or prediction not in pins
        or review.get("derived_result") != result_path
        or review.get("derived_result_sha256") != pins[result_path]
    ):
        raise ValueError("literal reviewed resolution and original prediction paths required")
    result = json.loads((root / result_path).read_text())
    failed_source = OUTPUT + "/jobs/fold-002/result.json"
    if failed_source not in pins:
        raise ValueError("original failed source must remain reviewed")
    failed = json.loads((root / failed_source).read_text())
    if (
        result.get("job") != oldplan["cases"][2]
        or result.get("status") != "computed_pending_review"
        or result.get("score_precision_passed") is not True
        or result.get("prediction_precision_passed") is not True
        or result.get("training_only_predictions") != prediction
        or result.get("training_only_predictions_sha256") != pins[prediction]
        or result.get("observation_measure") != "native_minutes_Jacobian_already_applied_once"
        or result.get("source_result") != failed_source
        or result.get("source_result_sha256") != pins[failed_source]
        or result.get("retained_direct_bridge_status") != "precision_failure"
        or failed.get("status") != "precision_failure"
        or failed.get("job") != oldplan["cases"][2]
    ):
        raise ValueError("same original job, native score and training-only predictions required")
    resolutions = {
        "fold-002": {
            "receipt": DERIVED_REVIEW,
            "receipt_sha256": pins[DERIVED_REVIEW],
            "result": result_path,
            "result_sha256": pins[result_path],
            "prediction": prediction,
            "prediction_sha256": pins[prediction],
        }
    }
    if gate.get("resolutions") != resolutions or gate.get("original_plan_sha256") != sha256(
        root / OUTPUT / "plan.json"
    ):
        raise ValueError("frozen explicit resolution registry and original plan required")
    cases, memberships = make_design(root)
    if (
        cases != oldplan["cases"]
        or memberships != oldplan["memberships"]
        or len(cases) != 29
        or sum(memberships[c["id"]]["charged_call_slots"] for c in cases[3:]) != 56
        or gate.get("remaining_cases") != cases[3:]
    ):
        raise ValueError("unchanged original29fold33event design and26remaining cases required")
    parents = parent_floors(root, gate)
    return {
        "gate": gate,
        "files": pins,
        "oldplan": oldplan,
        "worker_pins": worker_pins,
        "cases": cases,
        "memberships": memberships,
        "resolutions": resolutions,
        "parents": parents,
    }


def validate_logical_prefix(state, cases, memberships, resolutions):
    """Logical completion includes reviewed resolutions; inherited38calls never reset."""
    if (
        len(cases) < 3
        or set(resolutions) != {cases[2]["id"]}
        or type(state.get("next_fold")) is not int
        or not 3 <= state["next_fold"] <= len(cases)
        or state.get("continuation", {}).get("resolutions") != resolutions
    ):
        raise ValueError("complete fixed resolved-fold logical prefix required")
    expected = [c["id"] for c in cases[: state["next_fold"]] if c["id"] not in resolutions]
    if [a.get("case_id") for a in state.get("accepted", [])] != expected:
        raise ValueError("direct folds plus reviewed resolution must conserve logical prefix")
    attempts = state["continuation"].get("attempts", [])
    if [a.get("case_id") for a in attempts] != expected[2:]:
        raise ValueError("complete ordered new-attempt ledger required")
    for a, accepted in zip(attempts, state["accepted"][2:], strict=True):
        cost = memberships[a["case_id"]]["charged_call_slots"]
        if (
            a.get("outcome") != "accepted"
            or a.get("cost") != cost
            or a.get("started") != cost
            or a.get("receipt") != accepted.get("receipt")
            or a.get("receipt_sha256") != accepted.get("receipt_sha256")
        ):
            raise ValueError("all charged and started slots must match accepted memberships")
    charged = 38 + sum(a["cost"] for a in attempts)
    started = 38 + sum(a["started"] for a in attempts)
    if (
        state.get("calls_charged") != charged
        or state.get("calls_started") != started
        or charged > 248
    ):
        raise ValueError("all38inherited and every new sampler slot must be conserved")


def validate_inherited_path(root, state, pins):
    path = state.get("path_amendment", {})
    if (
        path.get("next_node") != 32
        or len(path.get("attempts", [])) != 32
        or path.get("plan_sha256") != sha256(root / PATH_OUTPUT / "plan.json")
        or path.get("final_summary_sha256") != pins.get(PATH_OUTPUT + "/run-summary.json")
    ):
        raise ValueError("all32 inherited path nodes and immutable summary required")
    validate_timings(root, path)
    validate_aggregates(root, path)
    for job, attempt in zip(path_jobs(), path["attempts"], strict=True):
        manifest = root / PATH_OUTPUT / "jobs" / job["id"] / "attempt-evidence.json"
        if (
            attempt.get("job") != job
            or attempt.get("outcome") != "accepted"
            or attempt.get("files") != path_attempt_files(root, job, complete=True)
            or attempt.get("receipt") != str(manifest.relative_to(root))
            or attempt.get("receipt_sha256") != sha256(manifest)
            or pins.get(str(manifest.relative_to(root))) != sha256(manifest)
        ):
            raise ValueError("original complete path attempt ledger changed")


def validate_raw_inventory(root, state, pins):
    raw = root / STORE
    known = {p for p in pins if p.startswith(STORE + "/") and not p.startswith(STORE + "/cache/")}
    for entry in state["accepted"]:
        known.update(p for p in entry["files"] if p.startswith(STORE + "/"))
    actual = {
        str(p.relative_to(root))
        for p in raw.rglob("*")
        if p.is_file() and not p.is_relative_to(raw / "cache")
    }
    expected_dirs = {f"fold-{j:03d}" for j in range(state["next_fold"])} | {
        "cache",
        "resolution-fold-002-path-v1",
    }
    if (
        actual != known
        or any(p.is_file() for p in raw.iterdir())
        or any(p.name not in expected_dirs for p in raw.iterdir() if p.is_dir())
    ):
        raise ValueError("unexpected raw file, partial or omitted original evidence")


def validate_first_new_fold(root, state):
    path = root / REHEARSAL
    if not path.is_file():
        raise ValueError("independently reviewed first continuation fold required")
    review = json.loads(path.read_text())
    first = state["accepted"][2]
    required = {
        **first["files"],
        first["receipt"]: first["receipt_sha256"],
        CONTINUATION + "/plan.json": sha256(root / CONTINUATION / "plan.json"),
    }
    if (
        review.get("status") != "accepted_first_curvature_continuation_fold"
        or review.get("independent_checker") is not True
        or any(review.get("files", {}).get(p) != h for p, h in required.items())
    ):
        raise ValueError("complete independently reviewed first continuation fold proof required")
    for p, h in review["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("continuation rehearsal proof changed")
    return sha256(path)


def retained_files(root, attempt, raw, spec):
    paths = {
        p
        for folder in [attempt, raw]
        for p in folder.rglob("*")
        if p.is_file() and p.name != "attempt-evidence.json"
    }
    paths.update(
        p
        for p in [spec, attempt.with_suffix(".log"), attempt.with_suffix(".supervisor.json")]
        if p.is_file()
    )
    return {str(p.relative_to(root)): sha256(p) for p in paths}


def run(root, *, resume=False, max_folds=1):
    root = root.resolve()
    if type(max_folds) is not int or not 1 <= max_folds <= 3 or not resume and max_folds != 1:
        raise ValueError("initial invocation is one metadata-defined fold; later batches at most3")
    os.environ.update(
        PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={root / STORE}/cache/pytensor",
        NUMBA_CACHE_DIR=str(root / STORE / "cache/numba"),
        MPLCONFIGDIR=str(root / STORE / "cache/matplotlib"),
    )
    design = admit_continuation(root)
    pins = design["files"]
    cases = design["cases"]
    memberships = design["memberships"]
    parents = design["parents"]
    worker_pins = design["worker_pins"]
    output = root / CONTINUATION
    state_path = root / STATE
    state = json.loads(state_path.read_text())
    if state.get("plan_sha256") != sha256(root / OUTPUT / "plan.json"):
        raise ValueError("original parent plan identity changed")
    if verify_rehearsal(root, state) != state.get("rehearsal_sha256"):
        raise ValueError("original first-fold review identity changed")
    validate_inherited_path(root, state, pins)
    for case, accepted in zip(cases[:2], state.get("accepted", [])[:2], strict=True):
        case_artifacts(root, case, memberships[case["id"]], worker_pins, accepted)
    lease = root / OUTPUT / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = root / OUTPUT / "STOP"

    def monitor():
        while not ended.wait(0.1):
            reason = storage_failure(root, parents, current[0])
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    try:
        expected = {
            "files": pins,
            "original_worker_files": worker_pins,
            "cases": cases,
            "original_plan_sha256": sha256(root / OUTPUT / "plan.json"),
            "resolutions": design["resolutions"],
            "resources": resources(),
            "canonical_state_path": STATE,
            "path_bindings": bindings(root, output, root / STORE, state_path),
            "inherited_slots": 38,
            "remaining_nominal_slots": 56,
            "global_call_ceiling": 248,
        }
        if resume:
            plan = json.loads((output / "plan.json").read_text())
            if (
                any(plan.get(k) != v for k, v in expected.items())
                or state.get("status") not in {"cv_checkpoint", "cv_computations_complete"}
                or state.get("current") is not None
                or state.get("continuation", {}).get("plan_sha256") != sha256(output / "plan.json")
            ):
                raise ValueError(
                    "changed or failed continuation ledger requires reviewed reconciliation"
                )
            validate_logical_prefix(state, cases, memberships, design["resolutions"])
        else:
            if (
                output.exists()
                or "continuation" in state
                or state.get("status") != "path_computations_complete"
                or state.get("calls_charged") != 38
                or state.get("calls_started") != 38
                or state.get("next_fold") != 2
                or state.get("current") is not None
                or len(state.get("accepted", [])) != 2
            ):
                raise ValueError(
                    "exact38slot completed-path parent required; no copied/reset allocation"
                )
            output.mkdir(parents=True)
            plan = {
                **expected,
                "source_git_sha": git_sha(root),
                "scope": "same original candidate/cohort; one reviewed numerical resolution",
            }
            write_json(output / "plan.json", plan)
            state["continuation"] = {
                "plan_sha256": sha256(output / "plan.json"),
                "resolutions": design["resolutions"],
                "attempts": [],
            }
            state.update(next_fold=3, status="cv_checkpoint")
            atomic_state(state_path, state)
        for case, accepted in zip(
            [c for c in cases[: state["next_fold"]] if c["id"] not in design["resolutions"]],
            state["accepted"],
            strict=True,
        ):
            case_artifacts(root, case, memberships[case["id"]], worker_pins, accepted)
            if case["id"] not in {"fold-000", "fold-001"}:
                supervisor = json.loads(
                    (root / OUTPUT / "jobs" / case["id"])
                    .with_suffix(".supervisor.json")
                    .read_text()
                )
                if (
                    supervisor.get("continuation_plan_sha256")
                    != state["continuation"]["plan_sha256"]
                ):
                    raise ValueError("new-fold supervisor amendment identity changed")
        validate_raw_inventory(root, state, pins)
        if storage_failure(root, parents):
            raise ValueError("retained working-store budget exceeded")
        if state["status"] == "cv_computations_complete":
            if validate_first_new_fold(root, state) != state["continuation"].get(
                "rehearsal_sha256"
            ):
                raise ValueError("completed first continuation review identity changed")
            if sha256(output / "run-summary.json") != state["continuation"].get(
                "final_summary_sha256"
            ):
                raise ValueError("completed continuation summary changed")
            return
        limit_worker_file_size(64 * MIB)
        watcher.start()
        for _ in range(max_folds):
            parent_floors(root, design["gate"])
            if state["next_fold"] >= 4:
                identity = validate_first_new_fold(root, state)
                if state["continuation"].get("rehearsal_sha256") not in {None, identity}:
                    raise ValueError("first continuation review changed")
                state["continuation"]["rehearsal_sha256"] = identity
            validate_raw_inventory(root, state, pins)
            if state["next_fold"] == len(cases):
                break
            case = cases[state["next_fold"]]
            member = memberships[case["id"]]
            cost = member["charged_call_slots"]
            if (
                stop.exists()
                or failures
                or storage_failure(root, parents)
                or state["calls_charged"] + cost > MAX_CALLS
                or byte_count(root / OUTPUT, root / STORE) + RESERVE > MAX_LOCAL
                or working_bytes(root, parents) + RESERVE > MAX_GLOBAL
            ):
                state["status"] = "cv_stop_or_budget_failure"
                break
            if any(not (root / p).is_file() or sha256(root / p) != h for p, h in pins.items()):
                raise ValueError("continuation accepted source drift")
            folder = root / OUTPUT / "jobs" / case["id"]
            raw = root / STORE / case["id"]
            spec = folder.with_name(case["id"] + "-spec.json")
            if any(
                p.exists()
                for p in [
                    folder,
                    raw,
                    spec,
                    folder.with_suffix(".log"),
                    folder.with_suffix(".supervisor.json"),
                ]
            ):
                raise ValueError("original attempt retained; no overwrite")
            write_json(spec, case)
            state.update(
                current=case["id"], status="cv_running", calls_charged=state["calls_charged"] + cost
            )
            atomic_state(state_path, state)
            current[0] = folder
            outcome = "runtime_failure"
            receipt = {}
            dispatch_started = time.monotonic()
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/fit_arrival_curvature_sequence.py"),
                        "--job",
                        str(spec),
                        "--output",
                        str(folder),
                        "--store",
                        str(raw),
                    ],
                    folder.with_suffix(".log"),
                    stop,
                    1200,
                )
            except KeyboardInterrupt:
                receipt = {"returncode": 130, "reason": "interrupt"}
                outcome = "interrupted"
            except Exception as exc:
                receipt = {
                    "returncode": None,
                    "reason": "launch_or_supervisor_failure",
                    "error": str(exc),
                }
            starts = list((folder / "sampling-starts").glob("*.json"))
            receipt.setdefault("elapsed_seconds", time.monotonic() - dispatch_started)
            state["calls_started"] += len(starts)
            write_json(
                folder.with_suffix(".supervisor.json"),
                {
                    **receipt,
                    "monitor_failures": list(failures),
                    "charged_slots": cost,
                    "start_markers": len(starts),
                    "job_sha256": sha256(spec),
                    "plan_sha256": state["plan_sha256"],
                    "continuation_plan_sha256": state["continuation"]["plan_sha256"],
                },
            )
            current[0] = None
            state["current"] = None
            result_file = folder / "result.json"
            files = {}
            manifest = folder / "attempt-evidence.json"
            if (
                receipt.get("returncode") == 0
                and receipt.get("reason") == "worker_exit"
                and result_file.exists()
            ):
                try:
                    result = json.loads(result_file.read_text())
                    outcome = "precision_or_diagnostic_failure"
                    if (
                        result.get("status") == "computed_pending_review"
                        and result.get("job") == case
                        and len(starts) == cost
                    ):
                        files, manifest = case_artifacts(root, case, member, worker_pins)
                        outcome = "accepted"
                except Exception as exc:
                    write_json(folder / "evaluation-failure.json", {"error": str(exc)})
                    outcome = "identity_or_evaluation_failure"
            if any(not (root / p).is_file() or sha256(root / p) != h for p, h in pins.items()):
                outcome = "source_identity_failure"
            if failures or storage_failure(root, parents, folder):
                outcome = "storage_failure"
            if outcome != "accepted":
                files = retained_files(root, folder, raw, spec)
            write_json(manifest, {"case_id": case["id"], "files": files})
            state["continuation"]["attempts"].append(
                {
                    "case_id": case["id"],
                    "cost": cost,
                    "started": len(starts),
                    "outcome": outcome,
                    "receipt": str(manifest.relative_to(root)),
                    "receipt_sha256": sha256(manifest),
                }
            )
            if outcome == "accepted":
                state["accepted"].append(
                    {
                        "case_id": case["id"],
                        "charged_slots": cost,
                        "files": files,
                        "receipt": str(manifest.relative_to(root)),
                        "receipt_sha256": sha256(manifest),
                    }
                )
                state["next_fold"] += 1
                state["status"] = (
                    "cv_computations_complete"
                    if state["next_fold"] == len(cases)
                    else "cv_checkpoint"
                )
                validate_logical_prefix(state, cases, memberships, design["resolutions"])
            else:
                state["status"] = "cv_needs_review"
            atomic_state(state_path, state)
            print(
                f"curvature logical folds {state['next_fold']}/29; "
                f"charged {state['calls_charged']}/248; {outcome}",
                flush=True,
            )
            if outcome != "accepted":
                break
        atomic_state(state_path, state)
        summary = {
            "status": state["status"],
            "logical_completed_folds": state["next_fold"],
            "planned_folds": 29,
            "direct_accepted_folds": len(state["accepted"]),
            "reviewed_resolutions": len(design["resolutions"]),
            "calls_charged": state["calls_charged"],
            "calls_started": state["calls_started"],
            "max_sampler_call_slots": 248,
            "inherited_slots": 38,
            "remaining_nominal_calls_at_start": 56,
            "working_bytes": working_bytes(root, parents),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        }
        write_json(output / "run-summary.json", summary)
        if storage_failure(root, parents):
            state["status"] = "cv_storage_failure"
            summary["status"] = state["status"]
            summary["working_bytes"] = working_bytes(root, parents)
            write_json(output / "run-summary.json", summary)
            atomic_state(state_path, state)
        if state["status"] == "cv_computations_complete":
            state["continuation"]["final_summary_sha256"] = sha256(output / "run-summary.json")
            atomic_state(state_path, state)
        if state["status"] not in {"cv_checkpoint", "cv_computations_complete"}:
            raise SystemExit(2)
    finally:
        ended.set()
        if watcher.is_alive():
            watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-folds", type=int, default=1)
    a = p.parse_args()
    run(Path(__file__).resolve().parents[1], resume=a.resume, max_folds=a.max_folds)
