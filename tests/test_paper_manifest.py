import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_paper_manifest import build


def receipt(root: Path, name: str, status: str, payload: bytes = b"data") -> Path:
    run = root / name
    run.mkdir()
    source: dict[str, str] = dict.fromkeys(
        ("source_class", "publisher", "crs", "horizontal_datum", "vertical_datum",
         "coordinate_order", "temporal_semantics", "units", "station_metadata"), "unknown"
    )
    source.update(source_id="sample", url="https://example.org/data", local_path="raw/data")
    digest = hashlib.sha256(payload).hexdigest()
    (run / "inputs.json").write_text(json.dumps([source]))
    (run / "outputs.json").write_text(json.dumps([{
        "source_id": "sample", "status": status, "reason": "HTTP 403" if status ==
        "quarantined" else "not applicable", "sha256": digest,
    }]))
    (run / "meta.json").write_text('{"timestamp_utc":"2026-10-31T12:00:00Z"}')
    (run / "config.json").write_text(json.dumps({"toml": 'terms = "fixture"'}))
    if status in {"downloaded", "cached"}:
        (root / "raw").mkdir(exist_ok=True)
        (root / "raw/data").write_bytes(payload)
        (root / "raw/data.sha256").write_text(digest + "\n")
    return run


def test_failures_are_retained_but_do_not_replace_success(tmp_path: Path) -> None:
    runs = [receipt(tmp_path, "01", "downloaded"), receipt(tmp_path, "02", "quarantined")]
    row = build(tmp_path, runs)[0]
    assert row["status"] == "candidate"
    assert row["local_path"] == "raw/data"
    assert len(json.loads(row["notes"])["attempts"]) == 2
    assert "not implied" in row["notes"]


def test_unavailable_source_has_attempt_date_not_claimed_bytes(tmp_path: Path) -> None:
    row = build(tmp_path, [receipt(tmp_path, "01", "quarantined")])[0]
    assert row["accessed_on"] == "2026-10-31"
    assert row["status"] == "blocked"
    assert row["sha256"] == row["local_path"] == "not-downloaded"


def test_local_checksum_corruption_fails(tmp_path: Path) -> None:
    run = receipt(tmp_path, "01", "downloaded")
    (tmp_path / "raw/data").write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        build(tmp_path, [run])


def test_conflicting_success_history_fails(tmp_path: Path) -> None:
    runs = [receipt(tmp_path, "01", "downloaded"), receipt(tmp_path, "02", "cached", b"new")]
    with pytest.raises(ValueError, match="source bytes changed"):
        build(tmp_path, runs)


def test_conflicting_source_identity_fails(tmp_path: Path) -> None:
    first = receipt(tmp_path, "01", "downloaded")
    second = receipt(tmp_path, "02", "cached")
    p = second / "inputs.json"
    data = json.loads(p.read_text())
    data[0]["url"] = "https://example.org/other"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="source identity changed"):
        build(tmp_path, [first, second])


def test_publisher_correction_keeps_visible_history(tmp_path: Path) -> None:
    first = receipt(tmp_path, "01", "downloaded")
    second = receipt(tmp_path, "02", "cached")
    p = second / "inputs.json"
    data = json.loads(p.read_text())
    data[0]["publisher"] = "verified operator"
    p.write_text(json.dumps(data))
    row = build(tmp_path, [first, second])[0]
    assert row["publisher"] == "verified operator"
    changes = json.loads(row["notes"])["metadata_changes"]
    assert changes == [{"field": "publisher", "previous": "unknown",
                        "updated": "verified operator", "run": "02"}]
