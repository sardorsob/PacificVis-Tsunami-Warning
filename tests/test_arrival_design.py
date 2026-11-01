"""Design counts must preserve roles, source semantics and identity uncertainty."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from analysis.arrival.design import DesignError, build_design, incidence_rank
from pipeline.ntwc_archive import arrival_value_flags
from scripts.build_arrival_design import main


def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[events.a]
event_id="a"
archive_source_id="source-a"
role="development"
usgs_mag="7.6"
usgs_magType="mww"
[events.b]
event_id="b"
archive_source_id="source-b"
role="development"
usgs_mag="8.1"
usgs_magType="mwb"
[events.c]
event_id="c"
archive_source_id="source-c"
role="sealed_evaluation"
""",
        encoding="utf-8",
    )
    annotation = tmp_path / "annotations.csv"
    annotation.write_text(
        "event_id,mechanism_class,cohort,citation\n"
        "a,normal,contrast,https://example.test/a\n"
        "b,interface_thrust,thrust_core,https://example.test/b\n",
        encoding="utf-8",
    )
    census = tmp_path / "census"
    census.mkdir()
    rows: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for eid in ("a", "b"):
        identity = {"event_id": eid, "role": "development", "source_id": f"source-{eid}"}
        fields = {
            "location": "Example\xa0Site",
            "estimated_arrival": "0100",
            "observed_arrival": "0200" if eid == "a" else "none",
        }
        rows.append(
            {
                **identity,
                "table_index": 0,
                "row_index": 1,
                "status": "accepted_source_row",
                "fields": fields,
            }
        )
        for day in ("001", "002"):
            links.append(
                {
                    **identity,
                    "table_index": 0,
                    "row_index": 1,
                    "status": "safe_archive_link",
                    "link_code": "exam",
                    "link_sensor": "A",
                    "link_identity_status": "archive_code_sensor_year_day",
                    "location_text": fields["location"],
                    "link_day": day,
                    "link_year": "2011",
                }
            )
    pages: list[dict[str, Any]] = []
    for row in rows:
        counts = {
            f"rows_with_{key}": int(value)
            for key, value in arrival_value_flags(row["fields"]).items()
        }
        pages.append(
            {key: row[key] for key in ("event_id", "source_id", "role")}
            | {"status": "inventoried", "arrival_tables": [{"rows_after_header": 1, **counts}]}
        )
    pages.append(
        {
            "event_id": "c",
            "source_id": "source-c",
            "role": "sealed_evaluation",
            "status": "inventoried",
            "arrival_tables": [],
        }
    )
    for name, records in (("census", pages), ("rows", rows), ("links", links)):
        (census / f"{name}.json").write_text(json.dumps(records), encoding="utf-8")
    return config, census, annotation


