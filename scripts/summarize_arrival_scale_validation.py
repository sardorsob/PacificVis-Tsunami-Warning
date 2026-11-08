"""Summarize retained distance-scale simulation trials without changing their outcomes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_scale_report import scale_validation_report  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scale_validation_report(
        Path(__file__).resolve().parents[1], args.batch.resolve(), args.output.resolve()
    )
