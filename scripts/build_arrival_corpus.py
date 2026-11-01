"""Build a paper-only corpus of reported arrival clocks with complete row accounting."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.arrival_corpus import CorpusError, build_corpus  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=Path, help="optional rows.csv instead of census/rows.json")
    parser.add_argument("--time-context", type=Path, help="reviewed event year/origin context CSV")
    parser.add_argument("--crosswalk", type=Path, help="reviewed report-to-site/deployment CSV")
    parser.add_argument("--time-evidence", type=Path, help="hash-bound reviewed time-rule CSV")
    args = parser.parse_args(argv)
    try:
        result = build_corpus(
            args.config,
            args.census,
            args.output,
            rows_path=args.rows,
            time_context=args.time_context,
            crosswalk=args.crosswalk,
            time_evidence=args.time_evidence,
        )
    except (CorpusError, OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "development_events",
                    "reserved_events_excluded",
                    "source_rows",
                    "exact_pairs",
                    "rejected_or_uncertain",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
