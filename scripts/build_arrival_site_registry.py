"""Build geography review proposals and source-native spatial sensitivity tables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.site_registry import build_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radii-km", type=float, nargs=3, default=[1, 2, 5])
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    print(
        build_registry(
            args.inputs, args.output, radii_km=tuple(args.radii_km), review_path=args.review
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
