"""Build the ignored, local-only story map-layers bundle (contours + coastline)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.story.map_layers import export_map_layers  # noqa: E402


def main() -> None:
    """Require explicit roots; never acquire data or substitute fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    print(
        export_map_layers(
            source_root=args.source_root, output_root=args.output_root, config_path=args.config
        )
    )


if __name__ == "__main__":
    main()
