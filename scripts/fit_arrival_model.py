"""Fit one gated source-specific exploration scaffold with a bounded process guardian."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["job", "gate", "output", "store"]:
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output, store = args.output.resolve(), args.store.resolve()
    if args.worker:
        limit_worker_file_size(64 * 1024**2)
        from analysis.arrival.model_fit import fit_exploration_job

        fit_exploration_job(
            Path(__file__).resolve().parents[1],
            json.loads(args.job.read_text()),
            args.gate.resolve(),
            output,
            store,
        )
        return
    if output.exists() or store.exists():
        raise ValueError("preserve previous fits; use new attempt paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    for name in ["job", "gate", "output", "store"]:
        command.extend(["--" + name, str(getattr(args, name).resolve())])
    job_hash, gate_hash = sha256(args.job), sha256(args.gate)
    started = time.monotonic()
    try:
        receipt = supervise(command, output.with_suffix(".log"), output.parent / "STOP", 600)
    except KeyboardInterrupt:
        receipt = {
            "returncode": 130,
            "reason": "interrupt",
            "elapsed_seconds": time.monotonic() - started,
        }
    receipt.update(
        {
            "job_sha256": job_hash,
            "gate_sha256": gate_hash,
            "runner_sha256": sha256(Path(__file__)),
            "input_identity_unchanged": job_hash == sha256(args.job)
            and gate_hash == sha256(args.gate),
        }
    )
    write_json(output.with_suffix(".supervisor.json"), receipt)
    if (
        receipt["returncode"] != 0
        or receipt["reason"] != "worker_exit"
        or not receipt["input_identity_unchanged"]
    ):
        raise SystemExit(130 if receipt["reason"] == "interrupt" else 1)
    result = json.loads((output / "result.json").read_text())
    if result["status"] != "computed_pending_scientific_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
