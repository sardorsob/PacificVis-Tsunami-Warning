"""Attach independent numerical acceptance to a stopped fold, preserving its failed attempt."""

# pyright: basic
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.model_checkpoint_resolution import attach_resolution  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["output", "store", "state", "receipt"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    attach_resolution(
        Path(__file__).resolve().parents[1], a.output, a.store, a.state, a.receipt.resolve()
    )
