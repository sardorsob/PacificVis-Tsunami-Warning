"""Replace one failed numerical integral without changing its model or predictions."""

# pyright: basic
from __future__ import annotations

import math

import numpy as np

from analysis.arrival.model_path_fold_resolution import path_fold_score


def resolved_path_result(
    original, primary, repeat_check, influences, bridge_arrays, native, *, training_sha
):
    """Pure score assembly; the calling run must verify independent evidence first.

    The original failed bridge remains immutable. Its training-only predictions
    are retained, and the predesignated primary path supplies the resolved score.
    """
    native = np.asarray(native)
    if (
        original.get("status") != "precision_failure"
        or original.get("prediction_precision_passed") is not True
        or original.get("observation_measure") != "native_minutes_Jacobian_already_applied_once"
        or original["job"].get("kind") != "mean-curvature"
        or original["job"].get("target") != "NCEI-native-duration"
        or original["job"].get("prior") != "base"
        or primary.get("kind") != "mean-curvature"
        or primary.get("target") != "NCEI-native-duration"
        or primary.get("precision_passed") is not True
        or native.ndim != 1
        or not len(native)
        or not np.isfinite(native).all()
        or (native <= 0).any()
        or primary.get("records") != len(native)
        or not math.isclose(
            primary.get("native_jacobian_subtracted_once", float("nan")),
            float(np.log(native).sum()),
            abs_tol=1e-10,
            rel_tol=0,
        )
        or repeat_check.get("agreement_passed") is not True
        or repeat_check.get("primary_designated_before_fitting") is not True
        or repeat_check.get("score_to_use") != "primary_never_select_favorable_repeat"
    ):
        raise ValueError("accepted same-model primary path with one native Jacobian required")
    fold = path_fold_score(original, primary, influences, bridge_arrays, training_sha=training_sha)
    events = []
    for old in original["events"]:
        if old["event_id"] == primary["event_id"]:
            events.append(
                {
                    **{k: old[k] for k in ["event_id", "sequence", "records"]},
                    **{
                        k: primary[k]
                        for k in [
                            "joint_log_predictive",
                            "normalized_event_score",
                            "normalized_mcse",
                            "joint_log_mcse_delta",
                            "method",
                            "precision_passed",
                        ]
                    },
                }
            )
        else:
            events.append(dict(old))
    return {
        **original,
        "status": "computed_pending_review",
        "events": events,
        "fold_score": fold,
        "score_precision_passed": True,
        "retained_direct_bridge_status": original["status"],
        "score_resolution": "predesignated_same_model_full_coefficient_power_path",
        "prediction_source": "unchanged_original_training_only_predictions",
    }
