"""Run one bounded synthetic recovery/SBC fit, preserving logs and failed attempts."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import sha256, write_json  # noqa: E402


def _terminate_group(worker: subprocess.Popen[bytes]) -> None:
    """Reap the leader and kill remaining group members even if that leader exits first."""
    try:
        try:
            os.killpg(worker.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            worker.poll()
            try:
                os.killpg(worker.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
    finally:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        worker.wait(timeout=5)


def supervise(command: list[str], log: Path, stop: Path, timeout: int) -> dict[str, object]:
    """Bound the worker process group and retain explicit stop/timeout evidence."""
    if not 1 <= timeout <= 3600 or log.exists():
        raise ValueError("require timeout 1..3600 seconds and a new log path")
    if stop.exists():
        return {"returncode": None, "reason": "stop_signal", "elapsed_seconds": 0.0}
    started = time.monotonic()
    reason = "worker_exit"
    with log.open("x", encoding="utf-8") as stream:
        worker = subprocess.Popen(
            command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while worker.poll() is None:
                if stop.exists() or time.monotonic() - started > timeout:
                    reason = "stop_signal" if stop.exists() else "timeout"
                    break
                time.sleep(0.25)
        finally:
            _terminate_group(worker)
    return {
        "returncode": worker.returncode,
        "reason": reason,
        "elapsed_seconds": time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--timeout", default=600, type=int)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    job_path, output, store = args.job.resolve(), args.output.resolve(), args.store.resolve()
    job_hash = sha256(job_path)
    if args.worker:
        from analysis.arrival.model_validation import fit_synthetic_job

        job = json.loads(job_path.read_text(encoding="utf-8"))
        fit_synthetic_job(Path(__file__).resolve().parents[1], job, output, store)
        return
    if output.exists() or store.exists():
        raise ValueError("use a new attempt output/store; preserve previous attempts")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--job",
        str(job_path),
        "--output",
        str(output),
        "--store",
        str(store),
    ]
    started = time.monotonic()
    try:
        receipt = supervise(
            command, output.with_suffix(".log"), output.parent / "STOP", args.timeout
        )
    except KeyboardInterrupt:
        receipt = {
            "returncode": 130,
            "reason": "interrupt",
            "elapsed_seconds": time.monotonic() - started,
        }
    receipt.update({"job_sha256": job_hash, "runner_sha256": sha256(Path(__file__))})
    result_path = output / "result.json"
    receipt["diagnostic_screen_passed"] = (
        json.loads(result_path.read_text(encoding="utf-8"))["diagnostics"]["screen_passed"]
        if result_path.exists()
        else False
    )
    write_json(output.with_suffix(".supervisor.json"), receipt)
    if receipt["returncode"] != 0 or receipt["reason"] != "worker_exit":
        raise SystemExit(130 if receipt["reason"] == "interrupt" else 1)
    if not receipt["diagnostic_screen_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
