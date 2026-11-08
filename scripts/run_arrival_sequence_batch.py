"""Finite serial sequence refits, reusing validated checkpoint and process guardians."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_cv import CONSUMED as CV_CONSUMED  # noqa: E402
from analysis.arrival.model_cv import verify_prediction_gate  # noqa: E402
from analysis.arrival.model_data import load_lanes, sequence_folds  # noqa: E402
from scripts.run_arrival_model_batch import (  # noqa: E402
    atomic_state,
    attempt_files,
    git_sha,
    validate_checkpoint,
)
from scripts.run_arrival_model_validation import supervise  # noqa: E402

CONTROLLER = "scripts/run_arrival_sequence_batch.py"


def make_sequence_cases(root: Path, target: str, kinds: list[str]) -> list[dict[str, Any]]:
    if (
        not kinds
        or len(set(kinds)) != len(kinds)
        or not set(kinds) <= {"pooled", "distance", "event", "distance-scale"}
        or target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
    ):
        raise ValueError("one target and distinct declared models required")
    lanes, _ = load_lanes(root)
    folds = sequence_folds(lanes[target])
    cases: list[dict[str, Any]] = []
    for kind in kinds:
        gate = (
            "artifacts/models/arrival-timing/distance-scale-validation-report-v1/review-acceptance.json"
            if kind == "distance-scale"
            else "artifacts/models/arrival-timing/inference-validation-acceptance-v1.json"
            if target == "NCEI-native-duration"
            else f"artifacts/models/arrival-timing/source-validation-report-v1/{target}/"
            "review-acceptance.json"
        )
        verify_prediction_gate(root, root / gate, target, kind)
        for j, fold in enumerate(folds):
            cases.append(
                {
                    "id": f"{kind}-fold-{j + 1:02d}",
                    "job": {
                        "target": target,
                        "kind": kind,
                        "sequence": fold.sequence_id,
                        "prior": "base",
                        "gate": gate,
                        "draws": 2000,
                        "tune": 1000,
                        "cores": 2,
                        "seed": 90261107
                        + {"NCEI-native-duration": 0, "T-OBS": 1000000, "T-CAL": 2000000}[target]
                        + ["pooled", "distance", "event", "distance-scale"].index(kind) * 10000
                        + j * 100,
                    },
                }
            )
    return cases


def run_sequence_batch(
    root: Path,
    target: str,
    kinds: list[str],
    output: Path,
    store: Path,
    state_path: Path,
    *,
    resume: bool = False,
    max_cases: int | None = None,
) -> None:
    if not store.resolve().is_relative_to(root.resolve()) or (
        max_cases is not None and max_cases < 0
    ):
        raise ValueError("project-local store and nonnegative invocation ceiling required")
    cases = make_sequence_cases(root, target, kinds)
    consumed = [
        CONTROLLER,
        "scripts/run_arrival_model_batch.py",
        *CV_CONSUMED,
        *sorted({c["job"]["gate"] for c in cases}),
    ]
    pins = {p: sha256(root / p) for p in consumed}
    plan: dict[str, Any]
    state: dict[str, Any]
    if resume:
        plan = json.loads((output / "plan.json").read_text())
        state = json.loads(state_path.read_text())
        if (
            plan["cases"] != cases
            or plan["files"] != pins
            or state["current"] is not None
            or state["plan_sha256"] != sha256(output / "plan.json")
        ):
            raise ValueError("changed or unfinished sequence plan; reconcile before resume")
        validate_checkpoint(state, plan)
    else:
        if output.exists() or store.exists() or state_path.exists():
            raise ValueError("new batch paths required")
        output.mkdir(parents=True)
        plan = {
            "cases": cases,
            "files": pins,
            "base_git_sha": git_sha(root),
            "target": target,
            "max_calls": 2 * len(cases),
            "max_posterior_bytes": 2 * 1024**3,
            "per_attempt_seconds": 600,
            "concurrency": 1,
            "cores": 2,
            "scientific_acceptance": "pending_independent_review",
        }
        write_json(output / "plan.json", plan)
        state = {
            "next_case": 0,
            "calls_used": 0,
            "attempts": [],
            "current": None,
            "status": "prepared",
            "plan_sha256": sha256(output / "plan.json"),
        }
    lease = output / ".controller.lock"
    with lease.open("x") as f:
        f.write(str(os.getpid()))
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
                raise ValueError("sequence sources changed during batch")
            used = sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
            if (
                state["calls_used"] >= plan["max_calls"]
                or used + 64 * 1024**2 > plan["max_posterior_bytes"]
            ):
                state["status"] = "budget_limit"
                break
            case = cases[state["next_case"]]
            history = [a for a in state["attempts"] if a["case_id"] == case["id"]]
            job = dict(case["job"])
            number = len(history) + 1
            if number > 2:
                raise ValueError("at most one retained precision repair per fold")
            if number > 1:
                job.update(draws=4000, tune=2000)
            name = case["id"] + f"-attempt-{number}"
            attempt = output / "jobs" / name
            spec = output / "jobs" / (name + "-spec.json")
            posterior = store / (name + ".nc")
            write_json(spec, job)
            state["calls_used"] += 1
            state["status"] = "running"
            state["current"] = {"case_id": case["id"], "attempt": number, "output": str(attempt)}
            atomic_state(state_path, state)
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/fit_arrival_sequence.py"),
                        "--worker",
                        "--job",
                        str(spec),
                        "--output",
                        str(attempt),
                        "--store",
                        str(posterior),
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
                        "files": attempt_files(attempt, spec, posterior),
                    }
                )
                state.update(current=None, status="interrupted")
                atomic_state(state_path, state)
                raise
            write_json(
                attempt.with_suffix(".supervisor.json"),
                {**receipt, "job_sha256": sha256(spec), "controller_sha256": pins[CONTROLLER]},
            )
            result_path = attempt / "result.json"
            outcome = "runtime_failure"
            if (
                receipt["returncode"] == 0
                and receipt["reason"] == "worker_exit"
                and result_path.exists()
            ):
                result = json.loads(result_path.read_text())
                d = result["diagnostics"]
                expected = {p: pins[p] for p in [*CV_CONSUMED, job["gate"]]}
                if (
                    result["job"] != job
                    or result["code_and_config"] != expected
                    or result["posterior"] != str(posterior.relative_to(root))
                    or not posterior.is_file()
                    or sha256(posterior) != result["posterior_sha256"]
                ):
                    outcome = "identity_failure"
                elif (
                    result["status"] == "computed_pending_review"
                    and d["screen_passed"]
                    and result["score_precision_passed"]
                ):
                    outcome = "accepted"
                elif number == 1 and (
                    result["status"] == "score_precision_failure"
                    and d["screen_passed"]
                    or result["status"] == "diagnostic_failure"
                    and d["finite_diagnostics"]
                    and d["divergences"] == 0
                    and d["maxdepth_reached"] == 0
                    and d["min_bfmi"] >= 0.3
                    and d["max_rhat"] <= 1.03
                ):
                    outcome = "precision_failure"
                else:
                    outcome = "diagnostic_or_precision_failure"
            if any(sha256(root / p) != h for p, h in pins.items()):
                outcome = "identity_failure"
            state["attempts"].append(
                {
                    **state["current"],
                    "outcome": outcome,
                    "files": attempt_files(attempt, spec, posterior),
                }
            )
            state["current"] = None
            if outcome == "accepted":
                state["next_case"] += 1
                completed_here += 1
            elif outcome != "precision_failure":
                state["status"] = "needs_review"
            atomic_state(state_path, state)
            print(
                f"sequence {state['next_case']}/{len(cases)}; "
                f"{state['calls_used']} calls; {outcome}",
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
                "completed": state["next_case"],
                "planned": len(cases),
                "calls": state["calls_used"],
                "max_calls": plan["max_calls"],
                "scientific_acceptance": "pending_independent_review",
                "plan_sha256": sha256(output / "plan.json"),
            },
        )
    finally:
        lease.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, choices=["NCEI-native-duration", "T-OBS", "T-CAL"])
    p.add_argument(
        "--kinds",
        nargs="+",
        required=True,
        choices=["pooled", "distance", "event", "distance-scale"],
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cases", type=int)
    a = p.parse_args()
    run_sequence_batch(
        Path(__file__).resolve().parents[1],
        a.target,
        a.kinds,
        a.output.resolve(),
        a.store.resolve(),
        a.state.resolve(),
        resume=a.resume,
        max_cases=a.max_cases,
    )
