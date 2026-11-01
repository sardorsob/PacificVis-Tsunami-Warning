"""Prepare full-index metadata contracts without opening any new event pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_ntwc_batch import (  # noqa: E402
    IndexParser,
    verified_text,
    write_identical_or_new,
)


def build(root: Path) -> tuple[str, list[dict[str, str]]]:
    """Reuse original 40 snapshots; contract the remaining index entries and catalog."""
    index = IndexParser()
    index.feed(verified_text(root / "data/raw/ntwc/batch-2026-10-30/index.html"))
    original: dict[str, Any] = tomllib.loads(
        (root / "config/ntwc-archive-batch.toml").read_text(encoding="utf-8")
    )
    old: dict[str, dict[str, str]] = {}
    for event_id, event in original["events"].items():
        key = parse_qs(urlsplit(str(event["archive_url"])).query)["p"][0]
        old[key] = {**original["assets"][event_id], **event}
    template = dict(next(iter(original["assets"].values())))
    lines = [
        'contract_version = "2026-10-31"',
        'purpose = "Full-index archive acquisition; metadata screening precedes cell parsing"',
        'terms = "Official source attribution retained; redistribution unreviewed"',
        "",
    ]
    mapping: list[dict[str, str]] = []
    contracts: list[dict[str, str]] = []
    for key, label in index.entries.items():
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        url = "https://www.tsunami.gov/previous.events/?p=" + quote(key, safe="")
        entry = {
            "archive_key": key,
            "label": label,
            "url": url,
            "source_id": "ntwc-index-" + digest,
            "local_path": f"data/raw/ntwc/screen-v1/{digest}.html",
            "prior_event_id": "unknown",
            "prior_role": "unassigned",
        }
        if key in old:
            entry.update(
                {
                    "source_id": old[key]["archive_source_id"],
                    "local_path": old[key]["local_path"],
                    "prior_event_id": old[key]["event_id"],
                    "prior_role": old[key]["role"],
                }
            )
        else:
            contracts.append(
                {
                    **template,
                    "source_id": entry["source_id"],
                    "url": url,
                    "local_path": entry["local_path"],
                    "reason": "Owner-authorized all-index source preservation",
                    "expected_content_signature": f"NTWC archive {key}; identity unchecked",
                }
            )
        mapping.append(entry)
    if len(mapping) != 118 or len({r["source_id"] for r in mapping}) != 118:
        raise ValueError("frozen source index must retain 118 unique entries")
    common = {
        **template,
        "crs": "unknown",
        "coordinate_order": "source-defined",
        "units": "source-defined",
        "reason": "Owner-authorized metadata screening",
        "station_metadata": "not applicable",
    }
    contracts.extend(
        [
            {
                **common,
                "source_id": "usgs-ntwc-wide-catalog",
                "source_class": "earthquake catalog",
                "url": "https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&starttime="
                "1996-06-01&endtime=2018-09-01&minmagnitude=6.5&orderby=time-asc",
                "local_path": "data/raw/usgs/ntwc-1996-2018-m65-all-depth.csv",
                "format": "CSV",
                "publisher": "USGS",
                "expected_prefix": "time,latitude,longitude",
                "expected_content_signature": "USGS FDSN CSV header",
                "temporal_semantics": (
                    "Reviewed origins in UTC; original archive origins kept separately"
                ),
            },
            {
                **common,
                "source_id": "ncei-ttt-layer-inventory",
                "source_class": "contour inventory",
                "url": "https://gis.ngdc.noaa.gov/arcgis/rest/services/ttt_contours/MapServer?f=pjson",
                "local_path": "data/raw/ncei/ttt-contours-layer-inventory.json",
                "format": "JSON",
                "publisher": "NOAA NCEI",
                "expected_prefix": "{",
                "expected_content_signature": (
                    "ArcGIS map-service metadata; inspect layers/error separately"
                ),
                "temporal_semantics": "Layer inventory only; no modeled arrivals inferred",
            },
        ]
    )
    for contract in contracts:
        lines.append("[assets." + json.dumps(contract["source_id"]) + "]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        lines.append("")
    return "\n".join(lines), mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    text, mapping = build(args.root)
    write_identical_or_new(args.root / "config/ntwc-archive-screen.toml", text)
    destination = args.root / "artifacts/generated/ntwc-batch/screen-v1/source-map.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_identical_or_new(destination, json.dumps(mapping, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"index_entries": len(mapping), "new_contracts": 80}))


if __name__ == "__main__":
    main()
