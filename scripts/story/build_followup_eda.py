"""Build explicit static follow-up diagnostics from accepted local evidence."""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analysis.story.followups import ROOT, load_followup_inputs, run_followups  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", default=["inputs"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.run_dir is not None:
        from analysis.story.artifacts import validate_story_output_path

        validate_story_output_path(args.run_dir.resolve())
        if args.run_dir.exists() or args.run_dir.resolve().is_relative_to(ROOT / "context"):
            parser.error("run directory must be fresh and outside private context")
        if "synthesis" not in args.tasks:
            parser.error("portable run requires synthesis")
    inputs = load_followup_inputs(
        ROOT / "data/processed/tohoku/2026-09-09-valparaiso-reviewed-7576ffb-a",
        ROOT / "artifacts/logs/runs/2026-09-16__0351__story-atlas__6c35d78",
        ROOT / "artifacts/eda/shared/2026-10-05-final",
        ROOT / "artifacts/releases/tohoku-descriptive-v1.json",
        ROOT / "config/story-followups.toml",
    )
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    results = run_followups(
        inputs,
        tuple(args.tasks),
        args.output,
        run_id=args.run_id or args.output.name,
        git_sha=git_sha,
        command="uv run python " + shlex.join(sys.argv),
    )
    if args.run_dir is not None:
        from analysis.story.followup_artifacts import record_followup_run

        record_followup_run(results, args.output, args.run_dir)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
