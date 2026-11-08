"""Integrate Normal coefficients and event effects at fixed residual/event scales."""

# pyright: basic
from __future__ import annotations

import math

import numpy as np


class CollapsedGaussian:
    """Positive weighted residual quadratics; at most 128 hyperparameter points per batch."""

    def __init__(self, response, design, events, scale_basis, coefficient_sd):
        y = np.asarray(response, dtype=float)
        x = np.asarray(design, dtype=float)
        e = np.asarray(events)
        w = np.asarray(scale_basis, dtype=float)
        prior = np.asarray(coefficient_sd, dtype=float)
        if (
            y.ndim != 1
            or not len(y)
            or x.ndim != 2
            or x.shape[0] != len(y)
            or not 1 <= x.shape[1] <= 4
            or e.shape != y.shape
            or w.ndim != 2
            or w.shape[0] != len(y)
            or not 1 <= w.shape[1] <= 3
            or prior.shape != (x.shape[1],)
            or any(not np.isfinite(v).all() for v in [y, x, w, prior])
            or (prior <= 0).any()
            or (w < 0).any()
            or not np.allclose(w.sum(axis=1), 1)
        ):
            raise ValueError("aligned finite Gaussian design and convex SD weights required")
        order = np.argsort(e, kind="stable")
        self.y = y[order]
        self.x = x[order]
        self.events = e[order]
        self.weights = w[order]
        self.prior = prior
        self.design = self.x * prior
        self.n = len(y)
        self.p = x.shape[1]
        _, self.event_index = np.unique(self.events, return_inverse=True)
        self.starts = np.r_[0, np.flatnonzero(np.diff(self.event_index)) + 1]
        self.counts = np.diff(np.r_[self.starts, self.n])
        self.mean_y = np.add.reduceat(self.y, self.starts) / self.counts
        self.mean_x = np.add.reduceat(self.design, self.starts, axis=0) / self.counts[:, None]
        yc = self.y - self.mean_y[self.event_index]
        xc = self.design - self.mean_x[self.event_index]
        self.within_qr = np.linalg.qr(np.c_[yc, xc], mode="r")
        self.within_xx = xc.T @ xc
        self.within_xy = xc.T @ yc

    def evaluate(self, values, *, coefficients=False):
        values = np.asarray(values, dtype=float)
        if (
            values.ndim != 2
            or values.shape[1] != self.weights.shape[1] + 1
            or not len(values)
            or not np.isfinite(values).all()
            or (values < 0).any()
        ):
            raise ValueError("finite nonnegative raw SD anchors plus event SD required")
        result = []
        means = []
        precisions = []
        for start in range(0, len(values), 128):
            v = values[start : start + 128]
            tau2 = v[:, -1] ** 2
            if self.weights.shape[1] == 1:
                sigma2 = v[:, 0] ** 2
                if (sigma2 <= 0).any():
                    raise ValueError("positive record SDs required")
                denominator = sigma2[:, None] + self.counts * tau2[:, None]
                bw = self.counts / denominator
                precision = (
                    np.eye(self.p)
                    + self.within_xx[None, :, :] / sigma2[:, None, None]
                    + np.einsum("he,ei,ej->hij", bw, self.mean_x, self.mean_x)
                )
                h = self.within_xy[None, :] / sigma2[:, None] + np.einsum(
                    "he,ei,e->hi", bw, self.mean_x, self.mean_y
                )
                b = np.linalg.solve(precision, h[..., None])[..., 0]
                within = np.einsum("ij,hj->hi", self.within_qr, np.c_[np.ones(len(v)), -b])
                quadratic = np.sum(within**2, axis=1) / sigma2
                residual = self.mean_y[None, :] - np.einsum("ei,hi->he", self.mean_x, b)
                quadratic += np.sum(bw * residual**2, axis=1) + np.sum(b**2, axis=1)
                logdet = (self.n - len(self.counts)) * np.log(sigma2) + np.log(denominator).sum(
                    axis=1
                )
            else:
                sigma = v[:, :-1] @ self.weights.T
                if (sigma <= 0).any():
                    raise ValueError("positive record SDs required")
                weight = 1 / sigma**2
                total = np.add.reduceat(weight, self.starts, axis=1)
                my = np.add.reduceat(weight * self.y, self.starts, axis=1) / total
                mx = (
                    np.add.reduceat(weight[..., None] * self.design, self.starts, axis=1)
                    / total[..., None]
                )
                xc = self.design[None, :, :] - mx[:, self.event_index, :]
                yc = self.y[None, :] - my[:, self.event_index]
                bw = total / (1 + tau2[:, None] * total)
                precision = (
                    np.eye(self.p)
                    + np.einsum("hn,hni,hnj->hij", weight, xc, xc)
                    + np.einsum("he,hei,hej->hij", bw, mx, mx)
                )
                h = np.einsum("hn,hni,hn->hi", weight, xc, yc) + np.einsum(
                    "he,hei,he->hi", bw, mx, my
                )
                b = np.linalg.solve(precision, h[..., None])[..., 0]
                residual = yc - np.einsum("hni,hi->hn", xc, b)
                between = my - np.einsum("hei,hi->he", mx, b)
                quadratic = (
                    np.sum(weight * residual**2, axis=1)
                    + np.sum(bw * between**2, axis=1)
                    + np.sum(b**2, axis=1)
                )
                logdet = 2 * np.log(sigma).sum(axis=1) + np.log1p(tau2[:, None] * total).sum(axis=1)
            sign, det = np.linalg.slogdet(precision)
            if (sign <= 0).any():
                raise ValueError("nonpositive coefficient precision determinant")
            ll = -0.5 * (self.n * math.log(2 * math.pi) + logdet + det + quadratic)
            if not np.isfinite(ll).all():
                raise ValueError("unresolved collapsed Gaussian density")
            result.append(ll)
            means.append(b)
            precisions.append(precision)
        ll = np.concatenate(result)
        return (ll, np.concatenate(means), np.concatenate(precisions)) if coefficients else ll

    def new_event_logpdf(self, values, response, design, scale_basis):
        values = np.asarray(values, dtype=float)
        y = np.asarray(response, dtype=float)
        x = np.asarray(design, dtype=float)
        w = np.asarray(scale_basis, dtype=float)
        if (
            y.ndim != 1
            or x.shape != (len(y), self.p)
            or w.shape != (len(y), self.weights.shape[1])
            or not np.isfinite(y).all()
            or not np.isfinite(x).all()
            or not np.isfinite(w).all()
            or (w < 0).any()
            or not np.allclose(w.sum(axis=1), 1)
        ):
            raise ValueError("aligned finite single-new-event design required")
        output = []
        for start in range(0, len(values), 128):
            v = values[start : start + 128]
            _, b, p = self.evaluate(v, coefficients=True)
            sigma = v[:, :-1] @ w.T
            if (sigma <= 0).any():
                raise ValueError("positive predictive record SDs required")
            root = np.swapaxes(
                np.linalg.solve(np.linalg.cholesky(p), np.broadcast_to(np.eye(self.p), p.shape)),
                1,
                2,
            )
            a = np.concatenate(
                [
                    (v[:, -1, None] / sigma)[..., None],
                    np.einsum("ni,hij->hnj", x * self.prior, root) / sigma[..., None],
                ],
                axis=2,
            )
            residual = (y[None, :] - np.einsum("ni,hi->hn", x * self.prior, b)) / sigma
            precision = np.eye(self.p + 1) + np.einsum("hni,hnj->hij", a, a)
            h = np.einsum("hni,hn->hi", a, residual)
            fitted = np.linalg.solve(precision, h[..., None])[..., 0]
            remainder = residual - np.einsum("hni,hi->hn", a, fitted)
            q = np.sum(remainder**2, axis=1) + np.sum(fitted**2, axis=1)
            sign, det = np.linalg.slogdet(precision)
            if (sign <= 0).any():
                raise ValueError("nonpositive predictive determinant")
            output.append(
                -0.5 * (len(y) * math.log(2 * math.pi) + 2 * np.log(sigma).sum(axis=1) + det + q)
            )
        return np.concatenate(output)
