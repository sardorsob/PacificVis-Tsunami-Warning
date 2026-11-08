"""Charge two fixed new ensembles to the existing curvature ledger; never retry."""

# pyright: basic
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_precision import (
    GATE,
    OUTPUT,
    STORE,
    WORKER,
    admit,
    job,
)  # noqa: E402
from scripts.run_arrival_curvature_continuation import (  # noqa: E402
    MAX_GLOBAL,
    MAX_LOCAL,
    RESERVE,
    STATE,
    byte_count,
    parent_floors,
    storage_failure,
    validate_inherited_path,
    validate_logical_prefix,
    working_bytes,
)
from scripts.run_arrival_curvature_continuation import (
    OUTPUT as PARENT_OUTPUT,
)
from scripts.run_arrival_curvature_continuation import (
    STORE as PARENT_STORE,
)
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

DESIGN = str(Path(GATE).parent)


def resources():
    return {
        "max_sampler_call_slots": 248,
        "inherited_charged_slots": 51,
        "new_sampler_call_slots": 2,
        "draws": 8000,
        "tune": 2000,
        "chains": 4,
        "cores": 2,
        "concurrency": 1,
        "automatic_retries": 0,
        "whole_job_seconds": 1200,
        "per_file_bytes": 64 * 1024**2,
        "global_max_bytes": MAX_GLOBAL,
        "local_max_bytes": MAX_LOCAL,
        "next_invocation_reserve_bytes": RESERVE,
        "cache_max_bytes": 256 * 1024**2,
        "job_max_bytes": 32 * 1024**2,
    }


def conserved_parent(root, state, pins):
    if (
        state.get("status") != "cv_needs_review"
        or state.get("current") is not None
        or state.get("next_fold") != 8
        or len(state.get("accepted", [])) != 7
        or state.get("calls_charged") != 51
        or state.get("calls_started") != 51
        or "precision_amendment" in state
    ):
        raise ValueError("exact conserved51slot stopped parent required; no retries")
    continuation = state["continuation"]
    if (
        state.get("plan_sha256") != pins.get(PARENT_OUTPUT + "/plan.json")
        or continuation.get("plan_sha256") != pins.get(PARENT_OUTPUT + "/continuation-v1/plan.json")
        or continuation.get("rehearsal_sha256")
        != pins.get(PARENT_OUTPUT + "/continuation-v1/rehearsal-review-acceptance.json")
    ):
        raise ValueError(
            "unchanged original and continuation plan/first-review identities required"
        )
    reviewed_plan = json.loads((root / PARENT_OUTPUT / "continuation-v1/plan.json").read_text())
    if continuation.get("resolutions") != reviewed_plan.get("resolutions"):
        raise ValueError("exact independently accepted resolution registry required")
    attempts = continuation["attempts"]
    if (
        not attempts
        or attempts[-1].get("case_id") != "fold-008"
        or attempts[-1].get("cost") != 3
        or attempts[-1].get("started") != 3
        or attempts[-1].get("outcome") == "accepted"
    ):
        raise ValueError("original three-call failed attempt required")
    for a in attempts:
        if (
            pins.get(a["receipt"]) != a["receipt_sha256"]
            or sha256(root / a["receipt"]) != a["receipt_sha256"]
        ):
            raise ValueError("all retained attempt receipts must be reviewed")
    original = json.loads((root / PARENT_OUTPUT / "plan.json").read_text())
    memberships = original["memberships"]
    for accepted in state["accepted"]:
        case_id = accepted["case_id"]
        canonical = PARENT_OUTPUT + "/jobs/" + case_id + "/attempt-evidence.json"
        if (
            accepted.get("receipt") != canonical
            or accepted.get("receipt_sha256") != pins.get(canonical)
            or accepted.get("charged_slots") != memberships[case_id]["charged_call_slots"]
        ):
            raise ValueError("canonical accepted attempt identity and charged slots required")
        manifest = json.loads((root / canonical).read_text())
        if (
            manifest.get("case_id") != case_id
            or not manifest.get("files")
            or accepted.get("files") != manifest["files"]
            or any(pins.get(p) != h for p, h in manifest["files"].items())
        ):
            raise ValueError("complete unchanged accepted public file map required")
    projected = copy.deepcopy(state)
    projected["continuation"]["attempts"].pop()
    projected["calls_charged"] -= 3
    projected["calls_started"] -= 3
    validate_logical_prefix(
        projected, original["cases"], original["memberships"], continuation["resolutions"]
    )
    validate_inherited_path(root, state, pins)
    known = {
        p
        for p in pins
        if p.startswith(PARENT_STORE + "/") and not p.startswith(PARENT_STORE + "/cache/")
    }
    raw = root / PARENT_STORE
    actual = {
        str(p.relative_to(root))
        for p in raw.rglob("*")
        if p.is_file() and not p.is_relative_to(raw / "cache")
    }
    expected_dirs = {p[len(PARENT_STORE) + 1 :].split("/")[0] for p in known} | {"cache"}
    if actual != known or any(p.is_file() or p.name not in expected_dirs for p in raw.iterdir()):
        raise ValueError("unexpected or omitted retained raw evidence")


