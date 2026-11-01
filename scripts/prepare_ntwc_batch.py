"""Freeze metadata-selected NTWC sources and an unexamined evaluation reservation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEED = "ntwc-metadata-batch-2026-10-30-v1"
ANCHORS = frozenset(
    {
        "official20100227063411530_30",
        "official20110311054624120_30",
        "us20003k7a",
        "usp000juhz",
        "usc000f1s0",
        "usp000j48h",
    }
)


class IndexParser(HTMLParser):
    """Read only archive links, retaining their original labels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: dict[str, str] = {}
        self.key: str | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.key = None
            self.parts = []
            href = dict(attrs).get("href") or ""
            parsed = urlsplit(href)
            if parsed.path == "/previous.events/" and parsed.netloc in {"", "www.tsunami.gov"}:
                keys = parse_qs(parsed.query).get("p", [])
                if len(keys) == 1:
                    self.key = keys[0]

    def handle_data(self, data: str) -> None:
        if self.key is not None:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.key is not None:
            if self.key in self.entries:
                raise ValueError(f"duplicate archive key: {self.key}")
            self.entries[self.key] = " ".join("".join(self.parts).split())
            self.key = None


def verified_text(path: Path) -> str:
    """Reject source bytes that no longer match the acquisition digest."""
    payload = path.read_bytes()
    expected = path.with_name(path.name + ".sha256").read_text(encoding="utf-8").strip()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"checksum mismatch: {path}")
    return payload.decode("utf-8-sig")


def reserve_events(
    events: list[dict[str, str]], count: int, *, stratum_key: str = "region", seed: str = SEED
) -> set[str]:
    """Allocate by source-region proportion, then hash-order within each region."""
    sizes = Counter(row[stratum_key] for row in events)
    selected: set[str] = set()
    held = Counter[str]()
    available = [row for row in events if row["event_id"] not in ANCHORS]
    while len(selected) < count:
        candidates = [
            row
            for row in available
            if row["event_id"] not in selected
            and held[row[stratum_key]] < sizes[row[stratum_key]] - 1
        ]
        if not candidates:
            raise ValueError(
                "insufficient events for reservation with a development case per region"
            )
        row = min(
            candidates,
            key=lambda event: (
                (held[event[stratum_key]] + 1) / sizes[event[stratum_key]],
                hashlib.sha256(f"{seed}:{event['event_id']}".encode()).hexdigest(),
            ),
        )
        selected.add(row["event_id"])
        held[row[stratum_key]] += 1
    return selected


