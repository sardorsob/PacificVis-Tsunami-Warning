"""Station identity requires source evidence beyond matching familiar place names."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
from pathlib import Path

import pytest

from analysis.arrival.stations import (
    StationError,
    build_crosswalk,
    geographic_site_id,
    parse_ntwc_header,
    validate_reviewed_site_evidence,
)

URL = "https://www.tsunami.gov/previous.events/event/Data/exam_A_2011.070"
HEADER = (
    "Example,_USA none UHSLC Continuous 10.0 20.0 20110311\n"
    "NGWLMS m UTC 1 min MLLW NTWC Unfiltered\n"
    "1_minute_data_via_GOES\n"
    "Data Format: SampleTime(epochal 1/1/1970) WaterLevel SampleTime(yyyymmddhhmmss)\n"
)


def inputs(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "events.toml"
    config.write_text(
        """
[events.a]
event_id="a"
role="development"
archive_source_id="source-a"
usgs_time="2011-03-11T05:46:24Z"
[events.b]
event_id="b"
role="sealed_evaluation"
archive_source_id="source-b"
usgs_time="2012-10-28T03:04:00Z"
""",
        encoding="utf-8",
    )
    census = tmp_path / "census"
    census.mkdir()
    identity = {
        "event_id": "a",
        "role": "development",
        "source_id": "source-a",
        "table_index": 0,
        "row_index": 1,
    }
    row = {
        **identity,
        "status": "accepted_source_row",
        "fields": {
            "location": "Example, USA",
            "estimated_arrival": "0100",
            "observed_arrival": "?",
        },
    }
    link = {
        **identity,
        "status": "safe_archive_link",
        "link_code": "exam",
        "link_sensor": "A",
        "resolved_url": URL,
    }
    for name, values in (("rows", [row]), ("links", [link])):
        (census / f"{name}.json").write_text(json.dumps(values), encoding="utf-8")
    return config, census


def source(tmp_path: Path, *, registry: bool = False) -> tuple[Path, Path]:
    name = "registry" if registry else "header"
    raw = tmp_path / ("registry.json" if registry else "exam_A_2011.070")
    payload = (
        json.dumps(
            {"stations": [{"id": "1234567", "name": "Example", "lat": 10.1, "lng": 20.1}]}
        ).encode()
        if registry
        else HEADER.encode()
    )
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(
        hashlib.sha256(payload).hexdigest(), encoding="utf-8"
    )
    values = {
        "source_id": name,
        "source_class": "current station registry" if registry else "header",
        "availability": "approved",
        "reason": "test fixture",
        "url": (
            "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/1234567.json"
            if registry
            else "https://web.archive.org/web/20161222045941id_/" + URL.replace("https:", "http:")
        ),
        "local_path": raw.name,
        "format": "JSON" if registry else "NTWC event archive ASCII",
        "publisher": "fixture",
        "expected_content_signature": "fixture",
        "expected_prefix": "{" if registry else "Example,_USA",
        "units": "unknown",
        "crs": "unknown",
        "horizontal_datum": "unknown",
        "vertical_datum": "unknown",
        "coordinate_order": "unknown",
        "temporal_semantics": "unknown",
        "station_metadata": "unknown",
    }
    config = tmp_path / f"{name}.toml"
    config.write_text(
        "[assets.example]\n"
        + "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items()),
        encoding="utf-8",
    )
    return config, raw


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def catalog_source(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    config, raw = source(tmp_path, registry=True)
    payload = json.dumps(records).encode()
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest())
    config.write_text(
        config.read_text()
        .replace("current station registry", "station identifier catalog")
        .replace(
            "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/1234567.json",
            "https://www.ioc-sealevelmonitoring.org/ssc/service.php?format=json",
        )
        .replace('expected_prefix="{"', 'expected_prefix="["')
    )
    return config


def coops_source(tmp_path: Path) -> tuple[Path, Path, Path]:
    registry, _ = source(tmp_path, registry=True)
    path = tmp_path / "a" / "observations.json"
    path.parent.mkdir()
    payload = json.dumps({"metadata": {"id": "1234567"}, "data": []}).encode()
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_name(path.name + ".sha256").write_text(digest)
    config = tmp_path / "coops.toml"
    config.write_text(
        registry.read_text()
        .replace("current station registry", "coastal water-level observation")
        .replace('source_id="registry"', 'source_id="observation"')
        .replace('local_path="registry.json"', 'local_path="a/observations.json"')
        .replace(
            "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/1234567.json",
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=1234567"
            "&begin_date=20110310&end_date=20110313&time_zone=gmt&product=water_level",
        )
    )
    receipts = tmp_path / "receipts.json"
    receipts.write_text(
        json.dumps(
            [
                {
                    "source_id": "observation",
                    "status": "downloaded",
                    "local_path": "a/observations.json",
                    "sha256": digest,
                    "bytes": len(payload),
                }
            ]
        )
    )
    return registry, config, receipts


def test_archive_code_is_not_a_physical_station_or_a_fit_eligible_pair(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    out = tmp_path / "result"
    result = build_crosswalk(config, census, tmp_path, out)
    row = read_csv(out / "event_site.csv")[0]
    assert row["identity_tier"] == "archive_code"
    assert row["physical_site_id"] == row["deployment_id"] == "unknown"
    assert row["latitude"] == row["longitude"] == "unknown"
    assert row["fit_eligible"] == "False"
    assert row["era_key"] == "2011"
    assert result["source_rows"] == result["distinct_source_reports"] == 1
    pull = read_csv(out / "pull_list.csv")[0]
    assert pull["request_kind"] == "ia_header_discovery"
    assert pull["waveform_pull_allowed"] == pull["direct_ntwc_fetch"] == "False"


def test_current_registry_name_match_never_promotes_historical_coordinates(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    registry, _ = source(tmp_path, registry=True)
    out = tmp_path / "result"
    build_crosswalk(config, census, tmp_path, out, registry_configs=[registry])
    row = read_csv(out / "event_site.csv")[0]
    assert row["identity_tier"] == "archive_code"
    assert row["evidence_status"] == "name_candidate_not_historical_match"
    assert json.loads(row["candidate_coops_ids"]) == ["1234567"]
    assert row["latitude"] == "unknown" and row["historical_deployment_verified"] == "False"


def test_current_catalog_cross_identifiers_do_not_promote_ntwc_namespace_or_history(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    registry = catalog_source(
        tmp_path,
        [
            {
                "ssc_id": "SSC-exam",
                "name": "Example",
                "ptwc": "exam",
                "ioc": ["exam", "exa2"],
                "uhslc": "999",
                "geo:lat": 10.1,
                "geo:lon": 20.1,
            }
        ],
    )
    out = tmp_path / "result"
    build_crosswalk(config, census, tmp_path, out, registry_configs=[registry])
    row = read_csv(out / "event_site.csv")[0]
    candidate = json.loads(row["candidate_catalog_matches"])[0]
    assert candidate["matching_namespaces"] == ["ptwc", "ioc"]
    assert candidate["provider_identifiers"]["uhslc"] == ["999"]
    assert candidate["place_label_agrees"] is True
    assert row["identity_tier"] == "archive_code"
    assert row["physical_site_id"] == row["latitude"] == "unknown"
    assert row["fit_eligible"] == "False"
    assert json.loads(row["candidate_coops_ids"]) == []


def test_catalog_name_match_without_identifier_match_is_not_a_code_crosswalk(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    registry = catalog_source(tmp_path, [{"ssc_id": "SSC-else", "name": "Example", "ptwc": "else"}])
    out = tmp_path / "result"
    build_crosswalk(config, census, tmp_path, out, registry_configs=[registry])
    assert json.loads(read_csv(out / "event_site.csv")[0]["candidate_catalog_matches"]) == []


def test_conflicting_catalog_entities_remain_visible_for_review(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    registry = catalog_source(
        tmp_path,
        [
            {"ssc_id": "SSC-exam", "name": "Example", "ptwc": "exam"},
            {"ssc_id": "SSC-other", "name": "Other place", "ptwc": "exam"},
        ],
    )
    out = tmp_path / "result"
    build_crosswalk(config, census, tmp_path, out, registry_configs=[registry])
    row = read_csv(out / "event_site.csv")[0]
    candidates = json.loads(row["candidate_catalog_matches"])
    assert len(candidates) == 2
    assert [candidate["place_label_agrees"] for candidate in candidates] == [True, False]
    assert row["physical_site_id"] == "unknown" and row["fit_eligible"] == "False"


def test_unexpected_catalog_identifier_shape_fails(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    registry = catalog_source(
        tmp_path, [{"ssc_id": "SSC-exam", "name": "Example", "ptwc": {"code": "exam"}}]
    )
    with pytest.raises(StationError, match="identifier shape"):
        build_crosswalk(config, census, tmp_path, tmp_path / "result", registry_configs=[registry])


def test_exact_linked_header_supplies_event_coordinates_but_none_id_stays_unknown(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    out = tmp_path / "result"
    summary = build_crosswalk(config, census, tmp_path, out, header_configs=[header])
    row = read_csv(out / "event_site.csv")[0]
    assert row["identity_tier"] == "header_exact"
    assert row["latitude"] == "10.0" and row["longitude"] == "20.0"
    assert row["coordinate_crs"] == "unknown"
    assert row["physical_site_id"].startswith("ntwc-header-site:")
    assert row["provider_station_id"] == row["deployment_id"] == "unknown"
    assert row["identity_scope"] == "source_qualified_geographic_site"
    assert row["event_site_identity_verified"] == "True"
    assert row["site_identity_fit_tier"] == "False"
    assert read_csv(out / "acquisition_candidates.csv") == []
    assert summary["verified_header_assets"] == 1
    assert summary["header_probe_candidates"] == 0


def test_same_code_different_event_file_does_not_borrow_header_identity(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    path = census / "links.json"
    links = json.loads(path.read_text())
    links[0]["resolved_url"] = URL.replace("/event/", "/different-event/")
    path.write_text(json.dumps(links))
    out = tmp_path / "result"
    summary = build_crosswalk(config, census, tmp_path, out, header_configs=[header])
    assert read_csv(out / "event_site.csv")[0]["identity_tier"] == "archive_code"
    assert summary["verified_header_assets"] == 0
    assert summary["source_evidence"] == []


def test_unresolved_label_alias_keeps_linked_header_evidence_without_promoting_identity(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    path = census / "rows.json"
    rows = json.loads(path.read_text())
    rows[0]["fields"]["location"] = "Example Island, USA"
    path.write_text(json.dumps(rows))
    out = tmp_path / "result"
    build_crosswalk(config, census, tmp_path, out, header_configs=[header])
    row = read_csv(out / "event_site.csv")[0]
    assert row["identity_tier"] == "ambiguous" and row["latitude"] == "unknown"
    assert json.loads(row["header_source_ids"]) == []
    assert json.loads(row["linked_header_source_ids"]) == ["header"]
    evidence = json.loads(row["header_metadata"])[0]
    assert evidence["header_name"] == "Example,_USA" and evidence["latitude"] == 10.0


@pytest.mark.parametrize(
    "text,filename",
    [
        ("<html>error</html>", "exam_A_2011.070"),
        (HEADER.replace("10.0", "nan"), "exam_A_2011.070"),
        (HEADER.replace("20.0", "181.0"), "exam_A_2011.070"),
        (HEADER, "exam_A_2012.070"),
        (HEADER, "exam_A_2011.071"),
    ],
)
def test_invalid_or_mismatched_header_is_rejected(text: str, filename: str) -> None:
    with pytest.raises(StationError):
        parse_ntwc_header(text, filename)


def test_multiple_code_sensors_are_retained_for_review(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    path = census / "links.json"
    links = json.loads(path.read_text())
    links.append({**links[0], "link_sensor": "B", "resolved_url": URL.replace("_A_", "_B_")})
    path.write_text(json.dumps(links))
    out = tmp_path / "result"
    result = build_crosswalk(config, census, tmp_path, out)
    assert result["source_rows"] == result["distinct_source_reports"] == 1
    assert result["event_site_rows"] == 2
    assert {row["identity_tier"] for row in read_csv(out / "event_site.csv")} == {"ambiguous"}


def test_sealed_values_fail_before_output(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    path = census / "rows.json"
    rows = json.loads(path.read_text())
    rows[0].update(event_id="b", source_id="source-b", role="sealed_evaluation")
    path.write_text(json.dumps(rows))
    with pytest.raises(StationError, match="reserved or unknown"):
        build_crosswalk(config, census, tmp_path, tmp_path / "result")
    assert not (tmp_path / "result").exists()


def test_checksum_conflict_fails_before_output(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, raw = source(tmp_path)
    raw.write_text(HEADER + "changed", encoding="utf-8")
    with pytest.raises(StationError, match="checksum mismatch"):
        build_crosswalk(config, census, tmp_path, tmp_path / "result", header_configs=[header])
    assert not (tmp_path / "result").exists()


def test_unrecognized_verified_file_is_quarantined_without_identity_or_retry(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    header, raw = source(tmp_path)
    payload = b"1234 1.2 201103110000\n"
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest())
    header.write_text(
        header.read_text().replace('expected_prefix="Example,_USA"', 'expected_prefix="1234"')
    )
    output = tmp_path / "result"
    summary = build_crosswalk(config, census, tmp_path, output, header_configs=[header])
    assert summary["unrecognized_header_assets"] == 1
    assert summary["verified_header_assets"] == summary["header_probe_candidates"] == 0
    assert summary["header_rejections"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
    row = read_csv(output / "event_site.csv")[0]
    assert row["identity_tier"] == "archive_code" and row["physical_site_id"] == "unknown"
    assert row["evidence_status"] == "unrecognized_header_format"
    assert json.loads(row["evidence"])["unrecognized_header_sources"][0]["source_id"] == "header"


def test_replay_is_identical_and_outputs_are_immutable(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    build_crosswalk(config, census, tmp_path, first)
    build_crosswalk(config, census, tmp_path, second)
    assert all(path.read_bytes() == (second / path.name).read_bytes() for path in first.iterdir())
    with pytest.raises(FileExistsError):
        build_crosswalk(config, census, tmp_path, first)


def test_available_provider_series_cannot_be_added_without_receipt_pair(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    with pytest.raises(StationError, match="supplied together"):
        build_crosswalk(config, census, tmp_path, tmp_path / "result", coops_config=config)


def test_coops_availability_is_only_a_candidate_even_with_valid_receipt(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    registry, coops, receipts = coops_source(tmp_path)
    out = tmp_path / "result"
    summary = build_crosswalk(
        config,
        census,
        tmp_path,
        out,
        registry_configs=[registry],
        coops_config=coops,
        coops_receipts=receipts,
    )
    row = read_csv(out / "event_site.csv")[0]
    assert summary["alternative_coops_event_station_windows"] == 1
    assert json.loads(row["available_alternative_source_ids"]) == ["observation"]
    assert row["identity_tier"] == "archive_code"
    assert row["physical_site_id"] == "unknown" and row["fit_eligible"] == "False"


@pytest.mark.parametrize("failure", ["reserved", "window", "receipt"])
def test_coops_receipts_must_respect_event_role_window_and_fingerprint(
    tmp_path: Path,
    failure: str,
) -> None:
    config, census = inputs(tmp_path)
    _, coops, receipts = coops_source(tmp_path)
    if failure == "reserved":
        coops.write_text(coops.read_text().replace("a/observations", "b/observations"))
    elif failure == "window":
        coops.write_text(coops.read_text().replace("20110310", "20110311"))
    else:
        records = json.loads(receipts.read_text())
        records[0]["sha256"] = "0" * 64
        receipts.write_text(json.dumps(records))
    with pytest.raises(StationError):
        build_crosswalk(
            config,
            census,
            tmp_path,
            tmp_path / "result",
            coops_config=coops,
            coops_receipts=receipts,
        )
    assert not (tmp_path / "result").exists()


def nos_inputs(
    tmp_path: Path,
    *,
    station_id: str = "1612340",
    label: str = "Honolulu, Oahu, HI",
    header_name: str = "Honolulu_Oahu,_HI",
    registry_longitude: float = 20.001,
) -> tuple[Path, Path, Path, Path]:
    config, census = inputs(tmp_path)
    rows_path = census / "rows.json"
    rows = json.loads(rows_path.read_text())
    rows[0]["fields"].update(location=label, observed_arrival="0130")
    rows_path.write_text(json.dumps(rows))
    header, raw = source(tmp_path)
    payload = HEADER.replace("Example,_USA none UHSLC", f"{header_name} {station_id} NOS").encode()
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest())
    header.write_text(
        header.read_text().replace(
            'expected_prefix="Example,_USA"', f'expected_prefix="{header_name}"'
        )
    )
    registry, raw = source(tmp_path, registry=True)
    payload = json.dumps(
        {
            "stations": [
                {
                    "id": station_id,
                    "name": "A current registry label",
                    "lat": 10.001,
                    "lng": registry_longitude,
                },
                {"id": "7654321", "name": label, "lat": 50.0, "lng": 100.0},
            ]
        }
    ).encode()
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest())
    return config, census, header, registry


@pytest.mark.parametrize(
    "station_id,label,header_name",
    [
        ("1612340", "Honolulu, Oahu, HI", "Honolulu_Oahu,_HI"),
        ("1615680", "Kahului, HI", "Kahului_Maui,_HI"),
        ("1619910", "Midway Island", "Sand_Island_(Midway_Is.),_USA"),
        ("1890000", "Wake Island", "Wake_Is.,_USA"),
        ("9419750", "Crescent City, CA", "Crescent_City,_CA"),
    ],
)
def test_documented_nos_id_resolves_alias_despite_current_name_candidates(
    tmp_path: Path,
    station_id: str,
    label: str,
    header_name: str,
) -> None:
    config, census, header, registry = nos_inputs(
        tmp_path, station_id=station_id, label=label, header_name=header_name
    )
    output = tmp_path / "result"
    summary = build_crosswalk(
        config, census, tmp_path, output, header_configs=[header], registry_configs=[registry]
    )
    row = read_csv(output / "unique_report_crosswalk.csv")[0]
    assert row["physical_site_id"] == f"coops:{station_id}"
    assert row["provider_station_id"] == station_id
    assert row["event_site_identity_verified"] == "True"
    assert row["deployment_id"] == "unknown" and row["deployment_continuity_verified"] == "False"
    assert row["site_identity_fit_tier"] == row["model_eligible"] == "False"
    assert row["review_status"] == "pending_independent_review"
    assert summary["verified_event_site_reports"] == 1
    candidate = read_csv(output / "acquisition_candidates.csv")[0]
    assert json.loads(candidate["source_ids"]) == ["header"]
    assert candidate["waveform_pull_allowed"] == "False"


@pytest.mark.parametrize("failure", ["label", "coordinates"])
def test_exact_header_id_does_not_override_bad_archive_link_or_far_registry(
    tmp_path: Path,
    failure: str,
) -> None:
    config, census, header, registry = nos_inputs(
        tmp_path,
        station_id="1890000",
        header_name="Wake_Is.,_USA",
        label="Chichijima, JP" if failure == "label" else "Wake Island",
        registry_longitude=100.0 if failure == "coordinates" else 20.001,
    )
    output = tmp_path / "result"
    build_crosswalk(
        config, census, tmp_path, output, header_configs=[header], registry_configs=[registry]
    )
    row = read_csv(output / "unique_report_crosswalk.csv")[0]
    assert row["identity_tier"] == "ambiguous"
    assert row["event_site_identity_verified"] == "False"
    assert row["physical_site_id"] == "unknown"
    assert read_csv(output / "acquisition_candidates.csv") == []


def review_file(tmp_path: Path, row: dict[str, str]) -> Path:
    path = tmp_path / "review.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "event_id",
                "report_id",
                "identity_evidence_sha256",
                "decision",
                "reviewer",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "event_id": row["event_id"],
                "report_id": row["report_id"],
                "identity_evidence_sha256": row["identity_evidence_sha256"],
                "decision": "approved",
                "reviewer": "independent-test-checker",
            }
        )
    return path


def test_reviewed_unique_adapter_preserves_unknown_deployment_and_source_evidence(
    tmp_path: Path,
) -> None:
    config, census, header, registry = nos_inputs(tmp_path)
    first, final = tmp_path / "first", tmp_path / "final"
    build_crosswalk(
        config, census, tmp_path, first, header_configs=[header], registry_configs=[registry]
    )
    review = review_file(tmp_path, read_csv(first / "unique_report_crosswalk.csv")[0])
    result = build_crosswalk(
        config,
        census,
        tmp_path,
        final,
        header_configs=[header],
        registry_configs=[registry],
        identity_review=review,
    )
    row = read_csv(final / "unique_report_crosswalk.csv")[0]
    assert row["review_status"] == "independently_reviewed"
    assert row["site_identity_fit_tier"] == "True" and row["deployment_id"] == "unknown"
    assert (
        row["fit_eligible"] == row["model_eligible"] == row["physical_onset_validated"] == "False"
    )
    assert result["reviewed_event_site_reports"] == 1
    assert result["event_identity_support"][0]["reviewed_explicit_pair_sites"] == 1
    assert read_csv(final / "acquisition_candidates.csv")[0]["waveform_pull_allowed"] == "True"
    assert result["identity_review_sha256"] == hashlib.sha256(review.read_bytes()).hexdigest()


@pytest.mark.parametrize("failure", ["digest", "duplicate", "reserved", "unresolved"])
def test_review_cannot_promote_stale_ambiguous_or_unknown_evidence(
    tmp_path: Path, failure: str
) -> None:
    config, census, header, registry = nos_inputs(tmp_path)
    header_configs = [] if failure == "unresolved" else [header]
    first = tmp_path / "first"
    build_crosswalk(
        config, census, tmp_path, first, header_configs=header_configs, registry_configs=[registry]
    )
    review = review_file(tmp_path, read_csv(first / "unique_report_crosswalk.csv")[0])
    if failure == "digest":
        review.write_text(
            review.read_text().replace(read_csv(review)[0]["identity_evidence_sha256"], "0" * 64)
        )
    elif failure == "duplicate":
        review.write_text(review.read_text() + review.read_text().splitlines()[-1] + "\n")
    elif failure == "reserved":
        review.write_text(review.read_text().replace("a,a:0:1", "b,b:0:1"))
    with pytest.raises(StationError):
        build_crosswalk(
            config,
            census,
            tmp_path,
            tmp_path / "final",
            header_configs=header_configs,
            registry_configs=[registry],
            identity_review=review,
        )
    assert not (tmp_path / "final").exists()


def test_unique_adapter_does_not_choose_documented_site_over_unresolved_alternative(
    tmp_path: Path,
) -> None:
    config, census, header, registry = nos_inputs(tmp_path)
    path = census / "links.json"
    links = json.loads(path.read_text())
    links.append({**links[0], "link_sensor": "B", "resolved_url": URL.replace("_A_", "_B_")})
    path.write_text(json.dumps(links))
    output = tmp_path / "result"
    build_crosswalk(
        config, census, tmp_path, output, header_configs=[header], registry_configs=[registry]
    )
    alternatives = read_csv(output / "event_site.csv")
    assert len(alternatives) == 2
    assert sum(row["event_site_identity_verified"] == "True" for row in alternatives) == 1
    report = read_csv(output / "unique_report_crosswalk.csv")[0]
    assert report["identity_tier"] == "ambiguous" and report["physical_site_id"] == "unknown"
    assert report["event_site_identity_verified"] == "False" and report["alternative_count"] == "2"


def test_geographic_signature_excludes_sensor_and_day_but_not_coordinate_or_source() -> None:
    header = dict(parse_ntwc_header(HEADER, "exam_A_2011.070"))
    original = geographic_site_id(header)
    assert (
        geographic_site_id({**header, "link_sensor": "B", "header_date": "2012-01-01"}) == original
    )
    for key, value in (
        ("latitude", 10.00001),
        ("provider", "OTHER"),
        ("link_code", "other"),
        ("header_station_id", "123"),
        ("header_name", "Other_place"),
    ):
        assert geographic_site_id({**header, key: value}) != original


def test_same_geographic_site_has_separate_sensors_but_one_site_count(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, raw = source(tmp_path)
    second_raw = tmp_path / raw.name.replace("_A_", "_B_")
    second_raw.write_bytes(raw.read_bytes())
    second_raw.with_name(second_raw.name + ".sha256").write_text(
        hashlib.sha256(raw.read_bytes()).hexdigest()
    )
    second_header = tmp_path / "header-b.toml"
    second_header.write_text(
        header.read_text()
        .replace("_A_", "_B_")
        .replace('source_id="header"', 'source_id="header-b"')
    )
    links_path = census / "links.json"
    links = json.loads(links_path.read_text())
    links.append({**links[0], "link_sensor": "B", "resolved_url": URL.replace("_A_", "_B_")})
    links_path.write_text(json.dumps(links))
    first, final = tmp_path / "first", tmp_path / "final"
    build_crosswalk(config, census, tmp_path, first, header_configs=[header, second_header])
    review = review_file(tmp_path, read_csv(first / "unique_report_crosswalk.csv")[0])
    result = build_crosswalk(
        config,
        census,
        tmp_path,
        final,
        header_configs=[header, second_header],
        identity_review=review,
    )
    expanded = read_csv(final / "event_site.csv")
    assert len(expanded) == 2 and {r["link_sensor"] for r in expanded} == {"A", "B"}
    assert len({r["physical_site_id"] for r in expanded}) == 1
    assert result["event_identity_support"][0]["reviewed_physical_sites"] == 1
    validate_reviewed_site_evidence(read_csv(final / "unique_report_crosswalk.csv")[0])


@pytest.mark.parametrize("kind", ["geographic", "provider"])
def test_reviewed_evidence_validates_both_site_scopes(tmp_path: Path, kind: str) -> None:
    if kind == "provider":
        config, census, header, registry = nos_inputs(tmp_path)
        registries = [registry]
    else:
        config, census = inputs(tmp_path)
        header, _ = source(tmp_path)
        registries = []
    first, final = tmp_path / "first", tmp_path / "final"
    build_crosswalk(
        config, census, tmp_path, first, header_configs=[header], registry_configs=registries
    )
    review = review_file(tmp_path, read_csv(first / "unique_report_crosswalk.csv")[0])
    build_crosswalk(
        config,
        census,
        tmp_path,
        final,
        header_configs=[header],
        registry_configs=registries,
        identity_review=review,
    )
    row = read_csv(final / "unique_report_crosswalk.csv")[0]
    validate_reviewed_site_evidence(row)
    for field, value in (
        ("physical_site_id", "ntwc-header-site:wrong"),
        ("provider", "OTHER"),
        ("provider_station_id", "9876543"),
        ("identity_scope", "other"),
        ("identity_basis", "other"),
        ("source_ids", "[]"),
    ):
        with pytest.raises(StationError):
            validate_reviewed_site_evidence({**row, field: value})


def test_generic_header_place_never_identifies_site(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, raw = source(tmp_path)
    raw.write_text(HEADER.replace("Example", "Unknown"))
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(raw.read_bytes()).hexdigest())
    header.write_text(header.read_text().replace("Example", "Unknown"))
    rows = json.loads((census / "rows.json").read_text())
    rows[0]["fields"]["location"] = "Unknown"
    (census / "rows.json").write_text(json.dumps(rows))
    build_crosswalk(config, census, tmp_path, tmp_path / "out", header_configs=[header])
    row = read_csv(tmp_path / "out" / "unique_report_crosswalk.csv")[0]
    assert row["event_site_identity_verified"] == "False"
    assert row["physical_site_id"] == "unknown"


@pytest.mark.parametrize("label", ["Example, Chile", "Example", "Example, USA, Other"])
def test_source_qualified_site_requires_full_report_region_agreement(
    tmp_path: Path, label: str
) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    rows = json.loads((census / "rows.json").read_text())
    rows[0]["fields"]["location"] = label
    (census / "rows.json").write_text(json.dumps(rows))
    output = tmp_path / "out"
    build_crosswalk(config, census, tmp_path, output, header_configs=[header])
    row = read_csv(output / "event_site.csv")[0]
    assert row["identity_tier"] == "ambiguous"
    assert row["evidence_status"] == "report_header_qualified_label_conflict"
    assert row["physical_site_id"] == "unknown"


def test_conflicting_linked_header_coordinates_do_not_choose_first_day(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    second_raw = tmp_path / "exam_A_2011.071"
    second_raw.write_text(HEADER.replace("20110311", "20110312").replace("10.0", "10.001"))
    second_raw.with_name(second_raw.name + ".sha256").write_text(
        hashlib.sha256(second_raw.read_bytes()).hexdigest()
    )
    second_header = tmp_path / "header-day2.toml"
    second_header.write_text(
        header.read_text()
        .replace("2011.070", "2011.071")
        .replace('source_id="header"', 'source_id="header-day2"')
    )
    links_path = census / "links.json"
    links = json.loads(links_path.read_text())
    links.append({**links[0], "resolved_url": URL.replace("2011.070", "2011.071")})
    links_path.write_text(json.dumps(links))
    output = tmp_path / "out"
    build_crosswalk(config, census, tmp_path, output, header_configs=[header, second_header])
    row = read_csv(output / "event_site.csv")[0]
    assert row["evidence_status"] == "header_identity_conflict"
    assert row["physical_site_id"] == "unknown"
    assert len(json.loads(row["header_metadata"])) == 2


@pytest.mark.parametrize(
    "station_id,label,header_name",
    [
        ("9462620", "Unalaska, Alaska", "Dutch_Harbor,_AK"),
        ("1611400", "Nawiliwili HI", "Nawiliwili_Kauai,_HI"),
        ("1612340", "Honolulu HI", "Honolulu_Oahu,_HI"),
        ("1617433", "Kawaihae HI", "Kawaihae,_HI"),
        ("1615680", "Kahului HI", "Kahului_Maui,_HI"),
    ],
)
def test_reviewed_id_qualified_nos_full_labels(
    tmp_path: Path, station_id: str, label: str, header_name: str
) -> None:
    config, census, header, registry = nos_inputs(
        tmp_path, station_id=station_id, label=label, header_name=header_name
    )
    build_crosswalk(
        config,
        census,
        tmp_path,
        tmp_path / "out",
        header_configs=[header],
        registry_configs=[registry],
    )
    row = read_csv(tmp_path / "out" / "unique_report_crosswalk.csv")[0]
    assert row["physical_site_id"] == "coops:" + station_id
    assert row["event_site_identity_verified"] == "True"


@pytest.mark.parametrize(
    "station_id,label", [("9462621", "Unalaska, Alaska"), ("9462620", "Unalaska, Chile")]
)
def test_nos_alias_does_not_override_wrong_id_or_country(
    tmp_path: Path, station_id: str, label: str
) -> None:
    config, census, header, registry = nos_inputs(
        tmp_path, station_id=station_id, label=label, header_name="Dutch_Harbor,_AK"
    )
    build_crosswalk(
        config,
        census,
        tmp_path,
        tmp_path / "out",
        header_configs=[header],
        registry_configs=[registry],
    )
    row = read_csv(tmp_path / "out" / "unique_report_crosswalk.csv")[0]
    assert row["physical_site_id"] == "unknown" and row["identity_tier"] == "ambiguous"


def pinned_header_source(tmp_path: Path) -> tuple[Path, Path, Path]:
    from pipeline.acquisition import load_contracts

    config, raw = source(tmp_path)
    contract = load_contracts(config)[0]
    captured = contract.url.split("/web/", 1)[1]
    timestamp, original = captured.split("id_/", 1)
    digest = base64.b32encode(
        hashlib.sha1(raw.read_bytes(), usedforsecurity=False).digest()
    ).decode()
    cdx = tmp_path / "cdx.json"
    cdx.write_text(
        json.dumps(
            [
                ["timestamp", "original", "digest", "statuscode"],
                [timestamp, original, digest, "200"],
            ]
        )
    )
    cdx_sha = hashlib.sha256(cdx.read_bytes()).hexdigest()
    cdx.with_name(cdx.name + ".sha256").write_text(cdx_sha)
    config.write_text(
        config.read_text().replace('expected_prefix="Example,_USA"', 'expected_prefix=""')
        + f'\nexpected_cdx_sha1="{digest}"\ncdx_evidence_path="cdx.json"\n'
        + f'cdx_evidence_sha256="{cdx_sha}"\n'
    )
    receipt = tmp_path / "header-receipts.json"
    receipt.write_text(
        json.dumps(
            [
                {
                    "source_id": "header",
                    "local_path": raw.name,
                    "status": "downloaded",
                    "bytes": len(raw.read_bytes()),
                    "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                    "verified_cdx_sha1": digest,
                    "reason": "not applicable",
                }
            ]
        )
    )
    return config, raw, receipt


def test_pinned_header_requires_complete_receipt_and_cdx_body_evidence(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, _, receipts = pinned_header_source(tmp_path)
    with pytest.raises(StationError, match="complete final receipts"):
        build_crosswalk(config, census, tmp_path, tmp_path / "absent", header_configs=[header])
    output = tmp_path / "out"
    summary = build_crosswalk(
        config, census, tmp_path, output, header_configs=[header], header_receipts=[receipts]
    )
    assert summary["verified_header_assets"] == 1
    assert (
        summary["header_receipt_sha256"][str(receipts)]
        == hashlib.sha256(receipts.read_bytes()).hexdigest()
    )
    assert read_csv(output / "event_site.csv")[0]["event_site_identity_verified"] == "True"


def test_duplicate_header_contract_ids_reject_before_publication(tmp_path: Path) -> None:
    config, census = inputs(tmp_path)
    header, _, receipts = pinned_header_source(tmp_path)
    copied = tmp_path / "copied-header.toml"
    copied.write_bytes(header.read_bytes())
    with pytest.raises(StationError, match="header contracts have duplicate source IDs"):
        build_crosswalk(
            config,
            census,
            tmp_path,
            tmp_path / "out",
            header_configs=[header, copied],
            header_receipts=[receipts],
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "failure", ["body", "evidence", "receipt_sha", "receipt_cdx", "running", "duplicate", "extra"]
)
def test_pinned_header_proof_failures_reject_before_publication(
    tmp_path: Path, failure: str
) -> None:
    config, census = inputs(tmp_path)
    header, raw, receipts = pinned_header_source(tmp_path)
    values = json.loads(receipts.read_text())
    if failure == "body":
        raw.write_bytes(raw.read_bytes() + b"changed")
        raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(raw.read_bytes()).hexdigest())
    elif failure == "evidence":
        (tmp_path / "cdx.json").write_text("[]")
    elif failure == "receipt_sha":
        values[0]["sha256"] = "0" * 64
    elif failure == "receipt_cdx":
        values[0]["verified_cdx_sha1"] = "A" * 32
    elif failure == "running":
        values[0]["status"] = "running"
    elif failure == "duplicate":
        values.append(values[0])
    else:
        values.append({**values[0], "source_id": "unconfigured"})
    receipts.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        build_crosswalk(
            config,
            census,
            tmp_path,
            tmp_path / "out",
            header_configs=[header],
            header_receipts=[receipts],
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("status", ["quarantined", "skipped"])
def test_unavailable_header_receipt_is_accounted_without_reading_raw(
    tmp_path: Path, status: str
) -> None:
    config, census = inputs(tmp_path)
    header, raw, receipts = pinned_header_source(tmp_path)
    values = json.loads(receipts.read_text())
    values[0].update(status=status, reason="provider unavailable", sha256="not-downloaded")
    receipts.write_text(json.dumps(values))
    raw.unlink()
    output = tmp_path / "out"
    summary = build_crosswalk(
        config, census, tmp_path, output, header_configs=[header], header_receipts=[receipts]
    )
    assert summary["unavailable_header_assets"] == 1 and summary["verified_header_assets"] == 0
    row = read_csv(output / "event_site.csv")[0]
    assert row["evidence_status"] == "header_acquisition_unavailable"
    assert row["physical_site_id"] == "unknown"
    assert (
        json.loads(row["evidence"])["unavailable_header_sources"][0]["acquisition_status"] == status
    )
    assert read_csv(output / "pull_list.csv") == []


def test_crosswalk_delta_distinguishes_new_and_unchanged_evidence_without_approval(
    tmp_path: Path,
) -> None:
    config, census = inputs(tmp_path)
    header, _ = source(tmp_path)
    first, new, replay = tmp_path / "first", tmp_path / "new", tmp_path / "replay"
    build_crosswalk(config, census, tmp_path, first)
    summary = build_crosswalk(
        config,
        census,
        tmp_path,
        new,
        header_configs=[header],
        previous_crosswalk=first / "unique_report_crosswalk.csv",
    )
    assert summary["identity_delta_counts"] == {"new_identity": 1}
    row = read_csv(new / "identity_delta.csv")[0]
    assert row["previous_physical_site_id"] == "unknown"
    assert row["current_review_status"] == "pending_independent_review"
    repeated = build_crosswalk(
        config,
        census,
        tmp_path,
        replay,
        header_configs=[header],
        previous_crosswalk=new / "unique_report_crosswalk.csv",
    )
    assert repeated["identity_delta_counts"] == {"unchanged_identity_evidence": 1}
    assert repeated["reviewed_event_site_reports"] == 0


@pytest.mark.parametrize("failure", ["duplicate", "digest", "role"])
def test_crosswalk_delta_rejects_invalid_frozen_report_evidence(
    tmp_path: Path, failure: str
) -> None:
    config, census = inputs(tmp_path)
    first = tmp_path / "first"
    build_crosswalk(config, census, tmp_path, first)
    previous = first / "unique_report_crosswalk.csv"
    rows = read_csv(previous)
    if failure == "duplicate":
        rows.append(rows[0])
    elif failure == "digest":
        rows[0]["identity_evidence_sha256"] = "0" * 64
    else:
        rows[0]["role"] = "sealed_evaluation"
    with previous.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(StationError):
        build_crosswalk(config, census, tmp_path, tmp_path / "out", previous_crosswalk=previous)
    assert not (tmp_path / "out").exists()
