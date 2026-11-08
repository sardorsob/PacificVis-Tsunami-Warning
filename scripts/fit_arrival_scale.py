"""Fit the validated distance-dependent spread candidate with a bounded guardian."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--worker", action="store_true")
    a = p.parse_args()
    job = a.job.resolve()
    out = a.output.resolve()
    store = a.store.resolve()
    if a.worker:
        limit_worker_file_size(64 * 1024**2)
        from analysis.arrival.model_scale_fit import fit_exploration_scale

        fit_exploration_scale(
            Path(__file__).resolve().parents[1], json.loads(job.read_text()), out, store
        )
    else:
        if out.exists() or store.exists():
            raise ValueError("new attempt paths required")
        out.parent.mkdir(parents=True, exist_ok=True)
        jobhash = sha256(job)
        runnerhash = sha256(Path(__file__))
        try:
            receipt = supervise(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--job",
                    str(job),
                    "--output",
                    str(out),
                    "--store",
                    str(store),
                ],
                out.with_suffix(".log"),
                out.parent / "STOP",
                600,
            )
        except KeyboardInterrupt:
            receipt = {"returncode": 130, "reason": "interrupt"}
        write_json(
            out.with_suffix(".supervisor.json"),
            {**receipt, "job_sha256": jobhash, "runner_sha256": runnerhash},
        )
        if (
            receipt["returncode"] != 0
            or receipt["reason"] != "worker_exit"
            or sha256(job) != jobhash
            or sha256(Path(__file__)) != runnerhash
        ):
            raise SystemExit(1)
        if (
            json.loads((out / "result.json").read_text())["status"]
            != "computed_pending_scientific_review"
        ):
            raise SystemExit(2)
