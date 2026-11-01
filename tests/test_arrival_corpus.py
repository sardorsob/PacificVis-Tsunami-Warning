"""Reported-clock parsing must preserve uncertainty, source rows and sealed roles."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from analysis.arrival.stations import geographic_signature, geographic_site_id
from pipeline.arrival_corpus import CorpusError, build_corpus, parse_reported_time
from scripts.build_arrival_corpus import main


def context(year: int = 2012, month: int = 2, day: int = 29) -> dict[str, Any]:
    return {"calendar_year": year, "origin": datetime(year, month, day, tzinfo=UTC)}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "blank"),
        ("\xa0", "blank"),
        ("none", "source_missing_token"),
        ("(?)", "source_missing_token"),
        ("??? 5/4", "source_missing_token"),
        ("? (060)", "source_missing_token"),
        ("~0010 (060)", "qualified_value"),
        ("0010 ? (060)", "qualified_value"),
        ("approx 0010", "qualified_value"),
        ("0010", "date_ambiguous"),
        ("24:00 (060)", "invalid_clock"),
        ("0060 (060)", "invalid_clock"),
        ("0010 (367)", "invalid_day_of_year"),
        ("0010 (000)", "invalid_day_of_year"),
        ("1 am", "unknown_format"),
    ],
)
def test_missing_qualified_and_ambiguous_values_are_never_exact(raw: str, expected: str) -> None:
    result = parse_reported_time(raw, "estimated_observed_utc_jday", context())
    assert result["state"] == expected and result["timestamp_utc"] == "unknown"


def test_exact_components_survive_without_calendar_authority() -> None:
    result = parse_reported_time(" \r\n00:10 (JD 060)\xa0", "estimated_observed_utc_jday")
    assert result == {
        "state": "calendar_context_missing",
        "hour": 0,
        "minute": 10,
        "day_of_year": 60,
        "timestamp_utc": "unknown",
    }
    exact = parse_reported_time("0010 (060)", "estimated_observed_gmt_jday", context())
    assert exact["timestamp_utc"] == "2012-02-29T00:10:00Z"


def test_leap_days_and_year_boundaries_need_valid_explicit_context() -> None:
    nonleap = parse_reported_time("0010 (366)", "estimated_observed_utc_jday", context(2011, 3, 11))
    assert nonleap["state"] == "invalid_day_of_year"
    rollover = parse_reported_time(
        "0010 (001)", "estimated_observed_utc_jday", context(2011, 12, 31)
    )
    assert rollover["state"] == "year_boundary_review_required"
    assert rollover["day_of_year"] == 1 and rollover["timestamp_utc"] == "unknown"


def test_header_semantics_are_not_inferred_from_numeric_appearance() -> None:
    assert parse_reported_time("0010 (060)", "arrival_eta_utc", context())["state"] == (
        "legacy_semantics_unverified"
    )
    assert parse_reported_time("0010 (060)", "computed_observed_utc", context())["state"] == (
        "day_semantics_unverified"
    )
    assert parse_reported_time("0010 (060)", "unknown", context())["state"] == "unknown_time_rule"


def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[events.a]
event_id="event-a"
archive_source_id="source-a"
role="development"
usgs_time="2012-02-29T00:00:01Z"
usgs_mag="8.0"
usgs_magType="mwb"
[events.b]
event_id="event-b"
archive_source_id="source-b"
role="development"
[events.sealed]
event_id="event-sealed"
archive_source_id="source-sealed"
role="sealed_evaluation"
""",
        encoding="utf-8",
    )
    census = tmp_path / "census"
    census.mkdir()
    rows: list[dict[str, Any]] = []
    for index, (estimate, observed) in enumerate(
        [
            ("0010 (060)", "0020 (060)"),
            ("~0010 (060)", "0020 (060)"),
            ("none", "0020 (060)"),
            ("0010", "0020"),
            ("", ""),
        ],
        1,
    ):
        rows.append(
            {
                "event_id": "event-a",
                "role": "development",
                "source_id": "source-a",
                "table_index": 0,
                "row_index": index,
                "status": "accepted_source_row" if index < 5 else "rejected_cell_count",
                "fields": {
                    "location": " Hilo\r\n",
                    "estimated_arrival": estimate,
                    "observed_arrival": observed,
                }
                if index < 5
                else {},
                "cells": [{"text": estimate, "raw_html": f"<td>\r\n{estimate}</td>"}],
                "cell_states": [],
                "raw_html": f"<tr>\r\n{estimate}\r\n</tr>",
            }
        )
    rows.append(
        {
            "event_id": "event-a",
            "role": "development",
            "source_id": "source-a",
            "table_index": 1,
            "row_index": 1,
            "status": "accepted_source_row",
            "fields": {
                "location": "Hilo",
                "arrival_as_labeled": "2/29 0020",
                "eta_as_labeled": "2/29 0010",
            },
            "cells": [],
            "cell_states": [],
            "raw_html": "<tr>legacy</tr>",
        }
    )
    pages: list[dict[str, Any]] = [
        {
            "event_id": "event-a",
            "role": "development",
            "source_id": "source-a",
            "sha256": "a" * 64,
            "archive_url": "https://example.test/a",
            "arrival_tables": [
                {
                    "table_index": 0,
                    "header_family": "estimated_observed_utc_jday",
                    "status": "recognized",
                    "header_row_index": 0,
                    "source_rows": 6,
                    "rows_after_header": 5,
                },
                {
                    "table_index": 1,
                    "header_family": "arrival_eta_utc",
                    "status": "recognized",
                    "header_row_index": 0,
                    "source_rows": 2,
                    "rows_after_header": 1,
                },
            ],
        },
        {
            "event_id": "event-b",
            "role": "development",
            "source_id": "source-b",
            "sha256": "b" * 64,
            "archive_url": "https://example.test/b",
            "arrival_tables": [],
        },
        {
            "event_id": "event-sealed",
            "role": "sealed_evaluation",
            "source_id": "source-sealed",
            "arrival_tables": [],
        },
    ]
    (census / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    (census / "census.json").write_text(json.dumps(pages), encoding="utf-8")
    years = tmp_path / "time-context.csv"
    years.write_text(
        "event_id,calendar_year,calendar_year_provenance,origin_utc,origin_basis,origin_provenance\n"
        "event-a,2012,reviewed archive header,2012-02-29T00:00:00Z,"
        "NTWC contemporary,reviewed intro\n",
        encoding="utf-8",
    )
    return config, census, years


def read_table(output: Path, name: str, event: str = "event-a") -> list[dict[str, str]]:
    with gzip.open(output / event / f"{name}.csv.gz", "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def time_evidence_fixture(tmp_path: Path, census: Path) -> Path:
    raw = tmp_path / "page.html"
    raw.write_text("<h1>Fixture 29 February 2012; UTC Arrival and ETA definitions</h1>")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    pages = json.loads((census / "census.json").read_text())
    pages[0]["sha256"] = digest
    (census / "census.json").write_text(json.dumps(pages))
    path = tmp_path / "evidence.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "event_id", "source_id", "source_sha256", "source_path", "table_index",
            "header_family", "rule_ids", "evidence_id", "review_status", "reviewer", "scope",
        ])
        writer.writeheader()
        writer.writerow({
            "event_id": "event-a", "source_id": "source-a", "source_sha256": digest,
            "source_path": "page.html", "table_index": 1, "header_family": "arrival_eta_utc",
            "rule_ids": '["inline_month_day_v1","legacy_definition_v1"]',
            "evidence_id": "fixture-legacy-definitions", "review_status": "independently_reviewed",
            "reviewer": "fixture independent checker", "scope": "table 1 UTC definitions",
        })
    return path


