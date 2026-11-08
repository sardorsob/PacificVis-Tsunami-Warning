"""Retained diagnostics keep records aligned and original worker files immutable."""

# pyright: basic
import copy

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_curvature_calibration as checks
from analysis.arrival.model_validation import rank_summary


def test_observation_fingerprint_detects_alignment_and_both_time_scales():
    data = xr.Dataset(
        {"response": (("record",), [0.1, 0.2]), "native_minutes": (("record",), [20.0, 30.0])},
        coords={"record": ["a", "b"]},
    )
    original = checks.observed_fingerprint(data)
    assert checks.observed_fingerprint(data.copy(deep=True)) == original
    assert checks.observed_fingerprint(data.isel(record=[1, 0])) != original
    for field in ["response", "native_minutes"]:
        changed = data.copy(deep=True)
        changed[field].values[0] += 1
        assert checks.observed_fingerprint(changed) != original


def test_retained_checks_do_not_rewrite_original_estimates(tmp_path, monkeypatch):
    rng = np.random.default_rng(71)
    values = rng.normal(size=(4, 2000))
    quantities = {f"q{j}": values + j for j in range(12)}
    seed = 72
    result = {
        "job": {"id": "sbc-fixture", "seed": seed},
        "truth": {},
        "estimates": [
            {"parameter": name, "truth": j, **rank_summary(v, j, seed + 10 + j)}
            for j, (name, v) in enumerate(quantities.items())
        ],
    }
    original = copy.deepcopy(result)
    tree = xr.DataTree.from_dict(
        {
            "posterior": xr.Dataset({"fixture": (("chain", "draw"), values)}),
            "observed_data": xr.Dataset(
                {"response": (("record",), [0.1]), "native_minutes": (("record",), [20.0])},
                coords={"record": ["a"]},
            ),
        }
    )
    path = tmp_path / "posterior.nc"
    tree.to_netcdf(path)
    payload = path.read_bytes()
    monkeypatch.setattr(checks, "curvature_quantities", lambda *a: (quantities, {}))
    monkeypatch.setattr(checks, "read_curvature_prior", lambda *a: {})
    monkeypatch.setattr(
        checks, "curve_checks", lambda *a: {"rank_ready": True, "estimates": [{}] * 9}
    )
    answer = checks.retained_checks(tmp_path, path, result)
    assert answer["rank_ready"] and len(answer["estimates"]) == 12
    assert result == original and path.read_bytes() == payload
    result["estimates"].reverse()
    with pytest.raises(ValueError, match="frozen order"):
        checks.retained_checks(tmp_path, path, result)
