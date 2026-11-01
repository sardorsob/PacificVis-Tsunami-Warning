"""Build a provisional development station crosswalk from verified local evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.stations import StationError, build_crosswalk  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Inventory identity tiers without asserting fit-ready historical deployments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry-config", type=Path, action="append", default=[])
    parser.add_argument("--header-config", type=Path, action="append", default=[])
    parser.add_argument(
        "--header-receipts",
        type=Path,
        action="append",
        default=[],
        help="Final receipts; required for every pinned-CDX header asset.",
    )
    parser.add_argument("--coops-config", type=Path)
    parser.add_argument("--coops-receipts", type=Path)
    parser.add_argument("--identity-review", type=Path)
    parser.add_argument(
        "--previous-crosswalk",
        type=Path,
        help="Frozen unique-report CSV to compare; never carries approval forward.",
    )
    args = parser.parse_args(argv)
    try:
        result = build_crosswalk(
            args.events,
            args.census,
            args.root,
            args.output,
            registry_configs=args.registry_config,
            header_configs=args.header_config,
            header_receipts=args.header_receipts,
            coops_config=args.coops_config,
            coops_receipts=args.coops_receipts,
            identity_review=args.identity_review,
            previous_crosswalk=args.previous_crosswalk,
        )
    except (StationError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "source_rows",
                    "tier_counts",
                    "header_probe_candidates",
                    "s4_disposition",
                    "verified_event_site_reports",
                    "reviewed_event_site_reports",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
