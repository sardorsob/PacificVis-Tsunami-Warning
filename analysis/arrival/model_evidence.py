"""Source-identity audit of the six exploration records on unresolved repeated edges."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analysis.arrival.evidence import checked_path, sha256
from analysis.arrival.model_data import load_lanes

RAW = "data/raw/arrival-recovery/"
SOURCES = {
    "recovery-ncei-9ffb03a9721a6bc9": (
        "ncei-development-v1",
        "ff36a5d3b7dfc1609fd7fd7a60be2459333031b16e83abfef8062c2c246e3eed",
    ),
    "recovery-ncei-c7a352e5a9628185": (
        "ncei-development-v1",
        "3ba40b6c217c3e448a5bba4e031159fae52999815c734999151bfa08092f6467",
    ),
    "recovery-ncei-564962a202e9e2be": (
        "ncei-development-v1",
        "76ba628b6705ba3ae35d6173deaab0348990b6ecbaae681a5966069fb227a952",
    ),
    "recovery-ncei-66bfa3cd99cb7161": (
        "ncei-development-runups-v1",
        "5246aa7026399d739ce349e9113594fbfc75097157eaa14f928761f046ec07aa",
    ),
}


def audit_repeated_edges(root: Path) -> dict[str, Any]:
    """Match the declared source positions without deciding which reported time is true."""
    lanes, _ = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    sources: dict[str, dict[str, Any]] = {}
    pins: dict[str, str] = {}
    for identity, (folder, expected) in SOURCES.items():
        relative = f"{RAW}{folder}/{identity}.json"
        path = checked_path(root, relative)
        if sha256(path) != expected:
            raise ValueError(f"native-source audit hash mismatch: {relative}")
        sources[identity] = json.loads(path.read_text(encoding="utf-8"))
        pins[relative] = expected
    records: list[dict[str, Any]] = []
    for row, included in zip(lane.rows, lane.included, strict=True):
        if included:
            continue
        identity, position = row["record_id"].rsplit(":", 1)
        native = sources[identity]["items"][int(position) - 1]
        duration = 60 * float(native.get("travHours", 0)) + float(native.get("travMins", 0))
        if native["locationName"] != row["source_label"] or duration != float(
            row["target_minutes"]
        ):
            raise ValueError("native source position/value no longer matches accepted record")
        records.append(
            {
                "record_id": row["record_id"],
                "event_id": row["event_id"],
                "site_id": row["physical_site_id"],
                "source_label": row["source_label"],
                "native_source_id": str(native["id"]),
                "native_tsunami_event_id": native["tsunamiEventId"],
                "native_measurement_type": native["typeMeasurementId"],
                "native_reported_minutes": duration,
                "raw_source": identity,
                "ancestry": "unknown",
                "independent_measurement": "unknown",
                "included_primary": False,
                "disposition": "exclude_entire_ambiguous_edge_group",
                "future_sensitivity": "source_ID_order_representatives_or_explicit_dependence",
            }
        )
    return {
        "schema_version": "arrival_model_repeat_review_v1",
        "records": records,
        "native_source_pins": pins,
        "code_pins": {
            p: sha256(root / p)
            for p in [
                "analysis/arrival/model_evidence.py",
                "analysis/arrival/model_data.py",
                "analysis/arrival/evidence.py",
            ]
        },
        "selection_basis": "event/site identity only; no outcome-based representative chosen",
        "conclusion": "distinct catalog IDs do not establish independent measurements or copying",
    }
