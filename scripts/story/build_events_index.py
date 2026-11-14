"""Build the ignored, local-only events index that pins the story bundles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.story.events_index import build_events_index  # noqa: E402


def main() -> None:
    """Require explicit paths; a different existing index needs --replace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(
        build_events_index(
            bundles_root=args.bundles_root, config_path=args.config, replace=args.replace
        )
    )


if __name__ == "__main__":
    main()
