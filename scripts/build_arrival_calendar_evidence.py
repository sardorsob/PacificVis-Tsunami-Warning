"""Build documentary calendar evidence and separate date-rule diagnostics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.calendar_evidence import build_calendar_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "lineage", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(build_calendar_evidence(args.inputs, args.lineage, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
