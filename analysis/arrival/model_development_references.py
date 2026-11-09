"""Literal original base-prior training references for the frozen development check.

No fitting or scoring occurs here. A changed prior/cohort requires a separately
registered frozen training fit; a convenient full or augmented fit is no substitute.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival import model_development_data as data
from analysis.arrival import model_sensitivity_references as historical
from analysis.arrival.evidence import read_rows
from analysis.arrival.model_data import lane_arrays
from analysis.arrival.model_sensitivity_summary import _validated

CONSUMED = (
    "analysis/arrival/model_development_references.py",
    "tests/test_arrival_model_development_references.py",
    *historical.CONSUMED,
)


class RequiresNewFrozenTrainingFit(ValueError):
    """No exact admitted base-prior training posterior can serve this frozen view."""


def _native_protocol(posterior, sample_stats):
    """Validate original sampler metadata without adding provenance attributes."""
    try:
        config = json.loads(sample_stats.attrs["inference_library_settings"])
        settings = config["settings"]
        actual = {
            "sampler": config["sampler"],
            "tune": settings["num_tune"],
            "draws": settings["num_draws"],
            "chains": settings["num_chains"],
            "target_accept": settings["adapt_options"]["step_size_settings"]["target_accept"],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("complete original native nutpie sampler settings required") from error
    if (
        any(
            group.attrs.get("inference_library") != "nutpie"
            or group.attrs.get("inference_library_version") != "0.16.11"
            for group in [posterior, sample_stats]
        )
        or type(posterior.attrs.get("tuning_steps")) not in {int, np.int32, np.int64}
        or posterior.attrs.get("tuning_steps") != 1000
        or any(type(actual[k]) is not int for k in ["tune", "draws", "chains"])
        or actual
        != {"sampler": "nuts", "tune": 1000, "draws": 2000, "chains": 4, "target_accept": 0.95}
        or any(
            group.sizes.get("chain") != 4
            or group.sizes.get("draw") != 2000
            or group.chain.values.tolist() != list(range(4))
            or group.draw.values.tolist() != list(range(2000))
            for group in [posterior, sample_stats]
        )
    ):
        raise ValueError("genuine native nutpie backend/version/protocol/coordinates required")


def _reference(target, kind) -> dict[str, Any]:
    if target != "NCEI-native-duration":
        return next(
            ref
            for ref in historical.descriptors()
            if ref["target"] == target and ref["kind"] == kind and ref["role"] == "base"
        )
    if kind == "distance-scale":
        name = "NCEI-native-duration-distance-scale-fold-11-attempt-1"
        folder = data.ART + "bridge-sequence-continuation-v2/jobs/" + name
        raw = "data/processed/models/bridge-sequence-continuation-v2/" + name + "/00-training.nc"
        review = data.ART + "bridge-sequence-continuation-v2/review-acceptance.json"
        status, checker, seed = (
            "accepted_all_logical_sequence_computations",
            "/root/ms3_fit_checker",
            1426120900,
        )
    else:
        folder = data.ART + "mean-curvature-sequence-v1/jobs/fold-014"
        raw = "data/processed/models/mean-curvature-sequence-v1/fold-014/00-training.nc"
        review = data.ART + "mean-curvature-sequence-v1/review-acceptance.json"
        status, checker, seed = "accepted_all_curvature_sequence_computations", True, 2856124800
    return dict(
        target=target,
        kind=kind,
        folder=folder,
        ensemble=folder + "/ensembles/00-training",
        raw=raw,
        review=review,
        review_status=status,
        checker=checker,
        records=1040,
        seed=seed,
    )


def _proof(root, pins, freeze, key, ref):
    bindings = freeze.get("training_references", {})
    if not isinstance(bindings, dict) or key not in bindings:
        raise RequiresNewFrozenTrainingFit(
            "requires_new_frozen_training_fit: no frozen reference binding"
        )
    binding = bindings[key]
    expected = {
        "raw": ref["raw"],
        "review": ref["review"],
        **{name: ref["ensemble"] + "/" + name + ".json" for name in ["job", "inputs", "result"]},
        "membership": None
        if ref["target"] != "NCEI-native-duration"
        else ref["ensemble"] + "/membership.json",
    }
    if (
        not isinstance(binding, dict)
        or set(binding) != {*expected, "files"}
        or any(binding[name] != value for name, value in expected.items())
    ):
        raise ValueError(
            "literal original training reference paths required; never augmented/later fits"
        )
    proof = binding["files"]
    data._require(pins, proof)
    data._require(freeze["files"], proof)
    required = set(CONSUMED) | {value for value in expected.values() if value is not None}
    if not required <= set(proof):
        raise ValueError("full frozen training-reference consumer/source closure required")
    review = data._json(root, proof, ref["review"])
    if review.get("status") != ref["review_status"]:
        raise ValueError("accepted literal reference producer status required")
    if ref["target"] == "NCEI-native-duration":
        if review.get("independent_checker") != ref["checker"]:
            raise ValueError("known original numerical review checker schema required")
        data._require(proof, review.get("files"))
        required |= {ref["folder"] + "/membership.json"}
        if not required - set(CONSUMED) - {ref["review"]} <= set(review["files"]):
            raise ValueError("accepted QA must bind raw and full original training metadata")
    else:
        if review.get("checker") != "/root/ms3_fit_checker":
            raise ValueError("known legacy NTWC full-fit review checker required")
        report = str(Path(ref["review"]).parent)
        historical._manifest(root, proof, report)
        if review.get("report_manifest_sha256") != proof[report + "/output-checksums.json"]:
            raise ValueError("legacy acceptance-to-report manifest binding required")
        report_inputs = data._json(root, proof, report + "/inputs.json")
        data._require(proof, report_inputs)
        if not {
            ref["raw"],
            ref["ensemble"] + "/result.json",
            ref["ensemble"] + "/output-checksums.json",
        } <= set(report_inputs):
            raise ValueError("accepted NTWC raw/result/output manifest closure required")
        historical._manifest(root, proof, ref["ensemble"])
    result = data._json(root, proof, expected["result"])
    job = data._json(root, proof, expected["job"])
    inputs = data._json(root, proof, expected["inputs"])
    historical._nested_pins(proof, inputs)
    historical._nested_pins(proof, result.get("code_and_config", {}))
    if (
        result.get("job") != job
        or result.get("posterior") != ref["raw"]
        or result.get("posterior_sha256") != proof[ref["raw"]]
        or result.get("records") != ref["records"]
        or result.get("diagnostics", {}).get("screen_passed") is not True
    ):
        raise ValueError("original training result/raw SHA/cohort/diagnostic binding required")
    if (
        any(
            job.get(name) != value
            for name, value in dict(
                target=ref["target"],
                kind=ref["kind"],
                seed=ref["seed"],
                draws=2000,
                tune=1000,
                cores=2,
            ).items()
        )
        or job.get("prior", "base") != "base"
    ):
        raise ValueError("identical original source-specific base-prior job required")
    if ref["target"] == "NCEI-native-duration" and (
        job.get("phase") != "training"
        or job.get("event") is not None
        or job.get("sequence") != data.CROSS_SEQUENCE
    ):
        raise ValueError("literal crossing-purged training phase required")
    return proof, inputs


def load_frozen_training_reference(
    root: Path, model_key: str, training_lane, pins
) -> tuple[xr.Dataset, dict[str, Any]]:
    """Return explicit population draws and provenance after protected admission.

    model_key is ``target:kind:role``, with role selected or runner_up. Only exact
    unchanged base priors can reuse these original four-chain2000draw ensembles.
    """
    freeze, contract, roles, sequences = data.verify_development_sources(root, pins)
    specs = {
        f"{target}:{spec['kind']}:{spec['role']}": (target, spec)
        for target, entries in freeze["models"].items()
        for spec in entries
    }
    if model_key not in specs:
        raise ValueError("exact frozen selected/runner-up model key required")
    target, spec = specs[model_key]
    if spec["prior_variant"] != "base":
        raise RequiresNewFrozenTrainingFit("requires_new_frozen_training_fit: nonbase frozen prior")
    ref = _reference(target, spec["kind"])
    proof, inputs = _proof(root, pins, freeze, model_key, ref)
    if inputs.get("source_files") != contract:
        raise ValueError("same full frozen exploration source parent required before NetCDF")
    source = lane_arrays(
        target,
        read_rows(data._path(root, data.TARGET_FILES[target])),
        sequences,
        roles["exploration"],
    )
    check_sequences = {sequences[event] for event in roles["confirmation"]}
    wanted = source.included & ~np.isin(source.sequences, sorted(check_sequences))
    if (
        training_lane.target != target
        or training_lane.record_ids != source.record_ids
        or not np.array_equal(training_lane.included, wanted)
        or int(wanted.sum()) != ref["records"]
    ):
        raise RequiresNewFrozenTrainingFit(
            "requires_new_frozen_training_fit: exact frozen training cohort unavailable"
        )
    for name in [
        "event_ids",
        "site_ids",
        "sequences",
        "y",
        "response",
        "distance_km",
        "reference_minutes",
        "x",
    ]:
        if not np.array_equal(getattr(training_lane, name), getattr(source, name)):
            raise ValueError("supplied training lane differs from literal frozen native source")
    indices = np.flatnonzero(wanted)
    record_ids = [source.record_ids[int(i)] for i in indices]
    if target == "NCEI-native-duration":
        membership = data._json(root, proof, ref["ensemble"] + "/membership.json")
        parent = data._json(root, proof, ref["folder"] + "/membership.json")
        removed = [source.record_ids[int(i)] for i in np.flatnonzero(source.included & ~wanted)]
        if (
            membership.get("included") != record_ids
            or parent.get("train") != record_ids
            or parent.get("test") != removed
            or parent.get("sequence") != data.CROSS_SEQUENCE
        ):
            raise ValueError("exact ordered original24-row crossing deletion membership required")
    raw = data._path(root, ref["raw"])
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        if observed.record.values.tolist() != record_ids or not np.array_equal(
            observed.response.values, source.response[indices]
        ):
            raise ValueError("raw observed training IDs/response differ from frozen cohort")
        native_present = "native_minutes" in observed
        if native_present and not np.array_equal(observed.native_minutes.values, source.y[indices]):
            raise ValueError("raw observed native minutes differ from frozen training source")
    with (
        xr.open_dataset(raw, group="posterior", engine="h5netcdf") as saved,
        xr.open_dataset(raw, group="sample_stats", engine="h5netcdf") as sample_stats,
    ):
        _native_protocol(saved, sample_stats)
        hyper, _ = _validated(training_lane, spec["kind"], saved, indices, 0, 800)
        population = saved[list(hyper)].load()
    data._unchanged(root, pins)
    provenance = dict(
        model_key=model_key,
        source_role="original_frozen_training_reference_no_new_fit",
        raw=ref["raw"],
        raw_sha256=pins[ref["raw"]],
        review=ref["review"],
        review_sha256=pins[ref["review"]],
        training_record_ids=record_ids,
        prior_variant="base",
        distance_mode="geodesic_km",
        raw_native_minutes_present=native_present,
        native_identity_source=data.TARGET_FILES[target],
        verified_pin_count=len(pins),
        verified_pins_sha256=hashlib.sha256(
            json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        new_sampler_calls=0,
        scoring_performed=False,
    )
    return population, provenance
