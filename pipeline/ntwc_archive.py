"""Offline, loss-preserving census of contracted NTWC arrival tables.

This module inventories source strings; it never interprets clock times, infers
physical onsets, or calculates arrival errors. Evaluation pages expose only
structural counts. The acquisition contract and SHA-256 sidecars are required.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlsplit

from pipeline.acquisition import SourceContract, load_contracts


class ArchiveError(ValueError):
    """An input violates the local archive inventory contract."""


@dataclass
class Link:
    """An exact source hyperlink and its visible text."""

    href: str
    start_tag: str
    text: str = ""


@dataclass
class Cell:
    """A source cell, including markup and unexpanded spans."""

    tag: str
    attributes: list[tuple[str, str | None]]
    text: str = ""
    raw_html: str = ""
    links: list[Link] = field(default_factory=lambda: list[Link]())

    @property
    def has_span(self) -> bool:
        """Report spans needing explicit layout review, without expanding them."""
        return any(k in {"rowspan", "colspan"} and v != "1" for k, v in self.attributes)


@dataclass
class Row:
    """One source row; its index is retained even when it is rejected."""

    cells: list[Cell] = field(default_factory=lambda: list[Cell]())
    raw_html: str = ""


@dataclass
class Table:
    """One table with source-ordered rows and parser diagnostics."""

    rows: list[Row] = field(default_factory=lambda: list[Row]())
    issues: list[str] = field(default_factory=lambda: list[str]())


class _Tables(HTMLParser):
    """Read HTML tables without browser repair or third-party dependencies."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.offsets = [0]
        for match in re.finditer("\n", source):
            self.offsets.append(match.end())
        self.tables: list[Table] = []
        self.stack: list[Table] = []
        self.row: Row | None = None
        self.cell: Cell | None = None
        self.link: Link | None = None
        self.cell_start = 0
        self.row_start = 0

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def _close_cell(self, offset: int) -> None:
        if self.cell is not None:
            self.cell.raw_html = self.source[self.cell_start:offset]
        self.cell = None
        self.link = None

    def _close_row(self, offset: int) -> None:
        self._close_cell(offset)
        if self.row is not None:
            self.row.raw_html = self.source[self.row_start:offset]
        self.row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        offset = self._offset()
        if tag == "table":
            if self.stack:
                self.stack[-1].issues.append("nested_table")
                self._close_row(offset)
            table = Table()
            self.tables.append(table)
            self.stack.append(table)
        elif self.stack and tag == "tr":
            self._close_row(offset)
            self.row = Row()
            self.row_start = offset
            self.stack[-1].rows.append(self.row)
        elif self.row is not None and tag in {"td", "th"}:
            self._close_cell(offset)
            self.cell = Cell(tag=tag, attributes=attrs)
            self.cell_start = offset
            self.row.cells.append(self.cell)
        elif self.cell is not None and tag == "a":
            self.link = Link(dict(attrs).get("href") or "", self.get_starttag_text() or "")
            self.cell.links.append(self.link)
        elif self.cell is not None and tag == "br":
            self.handle_data("\n")

    def handle_endtag(self, tag: str) -> None:
        offset = self._offset()
        end = self.source.find(">", offset) + 1
        if tag in {"td", "th"}:
            self._close_cell(end)
        elif tag == "tr":
            self._close_row(end)
        elif tag == "table" and self.stack:
            self._close_row(end)
            self.stack.pop()
        elif tag == "a":
            self.link = None

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.text += data
        if self.link is not None:
            self.link.text += data

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&#{name};"))

    def finish(self) -> list[Table]:
        """Finish the parser and retain incomplete-table diagnostics."""
        self.feed(self.source)
        self.close()
        self._close_row(len(self.source))
        for table in self.stack:
            table.issues.append("unclosed_table")
        return self.tables


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _column(text: str) -> str | None:
    """Recognize documented labels, not arrival values or positional guesses."""
    key = _key(text)
    if key in {"tidegage", "tidegauge", "tidegagesite", "tidegagemeasurementlocation",
               "tidegaugemeasurementlocation"}:
        return "location"
    if re.fullmatch(r"arrivaltime(?:utc|gmt)", key):
        return "arrival_as_labeled"
    if re.fullmatch(r"eta(?:utc|gmt)", key):
        return "eta_as_labeled"
    if re.fullmatch(r"(?:estimated|computed)(?:initial)?arrivaltime(?:utc|gmt)(?:jday)?", key):
        return "estimated_arrival"
    if re.fullmatch(r"observed(?:initial)?arrivaltime(?:utc|gmt)(?:jday)?", key):
        return "observed_arrival"
    if key in {"peakamplitudeabovesealevelincm", "peakamplitudecm"}:
        return "peak_amplitude"
    if key in {"waveheightcmpt", "peakwaveheightcmpt"}:
        return "wave_height_peak_to_trough"
    if re.fullmatch(r"timeofpeakamplitudemeasurement(?:utc|gmt)jday", key):
        return "peak_time"
    if key in {"modelforecastamplitudeabovesealevelincm", "modelforecastamplitudecm"}:
        return "model_amplitude"
    if key == "initialmotion":
        return "initial_motion"
    if key in {"sampleintervalmin", "sampleintervalminutes",
               "sampleintervalminunlessotherwisestated"}:
        return "sample_interval"
    if re.fullmatch(r"datafiles?(?:juliandaystartsat0000(?:utc|gmt))?", key):
        return "data_file"
    return None


