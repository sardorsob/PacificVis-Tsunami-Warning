"""Pinned exploration-only model views; immutable source rows and explicit exclusions."""

from __future__ import annotations

import json
import math
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from analysis.arrival.evidence import Row, checked_path, read_rows, sha256, write_json, write_rows

VREF_KM_MIN = math.sqrt(9.80665 * 4000) * 60 / 1000
BASE = "artifacts/eda/arrival-timing/results/exploration/"
TARGET_FILES = {
    "NCEI-native-duration": BASE + "data-integrity-and-response-records/"
    "ncei-native-travel-duration-analysis-records.csv",
    "T-OBS": BASE + "data-integrity-and-response-records/"
    "ntwc-reported-travel-duration-analysis-records.csv",
    "T-CAL": BASE + "estimated-minus-observed-timing-distributions/"
    "estimated-minus-observed-time-difference-versus-source-station-distance.csv",
}
SPLIT = "config/arrival-timing-exploration-confirmation-split.toml"
METADATA = "artifacts/eda/arrival-timing/frozen-inputs/development-event-metadata.csv"
SOURCE_MANIFEST = "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
CONTRACT = "config/arrival-model-contract-v1.toml"
CONVENTIONS = {
    "schema_version": "arrival_model_contract_v1",
    "response_units": "minutes",
    "distance_units": "km",
    "predictor": "ln(distance_km/1000)",
    "site_key": "physical_site_id",
    "evidence_policy": "exclude_all_unresolved_repeated_event_site_rows",
    "observation_rule": "native_reported_point_no_invented_accuracy_bounds",
    "primary_score": "equal_event_mean_joint_log_predictive_density_per_record",
    "reference_depth_m": 4000,
    "reference_g_m_s2": 9.80665,
    "near_field_km": 500,
    "target_conditioning": "archive_reporting_and_target_eligibility",
    "cross_source_policy": "separate_likelihoods_never_independent_pool",
    "shared_clock_policy": "T-OBS_and_T-CAL_share_O_not_independent",
    "definition_conflict_policy": "retain_native_reports_primary_exclude_in_MS5_sensitivity",
    "measurement_gate": "MS1_observation_rule_before_scientific_fit",
    "l3_estimated_travel_predictor": "deferred_until_origin_product_cutoff_verified",
    "score_formula": "mean_e(log_p(y_e_given_training_minus_sequence_X_e)/n_e)",
    "score_units": "nats_per_record",
    "score_measure": "native_minutes_density_with_duration_log_Jacobian",
    "validation_scope": "new_source_sequences_at_supported_station_geography",
    "confirmation_policy": "previously_inspected_development_check_after_MS5_freeze",
    "reserved_policy": "sealed_separate_MS7_go_and_metadata_overlap_audit",
}
LANE_SEMANTICS = {
    "NCEI-native-duration": {
        "response": "native_reported_positive_travel_minutes_not_universal_physical_onset",
        "transform": "ln(y/t0(distance))",
        "prediction": "new_sequence_reported_duration_at_specified_distance_and_site",
    },
    "T-OBS": {
        "response": "reported_observed_UTC_minus_reviewed_USGS_origin_positive_minutes",
        "transform": "ln(y/t0(distance))",
        "prediction": "new_sequence_reported_duration_at_specified_distance_and_site",
    },
    "T-CAL": {
        "response": "reported_estimated_UTC_minus_observed_UTC_signed_minutes",
        "transform": "identity_minutes",
        "prediction": "new_sequence_archived_product_discrepancy_retrospective_not_operational",
    },
}


@dataclass(frozen=True)
class Lane:
    """One source/target view; exclusion mask changes no original source value."""

    target: str
    rows: tuple[Row, ...]
    record_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    site_ids: tuple[str, ...]
    sequences: tuple[str, ...]
    y: NDArray[np.float64]
    distance_km: NDArray[np.float64]
    reference_minutes: NDArray[np.float64]
    x: NDArray[np.float64]
    response: NDArray[np.float64]
    included: NDArray[np.bool_]


@dataclass(frozen=True)
class Fold:
    """Exact primary-view sequence fold and held-out site support."""

    sequence_id: str
    train: NDArray[np.int64]
    test: NDArray[np.int64]
    seen_site: NDArray[np.bool_]


