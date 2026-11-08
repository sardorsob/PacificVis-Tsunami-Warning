"""One prospective historical fit allocation; immutable failure, finite worker guards."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_curvature_calibration import (  # noqa: E402
    OUTPUT as CALIBRATION_OUTPUT,
)
from scripts.run_arrival_curvature_calibration import (  # noqa: E402
    STORE as CALIBRATION_STORE,
)
from scripts.run_arrival_curvature_calibration import working_roots  # noqa: E402
from scripts.run_arrival_curvature_pilot import byte_count  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402

SELF = "scripts/run_arrival_curvature_fit.py"
OUTPUT = "artifacts/models/arrival-timing/exploration-mean-curvature-v1"
CONTROL = "artifacts/models/arrival-timing/mean-curvature-fit-attempt-v1"
STORE = "data/processed/models/mean-curvature-fit-v1"
DESIGN = "artifacts/models/arrival-timing/mean-curvature-fit-design-v1"
MIB = 1024**2
MAX_LOCAL = 512 * MIB
MAX_GLOBAL = 2048 * MIB
MAX_CACHE = 64 * MIB
MAX_SMALL = 16 * MIB
RESERVE = 272 * MIB


def quota_failure(root, parents):
    local = [root / p for p in [OUTPUT, CONTROL, STORE]]
    if byte_count(*parents, *local, root / DESIGN) > MAX_GLOBAL:
        return "global_storage"
    if byte_count(*local) > MAX_LOCAL:
        return "local_storage"
    if byte_count(root / STORE / "cache") > MAX_CACHE:
        return "cache_storage"
    if byte_count(root / OUTPUT, root / CONTROL) > MAX_SMALL:
        return "small_output_storage"
    return None


def run(root):
    root = root.resolve()
    output, control, raw = [root / p for p in [OUTPUT, CONTROL, STORE]]
    posterior = raw / "primary.nc"
    if any(p.exists() for p in [output, control, raw]):
        raise ValueError("single-call allocation or partial already retained; no automatic retry")
    cache_env = {
        "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={raw / 'cache/pytensor'}",
        "NUMBA_CACHE_DIR": str(raw / "cache/numba"),
        "MPLCONFIGDIR": str(raw / "cache/matplotlib"),
    }
    os.environ.update(cache_env)
    from analysis.arrival.model_curvature_fit import FIT_GATE, verify_fit_gate

    job_path = root / DESIGN / "job.json"
    job = json.loads(job_path.read_text())
    pins = verify_fit_gate(root, job, output, posterior)
    job_hash = sha256(job_path)
    gate = json.loads((root / FIT_GATE).read_text())
    expected = {
        "controller": SELF,
        "cache_environment": cache_env,
        "global_max_bytes": MAX_GLOBAL,
        "local_max_bytes": MAX_LOCAL,
        "cache_max_bytes": MAX_CACHE,
        "small_output_max_bytes": MAX_SMALL,
        "next_job_reserve_bytes": RESERVE,
        "timeout_seconds": 600,
        "concurrency": 1,
        "automatic_retries": 0,
    }
    if any(gate.get(k) != v for k, v in expected.items()):
        raise ValueError("complete prospective single-call resource allocation required")
    parents = working_roots(root, root / CALIBRATION_OUTPUT, root / CALIBRATION_STORE)
    floors = gate.get("parent_minimum_bytes", {})
    if (
        set(floors) != {str(p.relative_to(root)) for p in parents}
        or any(type(n) is not int or n < 0 for n in floors.values())
        or any(not (root / p).is_dir() or byte_count(root / p) < n for p, n in floors.items())
        or quota_failure(root, parents)
        or byte_count(*parents, root / DESIGN) + RESERVE > MAX_GLOBAL
    ):
        raise ValueError("preserved parent stores and actual resource headroom required")
    # Atomic exclusive claim conserves the sole attempted call even after failure or interruption.
    control.mkdir(parents=True, exist_ok=False)
    raw.mkdir(parents=True)
    write_json(
        control / "allocation.json",
        {
            "sampler_call_slots_used": 1,
            "max_sampler_call_slots": 1,
            "job": job,
            "job_sha256": sha256(job_path),
            "files": pins,
            "storage_scope": "monitored trip thresholds; no hard filesystem quota; "
            "retain/count overshoot",
            "parent_minimum_bytes": floors,
            **expected,
        },
    )
    stop = control / "STOP"
    ended = threading.Event()
    failures = []

    def monitor():
        while not ended.wait(0.1):
            reason = quota_failure(root, parents)
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        try:
            receipt = supervise(
                [
                    sys.executable,
                    str(root / "scripts/fit_arrival_curvature.py"),
                    "--worker",
                    "--job",
                    str(job_path),
                    "--output",
                    str(output),
                    "--store",
                    str(posterior),
                    "--max-output-bytes",
                    str(64 * MIB),
                ],
                control / "worker.log",
                stop,
                600,
            )
        except KeyboardInterrupt:
            receipt = {"returncode": 130, "reason": "interrupt"}
        write_json(control / "supervisor.json", {**receipt, "monitor_failures": failures})
        status = "interrupted" if receipt["reason"] == "interrupt" else "runtime_failure"
        if receipt["returncode"] == 0 and receipt["reason"] == "worker_exit":
            result = json.loads((output / "result.json").read_text())
            if (
                result["job"] != job
                or result["code_and_config"] != pins
                or result["posterior_sha256"] != sha256(posterior)
                or sha256(job_path) != job_hash
                or any(sha256(root / p) != h for p, h in pins.items())
            ):
                status = "identity_failure"
            elif not result["diagnostics"]["screen_passed"]:
                status = "diagnostic_failure"
            elif result.get("status") != "computed_pending_scientific_review":
                status = "identity_failure"
            else:
                try:
                    if verify_fit_gate(root, job, output, posterior) != pins or any(
                        byte_count(root / p) < n for p, n in floors.items()
                    ):
                        raise ValueError("parent proof changed during actual fit")
                    status = "computed_pending_independent_review"
                except (ValueError, FileNotFoundError):
                    status = "identity_failure"
        if failures or quota_failure(root, parents):
            status = "storage_failure"
        write_json(
            control / "result.json",
            {
                "status": status,
                "sampler_call_slots_used": 1,
                "max_sampler_call_slots": 1,
                "parent_and_actual_working_bytes": byte_count(
                    *parents, output, control, raw, root / DESIGN
                ),
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        if quota_failure(root, parents):
            status = "storage_failure"
            final = json.loads((control / "result.json").read_text())
            final["status"] = status
            write_json(control / "result.json", final)
        if status != "computed_pending_independent_review":
            raise SystemExit(2)
    finally:
        ended.set()
        watcher.join(timeout=2)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run(Path(__file__).resolve().parents[1])
