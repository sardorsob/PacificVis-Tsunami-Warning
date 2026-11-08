"""Native-unit quantile precision and bounded CDF Monte Carlo error."""

# pyright: basic
import numpy as np
import pytest
from scipy.stats import norm

from analysis.arrival.model_bridge_predictions import predictions_with_precision


def test_fixed_hyperparameters_have_exact_quantiles_and_zero_posterior_mcse():
    mean = np.full((4, 1000, 1), -10.0)
    sigma = np.full_like(mean, 20.0)
    tau = np.full((4, 1000), 10.0)
    result, precision = predictions_with_precision(
        np.array([-5.0]), mean, sigma, tau, np.ones(1), "T-CAL"
    )
    assert result["q05"][0] == pytest.approx(-10 + norm.ppf(0.05) * np.sqrt(500))
    assert result["q05"][0] < 0
    assert precision[0]["pit_mcse"] == 0
    assert precision[0]["max_quantile_mcse_fraction_interval_width"] == 0
    assert precision[0]["prediction_precision_passed"]


def test_quantile_precision_preserves_unit_conversion_and_log_duration_measure():
    rng = np.random.default_rng(17)
    mean = rng.normal(0, 0.2, (4, 4000, 1))
    sigma = np.full_like(mean, 0.5)
    tau = np.full((4, 4000), 0.2)
    response = np.array([0.1])
    first, p1 = predictions_with_precision(response, mean, sigma, tau, np.ones(1), "T-CAL")
    second, p2 = predictions_with_precision(
        response * 60, mean * 60, sigma * 60, tau * 60, np.ones(1), "T-CAL"
    )
    assert second["q95"][0] == pytest.approx(60 * first["q95"][0])
    assert p2[0]["q95_mcse_native"] == pytest.approx(60 * p1[0]["q95_mcse_native"])
    assert p2[0]["max_quantile_mcse_fraction_interval_width"] == pytest.approx(
        p1[0]["max_quantile_mcse_fraction_interval_width"]
    )
    duration, pd = predictions_with_precision(
        response, mean, sigma, tau, np.array([100.0]), "T-OBS"
    )
    assert duration["q95"][0] == pytest.approx(100 * np.exp(first["q95"][0]))
    # Delta-method derivative dy/dr = y supplies the native-duration measure.
    assert pd[0]["q95_mcse_native"] == pytest.approx(duration["q95"][0] * p1[0]["q95_mcse_native"])