def link_status(href: str, archive_url: str) -> tuple[str, str]:
    """Resolve an exact href, allowing only the NTWC HTTPS archive path.

    This is a discovery status, never permission to download the URL. A later
    acquisition must put the selected link into an exact source contract.
    """
    if not href or any(ord(char) < 32 for char in href) or "\\" in href:
        return "rejected_unsafe_url", ""
    resolved = urljoin(archive_url, href)
    try:
        parsed = urlsplit(resolved)
        decoded = unquote(parsed.path)
        safe = (
            parsed.scheme == "https"
            and parsed.netloc == "www.tsunami.gov"
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and decoded.startswith("/previous.events/")
            and ".." not in decoded.split("/")
            and "\\" not in decoded
            and "%" not in decoded
            and not any(ord(char) < 32 for char in decoded)
            and not parsed.fragment
        )
    except ValueError:
        safe = False
    return ("safe_archive_link" if safe else "rejected_unsafe_url"), resolved


def _cell_state(text: str) -> str:
    # Normalize only for classification. Exported source text and markup stay exact.
    stripped = " ".join(text.replace("\xa0", " ").split()).casefold()
    if not stripped:
        return "blank"
    if stripped in {"-", "--", "n/a", "na", "none", "unknown"} or re.fullmatch(
        r"\(?\?+\)?(?:\s*(?:\((?:jd\s*)?\d{1,3}\)|"
        r"\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?))?", stripped
    ):
        return "source_missing_token"
    return "source_text"


def arrival_value_flags(fields: dict[str, str]) -> dict[str, bool]:
    """Count source-value presence, keeping ambiguous legacy labels separate.

    Presence does not validate a clock, an observed physical onset, or a usable
    model row. Approximate/qualified numeric strings remain present source text.
    """
    estimate = fields.get("estimated_arrival", fields.get("eta_as_labeled", ""))
    observed = fields.get("observed_arrival", "")
    unspecified = fields.get("arrival_as_labeled", "")
    has_estimate = _cell_state(estimate) == "source_text"
    has_observed = _cell_state(observed) == "source_text"
    has_unspecified = _cell_state(unspecified) == "source_text"
    return {
        "estimate_value": has_estimate,
        "observed_value": has_observed,
        "both_values": has_estimate and has_observed,
        "arrival_as_labeled_value": has_unspecified,
        "estimate_and_arrival_as_labeled_values": has_estimate and has_unspecified,
    }


def link_identity(url: str) -> dict[str, str]:
    """Extract filename tokens without equating an archive code to a physical site."""
    empty = {"link_code": "unknown", "link_sensor": "unknown", "link_day": "unknown",
             "link_year": "unknown", "link_identity_status": "unrecognized_filename"}
    try:
        filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    except ValueError:
        return empty
    patterns = (
        (r"(?P<code>[a-z0-9]+)_(?P<sensor>[A-Z])_(?P<year>\d{4})\.(?P<day>\d{3})",
         "archive_code_sensor_year_day"),
        (r"(?P<code>[a-z0-9]{4})(?P<sensor>[A-Z])(?P<year>\d{4})\.(?P<day>\d{3})",
         "archive_code_sensor_year_day_compact"),
        (r"(?P<code>[a-z0-9]{4})(?P<day>\d{3})-(?P<year>\d{2})\.dat",
         "archive_code_day_two_digit_year"),
        (r"(?P<code>[a-z0-9]{4})-\d{1,2}-\d{1,2}-(?P<year>\d{4})\.dat",
         "archive_code_calendar_date"),
        (r"(?P<code>[a-z0-9]{4})\.(?P<day>\d{3})", "archive_code_day"),
    )
    for pattern, status in patterns:
        match = re.fullmatch(pattern, filename)
        if match:
            values = match.groupdict()
            day = values.get("day", "unknown")
            if day != "unknown" and not 1 <= int(day) <= 366:
                return {**empty, "link_identity_status": "invalid_filename_day"}
            return {**empty, **{f"link_{key}": value for key, value in values.items()},
                    "link_identity_status": status}
    return empty


