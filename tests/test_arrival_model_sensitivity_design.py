"""Pure synthetic bookkeeping for the finite 55-fit sensitivity design."""

# pyright: basic
import json
from dataclasses import replace

import numpy as np
import pytest

from analysis.arrival import model_sensitivity_design as design
from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN, lane_arrays
from analysis.arrival.model_scale import scale_weights


def synthetic_inputs():
    events = ["tohoku", "chile", "influence2014", "pre", "middle", "recent"]
    years = dict(zip(events, [2011, 2010, 2014, 2000, 2008, 2019], strict=True))
    rows = []
    for i in range(1060):
        record = f"r{i:04d}"
        if i in (7, 11):
            record = f"recovery-ncei-66bfa3cd99cb7161:{i}"
        rows.append(
            {
                "record_id": record,
                "event_id": events[i % 6],
                "physical_site_id": f"site-{i}",
                "distance_km": str(30 + (i % 71) * 210),
                "target_minutes": str(9.5 if i == 0 else 10 if i == 1 else 20 + i % 101),
                "target": "NCEI-native-duration",
            }
        )
    for i in range(4):
        rows.append(
            {
                "record_id": "lata-only" if i == 0 else f"lata-related-{i}",
                "event_id": "lata" if i == 0 else "lata-related",
                "physical_site_id": f"lata-site-{i}",
                "distance_km": str(1000 + i * 1000),
                "target_minutes": "30",
                "target": "NCEI-native-duration",
            }
        )
    years.update({"lata": 2014, "lata-related": 2014})
    for i in range(6):
        rows.append(
            {
                "record_id": f"excluded-{i}",
                "event_id": events[3 + i // 2],
                "physical_site_id": f"ambiguous-{i // 2}",
                "distance_km": "1000",
                "target_minutes": "30",
                "target": "NCEI-native-duration",
            }
        )
    sequences = {event: f"seq-{event}" for event in years}
    sequences["lata-related"] = sequences["lata"]
    ncei = lane_arrays("NCEI-native-duration", rows, sequences, set(years))
    lanes = {"NCEI-native-duration": ncei}
    for target in ["T-OBS", "T-CAL"]:
        ntwc = [
            {
                "record_id": f"{target}-{i}",
                "event_id": f"ntwc-{i % 3}",
                "physical_site_id": f"ntwc-site-{i}",
                "distance_km": str(100 + i * 700),
                "target_minutes": str(
                    (-1 if i % 2 else 1) * (10 + i) if target == "T-CAL" else 10 + i
                ),
                "target": target,
            }
            for i in range(9)
        ]
        lanes[target] = lane_arrays(
            target,
            ntwc,
            {f"ntwc-{i}": f"ntwc-seq-{i}" for i in range(3)},
            {f"ntwc-{i}" for i in range(3)},
        )
    primary = [record for record, keep in zip(ncei.record_ids, ncei.included, strict=True) if keep]
    metadata = design.SensitivityInputs(
        coastal=np.arange(len(ncei.rows)) % 2 == 0,
        event_years=years,
        publisher_distance_km=ncei.distance_km * (1.07 + np.arange(len(ncei.rows)) % 3 * 0.01),
        triage_record_ids=tuple(primary[:4]),
        component_assessed_record_ids=tuple(primary[:1050]),
        definition_record_ids=design.DEFINITION_RECORD_IDS,
        lata_record_id="lata-only",
        influence_sequences={
            "tohoku": "seq-tohoku",
            "chile2010": "seq-chile",
            "influential2014": "seq-influence2014",
        },
        site_keys_by_km={
            radius: tuple(f"{radius}-{site}" for site in ncei.site_ids) for radius in [1, 2, 5]
        },
    )
    return lanes, metadata


def test_fixed55_cases_two_counted_pilots_and_six_reuses():
    lanes, metadata = synthetic_inputs()
    result = design.build_sensitivity_design(lanes, metadata)
    cases = result["cases"]
    assert len(cases) == 55 and len({case["id"] for case in cases}) == 55
    assert [case["order"] for case in cases] == list(range(55))
    assert [(case["target"], case["kind"], case["prior_variant"]) for case in cases[:2]] == [
        ("NCEI-native-duration", "mean-curvature", "t4_matched"),
        ("T-CAL", "event", "t4_matched"),
    ]
    assert [case["pilot"] for case in cases] == [True, True] + [False] * 53
    assert result["initial_fits"] == 55 and result["inclusive_call_ceiling"] == 110
    assert result["prior_fits"] == 33 and result["nonprior_fits"] == 22
    assert len(result["reuse_training_posteriors"]) == 6
    assert all(
        spec["draws"] == 2000 and spec["requires_original_training_posterior"]
        for spec in result["reuse_training_posteriors"]
    )
    assert design.build_sensitivity_design(lanes, metadata) == result
    assert json.loads(json.dumps(result)) == result


def test_all_cases_retain_original_exclusions_and_report_support_rank():
    lanes, metadata = synthetic_inputs()
    result = design.build_sensitivity_design(lanes, metadata)
    for case in result["cases"]:
        lane = lanes[case["target"]]
        indices = design.case_indices(lane, case)
        assert len(indices) and lane.included[indices].all()
        assert case["support"]["records"] == len(indices)
        assert sum(case["support"]["event_counts"].values()) == len(indices)
        assert case["support"]["matrix_rank"] == case["support"]["expected_rank"]
        assert case["support"]["full_rank"] is True
        if lane.target == "NCEI-native-duration":
            assert len(case["excluded_record_ids"]) == 6
            assert not set(case["excluded_record_ids"]) & set(case["training_record_ids"])


def test_exact_omission_masks_and_whole_sequence_reuse():
    lanes, metadata = synthetic_inputs()
    result = design.build_sensitivity_design(lanes, metadata)
    ncei = lanes["NCEI-native-duration"]
    for kind in ["distance-scale", "mean-curvature"]:
        cases = {
            case["scenario"]: case
            for case in result["cases"]
            if case["target"] == ncei.target
            and case["kind"] == kind
            and case["prior_variant"] == "base"
        }
        assert set(cases) == set(design.NONPRIOR_SCENARIOS)
        assert set(cases["omit-triage"]["omitted_record_ids"]) == set(metadata.triage_record_ids)
        assert len(cases["component-assessed"]["training_record_ids"]) == 1050
        assert set(cases["omit-definition"]["omitted_record_ids"]) == set(
            design.DEFINITION_RECORD_IDS
        )
        assert cases["omit-lata-only"]["omitted_record_ids"] == ["lata-only"]
        assert len(cases["omit-lata-only"]["retained_lata_sequence_record_ids"]) == 3
        joint = cases["omit-tohoku-and-chile"]
        assert not {"seq-tohoku", "seq-chile"} & {
            ncei.sequences[int(i)] for i in design.case_indices(ncei, joint)
        }
        short = cases["omit-native-below10"]
        selected = design.case_indices(ncei, short)
        assert (ncei.y[selected] >= 10).all() and (ncei.y[selected] == 10).any()
        era_records = [
            set(cases[name]["training_record_ids"])
            for name in ["era-pre2007", "era-2007-2013", "era-2014plus"]
        ]
        assert not any(era_records[i] & era_records[j] for i in range(3) for j in range(i))
        assert set.union(*era_records) == set(ncei.record_ids) - set(short["excluded_record_ids"])
    for spec in result["reuse_training_posteriors"]:
        indices = design.case_indices(ncei, spec)
        assert spec["deleted_sequence"] not in {ncei.sequences[int(i)] for i in indices}
        assert spec["posterior_role"] == "original_LOSqO_training_not_augmented"


def test_publisher_distance_updates_all_covariates_preserving_native_ids_and_inputs():
    lanes, metadata = synthetic_inputs()
    ncei = lanes["NCEI-native-duration"]
    originals = {
        name: getattr(ncei, name).copy()
        for name in ["y", "distance_km", "reference_minutes", "x", "response", "included"]
    }
    rows = tuple(dict(row) for row in ncei.rows)
    case = next(
        case
        for case in design.build_sensitivity_design(lanes, metadata)["cases"]
        if case["scenario"] == "publisher-distance" and case["kind"] == "mean-curvature"
    )
    changed = design.case_lane(ncei, case, metadata)
    assert changed.record_ids == ncei.record_ids and changed.event_ids == ncei.event_ids
    np.testing.assert_array_equal(changed.y, ncei.y)
    np.testing.assert_array_equal(changed.distance_km, metadata.publisher_distance_km)
    np.testing.assert_allclose(changed.reference_minutes, changed.distance_km / VREF_KM_MIN)
    np.testing.assert_allclose(changed.x, np.log(changed.distance_km) - np.log(1000))
    np.testing.assert_allclose(changed.response, np.log(ncei.y) - np.log(changed.reference_minutes))
    assert not np.array_equal(
        curvature_basis(changed.distance_km), curvature_basis(ncei.distance_km)
    )
    assert not np.array_equal(scale_weights(changed.distance_km), scale_weights(ncei.distance_km))
    np.testing.assert_allclose(changed.reference_minutes, changed.distance_km / VREF_KM_MIN)
    for name, value in originals.items():
        np.testing.assert_array_equal(getattr(ncei, name), value)
    assert ncei.rows == rows
    assert case["distance_algorithm"] == "unknown" and case["distance_units"] == "km"


def test_site_key_invariance_is_a_proof_without_new_fits():
    lanes, metadata = synthetic_inputs()
    proof = design.build_sensitivity_design(lanes, metadata)["site_key_invariance"]
    assert set(proof) == {"1", "2", "5"}
    assert all(
        item["mask_equal"]
        and item["primary_records"] == 1064
        and item["excluded_records"] == 6
        and item["new_fits"] == 0
        for item in proof.values()
    )


@pytest.mark.parametrize(
    "change",
    [
        "empty_coastal",
        "bad_coastal_shape",
        "bad_coastal_dtype",
        "bad_publisher",
        "bad_year",
        "missing_year",
        "triage_count",
        "assessed_count",
        "unknown_triage",
        "one_definition",
        "bad_lata",
        "same_sequence",
        "site_mask",
    ],
)
def test_invalid_supplied_metadata_is_rejected(change):
    lanes, metadata = synthetic_inputs()
    if change == "empty_coastal":
        metadata = replace(metadata, coastal=np.zeros(1070, dtype=bool))
    elif change == "bad_coastal_shape":
        metadata = replace(metadata, coastal=np.ones(2, dtype=bool))
    elif change == "bad_coastal_dtype":
        metadata = replace(metadata, coastal=np.ones(1070, dtype=int))
    elif change == "bad_publisher":
        values = metadata.publisher_distance_km.copy()
        values[3] = np.nan
        metadata = replace(metadata, publisher_distance_km=values)
    elif change in {"bad_year", "missing_year"}:
        years = dict(metadata.event_years)
        if change == "bad_year":
            years["pre"] = True
        else:
            del years["pre"]
        metadata = replace(metadata, event_years=years)
    elif change == "triage_count":
        metadata = replace(metadata, triage_record_ids=metadata.triage_record_ids[:3])
    elif change == "assessed_count":
        metadata = replace(
            metadata, component_assessed_record_ids=metadata.component_assessed_record_ids[:-1]
        )
    elif change == "unknown_triage":
        metadata = replace(metadata, triage_record_ids=(*metadata.triage_record_ids[:3], "unknown"))
    elif change == "one_definition":
        metadata = replace(metadata, definition_record_ids=design.DEFINITION_RECORD_IDS[:1])
    elif change == "bad_lata":
        metadata = replace(metadata, lata_record_id="r0000")
    elif change == "same_sequence":
        metadata = replace(
            metadata,
            influence_sequences={key: "seq-tohoku" for key in metadata.influence_sequences},
        )
    else:
        keys = dict(metadata.site_keys_by_km)
        values = list(keys[2])
        values[0] = "new-unique-key"
        keys[2] = tuple(values)
        metadata = replace(metadata, site_keys_by_km=keys)
    with pytest.raises(ValueError):
        design.build_sensitivity_design(lanes, metadata)


def test_invalid_case_and_nonfinite_lane_are_rejected():
    lanes, metadata = synthetic_inputs()
    case = design.build_sensitivity_design(lanes, metadata)["cases"][0]
    ncei = lanes["NCEI-native-duration"]
    for ids in [[], ["unknown"], ["r0000", "r0000"]]:
        with pytest.raises(ValueError):
            design.case_indices(ncei, {**case, "training_record_ids": ids})
    response = ncei.response.copy()
    response[0] = np.nan
    with pytest.raises(ValueError):
        design.build_sensitivity_design(
            {**lanes, ncei.target: replace(ncei, response=response)}, metadata
        )


@pytest.mark.parametrize(
    "bad", [np.array([], dtype=float), np.zeros(1070), np.ones(1070, dtype=complex)]
)
def test_publisher_distance_arrays_must_be_real_positive_and_aligned(bad):
    lanes, metadata = synthetic_inputs()
    with pytest.raises(ValueError):
        design.build_sensitivity_design(lanes, replace(metadata, publisher_distance_km=bad))


def test_rank_deficiency_is_reported_and_cannot_enter_fixed_fit_cases():
    lanes, metadata = synthetic_inputs()
    ncei = lanes["NCEI-native-duration"]
    indices = np.flatnonzero(ncei.included)[:2]
    support = design.support_summary(ncei, "mean-curvature", indices)
    assert support["matrix_rank"] < 3 and support["full_rank"] is False
    coastal = np.zeros(len(ncei.rows), dtype=bool)
    coastal[indices] = True
    with pytest.raises(ValueError, match="design rank"):
        design.build_sensitivity_design(lanes, replace(metadata, coastal=coastal))
