"""Pure prospective masks for the finite MS-5 55-fit / 110-call tranche.

Inputs are supplied Lane objects and explicitly aligned, reviewed metadata; this
module opens no files. Omission/era cases stay conditional on reporting and do
not correct source values or identify missingness. Publisher distances have
verified km units and an unknown algorithm. Site-key checks and accepted LOSqO
training-posterior reuse are proofs/references, never additional fit cases.
"""

# pyright: basic
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN, Lane

DEFINITION_RECORD_IDS = (
    "recovery-ncei-66bfa3cd99cb7161:11",
    "recovery-ncei-66bfa3cd99cb7161:7",
)
FORMS = (
    ("NCEI-native-duration", "distance-scale"),
    ("NCEI-native-duration", "mean-curvature"),
    ("T-OBS", "pooled"),
    ("T-OBS", "distance"),
    ("T-OBS", "event"),
    ("T-CAL", "pooled"),
    ("T-CAL", "distance"),
    ("T-CAL", "event"),
)
PRIOR_VARIANTS = ("power_0.5", "power_1.5", "joint_wider", "t4_matched")
NONPRIOR_SCENARIOS = (
    "coastal-only",
    "era-pre2007",
    "era-2007-2013",
    "era-2014plus",
    "publisher-distance",
    "omit-triage",
    "component-assessed",
    "omit-native-below10",
    "omit-lata-only",
    "omit-tohoku-and-chile",
    "omit-definition",
)
PILOTS = (
    ("NCEI-native-duration", "mean-curvature", "t4_matched"),
    ("T-CAL", "event", "t4_matched"),
)


@dataclass(frozen=True)
class SensitivityInputs:
    """Reviewed metadata, aligned to the full NCEI lane including six exclusions.

    Record-ID cohorts contain primary rows only. Event years and influence
    sequences are supplied identities, not inferred from dates or raw schemas.
    Site-key arrays supply each reviewed 1/2/5-km grouping; this helper does not
    invent a clustering algorithm. Native-distance values are never source repairs.
    """

    coastal: np.ndarray
    event_years: Mapping[str, int]
    publisher_distance_km: np.ndarray
    triage_record_ids: tuple[str, ...]
    component_assessed_record_ids: tuple[str, ...]
    definition_record_ids: tuple[str, ...]
    lata_record_id: str
    influence_sequences: Mapping[str, str]
    site_keys_by_km: Mapping[int, tuple[str, ...]]
    publisher_distance_units: str = "km"
    publisher_distance_algorithm: str = "unknown"


def _validate_lane(lane: Lane) -> None:
    """Reject misaligned or inconsistent canonical arrays without changing them."""
    n = len(lane.rows)
    if lane.target not in {target for target, _ in FORMS} or not n:
        raise ValueError("a known nonempty source-specific lane required")
    for values in [lane.record_ids, lane.event_ids, lane.site_ids, lane.sequences]:
        if len(values) != n or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("aligned known record/event/site/sequence IDs required")
    if len(set(lane.record_ids)) != n:
        raise ValueError("unique native record IDs required")
    if lane.included.shape != (n,) or lane.included.dtype != np.bool_ or not lane.included.any():
        raise ValueError("nonempty aligned Boolean primary evidence mask required")
    for values in [lane.y, lane.distance_km, lane.reference_minutes, lane.x, lane.response]:
        if values.shape != (n,) or values.dtype.kind not in "iuf" or not np.isfinite(values).all():
            raise ValueError("aligned finite native and derived arrays required")
    if (lane.distance_km <= 0).any() or (lane.reference_minutes <= 0).any():
        raise ValueError("positive distance and reference duration required")
    if lane.target != "T-CAL" and (lane.y <= 0).any():
        raise ValueError("positive native durations required")
    expected_reference = lane.distance_km / VREF_KM_MIN
    expected_response = (
        lane.y if lane.target == "T-CAL" else np.log(lane.y) - np.log(expected_reference)
    )
    if (
        not np.allclose(lane.reference_minutes, expected_reference, rtol=0, atol=1e-10)
        or not np.allclose(lane.x, np.log(lane.distance_km) - np.log(1000), rtol=0, atol=1e-12)
        or not np.allclose(lane.response, expected_response, rtol=0, atol=1e-12)
    ):
        raise ValueError("coherent distance/reference/predictor/response arrays required")


def _cohort(lane: Lane, identifiers: tuple[str, ...], count: int) -> np.ndarray:
    """Validate an exact supplied primary cohort and return its literal mask."""
    primary = {record for record, keep in zip(lane.record_ids, lane.included, strict=True) if keep}
    if (
        len(identifiers) != count
        or len(set(identifiers)) != count
        or not set(identifiers) <= primary
    ):
        raise ValueError("exact supplied primary-record cohort/count required")
    return np.isin(lane.record_ids, identifiers)


