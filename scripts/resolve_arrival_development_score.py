"""Run the prospectively admitted, fixed zero-MCMC NCEI score resolution."""

# pyright: basic
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024**2)
    args = parser.parse_args()
    if not 1 <= args.max_output_bytes <= 64 * 1024**2:
        raise ValueError("per-file allocation must be1..64MiB")
    for key in [
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ]:
        os.environ[key] = "2"
    from scripts.run_arrival_model_validation import limit_worker_file_size

    limit_worker_file_size(args.max_output_bytes)
    from analysis.arrival.model_development_score_resolution import SUCCESS, run_resolution

    result = run_resolution(Path(__file__).resolve().parents[1], args.output)
    if result["status"] != SUCCESS:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
