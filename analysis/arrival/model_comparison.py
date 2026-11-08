"""Paired equal-event score differences with descriptive sequence-cluster uncertainty."""

# pyright: basic
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from scipy.stats import t


def _rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        event = row["event_id"]
        n = float(row["records"])
        score, joint = float(row["normalized_event_score"]), float(row["joint_log_predictive"])
        if (
            not event
            or event == "unknown"
            or event in result
            or row["target"] not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
            or row["precision_passed"] is not True
            or not row["sequence"]
            or row["sequence"] == "unknown"
            or any(
                not isinstance(row[key], str)
                or re.fullmatch(r"[0-9a-f]{64}", row[key]) is None
                for key in ["cohort_sha256", "record_membership_sha256"]
            )
            or not np.isfinite([n, score, joint]).all()
            or n < 1
            or n != math.floor(n)
            or not math.isclose(score, joint / n, abs_tol=1e-10, rel_tol=0)
        ):
            raise ValueError(
                "unique resolved native joint event scores and cohort identities required"
            )
        result[event] = {**row, "records": int(n), "normalized_event_score": score}
    if not result:
        raise ValueError("nonempty event scores required")
    return result


def paired_sequence_comparison(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    *,
    first_mcse: float | None = None,
    second_mcse: float | None = None,
    first_deterministic_error: float | None = None,
    second_deterministic_error: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Difference is first minus second, in nats/record within each event.

    MCSE inputs are already covariance-aware equal-event aggregates. Their streams
    must be independent across models. Cluster SE uses G/(G-1) times squared
    centered cluster totals/E²; t intervals are descriptive, with overlapping
    training sets and a small number of heuristic physical-sequence clusters.
    """
    a, b = _rows(first), _rows(second)
    if set(a) != set(b):
        raise ValueError("identical eligible event sets required")
    targets = {r["target"] for r in [*a.values(), *b.values()]}
    cohorts = {r["cohort_sha256"] for r in [*a.values(), *b.values()]}
    if len(targets) != 1 or len(cohorts) != 1:
        raise ValueError("targets and data cohorts cannot be pooled or compared as identical")
    ids = sorted(a)
    for event in ids:
        if any(
            a[event][key] != b[event][key]
            for key in ["sequence", "records", "record_membership_sha256"]
        ):
            raise ValueError("event/sequence record memberships differ")
    delta = np.array(
        [a[event]["normalized_event_score"] - b[event]["normalized_event_score"] for event in ids]
    )
    sequences = np.array([a[event]["sequence"] for event in ids])
    groups = sorted(set(sequences))
    if len(groups) < 2:
        raise ValueError("at least two sequences needed for descriptive cluster uncertainty")
    mean = float(delta.mean())
    totals = np.array([np.sum(delta[sequences == group] - mean) for group in groups])
    variance = len(groups) / (len(groups) - 1) * float(totals @ totals) / len(ids) ** 2
    se = math.sqrt(variance)
    half = float(t.ppf(0.975, len(groups) - 1)) * se
    errors = [first_mcse, second_mcse, first_deterministic_error, second_deterministic_error]
    if any(v is not None and (not math.isfinite(v) or v < 0) for v in errors):
        raise ValueError("nonnegative finite numerical errors or not-applicable None required")
    mcse = (
        None
        if first_mcse is None and second_mcse is None
        else math.hypot(first_mcse or 0, second_mcse or 0)
    )
    deterministic = (
        None
        if first_deterministic_error is None and second_deterministic_error is None
        else (first_deterministic_error or 0) + (second_deterministic_error or 0)
    )
    contributions = []
    for group in groups:
        mask = sequences == group
        contributions.append(
            {
                "sequence": group,
                "events": int(mask.sum()),
                "difference_sum": float(delta[mask].sum()),
                "centered_cluster_total": float(np.sum(delta[mask] - mean)),
                "mean_difference_without_cluster": float(delta[~mask].mean()),
                "scope": "score_contribution_deletion_not_an_additional_model_refit",
            }
        )
    return {
        "target": next(iter(targets)),
        "cohort_sha256": next(iter(cohorts)),
        "events": len(ids),
        "sequence_clusters": len(groups),
        "paired_mean_difference": mean,
        "sequence_cluster_se": se,
        "sequence_cluster_ci95_lower": mean - half,
        "sequence_cluster_ci95_upper": mean + half,
        "sequence_cluster_t_df": len(groups) - 1,
        "paired_numerical_mcse": mcse,
        "paired_deterministic_error_estimate_sum": deterministic,
        "numerical_mcse_assumption": "independent_simulation_streams_across_models",
        "sampling_uncertainty_scope": (
            "descriptive_sequence_cluster_sandwich_not_an_independence_or_transport_certificate"
        ),
        "practical_yardstick_nats_per_record": 0.01,
        "yardstick_scope": "analyst_reporting_reference_not_automatic_promotion_or_owner_utility",
    }, contributions
