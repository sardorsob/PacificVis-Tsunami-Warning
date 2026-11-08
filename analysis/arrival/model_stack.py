"""Synthetic API smoke; provides no scientific arrival-model inference."""

# pyright: basic
from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np


def smoke_stack(store: Path) -> dict[str, Any]:
    """Sample known synthetic observations and verify backend, APIs and serialization."""
    import pymc as pm
    import xarray as xr

    if store.exists():
        raise ValueError("synthetic result path already exists")
    store.parent.mkdir(parents=True, exist_ok=True)
    with pm.Model(coords={"record": range(5)}) as model:
        mean = pm.Normal("mean", 0, 1)
        pm.Normal("y", mean, 1, observed=np.array([-1, 0, 0, 1, 0.5]), dims="record")
        prior = pm.sample_prior_predictive(draws=20, random_seed=20261107)
        fitted = pm.sample(
            draws=100, tune=100, chains=2, cores=2, random_seed=20261107, progressbar=False
        )
        fitted.to_netcdf(store)
        pm.compute_log_likelihood(fitted, model=model)
        fitted.to_netcdf(store, mode="w")
        predictive = pm.sample_posterior_predictive(fitted, random_seed=20261107)
    if not isinstance(prior, xr.DataTree) or "prior_predictive" not in prior:
        raise ValueError("prior predictive DataTree API failed")
    if "posterior_predictive" not in predictive:
        raise ValueError("posterior predictive API failed")
    backend = str(fitted["posterior"].attrs)
    if "nutpie" not in backend.lower():
        raise ValueError(f"required nutpie backend not verified: {backend}")
    if not np.isfinite(cast(Any, fitted["log_likelihood"])["y"].values).all():
        raise ValueError("nonfinite synthetic log likelihood")
    with xr.open_datatree(store) as restored:
        np.testing.assert_array_equal(restored["posterior"]["mean"], fitted["posterior"]["mean"])
    divergences = int(cast(Any, fitted["sample_stats"])["diverging"].values.sum())
    if divergences:
        raise ValueError("synthetic smoke diverged")
    return {
        "scientific_model_fitted": False,
        "synthetic_sampler_used": True,
        "seed": 20261107,
        "draws_per_chain": 100,
        "chains": 2,
        "tune": 100,
        "backend": "nutpie",
        "backend_attributes": backend,
        "divergences": divergences,
        "finite_log_likelihood": True,
        "save_reload_equal": True,
        "prior_predictive_checked": True,
        "posterior_predictive_checked": True,
        "versions": {
            p: version(p)
            for p in [
                "pymc",
                "pytensor",
                "arviz",
                "arviz-base",
                "arviz-stats",
                "nutpie",
                "preliz",
                "h5netcdf",
                "h5py",
                "xarray",
                "numpy",
            ]
        },
    }