def budget_failure(root, parents, gate=None):
    try:
        if gate is not None:
            parent_floors(root, gate)
    except Exception:
        return "parent_floor_failure"
    return (
        storage_failure(root, parents, root / OUTPUT)
        or (
            "precision_job_storage"
            if byte_count(root / OUTPUT, root / STORE) > 32 * 1024**2
            else None
        )
        or (
            "precision_design_global_storage"
            if working_bytes(root, parents) + byte_count(root / DESIGN) > MAX_GLOBAL
            else None
        )
    )


def evidence(root, output, store, receipt):
    paths = {
        p
        for folder in [output, store]
        for p in folder.rglob("*")
        if p.is_file() and p.name != "attempt-evidence.json"
    }
    paths.add(receipt)
    return {str(p.relative_to(root)): sha256(p) for p in paths if p.is_file()}


def run(root):
    root = root.resolve()
    gate, pins, old = admit(root)
    if (
        gate.get("resources") != resources()
        or gate.get("output") != OUTPUT
        or gate.get("store") != STORE
    ):
        raise ValueError("fixed two-call resource/path allocation required")
    state_path = root / STATE
    state = json.loads(state_path.read_text())
    conserved_parent(root, state, pins)
    parents = parent_floors(root, gate)
    output, store = root / OUTPUT, root / STORE
    if (
        output.exists()
        or store.exists()
        or any(
            output.with_name(output.name + suffix).exists()
            for suffix in ["-allocation.json", ".log", ".supervisor.json"]
        )
    ):
        raise ValueError("retain previous output; new precision attempt cannot overwrite")
    if (
        budget_failure(root, parents, gate)
        or working_bytes(root, parents) + byte_count(root / DESIGN) + RESERVE > MAX_GLOBAL
        or byte_count(root / PARENT_OUTPUT, root / PARENT_STORE) + RESERVE > MAX_LOCAL
    ):
        raise ValueError("conserved shared storage and reserve required before dispatch")
    lease = (root / PARENT_OUTPUT) / ".controller.lock"
    stop = lease.with_name("STOP")
    if stop.exists():
        raise ValueError("STOP present; no new call charged")
    try:
        with lease.open("x") as f:
            f.write(str(os.getpid()))
    except FileExistsError as exc:
        raise ValueError("another curvature controller owns the shared lease") from exc
    ended = threading.Event()
    failures = []
    started = time.monotonic()

    def monitor():
        while not ended.wait(0.1):
            reason = budget_failure(root, parents, gate)
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    try:
        # Reconcile after acquiring the lease; the worker itself never edits this ledger.
        if json.loads(state_path.read_text()) != state or stop.exists():
            raise ValueError("parent changed or STOP appeared before reservation")
        allocation = output.with_name(output.name + "-allocation.json")
        write_json(
            allocation,
            {
                "files": pins,
                "job": job(),
                "resources": resources(),
                "source_git_sha": git_sha(root),
                "parent_calls_charged": 51,
                "parent_calls_started": 51,
            },
        )
        state["precision_amendment"] = {
            "allocation": str(output.with_name(output.name + "-allocation.json").relative_to(root)),
            "allocation_sha256": sha256(output.with_name(output.name + "-allocation.json")),
            "charged_slots": 2,
            "started": 0,
            "parent_calls_charged": 51,
            "parent_calls_started": 51,
        }
        state["calls_charged"] += 2
        state["current"] = job()["id"]
        state["status"] = "precision_running"
        atomic_state(state_path, state)
        watcher.start()
        os.environ.update(
            PYTENSOR_FLAGS=f"floatX=float64,base_compiledir={root / PARENT_STORE}/cache/pytensor",
            NUMBA_CACHE_DIR=str(root / PARENT_STORE / "cache/numba"),
            MPLCONFIGDIR=str(root / PARENT_STORE / "cache/matplotlib"),
        )
        log = output.with_name(output.name + ".log")
        try:
            receipt = supervise(
                [sys.executable, str(root / WORKER)],
                log=log,
                stop=stop,
                timeout=1200,
            )
        except BaseException as exc:
            receipt = {
                "returncode": None,
                "reason": "launch_or_supervisor_failure",
                "error": str(exc),
            }
        receipt.setdefault("elapsed_seconds", time.monotonic() - started)
        starts = list((output / "sampling-starts").glob("*.json"))
        state["calls_started"] += len(starts)
        state["precision_amendment"]["started"] = len(starts)
        atomic_state(state_path, state)
        supervisor = output.with_name(output.name + ".supervisor.json")
        write_json(
            supervisor,
            {
                **receipt,
                "charged_slots": 2,
                "start_markers": len(starts),
                "monitor_failures": list(failures),
                "allocation_sha256": state["precision_amendment"]["allocation_sha256"],
            },
        )
        passed = False
        result_file = output / "result.json"
        if (
            receipt.get("returncode") == 0
            and receipt.get("reason") == "worker_exit"
            and result_file.exists()
        ):
            try:
                result = json.loads(result_file.read_text())
                passed = (
                    result.get("status") == "computed_pending_review"
                    and result.get("job") == old["job"]
                    and result.get("precision_job") == job()
                    and result.get("score_precision_passed") is True
                    and {p.name for p in starts} == {"00.json", "01.json"}
                    and all(
                        json.loads((output / "sampling-starts" / f"{k:02d}.json").read_text())
                        == {
                            **job(),
                            "phase": "training" if k == 0 else "augmented",
                            "event": None if k == 0 else job()["event"],
                            "seed": job()["seed"] + k,
                        }
                        for k in range(2)
                    )
                )
            except (ValueError, TypeError):
                pass
        if any(
            not (root / p).is_file() or sha256(checked_path(root, p)) != h for p, h in pins.items()
        ):
            passed = False
        if failures or budget_failure(root, parents, gate):
            passed = False
        manifest = output / "attempt-evidence.json"
        files = evidence(root, output, store, supervisor)
        allocation = output.with_name(output.name + "-allocation.json")
        files[str(allocation.relative_to(root))] = sha256(allocation)
        if log.is_file():
            files[str(log.relative_to(root))] = sha256(log)
        write_json(
            manifest,
            {
                "job": job(),
                "files": files,
                "outcome": "computed_pending_review" if passed else "failed_retained",
            },
        )
        state["current"] = None
        state["status"] = "precision_computations_complete" if passed else "precision_needs_review"
        state["precision_amendment"].update(
            receipt=str(manifest.relative_to(root)), receipt_sha256=sha256(manifest)
        )
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "calls_charged": state["calls_charged"],
                "calls_started": state["calls_started"],
                "new_calls_started": len(starts),
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        ended.set()
        watcher.join(timeout=2)
        final_reason = budget_failure(root, parents, gate)
        if failures or final_reason:
            passed = False
            state["status"] = "precision_needs_review"
            payload = json.loads(manifest.read_text())
            payload.update(
                outcome="failed_retained",
                final_budget_failure=final_reason,
                monitor_failures=list(failures),
            )
            write_json(manifest, payload)
            state["precision_amendment"]["receipt_sha256"] = sha256(manifest)
            atomic_state(state_path, state)
            summary = json.loads((output / "run-summary.json").read_text())
            summary.update(status=state["status"], final_budget_failure=final_reason)
            write_json(output / "run-summary.json", summary)
        print(state["status"], state["calls_charged"], state["calls_started"], flush=True)
        if not passed:
            raise SystemExit(2)
    finally:
        ended.set()
        if watcher.is_alive():
            watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    limit_worker_file_size(64 * 1024**2)
    run(Path(__file__).resolve().parents[1])
