"""Run one finite known-normalizer or two-variance exploration bridge prototype."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import write_json  # noqa: E402
from analysis.arrival.model_bridge_validation import actual_pilot, calibration  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--augmented", type=Path)
    parser.add_argument("--kind", choices=["event", "distance-scale"], default="event")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if bool(args.training) != bool(args.augmented):
        parser.error("both training and augmented folders are required together")
    if args.worker:
        limit_worker_file_size(64 * 1024**2)
        if args.training:
            actual_pilot(
                root, args.training.resolve(), args.augmented.resolve(), output, kind=args.kind
            )
        else:
            calibration(root, output)
    else:
        if output.exists() or not output.is_relative_to(root):
            raise ValueError("new project-local output required")
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--output",
            str(output),
        ]
        if args.training:
            command += [
                "--training",
                str(args.training.resolve()),
                "--augmented",
                str(args.augmented.resolve()),
            ]
            command += ["--kind", args.kind]
        receipt = supervise(command, output.with_suffix(".log"), output.parent / "STOP", 600)
        write_json(output.with_suffix(".supervisor.json"), receipt)
        if receipt["returncode"] != 0 or receipt["reason"] != "worker_exit":
            raise SystemExit(1)
