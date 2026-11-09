"""Pure labelled new-event report predictions using the accepted precision helper.

Marginal PIT and predictive intervals are distinct from joint event scores. Only
Normal event/report noise is integrated; population coefficients remain explicit
under every prior family. No loading, fitting, source approval or UTC imputation.
"""

# pyright: basic
from __future__ import annotations

import math

import numpy as np
import xarray as xr

from analysis.arrival.model_bridge_predictions import predictions_with_precision
from analysis.arrival.model_curvature_cv import posterior_components as curved_components
from analysis.arrival.model_data import Lane
from analysis.arrival.model_development_scoring import QUALIFICATION, event_loglikelihood
from analysis.arrival.model_prediction import posterior_components

QUANTILES = ("q05", "q25", "q50", "q75", "q95")
PRECISION_KEYS = {
    "pit_mcse",
    "native_interval_90_width",
    "max_quantile_cdf_mcse",
    "max_quantile_mcse_fraction_interval_width",
    "prediction_precision_passed",
    "coverage90_numerically_ambiguous",
} | {q + suffix for q in QUANTILES for suffix in ["_cdf_mcse", "_mcse_native"]}


def new_event_predictions(
    lane: Lane, held_indices, kind: str, posterior: xr.Dataset, *, training_distance_range_km
):
    """Return ordered record rows and metadata for one caller-frozen held event.

    Training distance support is supplied explicitly, never inferred from held
    outcomes. The public scorer supplies common input/coordinate/content guards;
    its joint likelihood is discarded here. This adapter makes no score estimate.
    Existing mixture-CDF root tolerances and chain-aware delta-MCSE policy are
    unchanged. Failed finite precision screens retain their rows for review.
    """
    support = np.asarray(training_distance_range_km)
    if (
        support.shape != (2,)
        or support.dtype.kind not in "iuf"
        or not np.isfinite(support).all()
        or not 0 < support[0] <= support[1]
    ):
        raise ValueError("explicit finite positive ordered training km range required")
    _, proof = event_loglikelihood(lane, held_indices, kind, posterior)
    if posterior.sizes["draw"] < 100:
        raise ValueError("at least100 retained draws per each of four chains required")
    held = np.asarray(held_indices)
    distance = lane.distance_km[held]
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            mean, sigma, tau = (
                curved_components(posterior, distance)
                if kind == "mean-curvature"
                else posterior_components(posterior, kind, distance)
            )
            predicted, precision = predictions_with_precision(
                lane.response[held], mean, sigma, tau, lane.reference_minutes[held], lane.target
            )
    except (FloatingPointError, OverflowError) as error:
        raise ValueError("unrepresentable marginal predictive quantities or precision") from error
    if (
        set(predicted) != {"pit", "pit_chain_range", *QUANTILES}
        or len(precision) != len(held)
        or any(np.asarray(v).shape != (len(held),) for v in predicted.values())
    ):
        raise ValueError("complete aligned accepted marginal prediction schema required")
    rows = []
    for j, i in enumerate(held):
        values = {key: float(array[j]) for key, array in predicted.items()}
        check = precision[j]
        if (
            set(check) != PRECISION_KEYS
            or not np.isfinite(list(values.values())).all()
            or not 0 <= values["pit"] <= 1
            or not 0 <= values["pit_chain_range"] <= 1
            or any(
                values[a] >= values[b] for a, b in zip(QUANTILES[:-1], QUANTILES[1:], strict=True)
            )
            or lane.target != "T-CAL"
            and values["q05"] <= 0
            or any(
                type(check[k]) is not bool
                for k in ["prediction_precision_passed", "coverage90_numerically_ambiguous"]
            )
            or any(
                not math.isfinite(v) or v < 0
                for k, v in check.items()
                if k not in {"prediction_precision_passed", "coverage90_numerically_ambiguous"}
            )
        ):
            raise ValueError("finite ordered native quantiles/PIT and supported precision required")
        within = bool(support[0] <= distance[j] <= support[1])
        rows.append(
            {
                "record_id": lane.record_ids[int(i)],
                "event_id": lane.event_ids[int(i)],
                "sequence": lane.sequences[int(i)],
                "site_id": lane.site_ids[int(i)],
                "target": lane.target,
                "kind": kind,
                "distance_km": float(distance[j]),
                "reference_minutes": float(lane.reference_minutes[i]),
                "observed_reported_minutes": float(lane.y[i]),
                "modeled_response": float(lane.response[i]),
                "within_training_distance_range": within,
                "distance_support": "within"
                if within
                else "below"
                if distance[j] < support[0]
                else "above",
                "residual_scale_endpoint_clamped": bool(
                    kind in {"distance-scale", "mean-curvature"}
                    and (distance[j] < 500 or distance[j] > 5000)
                ),
                **values,
                **check,
            }
        )
    passed = all(row["prediction_precision_passed"] for row in rows)
    return rows, {
        **{k: v for k, v in proof.items() if k not in {"measure", "native_log_jacobian"}},
        "chain_coordinates": posterior.chain.values.tolist(),
        "draw_coordinates": posterior.draw.values.tolist(),
        "training_distance_range_km": support.astype(float).tolist(),
        "prediction_precision_passed": passed,
        "status": "computed_pending_review" if passed else "needs_numerical_review",
        "method": "existing_posterior_mixture_Normal_marginal_CDF_and_precision",
        "prediction_scope": (
            "new_event_marginal_report_PIT_and_predictive_quantiles_not_joint_score"
        ),
        "interval_type": "new_event_report_predictive_quantiles_05_25_50_75_95",
        "native_units": "signed_minutes" if lane.target == "T-CAL" else "positive_reported_minutes",
        "support_scope": "training_distance_range_only_not_geographic_or_transfer_validity",
        "provenance": "unverified_until_caller_binds_frozen_sources_and_training_posterior_SHA",
        "precision_policy": "existing_PIT_and_quantile_CDF_MCSE<=.005_and_native_MCSE/width<=.01",
        "mixing_scope": "existing_chain_aware_MCSE_not_a_replacement_for_posterior_diagnostics",
        "qualification": QUALIFICATION,
        "physical_UTC_arrival_or_imputation": False,
    }
