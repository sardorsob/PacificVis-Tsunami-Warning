"""Five immutable synthetic jobs, serial execution and finite storage/call guards."""

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

GATE = "artifacts/models/arrival-timing/mean-curvature-pilot-design-v1/review-acceptance.json"
SELF = "scripts/run_arrival_curvature_pilot.py"
CHECKPOINT_HELPER = "scripts/run_arrival_model_batch.py"
MIB = 1024**2
MAX_BYTES = 512 * MIB
RESERVE = 272 * MIB
MAX_CACHE = 64 * MIB
MAX_SMALL_OUTPUT = 16 * MIB
FIRST_EVENT = "official20100227063411530_30"


def make_cases():
    settings = [
        ("null-weak", 0.15, -0.05, 0.0, 0.05, [0.6, 0.6, 0.1]),
        ("positive-weak", 0.15, -0.05, 0.5, 0.05, [0.6, 0.6, 0.1]),
        ("negative-weak", 0.15, -0.05, -0.5, 0.05, [0.6, 0.6, 0.1]),
        ("null-moderate", 0.15, -0.05, 0.0, 0.25, [0.3, 0.3, 0.3]),
        ("combined", 0.4, -0.25, 0.75, 0.05, [0.8, 0.6, 0.08]),
    ]
    return [
        {
            "id": name,
            "model": "mean-curvature",
            "target": "NCEI-native-duration",
            "phase": "pilot",
            "draws": 1000,
            "tune": 1000,
            "cores": 2,
            "seed": 2816110800 + 100 * j,
            "first_event_id": FIRST_EVENT,
            "truth": dict(
                zip(["alpha", "beta", "gamma", "tau_event", "sigma_anchor"], values, strict=True)
            ),
        }
        for j, (name, *values) in enumerate(settings)
    ]


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


def quota_failure(output, store, attempt=None):
    if byte_count(output, store) > MAX_BYTES:
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
    attempt = output / "jobs" / case["id"]
    posterior = store / (case["id"] + ".nc")
    spec = attempt.with_name(case["id"] + "-spec.json")
    manifest = attempt / "attempt-evidence.json"
    mandatory = [
        attempt / name
        for name in [
            "job.json",
            "inputs.json",
            "result.json",
            "sampled-hyperparameter-diagnostics.csv",
            "sampling-diagnostics.csv",
        ]
    ]
    mandatory += [
        spec,
        attempt.with_suffix(".log"),
        attempt.with_suffix(".supervisor.json"),
        posterior,
    ]
    if not all(p.is_file() for p in mandatory):
        raise ValueError("incomplete mandatory pilot evidence")
    paths = [p for p in attempt.rglob("*") if p.is_file() and p != manifest]
    paths += mandatory[5:]
    current = {str(p.relative_to(root)): sha256(p) for p in paths}
    if accepted is not None:
        if (
            accepted.get("receipt") != str(manifest.relative_to(root))
            or not manifest.is_file()
            or sha256(manifest) != accepted.get("receipt_sha256")
        ):
            raise ValueError("accepted pilot prefix evidence receipt changed")
        original = json.loads(manifest.read_text())
        if (
            original.get("case_id") != case["id"]
            or original.get("files") != current
            or accepted.get("files") != current
        ):
            raise ValueError("accepted pilot prefix proof changed or omitted")
    result = json.loads((attempt / "result.json").read_text())
    if (
        result.get("job") != case
        or result.get("synthetic_only") is not True
        or result.get("posterior") != str(posterior.relative_to(root))
        or result.get("posterior_sha256") != current[str(posterior.relative_to(root))]
        or result.get("code_and_config") != {p: pins[p] for p in consumed}
        or not result.get("diagnostics", {}).get("screen_passed")
    ):
        raise ValueError("retained pilot result identity changed")
    return current, manifest


