"""Full-positive-domain cubature using an explicitly normalized coordinate proposal."""

# pyright: basic
from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
from scipy.integrate import cubature
from scipy.special import gammaln, stdtr, stdtrit


class PositiveProposal:
    """Product Student-t(5), truncated at zero; a coordinate map, not a model prior."""

    def __init__(self, location, scale):
        self.location = np.asarray(location, dtype=float)
        self.scale = np.asarray(scale, dtype=float)
        if (
            self.location.ndim != 1
            or self.scale.shape != self.location.shape
            or not np.isfinite(self.location).all()
            or not np.isfinite(self.scale).all()
            or (self.location < 0).any()
            or (self.scale <= 0).any()
        ):
            raise ValueError("finite positive proposal scales and nonnegative locations required")
        self.lower = stdtr(5.0, -self.location / self.scale)
        self.log_density_at_zero = float(gammaln(3.0) - gammaln(2.5) - 0.5 * math.log(5 * math.pi))

    def transform(self, uniform):
        uniform = np.asarray(uniform)
        if (
            uniform.ndim != 2
            or uniform.shape[1] != len(self.location)
            or ((uniform <= 0) | (uniform >= 1)).any()
        ):
            raise ValueError("interior unit-cube coordinates required")
        probability = self.lower + (1 - self.lower) * uniform
        z = stdtrit(5.0, probability)
        x = self.location + self.scale * z
        logpdf = self.log_density_at_zero - 3 * np.log1p(z * z / 5)
        jacobian = np.sum(np.log(self.scale) + np.log1p(-self.lower) - logpdf, axis=1)
        return x, jacobian


def integrate_positive(
    log_target, proposal, *, relative_tolerance=1e-7, max_points=500000, shift=0.0
):
    """Integrate over the complete positive orthant, with finite point/subdivision ceilings.

    The error is the cubature routine's estimate, not a universal error certificate.
    A second proposal/refinement and independent known-case checks remain necessary.
    """
    dimension = len(proposal.location)
    if (
        dimension not in {2, 4}
        or not 1e-9 <= relative_tolerance <= 1e-4
        or not 1000 <= max_points <= 2000000
    ):
        raise ValueError("bounded two/four-dimensional prototype allocation required")
    median = np.maximum(proposal.location, 0.5 * proposal.scale)
    center_cdf = (stdtr(5.0, (median - proposal.location) / proposal.scale) - proposal.lower) / (
        1 - proposal.lower
    )
    center, jac = proposal.transform(center_cdf[None, :])
    height = float(log_target(center)[0] + jac[0]) + shift
    if not math.isfinite(height):
        raise ValueError("unresolved cubature scaling height")
    points = 0

    def integrand(u):
        nonlocal points
        points += len(u)
        if points > max_points:
            raise ValueError("cubature point ceiling reached")
        x, j = proposal.transform(u)
        valid = (x >= 0).all(axis=1) & np.isfinite(x).all(axis=1) & np.isfinite(j)
        output = np.zeros(len(u))
        if valid.any():
            value = log_target(x[valid]) + j[valid] - height
            if not np.isfinite(value).all() or (value > 700).any():
                raise ValueError("unresolved transformed positive integrand")
            output[valid] = np.exp(value)
        return output

    result = cast(Any, cubature)(
        integrand,
        np.zeros(dimension),
        np.ones(dimension),
        rule="gk15",
        rtol=relative_tolerance,
        atol=0,
        max_subdivisions=4000,
        workers=1,
    )
    value = float(result.estimate)
    error = float(result.error)
    if result.status != "converged" or value <= error or not math.isfinite(value):
        raise ValueError("cubature did not meet the declared precision")
    return {
        "log_evidence": math.log(value) + height,
        "relative_error_estimate": error / value,
        "points": points,
        "subdivisions": int(result.subdivisions),
        "status": result.status,
        "dimension": dimension,
        "full_positive_domain": True,
        "scale_height": height,
        "proposal_location": proposal.location.tolist(),
        "proposal_scale": proposal.scale.tolist(),
    }
