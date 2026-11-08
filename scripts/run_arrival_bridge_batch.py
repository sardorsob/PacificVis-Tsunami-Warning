"""Finite serial grouped bridge validation with conserved fold and sampler-call budgets."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_bridge_cv import CONSUMED as FOLD_CONSUMED  # noqa: E402
from analysis.arrival.model_bridge_cv import verify_bridge_gate  # noqa: E402
from analysis.arrival.model_cv import verify_prediction_gate  # noqa: E402
from analysis.arrival.model_data import load_lanes, sequence_folds  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha, validate_checkpoint  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402

CONTROLLER = "scripts/run_arrival_bridge_batch.py"
METHOD_GATE = "artifacts/models/arrival-timing/bridge-validation-report-v1/review-acceptance.json"
MAX_POSTERIOR_BYTES = 2 * 1024**3


def make_bridge_cases(root):
    for target in ["NCEI-native-duration", "T-OBS", "T-CAL"]:
        for kind in ["event", "distance-scale"] if target == "NCEI-native-duration" else ["event"]:
            verify_bridge_gate(root, root / METHOD_GATE, target, kind)
    lanes, _ = load_lanes(root)
    cases = []
    for t, target in enumerate(["NCEI-native-duration", "T-OBS", "T-CAL"]):
        lane = lanes[target]
        folds = sorted(sequence_folds(lane), key=lambda f: (-len(f.test), f.sequence_id))
        for j, fold in enumerate(folds):
            for k, kind in enumerate(["event", "distance-scale"] if t == 0 else ["event"]):
                gate = (
                    "artifacts/models/arrival-timing/distance-scale-validation-report-v1/review-acceptance.json"
                    if kind == "distance-scale"
                    else "artifacts/models/arrival-timing/inference-validation-acceptance-v1.json"
                    if t == 0
                    else f"artifacts/models/arrival-timing/source-validation-report-v1/{target}/"
                    "review-acceptance.json"
                )
                verify_prediction_gate(root, root / gate, target, kind)
                cases.append(
                    {
                        "id": f"{target}-{kind}-fold-{j + 1:02d}",
                        "ensemble_count": 1 + len({lane.event_ids[int(i)] for i in fold.test}),
                        "job": {
                            "target": target,
                            "kind": kind,
                            "prior": "base",
                            "sequence": fold.sequence_id,
                            "gate": gate,
                            "bridge_gate": METHOD_GATE,
                            "draws": 2000,
                            "tune": 1000,
                            "cores": 2,
                            "seed": 1426110800 + t * 100000 + j * 1000 + k * 100,
                        },
                    }
                )
    return cases


def _files(output, spec, store):
    files = [spec, output.with_suffix(".log"), output.with_suffix(".supervisor.json")]
    files += [p for parent in [output, store] for p in parent.rglob("*") if p.is_file()]
    return {str(p): sha256(p) for p in files if p.is_file()}


def run_bridge_batch(root, output, store, state_path, *, resume=False, max_cases=None):
    root, output, store, state_path = (p.resolve() for p in [root, output, store, state_path])
    if (
        not all(p.is_relative_to(root) for p in [output, store, state_path])
        or max_cases is not None
        and (type(max_cases) is not int or max_cases < 0)
    ):
        raise ValueError("project-local paths and nonnegative invocation ceiling required")
    cases = make_bridge_cases(root)
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
    if resume:
        plan = json.loads((output / "plan.json").read_text())
        state = json.loads(state_path.read_text())
        if plan.get("raw_store") != str(store.relative_to(root)):
            raise ValueError("bridge raw store changed; byte accounting cannot be reset")
        if (
            plan["cases"] != cases
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
            "cases": cases,
            "files": pins,
            "base_git_sha": git_sha(root),
            "raw_store": str(store.relative_to(root)),
            "max_calls": 2 * len(cases),
            "max_sampler_calls": 2 * sum(c["ensemble_count"] for c in cases),
            "max_posterior_bytes": MAX_POSTERIOR_BYTES,
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
            used = sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
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
            if (
                sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
                > plan["max_posterior_bytes"]
            ):
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
    run_bridge_batch(
        Path(__file__).resolve().parents[1],
        a.output.resolve(),
        a.store.resolve(),
        a.state.resolve(),
        resume=a.resume,
        max_cases=a.max_cases,
    )
