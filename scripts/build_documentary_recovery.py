"""Build a separate, lossless documentary supplement from pinned public records."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.documentary_recovery import (  # noqa: E402
    extract_forecasts,
    iso,
    local_clock,
    native_origins,
    observation_day,
)
from analysis.arrival.evidence import (  # noqa: E402
    Row,
    development_reports,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import stable_id  # noqa: E402
from pipeline.acquisition import load_contracts  # noqa: E402

DOCUMENT_EVENTS = {
    "documentary-b01-04": "usp000h1ys", "documentary-b02-04": "usp000exfn",
    "documentary-b02-05": "usp000exfn",
    "documentary-b03-07": "official20100227063411530_30",
    "documentary-b03-08": "official20100227063411530_30",
}


class Cells(HTMLParser):
    """Read the one frozen Kuril table, retaining all cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.parts: list[str] = []
        self.in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        if tag == "td":
            self.in_cell, self.parts = True, []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self.row.append(" ".join(" ".join(self.parts).split()))
            self.in_cell = False
        if tag == "tr" and self.row:
            self.rows.append(self.row.copy())
            self.row = []


def paper_observations(document: dict[str, Any]) -> list[Row]:
    rows: list[Row] = []
    for page_number, event_id, day, origin in [
        (3, "usp000exfn", "2006-11-15", "11:14"),
        (6, "usp000f2ab", "2007-01-13", "04:23"),
    ]:
        text = next(p["text"] for p in document["pages"] if p["page"] == page_number)
        pattern = re.compile(
            r"^\s*([A-Za-z][A-Za-z +#-]*?)\s+(\d{2}\.\d{2})\s+(\d{3}\.\d{2})"
            r"\s+(\d+\.\d+\*?)\s+(\d{2}:\d{2}|\?)\s+(\d+:\d{2}|\?)", re.MULTILINE
        )
        matches = list(pattern.finditer(text))
        if len(matches) != (13 if page_number == 3 else 11):
            raise ValueError("paper first-wave table extraction incomplete")
        for match in matches:
            label, lat, lon, sampling, clock, travel = match.groups()
            utc = observation_day(day, origin, clock, travel)
            rows.append({
                "record_id": stable_id("paper-first-wave", event_id, label),
                "event_id": event_id, "source_id": document["source_id"],
                "kind": "reported_first_wave", "station_label": label,
                "arrival_utc": utc, "native_clock": clock, "native_zone": "UTC",
                "native_travel_hm": travel, "native_origin_minute_utc": f"{day}T{origin}:00Z",
                "date_basis": "native_clock_and_published_travel_time_agree" if utc != "unknown"
                else "source_missing", "latitude_native": lat, "longitude_native": lon,
                "sampling_minutes_native": sampling, "precision_seconds": "60",
                "locator": f"PDF page {page_number}; Table {1 if page_number == 3 else 2}; {label}",
                "raw_excerpt": match[0].strip(), "source_sha256": document["raw_sha256"],
                "model_approved": "False", "physical_onset_validated": "False",
                "deployment_identity": "unknown", "independence": "unknown",
                "parent_table_replacement_allowed": "False",
            })
    return rows


def kuril_forecasts(path: Path, digest: str) -> list[Row]:
    text = path.read_text()
    if "Origin Time 2024 PST January 12, 2007" not in " ".join(text.split()):
        raise ValueError("frozen Kuril product calendar changed")
    parser = Cells()
    parser.feed(text)
    rows: list[Row] = []
    for index, cells in enumerate(parser.rows[1:], 1):
        if not any(cells):
            continue
        if len(cells) != 4:
            raise ValueError("Kuril table shape changed")
        match = re.fullmatch(r"(\d{4}) (AKST|HST|PST) (\d{1,2})/(\d{1,2})", cells[1])
        if not match:
            raise ValueError("Kuril table dated clock not understood")
        clock, zone, month, day = match.groups()
        rows.append({
            "record_id": stable_id("kuril-forecast", str(index)), "event_id": "usp000f2ab",
            "source_id": "documentary-b01-01", "station_label": cells[0],
            "kind": "estimated_initial_arrival", "native_clock": clock, "native_zone": zone,
            "arrival_utc": iso(local_clock(2007, int(month), int(day), clock, zone)),
            "product_id": "NTWC:Kuril2007:dated_forecast_table:issue_unknown",
            "issuing_center": "NTWC", "issue_utc": "unknown", "message_version": "unknown",
            "native_origin_utc": "2007-01-13T04:24:00Z",
            "date_basis": "explicit_month_day_and_document_year",
            "available_before_predicted_arrival": "unknown", "latitude_native": "unknown",
            "longitude_native": "unknown", "raw_excerpt": " | ".join(cells),
            "locator": f"table row {index}", "source_sha256": digest,
            "model_approved": "False", "parent_table_replacement_allowed": "False",
            "independence": "unknown", "deployment_identity": "unknown",
        })
    if len(rows) != 21:
        raise ValueError("incomplete frozen Kuril forecast table")
    return rows


