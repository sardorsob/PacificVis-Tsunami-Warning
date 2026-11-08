"""Explicit heteroskedastic conditional replication retains fitted-event uncertainty."""

# pyright: basic
import numpy as np

from analysis.arrival.model_fit import conditional_replicates
from analysis.arrival.model_scale_fit import conditional_scale_replicates


def test_equal_anchor_ppc_matches_baseline_generator_with_same_noise():
    rng = np.random.default_rng(817)
    h = {
        "alpha": rng.normal(size=1000) * 0.1,
        "beta": rng.normal(size=1000) * 0.05,
        "sigma": np.full(1000, 0.3),
    }
    u = rng.normal(size=(1000, 2)) * 0.2
    event = np.array([0, 0, 1])
    distance = np.array([100.0, 3000.0, 10000.0])
    reference = distance / 12
    response, native = conditional_replicates(
        h, u, event, np.log(distance / 1000), reference, target="NCEI-native-duration", seed=13
    )
    hh = {"alpha": h["alpha"], "beta": h["beta"], "sigma_anchor": np.full((1000, 3), 0.3)}
    got_response, got_native = conditional_scale_replicates(
        hh, u, event, distance, reference, seed=13
    )
    np.testing.assert_allclose(got_response, response, atol=1e-14)
    np.testing.assert_allclose(got_native, native, atol=1e-10)
    hh["sigma_anchor"] = np.tile([0.6, 0.3, 0.1], (1000, 1))
    got, _ = conditional_scale_replicates(hh, u, event, distance, reference, seed=13)
    residual = (
        got - h["alpha"][:, None] - h["beta"][:, None] * np.log(distance / 1000) - u[:, event]
    )
    normal = np.random.default_rng(13).normal(size=(1000, 3))
    sigma = np.interp(np.log(distance), np.log([500, 2000, 5000]), [0.6, 0.3, 0.1])
    np.testing.assert_allclose(residual, normal * sigma, atol=1e-14)
