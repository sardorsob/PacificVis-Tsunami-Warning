"""Seeded pure-math development-score oracles; no loaders, fits or actual outcomes."""

# pyright: basic
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest
import xarray as xr
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from analysis.arrival import model_development_scoring as scoring
from analysis.arrival.model_data import lane_arrays
from analysis.arrival.model_scoring import mean_mcse
from analysis.arrival.model_sensitivity_design import FORMS


def lane(target="NCEI-native-duration"):
    distance = [100, 900, 4000, 500, 12000]
    rows = [
        dict(
            record_id=f"record-{i}",
            event_id="event-a" if i < 3 else "event-b",
            physical_site_id=f"site-{i}",
            target=target,
            distance_km=str(d),
            target_minutes=str([-7, 0, 11, -2, 8][i] if target == "T-CAL" else 15 + 10 * i),
        )
        for i, d in enumerate(distance)
    ]
    return lane_arrays(
        target, rows, {"event-a": "seq-a", "event-b": "seq-b"}, {"event-a", "event-b"}
    )


def posterior(kind, *, draws=160):
    rng = np.random.default_rng(9117)
    variables: dict[str, Any] = {"alpha": (("chain", "draw"), rng.normal(0, 0.1, (4, draws)))}
    if kind != "pooled":
        variables["beta"] = (("chain", "draw"), rng.normal(0, 0.03, (4, draws)))
    if kind == "mean-curvature":
        variables["gamma"] = (("chain", "draw"), rng.normal(0, 0.15, (4, draws)))
    if kind in {"event", "distance-scale", "mean-curvature"}:
        variables["tau_event"] = (("chain", "draw"), rng.uniform(0.1, 0.5, (4, draws)))
    if kind in {"distance-scale", "mean-curvature"}:
        variables["sigma_anchor"] = (
            ("chain", "draw", "scale_anchor_km"),
            rng.uniform(0.3, 1.0, (4, draws, 3)),
        )
    else:
        variables["sigma"] = (("chain", "draw"), rng.uniform(0.3, 1, (4, draws)))
    return xr.Dataset(
        variables,
        coords={
            "chain": ["a", "b", "c", "d"],
            "draw": np.arange(17, 17 + draws),
            **({"scale_anchor_km": [500, 2000, 5000]} if "sigma_anchor" in variables else {}),
        },
    )


@pytest.mark.parametrize("target,kind", FORMS)
def test_all_eight_explicit_forms_match_independent_dense_native_MVN(target, kind):
    data, post = lane(target), posterior(kind)
    original = post.copy(deep=True)
    held = np.array([0, 1, 2])
    logL, meta = scoring.event_loglikelihood(data, held, kind, post)
    assert logL.shape == (4, 160)
    assert logL.chain.values.tolist() == ["a", "b", "c", "d"]
    d = data.distance_km[held]
    for chain, draw in [(0, 0), (1, 77), (3, 159)]:
        mean = np.full(3, post.alpha.values[chain, draw])
        if "beta" in post:
            mean += post.beta.values[chain, draw] * np.log(d / 1000)
        if "gamma" in post:
            mean += post.gamma.values[chain, draw] * np.log((d + 500) / (1.5 * d))
        sigma = (
            np.interp(np.log(d), np.log([500, 2000, 5000]), post.sigma_anchor.values[chain, draw])
            if "sigma_anchor" in post
            else np.repeat(post.sigma.values[chain, draw], 3)
        )
        tau = post.tau_event.values[chain, draw] if "tau_event" in post else 0
        covariance = np.diag(sigma**2) + tau**2 * np.ones((3, 3))
        jacobian = 0 if target == "T-CAL" else -np.log(data.y[held]).sum()
        expected = cast(Any, multivariate_normal).logpdf(
            data.response[held], mean=mean, cov=covariance
        )
        assert logL.values[chain, draw] == pytest.approx(expected + jacobian, abs=1e-11)
        assert meta["native_log_jacobian"] == pytest.approx(jacobian)
    xr.testing.assert_identical(post, original)
    assert meta["coefficient_treatment"] == "explicit_no_Gaussian_prior_collapse"
    assert meta["measure"] == "native_minutes_joint_density"


