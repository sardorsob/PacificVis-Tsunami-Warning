"""Descriptive paper EDA: frozen metadata split and target-specific diagnostics."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import numpy as np
from pyproj import Geod

from analysis.arrival.evidence import Row

Record = dict[str, Any]
FORCED = ("official20110311054624120_30", "official20100227063411530_30")
DISTANCE_BINS = [0.0, 500.0, 2000.0, 5000.0, 10000.0, 20050.0]
VREF = math.sqrt(9.80665 * 4000.0) / 1000.0  # km/s, fixed, never fitted


def number(value: Any) -> float:
    """Keep missing/non-numeric values as NaN rather than zeros."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def unique(rows: list[Row], key: str) -> dict[str, Row]:
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate {key}")
    return result


def draw_split(
    metadata: list[Row], seed: int, *, forced: tuple[str, ...] = FORCED
) -> dict[str, list[str]]:
    """Largest-remainder stratification with forced exploration; metadata only."""
    unique(metadata, "event_id")
    groups: dict[str, list[str]] = defaultdict(list)
    for row in metadata:
        groups[row["region"] + "/" + row["era"]].append(row["event_id"])
    target = round(len(metadata) / 3)
    quota = {k: min(len([e for e in v if e not in forced]), len(v) // 3) for k, v in groups.items()}
    rng = np.random.default_rng(seed)
    order = {k: float(rng.random()) for k in sorted(groups)}
    while sum(quota.values()) < target:
        candidates = [k for k in groups if quota[k] < sum(e not in forced for e in groups[k])]
        if not candidates:
            raise ValueError("forced exploration prevents confirmation allocation")
        best = max(candidates, key=lambda k: (len(groups[k]) / 3 - quota[k], order[k]))
        quota[best] += 1
    confirmation: list[str] = []
    for key in sorted(groups):
        eligible = sorted(e for e in groups[key] if e not in forced)
        confirmation.extend(str(e) for e in rng.permutation(eligible)[: quota[key]])
    all_ids = {r["event_id"] for r in metadata}
    return {
        "exploration": sorted(all_ids - set(confirmation)),
        "confirmation": sorted(confirmation),
    }


def distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """WGS84 diagnostic geodesic; unknown source datum is not promoted."""
    if not all(math.isfinite(v) for v in [lon1, lat1, lon2, lat2]):
        return math.nan
    if max(abs(lat1), abs(lat2)) > 90 or max(abs(lon1), abs(lon2)) > 180:
        raise ValueError("invalid geographic coordinates")
    return float(Geod(ellps="WGS84").inv(lon1, lat1, lon2, lat2)[2]) / 1000


def frame_targets(
    rows: list[Row], sites: list[Row], metadata: list[Row], tiers: list[Row], target: str
) -> list[Record]:
    """One-to-one joins; derive each target only from its approved native value."""
    sm, em = unique(sites, "physical_site_id"), unique(metadata, "event_id")
    tm = unique(tiers, "report_id") if tiers else {}
    unique(rows, "source_record_id")
    out: list[Record] = []
    for row in rows:
        event = em[row["event_id"]]
        site = sm.get(row["physical_site_id"], {})
        tier = tm.get(row["source_record_id"], {})
        minutes = (
            number(row["estimated_minus_observed_seconds"]) / 60
            if target == "T-CAL"
            else number(row["duration_minutes"])
        )
        distance = distance_km(
            number(event.get("longitude")),
            number(event.get("latitude")),
            number(site.get("longitude")),
            number(site.get("latitude")),
        )
        ref_minutes = distance / VREF / 60
        r0 = (
            math.log(minutes / ref_minutes)
            if (target != "T-CAL" and minutes > 0 and ref_minutes > 0)
            else math.nan
        )
        second = math.nan
        if target == "T-OBS":
            try:
                second = float(
                    datetime.fromisoformat(
                        row.get("observed_utc", "unknown").replace("Z", "+00:00")
                    ).second
                )
            except ValueError:
                pass
        out.append(
            {
                "record_id": row["source_record_id"],
                "event_id": row["event_id"],
                "physical_site_id": row["physical_site_id"],
                "target": target,
                "target_minutes": minutes,
                "observed_clock_second": second,
                "distance_km": distance,
                "reference_minutes": ref_minutes,
                "r0": r0,
                "origin_difference_seconds": number(row.get("origin_difference_seconds")),
                "precision_seconds": row.get("precision_seconds", "unknown"),
                "identity_tier": tier.get("identity_tier", "unknown"),
                "time_evidence_tier": tier.get("time_evidence_tier", "unknown"),
                "identity_scope": tier.get("identity_scope", site.get("identity_scope", "unknown")),
                "measurement_family": row.get("measurement_family", "NTWC"),
                "entity_cluster_id": row.get("entity_cluster_id", "unknown"),
                "region": event.get("region", "unknown"),
                "era": event.get("era", "unknown"),
                "magnitude": number(event.get("magnitude")),
                "depth_km": number(event.get("depth")),
                "mechanism": event.get("mechanism", "unknown"),
                "site_latitude": number(site.get("latitude")),
                "site_longitude": number(site.get("longitude")),
                "coordinate_crs_native": site.get("coordinate_crs", "unknown"),
                "amplitude_native": row.get("peak_amplitude_native", "unknown"),
                "amplitude_units": row.get("amplitude_units", "unknown"),
                "qualifier": row.get("raw_qualifiers_json", "unknown"),
            }
        )
    return out


def summarize(values: list[float]) -> Record:
    """Unscaled MAD and quantiles; every nonfinite value remains accounted for."""
    x = np.array(values, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {
            "n": len(values),
            "finite_n": 0,
            "median": math.nan,
            "q10": math.nan,
            "q90": math.nan,
            "mad": math.nan,
        }
    med = float(np.median(x))
    return {
        "n": len(values),
        "finite_n": len(x),
        "median": med,
        "q10": float(np.quantile(x, 0.1)),
        "q90": float(np.quantile(x, 0.9)),
        "mad": float(np.median(np.abs(x - med))),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
    }


def bootstrap_median(rows: list[Record], key: str, repeats: int, seed: int) -> tuple[float, float]:
    """Resample events, keeping their complete row clusters together."""
    groups = {
        e: [number(r[key]) for r in rows if r["event_id"] == e]
        for e in sorted({r["event_id"] for r in rows})
    }
    if len(groups) < 2:
        return math.nan, math.nan
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    samples = [
        summarize([x for e in rng.choice(keys, len(keys), replace=True) for x in groups[str(e)]])[
            "median"
        ]
        for _ in range(repeats)
    ]
    finite = np.array([v for v in samples if math.isfinite(v)])
    return (
        (float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975)))
        if len(finite)
        else (math.nan, math.nan)
    )


def median_polish(values: Any) -> tuple[float, Any, Any, Any]:
    """Tukey median polish; sparse cells remain missing, components handled outside."""
    a = np.array(values, dtype=float, copy=True)
    overall = 0.0
    re = np.zeros(a.shape[0])
    ce = np.zeros(a.shape[1])
    for _ in range(100):
        old = a.copy()
        for i in range(a.shape[0]):
            v = a[i, np.isfinite(a[i])]
            effect = float(np.median(v)) if len(v) else 0.0
            a[i] -= effect
            re[i] += effect
        center = float(np.median(re))
        re -= center
        overall += center
        for j in range(a.shape[1]):
            v = a[np.isfinite(a[:, j]), j]
            effect = float(np.median(v)) if len(v) else 0.0
            a[:, j] -= effect
            ce[j] += effect
        center = float(np.median(ce))
        ce -= center
        overall += center
        if np.nanmax(np.abs(a - old), initial=0) < 1e-10:
            break
    return overall, re, ce, a


def rank_correlation(x: list[float], y: list[float]) -> float:
    """Spearman correlation with average ranks for ties, no p-values."""
    pairs = [(a, b) for a, b in zip(x, y, strict=True) if math.isfinite(a) and math.isfinite(b)]
    if len(pairs) < 3:
        return math.nan

    def ranks(a: Any) -> Any:
        values = [number(v) for v in a]
        return np.array(
            [sum(v < x for v in values) + (sum(v == x for v in values) - 1) / 2 for x in values],
            dtype=float,
        )

    a, b = np.array(pairs).T
    a, b = ranks(a), ranks(b)
    if np.std(a) == 0 or np.std(b) == 0:
        return math.nan
    return float(np.corrcoef(a, b)[0, 1])


def grouped(rows: list[Record], group: str, value: str) -> list[Record]:
    return [
        {"group": str(key), **summarize([number(r[value]) for r in rows if str(r[group]) == key])}
        for key in sorted({str(r[group]) for r in rows})
    ]


def components(rows: list[Record], site_key: str = "physical_site_id") -> list[list[Record]]:
    """Connected event/site subgraphs; never impose shared offsets across components."""
    remaining = list(rows)
    out: list[list[Record]] = []
    while remaining:
        events = {remaining[0]["event_id"]}
        sites = {remaining[0][site_key]}
        changed = True
        selected: list[Record] = []
        while changed:
            selected = [r for r in remaining if r["event_id"] in events or r[site_key] in sites]
            ne = {r["event_id"] for r in selected}
            ns = {r[site_key] for r in selected}
            changed = ne != events or ns != sites
            events, sites = ne, ns
        out.append(selected)
        remaining = [r for r in remaining if r["event_id"] not in events]
    return sorted(out, key=lambda c: (-len(c), str(c[0]["event_id"])))


def support(rows: list[Record], site_key: str = "physical_site_id") -> Record:
    ec = Counter(str(r["event_id"]) for r in rows)
    by_site = {
        s: {r["event_id"] for r in rows if r[site_key] == s} for s in {r[site_key] for r in rows}
    }
    comps = components(rows, site_key) if rows else []
    return {
        "rows": len(rows),
        "events": len(ec),
        "sites": len(by_site),
        "components": len(comps),
        "additive_design_rank": len(ec) + len(by_site) - len(comps),
        "inverse_simpson_events": len(rows) ** 2 / sum(v * v for v in ec.values()) if rows else 0,
        "top3_row_share": sum(sorted(ec.values(), reverse=True)[:3]) / len(rows) if rows else 0,
        **{
            f"sites_at_least_{n}_events": sum(len(v) >= n for v in by_site.values())
            for n in (2, 3, 5)
        },
    }


def load_frames(
    root: Any, frozen: Record, split_ids: list[str]
) -> tuple[dict[str, list[Record]], list[Record]]:
    """Assemble selected-development targets without evaluating the other half."""
    import json
    import re

    from analysis.arrival.evidence import read_rows
    from analysis.arrival.site_registry import bounded_clusters, label_key

    base = root / "data/processed/arrival-evidence/foundation-v1"
    metadata = read_rows(
        root / "artifacts/eda/arrival-timing/frozen-inputs/development-event-metadata.csv"
    )
    selected = set(split_ids)
    dev = set(frozen["events"])
    if not selected <= dev:
        raise ValueError("reserved or unknown event requested")
    sites = read_rows(base / "sites.csv.gz")
    reports: list[Row] = []
    for event in sorted(dev):
        reports.extend(
            read_rows(
                root / f"data/processed/arrival-corpus/foundation-v6/{event}/arrival_report.csv.gz"
            )
        )
    native = read_rows(root / "data/processed/ncei-arrivals/foundation-v1/observations.csv.gz")
    if any(r["event_id"] not in dev for r in reports) or any(
        r["development_event_id"] not in dev for r in native
    ):
        raise ValueError("non-development data in input")
    rm = unique(reports, "report_id")
    nm = unique(native, "source_record_id")
    availability = read_rows(
        root / "data/processed/arrival-evidence/source-process-v1/report_availability.csv.gz"
    )
    waveforms = read_rows(base / "waveform_coverage.csv.gz")
    provider = {
        s: sorted({r["provider"] for r in waveforms if r["physical_site_id"] == s})
        for s in {r["physical_site_id"] for r in waveforms}
    }
    labels = {k: r["source_label"] for k, r in rm.items()}
    labels.update({k: r["native_locationName"] for k, r in nm.items()})
    points = [
        {
            "id": r["physical_site_id"],
            "name_key": label_key(
                labels.get(r["coordinate_evidence_source_record_id"], r["physical_site_id"])
            ),
            "latitude": r["latitude"],
            "longitude": r["longitude"],
        }
        for r in sites
        if all(math.isfinite(number(r[k])) for k in ["latitude", "longitude"])
    ]
    keys = {n: bounded_clusters(points, n) for n in [1, 2, 5]}
    conflict_ids = {
        r["ncei_runup_id"]
        for r in read_rows(
            root / "data/processed/arrival-evidence/"
            "source-process-v1/ncei_definition_candidates.csv.gz"
        )
    }
    frames: dict[str, list[Record]] = {}
    for target in ["T-OBS", "NCEI-native-duration", "T-CAL"]:
        rows = read_rows(base / f"{target}.csv.gz")
        if any(r["event_id"] not in dev for r in rows):
            raise ValueError("non-development target")
        rows = [r for r in rows if r["event_id"] in selected]
        tier_path = root / (
            "artifacts/generated/ntwc-batch/data-completion-v1/design/"
            + ("t-cal.csv" if target == "T-CAL" else "t-obs.csv")
        )
        tiers = read_rows(tier_path) if target != "NCEI-native-duration" else []
        frame = frame_targets(rows, sites, metadata, tiers, target)
        for row in frame:
            rid = row["record_id"]
            source = rm.get(rid, {})
            n = nm.get(rid, {})
            row.update(
                header_family=source.get("header_family", "NCEI_native"),
                provider="unknown",
                site_inventory_providers=";".join(provider.get(row["physical_site_id"], []))
                or "unknown",
                native_distance_km=number(n.get("native_distFromSource")),
                native_period=number(n.get("native_period")),
                source_label=" ".join(labels.get(rid, "unknown").split()),
                definition_conflict_candidate=str(n.get("ncei_runup_id") in conflict_ids),
            )
            for radius, mapping in keys.items():
                row[f"site_{radius}km"] = mapping.get(
                    row["physical_site_id"], row["physical_site_id"]
                )
        frames[target] = frame
    am = unique(availability, "report_id")
    avail: list[Record] = []
    for rid, row in rm.items():
        if row["event_id"] not in selected:
            continue
        raw = json.loads(row["raw_row_json"])
        peak = raw.get("fields", {}).get("peak_amplitude", "unknown")
        peak_text = " ".join(peak.split())
        match = re.match(r"^[~<>?\s]*(-?\d+(?:\.\d+)?)", peak_text)
        a: Record = dict(am[rid])
        a["peak_scope"] = row["event_id"] + "/" + row["table_index"] + "/" + row["header_family"]
        a.update(
            peak_present=str(bool(match)),
            peak_native=number(match[1]) if match else math.nan,
            peak_units="source_table_native_unharmonized",
            header_family=row["header_family"],
            exact_observed=int(row["observed_state"] == "exact_reported_timestamp"),
            provider="unknown",
            distance_km=math.nan,
            era=next(m["era"] for m in metadata if m["event_id"] == row["event_id"]),
        )
        avail.append(a)
    # Availability has incomplete station matching: preserve unknown distance/provider.
    obs = unique(read_rows(base / "observations.csv.gz"), "source_record_id")
    sm = unique(sites, "physical_site_id")
    mm = unique(metadata, "event_id")
    for row in avail:
        site = obs.get(row["report_id"], {}).get("physical_site_id", "unknown")
        s = sm.get(site, {})
        e = mm[row["event_id"]]
        row["distance_km"] = distance_km(
            number(e["longitude"]),
            number(e["latitude"]),
            number(s.get("longitude")),
            number(s.get("latitude")),
        )
        row["distance_band"] = next(
            (
                f"{lo:g}–{hi:g}km"
                for lo, hi in zip(DISTANCE_BINS[:-1], DISTANCE_BINS[1:], strict=True)
                if lo <= row["distance_km"] < hi
            ),
            "unknown",
        )
        row["provider"] = "unknown"
        row["site_inventory_providers"] = ";".join(provider.get(site, [])) or "unknown"
    return frames, avail
