"""One supervised node in the frozen curvature numerical path."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_curvature_path_sampling import sample_node  # noqa:E402
from scripts.run_arrival_model_validation import limit_worker_file_size  # noqa:E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--store", required=True, type=Path)
    a = p.parse_args()
    limit_worker_file_size(64 * 1024**2)
    sample_node(
        Path(__file__).resolve().parents[1],
        json.loads(a.job.read_text()),
        a.output.resolve(),
        a.store.resolve(),
    )
    if (
        json.loads((a.output / "result.json").read_text())["status"]
        != "node_computed_pending_review"
    ):
        raise SystemExit(2)
