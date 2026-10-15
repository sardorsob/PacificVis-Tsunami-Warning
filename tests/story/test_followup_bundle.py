"""Portable, immutable outputs reproduce independently of location."""

import json
from pathlib import Path

import pytest

from analysis.story.artifacts import sha256_file
from analysis.story.followups import FollowupInputs, run_followups

TASKS = ("regional", "coverage", "signal", "contours", "synthesis")


def test_complete_bundle_has_hashed_references_and_table_derived_report(
    inputs: FollowupInputs, tmp_path: Path
) -> None:
    output = tmp_path / "bundle"
    result = run_followups(inputs, TASKS, output, run_id="test", git_sha="a" * 40)
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["artifacts"]) == 16
    for artifact in manifest["artifacts"]:
        assert artifact["sha256"] == sha256_file(output / artifact["path"])
        assert artifact["caption"] and artifact["alt_text"]
        for reference in artifact["references"]:
            assert reference["sha256"] == sha256_file(output / reference["path"])
    assert result["arrival_comparison_allowed"] is False
    assert len(result["tables"]["findings"]) == 5
    report = (output / "report.md").read_text()
    for row in result["tables"]["coverage-by-window"]:
        if row["window_id"] == "common_day":
            assert f"{row['strict_percent']:.4f}%" in report
    assert "MCAR" in report and "unclassified" in report
    assert "context/" not in report


def test_fresh_location_reproduces_stable_bytes(inputs: FollowupInputs, tmp_path: Path) -> None:
    for name in ("a", "b"):
        run_followups(inputs, TASKS, tmp_path / name, run_id="same", git_sha="b" * 40)
    first, second = tmp_path / "a", tmp_path / "b"
    assert {p.name for p in first.iterdir()} == {p.name for p in second.iterdir()}
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name


def test_synthesis_refuses_incomplete_evidence_before_writing(
    inputs: FollowupInputs, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="synthesis"):
        run_followups(inputs, ("synthesis",), tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