def _publisher_distances(lane: Lane, inputs: SensitivityInputs) -> np.ndarray:
    """Check supplied km values without replacing any native timing value."""
    values = np.asarray(inputs.publisher_distance_km)
    if (
        inputs.publisher_distance_units != "km"
        or inputs.publisher_distance_algorithm != "unknown"
        or values.shape != (len(lane.rows),)
        or values.dtype.kind not in "iuf"
        or not np.isfinite(values).all()
        or (values <= 0).any()
    ):
        raise ValueError("aligned finite positive publisher km with unknown algorithm required")
    return values.astype(float, copy=True)


def site_key_invariance(lane: Lane, keys_by_km: Mapping[int, tuple[str, ...]]) -> dict[str, Any]:
    """Prove unchanged ambiguity masks for supplied 1/2/5-km keys, without fitting."""
    _validate_lane(lane)
    if (
        lane.target != "NCEI-native-duration"
        or set(keys_by_km) != {1, 2, 5}
        or any(type(radius) is not int for radius in keys_by_km)
    ):
        raise ValueError("NCEI site-key proof at exactly1/2/5km required")
    proof = {}
    for radius, keys in sorted(keys_by_km.items()):
        if len(keys) != len(lane.rows) or any(
            not isinstance(key, str) or not key.strip() for key in keys
        ):
            raise ValueError("aligned known supplied site keys required")
        counts = Counter(zip(lane.event_ids, keys, strict=True))
        mask = np.array(
            [counts[event, key] == 1 for event, key in zip(lane.event_ids, keys, strict=True)]
        )
        if not np.array_equal(mask, lane.included):
            raise ValueError("site-key sensitivity changed primary ambiguity mask")
        proof[str(radius)] = {
            "radius_km": radius,
            "mask_equal": True,
            "primary_records": int(mask.sum()),
            "excluded_records": int((~mask).sum()),
            "new_fits": 0,
            "likelihood_invariance": "same_records_covariates_no_retained_site_effect",
        }
    return proof


