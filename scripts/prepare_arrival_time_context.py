"""Declare a reviewed USGS reference for exact reported clocks, without releasing onsets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def contexts(
    selection: dict[str, Any], selection_path: Path,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Retain only unambiguous same-year, explicitly UTC source-origin metadata.

    This reference permits durations from reviewed USGS origin. It does not claim
    that NTWC used that reviewed origin when making its original estimates.
    Compound pages, unspecified zones and source-year conflicts are withheld.
    """
    rows: list[dict[str, str]] = []
    withheld: dict[str, str] = {}
    material = {k: v for k, v in selection.items() if k != "selection_sha256"}
    expected = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected != selection.get("selection_sha256"):
        raise ValueError("frozen selection digest mismatch")
    fingerprint = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    for event in selection["events"]:
        if event["role"] != "development":
            continue
        eid = str(event["event_id"])
        evidence = json.loads(event["origin_evidence"])
        if event.get("attribution_status") == "compound_unresolved" or len(evidence) != 1:
            withheld[eid] = "compound_or_ambiguous_source_origin"
            continue
        source = evidence[0]
        if source["time_basis"] not in {"UTC", "GMT", "Z"}:
            withheld[eid] = "source_origin_timezone_unstated"
            continue
        original = datetime.fromisoformat(source["origin_time"])
        reviewed = datetime.fromisoformat(event["usgs_time"].replace("Z", "+00:00"))
        if original.year != reviewed.year:
            withheld[eid] = "calendar_year_conflict"
            continue
        rows.append({
            "event_id": eid,
            "calendar_year": str(original.year),
            "calendar_year_provenance": (
                f"{event['archive_url']}; explicit source origin {source['origin_time']}; "
                f"source SHA256 {event['source_sha256']}"
            ),
            "origin_utc": event["usgs_time"],
            "origin_basis": "reviewed_USGS_reference_not_claimed_original_NTWC_prediction_origin",
            "origin_provenance": (
                f"USGS snapshot data/raw/usgs/ntwc-1996-2018-m65-all-depth.csv; event {eid}; "
                f"frozen selection {selection_path.as_posix()} SHA256 {fingerprint}"
            ),
        })
    return rows, withheld


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, withheld = contexts(json.loads(args.selection.read_text()), args.selection)
    if not rows:
        parser.error("no eligible reference-clock contexts; preserve withheld events")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    payload = target.getvalue().encode()
    if args.output.exists() and args.output.read_bytes() != payload:
        parser.error("time context already exists with different bytes; use a new version")
    if not args.output.exists():
        args.output.write_bytes(payload)
    print(json.dumps({"declared_reference_events": len(rows), "withheld": withheld},
                     sort_keys=True))


if __name__ == "__main__":
    main()