def test_curved_kernel_equivalence_jacobian_once_and_newu_not_independent_records():
    from analysis.arrival.model_curvature_path import curvature_held_loglikelihood

    data, post = lane(), posterior("mean-curvature")
    held = np.array([0, 1, 2])
    result, meta = scoring.event_loglikelihood(data, held, "mean-curvature", post)
    np.testing.assert_allclose(
        result.values,
        curvature_held_loglikelihood(data, held, post) - np.log(data.y[held]).sum(),
        atol=1e-12,
    )
    individual = [
        scoring.event_loglikelihood(data, np.array([i]), "mean-curvature", post)[0] for i in held
    ]
    assert np.max(np.abs(result.values - sum(a.values for a in individual))) > 0.1
    assert meta["new_event_effect"] == "Normal_u_integrated_before_likelihood_averaging"
    zero_tau = post.copy(deep=True)
    zero_tau.tau_event.values[:] = 0
    joint = scoring.event_loglikelihood(data, held, "mean-curvature", zero_tau)[0]
    singles = [
        scoring.event_loglikelihood(data, np.array([i]), "mean-curvature", zero_tau)[0]
        for i in held
    ]
    np.testing.assert_allclose(joint.values, sum(a.values for a in singles), atol=1e-12)


@pytest.mark.parametrize(
    "bad",
    [
        "empty",
        "event",
        "duplicate",
        "negative",
        "float-index",
        "excluded",
        "unit",
        "response",
        "reference",
        "posterior-missing",
        "anchors",
        "chains",
        "duplicate-draw",
        "variable-dims",
        "negative-sigma",
        "negative-tau",
        "nonfinite",
    ],
)
def test_event_input_shape_units_identity_and_explicit_parameters_guarded(bad):
    data, post, held = lane(), posterior("mean-curvature"), np.array([0, 1, 2])
    if bad == "empty":
        held = np.array([], dtype=int)
    elif bad == "event":
        held = np.array([0, 3])
    elif bad == "duplicate":
        held = np.array([0, 0])
    elif bad == "negative":
        held = np.array([-1])
    elif bad == "float-index":
        held = np.array([0.0, 1.0])
    elif bad == "excluded":
        mask = data.included.copy()
        mask[0] = False
        data = replace(data, included=mask)
    elif bad == "unit":
        data = replace(data, distance_km=data.distance_km * 1000)
    elif bad == "response":
        data = replace(data, response=data.response + 1)
    elif bad == "reference":
        data = replace(data, reference_minutes=data.reference_minutes * 60)
    elif bad == "posterior-missing":
        post = post.drop_vars("alpha")
    elif bad == "anchors":
        post = post.assign_coords(scale_anchor_km=[2000, 500, 5000])
    elif bad == "chains":
        post = post.isel(chain=slice(3))
    elif bad == "duplicate-draw":
        post = post.assign_coords(draw=np.zeros(160, dtype=int))
    elif bad == "variable-dims":
        post["alpha"] = post.alpha.transpose("draw", "chain")
    elif bad == "negative-sigma":
        post.sigma_anchor.values[0, 0, 0] = -1
    elif bad == "negative-tau":
        post.tau_event.values[0, 0] = -1
    else:
        post.gamma.values[0, 0] = np.nan
    with pytest.raises(ValueError):
        scoring.event_loglikelihood(data, held, "mean-curvature", post)


def labelled(
    values, *, event="event-a", records=1, identity="a" * 64, target="T-OBS", kind="event"
):
    return xr.DataArray(
        values,
        dims=("chain", "draw"),
        coords={"chain": ["a", "b", "c", "d"], "draw": np.arange(values.shape[1])},
        attrs={
            "event_id": event,
            "records": records,
            "target": target,
            "kind": kind,
            "measure": "native_minutes_joint_density",
            "training_draw_identity": identity,
        },
    )


def test_stable_logmean_and_raw_joint_influence_independent_oracles():
    values = np.random.default_rng(881).normal(-15000, 0.05, (4, 2000))
    score = scoring.direct_event_score(labelled(values, records=7), 7)
    expected = float(cast(Any, logsumexp)(values)) - math.log(values.size)
    assert score["joint_log_predictive"] == pytest.approx(expected)
    assert score["normalized_event_score"] == pytest.approx(expected / 7)
    shifted = np.exp(values - values.max())
    expected_influence = shifted / shifted.mean() - 1
    np.testing.assert_array_equal(score["joint_influence"].values, expected_influence)
    assert score["normalized_mcse"] == pytest.approx(mean_mcse(expected_influence / 7))
    assert score["precision_passed"] and score["status"] == "computed_pending_review"
    assert score["density_weight_concentration_ess"] > 7900
    assert "not finite-sample certificates" in score["qualification"]