def reviewed_crosswalk(tmp_path: Path, census: Path, *, same_site: bool = True) -> Path:
    path = tmp_path / "crosswalk.csv"
    source_rows = json.loads((census / "rows.json").read_text())
    pages = json.loads((census / "census.json").read_text())
    for row in source_rows:
        row["fields"]["observed_arrival"] = "0200"
        page = next(page for page in pages if page["event_id"] == row["event_id"])
        page["arrival_tables"][0].update(
            {
                f"rows_with_{key}": int(value)
                for key, value in arrival_value_flags(row["fields"]).items()
            }
        )
    (census / "rows.json").write_text(json.dumps(source_rows))
    (census / "census.json").write_text(json.dumps(pages))
    records: list[dict[str, str]] = []
    for index, eid in enumerate(("a", "b")):
        evidence = json.dumps(
            [
                {
                    "event_id": eid,
                    "report_id": f"{eid}:0:1",
                    "physical_site_id": f"coops:{1000001 if same_site else 1000001 + index}",
                    "report_label": "Example Site",
                    "link_code": "exam",
                    "link_sensor": "A",
                    "registry_id_checks": [
                        {
                            "provider": "CO-OPS",
                            "station_id": str(1000001 if same_site else 1000001 + index),
                            "latitude": 10.0,
                            "longitude": 20.0,
                        }
                    ],
                    "headers": [
                        {
                            "header_date": "2011-03-11",
                            "header_name": "Example_Site",
                            "header_station_id": str(1000001 if same_site else 1000001 + index),
                            "latitude": 10.0,
                            "longitude": 20.0,
                            "link_code": "exam",
                            "link_sensor": "A",
                            "source_url": "https://www.tsunami.gov/previous.events/"
                            + eid
                            + "/exam_A_2011.070",
                            "original_url": "https://www.tsunami.gov/previous.events/"
                            + eid
                            + "/exam_A_2011.070",
                            "sha256": "a" * 64,
                            "provider": "NOS",
                            "cadence_value": "1",
                            "cadence_units": "min",
                            "units": "m",
                            "source_id": eid,
                        }
                    ],
                }
            ]
        )
        records.append(
            {
                "event_id": eid,
                "report_id": f"{eid}:0:1",
                "role": "development",
                "identity_tier": "header_exact",
                "physical_site_id": f"coops:{1000001 if same_site else 1000001 + index}",
                "provider": "CO-OPS",
                "provider_station_id": str(1000001 if same_site else 1000001 + index),
                "source_ids": json.dumps([eid]),
                "event_site_identity_verified": "True",
                "review_status": "independently_reviewed",
                "evidence": evidence,
                "identity_evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            }
        )
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return path


def test_reviewed_network_rank_holds_out_entire_event_or_site(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    crosswalk = reviewed_crosswalk(tmp_path, census)
    output = tmp_path / "design"
    summary = build_design(config, census, annotation, output, crosswalk=crosswalk)
    reviewed = summary["reviewed_identity_design"]
    rank = reviewed["explicit_pair_network"]
    assert (rank["events"], rank["sites"], rank["components"], rank["indicator_matrix_rank"]) == (
        2,
        1,
        1,
        2,
    )
    assert reviewed["median_site_event_degree"] == 2
    with (output / "fold_rank.csv").open() as stream:
        folds = list(csv.DictReader(stream))
    event_folds = [row for row in folds if row["fold"] == "LOEO"]
    assert len(event_folds) == 2 and all(row["indicator_matrix_rank"] == "1" for row in event_folds)
    site_fold = next(row for row in folds if row["fold"] == "LOSO")
    assert site_fold["training_edges"] == site_fold["indicator_matrix_rank"] == "0"
    assert json.loads(site_fold["unseen_events"]) == ["a", "b"]
    assert json.loads(site_fold["unseen_sites"]) == ["coops:1000001"]
    assert reviewed["model_eligibility_assessed"] is False
    assert (
        summary["input_sha256"]["crosswalk"] == hashlib.sha256(crosswalk.read_bytes()).hexdigest()
    )


def test_disconnected_single_event_sites_require_separate_constraints_and_sensitivity(
    tmp_path: Path,
) -> None:
    config, census, annotation = inputs(tmp_path)
    crosswalk = reviewed_crosswalk(tmp_path, census, same_site=False)
    result = build_design(config, census, annotation, tmp_path / "design", crosswalk=crosswalk)
    reviewed = result["reviewed_identity_design"]
    assert reviewed["explicit_pair_network"]["components"] == 2
    assert reviewed["explicit_pair_network"]["active_columns"] == 4
    assert reviewed["explicit_pair_network"]["indicator_matrix_rank"] == 2
    assert reviewed["site_effect_disposition"] == "sensitivity_only_single_event_sites"


@pytest.mark.parametrize(
    "failure", ["duplicate", "reserved", "digest", "unknown_site", "wrong_site"]
)
def test_design_rejects_crosswalk_identity_or_evidence_mismatch(
    tmp_path: Path, failure: str
) -> None:
    config, census, annotation = inputs(tmp_path)
    crosswalk = reviewed_crosswalk(tmp_path, census)
    with crosswalk.open() as stream:
        rows = list(csv.DictReader(stream))
    if failure == "duplicate":
        rows[1] = rows[0]
    elif failure == "reserved":
        rows[0]["event_id"] = "c"
    elif failure == "digest":
        rows[0]["evidence"] = "[]"
    elif failure == "unknown_site":
        rows[0]["physical_site_id"] = "unknown"
    else:
        rows[0]["physical_site_id"] = "coops:9999999"
    with crosswalk.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(DesignError):
        build_design(config, census, annotation, tmp_path / "design", crosswalk=crosswalk)
    assert not (tmp_path / "design").exists()


def test_indicator_rank_matches_connected_cycle_and_disconnected_edge() -> None:
    rank = incidence_rank({("a", "s1"), ("a", "s2"), ("b", "s1"), ("b", "s2"), ("c", "s3")})
    assert rank["active_columns"] == 6 and rank["components"] == 2
    assert rank["indicator_matrix_rank"] == 4
    assert incidence_rank(set())["indicator_matrix_rank"] == 0


def test_day_links_do_not_inflate_code_support_or_create_physical_site_ids(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    output = tmp_path / "design"
    summary = build_design(config, census, annotation, output)
    assert summary["development_events"] == 2 and summary["sealed_events_excluded"] == 1
    assert summary["source_pair_values"] == 1
    assert summary["archive_codes"]["unique_count"] == 1
    assert summary["archive_codes"]["median_events"] == 2
    assert summary["location_labels"]["unique_count"] == 1
    with (output / "code_incidence.csv").open(encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    assert len(records) == 2
    assert all(row["source_row_count"] == "1" and row["link_count"] == "2" for row in records)
    assert all(row["identity_tier"] == "archive_code" for row in records)
    assert all(row["physical_site_id"] == "unknown" for row in records)
    assert all(row["deployment_id"] == "unknown" for row in records)


def test_replay_is_identical_and_existing_outputs_cannot_be_replaced(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    build_design(config, census, annotation, first)
    build_design(config, census, annotation, second)
    assert all(path.read_bytes() == (second / path.name).read_bytes() for path in first.iterdir())
    with pytest.raises(FileExistsError):
        build_design(config, census, annotation, first)


def test_sealed_values_in_input_are_refused_before_any_output(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    path = census / "rows.json"
    rows = json.loads(path.read_text())
    rows.append({"event_id": "c", "role": "sealed_evaluation", "source_id": "source-c"})
    path.write_text(json.dumps(rows))
    with pytest.raises(DesignError, match="sealed row or link"):
        build_design(config, census, annotation, tmp_path / "design")
    assert not (tmp_path / "design").exists()


def test_source_count_mismatch_is_refused(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    path = census / "census.json"
    pages = json.loads(path.read_text())
    pages[0]["arrival_tables"][0]["rows_with_both_values"] += 1
    path.write_text(json.dumps(pages))
    with pytest.raises(DesignError, match="presence accounting mismatch"):
        build_design(config, census, annotation, tmp_path / "design")


def test_multiple_codes_on_one_row_are_an_ambiguous_identity(tmp_path: Path) -> None:
    config, census, annotation = inputs(tmp_path)
    path = census / "links.json"
    links = json.loads(path.read_text())
    links.append({**links[0], "link_code": "other"})
    path.write_text(json.dumps(links))
    summary = build_design(config, census, annotation, tmp_path / "design")
    assert summary["source_rows_with_multiple_code_sensors"] == 1
    with (tmp_path / "design/code_incidence.csv").open(encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    assert {row["identity_tier"] for row in records if row["event_id"] == "a"} == {"ambiguous"}


def test_cli_uses_the_same_deterministic_builder(tmp_path: Path, capsys: Any) -> None:
    config, census, annotation = inputs(tmp_path)
    assert (
        main(
            [
                "--config",
                str(config),
                "--census",
                str(census),
                "--annotations",
                str(annotation),
                "--output",
                str(tmp_path / "design"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["source_pair_values"] == 1


def test_source_qualified_network_is_identified_separately(tmp_path: Path) -> None:
    from analysis.arrival.stations import geographic_signature, geographic_site_id

    config, census, annotation = inputs(tmp_path)
    crosswalk = reviewed_crosswalk(tmp_path, census)
    with crosswalk.open() as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        alternatives = json.loads(row["evidence"])
        for alternative in alternatives:
            header = alternative["headers"][0]
            header.update(provider="UHSLC", header_station_id="none")
            alternative.update(
                physical_site_id=geographic_site_id(header),
                identity_scope="source_qualified_geographic_site",
                identity_basis="exact_linked_header_name_code_coordinates",
                geographic_signature=geographic_signature(header),
                registry_id_checks=[],
            )
        row.update(
            physical_site_id=alternatives[0]["physical_site_id"],
            provider="UHSLC",
            provider_station_id="unknown",
            identity_scope="source_qualified_geographic_site",
            identity_basis="exact_linked_header_name_code_coordinates",
            evidence=json.dumps(alternatives),
        )
        row["identity_evidence_sha256"] = hashlib.sha256(row["evidence"].encode()).hexdigest()
    with crosswalk.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = build_design(config, census, annotation, tmp_path / "result", crosswalk=crosswalk)
    scopes = result["reviewed_identity_design"]["network_by_identity_scope"]
    assert set(scopes) == {"source_qualified_geographic_site"}
    assert scopes["source_qualified_geographic_site"]["sites"] == 1
    assert scopes["source_qualified_geographic_site"]["events"] == 2
    assert result["reviewed_identity_design"]["model_eligibility_assessed"] is False
