"""One resolved path integral retains common-training covariance with direct bridges."""

# pyright: basic
from __future__ import annotations

import math
import re

import numpy as np

from analysis.arrival.model_scoring import mean_mcse


def path_fold_score(original, path_score, path_influences, bridge_arrays, *, training_sha):
    events = original["events"]
    event = path_score["event_id"]
    if (
        not isinstance(training_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", training_sha) is None
        or len({e["event_id"] for e in events}) != len(events)
        or {e["event_id"] for e in events if not e["precision_passed"]} != {event}
        or path_score["source_training_posterior_sha"] != training_sha
        or path_score["precision_passed"] is not True
        or len(path_influences) != 17
    ):
        raise ValueError(
            "one complete accepted path and identical original training draws required"
        )
    recovered = next(e for e in events if e["event_id"] == event)
    n = path_score["records"]
    count = len(events)
    if (
        n != recovered["records"]
        or path_score["sequence"] != recovered["sequence"]
        or not math.isclose(
            path_score["joint_log_predictive"] / n,
            path_score["normalized_event_score"],
            abs_tol=1e-10,
            rel_tol=0,
        )
    ):
        raise ValueError("same native joint event score required")
    variance = sum(mean_mcse(a) ** 2 for a in path_influences)
    if not math.isclose(
        math.sqrt(variance), path_score["joint_log_mcse_delta"], abs_tol=1e-10, rel_tol=1e-8
    ):
        raise ValueError("path influence cache and event MCSE differ")
    shape = path_influences[0].shape
    shared = path_influences[0] / n / count
    independent = sum((mean_mcse(a) / n / count) ** 2 for a in path_influences[1:])
    values = []
    for j, e in enumerate(events):
        if e["event_id"] == event:
            values.append(path_score["normalized_event_score"])
        else:
            first = bridge_arrays[f"training_influence_{j:03d}"]
            if first.shape != shape:
                raise ValueError("training chain/draw arrays must align exactly")
            shared = shared + first / e["records"] / count
            independent += (
                mean_mcse(bridge_arrays[f"augmented_influence_{j:03d}"]) / e["records"] / count
            ) ** 2
            values.append(e["normalized_event_score"])
    if not np.isfinite(values).all():
        raise ValueError("finite native scores required")
    return {
        "equal_event_score": float(np.mean(values)),
        "events": count,
        "mcse_equal_event_score": math.sqrt(mean_mcse(shared) ** 2 + independent),
        "event_precision_passed": True,
        "monte_carlo_used": True,
        "mean_deterministic_error_estimate": 0.0,
        "mcse_scope": (
            "path_and_other_event_training_influences_combined_before_independent_stage_variances"
        ),
        "source_training_posterior_sha": training_sha,
        "primary_path_training_variance": "included_once_in_shared_vector_not_added_again",
    }
