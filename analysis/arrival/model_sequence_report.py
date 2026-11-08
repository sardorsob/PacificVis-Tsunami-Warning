"""Native-minute predictive criticism and event-weighted sequence summaries."""

# pyright: basic
from __future__ import annotations

import math

import numpy as np

from analysis.arrival.model_data import sequence_folds


def validate_predictions(lane, rows):
    """Verify one complete model's predictions against the frozen exploration view."""
    expected = {}
    for fold in sequence_folds(lane):
        for i, seen in zip(fold.test, fold.seen_site, strict=True):
            expected[lane.record_ids[int(i)]] = (int(i), fold.sequence_id, bool(seen))
    if len(rows) != len(expected) or {r["record_id"] for r in rows} != set(expected):
        raise ValueError("exact unique primary record membership required")
    for row in rows:
        i, sequence, seen = expected[row["record_id"]]
        q = np.array([row[f"q{v:02d}"] for v in [5, 25, 50, 75, 95]], dtype=float)
        if (
            row["event_id"] != lane.event_ids[i]
            or ("target" in row and row["target"] != lane.target)
            or row["sequence"] != sequence
            or type(row["seen_site"]) is not bool
            or row["seen_site"] != seen
            or not math.isclose(
                float(row["distance_km"]), lane.distance_km[i], rel_tol=1e-12, abs_tol=1e-10
            )
            or not math.isclose(
                float(row["observed_native_minutes"]), lane.y[i], rel_tol=1e-12, abs_tol=1e-10
            )
            or not np.isfinite(q).all()
            or (np.diff(q) < 0).any()
            or (lane.target != "T-CAL" and (q <= 0).any())
            or not math.isfinite(float(row["pit"]))
            or not 0 <= float(row["pit"]) <= 1
        ):
            raise ValueError("prediction identity, native units, support or quantile order changed")


def predictive_statistics(rows):
    """Row summaries and equal-event averages remain distinct; widths use native minutes."""
    if not rows:
        raise ValueError("nonempty predictive stratum required")
    y = np.array([r["observed_native_minutes"] for r in rows], float)
    quantiles = np.array([[r[f"q{v:02d}"] for v in [5, 25, 50, 75, 95]] for r in rows], float)
    events = np.array([r["event_id"] for r in rows])
    cover90 = (y >= quantiles[:, 0]) & (y <= quantiles[:, 4])
    cover50 = (y >= quantiles[:, 1]) & (y <= quantiles[:, 3])
    absolute = abs(y - quantiles[:, 2])

    def equal_event(values):
        return float(np.mean([values[events == e].mean() for e in sorted(set(events))]))

    return {
        "records": len(rows),
        "events": len(set(events)),
        "sequences": len({r["sequence"] for r in rows}),
        "record_coverage50": float(cover50.mean()),
        "record_coverage90": float(cover90.mean()),
        "equal_event_coverage50": equal_event(cover50),
        "equal_event_coverage90": equal_event(cover90),
        "median_width50_minutes": float(np.median(quantiles[:, 3] - quantiles[:, 1])),
        "median_width90_minutes": float(np.median(quantiles[:, 4] - quantiles[:, 0])),
        "median_absolute_error_minutes": float(np.median(absolute)),
        "record_mean_absolute_error_minutes": float(absolute.mean()),
        "equal_event_mean_absolute_error_minutes": equal_event(absolute),
        "record_mean_width50_minutes": float(np.mean(quantiles[:, 3] - quantiles[:, 1])),
        "record_mean_width90_minutes": float(np.mean(quantiles[:, 4] - quantiles[:, 0])),
        "equal_event_mean_width50_minutes": equal_event(quantiles[:, 3] - quantiles[:, 1]),
        "equal_event_mean_width90_minutes": equal_event(quantiles[:, 4] - quantiles[:, 0]),
        "coverage90_numerically_ambiguous_records": sum(
            r.get("coverage90_numerically_ambiguous") is True for r in rows
        ),
        "coverage90_numerical_ambiguity_not_assessed_records": sum(
            type(r.get("coverage90_numerically_ambiguous")) is not bool for r in rows
        ),
    }


def event_weighted_pit_curve(rows, *, grid=None, seed=25261108, replicates=2000):
    """Whole-sequence pairs bootstrap of event-weighted marginal PIT ECDFs.

    Bands are descriptive sampling summaries under heuristic cluster exchangeability.
    Overlapping CV training sets remain a limitation. No uniformity test or model
    acceptance rule follows from these bands. Resample sequence sums and counts
    together so events, rather than stations or sequence sizes, define the estimand.
    """
    grid = np.linspace(0, 1, 101) if grid is None else np.asarray(grid, dtype=float)
    if (
        not rows
        or type(replicates) is not int
        or not 100 <= replicates <= 10000
        or grid.ndim != 1
        or not len(grid)
        or not np.isfinite(grid).all()
        or (np.diff(grid) <= 0).any()
        or (grid < 0).any()
        or (grid > 1).any()
    ):
        raise ValueError("nonempty PITs, ordered probability grid and finite bootstrap required")
    events = sorted({r["event_id"] for r in rows})
    # Bootstrap and empirical ECDFs jump only here; the plotting grid alone
    # can miss their supremum between two close observed PIT values.
    evaluation_grid = np.unique(np.r_[grid, [0.0, 1.0], [float(r["pit"]) for r in rows]])
    display = np.searchsorted(evaluation_grid, grid)
    event_curves, sequence_by_event = [], []
    for event in events:
        selected = [r for r in rows if r["event_id"] == event]
        sequences = {r["sequence"] for r in selected}
        pits = np.array([r["pit"] for r in selected], dtype=float)
        if (
            len(sequences) != 1
            or not np.isfinite(pits).all()
            or (pits < 0).any()
            or (pits > 1).any()
        ):
            raise ValueError("one sequence per event and resolved probability PITs required")
        event_curves.append((pits[:, None] <= evaluation_grid).mean(axis=0))
        sequence_by_event.append(next(iter(sequences)))
    curves = np.array(event_curves)
    sequence_by_event = np.array(sequence_by_event)
    groups = sorted(set(sequence_by_event))
    empirical_full = curves.mean(axis=0)
    empirical = empirical_full[display]
    if len(groups) > 1:
        counts = np.array([sum(sequence_by_event == g) for g in groups])
        totals = np.array([curves[sequence_by_event == g].sum(axis=0) for g in groups])
        selected = np.random.default_rng(seed).integers(0, len(groups), (replicates, len(groups)))
        multiplicity = np.array([np.bincount(row, minlength=len(groups)) for row in selected])
        boot_full = (multiplicity @ totals) / (multiplicity @ counts)[:, None]
        low, high = np.quantile(boot_full[:, display], [0.025, 0.975], axis=0)
        radius = float(np.quantile(abs(boot_full - empirical_full).max(axis=1), 0.95))
    else:
        low = high = ["insufficient_sequences"] * len(grid)
        radius = "insufficient_sequences"
    return [
        {
            "pit_probability": float(x),
            "equal_event_cdf": float(empirical[j]),
            "bootstrap_pointwise_q025": low[j],
            "bootstrap_pointwise_q975": high[j],
            "bootstrap_supnorm_radius95": radius,
            "supnorm_scope": "all_observed_PIT_jumps_and_endpoints",
            "records": len(rows),
            "events": len(events),
            "sequences": len(groups),
            "bootstrap_replicates": replicates,
            "bootstrap_seed": seed,
            "band_scope": "descriptive_sequence_pairs_bootstrap_not_uniformity_test",
        }
        for j, x in enumerate(grid)
    ]
