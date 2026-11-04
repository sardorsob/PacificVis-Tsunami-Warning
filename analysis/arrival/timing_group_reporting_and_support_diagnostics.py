"""Group, reporting, availability and influence diagnostics; no fitted model."""

from __future__ import annotations

import math
import warnings
from collections import Counter
from typing import Any

import numpy as np

from analysis.arrival.observations import design_support
from analysis.arrival.timing_data_and_descriptive_statistics import (
    Record,
    bootstrap_median,
    components,
    grouped,
    number,
    summarize,
    support,
)


def _polish(matrix: Any) -> tuple[Any, Any, Any]:
    """Vectorized median polish; missing cells never enter the observed residuals."""
    a = np.array(matrix, dtype=float, copy=True)
    event = np.zeros(a.shape[0])
    site = np.zeros(a.shape[1])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # empty bootstrap columns remain missing
        for _ in range(100):
            old = a.copy()
            e = np.nan_to_num(np.nanmedian(a, axis=1))
            a -= e[:, None]
            event += e
            event -= np.median(event)
            s = np.nan_to_num(np.nanmedian(a, axis=0))
            a -= s[None, :]
            site += s
            site -= np.median(site)
            if np.nanmax(np.abs(a - old), initial=0) < 1e-10:
                break
    return event, site, a


def _matrix(rows: list[Record], site_key: str) -> tuple[Any, list[str], list[str]]:
    events = sorted({str(r["event_id"]) for r in rows})
    sites = sorted({str(r[site_key]) for r in rows})
    matrix = np.full((len(events), len(sites)), np.nan)
    em = {v: i for i, v in enumerate(events)}
    sm = {v: i for i, v in enumerate(sites)}
    for row in rows:
        i, j = em[row["event_id"]], sm[row[site_key]]
        if math.isnan(matrix[i, j]):
            matrix[i, j] = summarize(
                [
                    r["r0"]
                    for r in rows
                    if r["event_id"] == row["event_id"] and r[site_key] == row[site_key]
                ]
            )["median"]
    return matrix, events, sites


def group_profile(
    rows: list[Record], site_key: str, repeats: int = 500
) -> tuple[Record, list[Record]]:
    own = [r for r in rows if math.isfinite(r["r0"])]
    comps = components(own, site_key) if own else []
    effects: list[Record] = []
    profiles: list[Record] = []
    for ci, comp in enumerate(comps):
        matrix, events, sites = _matrix(comp, site_key)
        ev, st, residual = _polish(matrix)
        for kind, ids, values in [("event", events, ev), ("site", sites, st)]:
            effects.extend(
                {
                    "component": ci,
                    "component_relative": True,
                    "kind": kind,
                    "id": key,
                    "effect": float(v),
                    "site_key": site_key,
                }
                for key, v in zip(ids, values, strict=True)
            )
        emad = summarize([float(v) for v in ev])["mad"]
        smad = summarize([float(v) for v in st])["mad"]
        rmad = summarize(residual[np.isfinite(residual)].tolist())["mad"]
        ratios: list[float] = []
        if ci == 0 and len(events) >= 2:
            rng = np.random.default_rng(20261103)
            for _ in range(repeats):
                bm = matrix[rng.integers(0, len(events), len(events)), :]
                bm = bm[:, np.isfinite(bm).any(axis=0)]
                _, bs, br = _polish(bm)
                den = summarize(br[np.isfinite(br)].tolist())["mad"]
                if den > 1e-10:
                    ratios.append(summarize(bs.tolist())["mad"] / den)
        profiles.append(
            {
                "component": ci,
                "rows": len(comp),
                "events": len(events),
                "sites": len(sites),
                "cells": int(np.isfinite(matrix).sum()),
                "event_mad": emad,
                "site_mad": smad,
                "residual_mad": rmad,
                "site_residual_ratio": smad / rmad if rmad > 1e-10 else math.nan,
                "event_residual_ratio": emad / rmad if rmad > 1e-10 else math.nan,
                "site_ratio_low": float(np.quantile(ratios, 0.025)) if ratios else math.nan,
                "site_ratio_high": float(np.quantile(ratios, 0.975)) if ratios else math.nan,
                "bootstrap_valid": len(ratios),
                "residual_degrees": int(np.isfinite(matrix).sum()) - len(events) - len(sites) + 1,
            }
        )
    return {
        "components": len(comps),
        "raw_rows": len(rows),
        "largest_component_rows": len(comps[0]) if comps else 0,
        "profiles": profiles,
    }, effects