def run(root, output, store, state_path, *, resume=False, max_cases=1):
    root, output, store, state_path = [p.resolve() for p in [root, output, store, state_path]]
    if (
        not 1 <= max_cases <= 5
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
            raise ValueError("new pilot paths required")
        output.mkdir(parents=True)
        store.mkdir(parents=True)
    bound_paths = bindings(root, output, store, state_path)
    if (
        resume
        and json.loads((output / "plan.json").read_text()).get("path_bindings") != bound_paths
    ):
        raise ValueError("pilot paths differ from frozen accounting scope")
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = output / "STOP"

    def monitor():
        while not ended.wait(0.1):
            reason = quota_failure(output, store, current[0])
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
        required = {SELF, CHECKPOINT_HELPER, *CONSUMED}
        if (
            gate.get("status") != "accepted_five_case_synthetic_pilot"
            or gate.get("independent_checker") is not True
            or gate.get("max_sampler_call_slots") != 5
            or gate.get("max_bytes") != MAX_BYTES
            or not required.issubset(gate.get("files", {}))
        ):
            raise ValueError("complete independently accepted five-case pilot gate required")
        pins = {**gate["files"], GATE: sha256(root / GATE)}
        for name, digest in pins.items():
            if sha256(checked_path(root, name)) != digest:
                raise ValueError("pilot gate source changed")
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
                or state["status"] not in {"checkpoint", "complete"}
                or state["calls_used"] != state["next_case"]
                or state["next_case"] != len(state["accepted"])
                or not 0 <= state["calls_used"] <= 5
            ):
                raise ValueError(
                    "changed, failed or incomplete pilot requires explicit reconciliation"
                )
            if [a["case_id"] for a in state["accepted"]] != [
                c["id"] for c in plan["cases"][: state["next_case"]]
            ]:
                raise ValueError("pilot prefix case membership changed")
            for j, accepted in enumerate(state["accepted"]):
                case_artifacts(root, output, store, plan["cases"][j], pins, CONSUMED, accepted)
        else:
            plan = {
                "schema_version": "arrival_curvature_pilot_v1",
                "path_bindings": bound_paths,
                "storage_scope": "monitored trip thresholds, not hard filesystem quotas; "
                "retain/count overshoot and abort",
                "files": pins,
                "cases": make_cases(),
                "versions": versions,
                "cache_environment": cache_env,
                "source_git_sha": git_sha(root),
                "max_sampler_call_slots": 5,
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
        for _ in range(max_cases):
            expected_nc = {store / (a["case_id"] + ".nc") for a in state["accepted"]}
            if set(store.glob("*.nc")) != expected_nc:
                raise ValueError("unexpected or incomplete pilot posterior collection")
            if state["next_case"] == 5:
                break
            if (
                stop.exists()
                or failures
                or quota_failure(output, store)
                or byte_count(output, store) + RESERVE > MAX_BYTES
            ):
                state["status"] = "stop_or_storage_failure"
                break
            if any(sha256(root / p) != digest for p, digest in pins.items()):
                raise ValueError("pilot source drift")
            case = plan["cases"][state["next_case"]]
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
                raise ValueError("pilot attempt or partial already exists")
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
            if failures or quota_failure(output, store, attempt):
                outcome = "storage_failure"
            state["current"] = None
            if outcome != "accepted_computation_pending_review":
                state["status"] = outcome
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
            state["status"] = "complete" if state["next_case"] == 5 else "checkpoint"
            atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "computed_cases": state["next_case"],
                "sampler_call_slots_used": state["calls_used"],
                "max_sampler_call_slots": 5,
                "raw_and_cache_and_evidence_bytes": byte_count(output, store),
                "max_bytes": MAX_BYTES,
                "scientific_acceptance": "pending independent results review",
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        if failures or quota_failure(output, store):
            state["status"] = "storage_failure"
            atomic_state(state_path, state)
            summary = json.loads((output / "run-summary.json").read_text())
            summary["status"] = "storage_failure"
            write_json(output / "run-summary.json", summary)
        if state["status"] not in {"checkpoint", "complete"}:
            raise SystemExit(2)
    finally:
        ended.set()
        watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=1)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run(
        project,
        (project / args.output).resolve(),
        (project / args.store).resolve(),
        (project / args.state).resolve(),
        resume=args.resume,
        max_cases=args.max_cases,
    )
