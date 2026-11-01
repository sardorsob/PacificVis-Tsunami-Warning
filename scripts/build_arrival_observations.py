"""Build individual observations and original reported-pair views."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.observations import build_observations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "sites", "lineage", "calendars", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(build_observations(args.inputs, args.sites, args.lineage, args.calendars, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