def label_key(label: str) -> str:
    label = label.upper().split(",")[0]
    label = re.sub(r"-(AK|CA|OR|WA|BC|HI)$", "", label.strip())
    return re.sub(r"[^A-Z0-9]", "", label)


def build(inputs: Path, extracted: Path, root: Path, output: Path) -> None:
    frozen = verify_inputs(inputs)
    if output.exists():
        raise ValueError("output already exists; use a fresh version/replay path")
    events = {k: v for k, v in frozen["events"].items() if v["role"] == "development"}
    documents = cast(list[dict[str, Any]], json.loads(extracted.read_text()))
    contracts = [c for p in sorted((root / "config").glob("arrival-documentary-b*.toml"))
                 for c in load_contracts(p)]
    sources = {c.source_id: c for c in contracts}
    pins: dict[str, str] = {str(inputs.relative_to(root)): sha256(inputs),
                            str(extracted.relative_to(root)): sha256(extracted)}
    raw: list[Row] = []
    forecasts: list[Row] = []
    dispositions: list[Row] = []
    for source in contracts:
        path = root / source.local_path
        if not path.exists():
            dispositions.append({"source_id": source.source_id, "status": "not_usable_cached",
                                 "reason": "see immutable acquisition receipt"})
            continue
        digest = sha256(path)
        if digest != path.with_name(path.name + ".sha256").read_text().strip():
            raise ValueError("raw checksum mismatch")
        pins[source.local_path.as_posix()] = digest
        raw.append({"source_id": source.source_id, "source_path": source.local_path.as_posix(),
                    "source_sha256": digest, "url": source.url, "bytes": str(path.stat().st_size)})
        if source.source_id in {"documentary-b03-02", "documentary-b03-05"}:
            dispositions.append({"source_id": source.source_id,
                                 "status": "excluded_wrong_event_response",
                                 "reason": "historical query returned current-event metadata"})
            continue
        if not re.search(r"/events/PAAQ/\d{4}/\d{2}/\d{2}/[^/]+/\d+/[^/]+/[^/]+\.txt$",
                         source.url):
            dispositions.append({"source_id": source.source_id, "status": "retained_document",
                                 "reason": "metadata/collection/table"})
            continue
        text = path.read_text()
        origins = native_origins(text)
        matched = [eid for eid, e in events.items() if any(abs((
            datetime.fromisoformat(t.replace("Z", "+00:00")) -
            datetime.fromisoformat(e["usgs_time"].replace("Z", "+00:00"))
        ).total_seconds()) <= 120 for t in origins)]
        records: list[Row] = []
        if len(matched) == 1:
            records = extract_forecasts(text, matched[0], source.source_id,
                                        reference_origin=events[matched[0]]["usgs_time"])
            for r in records:
                r.update(source_sha256=digest, locator="original text; " + r["raw_excerpt"])
        forecasts.extend(records)
        dispositions.append({"source_id": source.source_id, "status": "parsed_original_message",
                             "event_id": matched[0] if len(matched) == 1 else "unknown",
                             "forecast_rows": str(len(records)),
                             "reason": "measurement times excluded; absent ETA is product-specific"
                             if len(matched) == 1 else "event origin ambiguous/unverified"})
    observations: list[Row] = []
    for document in documents:
        source = sources[document["source_id"]]
        if sha256(root / source.local_path) != document["raw_sha256"]:
            raise ValueError("extracted text/raw binding changed")
        if document["source_id"] == "documentary-b01-05":
            observations = paper_observations(document)
            continue
        event = DOCUMENT_EVENTS[document["source_id"]]
        if event not in events:
            raise ValueError("document outside development cohort")
        text = "\n".join(p["text"] for p in document["pages"])
        records = extract_forecasts(text, event, document["source_id"],
                                    reference_origin=events[event]["usgs_time"])
        for record in records:
            pages = [str(p["page"]) for p in document["pages"]
                     if " ".join(record["raw_excerpt"].split()) in " ".join(p["text"].split())]
            if not pages:
                raise ValueError("forecast excerpt has no source locator")
            record.update(source_sha256=document["raw_sha256"],
                          locator="PDF page " + ",".join(pages) if pages != ["0"]
                          else "DOC text paragraph containing " + record["raw_excerpt"])
        forecasts.extend(records)
    forecasts.extend(kuril_forecasts(root / sources["documentary-b01-01"].local_path,
                                    pins[sources["documentary-b01-01"].local_path.as_posix()]))
    # Multiple copies of one bulletin are supporting evidence, not extra instances.
    canonical: dict[str, Row] = {}
    members: list[Row] = []
    for row in sorted(forecasts, key=lambda r: r["record_id"]):
        key = stable_id("forecast-instance", row["event_id"], row["product_id"],
                        row["station_label"], row["native_clock"], row["arrival_utc"])
        canonical.setdefault(key, {**row, "forecast_instance_id": key})
        members.append({"forecast_instance_id": key, "record_id": row["record_id"]})
    if len({r["record_id"] for r in forecasts}) != len(forecasts):
        raise ValueError("duplicate evidence record IDs")
    for row in canonical.values():
        peers = [other for other in canonical.values()
                 if (other["product_id"], other["station_label"].upper()) ==
                 (row["product_id"], row["station_label"].upper())]
        row["conflicting_product_point_clocks"] = str(
            len({other["arrival_utc"] for other in peers}) > 1
        )
    baseline = development_reports(frozen)
    candidates: list[Row] = []
    for key, row in canonical.items():
        for report in baseline:
            if (report["event_id"] == row["event_id"] and
                    label_key(report["source_label"]) == label_key(row["station_label"])):
                candidates.append({
                    "forecast_instance_id": key, "report_id": report["report_id"],
                    "event_id": row["event_id"], "forecast_utc": row["arrival_utc"],
                    "baseline_observed_utc": report["observed_utc"] or "unknown",
                    "baseline_estimated_utc": report["estimated_utc"] or "unknown",
                    "baseline_observed_state": report["observed_state"],
                    "baseline_estimate_state": report["estimate_state"],
                    "native_forecast_label": row["station_label"],
                    "native_report_label": report["source_label"],
                    "link_status": "normalized_label_candidate_not_approved_identity",
                    "pair_approved": "False", "parent_replacement_allowed": "False",
                })
    calendar_candidates: list[Row] = []
    for observation in observations:
        if observation["arrival_utc"] == "unknown":
            continue
        clock = observation["native_clock"].replace(":", "")
        for report in baseline:
            if (report["event_id"] == observation["event_id"] and
                    label_key(report["source_label"]) == label_key(observation["station_label"])):
                native = f"{report['observed_hour']:0>2}{report['observed_minute']:0>2}"
                calendar_candidates.append({
                    "report_id": report["report_id"], "record_id": observation["record_id"],
                    "event_id": observation["event_id"], "native_report_clock": native,
                    "documentary_clock": clock, "clock_agrees": str(native == clock),
                    "documentary_utc": observation["arrival_utc"],
                    "baseline_observed_utc": report["observed_utc"] or "unknown",
                    "calendar_write_allowed": "False", "identity_review_required": "True",
                })
    for name, rows in [("raw_sources", raw), ("forecast_evidence", forecasts),
                       ("forecast_instances", list(canonical.values())),
                       ("forecast_members", members),
                       ("first_wave_observations", observations), ("link_candidates", candidates),
                       ("calendar_candidates", calendar_candidates),
                       ("source_dispositions", dispositions)]:
        fields = sorted({k for row in rows for k in row})
        write_rows(output / f"{name}.csv.gz",
                   [{k: row.get(k, "unknown") for k in fields} for row in rows])
    summary = {
        "schema_version": "arrival_documentary_supplement_v1", "development_events": len(events),
        "raw_sources": len(raw),
        "raw_bytes_including_duplicate_snapshots": sum(int(r["bytes"]) for r in raw),
        "forecast_evidence_records": len(forecasts), "forecast_instances": len(canonical),
        "forecast_events": len({r["event_id"] for r in forecasts}),
        "forecast_products": len({r["product_id"] for r in forecasts}),
        "exact_forecast_instances": sum(r["arrival_utc"] != "unknown" for r in canonical.values()),
        "forecast_kinds": dict(Counter(r["kind"] for r in canonical.values())),
        "observation_records": len(observations),
        "exact_first_wave_observations": sum(r["arrival_utc"] != "unknown" for r in observations),
        "normalized_label_candidates": len(candidates), "approved_new_pairs": 0,
        "observation_calendar_candidates": len(calendar_candidates),
        "original_pairs_unchanged": 388, "original_unresolved_pairs_unchanged": 789,
        "original_reports_unchanged": len(baseline), "model_fitted": False,
        "notes": "New products stay separate; equal station labels do not establish deployments, "
                 "independent observations, compatible forecast points or prospective skill.",
    }
    write_json(output / "summary.json", summary)
    for p in sorted((root / "config").glob("arrival-documentary-b*.toml")):
        pins[p.relative_to(root).as_posix()] = sha256(p)
    write_json(output / "inputs.json", {"files": pins})
    write_json(output / "manifest.json", {p.name: sha256(p) for p in sorted(output.iterdir())})
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.inputs.resolve(), args.extracted.resolve(), args.root.resolve(), args.output)


if __name__ == "__main__":
    main()
