"""Supervise one finite known-normalizer path calibration, without model sampling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import write_json  # noqa: E402
from analysis.arrival.model_bridge_path_validation import calibrate_paths  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    root = Path(__file__).resolve().parents[1]
    if args.worker:
        limit_worker_file_size(64 * 1024**2)
        calibrate_paths(root, output)
    else:
        if output.exists() or not output.is_relative_to(root):
            raise ValueError("new project-local output required")
        output.parent.mkdir(parents=True, exist_ok=True)
        result = supervise(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(output)],
            output.with_suffix(".log"),
            output.parent / "STOP",
            600,
        )
        write_json(output.with_suffix(".supervisor.json"), result)
        if result["returncode"] != 0 or result["reason"] != "worker_exit":
            raise SystemExit(1)
