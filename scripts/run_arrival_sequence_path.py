"""Finite squared-path integration with independently checked parent-budget conservation."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_bridge import bridge_score  # noqa: E402
from analysis.arrival.model_bridge_path import path_score  # noqa: E402
from analysis.arrival.model_sequence_path_fit import (  # noqa: E402
    fixed_temperatures,
    path_jobs,
    read_sequence_node,
    validated_design,
)
from scripts.run_arrival_bridge_path import _files  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha, validate_checkpoint  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402


def check_live_parent_budget(root, design):
    spec = design["spec"]
    live = json.loads((checked_path(root, spec["parent_output"]) / "run-summary.json").read_text())
    copied = json.loads(checked_path(root, spec["budget_snapshot"]).read_text())
    if live != copied:
        raise ValueError("live parent budget changed before external sampling")


def prepare_sequence_path(root, manifest):
    design = validated_design(root, manifest)
    spec = design["spec"]
    design.update(
        parent_calls=spec["parent_call_slots"],
        parent_call_ceiling=spec["global_call_ceiling"],
        max_raw_bytes=spec["max_raw_bytes"],
        prior_raw_stores=spec["prior_raw_stores"],
        external_endpoint=spec["external_endpoint"],
    )
    check_live_parent_budget(root, design)
    return design


def _used_bytes(design, store):
    root = design["root"]
    return checked_path(root, design["external_endpoint"]).stat().st_size + sum(
        p.stat().st_size
        for folder in [store, *[checked_path(root, p) for p in design["prior_raw_stores"]]]
        for p in folder.rglob("*")
        if p.is_file()
    )


def run_sequence_path(root, manifest, output, store, state_path, *, resume=False, max_cases=None):
    root, manifest, output, store, state_path = (
        p.resolve() for p in [root, manifest, output, store, state_path]
    )
    if (
        not all(p.is_relative_to(root) for p in [manifest, output, store, state_path])
        or max_cases is not None
        and (type(max_cases) is not int or max_cases < 0)
    ):
        raise ValueError("project-local fixed path and nonnegative invocation ceiling required")
    design = prepare_sequence_path(root, manifest)
    design["root"] = root
    folders = [store, *[checked_path(root, p) for p in design["prior_raw_stores"]]]
    if len(set(folders)) != len(folders) or any(
        a.is_relative_to(b) or b.is_relative_to(a)
        for j, a in enumerate(folders)
        for b in folders[j + 1 :]
    ):
        raise ValueError("disjoint project-local path raw stores required")
    cases = [
        {"id": f"{j['path_role']}-node-{j['node']:02d}", "job": j}
        for j in path_jobs(design["spec"])
    ]
    if resume:
        plan = json.loads((output / "plan.json").read_text())
        state = json.loads(state_path.read_text())
        if plan["raw_store"] != str(store.relative_to(root)):
            raise ValueError("raw store changed")
        if state["current"] is not None:
            raise ValueError("unfinished path node requires reconciliation")
        validate_checkpoint(state, plan)
    elif output.exists() or store.exists() or state_path.exists():
        raise ValueError("new path run paths required")
    pins = design["files"]
    if resume:
        if (
            plan["cases"] != cases
            or plan["files"] != pins
            or state["plan_sha256"] != sha256(output / "plan.json")
            or plan["max_calls"] != 32
            or plan["parent_calls"] != design["parent_calls"]
            or plan["global_call_ceiling"] != design["parent_call_ceiling"]
            or plan["max_raw_bytes"] != design["max_raw_bytes"]
            or plan["prior_raw_stores"] != design["prior_raw_stores"]
            or plan["external_endpoint"] != design["external_endpoint"]
            or plan["design_manifest"] != str(manifest.relative_to(root))
            or plan["temperatures"] != fixed_temperatures().tolist()
            or plan["endpoint_metadata"] != design["endpoint_metadata"]
            or plan["record_count"] != design["record_count"]
            or plan["jacobian"] != design["jacobian"]
        ):
            raise ValueError("path sources or plan changed")
        for item in state["path_results"].values():
            if sha256(Path(item["path"])) != item["sha256"]:
                raise ValueError("retained path result changed")
    else:
        output.mkdir(parents=True)
        plan = {
            "cases": cases,
            "files": pins,
            "base_git_sha": git_sha(root),
            "max_calls": 32,
            "parent_calls": design["parent_calls"],
            "global_call_ceiling": design["parent_call_ceiling"],
            "max_raw_bytes": design["max_raw_bytes"],
            "raw_store": str(store.relative_to(root)),
            "prior_raw_stores": design["prior_raw_stores"],
            "external_endpoint": design["external_endpoint"],
            "design_manifest": str(manifest.relative_to(root)),
            "endpoint_metadata": design["endpoint_metadata"],
            "record_count": design["record_count"],
            "jacobian": design["jacobian"],
            "temperatures": fixed_temperatures().tolist(),
            "per_node_seconds": 600,
            "per_file_bytes": 64 * 1024**2,
            "cores": 2,
            "concurrency": 1,
            "repairs": "none_absolute_thirtytwo_call_ceiling",
            "primary": "primary_repeat_is_validation_only",
        }
        write_json(output / "plan.json", plan)
        state = {
            "next_case": 0,
            "calls_used": 0,
            "attempts": [],
            "current": None,
            "status": "prepared",
            "path_results": {},
            "plan_sha256": sha256(output / "plan.json"),
        }
    nodes = dict(design["endpoint_logs"])
    for attempt in state["attempts"]:
        if attempt["outcome"] == "accepted":
            job = next(c["job"] for c in cases if c["id"] == attempt["case_id"])
            nodes[(job["path_role"], job["node"])] = read_sequence_node(
                root, Path(attempt["output"]), job, design
            )
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    try:
        atomic_state(state_path, state)
        completed_here = 0
        while state["next_case"] < 32:
            if max_cases is not None and completed_here >= max_cases:
                state["status"] = "invocation_limit"
                break
            if (output / "jobs/STOP").exists():
                state["status"] = "stop_signal"
                break
            if any(sha256(root / p) != h for p, h in pins.items()):
                raise ValueError("path inputs changed")
            check_live_parent_budget(root, design)
            case = cases[state["next_case"]]
            job = case["job"]
            role, node = job["path_role"], job["node"]
            reserve = (3 if node == (15 if role == "primary" else 16) else 2) * plan[
                "per_file_bytes"
            ]
            if (
                state["calls_used"] >= 32
                or plan["parent_calls"] + state["calls_used"] >= plan["global_call_ceiling"]
                or _used_bytes(design, store) + reserve > plan["max_raw_bytes"]
            ):
                state["status"] = "budget_limit"
                break
            attempt = output / "jobs" / case["id"]
            spec = output / "jobs" / (case["id"] + "-spec.json")
            raw = store / (case["id"] + ".nc")
            write_json(spec, job)
            state["calls_used"] += 1
            state["current"] = {"case_id": case["id"], "attempt": 1, "output": str(attempt)}
            state["status"] = "running"
            atomic_state(state_path, state)
            outcome = "runtime_failure"
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/sample_arrival_sequence_path.py"),
                        "--worker",
                        "--design",
                        str(manifest),
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
                write_json(attempt.with_suffix(".supervisor.json"), receipt)
                if receipt["returncode"] == 0 and receipt["reason"] == "worker_exit":
                    values = read_sequence_node(root, attempt, job, design)
                    nodes[(role, node)] = values
                    outcome = "accepted"
                    for edge in [node - 1, node]:
                        if (role, edge) in nodes and (role, edge + 1) in nodes:
                            check, _, _ = bridge_score(
                                nodes[(role, edge)]
                                * (fixed_temperatures()[edge + 1] - fixed_temperatures()[edge]),
                                nodes[(role, edge + 1)]
                                * (fixed_temperatures()[edge + 1] - fixed_temperatures()[edge]),
                                records=design["record_count"],
                            )
                            write_json(
                                attempt / "edge-checks" / f"{edge:02d}-{edge + 1:02d}.json", check
                            )
                            if not check["precision_passed"]:
                                outcome = "edge_failure"
                                break
                    if outcome == "accepted" and node == (15 if role == "primary" else 16):
                        summary, combined = path_score(
                            [nodes[(role, i)] for i in range(17)],
                            fixed_temperatures(),
                            records=design["record_count"],
                            jacobian=design["jacobian"],
                        )
                        summary.update(
                            event_id=design["spec"]["event_id"],
                            sequence=design["spec"]["sequence"],
                            records=design["record_count"],
                            target="NCEI-native-duration",
                            kind="distance-scale",
                            source_training_posterior_sha=(
                                design["endpoint_metadata"][0]["posterior_sha256"]
                                if role == "primary"
                                else json.loads(
                                    (output / "jobs/repeat-node-00/result.json").read_text()
                                )["posterior_sha256"]
                            ),
                        )
                        target = output / f"{role}-path-result.json"
                        write_json(target, summary)
                        state["path_results"][role] = {
                            "path": str(target),
                            "sha256": sha256(target),
                        }
                        np.savez_compressed(
                            store / f"{role}-combined-influences.npz",
                            **{f"node_{i}": a for i, a in enumerate(combined)},
                        )
                        if not summary["precision_passed"]:
                            outcome = "path_precision_failure"
                        elif role == "repeat":
                            primary = json.loads(
                                Path(state["path_results"]["primary"]["path"]).read_text()
                            )
                            difference = abs(
                                primary["joint_log_predictive"] - summary["joint_log_predictive"]
                            )
                            error = math.hypot(
                                primary["joint_log_mcse_delta"], summary["joint_log_mcse_delta"]
                            )
                            agreed = difference <= 3 * error + 1e-6
                            write_json(
                                output / "independent-repeat-check.json",
                                {
                                    "primary_designated_before_fitting": True,
                                    "raw_difference": difference,
                                    "combined_mcse": error,
                                    "agreement_passed": agreed,
                                    "score_to_use": "primary_never_select_favorable_repeat",
                                },
                            )
                            if not agreed:
                                outcome = "independent_repeat_disagreement"
                elif receipt["reason"] == "worker_exit" and receipt["returncode"] == 2:
                    result = json.loads((attempt / "result.json").read_text())
                    if result["job"] != job:
                        outcome = "identity_failure"
                    elif result["status"] in {"backend_failure", "diagnostic_failure"}:
                        outcome = result["status"]
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
            except Exception as exc:
                write_json(attempt / "evaluation-failure.json", {"error": str(exc)})
                outcome = "identity_or_evaluation_failure"
            if any(sha256(root / p) != h for p, h in pins.items()):
                outcome = "identity_failure"
            if _used_bytes(design, store) > plan["max_raw_bytes"]:
                outcome = "storage_budget_failure"
            state["attempts"].append(
                {**state["current"], "outcome": outcome, "files": _files(attempt, spec, raw)}
            )
            state["current"] = None
            if outcome == "accepted":
                state["next_case"] += 1
                completed_here += 1
            else:
                state["status"] = "needs_review"
            atomic_state(state_path, state)
            print(
                f"fixed path {state['next_case']}/32; newcalls {state['calls_used']}; {outcome}",
                flush=True,
            )
            if state["status"] == "needs_review":
                break
        if state["next_case"] == 32:
            state["status"] = "computations_complete"
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "accepted_new_nodes": state["next_case"],
                "new_call_slots_used": state["calls_used"],
                "new_call_ceiling": 32,
                "parent_call_slots": plan["parent_calls"],
                "global_call_ceiling": plan["global_call_ceiling"],
                "remaining_global_calls": plan["global_call_ceiling"]
                - plan["parent_calls"]
                - state["calls_used"],
                "primary_score_acceptance": "pending_independent_actual_replay",
                "reserved_outcomes": "sealed",
            },
        )
    finally:
        lease.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--design", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cases", type=int)
    a = p.parse_args()
    run_sequence_path(
        Path(__file__).resolve().parents[1],
        a.design,
        a.output,
        a.store,
        a.state,
        resume=a.resume,
        max_cases=a.max_cases,
    )