def test_reviewed_time_evidence_preserves_observed_only_rows_and_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, census, years = inputs(tmp_path)
    evidence = time_evidence_fixture(tmp_path, census)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "v5"
    summary = build_corpus(config, census, output, time_context=years, time_evidence=evidence)
    assert summary["source_rows"] == 6 and summary["exact_pairs"] == 2
    assert summary["exact_observed_values"] == 4
    legacy = next(x for x in read_table(output, "pair") if x["report_id"] == "event-a:1:1")
    assert "legacy_definition_v1" in legacy["time_rule_id"]
    assert "unresolved" not in legacy["time_rule_id"]
    values = read_table(output, "reported_time_value")
    assert len(values) == 12
    value = next(x for x in values if x["report_id"] == "event-a:0:3"
                 and x["field_role"] == "observed")
    assert value["timestamp_utc"] == "2012-02-29T00:20:00Z"
    eligibility = read_table(output, "target_eligibility")
    assert len(eligibility) == 12
    partial = [x for x in eligibility if x["report_id"] == "event-a:0:3"]
    assert all(x["model_eligible"] == "False" for x in partial)
    obs = next(x for x in partial if x["target_id"] == "T-OBS")
    assert "estimate" not in obs["reason_codes"]
    assert "geographic_identity_unreviewed" in obs["reason_codes"]
    cal = next(x for x in partial if x["target_id"] == "T-CAL")
    assert "estimate:source_absent_explicit" in cal["reason_codes"]
    assert not (output / "event-sealed").exists()


