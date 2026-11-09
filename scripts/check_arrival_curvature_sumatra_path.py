"""Bounded independent numerical checks for the retained 49-report Sumatra path."""

# pyright: basic
from __future__ import annotations

import json
import math
import resource
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.linalg import cho_factor, cho_solve
from scipy.stats import halfnorm, norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_bridge_path import path_score  # noqa: E402
from analysis.arrival.model_bridge_sampling import bridge_indices  # noqa: E402
from analysis.arrival.model_curvature import build_curvature_model  # noqa: E402
from analysis.arrival.model_curvature_path import (  # noqa: E402
    build_curvature_path,
    curvature_held_loglikelihood,
)
from analysis.arrival.model_curvature_prior import read_curvature_prior  # noqa: E402
from analysis.arrival.model_curvature_resolution import resolved_path_result  # noqa: E402
from analysis.arrival.model_data import load_lanes  # noqa: E402
from analysis.arrival.model_scoring import mean_mcse  # noqa: E402

SOURCE = "artifacts/models/arrival-timing/mean-curvature-sequence-v1/jobs/fold-019"
STOP = (
    "artifacts/models/arrival-timing/mean-curvature-sequence-v1/continuation-v2/"
    "numerical-stop-review.json"
)
STOP_SHA = "60515491fc0f00b8734a736a60ac2719d7f94cf3b068991037ad6afd94ef15a1"
OUTPUT = (
    "artifacts/models/arrival-timing/mean-curvature-sumatra-path-design-v1/numerical-oracles.json"
)
COUNTS = {"usp000exfn": 49, "usp000f2ab": 22, "usp000gsmz": 9}
TIMES = (0.0, 1 / 256, 0.25, 225 / 256, 1.0)
POINTS = (
    (0.1, -0.05, 0.4, 0.2, 0.6, 0.3, 0.12),
    (-0.12, 0.08, 0.7, 0.08, 0.4, 0.22, 0.09),
)


def point_dict(vector):
    """The production model's seven unconstrained coordinates, in model order."""
    return {
        "alpha": np.array(vector[0]),
        "beta": np.array(vector[1]),
        "gamma": np.array(vector[2]),
        "tau_event_log__": np.array(vector[3]),
        "sigma_anchor_log__": np.array(vector[4:]),
    }


def dense_event(lane, ids, vector):
    """Direct Cholesky Normal density; independent of production marginal algebra."""
    a, b, g = vector[:3]
    tau, anchors = np.exp(vector[3]), np.exp(vector[4:])
    distance = lane.distance_km[ids]
    sd = np.interp(np.log(distance), np.log([500, 2000, 5000]), anchors)
    mean = a + b * np.log(distance / 1000) + g * np.log((distance + 500) / (1.5 * distance))
    residual = lane.response[ids] - mean
    covariance = np.diag(sd**2) + tau**2 * np.ones((len(ids), len(ids)))
    factor = cho_factor(covariance, lower=True)
    return float(
        -0.5
        * (
            len(ids) * np.log(2 * np.pi)
            + 2 * np.log(np.diag(factor[0])).sum()
            + residual @ cho_solve(factor, residual)
        )
    )


def dense_logp(lane, training, held, vector, temperature):
    """Independent event blocks, explicit proper priors and log-scale Jacobians."""
    total = norm.logpdf(vector[:3], scale=[0.5, 0.25, 0.5]).sum()
    total += halfnorm.logpdf(np.exp(vector[3:]), scale=0.4).sum() + vector[3:].sum()
    for event in sorted({lane.event_ids[int(i)] for i in training}):
        ids = np.array([i for i in training if lane.event_ids[int(i)] == event])
        total += dense_event(lane, ids, vector)
    return float(total + temperature * dense_event(lane, held, vector))


