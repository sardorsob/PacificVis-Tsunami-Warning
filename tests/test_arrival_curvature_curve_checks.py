"""Independent curve geometry, finite-grid credibility and rank-reference oracles."""

# pyright: basic
import numpy as np
import pytest
import xarray as xr

from analysis.arrival.model_curvature_curve_checks import (
    GRID_KM,
    curve_checks,
    sbc_rank_ecdf_screen,
    unbiased_rank,
)


def test_curve_band_preserves_joint_draws_and_labels_scope():
    rng = np.random.default_rng(99)
    z = rng.normal(size=(4, 2000))
    extra = rng.normal(size=(4, 2000))
    alpha = 0.1 + 0.1 * z
    beta = -0.05 + 0.03 * z + 0.01 * extra
    gamma = 0.4 - 0.04 * z + 0.03 * extra
    dataset = xr.Dataset(
        {k: (("chain", "draw"), v) for k, v in [("alpha", alpha), ("beta", beta), ("gamma", gamma)]}
    )
    truth = {"alpha": 0.1, "beta": -0.05, "gamma": 0.4}
    prior = {"alpha_sd": 0.5, "beta_sd": 0.25, "gamma_sd": 0.5}
    result = curve_checks(dataset, truth, prior, 2826110800)
    d = np.array(GRID_KM)
    f = (
        alpha[..., None]
        + beta[..., None] * np.log(d / 1000)
        + gamma[..., None] * np.log((d + 500) / (1.5 * d))
    )
    center = np.median(f, axis=(0, 1))
    sd = f.std(axis=(0, 1), ddof=1)
    t = np.max(np.abs((f - center) / sd), axis=-1)
    q = np.quantile(t, 0.9)
    assert result["grid_band90"]["q90"] == pytest.approx(q, abs=1e-12)
    assert result["grid_band90"]["posterior_fraction_within"] == pytest.approx(0.9, abs=0.001)
    assert len(result["estimates"]) == 9 and result["rank_ready"]
    for j, row in enumerate(result["estimates"]):
        assert row["grid_band_lower"] == pytest.approx(center[j] - q * sd[j])
        assert row["truth"] == pytest.approx(
            0.1 - 0.05 * np.log(d[j] / 1000) + 0.4 * np.log((d[j] + 500) / (1.5 * d[j]))
        )
    assert "no_offgrid_guarantee" in result["grid_band90"]["scope"]


def test_tied_rank_uses_all_equal_positions_without_touching_original():
    draws = np.tile(np.r_[np.full(25, -1.0), np.zeros(50), np.ones(25)], (4, 1))
    subset = draws[:, np.linspace(0, 99, 25, dtype=int)].ravel()
    less = int(np.sum(subset < 0))
    equal = int(np.sum(subset == 0))
    source = {"rank": less, "rank_draws": 100, "randomized_rank_pit": 0.1}
    got = [unbiased_rank(draws, 0.0, j, source)["rank"] for j in range(1000)]
    assert min(got) == less and max(got) == less + equal
    assert source["rank"] == less and source["randomized_rank_pit"] == 0.1


def test_fixed_n_discrete_ecdf_screen_and_dependence_safe_width():
    nearly_uniform = np.arange(100)
    result = sbc_rank_ecdf_screen(nearly_uniform)
    assert not result["screen_exceeded"]
    assert result["dkw_union_halfwidth"] == pytest.approx(np.sqrt(np.log(840) / 200))
    assert sbc_rank_ecdf_screen(np.zeros(100))["screen_exceeded"]
    with pytest.raises(ValueError):
        sbc_rank_ecdf_screen(np.arange(99))


def test_incorrect_original_rank_cannot_be_silently_carried_forward():
    values = np.arange(8000).reshape(4, 2000).astype(float)
    with pytest.raises(ValueError, match="original rank"):
        unbiased_rank(
            values, 2000.0, 123, {"rank": 99, "rank_draws": 100, "randomized_rank_pit": 0.9}
        )
