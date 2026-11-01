"""Build source lineage from pinned development data and the capped source pilot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.lineage import build_lineage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "sites", "receipts", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(build_lineage(args.inputs, args.sites, args.receipts, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