def covariance_oracle(native):
    """Exercise nonzero common-training covariance for the exact 49/22/9 design."""
    rng = np.random.default_rng(2856129919)
    shared = rng.normal(size=(4, 2000)) * 0.03
    influences = [shared] + [rng.normal(size=shared.shape) * 0.01 for _ in range(16)]
    arrays = {
        "training_influence_001": 0.7 * shared + rng.normal(size=shared.shape) * 0.003,
        "training_influence_002": 0.4 * shared + rng.normal(size=shared.shape) * 0.002,
        "augmented_influence_001": rng.normal(size=shared.shape) * 0.01,
        "augmented_influence_002": rng.normal(size=shared.shape) * 0.01,
    }
    jacobian = float(np.log(native).sum())
    primary = {
        "kind": "mean-curvature",
        "target": "NCEI-native-duration",
        "event_id": "usp000exfn",
        "sequence": "seq-usp000exfn",
        "records": 49,
        "source_training_posterior_sha": "a" * 64,
        "precision_passed": True,
        "joint_log_predictive": -245.0,
        "normalized_event_score": -5.0,
        "joint_log_mcse_delta": math.sqrt(sum(mean_mcse(a) ** 2 for a in influences)),
        "native_jacobian_subtracted_once": jacobian,
        "method": "synthetic_oracle_only",
    }
    primary["normalized_mcse"] = primary["joint_log_mcse_delta"] / 49
    original = {
        "status": "precision_failure",
        "prediction_precision_passed": True,
        "job": {"kind": "mean-curvature", "target": "NCEI-native-duration", "prior": "base"},
        "observation_measure": "native_minutes_Jacobian_already_applied_once",
        "events": [
            {
                "event_id": e,
                "sequence": "seq-usp000exfn",
                "records": n,
                "precision_passed": e != "usp000exfn",
                "normalized_event_score": -5.0 - j,
            }
            for j, (e, n) in enumerate(COUNTS.items())
        ],
    }
    repeat = {
        "agreement_passed": True,
        "primary_designated_before_fitting": True,
        "score_to_use": "primary_never_select_favorable_repeat",
    }
    result = resolved_path_result(
        original, primary, repeat, influences, arrays, native, training_sha="a" * 64
    )
    shared_vector = (
        influences[0] / 49
        + arrays["training_influence_001"] / 22
        + arrays["training_influence_002"] / 9
    ) / 3
    independent = sum((mean_mcse(a) / 49 / 3) ** 2 for a in influences[1:])
    independent += (mean_mcse(arrays["augmented_influence_001"]) / 22 / 3) ** 2
    independent += (mean_mcse(arrays["augmented_influence_002"]) / 9 / 3) ** 2
    expected = math.sqrt(mean_mcse(shared_vector) ** 2 + independent)
    actual = result["fold_score"]["mcse_equal_event_score"]
    np.testing.assert_allclose(actual, expected, rtol=1e-14)
    wrong_double = math.sqrt(expected**2 + (mean_mcse(influences[0]) / 49 / 3) ** 2)
    wrong_independent = math.sqrt(
        sum((mean_mcse(a) / 49 / 3) ** 2 for a in influences)
        + sum(
            (mean_mcse(arrays[f"{role}_influence_{j:03d}"]) / n / 3) ** 2
            for j, n in [(1, 22), (2, 9)]
            for role in ["training", "augmented"]
        )
    )
    assert expected > 0 and not math.isclose(actual, wrong_double, rel_tol=1e-5)
    assert not math.isclose(actual, wrong_independent, rel_tol=1e-5)
    for altered_sha, altered_arrays in [
        ("b" * 64, arrays),
        ("a" * 64, {**arrays, "training_influence_001": shared[:, :-1]}),
    ]:
        try:
            resolved_path_result(
                original,
                primary,
                repeat,
                influences,
                altered_arrays,
                native,
                training_sha=altered_sha,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("wrong training SHA or chain/draw shape accepted")
    return {
        "synthetic_only": True,
        "shape": [4, 2000],
        "records": [49, 22, 9],
        "actual_mcse": actual,
        "independent_assembly_mcse": expected,
        "incorrect_independent_training_mcse": wrong_independent,
        "incorrect_double_counted_t0_mcse": wrong_double,
        "wrong_training_sha_and_shape_rejected": True,
    }


def source_design(root):
    """Verify the accepted receipt and protected files before parsing source outcomes."""
    if sha256(root / STOP) != STOP_SHA:
        raise ValueError("accepted original stop receipt changed")
    stop = json.loads((root / STOP).read_text())
    if stop["status"] != "accepted_curvature_completion_overlap_stop" or len(stop["files"]) != 2980:
        raise ValueError("accepted original stop receipt required")
    for name, digest in stop["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError(f"protected source changed: {name}")
    lanes, frozen = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    training, fold = bridge_indices(lane, "seq-usp000exfn", "training", None)
    held = np.array([i for i in fold.test if lane.event_ids[int(i)] == "usp000exfn"])
    counts = {e: sum(lane.event_ids[int(i)] == e for i in fold.test) for e in COUNTS}
    assert counts == COUNTS and len(training) == 984 and len(fold.test) == 80
    assert not set(training) & set(fold.test)
    assert not set(lane.event_ids[int(i)] for i in training) & set(COUNTS)
    membership = json.loads((root / SOURCE / "membership.json").read_text())
    assert membership["train"] == [lane.record_ids[int(i)] for i in training]
    assert membership["test"] == [lane.record_ids[int(i)] for i in fold.test]
    endpoints = []
    for j, (event, _) in enumerate([(None, None), *COUNTS.items()]):
        name = "00-training" if j == 0 else f"{j:02d}-augmented"
        result_path = root / SOURCE / "ensembles" / name / "result.json"
        result = json.loads(result_path.read_text())
        raw = checked_path(root, result["posterior"])
        assert stop["files"][result["posterior"]] == result["posterior_sha256"] == sha256(raw)
        assert result["diagnostics"]["screen_passed"] is True
        ids, _ = bridge_indices(
            lane, "seq-usp000exfn", "training" if j == 0 else "augmented", event
        )
        with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
            assert observed.record.values.tolist() == [lane.record_ids[int(i)] for i in ids]
            np.testing.assert_array_equal(observed.response.values, lane.response[ids])
            np.testing.assert_array_equal(observed.native_minutes.values, lane.y[ids])
        with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as posterior:
            assert posterior.sizes["chain"] == 4 and posterior.sizes["draw"] == 2000
            assert posterior.chain.values.tolist() == list(range(4))
            assert posterior.draw.values.tolist() == list(range(2000))
            for variable in ["alpha", "beta", "gamma", "tau_event"]:
                assert posterior[variable].dims == ("chain", "draw")
                assert np.isfinite(posterior[variable].values).all()
            assert posterior.sigma_anchor.dims == ("chain", "draw", "scale_anchor_km")
            assert np.isfinite(posterior.sigma_anchor.values).all()
            assert posterior.scale_anchor_km.values.tolist() == [500, 2000, 5000]
        endpoints.append(
            {
                "name": name,
                "posterior": result["posterior"],
                "sha256": result["posterior_sha256"],
                "records": len(ids),
                "chain_draw_order_validated": True,
            }
        )
    return lane, training, held, frozen, endpoints


def report(root):
    lane, training, held, frozen, endpoints = source_design(root)
    prior = read_curvature_prior(root, "base")
    assert [prior[k] for k in ["alpha_sd", "beta_sd", "gamma_sd", "tau_sd", "sigma_sd"]] == [
        0.5,
        0.25,
        0.5,
        0.4,
        0.4,
    ]
    vectors = [np.r_[p[:3], np.log(p[3:])] for p in POINTS]
    checks = []
    for temperature in TIMES:
        model = build_curvature_path(lane, prior, training, held, temperature)
        logp, gradient = model.compile_logp(), model.compile_dlogp()
        for j, vector in enumerate(vectors):
            point = point_dict(vector)
            actual = float(logp(point))
            expected = dense_logp(lane, training, held, vector, temperature)
            finite_difference = []
            for coordinate in range(7):
                delta = np.eye(7)[coordinate] * 1e-5
                finite_difference.append(
                    (
                        dense_logp(lane, training, held, vector + delta, temperature)
                        - dense_logp(lane, training, held, vector - delta, temperature)
                    )
                    / 2e-5
                )
            error = np.asarray(gradient(point)) - finite_difference
            np.testing.assert_allclose(actual, expected, atol=2e-8, rtol=0)
            np.testing.assert_allclose(gradient(point), finite_difference, atol=5e-5, rtol=5e-7)
            checks.append(
                {
                    "temperature": temperature,
                    "point": j,
                    "dense_logp_error_nat": actual - expected,
                    "seven_gradient_errors": error.tolist(),
                }
            )
    held_checks = []
    for j, vector in enumerate(vectors):
        posterior = xr.Dataset(
            {
                k: (("chain", "draw"), np.full((1, 1), value))
                for k, value in zip(
                    ["alpha", "beta", "gamma", "tau_event"],
                    [*vector[:3], np.exp(vector[3])],
                    strict=True,
                )
            }
        )
        posterior["sigma_anchor"] = xr.DataArray(
            np.exp(vector[4:])[None, None, :],
            dims=("chain", "draw", "scale_anchor_km"),
            coords={"scale_anchor_km": [500, 2000, 5000]},
        )
        error = float(curvature_held_loglikelihood(lane, held, posterior)[0, 0]) - dense_event(
            lane, held, vector
        )
        assert abs(error) < 1e-8
        held_checks.append({"point": j, "dense_49_by_49_error_nat": error})
    altered_response, altered_distance = lane.response.copy(), lane.distance_km.copy()
    altered_response[held] += 123.0
    altered_distance[held] *= 1.37
    altered = replace(lane, response=altered_response, distance_km=altered_distance)
    zero = build_curvature_path(lane, prior, training, held, 0).compile_logp()
    altered_zero = build_curvature_path(altered, prior, training, held, 0).compile_logp()
    one = build_curvature_path(lane, prior, training, held, 1).compile_logp()
    augmented = build_curvature_model(
        lane, prior, indices=np.sort(np.r_[training, held])
    ).compile_logp()
    endpoint_errors = []
    for vector in vectors:
        assert float(zero(point_dict(vector))) == float(altered_zero(point_dict(vector)))
        error = float(one(point_dict(vector)) - augmented(point_dict(vector)))
        assert abs(error) < 2e-8
        endpoint_errors.append(error)
    try:
        build_curvature_path(lane, prior, np.r_[training, held[:1]], held, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("held event in training accepted")
    native = lane.y[held]
    assert len(native) == 49 and np.isfinite(native).all() and (native > 0).all()
    jacobian = float(sum(math.log(float(y)) for y in native))
    logs = [np.full((4, 2000), -49.0) for _ in range(17)]
    telescope, _ = path_score(logs, (np.arange(17) / 16) ** 2, records=49, jacobian=jacobian)
    assert abs(telescope["joint_log_predictive"] - (-49 - jacobian)) < 1e-10
    files = [
        STOP,
        f"{SOURCE}/membership.json",
        f"{SOURCE}/result.json",
        "scripts/check_arrival_curvature_sumatra_path.py",
        "tests/test_arrival_curvature_sumatra_path_math.py",
        "analysis/arrival/model_curvature_path.py",
        "analysis/arrival/model_bridge_path.py",
        "analysis/arrival/model_curvature_resolution.py",
        "analysis/arrival/model_path_fold_resolution.py",
    ]
    return {
        "status": "computed_pending_independent_review",
        "scope": "numerical_design_oracles_only",
        "files": {name: sha256(root / name) for name in files},
        "source_contract": frozen,
        "accepted_stop_sha256": STOP_SHA,
        "protected_pins_verified": 2980,
        "training_records": 984,
        "purged_records": 80,
        "held_records": COUNTS,
        "path_augmented_records": 1033,
        "other_held_records_absent_from_path": 31,
        "original_four_ensembles": endpoints,
        "representative_points": [list(p) for p in POINTS],
        "dense_path_and_gradient_checks": checks,
        "held_density_checks": held_checks,
        "t0_held_response_and_distance_invariance": True,
        "t1_old_augmented_model_errors_nat": endpoint_errors,
        "purged_held_event_guard_rejected": True,
        "native_jacobian_49": jacobian,
        "native_jacobian_subtracted_once": True,
        "native_jacobian_absent_inside_powered_response_path": True,
        "native_telescope_oracle": telescope["joint_log_predictive"],
        "nonzero_three_event_mcse_oracle": covariance_oracle(native),
        "bounds": {
            "points": 2,
            "temperatures": 5,
            "coordinates": 7,
            "finite_difference_step": 1e-5,
            "largest_held_dense_block": 49,
            "training_dense_matrix": "separate_event_blocks_only",
            "cli_cpu_seconds": 300,
            "cli_per_file_bytes": 64 * 1024**2,
            "json_output_bytes": 1024**2,
        },
        "new_path_node_caches_checked": False,
        "sampler_calls": 0,
        "failed_score_accepted": False,
        "score_promoted": False,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "limitations": [
            "No new path fits or caches exist; these are mathematical design checks.",
            "Finite representative-point checks do not prove global numerical accuracy.",
            "Equal-shape draw reordering needs endpoint hashes and coordinate/membership checks; "
            "the pure assembler cannot detect it.",
        ],
    }


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    root = Path(__file__).resolve().parents[1]
    result = report(root)
    assert len(json.dumps(result, allow_nan=False).encode()) <= 1024**2
    write_json(root / OUTPUT, result)
    print(OUTPUT)
