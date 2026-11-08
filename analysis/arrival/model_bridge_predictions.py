"""Training-only marginal predictions with chain-aware CDF and quantile MCSE."""

# pyright: basic
from __future__ import annotations

import math

import numpy as np
from scipy.special import ndtr

from analysis.arrival.model_prediction import marginal_report_predictions
from analysis.arrival.model_scoring import mean_mcse


def predictions_with_precision(response, mean, sigma, tau, reference, target):
    predicted = marginal_report_predictions(response, mean, sigma, tau, reference, target)
    total = np.sqrt(sigma**2 + tau[..., None] ** 2)
    precision = []
    for j in range(len(response)):
        pit_se = mean_mcse(ndtr((response[j] - mean[..., j]) / total[..., j]))
        width = float(predicted["q95"][j] - predicted["q05"][j])
        if not math.isfinite(width) or width <= 0:
            raise ValueError("unresolved native predictive interval width")
        row = {"pit_mcse": pit_se, "native_interval_90_width": width}
        cdf_errors, relative_quantile_errors = [], []
        for label in ["q05", "q25", "q50", "q75", "q95"]:
            native = float(predicted[label][j])
            r = native if target == "T-CAL" else math.log(native / reference[j])
            z = (r - mean[..., j]) / total[..., j]
            cdf_mcse = mean_mcse(ndtr(z))
            density = float(
                np.mean(np.exp(-0.5 * z * z) / (math.sqrt(2 * math.pi) * total[..., j]))
            )
            if target != "T-CAL":
                density /= native
            if not math.isfinite(density) or density <= 0:
                raise ValueError("unresolved predictive density at a quantile")
            quantile_mcse = cdf_mcse / density
            row[label + "_cdf_mcse"] = cdf_mcse
            row[label + "_mcse_native"] = quantile_mcse
            cdf_errors.append(cdf_mcse)
            relative_quantile_errors.append(quantile_mcse / width)
        row["max_quantile_cdf_mcse"] = max(cdf_errors)
        row["max_quantile_mcse_fraction_interval_width"] = max(relative_quantile_errors)
        row["prediction_precision_passed"] = bool(
            pit_se <= 0.005 and max(cdf_errors) <= 0.005 and max(relative_quantile_errors) <= 0.01
        )
        row["coverage90_numerically_ambiguous"] = bool(
            any(abs(predicted["pit"][j] - boundary) <= 3 * pit_se for boundary in [0.05, 0.95])
        )
        precision.append(row)
    return predicted, precision
