"""Known-integral and coordinate-Jacobian checks for positive-parameter cubature."""

# pyright: basic
import numpy as np
import pytest
from scipy.stats import t

from analysis.arrival.model_normalizer import PositiveProposal, integrate_positive


def test_truncated_student_coordinate_map_has_the_correct_density_jacobian():
    p = PositiveProposal(np.array([1.0, 0.1]), np.array([0.2, 0.3]))
    u = np.array([[0.01, 0.02], [0.3, 0.7], [0.99, 0.98]])
    x, j = p.transform(u)
    assert (x > 0).all()
    norm = 1 - t.cdf(-p.location / p.scale, df=5)
    expected = np.sum(np.log(p.scale * norm) - t.logpdf((x - p.location) / p.scale, df=5), axis=1)
    np.testing.assert_allclose(j, expected, atol=1e-12)
    np.testing.assert_allclose(
        (t.cdf((x - p.location) / p.scale, df=5) - (1 - norm)) / norm, u, atol=1e-11
    )


def test_positive_gaussian_integral_normalization_is_proposal_independent():
    # Independent normalized HalfNormal priors in two positive coordinates.
    def log_target(x):
        return np.log(2 / np.pi) - 0.5 * np.sum(x * x, axis=1)

    for width in [0.8, 1.2]:
        p = PositiveProposal(np.array([0.5, 0.5]), np.array([width, width]))
        result = integrate_positive(log_target, p, relative_tolerance=1e-7, max_points=300000)
        assert result["log_evidence"] == pytest.approx(0, abs=2e-7)
        assert result["relative_error_estimate"] < 1.1e-7


def test_four_dimensional_rule_keeps_a_known_normalized_proposal_density():
    proposal = PositiveProposal(np.full(4, 0.5), np.ones(4))

    def target(x):
        return np.sum(
            t.logpdf((x - proposal.location) / proposal.scale, df=5)
            - np.log(proposal.scale)
            - np.log(1 - t.cdf(-proposal.location / proposal.scale, df=5)),
            axis=1,
        )

    result = integrate_positive(
        target,
        proposal,
        relative_tolerance=1e-5,
        max_points=2000000,
    )
    assert result["log_evidence"] == pytest.approx(0, abs=1e-12)


def test_exhausting_a_four_dimensional_budget_is_an_explicit_failure():
    with pytest.raises(ValueError, match="point ceiling"):
        integrate_positive(
            lambda x: 2 * np.log(2 / np.pi) - 0.5 * np.sum(x * x, axis=1),
            PositiveProposal(np.full(4, 0.5), np.ones(4)),
            relative_tolerance=1e-5,
            max_points=1000,
        )
