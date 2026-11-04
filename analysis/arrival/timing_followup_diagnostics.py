"""Pre-registered descriptive branch checks; thresholds are not significance tests."""

from __future__ import annotations

import math
from typing import Any

from analysis.arrival.timing_data_and_descriptive_statistics import (
    Record,
    bootstrap_median,
    grouped,
    number,
    rank_correlation,
    summarize,
)
from analysis.arrival.timing_group_reporting_and_support_diagnostics import (
    paired_differences,
    within_event,
)


def branches(
    frames: dict[str, list[Record]], core: dict[str, Any], branch: str
) -> tuple[Record, dict[str, list[Record]]]:
    result: Record = {}
    tables: dict[str, list[Record]] = {}
    targets = (
        ["T-CAL"]
        if branch == "B10"
        else ["NTWC-reports"]
        if branch == "B7"
        else ["T-OBS", "NCEI-native-duration"]
    )
    for target in targets:
        rows = frames.get(target, frames["T-OBS"])
        scalar = math.nan
        triggered = False
        detail: Record = {}
        c3 = core.get("C3", {}).get(target, {})
        forced_route = core.get("_routes", {}).get(branch, {}).get(target)
        if branch in ["B1", "B9"]:
            scalar = number(c3["near"]["median"]) - number(c3["far"]["median"])
            choices: dict[str, float] = {"near_far": scalar}
            if branch == "B1":
                medians = [number(b["median"]) for b in c3["bins"] if b["finite_n"] >= 5]
                diffs = [b - a for a, b in zip(medians[:-1], medians[1:], strict=True)]
                monotone = bool(diffs) and (
                    all(v >= 0 for v in diffs) or all(v <= 0 for v in diffs)
                )
                choices["monotone_distance"] = medians[-1] - medians[0] if monotone else math.nan
            route = forced_route or next(
                (k for k, v in choices.items() if abs(v) > 0.1), "near_far"
            )
            scalar = choices.get(route, math.nan)
            detail["selected_route"] = route
            triggered = math.isfinite(scalar) and abs(scalar) > 0.1
            cutoff: list[Record] = []
            for minutes in [30, 60, 90]:
                low = summarize([r["r0"] for r in rows if r["reference_minutes"] < minutes])
                high = summarize([r["r0"] for r in rows if r["reference_minutes"] >= minutes])
                cutoff.append(
                    {
                        "cutoff_reference_minutes": minutes,
                        "near_n": low["finite_n"],
                        "far_n": high["finite_n"],
                        "difference": low["median"] - high["median"],
                    }
                )
            tables[target + "-cutoff-profile"] = cutoff
            detail["cutoffs"] = cutoff
            if branch == "B9":
                ratios = [
                    abs(r["origin_difference_seconds"]) / number(r["precision_seconds"])
                    for r in rows
                    if math.isfinite(r["origin_difference_seconds"])
                    and number(r["precision_seconds"]) > 0
                ]
                detail["origin_precision_ratios"] = summarize(ratios)
                detail["origin_route_status"] = (
                    "native-source comparison only"
                    if ratios
                    else "original-report ancestry unidentifiable"
                )
                # Absent original-report ancestry cannot be inferred from other products.
                if (
                    forced_route == "origin_precision"
                    or not forced_route
                    and not triggered
                    and ratios
                    and max(ratios) > 0.5
                ):
                    scalar = max(ratios, default=math.nan)
                    triggered = scalar > 0.5
                    detail["selected_route"] = "origin_precision"
            if branch == "B1":
                comparisons = [
                    {
                        "record_id": r["record_id"],
                        "event_id": r["event_id"],
                        "geodesic_km": r["distance_km"],
                        "native_distance": r["native_distance_km"],
                        "numeric_ratio": r["native_distance_km"] / r["distance_km"]
                        if r["distance_km"] > 0
                        else math.nan,
                        "native_units": "unverified in frozen schema; numeric diagnostic only",
                    }
                    for r in rows
                    if math.isfinite(r["native_distance_km"])
                ]
                tables[target + "-native-distance-comparison"] = comparisons
                detail["native_numeric_ratio"] = summarize(
                    [number(r["numeric_ratio"]) for r in comparisons]
                )
                detail["land_shadow"] = (
                    "unavailable: no approved coastline/bathymetric path input; no acquisition"
                )
        elif branch == "B2":
            s = summarize([r["r0"] for r in rows])
            mad = s["mad"]
            cases: list[Record] = []
            for r in rows:
                z = 0.67448975 * (r["r0"] - s["median"]) / mad if mad > 0 else math.nan
                if abs(z) > 3.5 or abs(r["r0"]) > math.log(2):
                    cases.append(
                        r
                        | {
                            "robust_z": z,
                            "source_review": "documented_definition_candidate"
                            if r["definition_conflict_candidate"] == "True"
                            else "origin_rounding_sensitive"
                            if r["target_minutes"] < 1
                            else "original_duration_retained; specific_cause_unresolved",
                        }
                    )
            scalar = len(cases) / len(rows) if rows else math.nan
            triggered = scalar > 0.02 or any(abs(r["r0"]) > math.log(2) for r in rows)
            tables[target + "-tail-source-cases"] = cases
            detail = {
                "flagged": len(cases),
                "retained_all": True,
                "classifications": grouped(cases, "source_review", "r0"),
            }
        elif branch in ["B3", "B4"]:
            p = core["C4"][target]["physical_site_id"]["profiles"]
            largest: Record = p[0] if p else {}
            ratio = "site_residual_ratio" if branch == "B3" else "event_residual_ratio"
            scalar = number(largest.get(ratio))
            if branch == "B3":
                other = core["C4"][target]["site_2km"]["profiles"]
                stable = (
                    bool(other)
                    and number(other[0]["site_ratio_low"]) >= 0.5
                    and number(largest.get("site_ratio_low")) >= 0.5
                    and number(largest.get("bootstrap_valid")) == 500
                    and number(other[0]["bootstrap_valid"]) == 500
                )
                triggered = math.isfinite(scalar) and scalar >= 0.5
                detail = {
                    "two_key_bootstrap_stability": stable,
                    "component_support": p,
                    "identifiability": "component-relative descriptive effects; no posterior claim",
                }
                tables[target + "-site-type-contrasts"] = grouped(rows, "measurement_family", "r0")
            else:
                triggered = math.isfinite(scalar) and scalar > 1
                effect_map = {
                    r["id"]: r["effect"]
                    for r in core["C4"][target]["physical_site_id"]["largest_event_effects"]
                }
                erows = [
                    {
                        "event_id": e,
                        "r0": effect_map.get(e, math.nan),
                        "magnitude": next(r["magnitude"] for r in rows if r["event_id"] == e),
                        "depth_km": next(r["depth_km"] for r in rows if r["event_id"] == e),
                    }
                    for e in sorted({r["event_id"] for r in rows})
                ]
                detail = {
                    "rank_correlations": {
                        k: rank_correlation([r[k] for r in erows], [r["r0"] for r in erows])
                        for k in ["magnitude", "depth_km"]
                    },
                    "categorical_covariates": "mechanism/region are categories, not ordinal ranks",
                }
                tables[target + "-event-covariates"] = erows
        elif branch == "B5":
            spreads: list[Record] = []
            for a, b in [(0, 500), (500, 2000), (2000, 5000), (5000, 10000), (10000, 20050)]:
                own = [r["r0"] for r in rows if a <= r["distance_km"] < b]
                spreads.append({"group": f"{a}-{b}km", **summarize(own)})
            usable = [r["mad"] for r in spreads if r["finite_n"] >= 5 and r["mad"] > 0]
            scalar = max(usable) / min(usable) if len(usable) > 1 else math.nan
            prec = grouped(rows, "precision_seconds", "r0")
            values = [number(r["mad"]) for r in prec if r["finite_n"] >= 5 and number(r["mad"]) > 0]
            precision_ratio = max(values) / min(values) if len(values) > 1 else math.nan
            choices = {"distance": scalar, "precision": precision_ratio}
            route = forced_route or next((k for k, v in choices.items() if v > 1.5), "distance")
            scalar = choices.get(route, math.nan)
            triggered = scalar > 1.5
            tables[target + "-distance-spread"] = spreads
            tables[target + "-precision-spread"] = grouped(rows, "precision_seconds", "r0")
            detail = {
                "selected_route": route,
                "distance_spreads": spreads,
                "measurement_family_spreads": grouped(rows, "measurement_family", "r0"),
            }
        elif branch in ["B6", "B11"]:
            linked = paired_differences(frames["T-OBS"], frames["NCEI-native-duration"])
            scalar = summarize([r["difference_minutes"] for r in linked])["median"]
            ci = core["C5"]["linked"]
            options: dict[str, Record] = {
                "direct_geographic": {
                    "median": scalar,
                    "ci_low": number(ci["ci_low"]),
                    "ci_high": number(ci["ci_high"]),
                }
            }
            all_contrasts: list[Record] = []
            if branch == "B6":
                for key in [
                    "header_family",
                    "precision_seconds",
                    "identity_tier",
                    "time_evidence_tier",
                    "measurement_family",
                ]:
                    contrasts = within_event(rows, key, "target_minutes")
                    for reference, other in sorted(
                        {(r["reference"], r["other"]) for r in contrasts}
                    ):
                        own = [
                            r
                            for r in contrasts
                            if r["reference"] == reference and r["other"] == other
                        ]
                        lo, hi = bootstrap_median(own, "difference", 500, 20261103)
                        comparison = key + "|" + reference + "|" + other
                        all_contrasts.extend(r | {"comparison_id": comparison} for r in own)
                        options[comparison] = {
                            "median": summarize([r["difference"] for r in own])["median"],
                            "ci_low": lo,
                            "ci_high": hi,
                        }

            def passes(v: Record) -> bool:
                return abs(v["median"]) > 1 and (v["ci_low"] > 0 or v["ci_high"] < 0)

            route = forced_route or next(
                (k for k, v in options.items() if passes(v)), "direct_geographic"
            )
            selected = options.get(
                route, {"median": math.nan, "ci_low": math.nan, "ci_high": math.nan}
            )
            scalar = selected["median"]
            triggered = (
                passes(selected) if branch == "B6" else math.isfinite(scalar) and abs(scalar) > 1
            )
            tables[target + "-linked-definition-review"] = linked
            tables[target + "-within-event-source-contrasts"] = all_contrasts
            detail = {
                "selected_route": route,
                "selected_contrast": selected,
                "comparison_rows": len(linked),
                "lineage": "unresolved; cross-source latent arrival not identified",
                "caution": (
                    "Unmatched duration contrasts mix distance and definition; "
                    "not causal source offsets"
                ),
            }
        elif branch == "B7":
            tab = core["C6"]["tables"]
            choices = {}
            for key in ["era", "header_family"]:
                values = [
                    number(r["availability"])
                    for r in tab["availability-" + key]
                    if r["accepted_rows"] >= 5
                ]
                choices[key] = max(values) - min(values) if len(values) > 1 else math.nan
            peak = any(
                number(r["native_median_difference"]) != 0 for r in tab["within-event-peak-size"]
            )
            choices["peak_size"] = 1.0 if peak else 0.0
            route = forced_route or next((k for k, v in choices.items() if v > 0.15), "era")
            scalar = choices.get(route, math.nan)
            triggered = scalar > 0.15
            detail = {
                "selected_route": route,
                "peak_size_contrast_present": peak,
                "availability_era": tab["availability-era"],
                "within_event": tab["within-event-peak-presence"],
                "scope": "NTWC exact-UTC availability only; NCEI availability not measured here",
                "mechanism": "not identified; calendar/format/era confounding",
            }
            tables[target + "-availability-era"] = tab["availability-era"]
        elif branch == "B8":
            loo = core["C7"][target]["loo"]
            scalar = max([number(r["relative_change"]) for r in loo], default=math.nan)
            effect_changes = [number(r.get("maximum_effect_mad_relative_change")) for r in loo]
            scale_changes = [
                number(r.get(k))
                for r in loo
                for k in [
                    "r0_mad_relative_change",
                    "near_far_relative_change",
                    "source_contrast_max_relative_change",
                ]
            ]
            finite = [v for v in [scalar] + effect_changes + scale_changes if math.isfinite(v)]
            scalar = max(finite, default=math.nan)
            triggered = scalar > 0.3 or any(
                r.get("any_summary_sign_flip", r["sign_flip"]) for r in loo
            )
            tables[target + "-full-influence"] = loo
            detail = {
                "sign_flip_events": [
                    r["event_id"] for r in loo if r.get("any_summary_sign_flip", r["sign_flip"])
                ]
            }
        elif branch == "B10":
            cal = frames["T-CAL"]
            trends: list[Record] = []
            for e in sorted({r["event_id"] for r in cal}):
                own = [r for r in cal if r["event_id"] == e]
                trends.append(
                    {
                        "event_id": e,
                        "n": len(own),
                        "rho": rank_correlation(
                            [r["distance_km"] for r in own], [r["target_minutes"] for r in own]
                        ),
                    }
                )
            scalar = summarize([r["rho"] for r in trends])["median"]
            triggered = abs(scalar) > 0.3
            tables["T-CAL-within-event-distance"] = trends
            detail = {
                "within_event_trends": trends,
                "era": "constant within event; separate era effect not identifiable",
            }
        else:
            raise ValueError(branch)
        result[target] = {
            "branch": branch,
            "triggered": bool(triggered),
            "scalar": scalar,
            "detail": detail,
            "checks_maximum": 2,
            "status": "exploratory_screen" if math.isfinite(scalar) else "not_identifiable",
        }
    return result, tables
