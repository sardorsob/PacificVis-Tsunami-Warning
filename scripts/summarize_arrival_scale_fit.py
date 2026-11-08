"""Report the exploratory distance-dependent spread fit and its remaining discrepancies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_scale_fit_report import scale_fit_report  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    scale_fit_report(Path(__file__).resolve().parents[1], a.output.resolve())
