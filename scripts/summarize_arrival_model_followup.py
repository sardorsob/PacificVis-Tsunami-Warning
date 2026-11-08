"""Compare the independent recovery follow-up with the selected initial setting."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_recovery_followup import write_followup_comparison  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_followup_comparison(Path(__file__).resolve().parents[1], args.output.resolve())
