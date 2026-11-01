import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.prepare_arrival_time_context import contexts


def frozen(tmp_path: Path, **changes: Any) -> tuple[dict[str, Any], Path]:
    event = {
        "event_id": "fixture", "role": "development", "attribution_status": "single_source",
        "origin_evidence": json.dumps([{"time_basis": "UTC",
                                        "origin_time": "2011-03-11T05:46:24+00:00"}]),
        "usgs_time": "2011-03-11T05:46:24.120Z", "archive_url": "https://example.org/event",
        "source_sha256": "a" * 64,
        **changes,
    }
    data: dict[str, Any] = {"events": [event]}
    data["selection_sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(data))
    return data, path


def test_reference_is_explicitly_reviewed_not_original_prediction_origin(tmp_path: Path) -> None:
    rows, withheld = contexts(*frozen(tmp_path))
    assert len(rows) == 1 and not withheld
    assert rows[0]["calendar_year"] == "2011"
    assert "not_claimed_original_NTWC" in rows[0]["origin_basis"]


@pytest.mark.parametrize("changes", [
    {"attribution_status": "compound_unresolved"},
    {"origin_evidence": json.dumps([{"time_basis": "unknown"}])},
    {"usgs_time": "2012-03-11T05:46:24Z"},
])
def test_uncertain_contexts_are_withheld(tmp_path: Path, changes: dict[str, str]) -> None:
    rows, withheld = contexts(*frozen(tmp_path, **changes))
    assert not rows and "fixture" in withheld


def test_reserved_contexts_are_never_exported(tmp_path: Path) -> None:
    assert contexts(*frozen(tmp_path, role="sealed")) == ([], {})


def test_changed_selection_is_rejected(tmp_path: Path) -> None:
    data, path = frozen(tmp_path)
    data["events"][0]["usgs_time"] = "2012-03-11T05:46:24Z"
    with pytest.raises(ValueError, match="digest mismatch"):
        contexts(data, path)
