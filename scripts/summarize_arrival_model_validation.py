"""Summarize retained synthetic trials, preserving incomplete status and calibration caveats."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_validation_report import (  # noqa: E402
    register_validation_report,
    write_validation_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    write_validation_report(
        Path(__file__).resolve().parents[1], args.batch.resolve(), args.output.resolve()
    )
    if args.register:
        register_validation_report(
            Path(__file__).resolve().parents[1], args.batch.resolve(), args.output.resolve()
        )


if __name__ == "__main__":
    main()