def _validated_masks(
    lane: Lane, inputs: SensitivityInputs
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Bind every approved NCEI stress to supplied metadata and the fixed cohort."""
    if int(lane.included.sum()) != 1064 or int((~lane.included).sum()) != 6:
        raise ValueError("frozen1064primary/sixexcluded NCEI cohort required")
    if inputs.coastal.shape != lane.included.shape or inputs.coastal.dtype != np.bool_:
        raise ValueError("aligned Boolean coastal metadata required")
    if set(inputs.event_years) != set(lane.event_ids) or any(
        type(year) is not int or not 1 <= year <= 9999 for year in inputs.event_years.values()
    ):
        raise ValueError("complete supplied integer event years required")
    years = np.array([inputs.event_years[event] for event in lane.event_ids])
    triage = _cohort(lane, inputs.triage_record_ids, 4)
    assessed = _cohort(lane, inputs.component_assessed_record_ids, 1050)
    definition = _cohort(lane, inputs.definition_record_ids, 2)
    if set(inputs.definition_record_ids) != set(DEFINITION_RECORD_IDS):
        raise ValueError("both frozen NCEI definition candidate IDs required")
    _publisher_distances(lane, inputs)
    influence = inputs.influence_sequences
    primary_sequences = {
        sequence for sequence, keep in zip(lane.sequences, lane.included, strict=True) if keep
    }
    if (
        set(influence) != {"tohoku", "chile2010", "influential2014"}
        or len(set(influence.values())) != 3
        or not set(influence.values()) <= primary_sequences
    ):
        raise ValueError("three distinct supplied whole influence sequences required")
    lata = _cohort(lane, (inputs.lata_record_id,), 1)
    sequence = lane.sequences[int(np.flatnonzero(lata)[0])]
    if (
        sum(
            keep and item == sequence
            for keep, item in zip(lane.included, lane.sequences, strict=True)
        )
        != 4
    ):
        raise ValueError("LATA-only deletion must retain its sequence's other three rows")
    masks = {
        "coastal-only": inputs.coastal,
        "era-pre2007": years < 2007,
        "era-2007-2013": (years >= 2007) & (years <= 2013),
        "era-2014plus": years >= 2014,
        "publisher-distance": np.ones(len(lane.rows), dtype=bool),
        "omit-triage": ~triage,
        "component-assessed": assessed,
        "omit-native-below10": lane.y >= 10,
        "omit-lata-only": ~lata,
        "omit-tohoku-and-chile": ~np.isin(
            lane.sequences, [influence["tohoku"], influence["chile2010"]]
        ),
        "omit-definition": ~definition,
    }
    return {name: mask & lane.included for name, mask in masks.items()}, site_key_invariance(
        lane, inputs.site_keys_by_km
    )


def _distance_view(lane: Lane, inputs: SensitivityInputs) -> Lane:
    """Change distance and every dependent quantity, retaining native values/IDs."""
    distance = _publisher_distances(lane, inputs)
    reference = distance / VREF_KM_MIN
    if not np.isfinite(reference).all() or (reference <= 0).any():
        raise ValueError("representable publisher-distance reference required")
    rows = []
    for row, value, ref in zip(lane.rows, distance, reference, strict=True):
        changed = dict(row)
        changed["distance_km"] = str(float(value))
        if "reference_minutes" in changed:
            changed["reference_minutes"] = str(float(ref))
        rows.append(changed)
    return replace(
        lane,
        rows=tuple(rows),
        distance_km=distance,
        reference_minutes=reference,
        x=np.log(distance) - np.log(1000),
        response=np.log(lane.y) - np.log(reference),
    )


def support_summary(lane: Lane, kind: str, indices: np.ndarray) -> dict[str, Any]:
    """Describe literal training support, group counts and identifiable mean rank."""
    _validate_lane(lane)
    if (lane.target, kind) not in FORMS:
        raise ValueError("one reviewed source-specific form required")
    if (
        indices.ndim != 1
        or not np.issubdtype(indices.dtype, np.integer)
        or not len(indices)
        or len(set(indices.tolist())) != len(indices)
        or (indices < 0).any()
        or (indices >= len(lane.rows)).any()
        or not lane.included[indices].all()
    ):
        raise ValueError("nonempty unique primary training indices required")
    columns = [np.ones(len(indices))]
    if kind != "pooled":
        columns.append(lane.x[indices])
    if kind == "mean-curvature":
        columns.append(curvature_basis(lane.distance_km[indices]))
    matrix = np.column_stack(columns)
    rank = int(np.linalg.matrix_rank(matrix))
    return {
        "records": len(indices),
        "event_counts": dict(sorted(Counter(lane.event_ids[int(i)] for i in indices).items())),
        "sequence_counts": dict(sorted(Counter(lane.sequences[int(i)] for i in indices).items())),
        "sites": len({lane.site_ids[int(i)] for i in indices}),
        "distance_km_min": float(lane.distance_km[indices].min()),
        "distance_km_max": float(lane.distance_km[indices].max()),
        "matrix_rank": rank,
        "expected_rank": len(columns),
        "full_rank": rank == len(columns),
    }


def _case(
    lane: Lane, kind: str, variant: str, scenario: str, indices: np.ndarray, *, pilot: bool = False
) -> dict[str, Any]:
    slug = {"NCEI-native-duration": "ncei", "T-OBS": "tobs", "T-CAL": "tcal"}[lane.target]
    support = support_summary(lane, kind, indices)
    if not support["full_rank"]:
        raise ValueError("sensitivity training subset lacks the required mean design rank")
    chosen = set(indices.tolist())
    return {
        "id": f"ms5-{slug}-{kind}-{variant.replace('_', '-')}-{scenario}",
        "target": lane.target,
        "kind": kind,
        "prior_variant": variant,
        "scenario": scenario,
        "pilot": pilot,
        "distance_mode": "publisher_native_km"
        if scenario == "publisher-distance"
        else "geodesic_km",
        "distance_units": "km",
        "distance_algorithm": "unknown" if scenario == "publisher-distance" else "geodesic",
        "training_record_ids": [lane.record_ids[int(i)] for i in indices],
        "omitted_record_ids": [
            record
            for i, record in enumerate(lane.record_ids)
            if lane.included[i] and i not in chosen
        ],
        "excluded_record_ids": [
            record for record, keep in zip(lane.record_ids, lane.included, strict=True) if not keep
        ],
        "support": support,
        "predictive_reference": "case_distance_km/VREF_KM_MIN",
        "interpretation": "reported_data_stress_no_source_repair_or_missingness_identification",
    }


def case_indices(lane: Lane, case: Mapping[str, Any]) -> np.ndarray:
    """Materialize the exact ordered primary cohort in one enumerated case."""
    _validate_lane(lane)
    identifiers = case.get("training_record_ids", [])
    if case.get("target") != lane.target or not isinstance(identifiers, list) or not identifiers:
        raise ValueError("bound case target and nonempty record IDs required")
    mask = _cohort(lane, tuple(identifiers), len(identifiers))
    indices = np.flatnonzero(mask)
    if identifiers != [lane.record_ids[int(i)] for i in indices]:
        raise ValueError("canonical lane order required for exact case membership")
    omitted = [
        record
        for record, keep, chosen in zip(lane.record_ids, lane.included, mask, strict=True)
        if keep and not chosen
    ]
    excluded = [
        record for record, keep in zip(lane.record_ids, lane.included, strict=True) if not keep
    ]
    if case.get("omitted_record_ids") != omitted or case.get("excluded_record_ids") != excluded:
        raise ValueError("complete original exclusion/omission bookkeeping required")
    return indices


def case_lane(lane: Lane, case: Mapping[str, Any], inputs: SensitivityInputs) -> Lane:
    """Return a new masked Lane; builders recompute basis/SD weights from its d.

    The same updated reference_minutes must be used for new-event prediction.
    No native y, record ID or source-original dictionary is modified.
    """
    indices = case_indices(lane, case)
    mode = case.get("distance_mode")
    if mode not in {"publisher_native_km", "geodesic_km"}:
        raise ValueError("reviewed distance mode required")
    if mode == "publisher_native_km":
        if lane.target != "NCEI-native-duration" or case.get("scenario") != "publisher-distance":
            raise ValueError("publisher distance is an NCEI-only design stress")
        lane = _distance_view(lane, inputs)
    mask = np.zeros(len(lane.rows), dtype=bool)
    mask[indices] = True
    return replace(lane, included=mask)


def build_sensitivity_design(
    lanes: Mapping[str, Lane], inputs: SensitivityInputs
) -> dict[str, Any]:
    """Enumerate 33 prior and 22 data fits, counting both representative pilots."""
    if set(lanes) != {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("the three separate source-specific lanes required")
    for target, lane in lanes.items():
        _validate_lane(lane)
        if lane.target != target:
            raise ValueError("lane key and target must agree")
    ncei = lanes["NCEI-native-duration"]
    masks, proof = _validated_masks(ncei, inputs)
    specs = [
        *PILOTS,
        *[
            (target, kind, variant)
            for target, kind in FORMS
            for variant in PRIOR_VARIANTS
            if (target, kind, variant) not in PILOTS
        ],
        ("NCEI-native-duration", "mean-curvature", "gamma_wider_only"),
    ]
    cases = [
        _case(
            lanes[target],
            kind,
            variant,
            "prior",
            np.flatnonzero(lanes[target].included),
            pilot=(target, kind, variant) in PILOTS,
        )
        for target, kind, variant in specs
    ]
    reused = []
    for kind in ["distance-scale", "mean-curvature"]:
        for scenario in NONPRIOR_SCENARIOS:
            view = _distance_view(ncei, inputs) if scenario == "publisher-distance" else ncei
            case = _case(view, kind, "base", scenario, np.flatnonzero(masks[scenario]))
            if scenario == "omit-lata-only":
                lata_index = ncei.record_ids.index(inputs.lata_record_id)
                group = ncei.sequences[lata_index]
                case["retained_lata_sequence_record_ids"] = [
                    ncei.record_ids[int(i)]
                    for i in np.flatnonzero(masks[scenario])
                    if ncei.sequences[int(i)] == group
                ]
            cases.append(case)
        for label, sequence in sorted(inputs.influence_sequences.items()):
            mask = ncei.included & (np.asarray(ncei.sequences) != sequence)
            reference = _case(ncei, kind, "base", f"reuse-{label}", np.flatnonzero(mask))
            reference.update(
                deleted_sequence=sequence,
                draws=2000,
                requires_original_training_posterior=True,
                posterior_role="original_LOSqO_training_not_augmented",
                source_policy="original_2000_draw_training_not_later_precision_supplement",
                new_fits=0,
            )
            reused.append(reference)
    if len(cases) != 55 or len({case["id"] for case in cases}) != 55 or len(reused) != 6:
        raise ValueError("exact finite55-fit/six-reuse sensitivity design required")
    for order, case in enumerate(cases):
        case["order"] = order
    return {
        "cases": cases,
        "initial_fits": 55,
        "prior_fits": 33,
        "nonprior_fits": 22,
        "inclusive_call_ceiling": 110,
        "automatic_retries": 0,
        "repair_policy": "at_most_one_separately_reviewed_numerical_repair_per_case_inside110",
        "reuse_training_posteriors": reused,
        "site_key_invariance": proof,
        "pilot_case_ids": [case["id"] for case in cases[:2]],
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