@pytest.mark.parametrize("bad_field", ["source_sha256", "event_id", "review_status"])
def test_invalid_time_evidence_cannot_publish_a_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_field: str,
) -> None:
    config, census, years = inputs(tmp_path)
    evidence = time_evidence_fixture(tmp_path, census)
    rows = list(csv.DictReader(evidence.open()))
    rows[0][bad_field] = {"source_sha256": "b" * 64, "event_id": "event-sealed",
                          "review_status": "pending"}[bad_field]
    with evidence.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "v5"
    with pytest.raises(CorpusError, match="evidence"):
        build_corpus(config, census, output, time_context=years, time_evidence=evidence)
    assert not output.exists()


def test_all_rows_accounted_and_raw_strings_round_trip_without_released_timestamps(
    tmp_path: Path,
) -> None:
    config, census, _ = inputs(tmp_path)
    out = tmp_path / "corpus"
    summary = build_corpus(config, census, out)
    assert summary["source_rows"] == summary["rejected_or_uncertain"] == 6
    assert summary["exact_pairs"] == 0 and summary["reserved_events_excluded"] == 1
    original = json.loads((census / "rows.json").read_text())
    reports = read_table(out, "arrival_report")
    assert [json.loads(row["raw_row_json"]) for row in reports] == original
    assert reports[0]["estimate_hour"] == "0" and reports[0]["estimate_day_of_year"] == "60"
    assert reports[0]["estimate_state"] == "calendar_context_missing"
    assert reports[-1]["observed_raw"] == "" and reports[-1]["legacy_arrival_raw"] == "2/29 0020"
    assert all(r["stage_d_status"] == "not_assessed" for r in read_table(out, "event"))
    assert not (out / "event-sealed").exists()
    assert read_table(out, "arrival_report", "event-b") == []


def test_reviewed_calendar_context_produces_only_exact_reported_pairs(tmp_path: Path) -> None:
    config, census, years = inputs(tmp_path)
    out = tmp_path / "corpus"
    summary = build_corpus(config, census, out, time_context=years)
    assert summary["exact_pairs"] == 1 and summary["rejected_or_uncertain"] == 5
    (pair,) = read_table(out, "pair")
    assert pair["report_id"] == "event-a:0:1"
    assert pair["estimated_elapsed_seconds"] == "600.0"
    assert pair["observed_elapsed_seconds"] == "1200.0"
    assert pair["origin_basis"] == "NTWC contemporary"
    assert pair["physical_site_id"] == "unknown" and pair["fit_tier_identity"] == "False"
    assert pair["model_eligible"] == pair["physical_onset_validated"] == "False"
    assert any(
        "structural:rejected_cell_count" in r["reason_codes"]
        for r in read_table(out, "rejected_record")
    )


@pytest.mark.parametrize(
    "origin",
    ["2012-02-28Z", "2012-02-28+00:00", "2012-02-29T00:00:00", "2012-02-29T00:00:00+01:00"],
)
def test_origin_requires_full_aware_utc_datetime(tmp_path: Path, origin: str) -> None:
    config, census, years = inputs(tmp_path)
    years.write_text(years.read_text().replace("2012-02-29T00:00:00Z", origin), encoding="utf-8")
    out = tmp_path / "corpus"
    with pytest.raises(CorpusError, match="origin"):
        build_corpus(config, census, out, time_context=years)
    assert not out.exists()


