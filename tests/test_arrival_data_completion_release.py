"""Integrity checks reject plausible-looking but incomplete releases."""

from copy import deepcopy

import pytest

from scripts.check_arrival_data_completion import (
    validate_ledger_preservation,
    validate_source_records,
)


def test_every_old_provenance_row_survives_with_unchanged_values() -> None:
    baseline = [{"source_id": "old", "sha256": "abc"}]
    new = {"source_id": "new", "sha256": "def"}
    validate_ledger_preservation(baseline + [new], baseline, {"new"})
    with pytest.raises(ValueError, match="conservation"):
        validate_ledger_preservation([new], baseline, {"new"})
    with pytest.raises(ValueError, match="provenance"):
        validate_ledger_preservation(
            [{"source_id": "old", "sha256": "changed"}, new], baseline, {"new"}
        )


def test_loss_duplicate_native_change_and_stale_hash_reject() -> None:
    import json

    source = {"report_id": "a", "source_sha256": "abc", "event_id": "dev"}
    row = {
        "source_record_id": "a",
        "source_sha256": "abc",
        "event_id": "dev",
        "native_record_json": json.dumps(source),
    }
    validate_source_records([row], {"a": source})
    for candidate in [[], [row, row], [{**row, "source_sha256": "changed"}]]:
        with pytest.raises(ValueError):
            validate_source_records(candidate, {"a": source})
    changed = deepcopy(row)
    changed["native_record_json"] = "{}"
    with pytest.raises(ValueError):
        validate_source_records([changed], {"a": source})
