"""Explicit numerical resolutions preserve original failures and native score targets."""

# pyright: basic
from __future__ import annotations

import math

import numpy as np

from analysis.arrival.model_bridge import bridge_fold_score


def hybrid_fold_score(original, deterministic, arrays):
    """Replace failed event integrals, retaining shared-training MC covariance elsewhere.

    Deterministic errors are estimates, added separately from MCSE. Original
    result objects and failed influences remain intact and are never averaged in.
    """
    events = original["events"]
    unresolved = {e["event_id"] for e in events if not e["precision_passed"]}
    if not unresolved or set(deterministic) != unresolved:
        raise ValueError("exactly the unresolved event scores need reviewed numerical integrals")
    values, mcscores, first, second = [], [], [], []
    error, refinement = 0.0, 0.0
    for i, event in enumerate(events):
        if event["event_id"] in deterministic:
            fixed = deterministic[event["event_id"]]
            if (
                any(
                    fixed[k] != v
                    for k, v in {
                        "event_id": event["event_id"],
                        "records": event["records"],
                        "sequence": original["job"]["sequence"],
                        "target": original["job"]["target"],
                        "kind": original["job"]["kind"],
                        "precision_passed": True,
                        "monte_carlo_used": False,
                    }.items()
                )
                or not math.isclose(
                    fixed["joint_log_predictive"] / fixed["records"],
                    fixed["normalized_event_score"],
                    rel_tol=0,
                    abs_tol=1e-10,
                )
                or any(
                    not math.isfinite(fixed[k]) or not 0 <= fixed[k] <= 1e-6
                    for k in [
                        "numerical_error_estimate_per_record",
                        "max_refinement_agreement_nats_per_record",
                    ]
                )
            ):
                raise ValueError("same native event score and passed deterministic checks required")
            values.append(fixed["normalized_event_score"])
            error += fixed["numerical_error_estimate_per_record"]
            refinement += fixed["max_refinement_agreement_nats_per_record"]
        else:
            values.append(event["normalized_event_score"])
            mcscores.append(event)
            first.append(arrays[f"training_influence_{i:03d}"])
            second.append(arrays[f"augmented_influence_{i:03d}"])
    if not np.isfinite(values).all():
        raise ValueError("finite native event score values required")
    # Rescale the MC subset's equal-event mean back to the full event count.
    mc = bridge_fold_score(mcscores, first, second) if mcscores else None
    return {
        "equal_event_score": float(np.mean(values)),
        "events": len(events),
        "mcse_equal_event_score": 0.0
        if mc is None
        else mc["mcse_equal_event_score"] * len(mcscores) / len(events),
        "monte_carlo_used": bool(mcscores),
        "mean_deterministic_error_estimate": error / len(events),
        "mean_deterministic_refinement_agreement": refinement / len(events),
        "deterministic_event_scores": len(deterministic),
        "event_precision_passed": True if mc is None else mc["event_precision_passed"],
        "min_MC_bridge_overlap": "not_applicable" if mc is None else mc["min_bridge_overlap"],
        "mcse_scope": "shared_training_covariance_of_MC_subset_no_MC_error_assigned_to_cubature",
        "deterministic_error_scope": "routine_estimates_and_refinement_not_rigorous_bounds",
    }