@pytest.mark.parametrize("constant", [-1e300, -1234.0, 0.0, 1e300])
def test_constant_likelihood_mathematically_exact_zero_mcse(constant):
    result = scoring.direct_event_score(np.full((4, 100), constant), 3)
    assert result["joint_log_predictive"] == constant
    assert result["normalized_event_score"] == constant / 3
    assert result["normalized_mcse"] == 0
    assert result["density_weight_concentration_ess"] == 400
    assert result["functional_mixing"] == {"constant": True, "passed": True}
    assert result["precision_passed"] and not result["numerical_failures"]
    np.testing.assert_array_equal(result["joint_influence"], 0)


def test_weight_degeneracy_and_separate_mixing_failures_require_review():
    degenerate = np.full((4, 1000), -1e300)
    degenerate[0, 0] = 1e300
    result = scoring.direct_event_score(degenerate, 1)
    assert result["density_weight_concentration_ess"] == 1
    assert not result["precision_passed"] and result["status"] == "needs_numerical_review"
    assert "density_weight_concentration" in result["numerical_failures"]
    # Large record count can shrink normalized MCSE, but cannot cure stuck chains.
    stuck = np.broadcast_to(np.arange(4)[:, None] * 0.1, (4, 1000)).copy()
    mixed = scoring.direct_event_score(stuck, 1000)
    assert not mixed["functional_mixing"]["passed"]
    assert mixed["status"] == "needs_numerical_review"


def test_ar_functional_autocorrelation_fails_ess_without_false_precision():
    rng = np.random.default_rng(9961)
    values = np.zeros((4, 3000))
    innovations = rng.normal(size=values.shape)
    for draw in range(1, values.shape[1]):
        values[:, draw] = 0.995 * values[:, draw - 1] + 0.01 * innovations[:, draw]
    result = scoring.direct_event_score(values, 1)
    iid = scoring.direct_event_score(rng.normal(0, 0.05, values.shape), 1)
    assert not result["functional_mixing"]["passed"]
    assert result["functional_mixing"]["ess_bulk"] < 400
    assert result["status"] == "needs_numerical_review" and iid["precision_passed"]
    assert result["normalized_mcse"] > iid["normalized_mcse"]


@pytest.mark.parametrize(
    "values,records",
    [
        (np.zeros((3, 1000)), 1),
        (np.zeros((4, 99)), 1),
        (np.zeros((4, 100)), 0),
        (np.zeros((4, 100)), True),
        (np.full((4, 100), np.nan), 1),
        (np.full((4, 100), -np.inf), 1),
        (np.zeros((4, 100), dtype=complex), 1),
    ],
)
def test_invalid_score_arrays_and_records_rejected(values, records):
    with pytest.raises(ValueError):
        scoring.direct_event_score(values, records)


def test_shared_training_covariance_counterexample_not_independent_quadrature():
    values = np.random.default_rng(772).normal(-20, 0.05, (4, 2000))
    first = scoring.direct_event_score(labelled(values, event="event-a", records=1), 1)
    second = scoring.direct_event_score(labelled(values, event="event-b", records=2), 2)
    result = scoring.aggregate_shared_training_events([first, second], "f" * 64)
    expected = (first["joint_influence"].values + second["joint_influence"].values / 2) / 2
    np.testing.assert_array_equal(result["shared_influence"].values, expected)
    assert result["mcse_equal_event_score"] == pytest.approx(mean_mcse(expected))
    incorrect = math.hypot(first["normalized_mcse"], second["normalized_mcse"]) / 2
    assert result["mcse_equal_event_score"] > incorrect * 1.3
    assert result["equal_event_score"] == pytest.approx(
        (first["normalized_event_score"] + second["normalized_event_score"]) / 2
    )
    assert result["precision_passed"] and result["training_posterior_sha256"] == "f" * 64


def test_aggregate_threshold_stricter_than_event_and_failed_event_cannot_be_hidden():
    rng = np.random.default_rng(431)
    values = rng.normal(-20, 0.2, (4, 2000))
    # Equal chain normalizers isolate the stricter aggregate MCSE threshold.
    values -= np.asarray(cast(Any, logsumexp)(values, axis=1))[:, None] - math.log(2000)
    first = scoring.direct_event_score(labelled(values), 1)
    assert first["precision_passed"] and 0.002 < first["normalized_mcse"] < 0.005
    total = scoring.aggregate_shared_training_events([first], "f" * 64)
    assert total["status"] == "needs_numerical_review"
    assert "aggregate_mcse" in total["numerical_failures"]
    first["precision_passed"] = False
    total = scoring.aggregate_shared_training_events([first], "f" * 64)
    assert "event_numerical_review" in total["numerical_failures"]


