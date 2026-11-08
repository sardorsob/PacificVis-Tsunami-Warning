"""Check the declared fixed-anchor SD priors before candidate inference."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_scale_prior import run_scale_prior  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    run_scale_prior(
        Path(__file__).resolve().parents[1], args.output.resolve(), args.store.resolve()
    )
