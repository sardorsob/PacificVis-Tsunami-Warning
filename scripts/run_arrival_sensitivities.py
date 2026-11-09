"""Finite serial MS-5 execution; every result remains pending scientific review."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_sensitivity_fit as fit  # noqa:E402
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa:E402
from analysis.arrival.model_sensitivity_design import PILOTS  # noqa:E402
from scripts import run_arrival_curvature_final_continuation as final_continuation  # noqa:E402
from scripts import run_arrival_curvature_sequences as original  # noqa:E402
from scripts.run_arrival_model_batch import atomic_state  # noqa:E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa:E402

GATE, OUTPUT, STORE = fit.GATE, fit.OUTPUT, fit.STORE
case_artifacts, verify_gate = fit.case_artifacts, fit.verify_gate
MAX_CACHE, MAX_GLOBAL, MAX_JOB = original.MAX_CACHE, original.MAX_GLOBAL, original.MAX_JOB
MAX_LOCAL, MIB, RESERVE = original.MAX_LOCAL, original.MIB, original.RESERVE
byte_count, parent_floors = original.byte_count, original.parent_floors
parent_roots, OLD_OUTPUT = original.parent_roots, original.OUTPUT

SELF = "scripts/run_arrival_sensitivities.py"
STATE = "context/runs/arrival-model-fitting-v1/sensitivity-state.json"
DESIGN = str(Path(GATE).parent)
PILOT_REVIEW = OUTPUT + "/pilot-review-acceptance.json"
MAX_CALLS, TIMEOUT, FILE_MAX, WATCH_SECONDS = 110, 600, 64 * MIB, 0.1
RUNTIME = [ SELF, "analysis/arrival/model_sensitivity_fit.py", "scripts/fit_arrival_sensitivity.py",
    "scripts/run_arrival_curvature_final_continuation.py",
    "scripts/run_arrival_curvature_sequences.py", "scripts/run_arrival_curvature_pilot.py",
    "scripts/run_arrival_model_batch.py", "scripts/run_arrival_model_validation.py", ]


def resources(): return {
        "global_max_bytes": MAX_GLOBAL, "local_max_bytes": MAX_LOCAL, "cache_max_bytes": MAX_CACHE,
        "job_max_bytes": MAX_JOB, "file_max_bytes": FILE_MAX,
        "next_invocation_reserve_bytes": RESERVE, "timeout_seconds": TIMEOUT,
        "watcher_seconds": WATCH_SECONDS, "chains": 4, "cores": 2, "draws": 2000, "tune": 1000,
        "initial_cases": 55, "max_sampler_call_slots": MAX_CALLS, }


def path_bindings(root): return {
        "project_root": str(root.resolve()), "output": OUTPUT, "store": STORE,
        "state": str(root.resolve() / STATE), }


def case_paths(root, job):
    folder = root / OUTPUT / "jobs" / job["id"]
    return (
        folder, root / STORE / (job["id"] + ".nc"), folder.with_name(folder.name + "-spec.json"),
        folder.with_name(folder.name + ".log"), folder.with_name(folder.name + ".supervisor.json"),
   )


def working_bytes(root, parents):
    return final_continuation.working_bytes(root, parents) + byte_count(
        root / DESIGN, root / OUTPUT, root / STORE)


def quota_failure(root, parents, gate, current=None, *, reserve=False):
    try:
        parent_floors(root, gate)
        roots = [root / DESIGN, root / OUTPUT, root / STORE]
        for base in roots:
            for path in base.rglob("*"):
                if path.is_symlink():
                    return "symlink_storage"
                try:
                    if path.is_file() and path.stat().st_size > FILE_MAX:
                        return "per_file_storage"
                except FileNotFoundError:
                    continue
        extra = RESERVE if reserve else 0
        if working_bytes(root, parents) + extra > MAX_GLOBAL:
            return "global_storage"
        if byte_count(*roots) + extra > MAX_LOCAL:
            return "local_storage"
        if byte_count(root / STORE / "cache") > MAX_CACHE:
            return "cache_storage"
        if current is not None:
            folder, raw, spec, log, process = case_paths(root, current)
            total = byte_count(folder) + sum(
                p.stat().st_size for p in [raw, spec, log, process] if p.is_file())
            if total > MAX_JOB:
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


def _unchanged(root, pins):
    if any(
        not checked_path(root, path).is_file() or sha256(checked_path(root, path)) != digest
        for path, digest in pins.items()
    ):
        raise ValueError("sensitivity source identity changed")


def new_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


@contextmanager
def _leases(root):
    leases = []
    try:
        for base in [root / OLD_OUTPUT, root / OUTPUT]:
            base.mkdir(parents=True, exist_ok=True)
            path = base / ".controller.lock"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(str(os.getpid()))
            leases.append(path)
        yield
    finally:
        for path in reversed(leases):
            path.unlink()


def _admit(root):
    admission = verify_gate(root)
    gate, pins = admission["gate"], admission["files"]
    jobs = gate["jobs"]
    if (
        gate.get("resources") != resources()
        or gate.get("path_bindings") != path_bindings(root)
        or not set(RUNTIME) <= set(pins)
        or STATE in pins
        or [(job.get("target"), job.get("kind"), job.get("prior_variant")) for job in jobs[:2]]
        != list(PILOTS)
        or [job.get("pilot") for job in jobs] != [True, True] + [False] * 53
    ):
        raise ValueError(
            "exact source-bound55case sensitivity resources/pilots/path identities required"
        )
    _unchanged(root, pins)
    parents = parent_floors(root, gate)
    if len(parents) != 15 or any(
        a == b or a in b.parents or b in a.parents
        for a in parents
        for b in [root / DESIGN, root / OUTPUT, root / STORE]
    ):
        raise ValueError("fifteen preserved nonoverlapping old parent floors required")
    return gate, pins, jobs, parents


def _validate_state(state, jobs):
    next_case = state.get("next_case")
    if (
        type(next_case) is not int
        or not 0 <= next_case <= 55
        or state.get("current") is not None
        or state.get("status")
        not in {
            "sensitivity_checkpoint",
            "sensitivity_pilot_review_required",
            "sensitivity_computations_complete",
        }
        or [item.get("case_id") for item in state.get("accepted", [])]
        != [job["id"] for job in jobs[:next_case]]
        or len(state.get("attempts", [])) != next_case
        or any(
            a.get("case_id") != job["id"]
            or a.get("outcome") != "accepted"
            or a.get("charged_slots") != 1
            or a.get("start_markers") != 1
            for a, job in zip(state["attempts"], jobs[:next_case], strict=True)
        )
        or type(state.get("calls_charged")) is not int
        or type(state.get("calls_started")) is not int
        or state["calls_charged"] != next_case
        or state["calls_started"] != next_case
        or state["calls_charged"] > MAX_CALLS
    ):
        raise ValueError(
            "conserved successful prefix required; "
            "failed/current calls need reviewed reconciliation"
        )
    if (state["status"] == "sensitivity_computations_complete") != (next_case == 55):
        raise ValueError("complete sensitivity status must conserve all55cases")


def _proofs(root, state, jobs, pins):
    for job, accepted, attempt in zip(
        jobs[: state["next_case"]], state["accepted"], state["attempts"], strict=True):
        case_artifacts(root, job, pins, accepted)
        if any(attempt.get(k) != accepted.get(k)
            for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]):
            raise ValueError("attempt and accepted case receipt identities changed")


def _inventory(root, state, current=None):
    raw, jobs_root = root / STORE, root / OUTPUT / "jobs"
    known = {
        path
        for entry in state["accepted"]
        for path in entry["files"]
        if path.startswith(STORE + "/")
    }
    accepted_ids = {entry["case_id"] for entry in state["accepted"]}
    if current is not None:
        known.add(str(case_paths(root, current)[1].relative_to(root)))
        accepted_ids.add(current["id"])
    actual = set()
    for path in raw.rglob("*"):
        if path.is_symlink():
            raise ValueError("raw/cache symlinks are not admitted")
        if path == raw / "cache" or (raw / "cache") in path.parents:
            continue
        if path.is_dir():
            raise ValueError("unknown raw directory retained; no automatic resume")
        if path.is_file():
            actual.add(str(path.relative_to(root)))
    if actual != known:
        raise ValueError("unknown/missing raw partials retained; no automatic resume")
    allowed = set(accepted_ids) | {
        identity + suffix
        for identity in accepted_ids
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    }
    if jobs_root.exists() and any(
        path.name not in allowed or path.is_symlink() for path in jobs_root.iterdir()
    ):
        raise ValueError("unknown case artifact retained; no automatic resume")


def _pilot_review(root, state):
    path = root / PILOT_REVIEW
    if not path.is_file():
        raise ValueError("independent two-pilot runtime/prior review required before case2+")
    review = json.loads(path.read_text())
    required = {OUTPUT + "/plan.json": state["plan_sha256"]}
    for accepted in state["accepted"][:2]:
        required.update(accepted["files"])
        required[accepted["receipt"]] = accepted["receipt_sha256"]
    if (review.get("status") != "accepted_sensitivity_two_case_runtime_and_prior_pilots"
        or review.get("independent_checker") is not True
        or any(review.get("files", {}).get(p) != h for p, h in required.items())):
        raise ValueError("complete independently accepted two-pilot closure required")
    _unchanged(root, review["files"])
    identity = sha256(path)
    if state.get("pilot_review_sha256") not in {None, identity}:
        raise ValueError("accepted pilot review identity changed")
    return identity


def _retained(root, job):
    folder, raw, spec, log, process = case_paths(root, job)
    paths = { path for base in [folder, root / STORE] for path in base.rglob("*")
        if path.is_file() and not path.is_symlink() and (root / STORE / "cache") not in path.parents
    }
    paths.update(
        path for path in [raw, spec, log, process] if path.is_file() and not path.is_symlink())
    return { str(path.relative_to(root)): sha256(path) for path in paths
        if path.name not in {"attempt-evidence.json", "failure-evidence.json"} }


def _dispatch(root, state, job, gate, pins, parents, failures, current, stop):
    folder, raw, spec, log, process = case_paths(root, job)
    if any(path.exists() or path.is_symlink() for path in [folder, raw, spec, log, process]):
        raise ValueError("new sensitivity case paths required; no overwrite or retry")
    new_json(spec, job)
    state.update(
        current=job["id"], status="sensitivity_running", calls_charged=state["calls_charged"] + 1)
    atomic_state(root / STATE, state)
    current[0] = job
    receipt, outcome = {}, "runtime_failure"
    started = time.monotonic()
    try:
        receipt = supervise([
                sys.executable, str(root / "scripts/fit_arrival_sensitivity.py"), "--job",
                str(spec), "--output", str(folder), "--store", str(raw), "--max-output-bytes",
                str(FILE_MAX), ], log, stop, TIMEOUT,)
    except KeyboardInterrupt:
        receipt = {"returncode": 130, "reason": "interrupt"}
    except Exception as exc:
        receipt = {"returncode": None, "reason": "launch_or_supervisor_failure", "error": str(exc)}
    starts = list(folder.rglob("sampling-start*.json"))
    state["calls_started"] += len(starts)
    receipt.setdefault("elapsed_seconds", time.monotonic() - started)
    new_json(process, {
            **receipt, "charged_slots": 1, "start_markers": len(starts), "job_sha256": sha256(spec),
            "plan_sha256": state["plan_sha256"], "monitor_failures": list(failures), },)
    manifest = folder / "attempt-evidence.json"
    files = {}
    if (receipt.get("returncode") == 0 and receipt.get("reason") == "worker_exit"
        and len(starts) == 1):
        try:
            files, bound = case_artifacts(root, job, pins)
            if bound != manifest:
                raise ValueError("literal attempt receipt path required")
            outcome = "accepted"
        except Exception as exc:
            new_json(folder / "evaluation-failure.json", {"error": str(exc)})
            outcome = "identity_or_evaluation_failure"
    try:
        _unchanged(root, pins)
        _inventory(root, state, job)
    except Exception:
        outcome = "source_or_inventory_failure"
    if failures or stop.exists() or quota_failure(root, parents, gate, job):
        outcome = "stop_or_storage_failure"
    if outcome != "accepted":
        files = _retained(root, job)
    new_json(manifest, {"case_id": job["id"], "files": files})
    if failures or stop.exists() or quota_failure(root, parents, gate, job):
        outcome = "late_stop_or_storage_failure"
        files = _retained(root, job)
        files[str(manifest.relative_to(root))] = sha256(manifest)
        manifest = folder / "failure-evidence.json"
        new_json(manifest, {"case_id": job["id"], "files": files})
    entry = { "case_id": job["id"], "charged_slots": 1, "receipt": str(manifest.relative_to(root)),
        "receipt_sha256": sha256(manifest), }
    state["attempts"].append({**entry, "start_markers": len(starts), "outcome": outcome})
    if outcome == "accepted":
        state["accepted"].append({**entry, "files": files})
        state["next_case"] += 1
    state.update(current=None,
        status="sensitivity_checkpoint" if outcome == "accepted" else "sensitivity_needs_review",)
    atomic_state(root / STATE, state)
    current[0] = None
    return outcome


def run(root, *, resume=False, max_cases=4):
    root = root.resolve()
    if type(max_cases) is not int or not 1 <= max_cases <= 4 or not resume and max_cases > 2:
        raise ValueError("initial pilots require explicit1or2cases; later batches at most4")
    gate, pins, jobs, parents = _admit(root)
    output, store, state_path = root / OUTPUT, root / STORE, root / STATE
    stops = [output / "STOP", root / OLD_OUTPUT / "STOP"]
    if any(path.exists() or path.is_symlink() for path in stops):
        raise ValueError("STOP present before allocation")
    if any((base / ".controller.lock").exists() for base in [output, root / OLD_OUTPUT]):
        raise ValueError("exclusive sensitivity/curvature controller lease required")
    expected = {
        "files": pins, "jobs": jobs, "resources": resources(), "path_bindings": path_bindings(root),
        "parent_minimum_bytes": gate["parent_minimum_bytes"], "gate_sha256": pins[GATE], }
    if resume:
        snapshot = state_path.read_bytes()
        state = json.loads(snapshot)
        plan = json.loads((output / "plan.json").read_text())
        if plan != expected or state.get("plan_sha256") != sha256(output / "plan.json"):
            raise ValueError("exact accepted source/jobs/plan identity required on resume")
        _validate_state(state, jobs)
        _proofs(root, state, jobs, pins)
        _inventory(root, state)
        if state["next_case"] < 2 and max_cases > 2 - state["next_case"]:
            raise ValueError("pilot-only continuation cannot cross the two-case boundary")
        if state["next_case"] >= 2 and (state["next_case"] < 55 or state.get("pilot_review_sha256")
       ):
            identity = _pilot_review(root, state)
            state["pilot_review_sha256"] = identity
        if state["status"] == "sensitivity_computations_complete":
            if quota_failure(root, parents, gate) or sha256(output / "run-summary.json"
           ) != state.get("final_summary_sha256"):
                raise ValueError("terminal resource/summary proof changed")
            return
    else:
        if output.exists() or store.exists() or state_path.exists():
            raise ValueError("new original sensitivity paths/state required; no reset")
        state = { "next_case": 0, "calls_charged": 0, "calls_started": 0, "current": None,
            "status": "sensitivity_checkpoint", "accepted": [], "attempts": [],
            "pilot_review_sha256": None, }
    with _leases(root):
        if resume and state_path.read_bytes() != snapshot:
            raise ValueError("private state changed before exclusive lease acquisition")
        if not resume:
            if state_path.exists() or store.exists() or (output / "plan.json").exists():
                raise ValueError("new sensitivity allocation appeared before lease acquisition")
            new_json(output / "plan.json", expected)
            store.mkdir(parents=True)
            state["plan_sha256"] = sha256(output / "plan.json")
            atomic_state(state_path, state)
        os.environ.update(
            PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
            NUMBA_CACHE_DIR=str(store / "cache/numba"),
            MPLCONFIGDIR=str(store / "cache/matplotlib"),)
        limit_worker_file_size(FILE_MAX)
        ended, failures, current = threading.Event(), [], [None]
        stop = stops[0]

        def monitor():
            while not ended.wait(WATCH_SECONDS):
                reason = quota_failure(root, parents, gate, current[0])
                if stops[1].exists():
                    reason = "old_curvature_STOP"
                if reason:
                    failures.append(reason)
                    try:
                        with stop.open("x", encoding="utf-8") as stream:
                            stream.write(reason + "\n")
                    except FileExistsError:
                        pass
                    return

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            for _ in range(min(max_cases, 55 - state["next_case"])):
                _proofs(root, state, jobs, pins)
                _inventory(root, state)
                _unchanged(root, pins)
                if state["next_case"] >= 2:
                    state["pilot_review_sha256"] = _pilot_review(root, state)
                if (any(path.exists() for path in stops) or failures
                    or state["calls_charged"] + 1 > MAX_CALLS
                    or quota_failure(root, parents, gate, reserve=True)):
                    state["status"] = "sensitivity_needs_review"
                    break
                outcome = _dispatch(
                    root, state, jobs[state["next_case"]], gate, pins, parents, failures, current,
                    stop,)
                if outcome != "accepted":
                    break
            ended.set()
            watcher.join(timeout=2)
            if (failures or any(path.exists() for path in stops)
                or quota_failure(root, parents, gate)):
                state["status"] = "sensitivity_needs_review"
            if state["status"] != "sensitivity_needs_review":
                state["status"] = ("sensitivity_computations_complete" if state["next_case"] == 55
                    else "sensitivity_pilot_review_required" if state["next_case"] == 2
                    else "sensitivity_checkpoint")
                _validate_state(state, jobs)
                _proofs(root, state, jobs, pins)
                _inventory(root, state)
                _unchanged(root, pins)
            summary = {
                key: state[key] for key in ["status", "next_case", "calls_charged", "calls_started"]
            }
            summary.update(planned_cases=55, max_sampler_call_slots=MAX_CALLS,
                working_bytes=working_bytes(root, parents), monitor_failures=list(failures),
                scientific_acceptance="pending_independent_checker",
                confirmation_outcomes_parsed=False, reserved_outcomes="sealed",)
            write_json(output / "run-summary.json", summary)
            atomic_state(state_path, state)
            if state["status"] != "sensitivity_needs_review":
                _unchanged(root, pins)
            if quota_failure(root, parents, gate) or any(path.exists() for path in stops):
                state["status"] = "sensitivity_needs_review"
                summary["status"] = state["status"]
                write_json(output / "run-summary.json", summary)
                atomic_state(state_path, state)
            elif state["status"] == "sensitivity_computations_complete":
                state["final_summary_sha256"] = sha256(output / "run-summary.json")
                atomic_state(state_path, state)
                if quota_failure(root, parents, gate) or any(path.exists() for path in stops):
                    state.pop("final_summary_sha256", None)
                    state["status"] = "sensitivity_needs_review"
                    summary["status"] = state["status"]
                    write_json(output / "run-summary.json", summary)
                    atomic_state(state_path, state)
            if state["status"] != "sensitivity_needs_review":
                _unchanged(root, pins)
            if state["status"] == "sensitivity_needs_review":
                raise SystemExit(2)
        except BaseException:
            state["status"] = "sensitivity_needs_review"
            state.pop("final_summary_sha256", None)
            atomic_state(state_path, state)
            raise
        finally:
            ended.set()
            if watcher.is_alive():
                watcher.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=4)
    arguments = parser.parse_args()
    run(Path(__file__).resolve().parents[1], resume=arguments.resume, max_cases=arguments.max_cases)
