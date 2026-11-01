"""Measure development arrival-table support and archive-code repetition offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.design import DesignError, build_design  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Build deterministic design counts without exposing sealed values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path)
    args = parser.parse_args(argv)
    try:
        summary = build_design(
            args.config, args.census, args.annotations, args.output, crosswalk=args.crosswalk
        )
    except (DesignError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                key: summary[key]
                for key in ("development_events", "source_pair_values", "archive_codes")
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
