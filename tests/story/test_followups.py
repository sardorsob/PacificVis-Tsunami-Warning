"""Follow-up evidence must preserve source identity and keep arrival gates closed."""

import json
from pathlib import Path

import pytest

from analysis.story.followups import FollowupInputs, load_followup_inputs, metadata_index

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data/processed/tohoku/2026-09-09-valparaiso-reviewed-7576ffb-a"
ATLAS = ROOT / "artifacts/logs/runs/2026-09-16__0351__story-atlas__6c35d78"
SHARED = ROOT / "artifacts/eda/shared/2026-10-05-final"
RELEASE = ROOT / "artifacts/releases/tohoku-descriptive-v1.json"
CONFIG = ROOT / "config/story-followups.toml"


def test_normalized_metadata_keeps_identity_zero_and_qc(inputs: FollowupInputs) -> None:
    row = inputs.metadata[("valp", "2011-03-12T01:30:00Z")]
    assert row["observation_id"] == "valp-2011-03-12T01:30:00Z"
    assert float(row["raw_value"]) == 0
    assert json.loads(row["source_extra"])["out_of_range"] == "T"
    assert len(inputs.atlas.stations) == 10
    assert len(inputs.shared["picks"]) == 160


def test_metadata_rejects_orphans_duplicates_and_semantics() -> None:
    station = dict(station_id="s", source_id="publisher", units="m", vertical_reference="unknown")
    row = dict(
        station_id="s",
        source_id="publisher",
        units="m",
        vertical_reference="unknown",
        observed_at_utc="2011-03-11T00:00:00Z",
        observation_id="sample",
        source_time="original",
        source_extra="",
        raw_value="0",
    )
    assert (
        metadata_index([row], {"s": station})[("s", row["observed_at_utc"])]["source_time"]
        == "original"
    )
    for rows in [[row, row], [row | {"station_id": "orphan"}], [row | {"units": "cm"}]]:
        with pytest.raises(ValueError):
            metadata_index(rows, {"s": station})


def test_changed_fingerprint_fails_before_loading_data(tmp_path: Path) -> None:
    (tmp_path / "inputs.json").write_text(
        json.dumps([{"path": "config/story-followups.toml", "sha256": "bad"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="checksum"):
        load_followup_inputs(PROCESSED, tmp_path, SHARED, RELEASE, CONFIG)