def paired_differences(
    a: list[Record], b: list[Record], site_key: str = "physical_site_id"
) -> list[Record]:
    """Shared reviewed geographic IDs permit comparisons, never independence claims."""
    ka = {(r["event_id"], r[site_key]) for r in a}
    kb = {(r["event_id"], r[site_key]) for r in b}
    out: list[Record] = []
    for event, site in sorted(ka & kb):
        aa = [r["target_minutes"] for r in a if (r["event_id"], r[site_key]) == (event, site)]
        bb = [r["target_minutes"] for r in b if (r["event_id"], r[site_key]) == (event, site)]
        diff = summarize(aa)["median"] - summarize(bb)["median"]
        out.append(
            {
                "event_id": event,
                "physical_site_id": site,
                "difference_minutes": diff,
                "ntwc_rows": len(aa),
                "ncei_rows": len(bb),
                "lineage_state": "unresolved",
                "independence_established": False,
                "link_basis": "shared reviewed geographic ID"
                if site_key == "physical_site_id"
                else "posthoc name and bounded 2km colocation; unapproved identity",
                "comparison_site_key": site_key,
                "ntwc_record_ids": [
                    r.get("record_id", "unknown")
                    for r in a
                    if (r["event_id"], r[site_key]) == (event, site)
                ],
                "ncei_record_ids": [
                    r.get("record_id", "unknown")
                    for r in b
                    if (r["event_id"], r[site_key]) == (event, site)
                ],
                "category": "0"
                if abs(diff) < 1e-9
                else "<1min"
                if abs(diff) < 1
                else "1to<5min"
                if abs(diff) < 5
                else ">=5min",
            }
        )
    return out


def availability_table(rows: list[Record], key: str) -> list[Record]:
    out: list[Record] = []
    for value in sorted({str(r[key]) for r in rows}):
        own = [r for r in rows if str(r[key]) == value]
        accepted = [r for r in own if r["structural_status"] == "accepted_source_row"]
        exact = sum(int(r["exact_observed"]) for r in accepted)
        out.append(
            {
                "group": value,
                "retained_rows": len(own),
                "accepted_rows": len(accepted),
                "structural_rows": len(own) - len(accepted),
                "exact_observed": exact,
                "availability": exact / len(accepted) if accepted else math.nan,
                "events": len({r.get("event_id", "unknown") for r in accepted}),
            }
        )
    return out


def within_event(rows: list[Record], key: str, value: str) -> list[Record]:
    out: list[Record] = []
    for event in sorted({r["event_id"] for r in rows}):
        own = [r for r in rows if r["event_id"] == event]
        groups = grouped(own, key, value)
        if len(groups) < 2:
            continue
        # All contrasts against lexicographically first source category, fixed before confirmation.
        reference = groups[0]
        for other in groups[1:]:
            out.append(
                {
                    "event_id": event,
                    "reference": reference["group"],
                    "other": other["group"],
                    "key": key,
                    "n_reference": reference["n"],
                    "n_other": other["n"],
                    "difference": other["median"] - reference["median"],
                }
            )
    return out


def source_contrast_profile(rows: list[Record]) -> dict[str, float]:
    """C5 descriptive group contrasts; no causal source-offset interpretation."""
    out: dict[str, float] = {}
    for key in [
        "header_family",
        "era",
        "precision_seconds",
        "identity_tier",
        "time_evidence_tier",
        "measurement_family",
        "identity_scope",
        "qualifier",
    ]:
        values = grouped(rows, key, "r0")
        if len(values) < 2:
            continue
        reference = values[0]
        for other in values[1:]:
            out[key + "|" + reference["group"] + "|" + other["group"]] = (
                other["median"] - reference["median"]
            )
    return out