def test_calendar_year_cannot_override_origin_year_without_rollover_authority(
    tmp_path: Path,
) -> None:
    config, census, years = inputs(tmp_path)
    years.write_text(years.read_text().replace("event-a,2012,", "event-a,2013,"), encoding="utf-8")
    out = tmp_path / "corpus"
    with pytest.raises(CorpusError, match="calendar year.*origin year"):
        build_corpus(config, census, out, time_context=years)
    assert not out.exists()


def test_fractional_utc_origin_keeps_subsecond_precision(tmp_path: Path) -> None:
    config, census, years = inputs(tmp_path)
    years.write_text(
        years.read_text().replace("2012-02-29T00:00:00Z", "2012-02-29T00:00:00.250+00:00"),
        encoding="utf-8",
    )
    out = tmp_path / "corpus"
    build_corpus(config, census, out, time_context=years)
    assert read_table(out, "pair")[0]["estimated_elapsed_seconds"] == "599.75"


def test_crosswalk_identity_does_not_promote_model_or_stage_d_eligibility(tmp_path: Path) -> None:
    config, census, years = inputs(tmp_path)
    crosswalk = tmp_path / "crosswalk.csv"
    crosswalk.write_text(
        "event_id,report_id,identity_tier,physical_site_id,deployment_id,evidence\n"
        "event-a,event-a:0:1,header_exact,hilo,deployment-2012,reviewed header/date\n",
        encoding="utf-8",
    )
    out = tmp_path / "corpus"
    build_corpus(config, census, out, time_context=years, crosswalk=crosswalk)
    (pair,) = read_table(out, "pair")
    assert pair["physical_site_id"] == "hilo" and pair["fit_tier_identity"] == "False"
    assert pair["model_eligible"] == "False"
    assert read_table(out, "event")[0]["stage_d_status"] == "not_assessed"


@pytest.mark.parametrize("tamper", [False, True])
@pytest.mark.parametrize("deployment_claim", [False, True])
@pytest.mark.parametrize("source_qualified", [False, True])
def test_reviewed_event_site_is_usable_without_invented_deployment(
    tmp_path: Path, tamper: bool, deployment_claim: bool, source_qualified: bool
) -> None:
    config, census, years = inputs(tmp_path)
    evidence = json.dumps(
        [
            {
                "event_id": "event-a",
                "report_id": "event-a:0:1",
                "physical_site_id": "coops:1234567",
                "report_label": "Hilo",
                "link_code": "hilo",
                "link_sensor": "A",
                "registry_id_checks": [
                    {
                        "provider": "CO-OPS",
                        "station_id": "1234567",
                        "name": "Hilo",
                        "latitude": 10.0,
                        "longitude": 20.0,
                    }
                ],
                "headers": [
                    {
                        "source_id": "header-a",
                        "header_station_id": "1234567",
                        "provider": "NOS",
                        "header_name": "Hilo",
                        "link_code": "hilo",
                        "link_sensor": "A",
                        "latitude": 10.0,
                        "longitude": 20.0,
                        "original_url": "https://www.tsunami.gov/previous.events/test/hilo_A_2012.060",
                        "source_url": "https://web.archive.org/web/20161201000000id_/http://www.tsunami.gov/previous.events/test/hilo_A_2012.060",
                        "sha256": "a" * 64,
                    }
                ],
            }
        ]
    )
    row = dict(
        event_id="event-a",
        report_id="event-a:0:1",
        identity_tier="header_exact",
        physical_site_id="coops:1234567",
        deployment_id="unverified-claim" if deployment_claim else "unknown",
        evidence=evidence,
        provider="CO-OPS",
        provider_station_id="7654321" if tamper else "1234567",
        source_ids='["header-a"]',
        identity_evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
        review_status="independently_reviewed",
        event_site_identity_verified="True",
        deployment_continuity_verified="True" if deployment_claim else "False",
    )
    if source_qualified:
        alternative = json.loads(evidence)[0]
        header = alternative["headers"][0]
        header.update(provider="GNS", header_station_id="none")
        alternative.update(
            physical_site_id=geographic_site_id(header),
            identity_scope="source_qualified_geographic_site",
            identity_basis="exact_linked_header_name_code_coordinates",
            geographic_signature=geographic_signature(header),
            registry_id_checks=[],
        )
        evidence = json.dumps([alternative])
        row.update(
            physical_site_id=alternative["physical_site_id"],
            provider="GNS",
            provider_station_id="7654321" if tamper else "unknown",
            identity_scope=alternative["identity_scope"],
            identity_basis=alternative["identity_basis"],
            evidence=evidence,
            identity_evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
        )
    crosswalk = tmp_path / "reviewed.csv"
    with crosswalk.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    out = tmp_path / "corpus"
    if tamper:
        with pytest.raises(CorpusError, match="digest-bound evidence"):
            build_corpus(config, census, out, time_context=years, crosswalk=crosswalk)
        assert not out.exists()
        return
    build_corpus(config, census, out, time_context=years, crosswalk=crosswalk)
    (pair,) = read_table(out, "pair")
    assert pair["fit_tier_identity"] == pair["event_site_identity_verified"] == "True"
    assert pair["deployment_id"] == row["deployment_id"]
    if source_qualified:
        assert pair["identity_scope"] == "source_qualified_geographic_site"
        assert pair["physical_site_id"].startswith("ntwc-header-site:")
    assert (
        pair["deployment_continuity_verified"]
        == pair["model_eligible"]
        == pair["physical_onset_validated"]
        == "False"
    )


