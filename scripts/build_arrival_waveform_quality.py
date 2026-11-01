"""Audit all pinned native waveforms and emit a stripped descriptive review packet."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.waveform_quality import build_quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "observations", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(build_quality(args.inputs, args.observations, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
