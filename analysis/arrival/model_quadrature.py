"""Analytic Normal coefficients and tail-controlled one-dimensional SD integration."""

# pyright: basic
from __future__ import annotations

import math
import warnings
from typing import Any, cast

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.integrate import IntegrationWarning, quad
from scipy.optimize import brentq, minimize_scalar
from scipy.special import log_ndtr, logsumexp, ndtr

LOG2PI = math.log(2 * math.pi)


class RegressionQuadrature:
    """Independent Normal coefficient priors and HalfNormal residual SD, constant scale.

    This is the same pooled/distance model, not a conjugate prior replacing its prior.
    Numerical near-exact fits are rejected, never repaired by a residual floor.
    """

    def __init__(self, response, design, coefficient_sd, sigma_sd, *, tolerance=1e-10):
        self.y = np.asarray(response, dtype=float)
        self.x = np.asarray(design, dtype=float)
        self.prior = np.asarray(coefficient_sd, dtype=float)
        self.scale = float(sigma_sd)
        if (
            self.y.ndim != 1
            or not len(self.y)
            or self.x.ndim != 2
            or self.x.shape[0] != len(self.y)
            or not 1 <= self.x.shape[1] <= 2
            or self.prior.shape != (self.x.shape[1],)
            or any(not np.isfinite(v).all() for v in [self.y, self.x, self.prior])
            or (self.prior <= 0).any()
            or not math.isfinite(self.scale)
            or self.scale <= 0
            or not 1e-12 <= tolerance <= 1e-7
        ):
            raise ValueError("finite one/two-column Gaussian regression and proper scales required")
        self.tolerance = tolerance
        w = self.x * self.prior
        u, s, vt = np.linalg.svd(w, full_matrices=False)
        threshold = max(w.shape) * np.finfo(float).eps * s[0] if len(s) else 0
        keep = s > threshold
        self.s = s[keep]
        self.vt = vt[keep]
        self.projection = u[:, keep].T @ self.y
        residual = self.y - u[:, keep] @ self.projection
        self.rank = len(self.s)
        self.n = len(self.y)
        self.residual2 = 0.0 if self.rank == self.n else float(residual @ residual)
        if self.n > self.rank and np.linalg.norm(residual) <= 1e-11 * max(
            1.0, np.linalg.norm(self.y)
        ):
            raise ValueError(
                "unresolved near-exact-fit boundary; truly exact fits have infinite evidence"
            )
        # Complete the coefficient-space basis without an n-by-n data-space matrix.
        self.null = np.linalg.qr(self.vt.T, mode="complete")[0][:, self.rank :]
        self.evaluations = 0
        self._integrate()

    def log_likelihood(self, t):
        if not -350 < t < 350:
            return -np.inf
        v = math.exp(2 * t)
        logdet = (self.n - self.rank) * 2 * t + np.logaddexp(2 * t, 2 * np.log(self.s)).sum()
        quadratic = self.residual2 / v + np.sum(self.projection**2 / (v + self.s**2))
        return float(-0.5 * (self.n * LOG2PI + logdet + quadratic))

    def log_integrand(self, t):
        self.evaluations += 1
        if self.evaluations > 80000:
            raise ValueError("finite quadrature evaluation ceiling reached")
        if not -350 < t < 350:
            return -np.inf
        return (
            self.log_likelihood(t)
            - 0.5 * (math.exp(t) / self.scale) ** 2
            + t
            + 0.5 * math.log(2 / math.pi)
            - math.log(self.scale)
        )

    def tail_log_bounds(self, lo, hi):
        loga = (
            -0.5 * self.n * LOG2PI
            - np.log(self.s).sum()
            + 0.5 * math.log(2 / math.pi)
            - math.log(self.scale)
            - 0.5 * np.sum(self.projection**2 / (math.exp(2 * lo) + self.s**2))
        )
        m = self.n - self.rank
        if self.residual2 == 0:
            left = loga + lo
        else:
            logu = math.log(self.residual2 / 2) - 2 * lo
            logu = min(logu, 700)
            u = math.exp(logu)
            shape = (m - 1) / 2
            if u <= max(shape - 1, 0):
                left = np.inf
            else:
                left = (
                    loga
                    - math.log(2)
                    + (1 - m) / 2 * math.log(self.residual2 / 2)
                    + (shape - 1) * logu
                    - u
                    - math.log1p(-max(shape - 1, 0) / u)
                )
        right = (
            -0.5 * self.n * LOG2PI
            - self.n * hi
            + math.log(2)
            + float(log_ndtr(-math.exp(hi) / self.scale))
        )
        return float(left), right

    def _integrate(self):
        lo = max(-300.0, math.log(self.scale) - 20)
        hi = min(300.0, math.log(self.scale) + 10)
        for _ in range(8):
            grid = np.linspace(lo, hi, 601)
            g = np.array([self.log_integrand(t) for t in grid])
            peaks = []
            for j in range(1, len(grid) - 1):
                if g[j] >= g[j - 1] and g[j] >= g[j + 1]:
                    opt = cast(Any, minimize_scalar)(
                        lambda t: -self.log_integrand(t),
                        bounds=(grid[j - 1], grid[j + 1]),
                        method="bounded",
                        options={"xatol": 1e-12, "maxiter": 150},
                    )
                    if not opt.success:
                        raise ValueError("quadrature peak search failed")
                    peaks.append(float(opt.x))
            if not peaks:
                raise ValueError("no resolved interior evidence peak")
            height = max(self.log_integrand(p) for p in peaks)
            points = list(peaks)
            for peak in peaks:
                for direction in [-1, 1]:
                    step = 0.025
                    for _ in range(12):
                        boundary = peak + direction * step
                        if not lo < boundary < hi:
                            break
                        if self.log_integrand(boundary) < height - 30:
                            points.append(boundary)
                            break
                        step *= 2

            value, error, info = self._scaled_integral(lo, hi, points, height, self.tolerance, 0)
            left, right = self.tail_log_bounds(lo, hi)
            total_tail = float(cast(Any, logsumexp)([left, right]))
            lower_core = value + math.log1p(-error)
            if total_tail - lower_core > math.log(1e-9):
                lo = max(-300.0, lo - 10)
                hi = min(300.0, hi + 2)
                continue
            refined, error2, info2 = self._scaled_integral(
                lo, hi, points, height, max(1e-12, self.tolerance / 10), 1.0
            )
            if abs(value - refined) > 1e-6 or max(error, error2) > 1e-8:
                raise ValueError("tighter/rescaled evidence quadrature failed precision screen")
            self.log_evidence = refined
            self.relative_error = max(error, error2)
            lower_core = min(lower_core, refined + math.log1p(-error2))
            self.log_tail_fraction_bound = total_tail - lower_core
            self.tail_fraction_bound = math.exp(self.log_tail_fraction_bound)
            self.log_evidence_refinement = abs(value - refined)
            self.bounds = (lo, hi)
            self.peaks = peaks
            self.integration_points = points
            self.height = height
            self.intervals = list(
                zip(info2["alist"][: info2["last"]], info2["blist"][: info2["last"]], strict=True)
            )
            self.node_sigma, self.node_weights, self.node_normalizer_error = self._nodes(24)
            self.refined_sigma, self.refined_weights, _ = self._nodes(48)
            return
        raise ValueError("finite evidence tail-expansion budget exhausted")

    def _scaled_integral(self, lo, hi, points, height, tolerance, shift, log_function=None):
        function = self.log_integrand if log_function is None else log_function
        with warnings.catch_warnings():
            warnings.simplefilter("error", IntegrationWarning)
            value, error, info = quad(
                lambda t: math.exp(function(t) - height - shift),
                lo,
                hi,
                points=sorted(set(points)),
                epsabs=tolerance,
                epsrel=tolerance,
                limit=400,
                full_output=1,
            )
        if value <= error or not math.isfinite(value):
            raise ValueError("unresolved evidence integral")
        return math.log(value) + height + shift, error / value, info

    def _nodes(self, order):
        z, w = leggauss(order)
        nodes = []
        weights = []
        for a, b in self.intervals:
            t = (a + b) / 2 + (b - a) / 2 * z
            nodes.extend(t)
            weights.extend(np.log(w * (b - a) / 2))
        nodes = np.asarray(nodes)
        logweights = np.asarray(weights) + np.array([self.log_integrand(t) for t in nodes])
        norm = float(cast(Any, logsumexp)(logweights))
        error = abs(math.expm1(norm - self.log_evidence))
        if error > 1e-8:
            raise ValueError("positive posterior nodes fail evidence normalization")
        return np.exp(nodes), np.exp(logweights - norm), error

    def conditional_coefficients(self, sigma):
        sigma = np.asarray(sigma)
        if sigma.ndim != 1 or not np.isfinite(sigma).all() or (sigma <= 0).any():
            raise ValueError("positive finite residual scale nodes required")
        v = sigma[:, None] ** 2
        mean = (self.projection * self.s / (v + self.s**2)) @ self.vt
        covariance = np.einsum("ri,kr,rj->kij", self.vt, v / (v + self.s**2), self.vt)
        covariance += self.null @ self.null.T
        return mean * self.prior, covariance * self.prior[:, None] * self.prior[None, :]

    def joint_logpdf(self, response, design):
        response = np.asarray(response)
        design = np.asarray(design)
        combined = RegressionQuadrature(
            np.r_[self.y, response],
            np.vstack([self.x, design]),
            self.prior,
            self.scale,
            tolerance=self.tolerance,
        )
        score = combined.log_evidence - self.log_evidence
        direct, error, _ = self._scaled_integral(
            *combined.bounds,
            combined.integration_points,
            combined.height,
            self.tolerance,
            0,
            log_function=lambda t: (
                self.log_integrand(t) + self.conditional_logpdf(t, response, design)
            ),
        )
        agreement = abs(direct - self.log_evidence - score)
        if agreement > 1e-4:
            raise ValueError("conditional predictive integral disagrees with evidence ratio")
        return {
            "log_predictive": score,
            "direct_integral_agreement": agreement,
            "log_error_estimate": self.relative_error + combined.relative_error,
            "direct_integral_error_estimate": error,
            "tail_fraction_bound": self.tail_fraction_bound + combined.tail_fraction_bound,
            "refinement_change": self.log_evidence_refinement + combined.log_evidence_refinement,
        }

    def conditional_logpdf(self, t, response, design):
        variance = math.exp(2 * t)
        mean_std = (self.projection * self.s / (variance + self.s**2)) @ self.vt
        root = np.c_[self.vt.T * np.sqrt(variance / (variance + self.s**2)), self.null]
        residual = response - (design * self.prior) @ mean_std
        w = (design * self.prior) @ root
        u, s, _ = np.linalg.svd(w, full_matrices=False)
        q = u.T @ residual
        perpendicular = residual - u @ q
        remainder = 0.0 if len(s) == len(response) else float(perpendicular @ perpendicular)
        with np.errstate(divide="ignore"):
            determinant = (len(response) - len(s)) * 2 * t + np.logaddexp(
                2 * t, 2 * np.log(s)
            ).sum()
        quadratic = remainder / variance + np.sum(q**2 / (variance + s**2))
        return float(-0.5 * (len(response) * LOG2PI + determinant + quadratic))

    def marginal_predictions(self, response, design):
        response = np.asarray(response)
        design = np.asarray(design)

        def components(sigmas):
            means, covs = self.conditional_coefficients(sigmas)
            mu = means @ design.T
            sd = np.sqrt(sigmas[:, None] ** 2 + np.einsum("ij,kjl,il->ki", design, covs, design))
            return mu, sd

        mu, sd = components(self.node_sigma)
        mu2, sd2 = components(self.refined_sigma)
        pit = np.sum(self.node_weights[:, None] * ndtr((response - mu) / sd), axis=0)
        out = {"pit": pit}
        differences = [
            np.max(
                np.abs(
                    pit
                    - np.sum(self.refined_weights[:, None] * ndtr((response - mu2) / sd2), axis=0)
                )
            )
        ]
        for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
            values = []
            for j in range(len(response)):
                low = float(np.min(mu[:, j] - 12 * sd[:, j]))
                high = float(np.max(mu[:, j] + 12 * sd[:, j]))
                value = cast(Any, brentq)(
                    lambda z, j=j, q=q: float(
                        np.sum(self.node_weights * ndtr((z - mu[:, j]) / sd[:, j])) - q
                    ),
                    low,
                    high,
                    xtol=1e-10,
                )
                values.append(value)
                refined_cdf = float(
                    np.sum(self.refined_weights * ndtr((value - mu2[:, j]) / sd2[:, j]))
                )
                differences.append(abs(refined_cdf - q))
            out[f"q{round(100 * q):02d}"] = np.asarray(values)
        out["maximum_cdf_refinement_difference"] = float(max(differences))
        if out["maximum_cdf_refinement_difference"] > 1e-7:
            raise ValueError("posterior predictive CDF refinement failed")
        return out
