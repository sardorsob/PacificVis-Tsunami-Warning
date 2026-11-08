"""Continue the remaining eighty-one folds without resetting stopped-run budgets."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_bridge_cv import CONSUMED as FOLD_CONSUMED  # noqa: E402
from scripts.run_arrival_bridge_batch import make_bridge_cases  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha, validate_checkpoint  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402

CONTROLLER = "scripts/run_arrival_bridge_continuation.py"
GATE = "artifacts/models/arrival-timing/bridge-continuation-method-v1.json"
PARENT = "artifacts/models/arrival-timing/bridge-sequence-validation-v1"
PATH = "artifacts/models/arrival-timing/tohoku-joint-score-integration-v1"


def continuation_design(root):
    gate_path = checked_path(root, GATE)
    gate = json.loads(gate_path.read_text())
    required = set(
        [
            CONTROLLER,
            *FOLD_CONSUMED,
            "scripts/run_arrival_model_validation.py",
            PARENT + "/plan.json",
            PARENT + "/run-summary.json",
            PARENT + "/rehearsal-review-acceptance.json",
            PATH + "/plan.json",
            PATH + "/run-summary.json",
            PATH + "/review-acceptance.json",
            PATH + "/primary-path-result.json",
            PATH + "/repeat-path-result.json",
            PATH + "/independent-repeat-check.json",
        ]
    )
    if (
        gate.get("schema_version") != "arrival_bridge_continuation_acceptance_v1"
        or gate.get("status") != "accepted_for_remaining_folds"
        or not gate.get("runtime_checker")
        or gate.get("reserved_outcomes") != "sealed"
        or not required <= set(gate.get("files", {}))
    ):
        raise ValueError("reviewed continuation runtime and actual path gate required")
    for p, h in gate["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("continuation gate identity changed")

    def read(p):
        return json.loads((root / p).read_text())

    parent_plan, parent_run = read(PARENT + "/plan.json"), read(PARENT + "/run-summary.json")
    path_plan, path_run = read(PATH + "/plan.json"), read(PATH + "/run-summary.json")
    qa = read(PATH + "/review-acceptance.json")
    cases = make_bridge_cases(root)
    if (
        len(cases) != 83
        or sum(c["ensemble_count"] for c in cases) != 176
        or parent_plan["cases"] != cases
        or parent_plan["max_sampler_calls"] != 352
        or parent_run["status"] != "needs_review"
        or parent_run["completed_folds"] != 1
        or parent_run["fold_attempts"] != 2
        or parent_run["sampler_calls_reserved"] != 4
        or path_run["status"] != "computations_complete"
        or path_run["new_call_slots_used"] != 15
        or path_run["remaining_global_calls"] != 333
        or qa.get("status") != "accepted_primary_score_and_independent_repeat"
        or qa.get("reserved_outcomes") != "sealed"
        or not read(PATH + "/independent-repeat-check.json")["agreement_passed"]
        or not read(PATH + "/primary-path-result.json")["precision_passed"]
        or not read(PATH + "/repeat-path-result.json")["precision_passed"]
        or [c["id"] for c in cases[:2]]
        != ["NCEI-native-duration-event-fold-01", "NCEI-native-duration-distance-scale-fold-01"]
    ):
        raise ValueError("exact reviewed 83-fold, nineteen-call lineage required")
    for p, h in qa["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("reviewed actual path evidence changed")
    parent_store = checked_path(root, parent_plan["raw_store"])
    external = [
        m["posterior"]
        for m in path_plan["endpoint_metadata"]
        if not checked_path(root, m["posterior"]).is_relative_to(parent_store)
    ]
    if len(external) != 1:
        raise ValueError("exactly one external reused endpoint required for shared storage")
    return {
        "cases": cases[2:],
        "files": {**gate["files"], GATE: sha256(gate_path)},
        "prior_calls": 19,
        "global_call_ceiling": 352,
        "remaining_calls": 333,
        "prior_raw_stores": [parent_plan["raw_store"], path_plan["raw_store"]],
        "external_endpoint": external[0],
        "max_raw_bytes": parent_plan["max_posterior_bytes"],
        "logical_fold_total": 83,
        "completed_parent_folds": 2,
    }


def used_bytes(root, store, design):
    return checked_path(root, design["external_endpoint"]).stat().st_size + sum(
        p.stat().st_size
        for folder in [store, *[checked_path(root, p) for p in design["prior_raw_stores"]]]
        for p in folder.rglob("*")
        if p.is_file()
    )


def _files(output, spec, store):
    files = [spec, output.with_suffix(".log"), output.with_suffix(".supervisor.json")]
    files += [p for parent in [output, store] for p in parent.rglob("*") if p.is_file()]
    return {str(p): sha256(p) for p in files if p.is_file()}


def run_continuation(root, output, store, state_path, *, resume=False, max_cases=None):
    root, output, store, state_path = (p.resolve() for p in [root, output, store, state_path])
    if (
        not all(p.is_relative_to(root) for p in [output, store, state_path])
        or max_cases is not None
        and (type(max_cases) is not int or max_cases < 0)
    ):
        raise ValueError("project-local paths and nonnegative invocation ceiling required")
    design = continuation_design(root)
    cases = design["cases"]
    if any(
        store.is_relative_to(root / p) or (root / p).is_relative_to(store)
        for p in design["prior_raw_stores"]
    ):
        raise ValueError("new store must be disjoint from retained prior stores")
    consumed = sorted(
        set(
            [
                CONTROLLER,
                *FOLD_CONSUMED,
                "scripts/run_arrival_model_batch.py",
                "scripts/run_arrival_model_validation.py",
                *[c["job"][key] for c in cases for key in ["gate", "bridge_gate"]],
            ]
        )
    )
    pins = {p: sha256(root / p) for p in consumed}
    pins.update(design["files"])
    if resume:
        plan = json.loads((output / "plan.json").read_text())
        state = json.loads(state_path.read_text())
        if plan.get("raw_store") != str(store.relative_to(root)):
            raise ValueError("bridge raw store changed; byte accounting cannot be reset")
        if (
            plan["cases"] != cases
            or any(plan.get(k) != v for k, v in design.items() if k not in {"cases", "files"})
            or plan["max_calls"] != 2 * len(cases)
            or plan["max_sampler_calls"] != design["remaining_calls"]
            or plan["max_posterior_bytes"] != design["max_raw_bytes"]
            or plan["files"] != pins
            or state["current"] is not None
            or state["plan_sha256"] != sha256(output / "plan.json")
        ):
            raise ValueError("changed or unfinished bridge plan; reconcile before resume")
        validate_checkpoint(state, plan)
        reserved = sum(
            next(c["ensemble_count"] for c in cases if c["id"] == a["case_id"])
            for a in state["attempts"]
        )
        if reserved != state["sampler_call_slots_used"] or reserved > plan["max_sampler_calls"]:
            raise ValueError("sampler call allocation conservation failed")
    else:
        if output.exists() or store.exists() or state_path.exists():
            raise ValueError("new bridge batch paths required")
        output.mkdir(parents=True)
        plan = {
            **design,
            "cases": cases,
            "files": pins,
            "base_git_sha": git_sha(root),
            "raw_store": str(store.relative_to(root)),
            "max_calls": 2 * len(cases),
            "max_sampler_calls": design["remaining_calls"],
            "max_posterior_bytes": design["max_raw_bytes"],
            "per_fold_attempt_seconds": 600,
            "per_file_bytes": 64 * 1024**2,
            "cores": 2,
            "concurrency": 1,
            "call_accounting": "fold_attempts_plus_conservative_sampler_call_reservations",
            "scientific_acceptance": "pending_independent_review",
        }
        write_json(output / "plan.json", plan)
        state = {
            "next_case": 0,
            "calls_used": 0,
            "sampler_call_slots_used": 0,
            "attempts": [],
            "current": None,
            "status": "prepared",
            "plan_sha256": sha256(output / "plan.json"),
        }
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    try:
        atomic_state(state_path, state)
        completed_here = 0
        while state["next_case"] < len(cases):
            if max_cases is not None and completed_here >= max_cases:
                state["status"] = "invocation_limit"
                break
            if (output / "jobs/STOP").exists():
                state["status"] = "stop_signal"
                break
            if any(sha256(root / p) != h for p, h in pins.items()):
                raise ValueError("bridge batch sources changed")
            case = cases[state["next_case"]]
            used = used_bytes(root, store, design)
            reserve = (case["ensemble_count"] + 1) * plan["per_file_bytes"]
            if (
                state["calls_used"] >= plan["max_calls"]
                or state["sampler_call_slots_used"] + case["ensemble_count"]
                > plan["max_sampler_calls"]
                or used + reserve > plan["max_posterior_bytes"]
            ):
                state["status"] = "budget_limit"
                break
            history = [a for a in state["attempts"] if a["case_id"] == case["id"]]
            number = len(history) + 1
            if number > 2:
                raise ValueError("one mild repair per fold only")
            job = {**case["job"], **({"draws": 4000, "tune": 2000} if number == 2 else {})}
            name = case["id"] + f"-attempt-{number}"
            attempt = output / "jobs" / name
            raw = store / name
            spec = output / "jobs" / (name + "-spec.json")
            write_json(spec, job)
            state["calls_used"] += 1
            state["sampler_call_slots_used"] += case["ensemble_count"]
            state["current"] = {"case_id": case["id"], "attempt": number, "output": str(attempt)}
            state["status"] = "running"
            atomic_state(state_path, state)
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/fit_arrival_bridge_fold.py"),
                        "--worker",
                        "--job",
                        str(spec),
                        "--output",
                        str(attempt),
                        "--store",
                        str(raw),
                    ],
                    attempt.with_suffix(".log"),
                    output / "jobs/STOP",
                    600,
                )
            except KeyboardInterrupt:
                state["attempts"].append(
                    {
                        **state["current"],
                        "outcome": "interrupted",
                        "files": _files(attempt, spec, raw),
                    }
                )
                state.update(current=None, status="interrupted")
                atomic_state(state_path, state)
                raise
            write_json(attempt.with_suffix(".supervisor.json"), receipt)
            outcome = "runtime_failure"
            result_path = attempt / "result.json"
            if (
                receipt["reason"] == "worker_exit"
                and receipt["returncode"] in {0, 2}
                and result_path.exists()
            ):
                result = json.loads(result_path.read_text())
                expected = {p: pins[p] for p in [*FOLD_CONSUMED, job["gate"], job["bridge_gate"]]}
                identities = json.loads((attempt / "inputs.json").read_text())["files"]
                actual_calls = len(list((attempt / "sampling-starts").glob("*.json")))
                if (
                    result["job"] != job
                    or identities != expected
                    or result["sampler_calls"] != actual_calls
                    or actual_calls > case["ensemble_count"]
                ):
                    outcome = "identity_failure"
                elif (
                    receipt["returncode"] == 0
                    and result["status"] == "computed_pending_review"
                    and actual_calls == case["ensemble_count"]
                    and result["score_precision_passed"]
                    and result["prediction_precision_passed"]
                ):
                    outcome = "accepted"
                elif (
                    number == 1
                    and receipt["returncode"] == 2
                    and result["status"] in {"diagnostic_failure", "precision_failure"}
                    and result.get("repairable")
                ):
                    outcome = "precision_failure"
                else:
                    outcome = "diagnostic_or_precision_failure"
            if any(sha256(root / p) != h for p, h in pins.items()):
                outcome = "identity_failure"
            if used_bytes(root, store, design) > plan["max_posterior_bytes"]:
                outcome = "storage_budget_failure"
            state["attempts"].append(
                {**state["current"], "outcome": outcome, "files": _files(attempt, spec, raw)}
            )
            state["current"] = None
            if outcome == "accepted":
                state["next_case"] += 1
                completed_here += 1
            elif outcome != "precision_failure":
                state["status"] = "needs_review"
            atomic_state(state_path, state)
            print(
                f"bridge folds {state['next_case']}/{len(cases)}; "
                f"sampler allocation {state['sampler_call_slots_used']}/"
                f"{plan['max_sampler_calls']}; "
                f"{outcome}",
                flush=True,
            )
            if state["status"] == "needs_review":
                break
        if state["next_case"] == len(cases):
            state["status"] = "computations_complete"
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "completed_folds": state["next_case"],
                "planned_folds": len(cases),
                "fold_attempts": state["calls_used"],
                "sampler_calls_reserved": state["sampler_call_slots_used"],
                "prior_call_slots": design["prior_calls"],
                "global_calls_reserved": design["prior_calls"] + state["sampler_call_slots_used"],
                "remaining_global_calls": (
                    design["remaining_calls"] - state["sampler_call_slots_used"]
                ),
                "logical_completed_folds": design["completed_parent_folds"] + state["next_case"],
                "logical_fold_total": design["logical_fold_total"],
                "raw_bytes_used": used_bytes(root, store, design),
                "max_sampler_calls": plan["max_sampler_calls"],
                "scientific_acceptance": "pending_independent_review",
                "plan_sha256": sha256(output / "plan.json"),
            },
        )
    finally:
        lease.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cases", type=int)
    a = p.parse_args()
    run_continuation(
        Path(__file__).resolve().parents[1],
        a.output.resolve(),
        a.store.resolve(),
        a.state.resolve(),
        resume=a.resume,
        max_cases=a.max_cases,
    )
