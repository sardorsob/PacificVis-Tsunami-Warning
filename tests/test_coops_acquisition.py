import hashlib
import json
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest

from pipeline.acquisition import SourceContract, load_contracts
from scripts.check_coops_acquisition import check_payload, verify


@pytest.fixture
def contract() -> SourceContract:
    return next(
        c
        for c in load_contracts(Path("config/coops-waveform-audit.toml"))
        if c.source_id == "coops-usp000fjta-1617760-one_minute_water_level"
    )


def test_grid_counts_retain_blank_zero_and_qc(contract: SourceContract) -> None:
    result = check_payload(
        contract,
        {
            "metadata": {"id": "1617760"},
            "data": [
                {"t": "2007-08-14 00:00", "v": "0", "q": "p"},
                {"t": "2007-08-14 00:02", "v": ""},
                {"t": "2007-08-14 00:02", "v": "nan"},
            ],
        },
    )
    assert result["rows"] == 3
    assert result["missing_timestamps"] == 5758
    assert result["duplicate_timestamps"] == 1
    assert result["blank_or_nonfinite_values"] == 2
    assert result["quality_codes"] == {"p": 1, "not_provided": 2}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"error": {"message": "unavailable"}}, "provider error"),
        ({"metadata": {"id": "wrong"}, "data": []}, "station mismatch"),
        (
            {"metadata": {"id": "1617760"}, "data": [{"t": "2007-08-18 00:00", "v": "1"}]},
            "UTC grid",
        ),
    ],
)
def test_invalid_evidence_is_rejected(
    contract: SourceContract,
    payload: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        check_payload(contract, payload)


@pytest.mark.parametrize("payload_kind", ["data", "error", "mixed"])
def test_receipt_hash_and_reserved_event_guard(
    contract: SourceContract, tmp_path: Path, payload_kind: str,
) -> None:
    config = tmp_path / "contract.toml"
    config.write_text(
        "[assets.test]\n"
        + "\n".join(f"{key} = {json.dumps(str(value))}" for key, value in asdict(contract).items())
    )
    event_config = tmp_path / "events.toml"
    event = tomllib.loads(Path("config/ntwc-archive-batch.toml").read_text())["events"][
        "usp000fjta"
    ]
    event_config.write_text(
        '[events.usp000fjta]\nrole = "development"\nusgs_time = ' + json.dumps(event["usgs_time"])
    )
    raw = {
        "data": b'{"metadata":{"id":"1617760"},"data":[]}',
        "error": b'{"error":{"message":"No data was found"}}',
        "mixed": b'{"error":{"message":"No data was found"},"data":[]}',
    }[payload_kind]
    path = tmp_path / contract.local_path
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest)
    receipts = tmp_path / "outputs.json"
    receipts.write_text(
        json.dumps(
            [
                {
                    "source_id": contract.source_id,
                    "local_path": str(contract.local_path),
                    "status": "downloaded",
                    "reason": "not applicable",
                    "bytes": len(raw),
                    "sha256": digest,
                }
            ]
        )
    )
    if payload_kind == "mixed":
        with pytest.raises(ValueError, match="mixes an error and data"):
            verify(config, receipts, event_config, tmp_path)
    else:
        result = verify(config, receipts, event_config, tmp_path)
        entry = cast(list[dict[str, Any]], result["results"])[0]
        if payload_kind == "error":
            assert entry["payload_status"] == "provider_error"
            assert entry["provider_error"] == {"message": "No data was found"}
            assert "rows" not in entry
        else:
            assert entry["rows"] == 0
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="checksum/size"):
        verify(config, receipts, event_config, tmp_path)
    path.write_bytes(raw)
    event_config.write_text(
        event_config.read_text().replace('"development"', '"sealed_evaluation"')
    )
    with pytest.raises(ValueError, match="reserved event"):
        verify(config, receipts, event_config, tmp_path)
