"""Run only the prospectively accepted LATA precision supplement."""

# pyright: basic
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_arrival_model_validation import limit_worker_file_size  # noqa: E402

if __name__ == "__main__":
    limit_worker_file_size(64 * 1024**2)
    from analysis.arrival.model_curvature_precision import run

    run(Path(__file__).resolve().parents[1])
