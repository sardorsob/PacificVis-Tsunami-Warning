"""The repeated-edge disposition must be traceable to native source identities."""

from pathlib import Path
from typing import Any

import pytest

from analysis.arrival import model_evidence
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import Lane, lane_arrays
from analysis.arrival.model_evidence import audit_repeated_edges


def test_native_ids_and_values_are_retained_without_independence_claim() -> None:
    root = Path(__file__).resolve().parents[1]
    if not all(
        (root / model_evidence.RAW / folder / (identity + ".json")).exists()
        for identity, (folder, _) in model_evidence.SOURCES.items()
    ):
        pytest.skip("immutable local source snapshots absent; cache-free audit tests still run")
    receipt = audit_repeated_edges(root)
    rows = receipt["records"]
    assert {row["native_source_id"] for row in rows} == {
        "11043",
        "11064",
        "25577",
        "25607",
        "19050",
        "37909",
    }
    assert len({(row["event_id"], row["site_id"]) for row in rows}) == 3
    assert all(row["ancestry"] == "unknown" and not row["included_primary"] for row in rows)


def synthetic_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path(__file__).resolve().parents[1]
    for name in ["model_evidence.py", "model_data.py", "evidence.py"]:
        output = tmp_path / "analysis/arrival" / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((root / "analysis/arrival" / name).read_bytes())
    rows = [
        {
            "record_id": f"fixture:{i + 1}",
            "event_id": "e1",
            "physical_site_id": site,
            "target": "NCEI-native-duration",
            "target_minutes": str(minutes),
            "distance_km": "100",
            "source_label": "A",
        }
        for i, (site, minutes) in enumerate([("s1", 10), ("s1", 20), ("s2", 30)])
    ]
    lane = lane_arrays("NCEI-native-duration", rows, {"e1": "q1"}, {"e1"})

    def load(_root: Path) -> tuple[dict[str, Lane], dict[str, Any]]:
        return {"NCEI-native-duration": lane}, {}

    path = tmp_path / model_evidence.RAW / "fixture/fixture.json"
    write_json(
        path,
        {
            "items": [
                {
                    "id": 101 + i,
                    "tsunamiEventId": 1,
                    "typeMeasurementId": 2,
                    "locationName": "A",
                    "travMins": minutes,
                }
                for i, minutes in enumerate([10, 20])
            ]
        },
    )
    monkeypatch.setattr(model_evidence, "load_lanes", load)
    monkeypatch.setattr(model_evidence, "SOURCES", {"fixture": ("fixture", sha256(path))})
    return path


def test_audit_fixture_preserves_both_records_without_local_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_source(tmp_path, monkeypatch)
    rows = audit_repeated_edges(tmp_path)["records"]
    assert [row["native_source_id"] for row in rows] == ["101", "102"]
    assert [row["native_reported_minutes"] for row in rows] == [10, 20]
    assert all(not row["included_primary"] for row in rows)


def test_native_source_corruption_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = synthetic_source(tmp_path, monkeypatch)
    path.write_text('{"items": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_repeated_edges(tmp_path)
