"""One finite32-node numerical amendment on the original248-slot curvature ledger."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa:E402
from analysis.arrival.model_bridge import bridge_score  # noqa:E402
from analysis.arrival.model_bridge_path import path_score  # noqa:E402
from analysis.arrival.model_curvature_path_sampling import (  # noqa:E402
    GATE,
    OUTPUT,
    STORE,
    load_design,
    path_jobs,
    read_endpoint,
    read_node,
    temperatures,
)
from scripts.run_arrival_curvature_sequences import (
    MAX_CACHE,
    MAX_CALLS,
    MAX_GLOBAL,
    MAX_JOB,
    MAX_LOCAL,
    MIB,
    RESERVE,
    STATE,
    byte_count,
    case_artifacts,
    parent_roots,
    quota_failure,
    verify_rehearsal,
)
from scripts.run_arrival_curvature_sequences import (  # noqa:E402
    OUTPUT as PARENT_OUTPUT,
)
from scripts.run_arrival_curvature_sequences import (
    STORE as PARENT_STORE,
)
from scripts.run_arrival_model_batch import atomic_state  # noqa:E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa:E402


def attempt_files(root, job, *, complete=False):
    folder = root / OUTPUT / "jobs" / job["id"]
    raw = root / STORE / (job["id"] + ".nc")
    mandatory = [
        folder / name
        for name in [
            "job.json",
            "inputs.json",
            "membership.json",
            "sampling-start.json",
            "sampling-diagnostics.csv",
            "result.json",
        ]
    ]
    mandatory += [
        raw,
        raw.with_suffix(".loglikelihood.npz"),
        folder.with_name(job["id"] + "-spec.json"),
        folder.with_suffix(".log"),
        folder.with_suffix(".supervisor.json"),
    ]
    if complete and not all(p.is_file() for p in mandatory):
        raise ValueError("complete mandatory node evidence required")
    if complete:
        supervisor = json.loads(folder.with_suffix(".supervisor.json").read_text())
        if (
            supervisor.get("returncode") != 0
            or supervisor.get("reason") != "worker_exit"
            or supervisor.get("job_sha256") != sha256(folder.with_name(job["id"] + "-spec.json"))
            or supervisor.get("plan_sha256") != sha256(root / OUTPUT / "plan.json")
            or supervisor.get("monitor_failures")
            or json.loads((folder / "job.json").read_text()) != job
            or json.loads((folder / "sampling-start.json").read_text()) != job
        ):
            raise ValueError("complete successful node process and job proof required")
    paths = {p for p in folder.rglob("*") if p.is_file() and p.name != "attempt-evidence.json"}
    paths.update(
        p
        for p in [
            raw,
            raw.with_suffix(".loglikelihood.npz"),
            folder.with_name(job["id"] + "-spec.json"),
            folder.with_suffix(".log"),
            folder.with_suffix(".supervisor.json"),
        ]
        if p.is_file()
    )
    return {str(p.relative_to(root)): sha256(p) for p in paths}


def working_bytes(root, parents):
    return byte_count(
        *parents,
        root / PARENT_OUTPUT,
        root / PARENT_STORE,
        root / "artifacts/models/arrival-timing/mean-curvature-sequence-design-v1",
        (root / GATE).parent,
    )


def path_quota_failure(root, parents, current=None):
    return quota_failure(root, parents, current) or (
        "global_storage_including_path_design"
        if working_bytes(root, parents) > MAX_GLOBAL
        else None
    )


def files_changed(root, files):
    return any(not (root / p).is_file() or sha256(root / p) != h for p, h in files.items())


def validate_timings(root, path):
    if (
        type(path.get("active_seconds")) not in {int, float}
        or not math.isfinite(path["active_seconds"])
        or not 0 <= path["active_seconds"] <= 1200
        or type(path.get("next_node")) is not int
        or not 0 <= path["next_node"] <= 32
    ):
        raise ValueError("finite nonnegative bounded active time and node count required")
    cursor, total, expected = 0, 0.0, set()
    for j, entry in enumerate(path.get("invocations", [])):
        name = OUTPUT + f"/invocations/{j:03d}.json"
        if entry.get("path") != name or sha256(root / name) != entry.get("sha256"):
            raise ValueError("immutable invocation timing receipt changed")
        item = json.loads((root / name).read_text())
        if (
            item.get("plan_sha256") != path["plan_sha256"]
            or item.get("start_node") != cursor
            or not cursor < item.get("end_node", -1) <= cursor + 3
            or type(item.get("seconds")) not in {int, float}
            or not math.isfinite(item["seconds"])
            or not 0 <= item["seconds"] <= 1200
        ):
            raise ValueError("complete contiguous invocation timing required")
        attempts = path["attempts"][item["start_node"] : item["end_node"]]
        if item.get("attempt_receipts") != {
            a["receipt"]: a["receipt_sha256"] for a in attempts
        } or any(
            path.get("aggregate_files", {}).get(p) != h
            for p, h in item.get("aggregate_files", {}).items()
        ):
            raise ValueError("invocation evidence closure changed")
        cursor = item["end_node"]
        total += item["seconds"]
        expected.add(root / name)
    actual = {p for p in (root / OUTPUT / "invocations").rglob("*") if p.is_file()}
    if (
        actual != expected
        or cursor != path["next_node"]
        or not math.isclose(total, path["active_seconds"], abs_tol=1e-9, rel_tol=0)
    ):
        raise ValueError("cumulative active time cannot be reset or omit an invocation")
    return total


def summarize_path(root, design, nodes, role):
    score, combined = path_score(
        [nodes[(role, j)] for j in range(17)],
        temperatures(),
        records=len(design["held"]),
        jacobian=float(np.log(design["lane"].y[design["held"]]).sum()),
    )
    source_sha = (
        read_endpoint(root, design, 0)[1]
        if role == "primary"
        else json.loads((root / OUTPUT / "jobs/repeat-node-00/result.json").read_text())[
            "posterior_sha256"
        ]
    )
    score.update(
        event_id="official20110311054624120_30",
        sequence="seq-official20110311054624120_30",
        records=len(design["held"]),
        target="NCEI-native-duration",
        kind="mean-curvature",
        source_training_posterior_sha=source_sha,
    )
    write_json(root / OUTPUT / (role + "-path-result.json"), score)
    np.savez_compressed(
        root / STORE / (role + "-combined-influences.npz"),
        **{f"node_{j}": v for j, v in enumerate(combined)},
    )
    if not score["precision_passed"]:
        raise ValueError("path precision failed")
    if role == "repeat":
        first = json.loads((root / OUTPUT / "primary-path-result.json").read_text())
        difference = abs(first["joint_log_predictive"] - score["joint_log_predictive"])
        error = math.hypot(first["joint_log_mcse_delta"], score["joint_log_mcse_delta"])
        passed = difference <= 3 * error + 1e-6
        write_json(
            root / OUTPUT / "independent-repeat-check.json",
            {
                "raw_difference": difference,
                "combined_mcse": error,
                "agreement_passed": passed,
                "primary_designated_before_fitting": True,
                "score_to_use": "primary_never_select_favorable_repeat",
            },
        )
        if not passed:
            raise ValueError("independent repeat disagreement")


def validate_aggregates(root, path):
    expected = set()
    for role, required in [
        ("primary", path["next_node"] >= 15),
        ("repeat", path["next_node"] == 32),
    ]:
        if required:
            expected.update(
                [OUTPUT + f"/{role}-path-result.json", STORE + f"/{role}-combined-influences.npz"]
            )
    if path["next_node"] == 32:
        expected.add(OUTPUT + "/independent-repeat-check.json")
    files = path.get("aggregate_files", {})
    if set(files) != expected or files_changed(root, files):
        raise ValueError("retained aggregate score and influence closure changed")


def run(root, *, resume=False, max_nodes=3):
    if type(max_nodes) is not int or not 1 <= max_nodes <= 3:
        raise ValueError("one through three nodes per invocation")
    started = time.monotonic()
    root = root.resolve()
    output = root / OUTPUT
    store = root / STORE
    state_path = root / STATE
    os.environ.update(
        PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={root / PARENT_STORE}/cache/pytensor",
        NUMBA_CACHE_DIR=str(root / PARENT_STORE / "cache/numba"),
        MPLCONFIGDIR=str(root / PARENT_STORE / "cache/matplotlib"),
    )
    design = load_design(root)
    gate = design["gate"]
    jobs = path_jobs()
    parents = parent_roots(root)
    resources = {
        "global_max_bytes": MAX_GLOBAL,
        "local_max_bytes": MAX_LOCAL,
        "cache_max_bytes": MAX_CACHE,
        "job_max_bytes": MAX_JOB,
        "next_invocation_reserve_bytes": RESERVE,
        "per_file_bytes": 64 * MIB,
        "per_node_seconds": 600,
        "whole_active_allocation_seconds": 1200,
        "concurrency": 1,
        "automatic_retries": 0,
        "max_nodes_per_invocation": 3,
    }
    if gate.get("resources") != resources:
        raise ValueError("frozen path runtime/resource design required")
    floors = gate.get("parent_minimum_bytes", {})
    if set(floors) != {str(p.relative_to(root)) for p in parents} or any(
        not (root / p).is_dir() or byte_count(root / p) < n for p, n in floors.items()
    ):
        raise ValueError("preserved cumulative parent accounting required")
    state = json.loads(state_path.read_text())
    parent_plan = json.loads((root / PARENT_OUTPUT / "plan.json").read_text())
    if state.get("plan_sha256") != sha256(root / PARENT_OUTPUT / "plan.json"):
        raise ValueError("original parent plan identity changed")
    if verify_rehearsal(root, state) != state.get("rehearsal_sha256"):
        raise ValueError("original independently accepted rehearsal changed")
    for case, accepted in zip(parent_plan["cases"][:2], state.get("accepted", []), strict=True):
        case_artifacts(
            root, case, parent_plan["memberships"][case["id"]], parent_plan["files"], accepted
        )
    lease = root / PARENT_OUTPUT / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = output / "STOP"

    active_before = [0.0]

    def monitor():
        while not ended.wait(0.1):
            reason = path_quota_failure(root, parents, current[0])
            if active_before[0] + time.monotonic() - started > 1200:
                reason = "active_allocation_time"
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    try:
        if resume:
            if not output.is_dir() or not store.is_dir():
                raise ValueError("original path stores required")
            plan = json.loads((output / "plan.json").read_text())
            path = state.get("path_amendment", {})
            if (
                plan.get("files") != design["files"]
                or plan.get("jobs") != jobs
                or plan.get("resources") != resources
                or path.get("plan_sha256") != sha256(output / "plan.json")
                or state.get("status") not in {"path_checkpoint", "path_computations_complete"}
                or state.get("current") is not None
                or state.get("calls_charged") != 38
                or state.get("next_fold") != 2
                or path.get("next_node") != len(path.get("attempts", []))
                or state.get("calls_started") != 6 + len(path.get("attempts", []))
            ):
                raise ValueError("changed or failed path ledger requires reviewed reconciliation")
        else:
            if output.exists() or store.exists() or "path_amendment" in state:
                raise ValueError("new canonical path allocation required")
            expected = {
                "status": "precision_or_diagnostic_failure",
                "calls_charged": 6,
                "calls_started": 6,
                "next_fold": 2,
                "current": None,
            }
            if (
                any(state.get(k) != v for k, v in expected.items())
                or len(state.get("accepted", [])) != 2
            ):
                raise ValueError("exact retained six-call numerical stop required")
            if gate.get("parent_checkpoint") != expected:
                raise ValueError("frozen parent checkpoint required")
            if (
                byte_count(root / PARENT_OUTPUT, root / PARENT_STORE) + RESERVE > MAX_LOCAL
                or working_bytes(root, parents) + RESERVE > MAX_GLOBAL
            ):
                raise ValueError("shared working-store reserve unavailable")
            output.mkdir(parents=True)
            store.mkdir(parents=True)
            plan = {
                "files": design["files"],
                "jobs": jobs,
                "resources": resources,
                "canonical_state_path": STATE,
                "parent_calls_charged": 6,
                "reserved_new_slots": 32,
                "global_call_ceiling": 248,
                "original_endpoints_reused": True,
                "primary_designated_before_repeat": True,
                "time_scope": "active controller invocations inclpreflight; QA pauseexcluded",
            }
            write_json(output / "plan.json", plan)
            path = {
                "next_node": 0,
                "attempts": [],
                "aggregate_files": {},
                "invocations": [],
                "active_seconds": 0.0,
                "plan_sha256": sha256(output / "plan.json"),
            }
            state.update(path_amendment=path, calls_charged=38, status="path_checkpoint")
            atomic_state(state_path, state)
        validate_aggregates(root, path)
        prior_active = validate_timings(root, path)
        start_node = path["next_node"]
        nodes = {("primary", j): read_endpoint(root, design, j)[0] for j in [0, 16]}
        for job, attempt in zip(jobs, path["attempts"], strict=False):
            if (
                attempt.get("job") != job
                or attempt.get("outcome") != "accepted"
                or attempt.get("files") != attempt_files(root, job, complete=True)
            ):
                raise ValueError("retained path node closure changed")
            manifest = root / OUTPUT / "jobs" / job["id"] / "attempt-evidence.json"
            if (
                attempt.get("receipt") != str(manifest.relative_to(root))
                or sha256(manifest) != attempt.get("receipt_sha256")
                or json.loads(manifest.read_text())
                != {"job": job, "outcome": "accepted", "files": attempt["files"]}
            ):
                raise ValueError("immutable complete node attempt receipt changed")
            nodes[(job["path_role"], job["node"])] = read_node(root, job, design)
        expected_raw = {
            name for a in path["attempts"] for name in a["files"] if name.startswith(STORE + "/")
        }
        if path["next_node"] >= 15:
            expected_raw.add(STORE + "/primary-combined-influences.npz")
        if path["next_node"] == 32:
            expected_raw.add(STORE + "/repeat-combined-influences.npz")
        if {str(p.relative_to(root)) for p in store.rglob("*") if p.is_file()} != expected_raw:
            raise ValueError("unexpected retained raw partial or omission")
        if state["status"] == "path_computations_complete":
            if sha256(output / "run-summary.json") != path.get("final_summary_sha256"):
                raise ValueError("completed path summary changed")
            return
        limit_worker_file_size(64 * MIB)
        watcher.start()
        active_before[0] = prior_active
        for _ in range(max_nodes):
            validate_aggregates(root, path)
            if path["next_node"] == 32:
                break
            remaining = 1200 - prior_active - (time.monotonic() - started)
            if (
                remaining < 1
                or stop.exists()
                or failures
                or path_quota_failure(root, parents)
                or byte_count(root / PARENT_OUTPUT, root / PARENT_STORE) + RESERVE > MAX_LOCAL
                or working_bytes(root, parents) + RESERVE > MAX_GLOBAL
            ):
                state["status"] = "path_stop_or_budget_failure"
                break
            if files_changed(root, design["files"]):
                raise ValueError("path source drift")
            job = jobs[path["next_node"]]
            folder = output / "jobs" / job["id"]
            raw = store / (job["id"] + ".nc")
            spec = folder.with_name(job["id"] + "-spec.json")
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
                raise ValueError("original path attempt retained; no overwrite")
            write_json(spec, job)
            state.update(current=job["id"], status="path_running")
            atomic_state(state_path, state)
            current[0] = folder
            outcome = "runtime_failure"
            receipt = {}
            node_started = time.monotonic()
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/sample_arrival_curvature_path.py"),
                        "--job",
                        str(spec),
                        "--output",
                        str(folder),
                        "--store",
                        str(raw),
                    ],
                    folder.with_suffix(".log"),
                    stop,
                    min(600, int(remaining)),
                )
                if receipt["reason"] == "worker_exit" and receipt["returncode"] == 0:
                    values = read_node(root, job, design)
                    role, node = job["path_role"], job["node"]
                    nodes[(role, node)] = values
                    outcome = "accepted"
                    for edge in [node - 1, node]:
                        if (role, edge) in nodes and (role, edge + 1) in nodes:
                            delta = temperatures()[edge + 1] - temperatures()[edge]
                            check, _, _ = bridge_score(
                                delta * nodes[(role, edge)],
                                delta * nodes[(role, edge + 1)],
                                records=len(design["held"]),
                            )
                            write_json(
                                folder / "edge-checks" / f"{edge:02d}-{edge + 1:02d}.json", check
                            )
                            if not check["precision_passed"]:
                                outcome = "edge_failure"
                                break
                    if outcome == "accepted" and node == (15 if role == "primary" else 16):
                        summarize_path(root, design, nodes, role)
            except Exception as exc:
                write_json(folder / "evaluation-failure.json", {"error": str(exc)})
                outcome = "evaluation_failure"
                if not receipt:
                    receipt = {
                        "returncode": None,
                        "reason": "launch_or_supervisor_failure",
                        "error": str(exc),
                    }
            except KeyboardInterrupt:
                outcome = "interrupted"
                receipt = {"returncode": 130, "reason": "interrupt"}
            receipt.setdefault("elapsed_seconds", time.monotonic() - node_started)
            write_json(
                folder.with_suffix(".supervisor.json"),
                {
                    **receipt,
                    "job_sha256": sha256(spec),
                    "plan_sha256": path["plan_sha256"],
                    "monitor_failures": list(failures),
                },
            )
            if (folder / "sampling-start.json").exists():
                state["calls_started"] += 1
            current[0] = None
            state["current"] = None
            aggregate_changed = files_changed(root, path["aggregate_files"])
            if aggregate_changed or files_changed(root, design["files"]):
                outcome = "source_or_aggregate_changed_during_node"
            aggregate_paths = [
                *output.glob("*-path-result.json"),
                *store.glob("*-combined-influences.npz"),
            ]
            if (output / "independent-repeat-check.json").exists():
                aggregate_paths.append(output / "independent-repeat-check.json")
            path["aggregate_files"].update(
                {
                    str(p.relative_to(root)): sha256(p)
                    for p in aggregate_paths
                    if str(p.relative_to(root)) not in path["aggregate_files"]
                }
            )
            if failures or path_quota_failure(root, parents, folder):
                outcome = "storage_failure"
            files = attempt_files(root, job, complete=outcome == "accepted")
            manifest = folder / "attempt-evidence.json"
            write_json(manifest, {"job": job, "outcome": outcome, "files": files})
            path["attempts"].append(
                {
                    "job": job,
                    "outcome": outcome,
                    "files": files,
                    "receipt": str(manifest.relative_to(root)),
                    "receipt_sha256": sha256(manifest),
                }
            )
            if outcome == "accepted":
                path["next_node"] += 1
            path["active_seconds"] = prior_active + time.monotonic() - started
            state["status"] = (
                ("path_computations_complete" if path["next_node"] == 32 else "path_checkpoint")
                if outcome == "accepted"
                else "path_needs_review"
            )
            atomic_state(state_path, state)
            print(
                f"curvature path {path['next_node']}/32; totalcharged38/248; {outcome}", flush=True
            )
            if outcome != "accepted":
                break
        duration = time.monotonic() - started
        timing = output / "invocations" / f"{len(path['invocations']):03d}.json"
        if timing.exists():
            raise ValueError("original invocation timing receipt retained")
        write_json(
            timing,
            {
                "plan_sha256": path["plan_sha256"],
                "start_node": start_node,
                "end_node": path["next_node"],
                "seconds": duration,
                "status": state["status"],
                "attempt_receipts": {
                    a["receipt"]: a["receipt_sha256"]
                    for a in path["attempts"][start_node : path["next_node"]]
                },
                "aggregate_files": path["aggregate_files"],
            },
        )
        path["invocations"].append(
            {"path": str(timing.relative_to(root)), "sha256": sha256(timing)}
        )
        path["active_seconds"] = prior_active + duration
        if path["active_seconds"] > 1200:
            state["status"] = "path_active_time_failure"
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "accepted_nodes": path["next_node"],
                "new_slots_charged": 32,
                "total_curvature_calls_charged": 38,
                "total_curvature_calls_started": state["calls_started"],
                "max_curvature_slots": MAX_CALLS,
                "active_seconds": path["active_seconds"],
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
                "primary_score_acceptance": "pending_independent_replay",
                "working_bytes": working_bytes(root, parents),
            },
        )
        if path_quota_failure(root, parents):
            state["status"] = "path_storage_failure"
            atomic_state(state_path, state)
            summary = json.loads((output / "run-summary.json").read_text())
            summary["status"] = state["status"]
            write_json(output / "run-summary.json", summary)
        if state["status"] == "path_computations_complete":
            path["final_summary_sha256"] = sha256(output / "run-summary.json")
            atomic_state(state_path, state)
        if state["status"] not in {"path_checkpoint", "path_computations_complete"}:
            raise SystemExit(2)
    finally:
        ended.set()
        if watcher.is_alive():
            watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-nodes", type=int, default=3)
    a = p.parse_args()
    run(Path(__file__).resolve().parents[1], resume=a.resume, max_nodes=a.max_nodes)
