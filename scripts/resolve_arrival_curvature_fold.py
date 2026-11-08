"""Assemble one independently accepted curvature path score; no sampling."""

# pyright: basic
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_curvature_resolution_io import write_resolution  # noqa:E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    write_resolution(Path(__file__).resolve().parents[1], a.output)
