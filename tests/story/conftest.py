"""Fixtures for accepted-cache follow-up integration checks."""

from pathlib import Path

import pytest

from analysis.story.followups import FollowupInputs, load_followup_inputs


@pytest.fixture(scope="module")
def inputs() -> FollowupInputs:
    root = Path(__file__).resolve().parents[2]
    processed = root / "data/processed/tohoku/2026-09-09-valparaiso-reviewed-7576ffb-a"
    if not processed.exists():
        pytest.skip("accepted local scientific cache unavailable")
    return load_followup_inputs(
        processed,
        root / "artifacts/logs/runs/2026-09-16__0351__story-atlas__6c35d78",
        root / "artifacts/eda/shared/2026-10-05-final",
        root / "artifacts/releases/tohoku-descriptive-v1.json",
        root / "config/story-followups.toml",
    )
