"""Curve uncertainty preserves joint draws; chart order follows numeric distance."""

# pyright: basic
import numpy as np
import pytest

from analysis.arrival.model_curvature_fit_report import (
    plot,
    population_curves,
    validate_identity,
    validate_ppc,
)


def test_curve_quantiles_preserve_coefficient_covariance():
    beta = np.linspace(-1, 1, 400).reshape(4, 100)
    post = {
        "alpha": -beta * np.log(2),
        "beta": beta,
        "gamma": np.zeros_like(beta),
        "sigma_anchor": np.full((4, 100, 3), 0.4),
    }
    quantiles, sd = population_curves(post, np.array([2000.0, 1000.0]), True)
    np.testing.assert_allclose(quantiles[:, 0], 0, atol=1e-15)
    np.testing.assert_allclose(sd, 0.4, atol=1e-15)
    assert quantiles[0, 1] < quantiles[1, 1] < quantiles[2, 1]


def test_plot_curves_orders_distances_numerically(tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    captured = []

    def save(fig, *args, **kwargs):
        if len(fig.axes[0].lines) == 2:
            captured.extend([line.get_xdata() for line in fig.axes[0].lines])

    monkeypatch.setattr(Figure, "savefig", save)
    curves = [
        {
            "model": model,
            "distance_km": d,
            **{
                f"{p}_q{q:02d}": v
                for p in ["log_median_ratio", "residual_sd"]
                for q, v in [(5, 0.1), (50, 0.2), (95, 0.3)]
            },
        }
        for model in ["linear", "curvature"]
        for d in [100, 1000, 20, 5000]
    ]
    events = [
        {"model": model, "q05": 0.1, "q50": 0.2, "q95": 0.3} for model in ["linear", "curvature"]
    ]
    checks = [
        {
            "model": model,
            "stratum": s,
            "scale": "modeled-response",
            "quantile": q,
            "replicated_q05": 0.1,
            "replicated_q50": 0.2,
            "replicated_q95": 0.3,
            "observed": 0.2,
        }
        for model in ["linear", "curvature"]
        for s in ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"]
        for q in [0.05, 0.5, 0.95]
    ]
    plot(tmp_path, curves, events, checks)
    assert len(captured) == 4
    for x in captured:
        np.testing.assert_array_equal(x, [20, 100, 1000, 5000])


def test_report_rejects_wrong_target_prior_or_duplicate_raw_identities():
    result = {
        "records": 1064,
        "events": 33,
        "job": {"target": "NCEI-native-duration", "prior": "base", "kind": "mean-curvature"},
    }
    records = [f"r{j}" for j in range(1064)]
    events = [f"e{j}" for j in range(33)]
    validate_identity(result, records, events, "curvature")
    with pytest.raises(ValueError, match="fit identities"):
        validate_identity(result, records[:-1] + [records[0]], events, "curvature")
    result["job"]["prior"] = "wider"
    with pytest.raises(ValueError, match="fit identities"):
        validate_identity(result, records, events, "curvature")


def test_ppc_schema_rejects_missing_cells_or_cross_model_observation_drift():
    counts = {
        "all": 1064,
        "under-500km": 100,
        "500-to-2000km": 200,
        "2000-to-5000km": 300,
        "5000km-and-above": 464,
    }
    rows = [
        {
            "model": model,
            "stratum": s,
            "scale": scale,
            "quantile": q,
            "records": n,
            "observed": q + 1,
            "replicated_q05": q + 0.9,
            "replicated_q50": q + 1,
            "replicated_q95": q + 1.1,
        }
        for model in ["linear", "curvature"]
        for s, n in counts.items()
        for scale in ["modeled-response", "native-minutes"]
        for q in [0.05, 0.5, 0.95]
    ]
    validate_ppc(rows)
    with pytest.raises(ValueError, match="exact5strata"):
        validate_ppc(rows[:-1])
    rows[-1]["observed"] += 0.5
    with pytest.raises(ValueError, match="identical observed"):
        validate_ppc(rows)