def test_replay_is_byte_identical_and_csv_input_preserves_row_payloads(tmp_path: Path) -> None:
    config, census, years = inputs(tmp_path)
    a, b, c = (tmp_path / name for name in ("first", "second", "csv"))
    build_corpus(config, census, a, time_context=years)
    build_corpus(config, census, b, time_context=years)
    for file in a.rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (b / file.relative_to(a)).read_bytes()
    with pytest.raises(FileExistsError):
        build_corpus(config, census, a)
    rows = json.loads((census / "rows.json").read_text())
    csv_path = census / "rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
            for row in rows
        )
    build_corpus(config, census, c, rows_path=csv_path, time_context=years)
    assert (a / "event-a/arrival_report.csv.gz").read_bytes() == (
        c / "event-a/arrival_report.csv.gz"
    ).read_bytes()


@pytest.mark.parametrize("violation", ["reserved", "duplicate", "count", "source", "index"])
def test_corrupt_or_reserved_rows_fail_before_publication(tmp_path: Path, violation: str) -> None:
    config, census, _ = inputs(tmp_path)
    rows = json.loads((census / "rows.json").read_text())
    if violation == "reserved":
        rows[0].update(event_id="event-sealed", role="sealed_evaluation")
    elif violation == "duplicate":
        rows.append(rows[0])
    elif violation == "count":
        rows.pop()
    elif violation == "source":
        rows[0]["source_id"] = "wrong"
    else:
        rows[0]["row_index"] = -1
    (census / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    out = tmp_path / "corpus"
    with pytest.raises(CorpusError):
        build_corpus(config, census, out)
    assert not out.exists()


def test_negative_elapsed_is_retained_as_rejected_not_retimed(tmp_path: Path) -> None:
    config, census, years = inputs(tmp_path)
    years.write_text(years.read_text().replace("00:00:00Z", "01:00:00Z"), encoding="utf-8")
    out = tmp_path / "corpus"
    summary = build_corpus(config, census, out, time_context=years)
    assert summary["exact_pairs"] == 0
    assert "estimated:nonpositive_elapsed" in read_table(out, "rejected_record")[0]["reason_codes"]
    assert read_table(out, "arrival_report")[0]["estimated_utc"] == "2012-02-29T00:10:00Z"


def test_cli_no_time_context_keeps_numeric_pairs_unreleased(tmp_path: Path, capsys: Any) -> None:
    config, census, _ = inputs(tmp_path)
    assert (
        main(
            ["--config", str(config), "--census", str(census), "--output", str(tmp_path / "corpus")]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["exact_pairs"] == 0
