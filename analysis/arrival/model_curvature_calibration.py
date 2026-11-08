"""Retained-output checks for the frozen fifty-recovery / hundred-SBC allocation."""

# pyright: basic
from __future__ import annotations

import hashlib
import json

import numpy as np
import xarray as xr

from analysis.arrival.model_curvature_curve_checks import curve_checks, unbiased_rank
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_curvature_validation import curvature_quantities


def observed_fingerprint(observed):
    digest = hashlib.sha256()
    digest.update(json.dumps(observed.coords["record"].values.tolist()).encode())
    for name in ["response", "native_minutes"]:
        digest.update(np.asarray(observed[name].values, dtype="<f8").tobytes())
    return digest.hexdigest()


def retained_checks(root, posterior_path, result):
    """Derive all twenty-one quantities without rewriting the worker's evidence."""
    tree = xr.open_datatree(posterior_path, engine="h5netcdf")
    try:
        fingerprint = observed_fingerprint(tree["observed_data"])
        posterior = tree["posterior"]
        quantities, _ = curvature_quantities(posterior, None, None)
        if [row["parameter"] for row in result["estimates"]] != list(quantities):
            raise ValueError("complete twelve scalar quantities required in frozen order")
        seed = result["job"]["seed"]
        estimates = [
            unbiased_rank(quantities[row["parameter"]], row["truth"], seed + 10 + j, row)
            for j, row in enumerate(result["estimates"])
        ]
        functional = curve_checks(
            posterior, result["truth"], read_curvature_prior(root, "base"), seed
        )
        return {
            "case_id": result["job"]["id"],
            "synthetic_observed_data_sha256": fingerprint,
            "estimates": estimates,
            "functional": functional,
            "rank_ready": all(row["rank_ready"] for row in estimates) and functional["rank_ready"],
            "scope": "computational calibration; original worker evidence retained unchanged",
        }
    finally:
        tree.close()
