"""Finite, serial source-specific recovery/SBC trials with conservative checkpoint resume."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import sha256, write_json, write_rows  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402

CONSUMED = [
    "scripts/run_arrival_model_batch.py",
    "scripts/run_arrival_model_validation.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/models.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/evidence.py",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-model-contract-v1.toml",
    "pyproject.toml",
    "uv.lock",
]


def consumed_for(protocol: str) -> list[str]:
    if protocol == "distance-scale":
        return CONSUMED + [
            "analysis/arrival/model_scale.py",
            "analysis/arrival/model_scale_validation.py",
            "artifacts/models/arrival-timing/distance-scale-prior-v1/review-acceptance.json",
        ]
    return CONSUMED


def git_sha(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def make_cases(
    phase: str, protocol: str = "core", target: str = "NCEI-native-duration"
) -> list[dict[str, Any]]:
    """Predefine all datasets; spaced seeds isolate truth/data/sampler/rank RNG channels."""
    if phase not in {"recovery", "sbc"}:
        raise ValueError("unknown validation phase")
    if target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("unknown source target")
    if protocol == "distance-scale":
        if target != "NCEI-native-duration":
            raise ValueError("distance-scale protocol is primary-source only")
        profile_settings = (
            [
                ("constant-spread", [0.3, 0.3, 0.3]),
                ("decreasing-spread", [0.6, 0.3, 0.08]),
                ("nonmonotone-spread", [0.15, 0.5, 0.2]),
            ]
            if phase == "recovery"
            else [("prior-generated", None)]
        )
        cases = []
        for scenario, (label, anchors) in enumerate(profile_settings):
            for replicate in range(15 if phase == "recovery" else 100):
                job = {
                    "phase": phase,
                    "target": target,
                    "model": "distance-scale",
                    "parameterization": "marginal",
                    "seed": 70261107
                    + (1000000 if phase == "recovery" else 2000000)
                    + scenario * 10000
                    + replicate * 100,
                    "draws": 1000 if phase == "recovery" else 2000,
                    "tune": 1000,
                    "cores": 2,
                }
                if anchors is not None:
                    job["truth"] = {
                        "alpha": 0.15,
                        "beta": -0.05,
                        "tau_event": 0.2,
                        "sigma_anchor": anchors,
                    }
                cases.append(
                    {
                        "id": f"{label}-rep-{replicate + 1:03d}",
                        "scenario": label,
                        "replicate": replicate + 1,
                        "job": job,
                    }
                )
        return cases
    if protocol not in {"core", "combined-followup"} or (
        protocol == "combined-followup"
        and (phase != "recovery" or target != "NCEI-native-duration")
    ):
        raise ValueError("invalid follow-up protocol")
    base = {"alpha": 0.15, "beta": -0.05, "tau_event": 0.2, "sigma": 0.3}
    scenarios: list[tuple[str, dict[str, float], int]] = [
        ("reference", {}, 0),
        ("no-event-variation", {"tau_event": 0}, 0),
        ("weak-event-variation", {"tau_event": 0.05}, 0),
        ("strong-event-variation", {"tau_event": 0.5}, 0),
        ("no-distance-adjustment", {"beta": 0}, 0),
        ("material-distance-adjustment", {"beta": -0.2}, 0),
        ("larger-record-spread", {"sigma": 0.6}, 0),
        ("combined-weak-event-large-spread", {"tau_event": 0.05, "sigma": 0.6, "beta": -0.2}, 0),
        ("reported-time-addition-stress", {}, 5),
    ]
    cases: list[dict[str, Any]] = []
    settings: list[tuple[str, dict[str, float], int]] = (
        scenarios if phase == "recovery" else [("prior-generated", {}, 0)]
    )
    if protocol == "combined-followup":
        settings = [scenarios[7]]
    secondary = target != "NCEI-native-duration"
    if secondary:
        base = (
            {"alpha": -15.0, "beta": 5.0, "tau_event": 10.0, "sigma": 20.0}
            if target == "T-CAL"
            else base
        )
        difficult = (
            {"tau_event": 2.5, "sigma": 40.0, "beta": 10.0}
            if target == "T-CAL"
            else {"tau_event": 0.05, "sigma": 0.6, "beta": -0.2}
        )
        settings = (
            [
                ("reference", {}, 0),
                ("no-event-variation", {"tau_event": 0}, 0),
                ("combined-weak-event-large-spread", difficult, 0),
            ]
            if phase == "recovery"
            else [("prior-generated", {}, 0)]
        )
    repeats = (
        (10 if phase == "recovery" else 30) if secondary else (30 if phase == "recovery" else 200)
    )
    for scenario, (label, changes, delay) in enumerate(settings):
        for replicate in range(repeats):
            seed = 20261107 + (1000000 if phase == "recovery" else 2000000)
            if protocol == "combined-followup":
                seed = 20261107 + 3000000
            seed += {"NCEI-native-duration": 0, "T-OBS": 10000000, "T-CAL": 20000000}[target]
            seed += scenario * 10000 + replicate * 100
            job: dict[str, Any] = {
                "phase": phase,
                "target": target,
                "parameterization": "marginal",
                "seed": seed,
                "draws": 1000 if phase == "recovery" else 2000,
                "tune": 1000,
                "cores": 2,
            }
            if phase == "recovery":
                job.update({"truth": {**base, **changes}, "additive_minutes": delay})
            cases.append(
                {
                    "id": f"{label}-rep-{replicate + 1:03d}",
                    "scenario": label,
                    "replicate": replicate + 1,
                    "job": job,
                }
            )
    return cases


def atomic_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp.json")
    write_json(temporary, state)
    temporary.replace(path)


def validate_checkpoint(state: dict[str, Any], plan: dict[str, Any]) -> None:
    """Require a conserved prefix; failed trials cannot disappear across a resume."""
    completed, calls = state["next_case"], state["calls_used"]
    attempts = state["attempts"]
    accepted = [item["case_id"] for item in attempts if item["outcome"] == "accepted"]
    ids = [case["id"] for case in plan["cases"]]
    if (
        type(completed) is not int
        or type(calls) is not int
        or not 0 <= completed <= len(ids)
        or not 0 <= calls <= plan["max_calls"]
        or calls != len(attempts)
        or accepted != ids[:completed]
        or any(item["case_id"] not in ids[: min(completed + 1, len(ids))] for item in attempts)
    ):
        raise ValueError("checkpoint trial conservation failed")
    if state["status"] in {"needs_review", "interrupted"}:
        raise ValueError("failed/interrupted attempt requires explicit review before another run")
    for item in attempts:
        if not item.get("files") or any(
            not Path(path).is_file() or sha256(Path(path)) != digest
            for path, digest in item["files"].items()
        ):
            raise ValueError("retained attempt changed or is missing; reconcile before resume")


def attempt_files(attempt: Path, job: Path, posterior: Path) -> dict[str, str]:
    paths = [job, posterior, attempt.with_suffix(".log"), attempt.with_suffix(".supervisor.json")]
    paths.extend(path for path in attempt.rglob("*") if path.is_file())
    return {str(path): sha256(path) for path in paths if path.is_file()}


def result_matches(
    root: Path, result: dict[str, Any], job: dict[str, Any], posterior: Path, pins: dict[str, str]
) -> bool:
    expected_pins = {p: digest for p, digest in pins.items() if p != CONSUMED[0]}
    return (
        result.get("job") == job
        and result.get("synthetic_only") is True
        and result.get("code_and_config") == expected_pins
        and result.get("posterior") == str(posterior.relative_to(root))
        and posterior.is_file()
        and result.get("posterior_sha256") == sha256(posterior)
    )


def _report(output: Path, state: dict[str, Any], plan: dict[str, Any]) -> None:
    rows = [
        {
            "case_id": str(item["case_id"]),
            "attempt": str(item["attempt"]),
            "outcome": str(item["outcome"]),
            "output": str(item["output"]),
            "counted_as_dataset": str(item["outcome"] == "accepted"),
        }
        for item in state["attempts"]
    ]
    write_rows(output / "trial-dispositions.csv", rows)
    write_json(
        output / "run-summary.json",
        {
            "phase": plan["phase"],
            "protocol": plan.get("protocol", "core"),
            "target": plan.get("target", "NCEI-native-duration"),
            "planned_datasets": len(plan["cases"]),
            "completed_datasets": state["next_case"],
            "calls_used": state["calls_used"],
            "max_calls": plan["max_calls"],
            "status": state["status"],
            "computational_completion_only": True,
            "scientific_acceptance": "pending_review",
            "plan_sha256": sha256(output / "plan.json"),
        },
    )


def run_batch(
    root: Path,
    phase: str,
    output: Path,
    store: Path,
    state_path: Path,
    *,
    max_cases: int | None = None,
    resume: bool = False,
    protocol: str = "core",
    target: str = "NCEI-native-duration",
) -> None:
    """Run fixed datasets; retry only mild precision failures once, retaining every attempt."""
    if max_cases is not None and max_cases < 0:
        raise ValueError("negative invocation case ceiling")
    cases = make_cases(phase, protocol, target)
    if not store.resolve().is_relative_to(root.resolve()):
        raise ValueError("posterior store must remain inside the project")
    if resume:
        if not output.is_dir() or not state_path.exists():
            raise ValueError("missing resume state/output")
    elif output.exists() or state_path.exists():
        raise ValueError("new run paths required; use explicit resume for an existing run")
    else:
        output.mkdir(parents=True)
    lease = output / ".controller.lock"
    try:
        with lease.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
    except FileExistsError as error:
        raise ValueError("active or stale controller lease; reconcile before resuming") from error
    try:
        plan: dict[str, Any]
        state: dict[str, Any]
        pins = {name: sha256(root / name) for name in consumed_for(protocol)}
        if resume:
            plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if (
                plan["phase"] != phase
                or plan["code_and_config"] != pins
                or plan.get("protocol", "core") != protocol
                or plan.get("target", "NCEI-native-duration") != target
            ):
                raise ValueError("source/phase changed; do not resume a different experiment")
            if state["current"] is not None:
                raise ValueError(
                    "incomplete attempt requires reconciliation; no automatic duplicate"
                )
            validate_checkpoint(state, plan)
        else:
            parent_budget = None
            max_calls, max_bytes = (330 if phase == "recovery" else 260), 2 * 1024**3
            if target != "NCEI-native-duration":
                max_calls = 45
            if protocol == "distance-scale":
                max_calls = 60 if phase == "recovery" else 130
            if protocol == "combined-followup":
                path = root / "artifacts/models/arrival-timing/design-recovery-v1/run-summary.json"
                parent = json.loads(path.read_text())
                if parent["status"] != "computations_complete" or parent["phase"] != "recovery":
                    raise ValueError("completed original recovery budget required")
                parent_store = root / "data/processed/models/design-recovery-v1"
                parent_bytes = sum(p.stat().st_size for p in parent_store.rglob("*") if p.is_file())
                if not parent_store.is_dir() or parent_bytes <= 0:
                    raise ValueError("original posterior storage accounting required")
                max_calls = parent["max_calls"] - parent["calls_used"]
                max_bytes -= parent_bytes
                parent_budget = {
                    "summary": str(path.relative_to(root)),
                    "sha256": sha256(path),
                    "calls_used": parent["calls_used"],
                    "posterior_bytes": parent_bytes,
                }
            plan = {
                "schema_version": "arrival_validation_batch_v1",
                "phase": phase,
                "protocol": protocol,
                "target": target,
                "base_git_sha": git_sha(root),
                "code_and_config": pins,
                "cases": cases,
                "max_calls": max_calls,
                "max_posterior_bytes": max_bytes,
                "parent_budget": parent_budget,
                "per_attempt_timeout_seconds": 600,
                "concurrency": 1,
                "cores_per_attempt": 2,
                "versions": {
                    p: version(p)
                    for p in ["pymc", "pytensor", "arviz-stats", "nutpie", "numpy", "h5netcdf"]
                },
                "created_utc": datetime.now(UTC).isoformat(),
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
        if state["plan_sha256"] != sha256(output / "plan.json"):
            raise ValueError("checkpoint plan identity changed")
        parent = plan.get("parent_budget")
        if parent and sha256(root / parent["summary"]) != parent["sha256"]:
            raise ValueError("original parent budget changed; reconcile before follow-up")
        atomic_state(state_path, state)
        completed_here = 0
        stop = output / "jobs/STOP"
        while state["next_case"] < len(plan["cases"]):
            if max_cases is not None and completed_here >= max_cases:
                state["status"] = "invocation_limit"
                break
            if stop.exists():
                state["status"] = "stop_signal"
                break
            if any(sha256(root / name) != digest for name, digest in pins.items()):
                raise ValueError("source changed during batch")
            if parent and sha256(root / parent["summary"]) != parent["sha256"]:
                raise ValueError("original parent budget changed during follow-up")
            if state["calls_used"] >= plan["max_calls"]:
                state["status"] = "call_ceiling"
                break
            used = sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
            if used >= plan["max_posterior_bytes"]:
                state["status"] = "storage_ceiling"
                break
            case = plan["cases"][state["next_case"]]
            history = [item for item in state["attempts"] if item["case_id"] == case["id"]]
            repair = any(item["outcome"] == "precision_failure" for item in history)
            job = dict(case["job"])
            if repair:
                job.update({"draws": min(4000, job["draws"] * 2), "tune": 2000})
            attempt = len(history) + 1
            name = case["id"] + f"-attempt-{attempt}"
            attempt_path, posterior = output / "jobs" / name, store / (name + ".nc")
            job_path = output / "jobs" / (name + "-spec.json")
            write_json(job_path, job)
            state["calls_used"] += 1
            state["current"] = {
                "case_id": case["id"],
                "attempt": attempt,
                "output": str(attempt_path),
                "seed": job["seed"],
            }
            state["status"] = "running"
            atomic_state(state_path, state)
            command = [
                sys.executable,
                str(root / "scripts/run_arrival_model_validation.py"),
                "--worker",
                "--job",
                str(job_path),
                "--output",
                str(attempt_path),
                "--store",
                str(posterior),
                "--max-output-bytes",
                str(plan["max_posterior_bytes"] - used),
            ]
            try:
                receipt = supervise(command, attempt_path.with_suffix(".log"), stop, 600)
            except KeyboardInterrupt:
                state["attempts"].append({**state["current"], "outcome": "interrupted"})
                state.update({"current": None, "status": "interrupted"})
                atomic_state(state_path, state)
                raise
            receipt.update(
                {
                    "job_sha256": sha256(job_path),
                    "controller_sha256": pins[CONSUMED[0]],
                    "worker_entry_sha256": pins[CONSUMED[1]],
                }
            )
            write_json(attempt_path.with_suffix(".supervisor.json"), receipt)
            result_path = attempt_path / "result.json"
            if receipt["returncode"] != 0 or not result_path.exists():
                outcome = "runtime_failure"
            else:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                diagnostics = result["diagnostics"]
                if not result_matches(root, result, job, posterior, pins):
                    outcome = "identity_failure"
                elif diagnostics["screen_passed"]:
                    outcome = "accepted"
                elif (
                    not repair
                    and diagnostics["finite_diagnostics"]
                    and diagnostics["divergences"] == 0
                    and diagnostics["maxdepth_reached"] == 0
                    and diagnostics["min_bfmi"] >= 0.3
                    and diagnostics["max_rhat"] <= 1.03
                ):
                    outcome = "precision_failure"
                else:
                    outcome = "diagnostic_failure"
            used_after = sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
            if used_after > plan["max_posterior_bytes"]:
                outcome = "storage_failure"
            state["attempts"].append(
                {
                    **state["current"],
                    "outcome": outcome,
                    "files": attempt_files(attempt_path, job_path, posterior),
                }
            )
            state["current"] = None
            if outcome == "accepted":
                state["next_case"] += 1
                completed_here += 1
            elif outcome != "precision_failure":
                state["status"] = "needs_review"
                atomic_state(state_path, state)
                break
            atomic_state(state_path, state)
            if state["next_case"] % 10 == 0 or outcome != "accepted":
                print(
                    f"{phase}: {state['next_case']}/{len(plan['cases'])} datasets; "
                    f"{state['calls_used']} calls; {outcome}",
                    flush=True,
                )
        if state["next_case"] == len(plan["cases"]):
            state["status"] = "computations_complete"
        atomic_state(state_path, state)
        _report(output, state, plan)
        print(f"{phase}: {state['status']}; {state['next_case']}/{len(plan['cases'])}", flush=True)
    finally:
        lease.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["recovery", "sbc"], required=True)
    parser.add_argument(
        "--target",
        choices=["NCEI-native-duration", "T-OBS", "T-CAL"],
        default="NCEI-native-duration",
    )
    parser.add_argument(
        "--protocol", choices=["core", "combined-followup", "distance-scale"], default="core"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int)
    args = parser.parse_args()
    run_batch(
        Path(__file__).resolve().parents[1],
        args.phase,
        args.output.resolve(),
        args.store.resolve(),
        args.state.resolve(),
        max_cases=args.max_cases,
        resume=args.resume,
        protocol=args.protocol,
        target=args.target,
    )


if __name__ == "__main__":
    main()
