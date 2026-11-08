"""One CV fold worker; its caller owns the conserved call/storage/timeout allocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_arrival_model_validation import limit_worker_file_size  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["job", "output", "store"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    limit_worker_file_size(64 * 1024**2)
    from analysis.arrival.model_curvature_sequence import run_fold

    root = Path(__file__).resolve().parents[1]
    run_fold(root, json.loads(args.job.read_text()), args.output.resolve(), args.store.resolve())
