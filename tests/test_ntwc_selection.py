import hashlib
from pathlib import Path

import pytest

from scripts.prepare_ntwc_batch import (
    ANCHORS,
    IndexParser,
    reserve_events,
    verified_text,
    write_identical_or_new,
)


def test_index_preserves_two_same_date_events_and_rejects_duplicate_keys() -> None:
    parser = IndexParser()
    parser.feed(
        '<a href="/previous.events/?p=09-05-04a">first</a>'
        '<a href="/previous.events/?p=09-05-04b">second</a>'
    )
    assert list(parser.entries) == ["09-05-04a", "09-05-04b"]
    with pytest.raises(ValueError, match="duplicate"):
        parser.feed('<a href="/previous.events/?p=09-05-04a">repeat</a>')


def test_reservation_is_deterministic_and_keeps_anchors_and_region_support() -> None:
    events = [{"event_id": f"e{i}", "region": str(i % 4)} for i in range(20)]
    events.extend({"event_id": event_id, "region": "0"} for event_id in ANCHORS)
    held = reserve_events(events, 5)
    assert len(held) == 5
    assert not held & ANCHORS
    assert held == reserve_events(list(reversed(events)), 5)
    assert {row["region"] for row in events if row["event_id"] not in held} == set("0123")


def test_failed_checksum_and_conflicting_freeze_are_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "index.html"
    source.write_text("original", encoding="utf-8")
    source.with_name("index.html.sha256").write_text(
        hashlib.sha256(b"original").hexdigest(), encoding="utf-8"
    )
    assert verified_text(source) == "original"
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        verified_text(source)
    with pytest.raises(ValueError, match="refusing"):
        write_identical_or_new(source, "replacement")
    assert source.read_text(encoding="utf-8") == "changed"


def test_reservation_refuses_to_empty_region() -> None:
    with pytest.raises(ValueError, match="insufficient"):
        reserve_events([{"event_id": "only", "region": "one"}], 1)
