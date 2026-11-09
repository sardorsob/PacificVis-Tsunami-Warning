"""Synthetic marginal new-event prediction adapter checks; no actual outcomes/fits."""

# pyright: basic
from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import norm

from analysis.arrival import model_development_predictions as prediction
from analysis.arrival.model_bridge_predictions import predictions_with_precision
from analysis.arrival.model_sensitivity_design import FORMS
from tests.test_arrival_model_development_scoring import lane, posterior


def fixed(kind):
    post = posterior(kind, draws=200)
    for name in post.data_vars:
        post[name].values[:] = {
            "alpha": -0.1,
            "beta": 0.05,
            "gamma": 0.3,
            "sigma": 0.4,
            "sigma_anchor": 0.4,
            "tau_event": 0.2,
        }[str(name)]
    return post


@pytest.mark.parametrize("target,kind", FORMS)
def test_all_eight_constant_cases_have_analytic_Normal_PIT_and_quantiles(target, kind):
    data, post = lane(target), fixed(kind)
    held = np.array([0, 1, 2])
    rows, metadata = prediction.new_event_predictions(
        data, held, kind, post, training_distance_range_km=(500, 3000)
    )
    for row, i in zip(rows, held, strict=True):
        d = data.distance_km[i]
        mean = -0.1 + (0.05 * np.log(d / 1000) if kind != "pooled" else 0)
        if kind == "mean-curvature":
            mean += 0.3 * np.log((d + 500) / (1.5 * d))
        tau = 0.2 if kind in {"event", "distance-scale", "mean-curvature"} else 0
        total = np.sqrt(0.4**2 + tau**2)
        assert row["pit"] == pytest.approx(norm.cdf((data.response[i] - mean) / total))
        for label, q in zip(prediction.QUANTILES, [0.05, 0.25, 0.5, 0.75, 0.95], strict=True):
            response_q = mean + norm.ppf(q) * total
            expected = (
                response_q if target == "T-CAL" else data.reference_minutes[i] * np.exp(response_q)
            )
            assert row[label] == pytest.approx(expected, abs=1e-9)
            assert row[label + "_cdf_mcse"] == row[label + "_mcse_native"] == 0
        assert row["pit_mcse"] == 0 and row["prediction_precision_passed"]
        assert row["observed_reported_minutes"] == data.y[i]
    assert [r["distance_support"] for r in rows] == ["below", "within", "above"]
    assert metadata["prediction_precision_passed"]
    assert "not_joint_score" in metadata["prediction_scope"]
    assert metadata["physical_UTC_arrival_or_imputation"] is False
    assert metadata["provenance"].startswith("unverified_until_caller")
    assert metadata["chain_coordinates"] == ["a", "b", "c", "d"]


def test_exact_old_helper_identity_and_dense_mixture_CDF_oracle():
    data, post = lane(), posterior("mean-curvature", draws=500)
    held = np.array([0, 1, 2])
    mean, sigma, tau = prediction.curved_components(post, data.distance_km[held])
    expected, checks = predictions_with_precision(
        data.response[held], mean, sigma, tau, data.reference_minutes[held], data.target
    )
    rows, _ = prediction.new_event_predictions(
        data, held, "mean-curvature", post, training_distance_range_km=(100, 20000)
    )
    total = np.sqrt(sigma**2 + tau[..., None] ** 2)
    for j, row in enumerate(rows):
        assert all(row[key] == float(values[j]) for key, values in expected.items())
        assert all(row[key] == value for key, value in checks[j].items())
        cdf = cast(Any, norm).cdf((data.response[held[j]] - mean[..., j]) / total[..., j]).mean()
        assert row["pit"] == pytest.approx(cdf, abs=1e-14)
        for key, q in zip(prediction.QUANTILES, [0.05, 0.25, 0.5, 0.75, 0.95], strict=True):
            response_q = np.log(row[key] / data.reference_minutes[held[j]])
            evaluated = cast(Any, norm).cdf((response_q - mean[..., j]) / total[..., j]).mean()
            assert evaluated == pytest.approx(q, abs=1e-10)


def test_signed_tcal_and_positive_native_quantiles_have_distinct_transforms():
    positive = lane("T-OBS")
    signed = replace(lane("T-CAL"), response=positive.response.copy(), y=positive.response.copy())
    post = fixed("event")
    signed_rows, _ = prediction.new_event_predictions(
        signed, np.array([0, 1, 2]), "event", post, training_distance_range_km=(100, 20000)
    )
    positive_rows, _ = prediction.new_event_predictions(
        positive, np.array([0, 1, 2]), "event", post, training_distance_range_km=(100, 20000)
    )
    assert signed_rows[0]["q05"] < 0
    for i, (a, b) in enumerate(zip(signed_rows, positive_rows, strict=True)):
        assert a["pit"] == b["pit"]
        for key in prediction.QUANTILES:
            assert b[key] == pytest.approx(positive.reference_minutes[i] * np.exp(a[key]))
            assert b[key + "_mcse_native"] == pytest.approx(b[key] * a[key + "_mcse_native"])


