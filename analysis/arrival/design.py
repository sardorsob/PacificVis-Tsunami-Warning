"""Describe development support and archive-code repetition before site matching.

Source-value presence is not a validated timestamp. Archive codes are identifiers
from filenames, not proof of a common physical station or deployment.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

from analysis.arrival.stations import StationError, validate_reviewed_site_evidence
from pipeline.ntwc_archive import arrival_value_flags


class DesignError(ValueError):
    """The design inputs conflict with their metadata/role contract."""


def _read_records(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(
        not isinstance(row, dict) for row in cast(list[Any], value)
    ):
        raise DesignError(f"expected a JSON record list: {path}")
    return cast(list[dict[str, Any]], value)


def _label(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _row_key(row: dict[str, Any]) -> tuple[str, int, int]:
    return row["event_id"], row["table_index"], row["row_index"]


def _magnitude_band(value: str) -> str:
    try:
        magnitude = float(value)
    except ValueError:
        return "unknown"
    if not math.isfinite(magnitude):
        return "unknown"
    if magnitude >= 8:
        return "ge_8.0"
    if magnitude >= 7.5:
        return "7.5_to_lt_8.0"
    if magnitude >= 7:
        return "7.0_to_lt_7.5"
    return "lt_7.0"


def _repeat_summary(groups: dict[str, set[str]]) -> dict[str, int | float]:
    counts = [len(events) for events in groups.values()]
    return {
        "unique_count": len(counts),
        "median_events": statistics.median(counts) if counts else 0,
        "in_at_least_5_events": sum(count >= 5 for count in counts),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def incidence_rank(edges: set[tuple[str, str]]) -> dict[str, Any]:
    """Exact rank of event/site indicator columns: active vertices minus components.

    This is a structural rank statement, not a claim that variance components or
    physical arrivals are identified. Each connected component needs a constraint.
    """
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for event, site in edges:
        a, b = ("event", event), ("site", site)
        adjacency[a].add(b)
        adjacency[b].add(a)
    pending = set(adjacency)
    components: list[dict[str, Any]] = []
    while pending:
        stack = [min(pending)]
        members: set[tuple[str, str]] = set()
        while stack:
            node = stack.pop()
            if node in members:
                continue
            members.add(node)
            stack.extend(adjacency[node] - members)
        pending -= members
        components.append(
            {
                "events": sorted(node[1] for node in members if node[0] == "event"),
                "sites": sorted(node[1] for node in members if node[0] == "site"),
            }
        )
    return {
        "events": len({event for event, _ in edges}),
        "sites": len({site for _, site in edges}),
        "edges": len(edges),
        "active_columns": len(adjacency),
        "components": len(components),
        "indicator_matrix_rank": len(adjacency) - len(components),
        "component_membership": components,
    }


def _reviewed_design(
    path: Path,
    source_rows: dict[tuple[str, int, int], dict[str, Any]],
    support: list[dict[str, Any]],
    development: set[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "event_id",
            "report_id",
            "role",
            "identity_tier",
            "physical_site_id",
            "event_site_identity_verified",
            "review_status",
            "evidence",
            "identity_evidence_sha256",
        }
        if not required <= set(reader.fieldnames or []):
            raise DesignError("reviewed crosswalk lacks report identity or review evidence")
        rows = list(reader)
    expected = {f"{eid}:{table}:{row}": value for (eid, table, row), value in source_rows.items()}
    if len(rows) != len(expected) or {row["report_id"] for row in rows} != set(expected):
        raise DesignError("crosswalk must contain each development report exactly once")
    accepted: list[dict[str, str]] = []
    for row in rows:
        original = expected[row["report_id"]]
        if (
            row["event_id"] not in development
            or row["role"] != "development"
            or row["event_id"] != original["event_id"]
        ):
            raise DesignError("crosswalk has reserved or mismatched event identity")
        if hashlib.sha256(row["evidence"].encode()).hexdigest() != row["identity_evidence_sha256"]:
            raise DesignError("crosswalk evidence digest mismatch")
        if row["review_status"] != "independently_reviewed":
            continue
        try:
            validate_reviewed_site_evidence(row)
        except StationError as error:
            raise DesignError(str(error)) from error
        if original["status"] != "accepted_source_row":
            raise DesignError("reviewed site has no accepted source report")
        accepted.append(row)
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    cadence_groups: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for row in accepted:
        grouped[(row["event_id"], row["physical_site_id"], row["identity_tier"])].append(row)
        for alternative in json.loads(row["evidence"]):
            for header in alternative.get("headers", []):
                cadence_groups[
                    (
                        str(header["header_date"])[:4],
                        str(header["provider"]),
                        str(header["cadence_value"]),
                        str(header["cadence_units"]),
                        str(header["units"]),
                    )
                ].add(str(header["source_id"]))
    incidence: list[dict[str, Any]] = []
    for (eid, site, tier), group in sorted(grouped.items()):
        flags = [arrival_value_flags(expected[row["report_id"]]["fields"]) for row in group]
        incidence.append(
            {
                "event_id": eid,
                "physical_site_id": site,
                "identity_tier": tier,
                "identity_scope": group[0].get("identity_scope", "authoritative_provider_site"),
                "identity_basis": group[0].get(
                    "identity_basis", "legacy_reviewed_provider_evidence"
                ),
                "source_reports": len(group),
                "explicit_pair_reports": sum(item["both_values"] for item in flags),
                "legacy_pair_reports": sum(
                    item["estimate_and_arrival_as_labeled_values"] for item in flags
                ),
                "report_ids": json.dumps(sorted(row["report_id"] for row in group)),
                "deployment_continuity_verified": False,
                "model_eligible": False,
            }
        )
    edges = {
        (row["event_id"], row["physical_site_id"])
        for row in incidence
        if row["explicit_pair_reports"]
    }
    all_sites = {site for _, site in edges}
    all_events = {event for event, _ in edges}
    rank = incidence_rank(edges)
    folds: list[dict[str, Any]] = []
    for kind, index, held_values in (("LOEO", 0, all_events), ("LOSO", 1, all_sites)):
        for held in sorted(held_values):
            training = {edge for edge in edges if edge[index] != held}
            train_rank = incidence_rank(training)
            folds.append(
                {
                    "fold": kind,
                    "held_out": held,
                    "held_out_edges": len(edges - training),
                    "training_edges": len(training),
                    "training_events": train_rank["events"],
                    "training_sites": train_rank["sites"],
                    "training_components": train_rank["components"],
                    "active_columns": train_rank["active_columns"],
                    "indicator_matrix_rank": train_rank["indicator_matrix_rank"],
                    "fixed_full_design_columns": rank["active_columns"],
                    "fixed_columns_nullity": rank["active_columns"]
                    - train_rank["indicator_matrix_rank"],
                    "unseen_events": json.dumps(
                        sorted(all_events - {event for event, _ in training})
                    ),
                    "unseen_sites": json.dumps(sorted(all_sites - {site for _, site in training})),
                }
            )
    degrees: list[dict[str, Any]] = [
        {
            "physical_site_id": site,
            "event_degree": len({event for event, linked in edges if linked == site}),
            "events": json.dumps(sorted(event for event, linked in edges if linked == site)),
        }
        for site in sorted(all_sites)
    ]
    for event in support:
        selected = [row for row in incidence if row["event_id"] == event["event_id"]]
        sites = {row["physical_site_id"] for row in selected}
        paired = {row["physical_site_id"] for row in selected if row["explicit_pair_reports"]}
        event.update(
            physical_site_count=len(sites),
            fit_tier_site_count=len(sites),
            reviewed_explicit_pair_sites=len(paired),
            stage_d_identity_support=len(paired) >= 5,
            model_eligible=False,
        )
    median_degree = (
        statistics.median(int(row["event_degree"]) for row in degrees) if degrees else None
    )
    pass_rates: list[dict[str, Any]] = []
    for grouping in ("magnitude_band", "cohort"):
        for value in sorted({row[grouping] for row in support}):
            selected = [row for row in support if row[grouping] == value]
            passed = sum(row["stage_d_identity_support"] for row in selected)
            pass_rates.append(
                {
                    "grouping": grouping,
                    "value": value,
                    "events": len(selected),
                    "identity_support_pass": passed,
                    "pass_rate": passed / len(selected),
                }
            )
    tables: dict[str, list[dict[str, Any]]] = {
        "reviewed_site_incidence": incidence,
        "site_degrees": degrees,
        "fold_rank": folds,
        "stage_d_pass_rates": pass_rates,
        "cadence_by_era": [
            {
                "year": key[0],
                "provider": key[1],
                "cadence_value": key[2],
                "cadence_units": key[3],
                "units": key[4],
                "header_assets": len(values),
            }
            for key, values in sorted(cadence_groups.items())
        ],
    }
    summary: dict[str, Any] = {
        "reviewed_site_reports": len(accepted),
        "explicit_pair_network": rank,
        "network_by_tier": {
            tier: incidence_rank(
                {
                    (row["event_id"], row["physical_site_id"])
                    for row in incidence
                    if row["identity_tier"] == tier and row["explicit_pair_reports"]
                }
            )
            for tier in ("header_exact", "registry_exact")
        },
        "network_by_identity_scope": {
            scope: incidence_rank(
                {
                    (row["event_id"], row["physical_site_id"])
                    for row in incidence
                    if row["identity_scope"] == scope and row["explicit_pair_reports"]
                }
            )
            for scope in sorted({row["identity_scope"] for row in incidence})
        },
        "median_site_event_degree": median_degree,
        "site_effect_disposition": "sensitivity_only_single_event_sites"
        if median_degree == 1
        else "not_identified_by_connectivity_alone"
        if median_degree
        else "no_reviewed_pair_network",
        "events_with_stage_d_identity_support": sum(
            row["stage_d_identity_support"] for row in support
        ),
        "model_eligibility_assessed": False,
        "interpretation": [
            "Ranks use distinct event/site edges with explicit source-pair values.",
            "The full indicator matrix has one event column and one site column per active level.",
            "Rank is active columns minus components; each component needs a constraint.",
            "LOEO/LOSO remove held-out groups; unseen groups need predictive integration.",
            "Unknown sites never merge. Legacy arrival labels are excluded from the network.",
            "Deployment continuity, physical onset and variance identification remain unproven.",
            "Source-qualified geographic groups are separate from authoritative provider IDs.",
            "Geographic grouping does not pool separate sensor observations.",
        ],
    }
    return tables, summary


def build_design(
    config: Path,
    census_dir: Path,
    annotations: Path,
    output: Path,
    *,
    crosswalk: Path | None = None,
) -> dict[str, Any]:
    """Write deterministic development-only support and code-incidence tables.

    Refuse sealed row/link contamination. Read census structural counts for all
    events, but expose event-level support and incidence only for development.
    Inputs are hashed into summary.json; output directories are never replaced.
    """
    if output.exists():
        raise FileExistsError(f"refusing to replace design directory: {output}")
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    events = cast(dict[str, dict[str, Any]], document.get("events", {}))
    by_id = {event["event_id"]: event for event in events.values()}
    if not events or len(by_id) != len(events):
        raise DesignError("config requires nonempty unique event IDs")
    if any(
        event.get("role") not in {"development", "sealed_evaluation"} for event in by_id.values()
    ):
        raise DesignError("invalid event role")
    development = {eid for eid, event in by_id.items() if event["role"] == "development"}
    with annotations.open(encoding="utf-8", newline="") as stream:
        annotation_rows = list(csv.DictReader(stream))
    required = {"event_id", "mechanism_class", "cohort", "citation"}
    if any(
        not required.issubset(row) or any(not row[key] for key in required)
        for row in annotation_rows
    ):
        raise DesignError("annotation rows require event_id, mechanism_class, cohort and citation")
    annotation_map = {row["event_id"]: row for row in annotation_rows}
    if len(annotation_map) != len(annotation_rows):
        raise DesignError("duplicate mechanism annotation")
    census = _read_records(census_dir / "census.json")
    rows = _read_records(census_dir / "rows.json")
    links = _read_records(census_dir / "links.json")
    if len(census) != len(by_id) or {row["event_id"] for row in census} != set(by_id):
        raise DesignError("census and config event sets differ")
    for row in census + rows + links:
        eid = row.get("event_id")
        if eid not in by_id or row.get("role") != by_id[eid]["role"]:
            raise DesignError("census identity or role disagrees with config")
        if row.get("source_id") != by_id[eid]["archive_source_id"]:
            raise DesignError("census source ID disagrees with config")
    if any(row["event_id"] not in development for row in rows + links):
        raise DesignError("sealed row or link values must not enter design inputs")
    row_map = {_row_key(row): row for row in rows}
    if len(row_map) != len(rows):
        raise DesignError("duplicate source row identity")
    event_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        event_rows[row["event_id"]].append(row)
        if row["status"] == "accepted_source_row":
            label = _label(row["fields"].get("location", ""))
            if label:
                labels[label].add(row["event_id"])
    census_by_id = {row["event_id"]: row for row in census}
    support: list[dict[str, Any]] = []
    for eid in sorted(development):
        event = by_id[eid]
        annotation = annotation_map.get(eid, {})
        states = Counter(row["status"] for row in event_rows[eid])
        presence: Counter[str] = Counter()
        for row in event_rows[eid]:
            if row["status"] == "accepted_source_row":
                presence.update(
                    {key: int(value) for key, value in arrival_value_flags(row["fields"]).items()}
                )
        tables = census_by_id[eid]["arrival_tables"]
        for key in arrival_value_flags({}):
            if sum(table[f"rows_with_{key}"] for table in tables) != presence[key]:
                raise DesignError(f"census presence accounting mismatch: {eid}/{key}")
        if sum(table["rows_after_header"] for table in tables) != len(event_rows[eid]):
            raise DesignError(f"census row accounting mismatch: {eid}")
        source_pairs = presence["both_values"] + presence["estimate_and_arrival_as_labeled_values"]
        support.append(
            {
                "event_id": eid,
                "role": "development",
                "name": event.get("name", "unknown"),
                "region": event.get("region", "unknown"),
                "magnitude": event.get("usgs_mag", "unknown"),
                "magnitude_type": event.get("usgs_magType", "unknown"),
                "magnitude_band": _magnitude_band(str(event.get("usgs_mag", "unknown"))),
                "mechanism_class": annotation.get("mechanism_class", "unknown"),
                "cohort": annotation.get("cohort", "unknown"),
                "mechanism_citation": annotation.get("citation", "unknown"),
                "census_status": census_by_id[eid]["status"],
                "source_rows": len(event_rows[eid]),
                "accepted_source_rows": states["accepted_source_row"],
                "blank_rows": states["blank_row"],
                "rejected_rows": sum(
                    count for key, count in states.items() if key.startswith("rejected")
                ),
                "estimate_values": presence["estimate_value"],
                "explicit_observed_values": presence["observed_value"],
                "explicit_both_values": presence["both_values"],
                "legacy_arrival_values": presence["arrival_as_labeled_value"],
                "legacy_both_values": presence["estimate_and_arrival_as_labeled_values"],
                "source_pair_values": source_pairs,
                "at_least_5_source_pairs": source_pairs >= 5,
                "fit_tier_site_count": "unknown",
                "physical_site_count": "unknown",
            }
        )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    row_codes: dict[tuple[str, int, int], set[tuple[str, str]]] = defaultdict(set)
    code_events: dict[str, set[str]] = defaultdict(set)
    code_sensor_events: dict[str, set[str]] = defaultdict(set)
    identity_states: Counter[str] = Counter()
    for link in links:
        key = _row_key(link)
        if key not in row_map or row_map[key]["status"] != "accepted_source_row":
            raise DesignError("link has no accepted source row")
        identity_states[link["link_identity_status"]] += 1
        code, sensor = link["link_code"], link["link_sensor"]
        if link["status"] != "safe_archive_link" or code == "unknown":
            continue
        grouped[(link["event_id"], code, sensor)].append(link)
        row_codes[key].add((code, sensor))
        code_events[code].add(link["event_id"])
        code_sensor_events[f"{code}:{sensor}"].add(link["event_id"])
    incidence: list[dict[str, Any]] = []
    for (eid, code, sensor), group in sorted(grouped.items()):
        keys = {_row_key(link) for link in group}
        pairs = [arrival_value_flags(row_map[key]["fields"]) for key in keys]
        ambiguous = sum(len(row_codes[key]) > 1 for key in keys)
        incidence.append(
            {
                "event_id": eid,
                "role": "development",
                "link_code": code,
                "link_sensor": sensor,
                "identity_tier": "ambiguous" if ambiguous else "archive_code",
                "physical_site_id": "unknown",
                "deployment_id": "unknown",
                "source_row_count": len(keys),
                "link_count": len(group),
                "explicit_both_values": sum(item["both_values"] for item in pairs),
                "legacy_both_values": sum(
                    item["estimate_and_arrival_as_labeled_values"] for item in pairs
                ),
                "ambiguous_source_rows": ambiguous,
                "source_row_refs": json.dumps(sorted([key[1], key[2]] for key in keys)),
                "location_labels": json.dumps(
                    sorted({_label(link["location_text"]) for link in group})
                ),
                "link_days": json.dumps(sorted({link["link_day"] for link in group})),
                "link_years": json.dumps(sorted({link["link_year"] for link in group})),
            }
        )
    pair_counts = sorted((row["source_pair_values"] for row in support), reverse=True)
    total_pairs = sum(pair_counts)
    bands: dict[str, dict[str, int]] = {}
    for band in sorted({row["magnitude_band"] for row in support}):
        subset = [row for row in support if row["magnitude_band"] == band]
        bands[band] = {
            "events": len(subset),
            "at_least_5_source_pairs": sum(row["at_least_5_source_pairs"] for row in subset),
        }
    inputs = {
        "config": config,
        "annotations": annotations,
        **{name: census_dir / f"{name}.json" for name in ("census", "rows", "links")},
    }
    reviewed_tables: dict[str, list[dict[str, Any]]] = {}
    reviewed_summary: dict[str, Any] | None = None
    if crosswalk:
        reviewed_tables, reviewed_summary = _reviewed_design(
            crosswalk, row_map, support, development
        )
        inputs["crosswalk"] = crosswalk
    summary: dict[str, Any] = {
        "schema_version": "arrival-design-v0",
        "development_events": len(development),
        "sealed_events_excluded": len(by_id) - len(development),
        "source_rows": len(rows),
        "explicit_both_values": sum(row["explicit_both_values"] for row in support),
        "legacy_both_values": sum(row["legacy_both_values"] for row in support),
        "source_pair_values": total_pairs,
        "events_by_minimum_source_pairs": {
            str(n): sum(count >= n for count in pair_counts) for n in (5, 10, 20, 50)
        },
        "top_5_event_source_pairs": sum(pair_counts[:5]),
        "top_5_event_source_pair_share": sum(pair_counts[:5]) / total_pairs
        if total_pairs
        else None,
        "magnitude_support": bands,
        "location_labels": _repeat_summary(labels),
        "archive_codes": _repeat_summary(code_events),
        "archive_code_sensor_pairs": _repeat_summary(code_sensor_events),
        "link_identity_status_counts": dict(sorted(identity_states.items())),
        "source_rows_with_multiple_code_sensors": sum(
            len(value) > 1 for value in row_codes.values()
        ),
        "input_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in sorted(inputs.items())
        },
        "interpretation": [
            "Value presence does not validate timestamps, physical onsets or model eligibility.",
            "Source pairs combine explicit Observed/Estimated and ambiguous legacy Arrival/ETA "
            "labels.",
            "Archive-code repetition does not establish shared physical sites or deployments.",
            "No fit-tier identity is assigned before the independently reviewed station crosswalk.",
            "Link incidence uses safe archive URLs only; repeated day links count once per "
            "source row.",
        ],
    }
    if reviewed_summary is not None:
        summary["schema_version"] = "arrival-design-reviewed-v1"
        summary["reviewed_identity_design"] = reviewed_summary
    output.mkdir(parents=True, exist_ok=False)
    _write_csv(output / "event_support.csv", support, list(support[0]) if support else ["event_id"])
    _write_csv(
        output / "code_incidence.csv",
        incidence,
        list(incidence[0]) if incidence else ["event_id", "link_code", "link_sensor"],
    )
    for name, records in reviewed_tables.items():
        _write_csv(output / f"{name}.csv", records, list(records[0]) if records else ["empty"])
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
