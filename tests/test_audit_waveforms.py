"""Audit samples retain source uncertainty and never become arrival labels."""

from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.normalize_audit_waveforms import build


def fixture(tmp_path: Path, kind: str = "coops") -> tuple[Path, Path, Path, Path]:
    events = tmp_path / "events.toml"
    events.write_text(
        '[events.a]\nevent_id="a"\nrole="development"\nusgs_time="2011-03-11T05:46:24Z"\n'
    )
    name = "exam_A_2011.070" if kind == "ntwc" else "data.json"
    raw = tmp_path / "raw" / "a" / name
    raw.parent.mkdir(parents=True)
    if kind == "ntwc":
        payload = (
            b"Example,_USA none UHSLC Continuous 10.0 20.0 20110311\r\n"
            b"NGWLMS m UTC 1 min MLLW NTWC Unfiltered\r\n"
            b"1_minute_data_via_GOES\r\n"
            b"Data Format: SampleTime(epochal 1/1/1970) WaterLevel SampleTime(yyymmddhhmmss)\r\n"
            b"1299801600 2.239000 20110311000000\r\n"
            b"1299801600 2.240000 20110311000000\r\n"
            b"1299801659 -0.2000 201103110000\r\n"
            b"1299801720 NaN 20110311000200\r\n"
            b"1299801780 0 20110311000400\r\n"
            b"malformed line\r\n"
        )
    else:
        payload = json.dumps(
            {
                "metadata": {"id": "1234567"},
                "data": [
                    {"t": "2011-03-10 00:00", "v": "0.000"},
                    {"t": "2011-03-10 00:01", "v": "", "q": "p", "f": "0,1"},
                    {"t": "2011-03-10 00:03", "v": "NaN"},
                    {"t": "bad-time", "v": "none"},
                    {"t": "2011-03-14 00:00", "v": "text"},
                ],
            }
        ).encode()
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    contract = dict(
        source_id="source-a",
        source_class="coastal water-level observation",
        availability="approved",
        reason="fixture",
        publisher="fixture",
        url=(
            "https://web.archive.org/web/20161222045941id_/http://www.tsunami.gov/previous.events/test/Data/"
            + name
        )
        if kind == "ntwc"
        else "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=1234567&product=one_minute_water_level&begin_date=20110310&end_date=20110313&time_zone=gmt&units=metric&datum=STND",
        local_path=raw.relative_to(tmp_path).as_posix(),
        format="NTWC event archive ASCII" if kind == "ntwc" else "CO-OPS Data API JSON",
        expected_content_signature="fixture",
        expected_prefix="Example,_USA" if kind == "ntwc" else "{",
        units="m",
        crs="unknown",
        horizontal_datum="unknown",
        vertical_datum="unknown",
        coordinate_order="unknown",
        temporal_semantics="UTC",
        station_metadata="fixture",
    )
    config = tmp_path / "source.toml"
    config.write_text(
        "[assets.a]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in contract.items())
    )
    receipts = tmp_path / "receipts.json"
    receipts.write_text(
        json.dumps(
            [
                dict(
                    source_id="source-a",
                    status="downloaded",
                    reason="not applicable",
                    local_path=contract["local_path"],
                    sha256=digest,
                    bytes=len(payload),
                )
            ]
        )
    )
    return config, receipts, events, raw


def read_rows(output: Path) -> list[dict[str, str]]:
    with gzip.open(output / "a/source-a.csv.gz", "rt", newline="") as f:
        return list(csv.DictReader(f))


def run(tmp_path: Path, kind: str = "coops") -> tuple[dict[str, Any], list[dict[str, str]], Path]:
    config, receipts, events, raw = fixture(tmp_path, kind)
    output = tmp_path / "out"
    summary = build([config], [receipts], events, tmp_path, output)
    return summary, read_rows(output), raw


