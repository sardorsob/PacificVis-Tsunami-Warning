"""Execute one preauthorized sensitivity case; the serial controller supervises it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_arrival_model_validation import limit_worker_file_size  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["job", "output", "store"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024**2)
    args = parser.parse_args()
    if not 1 <= args.max_output_bytes <= 64 * 1024**2:
        raise ValueError("per-file allocation must be1..64MiB")
    limit_worker_file_size(args.max_output_bytes)
    from analysis.arrival.model_sensitivity_fit import fit_sensitivity_job

    root = Path(__file__).resolve().parents[1]
    result = fit_sensitivity_job(root, json.loads(args.job.read_text()), args.output, args.store)
    if result["status"] != "computed_pending_scientific_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
