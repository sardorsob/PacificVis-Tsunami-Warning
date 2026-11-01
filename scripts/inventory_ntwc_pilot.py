"""Inventory checksummed NTWC snapshots offline; never normalize arrival times."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ntwc_archive import ArchiveError, inventory  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Write development raw cells and a masked structural census for sealed pages."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inventory(args.config, args.root, args.output)
    except (ArchiveError, OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