def test_coops_values_missingness_qc_and_invalid_timestamps_survive(tmp_path: Path) -> None:
    summary, rows, raw = run(tmp_path)
    assert summary["source_rows"] == len(rows) == 5
    assert [r["value_state"] for r in rows] == [
        "finite_numeric",
        "blank",
        "nonfinite",
        "source_missing_token",
        "nonnumeric",
    ]
    assert rows[0]["numeric_value"] == "0.0" and rows[0]["raw_value"] == "0.000"
    assert rows[0]["qc_state"] == "not_provided"
    assert json.loads(rows[1]["qc_json"]) == {"q": "p", "f": "0,1"}
    assert rows[-2]["timestamp_state"] == "invalid_timestamp"
    assert rows[-1]["timestamp_state"] == "outside_requested_grid"
    assert [json.loads(r["raw_row_json"]) for r in rows] == json.loads(raw.read_bytes())["data"]
    assert all(
        r["physical_site_id"] == r["deployment_id"] == r["sensor"] == "unknown" for r in rows
    )
    entry = summary["sources"][0]
    assert entry["missing_grid_timestamps"] == 5760 - 3
    assert entry["gaps_over_declared_cadence"] == 1
    assert entry["observed_delta_seconds"] == {"60.0": 1, "120.0": 1}


def test_ntwc_duplicate_epochs_minute_precision_and_malformed_rows_are_retained(
    tmp_path: Path,
) -> None:
    summary, rows, _ = run(tmp_path, "ntwc")
    assert len(rows) == summary["source_rows"] == 6
    assert rows[0]["observation_id"] == rows[1]["observation_id"]
    assert rows[0]["source_row_id"] != rows[1]["source_row_id"]
    assert rows[0]["duplicate_timestamp"] == rows[1]["duplicate_timestamp"] == "True"
    assert rows[2]["timestamp_utc"] == "2011-03-11T00:00:59Z"
    assert rows[2]["timestamp_state"] == "epoch_calendar_minute_agree"
    assert rows[2]["raw_value"] == "-0.2000" and rows[2]["numeric_value"] == "-0.2"
    assert rows[4]["timestamp_state"] == "epoch_calendar_mismatch"
    assert rows[5]["timestamp_state"] == "malformed_row"
    assert json.loads(rows[5]["raw_row_json"])["line"] == "malformed line"
    assert all(r["provider_station_id"] == "unknown" for r in rows)
    assert summary["sources"][0]["duplicate_timestamp_rows"] == 2
    assert summary["sources"][0]["duplicate_timestamp_excess"] == 1
    assert summary["sources"][0]["missing_grid_timestamps"] == "unknown"


@pytest.mark.parametrize("event_id", [".", "..", "../escape", "/escape"])
def test_unsafe_event_directory_is_rejected_before_any_output(
    tmp_path: Path, event_id: str
) -> None:
    config, receipts, events, _ = fixture(tmp_path)
    events.write_text(
        events.read_text().replace('event_id="a"', f"event_id={json.dumps(event_id)}")
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"source-a": event_id}))
    with pytest.raises(ValueError, match="event ID"):
        build([config], [receipts], events, tmp_path, tmp_path / "out", source_map=mapping)
    assert not list(tmp_path.rglob("*.gz"))
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("violation", ["duplicate", "role"])
def test_event_ids_and_roles_cannot_silently_override_reservation(
    tmp_path: Path, violation: str
) -> None:
    config, receipts, events, _ = fixture(tmp_path)
    if violation == "duplicate":
        original = events.read_text()
        events.write_text(
            original.replace('role="development"', 'role="sealed_evaluation"')
            + original.replace("[events.a]", "[events.alias]")
        )
    else:
        events.write_text(events.read_text().replace('role="development"', 'role="unassigned"'))
    with pytest.raises(ValueError, match="event ID|event role"):
        build([config], [receipts], events, tmp_path, tmp_path / "out")
    assert not list(tmp_path.rglob("*.gz"))


