"""Safe publication boundaries for the follow-up diagnostic runner."""

from pathlib import Path

import pytest

from analysis.story.followups import FollowupInputs, run_followups


def test_runner_rejects_arrival_task_without_writing(
    inputs: FollowupInputs, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="task"):
        run_followups(inputs, ("arrivals",), tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_runner_refuses_overwrite_and_app_exports(inputs: FollowupInputs, tmp_path: Path) -> None:
    output = tmp_path / "run"
    run_followups(inputs, ("inputs",), output)
    first = (output / "inputs.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_followups(inputs, ("inputs",), output)
    assert (output / "inputs.json").read_bytes() == first
    with pytest.raises(ValueError):
        run_followups(inputs, ("inputs",), tmp_path / "app/public/data/bad")
