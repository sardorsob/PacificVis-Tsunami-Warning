"""Build a source-specific report for the initial NCEI exploration comparators."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_fit_report import write_fit_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fits", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_fit_report(
        Path(__file__).resolve().parents[1], args.fits.resolve(), args.output.resolve()
    )


if __name__ == "__main__":
    main()