@pytest.mark.parametrize(
    "bad",
    [
        "coordinates",
        "content",
        "source",
        "kind",
        "duplicate-event",
        "ndarray",
        "count",
        "measure",
        "sha",
        "empty",
    ],
)
def test_shared_aggregate_rejects_misaligned_or_unbound_training_streams(bad):
    values = np.random.default_rng(1).normal(-20, 0.01, (4, 1000))
    first = scoring.direct_event_score(labelled(values), 1)
    second = scoring.direct_event_score(labelled(values, event="event-b"), 1)
    sha = "f" * 64
    if bad == "coordinates":
        second["joint_influence"] = second["joint_influence"].isel(draw=slice(None, None, -1))
    elif bad in {"content", "source", "kind", "duplicate-event", "measure"}:
        key, value = {
            "content": ("training_draw_identity", "b" * 64),
            "source": ("target", "T-CAL"),
            "kind": ("kind", "distance"),
            "duplicate-event": ("event_id", "event-a"),
            "measure": ("measure", "log_ratio"),
        }[bad]
        second["metadata"][key] = value
        second["joint_influence"].attrs[key] = value
    elif bad == "ndarray":
        second["joint_influence"] = second["joint_influence"].values
    elif bad == "count":
        second["records"] = 2
    elif bad == "sha":
        sha = "not-a-sha"
    events = [] if bad == "empty" else [first, second]
    with pytest.raises(ValueError):
        scoring.aggregate_shared_training_events(events, sha)


def test_training_content_identity_reproducible_sensitive_and_preserves_chain_order():
    data, post = lane(), posterior("distance-scale")
    _, first = scoring.event_loglikelihood(data, np.array([0, 1, 2]), "distance-scale", post)
    _, second = scoring.event_loglikelihood(data, np.array([3, 4]), "distance-scale", post.copy())
    assert first["training_draw_identity"] == second["training_draw_identity"]
    changed = post.copy(deep=True)
    changed.alpha.values[0, 0] += 0.001
    _, third = scoring.event_loglikelihood(data, np.array([3, 4]), "distance-scale", changed)
    assert third["training_draw_identity"] != first["training_draw_identity"]
    shuffled = post.isel(chain=[1, 0, 2, 3])
    _, fourth = scoring.event_loglikelihood(data, np.array([3, 4]), "distance-scale", shuffled)
    assert fourth["training_draw_identity"] != first["training_draw_identity"]


def test_student_population_draws_never_call_Gaussian_coefficient_collapse(monkeypatch):
    from analysis.arrival.model_collapsed import CollapsedGaussian

    def forbidden(*args, **kwargs):
        pytest.fail("Gaussian population coefficient collapse under Student-t priors")

    monkeypatch.setattr(CollapsedGaussian, "new_event_logpdf", forbidden)
    data, post = lane(), posterior("mean-curvature")
    post["alpha"].values[:] = np.random.default_rng(333).standard_t(4, size=(4, 160))
    post.attrs["population_prior"] = "matched_StudentT4"
    result, metadata = scoring.event_loglikelihood(
        data, np.array([0, 1, 2]), "mean-curvature", post
    )
    assert np.isfinite(result.values).all()
    assert metadata["coefficient_treatment"] == "explicit_no_Gaussian_prior_collapse"


def test_unresolved_mcse_is_none_and_review_not_false_zero(monkeypatch):
    def unresolved(*args):
        raise ValueError("synthetic unresolved mean MCSE")

    monkeypatch.setattr(scoring, "mean_mcse", unresolved)
    values = np.random.default_rng(66).normal(0, 0.01, (4, 1000))
    event = scoring.direct_event_score(labelled(values), 1)
    assert event["normalized_mcse"] is None and event["joint_log_mcse_delta"] is None
    assert event["status"] == "needs_numerical_review"
    assert "unresolved_delta_mcse" in event["numerical_failures"]
    aggregate = scoring.aggregate_shared_training_events([event], "a" * 64)
    assert aggregate["mcse_equal_event_score"] is None
    assert aggregate["status"] == "needs_numerical_review"


def test_shared_constant_very_large_logscore_average_does_not_overflow():
    values = np.full((4, 100), 1e308)
    first = scoring.direct_event_score(labelled(values, event="event-a"), 1)
    second = scoring.direct_event_score(labelled(values, event="event-b"), 1)
    result = scoring.aggregate_shared_training_events([first, second], "a" * 64)
    assert result["equal_event_score"] == 1e308
    assert result["mcse_equal_event_score"] == 0 and result["precision_passed"]
