"""Supervise one exact node of the frozen Tohoku normalizer path."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import write_json  # noqa: E402
from analysis.arrival.model_bridge_path_fit import sample_path_job  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker:
        limit_worker_file_size(64 * 1024**2)
        sample_path_job(
            Path(__file__).resolve().parents[1],
            json.loads(args.job.read_text()),
            output,
            args.store.resolve(),
        )
        if (
            json.loads((output / "result.json").read_text())["status"]
            != "node_computed_pending_review"
        ):
            raise SystemExit(2)
    else:
        if output.exists() or args.store.exists():
            raise ValueError("new path node output and posterior required")
        output.parent.mkdir(parents=True, exist_ok=True)
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--job",
                str(args.job.resolve()),
                "--output",
                str(output),
                "--store",
                str(args.store.resolve()),
            ],
            output.with_suffix(".log"),
            output.parent / "STOP",
            600,
        )
        write_json(output.with_suffix(".supervisor.json"), receipt)
        if receipt["reason"] != "worker_exit" or receipt["returncode"] != 0:
            raise SystemExit(1)
