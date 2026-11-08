"""New-event prediction uses native units and integrates a common event effect."""

# pyright: basic
import numpy as np
import pytest
from scipy.stats import norm

from analysis.arrival.model_prediction import marginal_report_predictions, posterior_components


def test_marginal_predictive_quantiles_and_pit_match_known_normal_in_native_units():
    mean = np.zeros((4, 1000, 2)) + [0.1, -0.2]
    sd = np.zeros_like(mean) + [0.3, 0.5]
    tau = np.full((4, 1000), 0.4)
    reference = np.array([20.0, 300.0])
    response = np.array([0.2, -0.3])
    result = marginal_report_predictions(response, mean, sd, tau, reference, "NCEI-native-duration")
    total = np.sqrt(np.array([0.3, 0.5]) ** 2 + 0.4**2)
    np.testing.assert_allclose(result["pit"], norm.cdf((response - [0.1, -0.2]) / total))
    for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
        np.testing.assert_allclose(
            result[f"q{round(q * 100):02d}"], reference * np.exp([0.1, -0.2] + norm.ppf(q) * total)
        )
    signed = marginal_report_predictions(response, mean, sd, tau, reference, "T-CAL")
    assert signed["q50"][1] == pytest.approx(-0.2)
    assert signed["q05"][0] < 0


def test_distance_scale_components_retain_chains_and_baseline_zero_terms():
    import xarray as xr

    ds = xr.Dataset(
        {
            "alpha": (("chain", "draw"), np.zeros((4, 1000))),
            "beta": (("chain", "draw"), np.zeros((4, 1000))),
            "tau_event": (("chain", "draw"), np.zeros((4, 1000))),
            "sigma": (("chain", "draw"), np.ones((4, 1000))),
            "sigma_anchor": (("chain", "draw", "anchor"), np.tile([0.6, 0.3, 0.1], (4, 1000, 1))),
        }
    )
    mean, sigma, tau = posterior_components(ds, "pooled", np.array([500.0, 1000.0]))
    assert mean.shape == sigma.shape == (4, 1000, 2)
    assert not mean.any() and not tau.any()
    mean, sigma, tau = posterior_components(ds, "distance-scale", np.array([500.0, 1000.0]))
    np.testing.assert_allclose(sigma[0, 0], [0.6, 0.45])


def test_omitted_parameters_absent_and_varying_mixture_quantiles_solve_cdf():
    import xarray as xr

    ds = xr.Dataset(
        {
            "alpha": (("chain", "draw"), np.tile(np.linspace(-1, 1, 1000), (4, 1))),
            "sigma": (("chain", "draw"), np.tile(np.linspace(0.1, 0.7, 1000), (4, 1))),
        }
    )
    mean, sigma, tau = posterior_components(ds, "pooled", np.array([1000.0]))
    out = marginal_report_predictions(np.array([0.2]), mean, sigma, tau, np.array([1.0]), "T-CAL")
    for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
        v = out[f"q{round(100 * q):02d}"][0]
        assert np.mean(norm.cdf((v - mean) / sigma)) == pytest.approx(q, abs=1e-10)
    ds["beta"] = (("chain", "draw"), np.ones((4, 1000)) * 0.1)
    _, _, tau = posterior_components(ds, "distance", np.array([1000.0]))
    assert not tau.any()
