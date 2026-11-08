"""One conserved 150-call allocation: recovery, independent gate, then prior SBC."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

GATE = "artifacts/models/arrival-timing/mean-curvature-calibration-design-v1/review-acceptance.json"
OUTPUT = "artifacts/models/arrival-timing/mean-curvature-calibration-v1"
STORE = "data/processed/models/mean-curvature-calibration-v1"
STATE = "context/runs/arrival-model-fitting-v1/curvature-calibration-state.json"
RECOVERY_GATE = OUTPUT + "/recovery-review-acceptance.json"
EXTRA = [
    "scripts/run_arrival_curvature_pilot.py",
    "analysis/arrival/model_curvature_calibration.py",
    "analysis/arrival/model_curvature_curve_checks.py",
]
PARENT_ROOTS = [
    "data/processed/models/mean-curvature-prior-v1",
    "data/processed/models/mean-curvature-prior-unreviewed-v1",
    "data/processed/models/mean-curvature-pilot-v1",
    "artifacts/models/arrival-timing/mean-curvature-design-v1",
    "artifacts/models/arrival-timing/mean-curvature-pilot-design-v1",
    "artifacts/models/arrival-timing/mean-curvature-pilot-v1",
    "artifacts/models/arrival-timing/mean-curvature-pilot-report-v1",
    "artifacts/models/arrival-timing/mean-curvature-prior-report-v2",
    "artifacts/models/arrival-timing/mean-curvature-calibration-design-v1",
]
SELF = "scripts/run_arrival_curvature_calibration.py"
CHECKPOINT_HELPER = "scripts/run_arrival_model_batch.py"
MIB = 1024**2
MAX_BYTES = 2048 * MIB
RESERVE = 464 * MIB
MAX_CACHE = 256 * MIB
MAX_SMALL_OUTPUT = 16 * MIB
PILOT_GATE = "artifacts/models/arrival-timing/mean-curvature-pilot-v1/review-acceptance.json"
PARENT_GATES = [
    PILOT_GATE,
    "artifacts/models/arrival-timing/mean-curvature-prior-report-v2/review-acceptance.json",
    "artifacts/models/arrival-timing/mean-curvature-pilot-report-v1/review-acceptance.json",
]
FIRST_EVENT = "official20100227063411530_30"


def make_cases():
    from scripts.run_arrival_curvature_pilot import make_cases as pilot_cases

    pilot = pilot_cases()
    cases = []
    for j in range(150):
        recovery = j < 50
        local = j if recovery else j - 50
        case = {
            **pilot[local // 10 if recovery else 0],
            "id": f"{'recovery' if recovery else 'sbc'}-{local:03d}",
            "phase": "recovery" if recovery else "sbc",
            "draws": 2000,
            "seed": (2826110800 if recovery else 2836110800) + 100 * local,
        }
        if not recovery:
            del case["truth"]
        cases.append(case)
    return cases


def parent_inventory(root):
    return {
        str(p.relative_to(root)): sha256(p)
        for name in PARENT_ROOTS[:-1]
        for p in (root / name).rglob("*")
        if p.is_file() and "cache" not in p.relative_to(root / name).parts
    }


def verify_parent_accounting(root, gate):
    inventory = parent_inventory(root)
    floors = gate.get("parent_minimum_bytes", {})
    if (
        not inventory
        or inventory != gate.get("parent_inventory")
        or any(gate["files"].get(p) != digest for p, digest in inventory.items())
        or set(floors) != set(PARENT_ROOTS[:-1])
        or any(type(n) is not int or n < 0 for n in floors.values())
        or any(byte_count(root / name) < n for name, n in floors.items())
    ):
        raise ValueError("frozen parent evidence inventory/accounting changed")


def parent_datasets(root):
    import xarray as xr

    from analysis.arrival.model_curvature_calibration import observed_fingerprint
    from scripts.run_arrival_curvature_pilot import make_cases as pilot_cases

    gate = json.loads((root / PILOT_GATE).read_text())
    required = {
        f"data/processed/models/mean-curvature-pilot-v1/{c['id']}.nc" for c in pilot_cases()
    }
    if (
        gate.get("status") != "accepted_complete_five_case_computational_pilot"
        or gate.get("independent_checker") is not True
        or not required.issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independent parent pilot proof required")
    for name, digest in gate["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("parent pilot evidence changed")
    hashes = []
    for name in sorted(required):
        tree = xr.open_datatree(root / name, engine="h5netcdf")
        try:
            hashes.append(observed_fingerprint(tree["observed_data"]))
        finally:
            tree.close()
    if len(set(hashes)) != 5:
        raise ValueError("five distinct parent pilot datasets required")
    return hashes


def working_roots(root, output, store):
    return [output, store, *(root / p for p in PARENT_ROOTS)]


def byte_count(*roots):
    total = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.lstat().st_size
            except FileNotFoundError:
                continue  # atomic cache/NC replacement can remove a scanned name
    return total


def quota_failure(root, output, store, attempt=None):
    if byte_count(*working_roots(root, output, store)) > MAX_BYTES:
        return "aggregate_storage"
    if byte_count(store / "cache") > MAX_CACHE:
        return "cache_storage"
    if attempt is not None and byte_count(attempt) > MAX_SMALL_OUTPUT:
        return "small_output_storage"
    return None


def bindings(root, output, store, state_path):
    # This binds an argument string, never private state contents or a context file pin.
    return {
        "output": str(output.relative_to(root)),
        "store": str(store.relative_to(root)),
        "private_state_identity_sha256": hashlib.sha256(str(state_path).encode()).hexdigest(),
    }


def case_artifacts(root, output, store, case, pins, consumed, accepted=None):
    from scripts.run_arrival_curvature_pilot import case_artifacts as pilot_artifacts

    attempt = output / "jobs" / case["id"]
    path = attempt / "calibration-checks.json"
    if not path.is_file():
        raise ValueError("mandatory calibration checks missing")
    checks = json.loads(path.read_text())
    if (
        checks.get("case_id") != case["id"]
        or checks.get("rank_ready") is not True
        or len(checks.get("estimates", [])) != 12
        or len(checks.get("functional", {}).get("estimates", [])) != 9
    ):
        raise ValueError("complete21-quantity retained calibration diagnostics required")
    return pilot_artifacts(root, output, store, case, pins, consumed, accepted)


def verify_recovery_gate(root, output, state):
    gate_path = root / RECOVERY_GATE
    if state["next_case"] < 50 or not gate_path.is_file():
        raise ValueError("SBC requires fifty independently accepted recovery datasets")
    gate = json.loads(gate_path.read_text())
    required = {str(output.relative_to(root) / Path("plan.json"))}
    for entry in state["accepted"][:50]:
        required.update(entry["files"])
        required.add(entry["receipt"])
    if (
        gate.get("status") != "accepted_fifty_recovery_for_sbc"
        or gate.get("independent_checker") is not True
        or gate.get("recovery_cases") != 50
        or not required.issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independent fifty-case recovery proof required")
    for name, digest in gate["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("independent recovery proof changed")
    identity = sha256(gate_path)
    if state.get("recovery_gate_sha256") not in {None, identity}:
        raise ValueError("recovery gate identity changed")
    return identity


def run(root, output, store, state_path, *, phase="recovery", resume=False, max_cases=1):
    root, output, store, state_path = [p.resolve() for p in [root, output, store, state_path]]
    if (
        phase not in {"recovery", "sbc"}
        or not 1 <= max_cases <= 5
        or output != root / OUTPUT
        or store != root / STORE
        or state_path != root / STATE
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
        or output.is_relative_to(store)
        or store.is_relative_to(output)
        or not state_path.is_relative_to(root / "context/runs/arrival-model-fitting-v1")
    ):
        raise ValueError(
            "bounded invocation and disjoint project stores/canonical private state required"
        )
    if resume:
        if not output.is_dir() or not store.is_dir() or not state_path.exists():
            raise ValueError("resume requires original state/stores")
    else:
        if output.exists() or store.exists() or state_path.exists():
            raise ValueError("new calibration paths required")
        output.mkdir(parents=True)
        store.mkdir(parents=True)
    bound_paths = bindings(root, output, store, state_path)
    if (
        resume
        and json.loads((output / "plan.json").read_text()).get("path_bindings") != bound_paths
    ):
        raise ValueError("calibration paths differ from frozen accounting scope")
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = output / "STOP"

    def monitor():
        while not ended.wait(0.1):
            reason = quota_failure(root, output, store, current[0])
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        limit_worker_file_size(64 * MIB)
        cache_env = {
            "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
            "NUMBA_CACHE_DIR": str(store / "cache/numba"),
            "MPLCONFIGDIR": str(store / "cache/matplotlib"),
        }
        os.environ.update(cache_env)
        from analysis.arrival.model_curvature_validation import CONSUMED

        gate = json.loads((root / GATE).read_text())
        required = {SELF, CHECKPOINT_HELPER, *PARENT_GATES, *CONSUMED, *EXTRA}
        if (
            gate.get("status") != "accepted_finite_curvature_calibration"
            or gate.get("independent_checker") is not True
            or gate.get("max_sampler_call_slots") != 150
            or gate.get("max_bytes") != MAX_BYTES
            or not required.issubset(gate.get("files", {}))
        ):
            raise ValueError("complete independently accepted 150-case calibration gate required")
        pins = {**gate["files"], GATE: sha256(root / GATE)}
        for name, digest in pins.items():
            if sha256(checked_path(root, name)) != digest:
                raise ValueError("calibration gate source changed")
        if not all((root / name).is_dir() for name in PARENT_ROOTS):
            raise ValueError("all frozen parent accounting roots required")
        verify_parent_accounting(root, gate)
        pilot_datasets = parent_datasets(root)
        versions = {
            p: version(p)
            for p in ["pymc", "pytensor", "arviz-stats", "nutpie", "numpy", "h5netcdf"]
        }
        if resume:
            plan = json.loads((output / "plan.json").read_text())
            state = json.loads(state_path.read_text())
            if (
                plan["files"] != pins
                or plan["cases"] != make_cases()
                or plan["versions"] != versions
                or plan["cache_environment"] != cache_env
                or state["plan_sha256"] != sha256(output / "plan.json")
                or state["current"] is not None
                or plan["parent_roots"] != PARENT_ROOTS
                or plan["parent_dataset_sha256"] != pilot_datasets
                or state["status"] not in {"checkpoint", "recovery_complete", "complete"}
                or state["calls_used"] != state["next_case"]
                or state["next_case"] != len(state["accepted"])
                or not 0 <= state["calls_used"] <= 150
            ):
                raise ValueError(
                    "changed, failed or incomplete calibration requires explicit reconciliation"
                )
            if [a["case_id"] for a in state["accepted"]] != [
                c["id"] for c in plan["cases"][: state["next_case"]]
            ]:
                raise ValueError("calibration prefix case membership changed")
            for j, accepted in enumerate(state["accepted"]):
                case_artifacts(root, output, store, plan["cases"][j], pins, CONSUMED, accepted)
        else:
            plan = {
                "schema_version": "arrival_curvature_calibration_v1",
                "path_bindings": bound_paths,
                "parent_roots": PARENT_ROOTS,
                "parent_dataset_sha256": pilot_datasets,
                "storage_scope": "monitored trip thresholds, not hard filesystem quotas; "
                "retain/count overshoot and abort",
                "files": pins,
                "cases": make_cases(),
                "versions": versions,
                "cache_environment": cache_env,
                "source_git_sha": git_sha(root),
                "max_sampler_call_slots": 150,
                "max_bytes": MAX_BYTES,
                "next_job_reserve_bytes": RESERVE,
                "cache_quota_bytes": MAX_CACHE,
                "small_job_output_quota_bytes": MAX_SMALL_OUTPUT,
                "timeout_seconds": 600,
                "concurrency": 1,
                "automatic_retries": 0,
            }
            write_json(output / "plan.json", plan)
            state = {
                "next_case": 0,
                "calls_used": 0,
                "accepted": [],
                "current": None,
                "status": "checkpoint",
                "plan_sha256": sha256(output / "plan.json"),
            }
            atomic_state(state_path, state)
        if phase == "sbc":
            state["recovery_gate_sha256"] = verify_recovery_gate(root, output, state)
            atomic_state(state_path, state)
        elif state["next_case"] > 50:
            raise ValueError("recovery phase cannot dispatch SBC")
        from analysis.arrival.model_curvature_calibration import retained_checks

        for _ in range(max_cases):
            expected_nc = {store / (a["case_id"] + ".nc") for a in state["accepted"]}
            if set(store.glob("*.nc")) != expected_nc:
                raise ValueError("unexpected or incomplete calibration posterior collection")
            if state["next_case"] == (50 if phase == "recovery" else 150):
                break
            if (
                stop.exists()
                or failures
                or quota_failure(root, output, store)
                or byte_count(*working_roots(root, output, store)) + RESERVE > MAX_BYTES
            ):
                state["status"] = "stop_or_storage_failure"
                break
            verify_parent_accounting(root, gate)
            if any(sha256(root / p) != digest for p, digest in pins.items()):
                raise ValueError("calibration source drift")
            case = plan["cases"][state["next_case"]]
            if case["phase"] != phase:
                raise ValueError("phase does not match conserved dispatch index")
            if phase == "sbc":
                verify_recovery_gate(root, output, state)
            attempt = output / "jobs" / case["id"]
            posterior = store / (case["id"] + ".nc")
            spec = attempt.with_name(case["id"] + "-spec.json")
            if any(
                p.exists()
                for p in [
                    attempt,
                    posterior,
                    spec,
                    posterior.with_name(posterior.stem + "-augmented.nc"),
                ]
            ):
                raise ValueError("calibration attempt or partial already exists")
            write_json(spec, case)
            state.update(current=case["id"], calls_used=state["calls_used"] + 1, status="running")
            atomic_state(state_path, state)
            current[0] = attempt
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/fit_arrival_curvature_synthetic.py"),
                        "--worker",
                        "--job",
                        str(spec),
                        "--output",
                        str(attempt),
                        "--store",
                        str(posterior),
                        "--max-output-bytes",
                        str(64 * MIB),
                    ],
                    attempt.with_suffix(".log"),
                    stop,
                    600,
                )
            except KeyboardInterrupt:
                receipt = {"returncode": 130, "reason": "interrupt"}
            write_json(
                attempt.with_suffix(".supervisor.json"),
                {
                    **receipt,
                    "job_sha256": sha256(spec),
                    "plan_sha256": state["plan_sha256"],
                    "monitor_failures": failures,
                },
            )
            current[0] = None
            result_path = attempt / "result.json"
            outcome = "interrupted" if receipt["reason"] == "interrupt" else "runtime_failure"
            if (
                receipt["returncode"] == 0
                and receipt["reason"] == "worker_exit"
                and result_path.exists()
            ):
                result = json.loads(result_path.read_text())
                if (
                    result["job"] != case
                    or result["code_and_config"] != {p: pins[p] for p in CONSUMED}
                    or result["posterior_sha256"] != sha256(posterior)
                    or any(sha256(root / p) != digest for p, digest in pins.items())
                ):
                    outcome = "identity_failure"
                elif not result["diagnostics"]["screen_passed"]:
                    outcome = "diagnostic_failure"
                else:
                    outcome = "accepted_computation_pending_review"
            if failures or quota_failure(root, output, store, attempt):
                outcome = "storage_failure"
            state["current"] = None
            if outcome != "accepted_computation_pending_review":
                state["status"] = outcome
                atomic_state(state_path, state)
                break
            checks = retained_checks(root, posterior, result)
            write_json(attempt / "calibration-checks.json", checks)
            previous = {
                json.loads(
                    (root / a["receipt"]).parent.joinpath("calibration-checks.json").read_text()
                )["synthetic_observed_data_sha256"]
                for a in state["accepted"]
            } | set(pilot_datasets)
            if not checks["rank_ready"] or checks["synthetic_observed_data_sha256"] in previous:
                state["status"] = "rank_or_distinct_dataset_failure"
                atomic_state(state_path, state)
                break
            files, manifest = case_artifacts(root, output, store, case, pins, CONSUMED)
            write_json(manifest, {"case_id": case["id"], "files": files})
            state["accepted"].append(
                {
                    "case_id": case["id"],
                    "files": files,
                    "receipt": str(manifest.relative_to(root)),
                    "receipt_sha256": sha256(manifest),
                }
            )
            state["next_case"] += 1
            state["status"] = (
                "complete"
                if state["next_case"] == 150
                else "recovery_complete"
                if state["next_case"] == 50
                else "checkpoint"
            )
            atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "computed_cases": state["next_case"],
                "sampler_call_slots_used": state["calls_used"],
                "max_sampler_call_slots": 150,
                "raw_and_cache_and_evidence_bytes": byte_count(*working_roots(root, output, store)),
                "max_bytes": MAX_BYTES,
                "scientific_acceptance": "pending independent results review",
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        if failures or quota_failure(root, output, store):
            state["status"] = "storage_failure"
            atomic_state(state_path, state)
            summary = json.loads((output / "run-summary.json").read_text())
            summary["status"] = "storage_failure"
            write_json(output / "run-summary.json", summary)
        if state["status"] not in {"checkpoint", "recovery_complete", "complete"}:
            raise SystemExit(2)
    finally:
        ended.set()
        watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--phase", choices=["recovery", "sbc"], default="recovery")
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=1)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run(
        project,
        (project / args.output).resolve(),
        (project / args.store).resolve(),
        (project / args.state).resolve(),
        phase=args.phase,
        resume=args.resume,
        max_cases=args.max_cases,
    )
