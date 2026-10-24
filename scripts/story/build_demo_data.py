"""Build an ignored, local-only descriptive browser evidence bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.story.demo_export import export_demo_bundle  # noqa: E402


def main() -> None:
    """Require explicit roots; never acquire data or substitute fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    print(
        export_demo_bundle(
            source_root=args.source_root, output_root=args.output_root, config_path=args.config
        )
    )


if __name__ == "__main__":
    main()
