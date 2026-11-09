"""Fixed historical population-posterior references for the 69 MS-5 views.

Eight full fits and six original LOSqO training fits cost no new sampler calls.
Admission hashes metadata and its closure before any NetCDF parsing. Accepted
legacy reviews retain their own checker schemas; they are not new fit approvals.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival.evidence import sha256
from analysis.arrival.model_sensitivity_summary import _validated

ART = "artifacts/models/arrival-timing/"
RAW = "data/processed/models/"
COMPARISON = ART + "curvature-sequence-predictive-comparison-v1/review-acceptance.json"
CV = ART + "mean-curvature-sequence-v1/review-acceptance.json"
CONSUMED = (
    "analysis/arrival/model_sensitivity_references.py",
    "tests/test_arrival_model_sensitivity_references.py",
    "analysis/arrival/model_sensitivity_summary.py",
    "analysis/arrival/model_sensitivity_priors.py",
    "analysis/arrival/model_sensitivity_design.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/evidence.py",
)


def descriptors() -> list[dict[str, Any]]:
    """Return fresh fixed descriptors; paths never follow a latest-fit search."""
    entries = []
    for kind, folder, raw, seed, qa, status in [
        (
            "distance-scale",
            "exploration-distance-scale-v1",
            "exploration-distance-scale-v1.nc",
            89261107,
            "distance-scale-fit-report-v1/review-acceptance.json",
            "accepted_provisional_model_criticism",
        ),
        (
            "mean-curvature",
            "exploration-mean-curvature-v1",
            "mean-curvature-fit-v1/primary.nc",
            2846110800,
            "exploration-mean-curvature-v1/review-acceptance.json",
            "accepted_actual_curvature_fit_with_conditional_ppc_inadequacy",
        ),
    ]:
        entries.append(
            dict(
                target="NCEI-native-duration",
                kind=kind,
                role="base",
                folder=ART + folder,
                raw=RAW + raw,
                seed=seed,
                records=1064,
                events=33,
                review=ART + qa,
                review_status=status,
            )
        )
    for target, records, events, seed in [
        ("T-OBS", 236, 14, 25261107),
        ("T-CAL", 156, 13, 25262107),
    ]:
        for j, kind in enumerate(["pooled", "distance", "event"]):
            entries.append(
                dict(
                    target=target,
                    kind=kind,
                    role="base",
                    records=records,
                    events=events,
                    folder=ART + f"exploration-baselines-v1/{target}/{kind}",
                    raw=RAW + f"exploration-baselines-v1/{target}/{kind}.nc",
                    seed=seed + j * 100,
                    review=ART + f"source-baseline-report-v1/{target}/review-acceptance.json",
                    review_status="accepted_provisional_exploration_fits",
                )
            )
    for (
        label,
        sequence,
        records,
        linear_base,
        linear_fold,
        curved_fold,
        linear_seed,
        curved_seed,
    ) in [
        (
            "tohoku",
            "seq-official20110311054624120_30",
            793,
            "bridge-sequence-validation-v1",
            "01",
            "002",
            1426110900,
            2856112800,
        ),
        (
            "chile2010",
            "seq-official20100227063411530_30",
            926,
            "bridge-sequence-continuation-v1",
            "02",
            "001",
            1426111900,
            2856111800,
        ),
        (
            "influential2014",
            "seq-usc000phx5",
            1060,
            "bridge-sequence-continuation-v2",
            "20",
            "008",
            1426129900,
            2856118800,
        ),
    ]:
        linear_id = f"NCEI-native-duration-distance-scale-fold-{linear_fold}-attempt-1"
        for kind, folder, raw, seed, qa, status in [
            (
                "distance-scale",
                f"{linear_base}/jobs/{linear_id}",
                f"{linear_base}/{linear_id}/00-training.nc",
                linear_seed,
                "bridge-sequence-continuation-v2/review-acceptance.json",
                "accepted_all_logical_sequence_computations",
            ),
            (
                "mean-curvature",
                f"mean-curvature-sequence-v1/jobs/fold-{curved_fold}",
                f"mean-curvature-sequence-v1/fold-{curved_fold}/00-training.nc",
                curved_seed,
                "mean-curvature-sequence-v1/continuation-v2/numerical-stop-review.json",
                "accepted_curvature_completion_overlap_stop",
            ),
        ]:
            entries.append(
                dict(
                    target="NCEI-native-duration",
                    kind=kind,
                    role=f"reuse-{label}",
                    records=records,
                    deleted_sequence=sequence,
                    folder=ART + folder,
                    raw=RAW + raw,
                    seed=seed,
                    review=ART + qa,
                    review_status=status,
                )
            )
    for entry in entries:
        entry["key"] = f"{entry['target']}:{entry['kind']}:{entry['role']}"
        entry["ensemble"] = entry["folder"] + (
            "/ensembles/00-training" if entry["role"] != "base" else ""
        )
        entry["draws"] = 2000
        entry["chains"] = 4
        entry["distance_mode"] = "geodesic_km"
        entry["prior_variant"] = "base"
        entry["new_sampler_calls"] = 0
        entry["source_role"] = (
            "full_exploration_fit"
            if entry["role"] == "base"
            else "original_LOSqO_training_not_augmented"
        )
    return entries


def _path(root, name):
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or Path(name).as_posix() != name
        or any(x in {".", ".."} for x in name.split("/"))
    ):
        raise ValueError("literal project-relative nonsymlink reference path required")
    root = root.resolve()
    path = root / name
    if path.resolve() != path or not path.is_file():
        raise ValueError("literal project-local nonsymlink reference file required")
    return path


def _unchanged(root, pins):
    if not isinstance(pins, dict) or not pins:
        raise ValueError("frozen reference pins required")
    for name, digest in pins.items():
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or sha256(_path(root, name)) != digest
        ):
            raise ValueError("reference source SHA changed")


def _require(pins, values):
    if (
        not isinstance(values, dict)
        or not values
        or any(pins.get(p) != h for p, h in values.items())
    ):
        raise ValueError("complete caller-pinned accepted reference closure required")


def _nested_pins(pins, value):
    """Close recorded source contracts without parsing any referenced outcome file."""
    if isinstance(value, dict):
        for name, item in value.items():
            if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item):
                if pins.get(name) != item:
                    raise ValueError("complete transitive source/config reference required")
            elif isinstance(item, (dict, list)):
                _nested_pins(pins, item)
    elif isinstance(value, list):
        for item in value:
            _nested_pins(pins, item)


def _json(root, pins, name):
    if name not in pins:
        raise ValueError("required literal reference metadata missing from frozen pins")
    value = json.loads(_path(root, name).read_text())
    if not isinstance(value, dict):
        raise ValueError("reference metadata object required")
    return value


def _manifest(root, pins, folder):
    name = folder + "/output-checksums.json"
    manifest = _json(root, pins, name)
    # Local keys are canonical relative children; caller pins close every output.
    refs = {}
    for child, digest in manifest.items():
        _path(root, folder + "/" + child)
        refs[folder + "/" + child] = digest
    _require(pins, refs)
    if "inputs.json" not in manifest:
        raise ValueError("accepted manifest must pin its source inputs")
    return manifest


def verify_reference_sources(root: Path, pins: dict[str, str]) -> None:
    """Verify all 14 fixed metadata closures before opening any posterior."""
    root = root.resolve()
    _unchanged(root, pins)
    if not set(CONSUMED) | {COMPARISON, CV} <= set(pins):
        raise ValueError("reference consumer and closed comparison prerequisites required")
    for name, status in [
        (COMPARISON, "accepted_curvature_sequence_predictive_comparison"),
        (CV, "accepted_all_curvature_sequence_computations"),
    ]:
        review = _json(root, pins, name)
        if (
            review.get("status") != status
            or review.get("independent_checker") is not True
            or review.get("confirmation_outcomes_parsed") is not False
            or review.get("reserved_outcomes") != "sealed"
        ):
            raise ValueError("accepted closed comparison/CV required before reference loading")
        _require(pins, review.get("files"))
        if name == COMPARISON and review["files"].get(CV) != pins[CV]:
            raise ValueError("comparison must pin the same accepted complete CV")
    source_contract = None
    for ref in descriptors():
        review = _json(root, pins, ref["review"])
        if review.get("status") != ref["review_status"]:
            raise ValueError("literal legacy reference acceptance status required")
        if ref["kind"] == "mean-curvature":
            if review.get("independent_checker") is not True:
                raise ValueError("known curvature independent review schema required")
        elif ref["role"] != "base":
            if review.get("independent_checker") != "/root/ms3_fit_checker":
                raise ValueError("known legacy bridge checker schema required")
        elif review.get("checker", review.get("posterior_checker")) != "/root/ms3_fit_checker":
            raise ValueError("known legacy full-fit checker schema required")
        if "files" in review:
            _require(pins, review["files"])
            required = {ref["raw"]} | {
                ref["ensemble"] + "/" + name for name in ["result.json", "job.json", "inputs.json"]
            }
            if ref["role"] != "base":
                required |= {
                    ref["folder"] + "/membership.json",
                    ref["ensemble"] + "/membership.json",
                }
            if not required <= set(review["files"]):
                raise ValueError("accepted review must pin literal posterior and source metadata")
        else:
            report_folder = str(Path(ref["review"]).parent)
            manifest = _manifest(root, pins, report_folder)
            expected = review.get("report_manifest_sha256", review.get("manifest_sha256"))
            if (
                expected != pins[report_folder + "/output-checksums.json"]
                or manifest["inputs.json"] != pins[report_folder + "/inputs.json"]
            ):
                raise ValueError("legacy report manifest acceptance binding required")
            report_inputs = _json(root, pins, report_folder + "/inputs.json")
            _require(pins, report_inputs)
            required = {
                ref["raw"],
                ref["folder"] + "/result.json",
                ref["folder"] + "/output-checksums.json",
            }
            if not required <= set(report_inputs):
                raise ValueError(
                    "accepted report must pin original posterior/result/output manifest"
                )
        result = _json(root, pins, ref["ensemble"] + "/result.json")
        job = _json(root, pins, ref["ensemble"] + "/job.json")
        inputs = _json(root, pins, ref["ensemble"] + "/inputs.json")
        if (
            result.get("posterior") != ref["raw"]
            or ref["raw"] not in pins
            or result.get("posterior_sha256") != pins[ref["raw"]]
        ):
            raise ValueError("literal original result/raw/caller SHA binding required")
        if (
            result.get("job") != job
            or job.get("target") != ref["target"]
            or job.get("kind") != ref["kind"]
            or job.get("seed") != ref["seed"]
            or job.get("draws") != 2000
            or job.get("tune") != 1000
            or job.get("cores") != 2
            or job.get("prior", "base") != "base"
            or result.get("records") != ref["records"]
            or result.get("diagnostics", {}).get("screen_passed") is not True
        ):
            raise ValueError("original source-specific base-prior job/cohort required")
        _nested_pins(pins, inputs)
        _nested_pins(pins, result.get("code_and_config", {}))
        contract = inputs.get("source_files")
        if (
            not isinstance(contract, dict)
            or not contract
            or (source_contract is not None and contract != source_contract)
        ):
            raise ValueError("same frozen three-lane native source contract required")
        source_contract = contract
        if ref["role"] == "base":
            if (
                result.get("status") != "computed_pending_scientific_review"
                or result.get("events") != ref["events"]
            ):
                raise ValueError("accepted full exploration result required")
            manifest = _manifest(root, pins, ref["folder"])
            if not {"result.json", "job.json", "inputs.json"} <= set(manifest):
                raise ValueError("full original fit manifest required")
        else:
            membership = _json(root, pins, ref["folder"] + "/membership.json")
            ensemble_membership = _json(root, pins, ref["ensemble"] + "/membership.json")
            train, held = membership.get("train"), membership.get("test")
            if (
                not isinstance(train, list)
                or not isinstance(held, list)
                or not all(isinstance(record, str) and record for record in train + held)
                or len(train) != ref["records"]
                or len(train) + len(held) != 1064
                or len(set(train + held)) != 1064
            ):
                raise ValueError("complete unique disjoint1064-record deletion partition required")
            if (
                job.get("phase") != "training"
                or job.get("event") is not None
                or job.get("sequence") != ref["deleted_sequence"]
                or membership.get("sequence") != ref["deleted_sequence"]
                or ensemble_membership.get("included") != membership.get("train")
            ):
                raise ValueError("literal whole-sequence original training membership required")
    _unchanged(root, pins)


def load_reference(root: Path, key: str, lanes, pins: dict[str, str]):
    """Return coherent lane, kind, indices, explicit population and provenance.

    This read-only view preserves literal chain/draw ordering. Consumers choose
    their frozen prediction seed and retain the summary's Monte Carlo limits.
    """
    registry = {ref["key"]: ref for ref in descriptors()}
    if key not in registry:
        raise ValueError("one fixed historical sensitivity reference key required")
    verify_reference_sources(root, pins)
    ref = registry[key]
    lane = lanes[ref["target"]]
    primary = np.flatnonzero(lane.included)
    expected_full = {"NCEI-native-duration": 1064, "T-OBS": 236, "T-CAL": 156}[ref["target"]]
    expected_events = {"NCEI-native-duration": 33, "T-OBS": 14, "T-CAL": 13}[ref["target"]]
    if (
        lane.target != ref["target"]
        or len(primary) != expected_full
        or len(set(lane.record_ids)) != len(lane.record_ids)
        or len({lane.event_ids[int(i)] for i in primary}) != expected_events
    ):
        raise ValueError("canonical full native source cohort required")
    indices = primary
    if ref["role"] != "base":
        indices = primary[np.asarray(lane.sequences)[primary] != ref["deleted_sequence"]]
        held = primary[np.asarray(lane.sequences)[primary] == ref["deleted_sequence"]]
        membership = _json(root, pins, ref["folder"] + "/membership.json")
        if membership.get("train") != [lane.record_ids[int(i)] for i in indices] or membership.get(
            "test"
        ) != [lane.record_ids[int(i)] for i in held]:
            raise ValueError("ordered canonical cohort minus whole deleted sequence required")
    if len(indices) != ref["records"]:
        raise ValueError("literal reference training count required")
    raw = _path(root, ref["raw"])
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        if observed.record.values.tolist() != [
            lane.record_ids[int(i)] for i in indices
        ] or not np.array_equal(observed.response.values, lane.response[indices]):
            raise ValueError("posterior observed native membership/response mismatch")
        if "native_minutes" in observed and not np.array_equal(
            observed.native_minutes.values, lane.y[indices]
        ):
            raise ValueError("posterior native-minute identity mismatch")
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as saved:
        if saved.sizes.get("chain") != 4 or saved.sizes.get("draw") != 2000:
            raise ValueError("literal original four-chain2000draw reference required")
        # Validate/select only explicit population variables; old reconstructed u
        # and derived variables are not inputs to the new conditional summary.
        hyper, _ = _validated(lane, ref["kind"], saved, indices, 0, 800)
        posterior = saved[list(hyper)].load()
    mask = np.zeros(len(lane.rows), dtype=bool)
    mask[indices] = True
    provenance = {
        **ref,
        "posterior_sha256": pins[ref["raw"]],
        "review_sha256": pins[ref["review"]],
        "training_record_ids": [lane.record_ids[int(i)] for i in indices],
        "source_metadata": {
            ref["ensemble"] + "/" + name: pins[ref["ensemble"] + "/" + name]
            for name in ["result.json", "job.json", "inputs.json"]
        },
        "verified_pin_count": len(pins),
        "verified_pins_sha256": hashlib.sha256(
            json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "status": "historical_reference_only_no_new_fit",
        "quantile_precision": (
            "finite_posterior_and800_prediction_draws_do_not_certify_tiny_shift_materiality"
        ),
    }
    if ref["role"] != "base":
        for name in [ref["folder"] + "/membership.json", ref["ensemble"] + "/membership.json"]:
            provenance["source_metadata"][name] = pins[name]
    _unchanged(root, pins)
    return replace(lane, included=mask), ref["kind"], indices, posterior, provenance