def build_batch(root: Path) -> tuple[str, dict[str, object]]:
    """Join explicit IDs and archive keys; never identify earthquakes from dates alone."""
    raw = root / "data/raw/ntwc/batch-2026-10-30"
    parser = IndexParser()
    parser.feed(verified_text(raw / "index.html"))
    catalog = {
        row["id"]: row
        for row in csv.DictReader(io.StringIO(verified_text(raw / "usgs-catalog.csv")))
    }
    selection_path = root / "config/ntwc-event-selection.csv"
    with selection_path.open(encoding="utf-8", newline="") as source:
        events = list(csv.DictReader(source))
    if not 30 <= len(events) <= 40:
        raise ValueError("the authorized batch must contain 30–40 candidate events")
    ids = [row["event_id"] for row in events]
    keys = [row["archive_key"] for row in events]
    if len(set(ids)) != len(ids) or len(set(keys)) != len(keys):
        raise ValueError("duplicate event ID or archive key")
    for row in events:
        if not re.fullmatch(r"[A-Za-z0-9_]+", row["event_id"]):
            raise ValueError("unsafe event identifier")
        if row["archive_key"] not in parser.entries or row["event_id"] not in catalog:
            raise ValueError(f"source identity absent from index/catalog: {row}")
        origin = catalog[row["event_id"]]
        if origin["type"] != "earthquake" or not origin["magType"].startswith("mw"):
            raise ValueError(f"unsupported event or magnitude type: {row['event_id']}")
        if float(origin["mag"]) < 7 or not 0 <= float(origin["depth"]) <= 70:
            raise ValueError(f"outside discovery envelope: {row['event_id']}")
        row.update({f"usgs_{key}": value for key, value in origin.items()})
        row["archive_label"] = parser.entries[row["archive_key"]]
    reservation = reserve_events(events, round(len(events) * 0.2))
    for row in events:
        row["role"] = "sealed_evaluation" if row["event_id"] in reservation else "development"
        row["archive_source_id"] = "ntwc-" + row["event_id"]
        row["archive_url"] = "https://www.tsunami.gov/previous.events/?p=" + quote(
            row["archive_key"], safe=""
        )
    events.sort(key=lambda row: (row["usgs_time"], row["event_id"]))
    frozen = json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(frozen).hexdigest()
    lines = [
        'contract_version = "2026-10-30"',
        f'selection_sha256 = "{digest}"',
        f'selection_seed = "{SEED}"',
        'selection_design = "Purposive metadata cohort; not representative or quality-certified"',
        'terms = "NOAA and upstream gauge providers; preserve attribution; '
        'redistribution unreviewed"',
        'time_policy = "Preserve NTWC contemporary origins and reviewed USGS origins separately"',
        "",
    ]
    for row in events:
        lines.append(f"[events.{row['event_id']}]")
        for key in (
            "event_id",
            "name",
            "region",
            "mechanism_status",
            "role",
            "archive_source_id",
            "archive_url",
            "usgs_time",
            "usgs_mag",
            "usgs_magType",
        ):
            lines.append(f"{key} = {json.dumps(row[key])}")
        lines.extend(["", f"[assets.{row['event_id']}]"])
        fields = dict(
            source_id=row["archive_source_id"],
            source_class="NTWC event arrival archive",
            availability="approved",
            reason="User-authorized metadata-selected acquisition",
            url=row["archive_url"],
            local_path=f"data/raw/ntwc/batch-2026-10-30/{row['event_id']}.html",
            format="HTML",
            publisher="NOAA National Tsunami Warning Center",
            expected_content_signature=f"Event archive {row['archive_key']}; "
            "table shape and event identity require downstream validation",
            expected_prefix="<!DOCTYPE",
            units="source-labeled cells; no conversions",
            crs="unknown",
            horizontal_datum="unknown",
            vertical_datum="unknown",
            coordinate_order="not applicable to arrival table",
            temporal_semantics="Retain published UTC/GMT/Julian-day headers; no retiming",
            station_metadata="Place labels only; deployment identity unverified",
        )
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in fields.items())
        lines.append("")
    ledger: dict[str, object] = {
        "seed": SEED,
        "selection_sha256": digest,
        "selection_csv_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "index_sha256": hashlib.sha256((raw / "index.html").read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256((raw / "usgs-catalog.csv").read_bytes()).hexdigest(),
        "selection_basis": "Official index and explicit USGS IDs; magnitude, region and era; "
        "no arrival differences or waveform quality examined",
        "reservation_limit": "Metadata reservation, not final evaluation approval; all source "
        "mechanisms and identities need review; rows remain masked until authorized evaluation",
        "events": events,
        "index_dispositions": [
            {
                "archive_key": key,
                "label": label,
                "status": "selected" if key in keys else "not_selected_not_screened",
            }
            for key, label in parser.entries.items()
        ],
    }
    return "\n".join(lines), ledger


def write_identical_or_new(path: Path, text: str) -> None:
    """Allow exact reproduction, but never replace a conflicting selection."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"refusing to replace existing selection: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        target.write(text)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config, ledger = build_batch(root)
    write_identical_or_new(root / "config/ntwc-archive-batch.toml", config)
    write_identical_or_new(
        root / "artifacts/generated/ntwc-batch/selection.json",
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
    )
    events = cast(list[dict[str, str]], ledger["events"])
    table = io.StringIO(newline="")
    columns = [
        "event_id",
        "name",
        "region",
        "role",
        "mechanism_status",
        "usgs_time",
        "usgs_mag",
        "usgs_magType",
        "usgs_depth",
        "usgs_latitude",
        "usgs_longitude",
        "archive_url",
    ]
    writer = csv.DictWriter(table, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(events)
    write_identical_or_new(root / "artifacts/generated/ntwc-batch/events.csv", table.getvalue())
    report = [
        "# Selected tsunami archive candidates",
        "",
        "Forty metadata-selected candidates, not forty certified clean events. "
        "Current USGS magnitude subtypes, reviewed origins and archive identities are preserved. "
        "The source-region labels are sampling groups, not a tectonic classification.",
        "",
        "32 events are development data; eight are reserved with arrival cells masked. "
        "The reservation needs source-sequence review before evaluation. "
        "All mechanisms and deployment identities need scientific review before pooling.",
        "",
        f"Selection SHA-256: `{ledger['selection_sha256']}`.",
        "",
        "| Event | Magnitude (USGS subtype) | Region | Role | Archive |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in events:
        report.append(
            f"| {event['name']} | {event['usgs_mag']} {event['usgs_magType']} | "
            f"{event['region']} | {event['role']} | [NTWC]({event['archive_url']}) |"
        )
    report.extend(
        [
            "",
            "Sources: [NTWC event index](https://www.tsunami.gov/recent_tsunamis/) "
            "and the checksummed USGS catalog specified in "
            "`config/ntwc-archive-discovery.toml`. "
            "Reproduce with `.venv/bin/python scripts/prepare_ntwc_batch.py`.",
            "",
        ]
    )
    write_identical_or_new(root / "artifacts/generated/ntwc-batch/selection.md", "\n".join(report))
    print(f"Frozen selection: {ledger['selection_sha256']}")


if __name__ == "__main__":
    main()