def test_permutation_preserves_record_identity_and_posterior_fingerprint():
    data, post = lane(), posterior("distance-scale", draws=300)
    before = post.copy(deep=True)
    first, a = prediction.new_event_predictions(
        data, np.array([0, 1, 2]), "distance-scale", post, training_distance_range_km=(100, 20000)
    )
    second, b = prediction.new_event_predictions(
        data, np.array([2, 0, 1]), "distance-scale", post, training_distance_range_km=(100, 20000)
    )
    assert second == [first[2], first[0], first[1]]
    assert a["training_draw_identity"] == b["training_draw_identity"]
    import xarray as xr

    xr.testing.assert_identical(post, before)


def test_explicit_student_population_draws_do_not_call_Gaussian_coefficient_collapse(monkeypatch):
    from analysis.arrival.model_collapsed import CollapsedGaussian

    def forbidden(*args, **kwargs):
        pytest.fail("collapsed Gaussian coefficients in T4 prediction")

    monkeypatch.setattr(CollapsedGaussian, "new_event_logpdf", forbidden)
    data, post = lane(), posterior("mean-curvature", draws=300)
    post.alpha.values[:] = np.random.default_rng(91).standard_t(4, size=(4, 300)) * 0.1
    post.attrs["population_prior"] = "StudentT4"
    rows, meta = prediction.new_event_predictions(
        data, np.array([0, 1, 2]), "mean-curvature", post, training_distance_range_km=(100, 20000)
    )
    assert all(np.isfinite([r[q] for q in prediction.QUANTILES]).all() for r in rows)
    assert meta["coefficient_treatment"] == "explicit_no_Gaussian_prior_collapse"


@pytest.mark.parametrize(
    "bad",
    [
        "empty",
        "multi-event",
        "missing-alpha",
        "zero-sigma",
        "nan",
        "three-chains",
        "anchor-order",
        "draw-order-duplicates",
        "few-draws",
        "unit",
        "target-kind",
    ],
)
def test_invalid_input_cannot_produce_predictions(bad):
    data, post, held = lane(), posterior("mean-curvature"), np.array([0, 1, 2])
    kind = "mean-curvature"
    if bad == "empty":
        held = np.array([], dtype=int)
    elif bad == "multi-event":
        held = np.array([0, 3])
    elif bad == "missing-alpha":
        post = post.drop_vars("alpha")
    elif bad == "zero-sigma":
        post.sigma_anchor.values[0, 0, 0] = 0
    elif bad == "nan":
        post.alpha.values[0, 0] = np.nan
    elif bad == "three-chains":
        post = post.isel(chain=slice(3))
    elif bad == "anchor-order":
        post = post.assign_coords(scale_anchor_km=[2000, 500, 5000])
    elif bad == "draw-order-duplicates":
        post = post.assign_coords(draw=np.zeros(160, dtype=int))
    elif bad == "few-draws":
        post = post.isel(draw=slice(99))
    elif bad == "unit":
        data = replace(data, reference_minutes=data.reference_minutes * 60)
    else:
        kind = "pooled"
    with pytest.raises(ValueError):
        prediction.new_event_predictions(
            data, held, kind, post, training_distance_range_km=(100, 20000)
        )


@pytest.mark.parametrize("support", [None, [], [0, 100], [1000, 100], [100, np.inf], [True, False]])
def test_training_support_must_be_explicit_valid_metadata(support):
    with pytest.raises(ValueError):
        prediction.new_event_predictions(
            lane(),
            np.array([0]),
            "distance-scale",
            fixed("distance-scale"),
            training_distance_range_km=support,
        )


def test_failed_finite_helper_precision_is_retained_without_clipping_or_repair(monkeypatch):
    original = prediction.predictions_with_precision

    def failed(*args):
        values, checks = original(*args)
        checks[0]["prediction_precision_passed"] = False
        checks[0]["pit_mcse"] = 0.02
        return values, checks

    monkeypatch.setattr(prediction, "predictions_with_precision", failed)
    rows, meta = prediction.new_event_predictions(
        lane(),
        np.array([0, 1, 2]),
        "distance-scale",
        fixed("distance-scale"),
        training_distance_range_km=(100, 20000),
    )
    assert rows[0]["pit_mcse"] == 0.02 and not rows[0]["prediction_precision_passed"]
    assert meta["status"] == "needs_numerical_review"


@pytest.mark.parametrize("bad", ["precision-missing", "quantile-nan", "pit-outside", "unordered"])
def test_unsupported_or_nonfinite_helper_outputs_fail_conservatively(monkeypatch, bad):
    original = prediction.predictions_with_precision

    def changed(*args):
        values, checks = original(*args)
        if bad == "precision-missing":
            checks[0].pop("q05_cdf_mcse")
        elif bad == "quantile-nan":
            values["q05"][0] = np.nan
        elif bad == "pit-outside":
            values["pit"][0] = 1.01
        else:
            values["q05"][0] = values["q95"][0] + 1
        return values, checks

    monkeypatch.setattr(prediction, "predictions_with_precision", changed)
    with pytest.raises(ValueError):
        prediction.new_event_predictions(
            lane(),
            np.array([0]),
            "distance-scale",
            fixed("distance-scale"),
            training_distance_range_km=(100, 20000),
        )
