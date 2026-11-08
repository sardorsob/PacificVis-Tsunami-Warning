"""Fit one exact exploration sequence fold with a bounded subprocess guardian."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    job, output, store = args.job.resolve(), args.output.resolve(), args.store.resolve()
    if args.worker:
        limit_worker_file_size(64 * 1024**2)
        from analysis.arrival.model_cv import fit_sequence_job

        fit_sequence_job(
            Path(__file__).resolve().parents[1], json.loads(job.read_text()), output, store
        )
        return
    if output.exists() or store.exists():
        raise ValueError("retain previous attempts and use new paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    pins = {"job_sha256": sha256(job), "runner_sha256": sha256(Path(__file__))}
    try:
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--job",
                str(job),
                "--output",
                str(output),
                "--store",
                str(store),
            ],
            output.with_suffix(".log"),
            output.parent / "STOP",
            600,
        )
    except KeyboardInterrupt:
        receipt = {"returncode": 130, "reason": "interrupt"}
    receipt.update(pins)
    write_json(output.with_suffix(".supervisor.json"), receipt)
    if (
        receipt["returncode"] != 0
        or receipt["reason"] != "worker_exit"
        or sha256(job) != pins["job_sha256"]
        or sha256(Path(__file__)) != pins["runner_sha256"]
    ):
        raise SystemExit(1)
    result = json.loads((output / "result.json").read_text())
    if result["status"] != "computed_pending_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