def parse_archive(source: str, archive_url: str, *, sealed: bool = False) -> dict[str, Any]:
    """Inventory an HTML page; unknown headers and row layouts stay rejected.

    Raw cells, markup, headers, links and row order are retained for development
    pages. Sealed pages return only counts, family identifiers and status codes.
    """
    tables = _Tables(source).finish()
    census: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for table_index, table in enumerate(tables):
        candidates = [
            index for index, row in enumerate(table.rows)
            if "arrival" in _key(" ".join(cell.text for cell in row.cells))
            and (any(re.search(r"observed(?:initial)?arrival", _key(cell.text))
                     for cell in row.cells)
                 or any(_column(cell.text) == "eta_as_labeled" for cell in row.cells))
        ]
        if not candidates:
            continue
        header_index = candidates[0]
        header = table.rows[header_index]
        columns = [_column(cell.text) for cell in header.cells]
        recognized_pair = (
            {"location", "estimated_arrival", "observed_arrival"}.issubset(columns)
            or {"location", "arrival_as_labeled", "eta_as_labeled"}.issubset(columns)
        )
        known = (
            not table.issues
            and not any(cell.has_span for cell in header.cells)
            and None not in columns
            and len(set(columns)) == len(columns)
            and recognized_pair
        )
        basis = {token for token in ("utc", "gmt")
                 if any(token in _key(cell.text) for cell in header.cells)}
        known = known and len(basis) == 1
        estimate_kind = "computed" if any(
            re.search(r"computed(?:initial)?arrival", _key(cell.text)) for cell in header.cells
        ) else "estimated"
        day_label = "_jday" if any(
            "jday" in _key(cell.text) for cell in header.cells
        ) else ""
        family = (f"{estimate_kind}_observed_{next(iter(basis))}{day_label}"
                  if known else "unknown")
        if known and "eta_as_labeled" in columns:
            family = f"arrival_eta_{next(iter(basis))}"
        counts = {"accepted_source_rows": 0, "blank_rows": 0, "rejected_rows": 0}
        counts.update({f"rows_with_{key}": 0 for key in arrival_value_flags({})})
        spanning_until = -1
        for row_index, row in enumerate(table.rows):
            if row_index <= header_index:
                continue
            if not any(cell.text.strip() or cell.links for cell in row.cells):
                status = "blank_row"
                counts["blank_rows"] += 1
            elif not known:
                status = "rejected_unknown_header"
                counts["rejected_rows"] += 1
            elif [_column(cell.text) for cell in row.cells] == columns:
                status = "rejected_repeated_header"
                counts["rejected_rows"] += 1
            elif any(cell.has_span for cell in row.cells) or row_index <= spanning_until:
                status = "rejected_spanning_row"
                counts["rejected_rows"] += 1
            elif len(row.cells) != len(columns):
                status = "rejected_cell_count"
                counts["rejected_rows"] += 1
            else:
                status = "accepted_source_row"
                counts["accepted_source_rows"] += 1
            for cell in row.cells:
                for name, value in cell.attributes:
                    if name == "rowspan" and value != "1":
                        length = int(value) if value and value.isdecimal() else 0
                        end_row = row_index + length - 1 if length > 0 else len(table.rows)
                        spanning_until = max(spanning_until, end_row)
            fields = dict(zip(cast(list[str], columns),
                              (cell.text for cell in row.cells), strict=True)) if (
                status == "accepted_source_row"
            ) else {}
            if status == "accepted_source_row":
                for key, present in arrival_value_flags(fields).items():
                    counts[f"rows_with_{key}"] += int(present)
            if sealed:
                continue
            records.append({
                "table_index": table_index, "row_index": row_index,
                "status": status, "fields": fields,
                "cell_states": [_cell_state(cell.text) for cell in row.cells],
                "cells": [asdict(cell) for cell in row.cells], "raw_html": row.raw_html,
            })
            if status == "accepted_source_row" and "data_file" in columns:
                cell = row.cells[columns.index("data_file")]
                for link in cell.links:
                    safety, resolved = link_status(link.href, archive_url)
                    links.append({
                        "table_index": table_index, "row_index": row_index,
                        "location_text": fields["location"],
                        "href": link.href, "start_tag": link.start_tag,
                        "link_text": link.text, "resolved_url": resolved,
                        "status": safety,
                        **link_identity(resolved),
                    })
        summary: dict[str, Any] = {
            "table_index": table_index, "header_family": family,
            "status": "recognized" if known else "rejected_unknown_header",
            "source_rows": len(table.rows), "header_row_index": header_index,
            "rows_before_header": header_index,
            "rows_after_header": len(table.rows) - header_index - 1,
            **counts,
        }
        if not sealed:
            summary.update({"header_cells": [asdict(cell) for cell in header.cells],
                            "pre_header_rows": [asdict(row)
                                                for row in table.rows[:header_index]],
                            "columns": columns, "parser_issues": table.issues})
        census.append(summary)
    return {
        "status": "inventoried" if census else "rejected_no_arrival_table",
        "tables_in_page": len(tables), "arrival_tables": census,
        "rows": records, "links": links,
    }


