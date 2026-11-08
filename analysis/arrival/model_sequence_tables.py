"""Source-specific comparison and calibration tables for complete sequence validation."""

# pyright: basic
from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations

from analysis.arrival.model_comparison import paired_sequence_comparison
from analysis.arrival.model_sequence_report import event_weighted_pit_curve, predictive_statistics


def prediction_strata(rows) -> Iterator[tuple[str, list]]:
    """Fixed physical distances and geographic-site support; no learned cut points."""
    yield "all", rows
    for name, low, high in [
        ("under-500km", 0, 500),
        ("500-to-2000km", 500, 2000),
        ("2000-to-5000km", 2000, 5000),
        ("5000km-and-above", 5000, float("inf")),
    ]:
        subset = [r for r in rows if low <= r["distance_km"] < high]
        if subset:
            yield name, subset
    for seen in [True, False]:
        subset = [r for r in rows if r["seen_site"] is seen]
        if subset:
            yield "seen-geographic-site" if seen else "unseen-geographic-site", subset


def comparison_tables(models, *, bootstrap_replicates=2000):
    """Keep sampling uncertainty, Monte Carlo error and deterministic estimates distinct."""
    tables = {
        name: []
        for name in [
            "model-scores",
            "paired-score-differences",
            "sequence-score-influence",
            "event-joint-scores",
            "predictive-calibration-by-stratum",
            "event-weighted-pit",
        ]
    }
    for (target, kind), model in models.items():
        summary = model["summary"]
        mcse = summary["monte_carlo_standard_error"] if summary["monte_carlo_used"] else None
        tables["model-scores"].append(
            {
                "target": target,
                "model": kind,
                "records": summary["records"],
                "events": summary["events"],
                "sequence_refits": len({e["sequence"] for e in model["events"]}),
                "equal_event_score": summary["equal_event_score"],
                "row_weighted_joint_score_secondary": summary["row_weighted_joint_score"],
                "monte_carlo_standard_error": mcse,
                "deterministic_error_estimate": summary["mean_numerical_error_estimate"],
                "cohort_sha256": summary["cohort_sha256"],
                "score_units": "native_minute_joint_log_density_per_record_equal_event_mean",
            }
        )
        tables["event-joint-scores"] += [{"model": kind, **e} for e in model["events"]]
        for stratum, subset in prediction_strata(model["predictions"]):
            identity = {"target": target, "model": kind, "stratum": stratum}
            tables["predictive-calibration-by-stratum"].append(
                {
                    **identity,
                    **predictive_statistics(subset),
                }
            )
            tables["event-weighted-pit"] += [
                {**identity, **r}
                for r in event_weighted_pit_curve(
                    subset,
                    replicates=bootstrap_replicates,
                )
            ]
    for target in ["NCEI-native-duration", "T-OBS", "T-CAL"]:
        kinds = [k for t, k in models if t == target]
        for second, first in combinations(kinds, 2):
            a, b = models[(target, first)], models[(target, second)]
            sa, sb = a["summary"], b["summary"]
            comparison, influence = paired_sequence_comparison(
                a["events"],
                b["events"],
                first_mcse=sa["monte_carlo_standard_error"] if sa["monte_carlo_used"] else None,
                second_mcse=sb["monte_carlo_standard_error"] if sb["monte_carlo_used"] else None,
                first_deterministic_error=sa["mean_numerical_error_estimate"],
                second_deterministic_error=sb["mean_numerical_error_estimate"],
            )
            identity = {"first_model": first, "second_model": second}
            tables["paired-score-differences"].append({**identity, **comparison})
            tables["sequence-score-influence"] += [
                {"target": target, **identity, **r} for r in influence
            ]
    return tables
