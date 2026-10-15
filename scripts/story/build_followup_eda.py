"""Build explicit static follow-up diagnostics from accepted local evidence."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analysis.story.followups import ROOT, load_followup_inputs, run_followups  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", default=["inputs"])
    args = parser.parse_args()
    inputs = load_followup_inputs(
        ROOT / "data/processed/tohoku/2026-09-09-valparaiso-reviewed-7576ffb-a",
        ROOT / "artifacts/logs/runs/2026-09-16__0351__story-atlas__6c35d78",
        ROOT / "artifacts/eda/shared/2026-10-05-final",
        ROOT / "artifacts/releases/tohoku-descriptive-v1.json",
        ROOT / "config/story-followups.toml",
    )
    run_followups(inputs, tuple(args.tasks), args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