def test_internally_agreeing_ntwc_time_outside_header_day_is_flagged(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    payload = raw.read_bytes().replace(
        b"1299801600 2.239000 20110311000000", b"1331424000 2.239000 20120311000000"
    )
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    result = json.loads(receipts.read_text())
    result[0].update(sha256=digest, bytes=len(payload))
    receipts.write_text(json.dumps(result))
    out = tmp_path / "out"
    summary = build([config], [receipts], events, tmp_path, out)
    row = read_rows(out)[0]
    assert row["timestamp_state"] == "outside_header_day"
    assert row["timestamp_utc"] == "unknown" and row["raw_timestamp"] == "20120311000000"
    assert row["raw_epoch"] == "1331424000"
    assert summary["source_rows"] == 6


@pytest.mark.parametrize(
    ("epoch", "calendar", "state", "stamp"),
    [
        ("1299888000", "20110312000000", "header_day_end_boundary", "2011-03-12T00:00:00Z"),
        ("1299888001", "20110312000001", "outside_header_day", "unknown"),
    ],
)
def test_daily_file_retains_exact_right_boundary_but_no_later_sample(
    tmp_path: Path, epoch: str, calendar: str, state: str, stamp: str
) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    payload = raw.read_bytes().replace(
        b"1299801600 2.239000 20110311000000", f"{epoch} 2.239000 {calendar}".encode()
    )
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    result = json.loads(receipts.read_text())
    result[0].update(sha256=digest, bytes=len(payload))
    receipts.write_text(json.dumps(result))
    out = tmp_path / "out"
    build([config], [receipts], events, tmp_path, out)
    row = read_rows(out)[0]
    assert row["timestamp_state"] == state and row["timestamp_utc"] == stamp


@pytest.mark.parametrize(
    "failure", ["checksum", "size", "receipt_path", "receipt_id", "role", "window", "station"]
)
def test_bad_identity_or_fingerprint_fails_before_publication(tmp_path: Path, failure: str) -> None:
    config, receipts, events, raw = fixture(tmp_path)
    if failure in {"checksum", "size", "receipt_path", "receipt_id"}:
        result = json.loads(receipts.read_text())
        key, value = {
            "checksum": ("sha256", "0" * 64),
            "size": ("bytes", 1),
            "receipt_path": ("local_path", "wrong"),
            "receipt_id": ("source_id", "other"),
        }[failure]
        result[0][key] = value
        receipts.write_text(json.dumps(result))
    elif failure == "role":
        events.write_text(
            events.read_text().replace('role="development"', 'role="sealed_evaluation"')
        )
        raw.unlink()  # Role must reject before any raw read.
    elif failure == "window":
        config.write_text(config.read_text().replace("begin_date=20110310", "begin_date=20110311"))
    else:
        config.write_text(config.read_text().replace("station=1234567", "station=7654321"))
    with pytest.raises(ValueError):
        build([config], [receipts], events, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unavailable_request_is_kept_without_observation_rows(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path)
    result = json.loads(receipts.read_text())
    result[0].update(status="quarantined", reason="HTTP 403")
    receipts.write_text(json.dumps(result))
    raw.unlink()
    output = tmp_path / "out"
    summary = build([config], [receipts], events, tmp_path, output)
    assert summary["source_rows"] == 0
    assert summary["sources"][0]["processing_status"] == "unavailable"
    assert summary["sources"][0]["reason"] == "HTTP 403"
    assert not list(output.rglob("*.gz"))


def test_raw_error_response_is_never_an_observation(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path)
    payload = b'{"error":{"message":"No data was found."}}'
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    result = json.loads(receipts.read_text())
    result[0].update(sha256=digest, bytes=len(payload))
    receipts.write_text(json.dumps(result))
    summary = build([config], [receipts], events, tmp_path, tmp_path / "out")
    assert summary["sources"][0]["processing_status"] == "unavailable_provider_response"
    assert summary["sources"][0]["provider_error"] == json.loads(payload)
    assert summary["source_rows"] == 0 and summary["series_coverage"] == []
    config.write_text(
        config.read_text().replace(
            "coastal water-level observation", "provider availability response"
        )
    )
    summary = build([config], [receipts], events, tmp_path, tmp_path / "diagnostic")
    assert summary["sources"][0]["processing_status"] == "unavailable_diagnostic"
    assert summary["sources"][0]["provider_error"] == json.loads(payload)
    assert summary["source_rows"] == 0


def test_replay_is_byte_identical_and_existing_output_is_not_replaced(tmp_path: Path) -> None:
    config, receipts, events, _ = fixture(tmp_path)
    first, second = tmp_path / "one", tmp_path / "two"
    for out in [first, second]:
        build([config], [receipts], events, tmp_path, out)
    for p in first.rglob("*"):
        if p.is_file():
            assert p.read_bytes() == (second / p.relative_to(first)).read_bytes()
    with pytest.raises(FileExistsError):
        build([config], [receipts], events, tmp_path, first)


def replace_raw(raw: Path, receipts: Path, payload: bytes) -> None:
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    receipt = json.loads(receipts.read_text())
    receipt[0].update(sha256=digest, bytes=len(payload))
    receipts.write_text(json.dumps(receipt))


def selection_for(events: Path) -> Path:
    ledger: dict[str, Any] = {"events": list(tomllib.loads(events.read_text())["events"].values())}
    digest = hashlib.sha256(
        json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger["selection_sha256"] = digest
    events.write_text(f'selection_sha256="{digest}"\n' + events.read_text())
    path = events.with_suffix(".json")
    path.write_text(json.dumps(ledger))
    return path


@pytest.mark.parametrize("valid_header", [True, False])
def test_header_evidence_never_parses_body_or_claims_waveform_coverage(
    tmp_path: Path, valid_header: bool
) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    selection = selection_for(events)
    header = b"\n".join(raw.read_bytes().splitlines()[:4])
    if not valid_header:
        header = header.replace(b"Data Format:", b"Unknown Format:")
    payload = header + b"\n\xffuninterpreted body\n1299801600 2.239 20110311000000\n"
    replace_raw(raw, receipts, payload)
    out = tmp_path / "out"
    summary = build(
        [config],
        [receipts],
        events,
        tmp_path,
        out,
        selection=selection,
        header_evidence_configs=[config],
    )
    (entry,) = summary["sources"]
    assert entry["purpose"] == "header_evidence"
    assert entry["source_scope"] == "historical_header_identity_only"
    assert entry["source_line_count"] == 6 and entry["source_bytes"] == len(payload)
    assert entry["source_rows"] == summary["source_rows"] == 0
    assert summary["series_coverage"] == [] and not list(out.rglob("*.gz"))
    assert "window_start_utc" not in entry and "window_stop_utc" not in entry
    assert raw.read_bytes() == payload
    if valid_header:
        assert entry["processing_status"] == "verified_header_evidence"
        assert entry["source_metadata"]["provider"] == "UHSLC"
    else:
        assert entry["processing_status"] == "retained_unparsed_header_evidence"
        assert "source_metadata" not in entry and entry["parse_reason"]


@pytest.mark.parametrize("failure", ["no_selection", "absent_config", "non_ntwc", "window"])
def test_header_evidence_scope_requires_explicit_consistent_inputs(
    tmp_path: Path, failure: str
) -> None:
    config, receipts, events, _ = fixture(tmp_path, "coops" if failure == "non_ntwc" else "ntwc")
    selection = selection_for(events)
    if failure == "window":
        config.write_text(config.read_text() + '\n[source_windows.source-a]\nevent_id="a"\n')
    with pytest.raises(ValueError, match="header evidence"):
        build(
            [config],
            [receipts],
            events,
            tmp_path,
            tmp_path / "out",
            selection=None if failure == "no_selection" else selection,
            header_evidence_configs=[
                tmp_path / "absent.toml" if failure == "absent_config" else config
            ],
        )
    assert not (tmp_path / "out").exists()


def test_legacy_two_column_source_retained_without_guessing_units_or_clock(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    payload = b" 268.958344  1.668000\r\n 268.962555  1.640000\r\n"
    replace_raw(raw, receipts, payload)
    config.write_text(
        config.read_text().replace('expected_prefix="Example,_USA"', 'expected_prefix="268.958344"')
    )
    out = tmp_path / "out"
    summary = build([config], [receipts], events, tmp_path, out, retain_unparsed=True)
    entry = summary["sources"][0]
    assert entry["processing_status"] == "retained_unparsed_source"
    assert entry["source_line_count"] == 2 and entry["source_bytes"] == len(payload)
    assert entry["raw_path"] == raw.relative_to(tmp_path).as_posix()
    assert summary["source_rows"] == 0 and summary["series_coverage"] == []
    assert raw.read_bytes() == payload and not list(out.rglob("*.gz"))


@pytest.mark.parametrize("failure", ["none", "reserved_overlap", "wrong_window", "no_selection"])
def test_declared_windows_require_selection_and_preserve_reserved_guards(
    tmp_path: Path, failure: str
) -> None:
    config, receipts, events, _ = fixture(tmp_path)
    if failure == "reserved_overlap":
        events.write_text(
            events.read_text() + '\n[events.b]\nevent_id="b"\nrole="sealed_evaluation"\n'
            'usgs_time="2011-03-12T00:00:00Z"\n'
        )
    selection = selection_for(events)
    start = "2011-03-11" if failure == "wrong_window" else "2011-03-10"
    config.write_text(
        config.read_text() + '\n[source_windows.source-a]\nevent_id="a"\npurpose="event_window"\n'
        f'start_utc="{start}T00:00:00Z"\nstop_utc="2011-03-14T00:00:00Z"\n'
    )
    kwargs: dict[str, Any] = {} if failure == "no_selection" else {"selection": selection}
    if failure != "none":
        with pytest.raises(ValueError):
            build([config], [receipts], events, tmp_path, tmp_path / "out", **kwargs)
        assert not (tmp_path / "out").exists()
    else:
        summary = build([config], [receipts], events, tmp_path, tmp_path / "out", **kwargs)
        assert summary["sources"][0]["purpose"] == "event_window"


@pytest.mark.parametrize(
    "mode,eligible",
    [("complete", True), ("sparse", False), ("duplicates", False), ("fragmented", False)],
)
def test_display_coverage_requires_density_contiguity_and_unique_valid_samples(
    tmp_path: Path, mode: str, eligible: bool
) -> None:
    config, receipts, events, raw = fixture(tmp_path)
    start = datetime(2011, 3, 10, 23, 47, tzinfo=UTC)
    rows = [
        {"t": (start + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"), "v": "1.2"}
        for i in range(2160)
    ]
    if mode == "sparse":
        rows = rows[:1700]
    elif mode == "duplicates":
        rows += rows
    elif mode == "fragmented":
        rows = [r for i, r in enumerate(rows) if i % 30 != 0]
    replace_raw(raw, receipts, json.dumps({"metadata": {"id": "1234567"}, "data": rows}).encode())
    summary = build([config], [receipts], events, tmp_path, tmp_path / "out")
    (quality,) = summary["series_coverage"]
    assert quality["display_eligible"] is eligible
    assert quality["expected_bins"] == 2160
    assert quality["display_station_key"] == "coops:1234567"
    assert quality["window_start_utc"] == "2011-03-10T23:46:24+00:00"
    assert quality["window_stop_utc"] == "2011-03-12T11:46:24+00:00"
    if mode == "duplicates":
        assert quality["usable_bins"] == 0 and quality["duplicate_timestamp_rows"] == 4320


def test_quiet_controls_are_accounted_but_never_display_coverage(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path)
    selection = selection_for(events)
    config.write_text(
        config.read_text().replace("20110310", "20110224").replace("20110313", "20110227")
        + '\n[source_windows.source-a]\nevent_id="a"\npurpose="quiet_control"\n'
        'offset_days="-14"\nstart_utc="2011-02-24T00:00:00Z"\n'
        'stop_utc="2011-02-28T00:00:00Z"\n'
    )
    replace_raw(
        raw,
        receipts,
        json.dumps(
            {"metadata": {"id": "1234567"}, "data": [{"t": "2011-02-24 00:00", "v": "1"}]}
        ).encode(),
    )
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "id,time,type\nfirst,2000-01-01T00:00:00Z,earthquake\nlast,2020-01-01T00:00:00Z,earthquake\n"
    )
    catalog.with_name(catalog.name + ".sha256").write_text(
        hashlib.sha256(catalog.read_bytes()).hexdigest()
    )
    summary = build(
        [config],
        [receipts],
        events,
        tmp_path,
        tmp_path / "out",
        selection=selection,
        known_catalog=catalog,
    )
    assert summary["sources"][0]["purpose"] == "quiet_control"
    assert summary["source_rows"] == 1 and summary["series_coverage"] == []
    assert read_rows(tmp_path / "out")[0]["purpose"] == "quiet_control"


def test_declared_source_window_ids_must_cover_every_contract(tmp_path: Path) -> None:
    config, receipts, events, _ = fixture(tmp_path)
    selection = selection_for(events)
    config.write_text(config.read_text() + '\n[source_windows.wrong]\nevent_id="a"\n')
    with pytest.raises(ValueError, match="window/contract IDs"):
        build([config], [receipts], events, tmp_path, tmp_path / "out", selection=selection)


def test_ntwc_explicit_seconds_cadence_and_centimeters_are_preserved(tmp_path: Path) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    replace_raw(
        raw, receipts, raw.read_bytes().replace(b"NGWLMS m UTC 1 min", b"Radar cm UTC 15 sec")
    )
    summary = build([config], [receipts], events, tmp_path, tmp_path / "out")
    assert summary["sources"][0]["declared_cadence_seconds"] == 15
    assert summary["sources"][0]["units"] == "cm"
    assert read_rows(tmp_path / "out")[0]["numeric_value"] == "2.239"


@pytest.mark.parametrize("receipt_proves_digest", [True, False])
def test_pinned_cdx_normalization_rechecks_body_and_acquisition_receipt(
    tmp_path: Path, receipt_proves_digest: bool
) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    digest = base64.b32encode(
        hashlib.sha1(raw.read_bytes(), usedforsecurity=False).digest()
    ).decode()
    url = tomllib.loads(config.read_text())["assets"]["a"]["url"]
    cdx = tmp_path / "cdx.json"
    cdx.write_text(
        json.dumps(
            [
                ["timestamp", "original", "digest"],
                ["20161222045941", url.split("id_/", 1)[1], digest],
            ]
        )
    )
    evidence_sha = hashlib.sha256(cdx.read_bytes()).hexdigest()
    cdx.with_name("cdx.json.sha256").write_text(evidence_sha)
    config.write_text(
        config.read_text()
        + f'\nexpected_cdx_sha1="{digest}"\ncdx_evidence_path="cdx.json"\n'
        + f'cdx_evidence_sha256="{evidence_sha}"\n'
    )
    outcome = json.loads(receipts.read_text())
    if receipt_proves_digest:
        outcome[0]["verified_cdx_sha1"] = digest
    receipts.write_text(json.dumps(outcome))
    if receipt_proves_digest:
        assert build([config], [receipts], events, tmp_path, tmp_path / "out")["source_rows"] == 6
    else:
        with pytest.raises(ValueError, match="CDX"):
            build([config], [receipts], events, tmp_path, tmp_path / "out")


def test_same_archive_code_with_different_provider_ids_never_merges_coverage(
    tmp_path: Path,
) -> None:
    config, receipts, events, raw = fixture(tmp_path, "ntwc")
    replace_raw(raw, receipts, raw.read_bytes().replace(b"none UHSLC", b"1234567 NOS"))
    config_b, receipts_b = tmp_path / "source-b.toml", tmp_path / "receipts-b.json"
    raw_b = raw.with_name("exam_A_2011.071")
    config_b.write_text(
        config.read_text().replace("source-a", "source-b").replace("2011.070", "2011.071")
    )
    outcome = json.loads(receipts.read_text())[0]
    outcome.update(source_id="source-b", local_path=raw_b.relative_to(tmp_path).as_posix())
    receipts_b.write_text(json.dumps([outcome]))
    payload = (
        raw.read_bytes().replace(b"1234567 NOS", b"7654321 NOS").replace(b"20110311", b"20110312")
    )
    replace_raw(raw_b, receipts_b, payload)
    summary = build([config, config_b], [receipts, receipts_b], events, tmp_path, tmp_path / "out")
    assert len(summary["series_coverage"]) == 2
    assert {q["display_station_key"] for q in summary["series_coverage"]} == {
        "coops:1234567",
        "coops:7654321",
    }
    assert all(len(q["source_ids"]) == 1 for q in summary["series_coverage"])