def diagnostics(
    frames: dict[str, list[Record]], availability: list[Record], module: str
) -> tuple[Record, dict[str, list[Record]]]:
    results: Record = {}
    tables: dict[str, list[Record]] = {}
    if module == "C6":
        accepted = [r for r in availability if r["structural_status"] == "accepted_source_row"]
        for key in ["era", "header_family", "provider", "distance_band", "peak_present"]:
            tables["availability-" + key] = availability_table(availability, key)
        tables["availability-by-event"] = availability_table(availability, "event_id")
        tables["availability-records"] = availability
        tables["within-event-peak-presence"] = within_event(
            accepted, "peak_present", "exact_observed"
        )
        peak_size: list[Record] = []
        for scope in sorted({r["peak_scope"] for r in accepted}):
            own = [
                r for r in accepted if r["peak_scope"] == scope and math.isfinite(r["peak_native"])
            ]
            event = own[0]["event_id"] if own else "unknown"
            yes = [r["peak_native"] for r in own if r["exact_observed"]]
            no = [r["peak_native"] for r in own if not r["exact_observed"]]
            if yes and no:
                peak_size.append(
                    {
                        "event_id": event,
                        "exact_observed_n": len(yes),
                        "not_exact_observed_n": len(no),
                        "native_median_difference": summarize(yes)["median"]
                        - summarize(no)["median"],
                        "unit_scope": scope + "; native units unknown; no pooled size",
                    }
                )
        tables["within-event-peak-size"] = peak_size
        results = {
            "retained": len(availability),
            "accepted": len(accepted),
            "structural": len(availability) - len(accepted),
            "exact_observed": sum(r["exact_observed"] for r in accepted),
            "absent_observed": sum(r["observed_absent"] == "True" for r in accepted),
            "absent_observed_with_peak": sum(
                r["observed_absent"] == "True" and r["peak_present"] == "True" for r in accepted
            ),
            "tables": {k: v for k, v in tables.items() if k != "availability-records"},
            "opportunities": "Heterogeneous opportunities; not an operating-station census",
            "mechanism": "MCAR/MAR/MNAR unidentified; contrasts descriptive only",
        }
        return results, tables
    if module == "C5":
        linked = paired_differences(frames["T-OBS"], frames["NCEI-native-duration"])
        tables["linked-geographic-comparisons"] = linked
        sensitivity = paired_differences(
            frames["T-OBS"], frames["NCEI-native-duration"], "site_2km"
        )
        tables["posthoc-P1-colocation-comparisons"] = sensitivity
        low, high = bootstrap_median(sensitivity, "difference_minutes", 500, 20261103)
        results["posthoc_P1"] = summarize([r["difference_minutes"] for r in sensitivity]) | {
            "ci_low": low,
            "ci_high": high,
            "identity_approved": False,
            "interpretation": "posthoc geography only; no onset equivalence or independence",
        }
        lo, hi = bootstrap_median(linked, "difference_minutes", 500, 20261103)
        results["linked"] = summarize([r["difference_minutes"] for r in linked]) | {
            "ci_low": lo,
            "ci_high": hi,
            "categories": dict(Counter(r["category"] for r in linked)),
            "interpretation": "geographic comparisons only; lineage unresolved",
        }
    for target in (
        ["T-OBS", "NCEI-native-duration", "T-CAL"]
        if module == "C9"
        else ["T-OBS", "NCEI-native-duration"]
    ):
        rows = frames[target]
        result: Record = {}
        if module == "C4":
            for key in ["physical_site_id", "site_1km", "site_2km", "site_5km"]:
                summary, effects = group_profile(
                    rows, key, 500 if key in ["physical_site_id", "site_2km"] else 0
                )
                summary["largest_event_effects"] = [
                    r for r in effects if r["component"] == 0 and r["kind"] == "event"
                ]
                result[key] = summary
                tables[target + "-" + key + "-effects"] = effects
        elif module == "C5":
            for key in [
                "header_family",
                "era",
                "provider",
                "precision_seconds",
                "identity_tier",
                "time_evidence_tier",
                "identity_scope",
                "measurement_family",
                "qualifier",
            ]:
                result[key] = grouped(rows, key, "r0")
                tables[target + "-" + key] = result[key]
                contrasts = within_event(rows, key, "target_minutes")
                tables[target + "-within-" + key] = contrasts
                result["within-" + key] = {
                    "contrasts": len(contrasts),
                    **summarize([r["difference"] for r in contrasts]),
                }
        elif module == "C7":
            base_summary = summarize([r["r0"] for r in rows])
            base = base_summary["median"]
            base_near = (
                summarize([r["r0"] for r in rows if r["distance_km"] < 500])["median"]
                - summarize([r["r0"] for r in rows if r["distance_km"] >= 500])["median"]
            )
            base_gp, _ = group_profile(rows, "physical_site_id", 0)
            base_profile: Record = base_gp["profiles"][0] if base_gp["profiles"] else {}
            base_contrasts = source_contrast_profile(rows)
            loo: list[Record] = []
            for event in sorted({r["event_id"] for r in rows}):
                own = [r for r in rows if r["event_id"] != event]
                value = summarize([r["r0"] for r in own])["median"]
                gp, _ = group_profile(own, "physical_site_id", 0)
                profile: Record = gp["profiles"][0] if gp["profiles"] else {}
                effect_changes = [
                    abs(number(profile.get(k)) - number(base_profile.get(k)))
                    / abs(number(base_profile.get(k)))
                    for k in ["site_mad", "event_mad"]
                    if abs(number(base_profile.get(k))) > 1e-10
                ]
                largest_effect_change = max(effect_changes, default=math.nan)
                contrasts = source_contrast_profile(own)
                source_changes = [
                    abs(contrasts[key] - baseline) / abs(baseline)
                    for key, baseline in base_contrasts.items()
                    if key in contrasts and abs(baseline) > 1e-10
                ]
                own_near_far = (
                    summarize([r["r0"] for r in own if r["distance_km"] < 500])["median"]
                    - summarize([r["r0"] for r in own if r["distance_km"] >= 500])["median"]
                )
                loo.append(
                    {
                        "event_id": event,
                        "remaining_rows": len(own),
                        "median_r0": value,
                        "absolute_change": value - base,
                        "maximum_effect_mad_relative_change": largest_effect_change,
                        "source_contrast_max_relative_change": max(
                            source_changes, default=math.nan
                        ),
                        "unavailable_source_contrasts": len(
                            base_contrasts.keys() - contrasts.keys()
                        ),
                        "site_mad": profile.get("site_mad", math.nan),
                        "event_mad": profile.get("event_mad", math.nan),
                        "mad_r0": summarize([r["r0"] for r in own])["mad"],
                        "r0_mad_relative_change": abs(
                            summarize([r["r0"] for r in own])["mad"] - base_summary["mad"]
                        )
                        / base_summary["mad"]
                        if base_summary["mad"] > 1e-10
                        else math.nan,
                        "near_far_relative_change": abs(
                            (
                                summarize([r["r0"] for r in own if r["distance_km"] < 500])[
                                    "median"
                                ]
                                - summarize([r["r0"] for r in own if r["distance_km"] >= 500])[
                                    "median"
                                ]
                            )
                            - base_near
                        )
                        / abs(base_near)
                        if abs(base_near) > 1e-10
                        else math.nan,
                        "near_far_difference": summarize(
                            [r["r0"] for r in own if r["distance_km"] < 500]
                        )["median"]
                        - summarize([r["r0"] for r in own if r["distance_km"] >= 500])["median"],
                        "baseline_near_far": base_near,
                        "relative_change": abs(value - base) / abs(base)
                        if abs(base) > 1e-12
                        else math.nan,
                        "sign_flip": bool(base * value < 0),
                        "any_summary_sign_flip": bool(
                            base * value < 0
                            or base_near * own_near_far < 0
                            or any(
                                baseline * contrasts.get(key, math.nan) < 0
                                for key, baseline in base_contrasts.items()
                            )
                        ),
                    }
                )
            tables[target + "-leave-one-event-out"] = loo
            result = support(rows) | {"baseline_r0": base, "loo": loo}
        elif module == "C9":
            baseline = design_support(
                [
                    {"event_id": r["event_id"], "physical_site_id": r["physical_site_id"]}
                    for r in rows
                ]
            )
            result = support(rows) | {"existing_design_support": baseline}
            event_holdout: list[Record] = []
            for event in sorted({r["event_id"] for r in rows}):
                test = [r for r in rows if r["event_id"] == event]
                train = [r for r in rows if r["event_id"] != event]
                seen = {r["physical_site_id"] for r in train}
                event_holdout.append(
                    {
                        "event_id": event,
                        "test_rows": len(test),
                        "test_rows_at_seen_sites": sum(r["physical_site_id"] in seen for r in test),
                        "train_components": support(train)["components"],
                    }
                )
            tables[target + "-LOEO-support"] = event_holdout
            tables[target + "-LOSO-support"] = [
                {
                    "physical_site_id": s,
                    "test_rows": sum(r["physical_site_id"] == s for r in rows),
                    "train_additive_rank": support([r for r in rows if r["physical_site_id"] != s])[
                        "additive_design_rank"
                    ],
                    "train_events_for_site_events": len(
                        {r["event_id"] for r in rows if r["physical_site_id"] == s}
                        & {r["event_id"] for r in rows if r["physical_site_id"] != s}
                    ),
                }
                for s in sorted({r["physical_site_id"] for r in rows})
            ]
        results[target] = result
    return results, tables
