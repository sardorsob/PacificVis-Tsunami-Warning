"""Lossless source records, individual measurements and target-specific views."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from analysis.arrival.evidence import (
    Row,
    checked_path,
    development_reports,
    file_manifest,
    read_rows,
    require_development,
    sha256,
    verify_inputs,
    verify_product,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import stable_id, validate_members


def entity_id(event: str, site: str, family: str, definition: str, record: str) -> str:
    """Geographic grouping does not establish a common latent arrival or independence."""
    return stable_id("entity", event, site if site != "unknown" else record, family, definition)


def opportunity(record: str, event: str) -> Row:
    return {
        "opportunity_id": stable_id("opportunity", record),
        "source_record_id": record,
        "event_id": event,
        "opportunity_state": "documented_source_record",
        "reporting_state": "source_record_exists",
        "historical_operating_state": "unknown",
        "availability_interval": "unknown",
        "nonreport_or_nondetection": "unknown",
        "negative_observation": "False",
        "scope": "report_presence_only",
    }


def ncei_measurement(row: Row, site: str, lineage: str) -> Row:
    match: dict[str, Any] = json.loads(row["event_match_json"])
    native: dict[str, Any] = json.loads(row["raw_record_json"])
    rid = row["source_record_id"]
    return {
        "observation_id": stable_id("observation", rid, "reported_initial_wave"),
        "source_record_id": rid,
        "event_id": row["development_event_id"],
        "physical_site_id": site,
        "measurement_family": row["measurement_family"],
        "arrival_definition": "source_reported_initial_wave",
        "entity_cluster_id": entity_id(
            row["development_event_id"],
            site,
            row["measurement_family"],
            "reported_initial_wave",
            rid,
        ),
        "lineage_id": lineage,
        "observed_utc": row["arrival_utc"],
        "duration_minutes": row["reported_duration_minutes"],
        "duration_state": row["travel_state"],
        "source_native_origin": match.get("ncei_origin_utc", "unknown"),
        "origin_difference_seconds": match.get("origin_difference_seconds", "unknown"),
        "origin_basis": "NCEI_native_not_USGS",
        "precision_seconds": "60",
        "first_motion": str(
            native.get("firstMotion") if native.get("firstMotion") is not None else "unknown"
        ),
        "peak_amplitude_native": str(
            native.get("runupHt") if native.get("runupHt") is not None else "unknown"
        ),
        "amplitude_units": "source_native_not_harmonized",
        "detection_state": "unknown",
        "model_eligible": "False",
        "physical_onset_validated": "False",
        "target_candidate": row["duration_candidate"],
        "raw_qualifiers_json": json.dumps(
            {k: native.get(k, "unknown") for k in ["doubtful", "publish", "firstMotion"]},
            sort_keys=True,
        ),
    }


def design_support(rows: list[Row]) -> dict[str, Any]:
    """Descriptive support; this is not a posterior effective sample size."""
    events = Counter(r["event_id"] for r in rows)
    sites: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["physical_site_id"] in {"", "unknown"}:
            continue
        sites[row["physical_site_id"]].add(row["event_id"])
    n = len(rows)
    return {
        "rows": n,
        "events": len(events),
        "sites": len(sites),
        "sites_with_at_least_events": {
            str(k): sum(len(v) >= k for v in sites.values()) for k in [2, 3, 5]
        },
        "rows_by_event": dict(sorted(events.items())),
        "inverse_simpson_event_concentration": n * n / sum(v * v for v in events.values())
        if n
        else 0,
        "concentration_is_posterior_ESS": False,
    }


def build_observations(
    inputs: Path, sites: Path, lineage: Path, calendars: Path, output: Path
) -> Path:
    document = verify_inputs(inputs)
    digest = sha256(inputs)
    for product, required in [
        (sites, ("site_links.csv.gz", "crosswalk.csv", "native_positions.csv.gz")),
        (lineage, ("lineage.csv.gz", "lineage_members.csv.gz")),
        (calendars, ("calendar_evidence.csv.gz", "forecast_instances.csv.gz")),
    ]:
        verify_product(product, required_files=required, inputs_sha256=digest)
    if output.exists():
        raise ValueError("output already exists")
    root = Path(document["root"])
    ledger_path = checked_path(root, "artifacts/provenance/paper-source-manifest-v2.csv")
    ledger_sha = "a6c4a2584899affd4e18f57ba0eb2c4c4c430735e805db877226c6795ee122ac"
    if sha256(ledger_path) != ledger_sha:
        raise ValueError("accepted source ledger changed")
    ledger = {r["source_id"]: r for r in read_rows(ledger_path)}
    ntwc = development_reports(document)
    ncei = read_rows(root / document["ncei"] / "observations.csv.gz")
    require_development(ncei, document["events"], "development_event_id")
    expected = {r["report_id"] for r in ntwc} | {r["source_record_id"] for r in ncei}
    links = read_rows(sites / "site_links.csv.gz")
    validate_members(links, expected)
    site_by_id = {r["source_record_id"]: r for r in links}
    members = read_rows(lineage / "lineage_members.csv.gz")
    validate_members(members, expected)
    ancestry = {r["source_record_id"]: r["lineage_id"] for r in members}
    source_records: list[Row] = []
    observations: list[Row] = []
    pairs: list[Row] = []
    dispositions: list[Row] = []
    opportunities: list[Row] = []
    for source, rows in [("NTWC", ntwc), ("NCEI", ncei)]:
        for row in rows:
            rid = row["report_id"] if source == "NTWC" else row["source_record_id"]
            event = row["event_id"] if source == "NTWC" else row["development_event_id"]
            site = site_by_id[rid]["physical_site_id"]
            source_records.append(
                {
                    "source_record_id": rid,
                    "source_family": source,
                    "event_id": event,
                    "source_id": row["source_id"],
                    "source_sha256": row["source_sha256"],
                    "raw_locator": rid if source == "NTWC" else row["source_row_number"],
                    "raw_asset_path": row.get("raw_path", ledger[row["source_id"]]["local_path"]),
                    "native_record_json": json.dumps(row, sort_keys=True, ensure_ascii=False),
                    "parsing_state": row.get("structural_status", "retained_native_source_row"),
                    "model_eligible": "False",
                }
            )
            opportunities.append(opportunity(rid, event))
            if source == "NCEI":
                observations.append(ncei_measurement(row, site, ancestry[rid]))
                reason = row["travel_state"] + ";calendar=" + row["arrival_calendar_state"]
            else:
                raw: dict[str, Any] = json.loads(row["raw_row_json"])
                fields = raw.get("fields", {})
                utc = row["observed_utc"] or "unknown"
                duration = "unknown"
                if utc != "unknown":
                    observed = datetime.fromisoformat(utc.replace("Z", "+00:00"))
                    origin = datetime.fromisoformat(
                        document["events"][event]["usgs_time"].replace("Z", "+00:00")
                    )
                    duration = str((observed - origin).total_seconds() / 60)
                oid = stable_id("observation", rid, "reported_observed_arrival")
                observations.append(
                    {
                        "observation_id": oid,
                        "source_record_id": rid,
                        "event_id": event,
                        "physical_site_id": site,
                        "measurement_family": "reported_water_level_unknown_sensor",
                        "arrival_definition": "NTWC_reported_observed_arrival",
                        "entity_cluster_id": entity_id(
                            event, site, "NTWC_reported", "observed_arrival", rid
                        ),
                        "lineage_id": ancestry[rid],
                        "observed_utc": utc,
                        "duration_minutes": duration,
                        "duration_state": row["observed_state"],
                        "source_native_origin": "unknown",
                        "origin_difference_seconds": "unknown",
                        "origin_basis": "reviewed_USGS_reference_not_original_prediction_origin",
                        "precision_seconds": row["reported_precision_seconds"],
                        "first_motion": fields.get("initial_motion", "unknown"),
                        "peak_amplitude_native": fields.get("peak_amplitude", "unknown"),
                        "amplitude_units": "source_native_not_harmonized",
                        "detection_state": "unknown",
                        "model_eligible": "False",
                        "physical_onset_validated": "False",
                        "target_candidate": "see_target_eligibility",
                        "raw_qualifiers_json": row["reason_codes"],
                    }
                )
                if row["disposition"] == "exact_reported_pair":
                    estimate = datetime.fromisoformat(row["estimated_utc"].replace("Z", "+00:00"))
                    observed = datetime.fromisoformat(row["observed_utc"].replace("Z", "+00:00"))
                    pairs.append(
                        {
                            "pair_id": stable_id("original-pair", rid),
                            "source_record_id": rid,
                            "event_id": event,
                            "physical_site_id": site,
                            "observation_id": oid,
                            "forecast_instance_id": stable_id("forecast", rid, "estimate_cell"),
                            "estimated_utc": row["estimated_utc"],
                            "observed_utc": row["observed_utc"],
                            "estimated_minus_observed_seconds": str(
                                (estimate - observed).total_seconds()
                            ),
                            "compatibility": "same_reported_table_pair",
                            "original_source_instance": row["source_id"],
                            "target_version": "reported_absolute_difference_v1",
                            "model_eligible": "False",
                        }
                    )
                reason = row["disposition"]
            dispositions.append(
                {
                    "candidate_id": rid,
                    "candidate_kind": "source_record",
                    "event_id": event,
                    "terminal_disposition": "retained_individual_measurement",
                    "reason": reason,
                    "geography_state": site_by_id[rid]["decision"],
                    "model_eligible": "False",
                }
            )
    targets = development_reports(document, targets=True)
    for row in targets:
        link = site_by_id[row["report_id"]]
        reasons = json.loads(row["reason_codes"])
        if link["decision"] == "accepted":
            reasons = [r for r in reasons if r != "geographic_identity_unreviewed"]
            row["physical_site_id"] = link["physical_site_id"]
        row["reason_codes"] = json.dumps(reasons, separators=(",", ":"))
        row["eligible"] = str(not reasons)
    by_observation = {r["source_record_id"]: r for r in observations}
    t_obs = [
        by_observation[r["report_id"]]
        for r in targets
        if r["target_id"] == "T-OBS" and r["eligible"] == "True"
    ]
    t_cal = [
        r
        for r in pairs
        if any(
            t["report_id"] == r["source_record_id"]
            and t["target_id"] == "T-CAL"
            and t["eligible"] == "True"
            for t in targets
        )
    ]
    native = [r for r in observations if r.get("target_candidate") == "True"]
    tables = {
        "source_records": source_records,
        "observations": observations,
        "pair_members": pairs,
        "opportunities": opportunities,
        "dispositions": dispositions,
        "target_eligibility": targets,
        "site_links": links,
        "T-OBS": t_obs,
        "T-CAL": t_cal,
        "NCEI-native-duration": native,
    }
    for name, rows in tables.items():
        write_rows(output / (name + ".csv.gz"), rows)
    for product, names in [
        (lineage, ["lineage", "lineage_members", "references", "statements"]),
        (calendars, ["calendar_evidence", "calendar_backtest", "forecast_instances"]),
    ]:
        for name in names:
            (output / (name + ".csv.gz")).write_bytes((product / (name + ".csv.gz")).read_bytes())
    positions = {r["id"]: r for r in read_rows(sites / "native_positions.csv.gz")}
    for row in read_rows(sites / "crosswalk.csv"):
        if row["review_status"] != "independently_reviewed":
            continue
        alt = json.loads(row["evidence"])[0]
        if alt["headers"]:
            header = alt["headers"][0]
            positions[row["report_id"]] = {
                "latitude": str(header["latitude"]),
                "longitude": str(header["longitude"]),
            }
    site_rows: dict[str, Row] = {}
    for link in sorted(links, key=lambda r: r["source_record_id"]):
        sid = link["physical_site_id"]
        if sid == "unknown":
            continue
        position = positions.get(link["source_record_id"], {})
        site_rows.setdefault(
            sid,
            {
                "physical_site_id": sid,
                "deployment_id": "unknown",
                "latitude": position.get("latitude", "unknown"),
                "longitude": position.get("longitude", "unknown"),
                "coordinate_crs": "unknown",
                "coordinate_accuracy": "unknown",
                "deployment_continuity": "unknown",
                "coordinate_evidence_source_record_id": link["source_record_id"],
                "identity_scope": link["decision"],
            },
        )
    write_rows(output / "sites.csv.gz", list(site_rows.values()))
    (output / "crosswalk.csv").write_bytes((sites / "crosswalk.csv").read_bytes())
    missingness: list[Row] = []
    for source in ["NTWC", "NCEI"]:
        group = [r for r in source_records if r["source_family"] == source]
        for event in sorted({r["event_id"] for r in group}):
            selected = [r for r in group if r["event_id"] == event]
            observed = [by_observation[r["source_record_id"]] for r in selected]
            missingness.append(
                {
                    "source_family": source,
                    "event_id": event,
                    "era": document["events"][event]["usgs_time"][:4],
                    "denominator": str(len(selected)),
                    "unknown_full_arrival_utc": str(
                        sum(r["observed_utc"] == "unknown" for r in observed)
                    ),
                    "unknown_duration": str(
                        sum(r["duration_minutes"] == "unknown" for r in observed)
                    ),
                    "unknown_geography": str(
                        sum(r["physical_site_id"] == "unknown" for r in observed)
                    ),
                    "interpretation": "descriptive_association_not_MCAR_MAR_MNAR_identification",
                }
            )
    write_rows(output / "missingness.csv.gz", missingness)
    write_json(
        output / "design_summary.json",
        {
            "source_records": len(source_records),
            "source_counts": dict(Counter(r["source_family"] for r in source_records)),
            "original_exact_pairs": len(pairs),
            "targets": {
                "T-OBS": design_support(t_obs),
                "T-CAL": design_support(t_cal),
                "NCEI-native-duration": design_support(native),
            },
            "model_eligible": False,
            "physical_onset_validated": False,
            "Cartesian_negative_observations": 0,
            "missingness_mechanism": "not_identified_from_observed_data",
            "unknown_lineage_primary_records": len(observations),
            "source_origin_differences_seconds": dict(
                Counter(r["origin_difference_seconds"] for r in observations)
            ),
        },
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": "arrival_observations_v1",
            "inputs_sha256": digest,
            "stage_inputs": {
                "source_ledger": ledger_sha,
                "sites": sha256(sites / "manifest.json"),
                "lineage": sha256(lineage / "manifest.json"),
                "calendars": sha256(calendars / "manifest.json"),
            },
            "files": file_manifest(output),
        },
    )
    return output / "manifest.json"
