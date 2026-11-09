"""One fixed development dispatch or versioned read-only scientific artifact proof."""
# pyright: basic

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# This module is stdlib-only; bootstrap runs before every scientific import.
from analysis.arrival import model_development_technical_completion as program


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--phase", choices=program.PHASES, required=True)
    p.add_argument("--proof-only", action="store_true")
    p.add_argument("--job", type=Path)
    p.add_argument("--proof-output", type=Path)
    a = p.parse_args()
    if a.proof_only:
        program.require(
            a.job is not None and a.proof_output is not None, "fixed proof paths required"
        )
        program.proof_only(a.root.resolve(), a.phase, a.job, a.proof_output)
    else:
        program.run_one(a.root.resolve(), a.phase)


if __name__ == "__main__":
    main()
