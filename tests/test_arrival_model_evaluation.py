"""Independent density oracles for joint new-event scores and native-minute units."""

# pyright: basic

import numpy as np
import pytest
from scipy.stats import lognorm, multivariate_normal, norm

from analysis.arrival.model_evaluation import gaussian_event_logpdf, native_event_logpdf


def test_joint_gaussian_integral_matches_full_covariance() -> None:
    y = np.array([0.1, -0.2, 0.7])
    mu = np.array([[0, 0.1, 0.2], [0.1, 0.2, 0.3]])
    sigma = np.array([[0.2, 0.3, 0.4], [0.4, 0.5, 0.6]])
    tau = np.array([0.3, 0.7])
    actual = gaussian_event_logpdf(y, mu, sigma, tau)
    expected = [
        multivariate_normal.logpdf(
            y, mean=mu[j], cov=np.diag(sigma[j] ** 2) + tau[j] ** 2 * np.ones((3, 3))
        )
        for j in range(2)
    ]
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_zero_event_variance_and_native_duration_jacobian() -> None:
    y = np.array([0.1, 0.2, 0.3])
    np.testing.assert_allclose(
        gaussian_event_logpdf(y, np.zeros(3), 0.4, 0), norm.logpdf(y, scale=0.4).sum()
    )
    native = np.array([100.0])
    reference = np.array([80.0])
    actual = native_event_logpdf(native, reference, "T-OBS", np.array([0.1]), 0.3, 0.2)
    expected = lognorm.logpdf(100, s=np.sqrt(0.3**2 + 0.2**2), scale=80 * np.exp(0.1))
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_signed_calibration_does_not_apply_duration_jacobian() -> None:
    y = np.array([-3.0, 2.0])
    np.testing.assert_allclose(
        native_event_logpdf(y, np.ones(2), "T-CAL", np.zeros(2), 2.0, 0),
        norm.logpdf(y, scale=2).sum(),
    )


@pytest.mark.parametrize("sigma,tau", [(0, 1), (-1, 1), (1, -1), (np.inf, 1)])
def test_invalid_density_parameters_fail(sigma: float, tau: float) -> None:
    with pytest.raises(ValueError):
        gaussian_event_logpdf(np.array([1.0]), np.array([0.0]), sigma, tau)
