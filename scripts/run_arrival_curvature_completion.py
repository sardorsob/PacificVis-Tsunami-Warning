"""Finish the unchanged curvature folds after two independently reviewed numerical resolutions."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_precision import (  # noqa: E402
    GATE as PRECISION_GATE,
)
from analysis.arrival.model_curvature_precision import (
    OUTPUT as PRECISION_OUTPUT,
)
from analysis.arrival.model_curvature_precision import (
    SOURCE as PRECISION_SOURCE,
)
from analysis.arrival.model_curvature_precision import (
    admit as admit_precision,
)
from analysis.arrival.model_curvature_precision import (
    job as precision_job,
)
from scripts import run_arrival_curvature_continuation as previous  # noqa: E402
from scripts.run_arrival_curvature_pilot import bindings  # noqa: E402
from scripts.run_arrival_curvature_sequences import (  # noqa: E402
    MAX_CALLS,
    MAX_GLOBAL,
    MAX_LOCAL,
    MIB,
    OUTPUT,
    RESERVE,
    STATE,
    STORE,
    byte_count,
    case_artifacts,
    parent_floors,
    verify_rehearsal,
)
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

SELF = "scripts/run_arrival_curvature_completion.py"
CONTINUATION = OUTPUT + "/continuation-v2"
DESIGN = "artifacts/models/arrival-timing/mean-curvature-completion-design-v1"
GATE = DESIGN + "/review-acceptance.json"
PRECISION_REVIEW = PRECISION_OUTPUT + "/review-acceptance.json"
REHEARSAL = CONTINUATION + "/rehearsal-review-acceptance.json"


def resources():
    return {**previous.resources(), "inherited_charged_slots": 53}


def working_bytes(root, parents):
    return previous.working_bytes(root, parents) + byte_count(
        root / Path(PRECISION_GATE).parent, root / DESIGN
    )


def storage_failure(root, parents, current=None, *, gate=None):
    try:
        if gate is not None:
            parent_floors(root, gate)
    except Exception:
        return "parent_floor_failure"
    return (
        (
            "completion_job_storage"
            if current is not None and byte_count(current, root / STORE / current.name) > 32 * MIB
            else None
        )
        or previous.storage_failure(root, parents, current)
        or (
            "completion_design_global_storage"
            if working_bytes(root, parents) > MAX_GLOBAL
            else None
        )
    )


def inherited_ledger_sha256(state):
    selected = {
        name: state[name] for name in ["path_amendment", "continuation", "precision_amendment"]
    }
    return hashlib.sha256(
        json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def admit_continuation(root):
    gate = json.loads((root / GATE).read_text())
    required = {
        SELF,
        previous.GATE,
        PRECISION_GATE,
        PRECISION_REVIEW,
        PRECISION_OUTPUT + "/result.json",
        PRECISION_SOURCE + "/result.json",
        PRECISION_SOURCE + "/held-out-record-predictions.csv",
    }
    if (
        gate.get("status") != "accepted_curvature_completion_rehearsal"
        or gate.get("independent_checker") is not True
        or gate.get("resources") != resources()
        or gate.get("path_bindings")
        != bindings(root, root / CONTINUATION, root / STORE, root / STATE)
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or not required.issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independent two-resolution completion design required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for p, h in pins.items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("completion evidence changed")
    review = json.loads((root / PRECISION_REVIEW).read_text())
    if (
        review.get("status") != "accepted_same_model_curvature_precision_resolution"
        or review.get("independent_checker") is not True
        or review.get("confirmation_outcomes_parsed") is not False
        or review.get("reserved_outcomes") != "sealed"
        or not review.get("files")
        or any(pins.get(p) != h for p, h in review["files"].items())
        or review.get("derived_result") != PRECISION_OUTPUT + "/result.json"
        or review.get("derived_result_sha256") != pins[PRECISION_OUTPUT + "/result.json"]
    ):
        raise ValueError("complete independently accepted LATA precision resolution required")
    # Both helpers admit their entire source/raw closure before loading the exploration tables.
    _, precision_pins, _ = admit_precision(root)
    if any(pins.get(p) != h for p, h in precision_pins.items()):
        raise ValueError("complete numerical precision source closure required")
    for receipt in [previous.GATE, previous.DERIVED_REVIEW]:
        proof = json.loads((root / receipt).read_text())
        if not proof.get("files") or any(pins.get(p) != h for p, h in proof["files"].items()):
            raise ValueError("complete original continuation and path source closure required")
    design = previous.admit_continuation(root)
    if any(pins.get(p) != h for p, h in design["files"].items()):
        raise ValueError("unchanged original fold/source closure required")
    result = json.loads((root / PRECISION_OUTPUT / "result.json").read_text())
    prediction = PRECISION_SOURCE + "/held-out-record-predictions.csv"
    if (
        result.get("job") != design["cases"][8]
        or result.get("precision_job") != precision_job()
        or result.get("status") != "computed_pending_review"
        or result.get("score_precision_passed") is not True
        or result.get("prediction_precision_passed") is not True
        or result.get("observation_measure") != "native_minutes_Jacobian_already_applied_once"
        or result.get("source_result") != PRECISION_SOURCE + "/result.json"
        or result.get("source_result_sha256") != pins[PRECISION_SOURCE + "/result.json"]
        or result.get("training_only_predictions") != prediction
        or result.get("training_only_predictions_sha256") != pins[prediction]
    ):
        raise ValueError(
            "same original failed fold, native score and training predictions required"
        )
    resolutions = {
        **design["resolutions"],
        "fold-008": {
            "receipt": PRECISION_REVIEW,
            "receipt_sha256": pins[PRECISION_REVIEW],
            "result": PRECISION_OUTPUT + "/result.json",
            "result_sha256": pins[PRECISION_OUTPUT + "/result.json"],
            "prediction": prediction,
            "prediction_sha256": pins[prediction],
        },
    }
    if (
        gate.get("resolutions") != resolutions
        or gate.get("remaining_cases") != design["cases"][9:]
        or sum(design["memberships"][c["id"]]["charged_call_slots"] for c in design["cases"][9:])
        != 43
    ):
        raise ValueError("unchanged final20fold43call design and two literal resolutions required")
    parents = parent_floors(root, gate)
    return {**design, "gate": gate, "files": pins, "parents": parents, "resolutions": resolutions}


def validate_inherited_path(root, state, pins):
    previous.validate_inherited_path(root, state, pins)
    gate = json.loads((root / GATE).read_text())
    if inherited_ledger_sha256(state) != gate.get("inherited_ledger_sha256"):
        raise ValueError("inherited path, stopped continuation or precision ledger changed")
    part = state["precision_amendment"]
    receipt = PRECISION_OUTPUT + "/attempt-evidence.json"
    allocation = PRECISION_OUTPUT + "-allocation.json"
    if (
        part.get("charged_slots") != 2
        or part.get("started") != 2
        or part.get("parent_calls_charged") != 51
        or part.get("parent_calls_started") != 51
        or part.get("receipt") != receipt
        or part.get("receipt_sha256") != pins.get(receipt)
        or part.get("allocation") != allocation
        or part.get("allocation_sha256") != pins.get(allocation)
    ):
        raise ValueError("complete two-call53slot precision inheritance required")


def validate_logical_prefix(state, cases, memberships, resolutions):
    if (
        set(resolutions) != {"fold-002", "fold-008"}
        or type(state.get("next_fold")) is not int
        or not 9 <= state["next_fold"] <= len(cases)
        or state.get("completion", {}).get("resolutions") != resolutions
    ):
        raise ValueError("complete two-resolution logical prefix required")
    expected = [c["id"] for c in cases[: state["next_fold"]] if c["id"] not in resolutions]
    if [a.get("case_id") for a in state.get("accepted", [])] != expected:
        raise ValueError("direct attempts plus two reviewed resolutions must conserve prefix")
    attempts = state["completion"].get("attempts", [])
    if [a.get("case_id") for a in attempts] != expected[7:]:
        raise ValueError("complete ordered completion attempt ledger required")
    for a, accepted in zip(attempts, state["accepted"][7:], strict=True):
        cost = memberships[a["case_id"]]["charged_call_slots"]
        if (
            a.get("outcome") != "accepted"
            or a.get("cost") != cost
            or a.get("started") != cost
            or a.get("receipt") != accepted.get("receipt")
            or a.get("receipt_sha256") != accepted.get("receipt_sha256")
        ):
            raise ValueError("all new slots and receipts must be conserved")
    if (
        state.get("calls_charged") != 53 + sum(a["cost"] for a in attempts)
        or state.get("calls_started") != 53 + sum(a["started"] for a in attempts)
        or state["calls_charged"] > 248
    ):
        raise ValueError("all53inherited and every new call must be conserved")


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
        "resolution-fold-008-precision-v1",
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
    first = state["accepted"][7]
    required = {
        **first["files"],
        first["receipt"]: first["receipt_sha256"],
        CONTINUATION + "/plan.json": sha256(root / CONTINUATION / "plan.json"),
    }
    if (
        review.get("status") != "accepted_first_curvature_completion_fold"
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
    lease = root / OUTPUT / ".controller.lock"
    if lease.with_name("STOP").exists():
        raise ValueError("STOP present before any new allocation")
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = root / OUTPUT / "STOP"

    def monitor():
        while not ended.wait(0.1):
            reason = storage_failure(root, parents, current[0], gate=design["gate"])
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
            "inherited_slots": 53,
            "remaining_nominal_slots": 43,
            "global_call_ceiling": 248,
        }
        if resume:
            plan = json.loads((output / "plan.json").read_text())
            if (
                any(plan.get(k) != v for k, v in expected.items())
                or state.get("status") not in {"cv_checkpoint", "cv_computations_complete"}
                or state.get("current") is not None
                or state.get("completion", {}).get("plan_sha256") != sha256(output / "plan.json")
            ):
                raise ValueError(
                    "changed or failed continuation ledger requires reviewed reconciliation"
                )
            validate_logical_prefix(state, cases, memberships, design["resolutions"])
        else:
            if (
                output.exists()
                or "completion" in state
                or state.get("status") != "precision_computations_complete"
                or state.get("calls_charged") != 53
                or state.get("calls_started") != 53
                or state.get("next_fold") != 8
                or state.get("current") is not None
                or len(state.get("accepted", [])) != 7
            ):
                raise ValueError(
                    "exact53slot completed-precision parent required; no copied/reset allocation"
                )
            output.mkdir(parents=True)
            plan = {
                **expected,
                "source_git_sha": git_sha(root),
                "scope": "same original candidate/cohort; two reviewed numerical resolutions",
            }
            write_json(output / "plan.json", plan)
            state["completion"] = {
                "plan_sha256": sha256(output / "plan.json"),
                "resolutions": design["resolutions"],
                "attempts": [],
            }
            state.update(next_fold=9, status="cv_checkpoint")
            atomic_state(state_path, state)
        for case, accepted in zip(
            [c for c in cases[: state["next_fold"]] if c["id"] not in design["resolutions"]],
            state["accepted"],
            strict=True,
        ):
            case_artifacts(root, case, memberships[case["id"]], worker_pins, accepted)
            if case in cases[9:]:
                supervisor = json.loads(
                    (root / OUTPUT / "jobs" / case["id"])
                    .with_suffix(".supervisor.json")
                    .read_text()
                )
                if supervisor.get("continuation_plan_sha256") != state["completion"]["plan_sha256"]:
                    raise ValueError("new-fold supervisor amendment identity changed")
        validate_raw_inventory(root, state, pins)
        if storage_failure(root, parents, gate=design["gate"]):
            raise ValueError("retained working-store budget exceeded")
        if state["status"] == "cv_computations_complete":
            if validate_first_new_fold(root, state) != state["completion"].get("rehearsal_sha256"):
                raise ValueError("completed first continuation review identity changed")
            if sha256(output / "run-summary.json") != state["completion"].get(
                "final_summary_sha256"
            ):
                raise ValueError("completed continuation summary changed")
            return
        limit_worker_file_size(64 * MIB)
        watcher.start()
        for _ in range(max_folds):
            parent_floors(root, design["gate"])
            if state["next_fold"] >= 10:
                identity = validate_first_new_fold(root, state)
                if state["completion"].get("rehearsal_sha256") not in {None, identity}:
                    raise ValueError("first continuation review changed")
                state["completion"]["rehearsal_sha256"] = identity
            validate_raw_inventory(root, state, pins)
            if state["next_fold"] == len(cases):
                break
            case = cases[state["next_fold"]]
            member = memberships[case["id"]]
            cost = member["charged_call_slots"]
            if (
                stop.exists()
                or failures
                or storage_failure(root, parents, gate=design["gate"])
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
                    "continuation_plan_sha256": state["completion"]["plan_sha256"],
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
            if failures or storage_failure(root, parents, folder, gate=design["gate"]):
                outcome = "storage_failure"
            if outcome != "accepted":
                files = retained_files(root, folder, raw, spec)
            write_json(manifest, {"case_id": case["id"], "files": files})
            if storage_failure(root, parents, folder, gate=design["gate"]):
                outcome = "storage_failure"
                files = retained_files(root, folder, raw, spec)
                write_json(manifest, {"case_id": case["id"], "files": files})
            state["completion"]["attempts"].append(
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
            "inherited_slots": 53,
            "remaining_nominal_calls_at_start": 43,
            "working_bytes": working_bytes(root, parents),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        }
        write_json(output / "run-summary.json", summary)
        if storage_failure(root, parents, gate=design["gate"]):
            state["status"] = "cv_storage_failure"
            summary["status"] = state["status"]
            summary["working_bytes"] = working_bytes(root, parents)
            write_json(output / "run-summary.json", summary)
            atomic_state(state_path, state)
        ended.set()
        watcher.join(timeout=2)
        if failures or storage_failure(root, parents, gate=design["gate"]):
            state["status"] = summary["status"] = "cv_storage_failure"
            write_json(output / "run-summary.json", summary)
            atomic_state(state_path, state)
        if state["status"] == "cv_computations_complete":
            state["completion"]["final_summary_sha256"] = sha256(output / "run-summary.json")
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
