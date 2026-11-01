"""Secondary NCEI records retain source meaning and never become NTWC labels."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.build_ncei_observations import build_ncei_observations


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest)
    return digest


def record(number: int, **changes: Any) -> dict[str, Any]:
    return dict(
        id=number,
        tsunamiEventId=2373,
        year=2001,
        month=6,
        day=23,
        locationName="Synthetic gauge",
        latitude=10.5,
        longitude=-170.25,
        typeMeasurementId=2,
        doubtful="n",
        publish=True,
        arrDay=24,
        arrHour=1,
        arrMin=2,
        travHours=0,
        travMins=30,
        maxWaveArrDay=25,
        maxWaveArrHour=2,
        maxWaveArrMin=3,
        **changes,
    )


def fixture(
    root: Path,
    pages: list[list[dict[str, Any]]] | None = None,
    *,
    total_pages: int | None = None,
    total_items: int | None = None,
) -> None:
    pages = pages if pages is not None else [[record(1)]]
    events = [
        dict(event_id="event", role="development", usgs_time="2001-06-23T20:33:14Z"),
        dict(event_id="reserved", role="sealed_evaluation", usgs_time="2001-07-23T00:00:00Z"),
    ]
    selection: dict[str, Any] = dict(events=events)
    digest = hashlib.sha256(
        json.dumps(selection, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    selection["selection_sha256"] = digest
    write_json(root / "selection.json", selection)
    (root / "events.toml").write_text(
        f'selection_sha256="{digest}"\n'
        + "\n".join(
            f"[events.{row['event_id']}]\n"
            + "\n".join(f"{key}={json.dumps(value)}" for key, value in row.items())
            for row in events
        )
    )
    metadata_path = root / "raw/metadata.json"
    metadata_hash = write_json(
        metadata_path,
        dict(
            items=[dict(id=2373, year=2001, month=6, day=23)],
            page=1,
            totalPages=1,
            itemsPerPage=20,
            totalItems=1,
        ),
    )
    match = dict(
        development_event_id="event",
        ncei_event_id="2373",
        metadata_source_id="metadata",
        metadata_raw_path="raw/metadata.json",
        metadata_sha256=metadata_hash,
        review_status="independently_reviewed",
        reviewer="independent fixture reviewer",
        review_basis="Synthetic source date and event match",
        metadata_source_url="https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/events?id=2373",
    )
    with (root / "matches.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(match))
        writer.writeheader()
        writer.writerow(match)
    fields = [
        "id",
        "tsunamiEventId",
        "arrDay",
        "arrHour",
        "arrMin",
        "travHours",
        "travMins",
        "typeMeasurementId",
        "publish",
        "doubtful",
        "maxWaveArrDay",
        "maxWaveArrHour",
        "maxWaveArrMin",
        "latitude",
        "longitude",
    ]
    write_json(
        root / "schema.json",
        dict(
            components=dict(
                schemas=dict(
                    RunupView=dict(properties={key: {"type": "integer"} for key in fields})
                )
            ),
            paths={"/hazard-service/api/v1/tsunamis/runups": {"get": {"summary": "fixture"}}},
        ),
    )
    source = (
        "arrival of the initial tsunami wave\ntime in hours and minutes\n"
        "arrival of the maximum tsunami wave\nlatitude and longitude"
    )
    (root / "semantics.js").write_text(source)
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    proof: dict[str, Any] = dict(official_app_semantic_evidence=[])
    for text in source.splitlines():
        proof["official_app_semantic_evidence"].append(
            dict(
                source_sha256=source_hash,
                start_char=source.index(text),
                end_char=source.index(text) + len(text),
                text=text,
            )
        )
    write_json(root / "proof.json", proof)
    contracts: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for index, records in enumerate(pages, 1):
        source_id = f"page-{index}"
        relative = f"raw/{source_id}.json"
        payload = dict(
            items=records,
            page=index,
            totalPages=total_pages or len(pages),
            itemsPerPage=2,
            totalItems=total_items if total_items is not None else sum(map(len, pages)),
        )
        digest = write_json(root / relative, payload)
        url = f"https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/runups?tsunamiEventId=2373&typeMeasurementId=2&typeMeasurementId=3&itemsPerPage=2&page={index}"
        contract = dict(
            source_id=source_id,
            source_class="secondary_reported station observations sample",
            availability="approved",
            reason="Synthetic test",
            url=url,
            local_path=relative,
            format="NOAA NCEI HaZEL JSON",
            publisher="NOAA NCEI",
            expected_content_signature="JSON items",
            expected_prefix="{",
            units="source-defined",
            crs="unknown",
            horizontal_datum="unknown",
            vertical_datum="unknown",
            coordinate_order="source-defined",
            temporal_semantics="source-defined",
            station_metadata=json.dumps(dict(event_id="event", ncei_event_id=2373)),
        )
        contracts.append(contract)
        receipts.append(
            dict(
                source_id=source_id,
                local_path=relative,
                status="downloaded",
                reason="not applicable",
                sha256=digest,
                bytes=(root / relative).stat().st_size,
                final_url=url,
            )
        )
    (root / "sources.toml").write_text(
        "\n".join(
            f"[assets.{c['source_id']}]\n"
            + "\n".join(f"{key}={json.dumps(value)}" for key, value in c.items())
            for c in contracts
        )
    )
    write_json(root / "inputs.json", contracts)
    write_json(root / "outputs.json", receipts)


def run(root: Path, output: str = "out") -> dict[str, Any]:
    return build_ncei_observations(
        [root / "sources.toml"],
        [root / "outputs.json"],
        root / "matches.csv",
        root / "events.toml",
        root / "selection.json",
        root / "schema.json",
        root / "proof.json",
        root / "semantics.js",
        root,
        root / output,
    )


def read(root: Path, name: str = "observations") -> list[dict[str, str]]:
    with gzip.open(root / f"out/{name}.csv.gz", "rt", newline="") as handle:
        return list(csv.DictReader(handle))


def test_zero_components_raw_fields_and_secondary_duration_are_separate(tmp_path: Path) -> None:
    first = record(1)
    second = record(2)
    second.pop("travHours")
    fixture(tmp_path, [[first, second]])
    summary = run(tmp_path)
    rows = read(tmp_path)
    assert summary["source_records"] == 2 and summary["reported_duration_candidates"] == 1
    assert rows[0]["reported_duration_minutes"] == "30"
    assert rows[0]["native_travHours"] == "0"
    assert (
        rows[1]["travel_state"] == "partial_components"
        and rows[1]["reported_duration_minutes"] == "unknown"
    )
    assert rows[1]["native_travHours"] == "not_provided"
    assert all(row["arrival_utc"] == "unknown" for row in rows)
    assert rows[0]["native_arrDay"] == "24" and rows[0]["native_maxWaveArrDay"] == "25"
    assert [json.loads(row["raw_record_json"]) for row in rows] == [first, second]
    assert all(row["source_family"] == "NCEI_secondary_reported" for row in rows)
    assert all(row["model_eligible"] == row["physical_onset_validated"] == "False" for row in rows)
    assert not any("estimated" in key for key in rows[0])


@pytest.mark.parametrize(
    "hours,minutes,state",
    [
        (0, 0, "nonpositive_duration"),
        (1, 0, "complete_positive"),
        (-1, 3, "invalid_components"),
        (1, 60, "invalid_components"),
        (True, 2, "invalid_components"),
        ("0", 2, "invalid_components"),
    ],
)
def test_invalid_and_zero_travel_components_are_not_filled(
    tmp_path: Path, hours: Any, minutes: Any, state: str
) -> None:
    row = record(1)
    row.update(travHours=hours, travMins=minutes)
    fixture(tmp_path, [[row]])
    run(tmp_path)
    result = read(tmp_path)[0]
    assert result["travel_state"] == state
    assert (result["duration_candidate"] == "True") == (state == "complete_positive")


def test_missing_pages_retain_rows_but_withhold_candidates(tmp_path: Path) -> None:
    fixture(tmp_path, [[record(1), record(2)]], total_pages=2, total_items=3)
    summary = run(tmp_path)
    assert summary["source_records"] == 2 and summary["collection_complete"] is False
    assert summary["reported_duration_candidates"] == 0
    assert all("incomplete_collection" in row["candidate_reason_codes"] for row in read(tmp_path))


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_ids_retain_every_occurrence_and_withhold_conflicts(
    tmp_path: Path, conflict: bool
) -> None:
    duplicate = record(1)
    if conflict:
        duplicate["travMins"] = 31
    fixture(tmp_path, [[record(1), duplicate]])
    summary = run(tmp_path)
    assert summary["source_records"] == 2 and summary["unique_runup_ids"] == 1
    assert summary["collection_complete"] is False
    assert {row["duplicate_id_state"] for row in read(tmp_path)} == {
        "duplicate_conflicting" if conflict else "duplicate_identical"
    }
    assert summary["reported_duration_candidates"] == 0


@pytest.mark.parametrize(
    "flag,value,reason",
    [
        ("doubtful", "y", "doubtfulness_not_clear"),
        ("publish", False, "publication_not_true"),
        ("typeMeasurementId", 1, "measurement_not_requested_gauge"),
        ("latitude", 91, "invalid_coordinates"),
    ],
)
def test_quality_measurement_and_coordinate_flags_are_preserved_and_withheld(
    tmp_path: Path, flag: str, value: Any, reason: str
) -> None:
    item = record(1)
    item[flag] = value
    fixture(tmp_path, [[item]])
    summary = run(tmp_path)
    assert summary["reported_duration_candidates"] == 0
    row = read(tmp_path)[0]
    assert reason in json.loads(row["candidate_reason_codes"])
    assert json.loads(row["raw_record_json"])[flag] == value


@pytest.mark.parametrize(
    "violation",
    ["source_hash", "metadata_hash", "reserved_match", "wrong_event", "bad_page", "bad_semantics"],
)
def test_contract_or_event_drift_never_publishes_output(tmp_path: Path, violation: str) -> None:
    fixture(tmp_path)
    if violation == "source_hash":
        (tmp_path / "raw/page-1.json").write_text("changed")
    elif violation == "metadata_hash":
        (tmp_path / "raw/metadata.json").write_text("changed")
    elif violation == "reserved_match":
        path = tmp_path / "matches.csv"
        path.write_text(path.read_text().replace("event,2373", "reserved,2373"))
    elif violation == "bad_semantics":
        (tmp_path / "semantics.js").write_text("changed")
    else:
        path = tmp_path / "raw/page-1.json"
        payload = json.loads(path.read_text())
        if violation == "wrong_event":
            payload["items"][0]["tsunamiEventId"] = 2406
        else:
            payload["page"] = 2
        digest = write_json(path, payload)
        receipts = json.loads((tmp_path / "outputs.json").read_text())
        receipts[0].update(sha256=digest, bytes=path.stat().st_size)
        write_json(tmp_path / "outputs.json", receipts)
    with pytest.raises((ValueError, KeyError)):
        run(tmp_path)
    assert not (tmp_path / "out").exists()


def test_complete_pagination_order_and_immutable_replay(tmp_path: Path) -> None:
    fixture(tmp_path, [[record(3), record(1)], [record(2)]])
    summary = run(tmp_path)
    assert summary["collection_complete"] is True
    assert [row["ncei_runup_id"] for row in read(tmp_path)] == ["1", "2", "3"]
    run(tmp_path, "again")
    assert {p.name: p.read_bytes() for p in (tmp_path / "out").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "again").iterdir()
    }
    with pytest.raises(FileExistsError):
        run(tmp_path)


@pytest.mark.parametrize("identifier", [None, True, "1", 0, [1]])
def test_invalid_identifiers_are_retained_but_withheld(tmp_path: Path, identifier: Any) -> None:
    item = record(1)
    item["id"] = identifier
    fixture(tmp_path, [[item]])
    summary = run(tmp_path)
    assert summary["source_records"] == 1
    assert summary["reported_duration_candidates"] == summary["unique_runup_ids"] == 0
    row = read(tmp_path)[0]
    assert row["duplicate_id_state"] == "invalid_id"
    assert json.loads(row["raw_record_json"])["id"] == identifier


def test_empty_page_has_stable_schema_and_no_candidates(tmp_path: Path) -> None:
    fixture(tmp_path, [[]])
    summary = run(tmp_path)
    assert summary["collection_complete"] is True
    assert summary["source_records"] == summary["reported_duration_candidates"] == 0
    with gzip.open(tmp_path / "out/observations.csv.gz", "rt") as handle:
        header = next(csv.reader(handle))
    assert "native_travHours" in header and "model_eligible" in header


@pytest.mark.parametrize(
    "wrapper",
    [
        {"error": "Source service failed", "status": 500},
        {"errors": ["Source service failed"]},
        {"status": 500},
        {"status": "503"},
        {"status": "ERROR"},
        {"statusCode": 404},
        {"status_code": 429},
    ],
)
def test_error_wrapper_cannot_become_a_complete_empty_collection(
    tmp_path: Path, wrapper: dict[str, Any]
) -> None:
    fixture(tmp_path, [[]])
    path = tmp_path / "raw/page-1.json"
    payload = json.loads(path.read_text())
    payload.update(wrapper)
    digest = write_json(path, payload)
    receipts = json.loads((tmp_path / "outputs.json").read_text())
    receipts[0].update(sha256=digest, bytes=path.stat().st_size)
    write_json(tmp_path / "outputs.json", receipts)
    with pytest.raises(ValueError, match="error response"):
        run(tmp_path)
    assert not (tmp_path / "out").exists()


def test_native_null_and_invalid_arrival_remain_unresolved(tmp_path: Path) -> None:
    item = record(1)
    item.update(travHours=None, arrDay=0)
    fixture(tmp_path, [[item]])
    run(tmp_path)
    row = read(tmp_path)[0]
    assert row["native_travHours"] == "null"
    assert row["travel_state"] == "partial_components"
    assert row["arrival_component_state"] == "invalid_components"
    assert row["arrival_utc"] == "unknown"


def test_direct_cli_without_pythonpath(tmp_path: Path) -> None:
    fixture(tmp_path)
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/build_ncei_observations.py"),
    ]
    for name, file in (
        ("config", "sources.toml"),
        ("receipts", "outputs.json"),
        ("event-matches", "matches.csv"),
        ("events", "events.toml"),
        ("selection", "selection.json"),
        ("schema", "schema.json"),
        ("semantics-proof", "proof.json"),
        ("semantics-source", "semantics.js"),
        ("output", "out"),
    ):
        command.extend(["--" + name, str(tmp_path / file)])
    command.extend(["--root", str(tmp_path)])
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_records"] == 1


def test_standard_cached_receipt_preserves_unknown_final_url_and_supports_repeated_runs(
    tmp_path: Path,
) -> None:
    fixture(tmp_path)
    receipts = json.loads((tmp_path / "outputs.json").read_text())
    receipts[0].update(status="cached", final_url="not-recorded")
    write_json(tmp_path / "outputs.json", receipts)
    summary = build_ncei_observations(
        [tmp_path / "sources.toml", tmp_path / "sources.toml"],
        [tmp_path / "outputs.json", tmp_path / "outputs.json"],
        tmp_path / "matches.csv",
        tmp_path / "events.toml",
        tmp_path / "selection.json",
        tmp_path / "schema.json",
        tmp_path / "proof.json",
        tmp_path / "semantics.js",
        tmp_path,
        tmp_path / "out",
    )
    assert summary["source_records"] == 1 and summary["collection_complete"] is True
    with gzip.open(tmp_path / "out/source_pages.csv.gz", "rt") as handle:
        page = next(csv.DictReader(handle))
    assert json.loads(page["acquisition_dispositions"])[0]["final_url"] == "not-recorded"
