"""Join frozen signal diagnostics to original sample identity and source flags."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from analysis.story.followups import FollowupInputs
from pipeline.normalize import IOC_QC_FLAGS


def signal_references(inputs: FollowupInputs) -> dict[str, list[dict[str, Any]]]:
    """Preserve failures and contradictions; never create a physical arrival pick."""
    profiles = {r["station_id"]: r for r in inputs.shared["profiles"]}
    stations = {s.station_id: s for s in inputs.atlas.stations}
    support: list[dict[str, Any]] = []
    for summary in inputs.shared["summaries"]:
        sid = summary["station_id"]
        station = stations[sid]
        support.append(
            dict(
                station_id=sid,
                name=station.name,
                field=summary["field"],
                units=station.units,
                vertical_datum=station.vertical_reference,
                observation_support=summary["measurement_supported"],
                detected_settings=summary["detected_settings"],
                total_settings=summary["settings"],
                control_crossings=summary["control_crossings"],
                control_unevaluable=summary["control_ineligible"],
                mechanical_screen_pass=summary["screen_pass"],
                external_validation=summary["external_validation"],
                physical_onset_status=summary["physical_arrival_status"],
                modeled_arrival_status=summary["modeled_arrival_utc"],
                source_qc_count=profiles[sid]["qc_flagged"],
            )
        )
    windows: list[dict[str, Any]] = []
    qc_rows: list[dict[str, Any]] = []
    origin = inputs.atlas.event.origin_time_utc
    for (sid, stamp), sample in sorted(inputs.metadata.items()):
        if sid not in ("21418", "9461380", "valp"):
            continue
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        elapsed = (moment - origin).total_seconds()
        # IOC stores flags as JSON; DART's source_extra is a numeric correction field.
        extra: dict[str, Any] = json.loads(sample["source_extra"]) if sid == "valp" else {}
        flags = {name: extra.get(name, "unknown") for name in IOC_QC_FLAGS}
        bad = any(value == "T" for value in flags.values())
        field = "residual" if sid == "21418" else "raw"
        row = dict(
            **sample,
            **flags,
            field=field,
            value=sample[f"{field}_value"] or "unknown",
            elapsed_seconds=elapsed,
            qc_flagged=bad,
            diagnostic_exclusion_reason=(
                "source_QC_flagged_retained_for_inspection"
                if bad
                else "not_excluded_not_a_validated_onset"
            ),
        )
        # Blank source values stay explicit; the original serialized flags also survive.
        for key in ("raw_value", "fitted_value", "residual_value"):
            row[key] = row[key] or "unknown"
        if sid == "valp" and bad:
            qc_rows.append(row)
        if (
            sid == "valp"
            or sid == "21418"
            and -300 <= elapsed < 3600
            or sid == "9461380"
            and -18000 <= elapsed < 0
        ):
            windows.append(row)
    cached = "data/raw/nctr/honshu20110311.html"
    source = next(r for r in inputs.fingerprints if r["path"] == cached)
    references = [
        dict(
            source_id="nctr-honshu20110311",
            publisher="NOAA PMEL NCTR",
            url="https://nctr.pmel.noaa.gov/honshu20110311/",
            cached_path=cached,
            sha256=source["sha256"],
            precision="approximate",
            reported_elapsed_minutes_approx=25,
            physical_pick_utc="unknown",
            claim="Publisher describes first tsunami recording at DART 21418 "
            "at approximately 25 minutes.",
            interpretation="Early threshold signal remains unclassified; "
            "not a validated tsunami arrival.",
            source_verification_date="2026-10-05",
            verification_kind="accepted cached source; no new live lookup",
        )
    ]
    if len(qc_rows) != profiles["valp"]["qc_flagged"]:
        raise ValueError("sample-level QC flags differ from frozen audit count")
    return {
        "signal-support": support,
        "setting-reference": inputs.shared["picks"],
        "signal-windows": windows,
        "source-qc-reference": qc_rows,
        "source-references": references,
    }