def _verified_source(contract: SourceContract, root: Path) -> tuple[str, str]:
    root = root.resolve()
    path = root / contract.local_path
    checksum = path.with_name(f"{path.name}.sha256")
    if not all(item.resolve().is_relative_to(root) for item in (path, checksum)):
        raise ArchiveError(f"source path outside root: {contract.source_id}")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if checksum.read_text(encoding="utf-8").strip() != digest:
        raise ArchiveError(f"checksum mismatch: {contract.source_id}")
    source = payload.decode("utf-8")
    if not source.lstrip().startswith(contract.expected_prefix):
        raise ArchiveError(f"content prefix mismatch: {contract.source_id}")
    return source, digest


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False, sort_keys=True)
                             if isinstance(row[key], (dict, list)) else row[key]
                             for key in columns})


def inventory(config: Path, root: Path, output: Path) -> dict[str, int]:
    """Verify exact contracted snapshots and write a new offline census directory."""
    if output.exists():
        raise FileExistsError(f"refusing to replace inventory directory: {output}")
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    events = document.get("events")
    if not isinstance(events, dict) or not events:
        raise ArchiveError("config must contain nonempty [events.slug] tables")
    contracts = {item.source_id: item for item in load_contracts(config)}
    census: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for slug, raw_event in sorted(cast(dict[str, Any], events).items()):
        if not isinstance(raw_event, dict):
            raise ArchiveError(f"event {slug} must be a table")
        event = cast(dict[str, Any], raw_event)
        for key in ("event_id", "archive_source_id", "role", "archive_url"):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ArchiveError(f"event {slug} requires nonblank {key}")
        role = event["role"]
        if role not in {"development", "sealed_evaluation"}:
            raise ArchiveError(f"event {slug} has unsupported role")
        source_id = event["archive_source_id"]
        if source_id in seen_sources or source_id not in contracts:
            raise ArchiveError(f"event {slug} has duplicate or absent archive_source_id")
        seen_sources.add(source_id)
        contract = contracts[source_id]
        if (contract.availability != "approved" or contract.url != event["archive_url"]
                or "html" not in contract.format.lower()
                or link_status(contract.url, contract.url)[0] != "safe_archive_link"):
            raise ArchiveError(f"event {slug} archive contract does not match")
        source, digest = _verified_source(contract, root)
        result = parse_archive(source, contract.url, sealed=role == "sealed_evaluation")
        identity = {"event_slug": slug, "event_id": event["event_id"],
                    "source_id": source_id, "role": role}
        census.append({**identity, "sha256": digest, "archive_url": contract.url,
                       "status": result["status"], "tables_in_page": result["tables_in_page"],
                       "arrival_tables": result["arrival_tables"]})
        rows.extend({**identity, **row} for row in result["rows"])
        links.extend({**identity, **link} for link in result["links"])
    output.mkdir(parents=True, exist_ok=False)
    for name, values in (("census", census), ("rows", rows), ("links", links)):
        (output / f"{name}.json").write_text(
            json.dumps(values, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    identity_columns = ["event_slug", "event_id", "source_id", "role"]
    _write_csv(output / "census.csv", census, identity_columns + [
        "sha256", "archive_url", "status", "tables_in_page", "arrival_tables"])
    _write_csv(output / "rows.csv", rows, identity_columns + [
        "table_index", "row_index", "status", "fields", "cell_states", "cells", "raw_html"])
    _write_csv(output / "links.csv", links, identity_columns + [
        "table_index", "row_index", "location_text", "href", "start_tag", "link_text",
        "resolved_url", "status", "link_code", "link_sensor", "link_day", "link_year",
        "link_identity_status"])
    return {"events": len(census), "development_rows": len(rows), "development_links": len(links)}