def _known(value: str) -> bool:
    return bool(value.strip()) and value.strip().lower() not in {"unknown", "nan", "none"}


def lane_arrays(
    target: str, rows: list[Row], sequence_by_event: dict[str, str], exploration: set[str]
) -> Lane:
    """Validate mandatory fields and construct a target-specific primary view."""
    if target not in TARGET_FILES or not rows:
        raise ValueError("require a known nonempty lane")
    records = tuple(dict(row) for row in sorted(rows, key=lambda row: row["record_id"]))
    identifiers = tuple(row["record_id"] for row in records)
    if len(set(identifiers)) != len(records) or not all(map(_known, identifiers)):
        raise ValueError("require unique known native record IDs")
    for row in records:
        if row["target"] != target:
            raise ValueError("target mismatch")
        if row["event_id"] not in exploration:
            raise ValueError("non-exploration event in model lane")
        if not _known(row["physical_site_id"]):
            raise ValueError("unknown mandatory site identity")
        if not _known(sequence_by_event.get(row["event_id"], "")):
            raise ValueError("unknown mandatory sequence identity")
    y = np.array([float(row["target_minutes"]) for row in records], dtype=np.float64)
    distance = np.array([float(row["distance_km"]) for row in records], dtype=np.float64)
    if not np.isfinite(y).all() or (target != "T-CAL" and (y <= 0).any()):
        raise ValueError("require finite signed differences or finite positive durations")
    if not np.isfinite(distance).all() or (distance <= 0).any():
        raise ValueError("require finite positive distance")
    reference = distance / VREF_KM_MIN
    if not np.isfinite(reference).all() or (reference <= 0).any():
        raise ValueError("unrepresentable reference duration")
    for row, expected in zip(records, reference, strict=True):
        if "reference_minutes" in row and not math.isclose(
            float(row["reference_minutes"]), float(expected), rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError("source reference disagrees with fixed reference contract")
    edges = Counter((row["event_id"], row["physical_site_id"]) for row in records)
    included = np.array(
        [
            target != "NCEI-native-duration" or edges[row["event_id"], row["physical_site_id"]] == 1
            for row in records
        ],
        dtype=np.bool_,
    )
    if not included.any():
        raise ValueError("no primary evidence units remain")
    return Lane(
        target,
        records,
        identifiers,
        tuple(row["event_id"] for row in records),
        tuple(row["physical_site_id"] for row in records),
        tuple(sequence_by_event[row["event_id"]] for row in records),
        y,
        distance,
        reference,
        np.log(distance) - math.log(1000),
        y.copy() if target == "T-CAL" else np.log(y) - np.log(reference),
        included,
    )


def sequence_folds(lane: Lane) -> tuple[Fold, ...]:
    """Purge every related event and ambiguous evidence unit from training."""
    groups = np.array(lane.sequences)
    folds: list[Fold] = []
    for sequence in sorted(set(groups[lane.included])):
        train = np.flatnonzero((groups != sequence) & lane.included)
        test = np.flatnonzero((groups == sequence) & lane.included)
        if not len(train) or not len(test):
            raise ValueError("sequence validation requires nonempty training and test sets")
        training_sites = {lane.site_ids[int(i)] for i in train}
        seen = np.array([lane.site_ids[int(i)] in training_sites for i in test], dtype=np.bool_)
        folds.append(Fold(str(sequence), train, test, seen))
    return tuple(folds)


def load_lanes(root: Path) -> tuple[dict[str, Lane], dict[str, Any]]:
    """Parse three exploration tables and outcome-free metadata; never mixed outcomes."""
    contract = tomllib.loads(checked_path(root, CONTRACT).read_text(encoding="utf-8"))
    for key, expected in CONVENTIONS.items():
        if contract.get(key) != expected:
            raise ValueError(f"unsupported scientific contract: {key}")
    inputs: dict[str, str] = contract["inputs"]
    if set(inputs) != {*TARGET_FILES.values(), SPLIT, METADATA, SOURCE_MANIFEST}:
        raise ValueError("input allowlist must contain only exploration tables and metadata")
    for name, expected in inputs.items():
        if sha256(checked_path(root, name)) != expected:
            raise ValueError(f"input hash mismatch: {name}")
    split = tomllib.loads(checked_path(root, SPLIT).read_text(encoding="utf-8"))
    exploration: set[str] = set(split["exploration"])
    confirmation: set[str] = set(split["confirmation"])
    if len(exploration) != 38 or len(confirmation) != 19 or exploration & confirmation:
        raise ValueError("invalid frozen exploration/confirmation roles")
    metadata = read_rows(checked_path(root, METADATA))
    if len({row["event_id"] for row in metadata}) != len(metadata):
        raise ValueError("duplicate event metadata identity")
    if {row["event_id"] for row in metadata} != exploration | confirmation:
        raise ValueError("event roles disagree with metadata")
    sequences = {row["event_id"]: row["sequence_group"] for row in metadata}
    lanes = {
        target: lane_arrays(target, read_rows(checked_path(root, path)), sequences, exploration)
        for target, path in TARGET_FILES.items()
    }
    expected_lanes = contract["lanes"]
    if set(expected_lanes) != set(lanes):
        raise ValueError("contract requires exactly three separate target lanes")
    for target, lane in lanes.items():
        actual = {
            **LANE_SEMANTICS[target],
            "rows": len(lane.rows),
            "primary_rows": int(lane.included.sum()),
            "events": len(set(lane.event_ids)),
            "sites": len(set(lane.site_ids)),
            "sequences": len(sequence_folds(lane)),
            "excluded_ids": sorted(
                r for r, ok in zip(lane.record_ids, lane.included, strict=True) if not ok
            ),
        }
        if actual != expected_lanes[target]:
            raise ValueError(f"contract lane/identity mismatch: {target}")
    return lanes, contract


def write_data_bundle(root: Path, output: Path) -> dict[str, Any]:
    """Export every source row, exact primary folds and consumed input identities."""
    if output.exists():
        raise ValueError("output must be new; retain previous scientific bundles")
    lanes, contract = load_lanes(root)
    output.mkdir(parents=True)
    membership: list[Row] = []
    for target, lane in lanes.items():
        rows: list[Row] = []
        for i, original in enumerate(lane.rows):
            rows.append(
                {
                    **original,
                    "sequence_group": lane.sequences[i],
                    "included_primary": str(bool(lane.included[i])),
                    "model_disposition": "included"
                    if lane.included[i]
                    else "unresolved_repeated_edge_excluded_as_group",
                    "model_x": str(float(lane.x[i])),
                    "model_response": str(float(lane.response[i])),
                }
            )
        write_rows(output / f"{target}.csv.gz", rows)
        for fold in sequence_folds(lane):
            training = set(fold.train.tolist())
            seen = {int(i): bool(ok) for i, ok in zip(fold.test, fold.seen_site, strict=True)}
            for i, record in enumerate(lane.record_ids):
                membership.append(
                    {
                        "target": target,
                        "held_out_sequence": fold.sequence_id,
                        "record_id": record,
                        "event_id": lane.event_ids[i],
                        "sequence_group": lane.sequences[i],
                        "site_id": lane.site_ids[i],
                        "role": "excluded"
                        if not lane.included[i]
                        else "train"
                        if i in training
                        else "test",
                        "seen_site": str(seen[i]) if i in seen else "not_test",
                    }
                )
    write_rows(output / "fold-membership.csv.gz", membership)
    write_json(output / "contract.json", contract)
    upstream = json.loads(checked_path(root, SOURCE_MANIFEST).read_text(encoding="utf-8"))
    upstream.pop("root", None)
    write_json(
        output / "upstream-input-manifest.json",
        {
            "relative_to": "project_root",
            "original_path": SOURCE_MANIFEST,
            "original_sha256": contract["inputs"][SOURCE_MANIFEST],
            "manifest": upstream,
            "upstream_outcome_files_parsed": False,
        },
    )
    code = [
        "analysis/arrival/model_data.py",
        "analysis/arrival/evidence.py",
        "scripts/arrival_model.py",
        "pyproject.toml",
        "uv.lock",
        CONTRACT,
    ]
    write_json(
        output / "inputs.json",
        {
            "schema_version": "arrival_model_inputs_v1",
            "relative_to": "project_root",
            "files": {**contract["inputs"], **{p: sha256(root / p) for p in code}},
            "parsed_outcomes": list(TARGET_FILES.values()),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes_parsed": False,
        },
    )
    write_json(output / "metrics.json", contract["lanes"])
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
    return contract["lanes"]
