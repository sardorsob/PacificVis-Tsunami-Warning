"""Independent checks stay fast and use synthetic responses, never new fits."""

# pyright: basic
from typing import Any, cast

import numpy as np
import pytest
from scipy.stats import multivariate_normal

from scripts.check_arrival_curvature_sumatra_path import (
    covariance_oracle,
    dense_event,
    dense_logp,
    point_dict,
)
from tests.test_arrival_model_scale import grouped_lane


def test_dense_reference_uses_shared_event_covariance_and_unconstrained_coordinates():
    lane = grouped_lane()
    vector = np.r_[0.1, -0.05, 0.4, np.log([0.2, 0.6, 0.3, 0.12])]
    ids = np.array([0, 1])
    d = lane.distance_km[ids]
    sd = np.interp(np.log(d), np.log([500, 2000, 5000]), [0.6, 0.3, 0.12])
    mean = 0.1 - 0.05 * np.log(d / 1000) + 0.4 * np.log((d + 500) / (1.5 * d))
    expected = cast(Any, multivariate_normal).logpdf(
        lane.response[ids], mean, np.diag(sd**2) + 0.04
    )
    assert dense_event(lane, ids, vector) == pytest.approx(expected, abs=1e-12)
    assert list(point_dict(vector)) == [
        "alpha",
        "beta",
        "gamma",
        "tau_event_log__",
        "sigma_anchor_log__",
    ]
    held = np.array([2])
    assert dense_logp(lane, ids, held, vector, 1) - dense_logp(
        lane, ids, held, vector, 0
    ) == pytest.approx(dense_event(lane, held, vector), abs=1e-12)


def test_exact_49_22_9_covariance_detects_t0_double_counting_and_independent_training_error():
    result = covariance_oracle(np.exp(np.linspace(1, 5, 49)))
    assert result["actual_mcse"] > 0
    assert result["actual_mcse"] == result["independent_assembly_mcse"]
    assert result["actual_mcse"] != result["incorrect_double_counted_t0_mcse"]
    assert result["actual_mcse"] != result["incorrect_independent_training_mcse"]
    assert result["wrong_training_sha_and_shape_rejected"] is True
