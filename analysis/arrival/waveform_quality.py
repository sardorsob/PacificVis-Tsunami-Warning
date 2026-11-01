"""Structural audit of native waveforms; no interpolation, onset picking or detiding."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from analysis.arrival.evidence import (
    Row,
    file_manifest,
    read_rows,
    require_development,
    sha256,
    verify_inputs,
    verify_product,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import stable_id

VALID_TIMES = {
    "reported_utc",
    "epoch_calendar_agree",
    "epoch_calendar_minute_agree",
    "header_day_end_boundary",
}
PACKET_FIELDS = (
    "source_row_number",
    "timestamp_utc",
    "timestamp_state",
    "raw_timestamp",
    "raw_epoch",
    "raw_value",
    "numeric_value",
    "value_state",
    "units",
    "vertical_datum",
    "qc_state",
    "qc_json",
    "duplicate_timestamp",
)
SEED = "arrival-structural-audit-v2"


def strip_rows(rows: list[Row]) -> list[Row]:
    """Whitelist waveform fields, excluding all report, estimate and event IDs."""
    return [{key: row.get(key, "unknown") for key in PACKET_FIELDS} for row in rows]


def audit_rows(rows: list[Row], cadence: float | None) -> Row:
    times: dict[str, set[str]] = defaultdict(set)
    finite = 0
    invalid_times = 0
    for row in rows:
        try:
            if row["timestamp_state"] not in VALID_TIMES:
                raise ValueError("unusable native time")
            datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            times[row["timestamp_utc"]].add(row["numeric_value"])
        except (KeyError, ValueError):
            invalid_times += 1
        if row.get("value_state") == "finite_numeric":
            if not math.isfinite(float(row["numeric_value"])):
                raise ValueError("finite flag conflicts with source value")
            finite += 1
    stamps = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times)
    deltas = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    grid_missing = "unknown"
    if (
        cadence
        and len(stamps) > 1
        and all(abs(d / cadence - round(d / cadence)) < 1e-8 for d in deltas)
    ):
        grid_missing = str(
            round((stamps[-1] - stamps[0]).total_seconds() / cadence) + 1 - len(stamps)
        )
    return {
        "sample_rows": str(len(rows)),
        "finite_numeric_rows": str(finite),
        "invalid_timestamp_rows": str(invalid_times),
        "unique_valid_timestamps": str(len(times)),
        "non_numeric_rows": str(len(rows) - finite),
        "duplicate_timestamp_excess": str(len(rows) - invalid_times - len(times)),
        "conflicting_duplicate_timestamps": str(sum(len(v) > 1 for v in times.values())),
        "observed_delta_seconds_json": json.dumps(dict(sorted(Counter(deltas).items()))),
        "gaps_over_1_5_declared_cadence": str(sum(d > 1.5 * cadence for d in deltas))
        if cadence
        else "unknown",
        "expected_grid_missing": grid_missing,
        "expected_grid_scope": "between_first_last_valid_timestamp_only_when_aligned",
        "largest_valid_timestamp_gap_seconds": str(max(deltas)) if deltas else "unknown",
        "units_json": json.dumps(sorted({r.get("units", "unknown") for r in rows})),
        "datum_json": json.dumps(sorted({r.get("vertical_datum", "unknown") for r in rows})),
        "qc_states_json": json.dumps(
            dict(sorted(Counter(r.get("qc_state", "unknown") for r in rows).items()))
        ),
        "qc_passed": "unknown",
        "physical_onset_validated": "False",
        "model_eligible": "False",
        "interpolated_rows": "0",
        "detided_by_this_pipeline": "False",
    }


def _cadence(source: dict[str, Any]) -> float | None:
    try:
        value = float(source.get("declared_cadence_seconds", "unknown"))
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _key(source: dict[str, Any]) -> tuple[str, ...]:
    metadata = source.get("source_metadata", {})
    return tuple(
        str(x)
        for x in [
            source["event_id"],
            source.get("provider", "unknown"),
            source.get("station_key", source["source_id"]),
            source.get("sensor", "unknown"),
            source["purpose"],
            source.get("units", "unknown"),
            source.get("vertical_datum", "unknown"),
            metadata.get("processing", "provider_product_unknown_processing"),
            source.get("declared_cadence_seconds", "unknown"),
        ]
    )


def select_cases(candidates: list[Row], events: dict[str, Any], count: int) -> list[Row]:
    """Balance metadata and structural coverage, independent of all arrival fields."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    result: list[Row] = []
    remaining = sorted(candidates, key=lambda r: r["case_id"])
    while remaining and len(result) < count:

        def strata(row: Row) -> list[str]:
            event = events[row["event_id"]]
            return [
                row["event_id"],
                event.get("region", "unknown"),
                str(int(event["usgs_time"][:4]) // 5),
                row["provider"],
                row["family"],
                row["cadence"],
                row["coverage_class"],
            ]

        def score(row: Row) -> tuple[Any, ...]:
            return (
                *[counts[str(i)][s] for i, s in enumerate(strata(row))],
                hashlib.sha256((SEED + row["case_id"]).encode()).hexdigest(),
            )

        chosen = min(remaining, key=score)
        remaining.remove(chosen)
        result.append(chosen)
        for i, s in enumerate(strata(chosen)):
            counts[str(i)][s] += 1
    return result


def build_quality(inputs: Path, observations: Path, output: Path) -> Path:
    document = verify_inputs(inputs)
    verify_product(
        observations,
        required_files=("site_links.csv.gz", "crosswalk.csv"),
        inputs_sha256=sha256(inputs),
    )
    if output.exists():
        raise ValueError("output already exists")
    root = Path(document["root"])
    wave = root / document["waveforms"]
    manifest = json.loads((wave / "manifest.json").read_text())
    sources: list[dict[str, Any]] = manifest["sources"]
    require_development(
        [{"event_id": s["event_id"]} for s in sources if "event_id" in s],
        document["events"],
        "event_id",
    )
    pins = {r["path"]: r["sha256"] for r in document["files"]}
    links = read_rows(observations / "site_links.csv.gz")
    accepted_sites = {
        (r["event_id"], r["physical_site_id"]) for r in links if r["decision"] == "accepted"
    }
    header_sites: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in read_rows(observations / "crosswalk.csv"):
        if row["review_status"] != "independently_reviewed":
            continue
        for alternative in json.loads(row["evidence"]):
            for header in alternative["headers"]:
                header_sites[(row["event_id"], header["sha256"])].add(row["physical_site_id"])
    coverage: list[Row] = []
    dispositions: list[Row] = []
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        if "event_id" not in source:
            if source["processing_status"] != "outside_observation_scope":
                raise ValueError("eventless waveform cannot enter observation audit")
            dispositions.append(
                {
                    "candidate_id": source["source_id"],
                    "event_id": "unknown",
                    "candidate_kind": "waveform_source",
                    "terminal_disposition": source["processing_status"],
                    "acquisition_status": source["acquisition_status"],
                    "reason": source["reason"],
                }
            )
            continue
        grouped[_key(source)].append(source)
    cases: list[Row] = []
    overlap: list[Row] = []
    for key, group in sorted(grouped.items()):
        seen: dict[str, set[str]] = defaultdict(set)
        repeated = 0
        group_rows = 0
        group_usable = 0
        normalized: list[dict[str, Any]] = []
        for source in sorted(group, key=lambda s: s["source_id"]):
            sid = source["source_id"]
            dispositions.append(
                {
                    "candidate_id": sid,
                    "event_id": source["event_id"],
                    "candidate_kind": "waveform_source",
                    "terminal_disposition": source["processing_status"],
                    "acquisition_status": source["acquisition_status"],
                    "reason": source["reason"],
                }
            )
            if source["processing_status"] != "normalized_source_samples":
                continue
            path = wave / source["output_path"]
            relative = str(path.relative_to(root))
            if (
                pins.get(relative) != source["output_sha256"]
                or sha256(path) != source["output_sha256"]
            ):
                raise ValueError("unpinned or changed waveform")
            rows = read_rows(path)
            if any(r["event_id"] != source["event_id"] or r["source_id"] != sid for r in rows):
                raise ValueError("waveform row identity conflict")
            quality = audit_rows(rows, _cadence(source))
            origin = datetime.fromisoformat(
                document["events"][source["event_id"]]["usgs_time"].replace("Z", "+00:00")
            )
            supported: dict[str, set[str]] = {"baseline": set(), "post_origin": set()}
            if source["purpose"] == "event_window":
                for row in rows:
                    if (
                        row["timestamp_state"] in VALID_TIMES
                        and row["value_state"] == "finite_numeric"
                    ):
                        hour = (
                            datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
                            - origin
                        ).total_seconds() / 3600
                        if -6 <= hour < 0:
                            supported["baseline"].add(row["timestamp_utc"])
                        elif 0 <= hour < 30:
                            supported["post_origin"].add(row["timestamp_utc"])
            if len(rows) != source["source_rows"]:
                raise ValueError("waveform row count conflict")
            for row in rows:
                if row["timestamp_state"] in VALID_TIMES:
                    stamp = row["timestamp_utc"]
                    repeated += bool(seen[stamp])
                    seen[stamp].add(row["numeric_value"])
            site = source.get("display_station_key", "unknown")
            matched = (source["event_id"], site) in accepted_sites
            header_matches = header_sites.get((source["event_id"], source["source_sha256"]), set())
            if not matched and len(header_matches) == 1:
                site = next(iter(header_matches))
                matched = True
            coverage.append(
                {
                    **quality,
                    "source_id": sid,
                    "event_id": source["event_id"],
                    "asset_path": relative,
                    "asset_sha256": source["output_sha256"],
                    "source_sha256": source["source_sha256"],
                    "provider": source.get("provider", "unknown"),
                    "physical_site_id": site if matched else "unknown",
                    "site_match": str(matched),
                    "provider_station_id": str(source.get("provider_station_id", "unknown")),
                    "deployment_id": "unknown",
                    "purpose": source["purpose"],
                    "provider_processing": source.get("source_metadata", {}).get(
                        "processing", "unknown"
                    ),
                    "declared_cadence_seconds": str(
                        source.get("declared_cadence_seconds", "unknown")
                    ),
                    "first_timestamp_utc": source["first_timestamp_utc"],
                    "last_timestamp_utc": source["last_timestamp_utc"],
                    "baseline_coverage": str(len(supported["baseline"]))
                    if source["purpose"] == "event_window"
                    else "unknown",
                    "baseline_coverage_units": "unique_finite_samples_in_origin_minus6h_to_origin",
                    "post_origin_coverage_samples": str(len(supported["post_origin"]))
                    if source["purpose"] == "event_window"
                    else "unknown",
                    "post_origin_window_hours": "0_to30_not_actual_arrival_window",
                    "arrival_window_coverage": "unknown_no_pick_used",
                    "method_eligibility": "structural_review_only",
                    "known_numeric_sentinels": "unknown_no_silent_removal",
                }
            )
            normalized.append(source)
            group_rows += len(rows)
            group_usable += int(quality["finite_numeric_rows"])
        if not normalized:
            continue
        case = stable_id("case", *key)
        overlap.append(
            {
                "case_id": case,
                "assets": str(len(normalized)),
                "repeated_timestamp_rows": str(repeated),
                "conflicting_timestamps": str(sum(len(v) > 1 for v in seen.values())),
                "same_units_datum_processing_only": "True",
                "resolved_by_averaging": "False",
            }
        )
        if group_usable and key[4] in {"event_window", "quiet_control"}:
            cases.append(
                {
                    "case_id": case,
                    "event_id": key[0],
                    "provider": key[1],
                    "purpose": key[4],
                    "family": str(
                        normalized[0]
                        .get("source_metadata", {})
                        .get("measurement_system", "unknown")
                    ),
                    "cadence": key[-1],
                    "coverage_class": "all_finite"
                    if group_usable == group_rows
                    else "has_missing_values",
                    "key_json": json.dumps(key),
                    "source_ids_json": json.dumps(sorted(s["source_id"] for s in normalized)),
                }
            )
    events = document["events"]
    chosen = select_cases([r for r in cases if r["purpose"] == "event_window"], events, 60)
    controls = select_cases([r for r in cases if r["purpose"] == "quiet_control"], events, 9)
    # Freeze the selection before emitting any stripped trace packet.
    write_rows(output / "selection.csv.gz", chosen + controls)
    write_json(
        output / "recipe.json",
        {
            "seed": SEED,
            "event_cases": len(chosen),
            "quiet_controls": len(controls),
            "requested_event_cases": 60,
            "requested_quiet_controls": 9,
            "selection_sha256": sha256(output / "selection.csv.gz"),
            "report_or_ETA_selection_fields": False,
            "review_scope": "nonexpert_structural_descriptive",
            "expert_ground_truth": False,
            "tide_removal": "disabled: no new compatible harmonic method established",
            "physical_onset_validated": False,
            "blinding_claim": False,
        },
    )
    by_id = {s["source_id"]: s for s in sources}
    for case in chosen + controls:
        for index, sid in enumerate(json.loads(case["source_ids_json"])):
            source = by_id[sid]
            write_rows(
                output / "packet" / case["case_id"] / f"trace-{index:03d}.csv.gz",
                strip_rows(read_rows(wave / source["output_path"])),
                columns=list(PACKET_FIELDS),
            )
    for name, rows in [
        ("waveform_coverage", coverage),
        ("waveform_dispositions", dispositions),
        ("overlapping_assets", overlap),
    ]:
        write_rows(output / (name + ".csv.gz"), rows)
    write_json(
        output / "summary.json",
        {
            "source_outcomes": len(sources),
            "normalized_assets": len(coverage),
            "native_sample_rows": sum(int(r["sample_rows"]) for r in coverage),
            "finite_numeric_rows": sum(int(r["finite_numeric_rows"]) for r in coverage),
            "invalid_timestamp_rows": sum(int(r["invalid_timestamp_rows"]) for r in coverage),
            "normalized_assets_matched_to_reviewed_site": sum(
                r["site_match"] == "True" for r in coverage
            ),
            "within_asset_conflicting_duplicate_timestamps": sum(
                int(r["conflicting_duplicate_timestamps"]) for r in coverage
            ),
            "source_dispositions": dict(Counter(r["terminal_disposition"] for r in dispositions)),
            "event_packet_cases": len(chosen),
            "quiet_control_cases": len(controls),
            "physical_onsets_validated": 0,
            "waveform_rows_modified": 0,
            "QC_pass_claimed": False,
        },
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": "arrival_waveform_quality_v1",
            "inputs_sha256": sha256(inputs),
            "observations_sha256": sha256(observations / "manifest.json"),
            "files": file_manifest(output),
        },
    )
    return output / "manifest.json"
