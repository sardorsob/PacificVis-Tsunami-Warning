"""Inventory frozen development evidence without recovering or promoting labels.

Run from the repository root with ``.venv/bin/python -m
scripts.inventory_arrival_recovery``. All outputs are deterministic, local and
hash-bound. Raw strings remain in the frozen corpus; this ledger records their
locators, shapes and digests rather than reproducing source excerpts.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

BASE = Path("artifacts/generated/ntwc-batch")
CENSUS = BASE / "census-v4"
CROSSWALK = BASE / "crosswalk-reviewed-v3"
CORPUS = Path("data/processed/arrival-corpus/foundation-v4")
WAVES = Path("data/processed/arrival-waveforms/foundation-v4")
SELECTION = BASE / "screen-v1/selection-v2.json"
PROVENANCE = Path("artifacts/provenance/paper-source-manifest.csv")
DEFAULT_OUTPUT = BASE / "recovery-inventory-v1"
ABSENCE = {"-", "--", "n/a", "na", "none", "unknown", "no eta"}
DATE_STATES = {"date_ambiguous", "calendar_context_missing", "day_semantics_unverified"}
NORMALIZED = "normalized_source_samples"
UNPARSED = "retained_unparsed_source"


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _path(root: Path, name: str | Path) -> Path:
    candidate = root / name
    if Path(name).is_absolute() or not candidate.resolve().is_relative_to(root):
        raise ValueError(f"input path escapes repository: {name}")
    return candidate


def _pin(root: Path, name: str | Path, hashes: dict[str, str], expected: str = "") -> Path:
    path = _path(root, name)
    digest = _sha(path)
    if expected and digest != expected:
        raise ValueError(f"input checksum mismatch: {name}")
    key = Path(name).as_posix()
    if key in hashes and hashes[key] != digest:
        raise ValueError(f"input changed during inventory: {name}")
    hashes[key] = digest
    return path


def _document(root: Path, name: Path, hashes: dict[str, str]) -> dict[str, Any]:
    value = json.loads(_pin(root, name, hashes).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {name}")
    return cast(dict[str, Any], value)


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"expected object list: {label}")
    if not all(isinstance(item, dict) for item in cast(list[Any], value)):
        raise ValueError(f"expected object list: {label}")
    return cast(list[dict[str, Any]], value)


def _records(root: Path, name: Path, hashes: dict[str, str]) -> list[dict[str, Any]]:
    return _objects(json.loads(_pin(root, name, hashes).read_text(encoding="utf-8")), str(name))


def _csv(path: Path) -> list[dict[str, str]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise ValueError(f"missing or duplicate {key}: {label}")
        result[value] = row
    return result


def _source_ids(raw: str) -> list[str]:
    ids = json.loads(raw)
    if not isinstance(ids, list):
        raise ValueError("crosswalk source_ids must be a JSON string list")
    if not all(isinstance(s, str) and s for s in cast(list[Any], ids)):
        raise ValueError("crosswalk source_ids must be a JSON string list")
    return cast(list[str], ids)


def _presence(raw: str) -> str:
    token = " ".join(raw.replace("\xa0", " ").split()).casefold()
    if not token:
        return "blank"
    if token in ABSENCE or re.fullmatch(
        r"\(?\?+\)?(?:\s*(?:\((?:jd\s*)?\d{1,3}\)|"
        r"\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?))?", token
    ):
        return "explicit_absence_token"
    return "source_entry_present"


def _token_tags(raw: str) -> list[str]:
    """Classify syntax for sampling; no tag assigns a clock, date or uncertainty."""
    tags: set[str] = set()
    if _presence(raw) != "source_entry_present":
        return [_presence(raw)]
    if re.search(r"\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?", raw):
        tags.add("explicit_month_day_syntax")
    if re.search(r"\((?:JD\s*)?\d{1,3}\)", raw, re.I):
        tags.add("parenthesized_day_syntax")
    if re.fullmatch(r"\s*(?:\d{4}|\d{1,2}:\d{2})\s*", raw):
        tags.add("bare_clock_syntax")
    if re.search(r"[?~≈]|approx", raw, re.I):
        tags.add("qualifier_syntax")
    if "*" in raw or re.search(r"\d\)\s*-$", raw):
        tags.add("footnote_syntax")
    if re.search(r"\b(?:0000|2359|2400)\b|\((?:JD\s*)?(?:0*1|365|366)\)", raw, re.I):
        tags.add("boundary_syntax")
    return sorted(tags or {"other_source_text"})


def _time_gap(report: dict[str, Any], estimate: str, observed: str) -> str:
    if report["structural_status"] != "accepted_source_row":
        return "structural_review"
    if (_presence(estimate) != "source_entry_present"
            or _presence(observed) != "source_entry_present"):
        return "source_time_absent"
    if report["disposition"] == "exact_reported_pair":
        return "currently_resolved_pair"
    if report["header_family"].startswith("arrival_eta_"):
        return "legacy_semantics_review"
    states = {report["estimate_state"], report["observed_state"]}
    if states <= DATE_STATES | {"exact_reported_timestamp"} and states & DATE_STATES:
        return "date_context_review"
    if "qualified_value" in states:
        return "qualified_time_review"
    return "format_or_footnote_review"


def _waveform_tags(path: Path, source: dict[str, Any]) -> list[str]:
    """Describe retained unsupported syntax without interpreting numerical clocks."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = [next(handle, "") for _ in range(8)]
    sample = "\n".join(lines).casefold()
    tags: list[str] = []
    if "header date conflicts" in source.get("parse_reason", ""):
        tags.append("header_record_date_conflict")
    if "before/after event time" in sample and "detided" in sample:
        tags.append("event_relative_provider_detided_header")
    if re.search(r"radar\s+cm\s+utc\s+sec", sample):
        tags.append("radar_cm_utc_sec_header")
    if re.search(r"1\+\s+min", sample):
        tags.append("irregular_cadence_header")
    if "epochal" in sample and "sampletime" in sample:
        tags.append("redundant_epoch_compact_clock_header")
    first = lines[0].split()
    if len(first) == 2 and all(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t) for t in first):
        tags.append("headerless_two_numeric_columns")
        if "." in first[0] and "." in first[1]:
            tags.append("decimal_first_column_clock_unresolved")
        elif re.fullmatch(r"\d{12}", first[1]):
            tags.append("encoded_integer_second_column_clock_unresolved")
    return sorted(tags or ["unrecognized_waveform_shape"])


def _reviewed(row: dict[str, Any]) -> bool:
    return (row.get("event_site_identity_verified") == "True"
            and row.get("review_status") == "independently_reviewed"
            and row.get("physical_site_id", "unknown") != "unknown")


def _write_tables(stage: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (stage / f"{name}.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if rows:
        with (stage / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: _json(v) if isinstance(v, (dict, list)) else v
                              for k, v in row.items()} for row in rows)


def inventory_recovery(root: Path, output: Path) -> dict[str, Any]:
    """Publish a new, hash-bound inventory of development evidence only.

    Raises:
        ValueError: Input hashes, event roles, record conservation or paths disagree.
        FileExistsError: The output already exists; frozen products are never replaced.
    """
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(output)
    hashes: dict[str, str] = {}
    selection = _document(root, SELECTION, hashes)
    selected = _unique(_objects(selection.get("events"), "selection"), "event_id", "selection")
    development = {event for event, row in selected.items() if row.get("role") == "development"}

    def guard(event: str, role: str = "development") -> None:
        if event not in development or role != "development":
            raise ValueError(f"non-development evidence prohibited: {event}")

    provenance = _unique(cast(list[dict[str, Any]], _csv(_pin(root, PROVENANCE, hashes))),
                         "source_id", "provenance")
    census = _records(root, CENSUS / "census.json", hashes)
    pages: dict[str, dict[str, Any]] = {}
    for page in census:
        if page.get("role") == "sealed_evaluation":
            if selected.get(page["event_id"], {}).get("role") != "sealed_evaluation":
                raise ValueError("census/selection role mismatch")
            continue  # Metadata only: never read this page or its arrival cells.
        guard(page["event_id"], page["role"])
        if page["event_id"] in pages:
            raise ValueError("duplicate development census event")
        source = provenance[page["source_id"]]
        if source["sha256"] != page["sha256"]:
            raise ValueError("page/provenance checksum mismatch")
        _pin(root, source["local_path"], hashes, page["sha256"])
        pages[page["event_id"]] = page
    if set(pages) != development:
        raise ValueError("development census does not conserve selection")
    rows = _records(root, CENSUS / "rows.json", hashes)
    raw_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        guard(row["event_id"], row["role"])
        rid = f"{row['event_id']}:{row['table_index']}:{row['row_index']}"
        if rid in raw_rows or row["source_id"] != pages[row["event_id"]]["source_id"]:
            raise ValueError("duplicate row ID or inconsistent source")
        raw_rows[rid] = row
    # Pin accepted discovery links; inventory raw-row links independently.
    for link in _records(root, CENSUS / "links.json", hashes):
        guard(link["event_id"], link["role"])
    corpus = _document(root, CORPUS / "summary.json", hashes)
    for key, name in (("rows", CENSUS / "rows.json"), ("census", CENSUS / "census.json"),
                      ("crosswalk", CROSSWALK / "unique_report_crosswalk.csv")):
        if key in corpus["input_sha256"]:
            _pin(root, name, hashes, corpus["input_sha256"][key])
    reports: dict[str, dict[str, Any]] = {}
    for event in sorted(development):
        name = Path(event) / "arrival_report.csv.gz"
        digest = corpus["output_sha256"].get(name.as_posix())
        if not isinstance(digest, str):
            raise ValueError("corpus report is absent from frozen output manifest")
        path = _pin(root, CORPUS / name, hashes, digest)
        for report in _csv(path):
            guard(report["event_id"])
            rid = report["report_id"]
            if (rid in reports or report["event_id"] != event or rid not in raw_rows
                    or report["source_id"] != pages[event]["source_id"]
                    or report["source_sha256"] != pages[event]["sha256"]
                    or json.loads(report["raw_row_json"]) != raw_rows[rid]):
                raise ValueError("corpus source/row conservation failure")
            reports[rid] = report
    if set(reports) != set(raw_rows) or len(reports) != corpus["source_rows"]:
        raise ValueError("report ID conservation failed")
    unique = _unique(cast(list[dict[str, Any]], _csv(_pin(
        root, CROSSWALK / "unique_report_crosswalk.csv", hashes))), "report_id", "crosswalk")
    alternatives = cast(list[dict[str, Any]], _csv(
        _pin(root, CROSSWALK / "event_site.csv", hashes)))
    if set(unique) != set(reports):
        raise ValueError("crosswalk report conservation failed")
    by_report: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in [*unique.values(), *alternatives]:
        guard(row["event_id"], row["role"])
        if (row["report_id"] not in reports
                or row["event_id"] != reports[row["report_id"]]["event_id"]):
            raise ValueError("crosswalk event/report mismatch")
        _source_ids(row["source_ids"])
    for row in alternatives:
        by_report[row["report_id"]].append(row)
    if set(by_report) != set(reports):
        raise ValueError("crosswalk alternative conservation failed")

    wave_manifest = _document(root, WAVES / "manifest.json", hashes)
    for name, digest in sorted(wave_manifest["input_sha256"].items()):
        _pin(root, name, hashes, digest)
    wave_sources = _unique(
        _objects(wave_manifest["sources"], "waveforms"), "source_id", "waveforms")
    assets: list[dict[str, Any]] = []
    asset_map: dict[str, dict[str, Any]] = {}
    skipped_scope = 0
    for sid, source in sorted(wave_sources.items()):
        if source["processing_status"] == "outside_observation_scope":
            skipped_scope += 1
            continue
        event = source.get("event_id", "unknown")
        guard(event)
        raw_path, digest = source["raw_path"], source.get("source_sha256", "unknown")
        _path(root, raw_path)  # Validate even an intentionally absent path.
        state = source["processing_status"]
        capture = "no_retained_body"
        tags: list[str] = []
        if digest != "unknown":
            path = _pin(root, raw_path, hashes, digest)
            entry = provenance.get(sid)
            if entry is None or entry["local_path"] != raw_path or entry["sha256"] != digest:
                raise ValueError("waveform/provenance mismatch")
            capture = "retained_body_hash_verified"
            if state == UNPARSED:
                tags = _waveform_tags(path, source)
            if state == NORMALIZED:
                _pin(root, WAVES / source["output_path"], hashes, source["output_sha256"])
        elif state != "unavailable":
            raise ValueError("captured waveform lacks a source hash")
        if "cdx_evidence_path" in source:
            _pin(root, source["cdx_evidence_path"], hashes, source["cdx_evidence_sha256"])
        asset = dict(
            source_id=sid, event_id=event, role="development", purpose=source["purpose"],
            acquisition_status=source.get("acquisition_status", "unknown"), capture_state=capture,
            processing_status=state, parse_reason=source.get("parse_reason", "not applicable"),
            waveform_syntax_tags=tags, raw_path=raw_path, source_sha256=digest,
            source_bytes=source.get("source_bytes", "unknown"),
            source_line_count=source.get("source_line_count", "unknown"),
            source_rows=source["source_rows"], source_url=source["source_url"],
            provider=source.get("provider", "unknown"),
            provider_station_id=source.get("provider_station_id", "unknown"),
            sensor=source.get("sensor", "unknown"), units=source.get("units", "unknown"),
            processing_level=source.get("source_metadata", {}).get("processing", "unknown"),
            output_path=source.get("output_path", "unknown"),
        )
        assets.append(asset)
        asset_map[sid] = asset

    provider_assets: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for asset in assets:
        if asset["provider"] != "unknown" and asset["provider_station_id"] != "unknown":
            provider_key = (asset["event_id"], asset["provider"], asset["provider_station_id"])
            provider_assets[provider_key].append(asset["source_id"])
    joins: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    sampled: set[tuple[str, str]] = set()

    def representative(kind: str, rid: str, rule: str, locator: str, digest: str) -> None:
        cases.append(dict(record_kind=kind, record_id=rid, rule=rule, locator=locator,
                          evidence_sha256=digest, interpretation="syntax_inventory_only"))

    for rid, report in sorted(reports.items()):
        row = raw_rows[rid]
        event = report["event_id"]
        identity = unique[rid]
        approved = _reviewed(identity)
        legacy = report["header_family"].startswith("arrival_eta_")
        estimate = report["legacy_eta_raw"] if legacy else report["estimated_raw"]
        observed = report["legacy_arrival_raw"] if legacy else report["observed_raw"]
        tags = sorted(set(_token_tags(estimate) + _token_tags(observed)))
        gap = _time_gap(report, estimate, observed)
        report_assets: set[str] = set()
        for index, alternative in enumerate(sorted(by_report[rid], key=_json)):
            joinable = approved and _reviewed(alternative)
            candidates: dict[str, set[str]] = defaultdict(set)
            if joinable:
                for sid in _source_ids(alternative["source_ids"]):
                    if sid in asset_map:
                        if asset_map[sid]["event_id"] != event:
                            raise ValueError("reviewed identity points at another event's waveform")
                        candidates[sid].add("reviewed_source_id")
                provider_key = (event, alternative["provider"], alternative["provider_station_id"])
                for sid in provider_assets.get(provider_key, []):
                    candidates[sid].add("reviewed_provider_station_id")
            candidates = {sid: basis for sid, basis in candidates.items()
                          if asset_map[sid]["purpose"] == "event_window"}
            if not candidates:
                candidates = {"unknown": {"no_reviewed_mapping" if not joinable else
                                          "no_existing_event_window_asset"}}
            for sid, basis in sorted(candidates.items()):
                asset = asset_map.get(sid, {})
                if sid != "unknown":
                    report_assets.add(sid)
                joins.append(dict(
                    report_id=rid, event_id=event, alternative_index=index,
                    physical_site_id=alternative["physical_site_id"],
                    link_code=alternative.get("link_code", "unknown"),
                    link_sensor=alternative.get("link_sensor", "unknown"), source_id=sid,
                    join_basis=sorted(basis),
                    join_scope="event_geographic_site_only" if sid != "unknown" else "unresolved",
                    identity_evidence_sha256=alternative["identity_evidence_sha256"],
                    processing_status=asset.get("processing_status", "unknown"),
                    sensor=asset.get("sensor", "unknown"),
                    deployment_continuity_verified=False, physical_onset_validated=False,
                ))
        locator = (CORPUS / event / "arrival_report.csv.gz").as_posix() + f"#report_id={rid}"
        source_hash = report["source_sha256"]
        raw_hash = _digest(row)
        ledger.append(dict(
            report_id=rid, event_id=event, role="development", source_id=report["source_id"],
            source_sha256=source_hash, source_path=provenance[report["source_id"]]["local_path"],
            source_row_sha256=raw_hash, source_locator=locator,
            table_index=report["table_index"], row_index=report["row_index"],
            structural_status=report["structural_status"], header_family=report["header_family"],
            estimate_presence=_presence(estimate), observed_presence=_presence(observed),
            legacy_column_semantics="unreviewed" if legacy else "modern_source_columns",
            estimate_state=report["estimate_state"], observed_state=report["observed_state"],
            estimated_token_sha256=hashlib.sha256(estimate.encode("utf-8")).hexdigest(),
            observed_token_sha256=hashlib.sha256(observed.encode("utf-8")).hexdigest(),
            syntax_tags=tags, time_gap=gap, identity_tier=identity["identity_tier"],
            identity_gap="reviewed_geography_only" if approved else "identity_review_required",
            physical_site_id=identity["physical_site_id"],
            attribution_status=selected[event].get("attribution_status", "unknown"),
            reviewed_existing_asset_count=len(report_assets),
            normalized_event_asset_count=sum(asset_map[s]["processing_status"] == NORMALIZED
                                             for s in report_assets),
            unparsed_event_asset_count=sum(asset_map[s]["processing_status"] == UNPARSED
                                           for s in report_assets),
            acquired_mapping_status="reviewed_existing_assets" if report_assets else
                                    "no_reviewed_existing_asset_mapping",
        ))
        for cell_index, cell in enumerate(_objects(row["cells"], "row cells")):
            for link_index, link in enumerate(_objects(cell.get("links", []), "cell links")):
                links.append(dict(
                    report_id=rid, event_id=event, structural_status=report["structural_status"],
                    cell_index=cell_index, link_index=link_index, href=link["href"],
                    resolved_url=urljoin(pages[event]["archive_url"], link["href"]),
                    link_text_sha256=hashlib.sha256(
                        link.get("text", "").encode("utf-8")).hexdigest(),
                    source_sha256=source_hash, source_row_sha256=raw_hash,
                    discovery_scope="raw_row_link_only_no_fetch_authorization",
                ))
        sample_groups = [("header", report["header_family"]),
                         ("time_state", f"{report['estimate_state']}|{report['observed_state']}")]
        sample_groups.extend(("time_syntax", tag) for tag in tags)
        for family, value in sample_groups:
            if (family, value) not in sampled:
                representative("report", rid, f"representative_{family}:{value}", locator, raw_hash)
                sampled.add((family, value))
        if gap == "structural_review":
            representative("report", rid, "all_structural_rows", locator, raw_hash)
        for tag in tags:
            if tag in {"qualifier_syntax", "footnote_syntax", "boundary_syntax"}:
                representative("report", rid, f"all_{tag}", locator, raw_hash)
        if gap != "currently_resolved_pair" or not approved:
            priority = {"date_context_review": 10, "format_or_footnote_review": 15,
                        "legacy_semantics_review": 20, "qualified_time_review": 25,
                        "structural_review": 30, "source_time_absent": 40,
                        "currently_resolved_pair": 50}[gap]
            queue.append(dict(
                priority=priority, record_kind="report", record_id=rid, event_id=event,
                evidence_gap=gap, identity_gap=ledger[-1]["identity_gap"],
                attribution_status=ledger[-1]["attribution_status"],
                existing_asset_count=len(report_assets),
                action="review_cached_evidence_before_target_or_acquisition_decision",
                candidate_yield="unknown_not_achieved", achieved_recovered_labels=0,
            ))
    for asset in assets:
        if asset["processing_status"] != UNPARSED:
            continue
        sid = asset["source_id"]
        for tag in asset["waveform_syntax_tags"]:
            representative("asset", sid, f"all_unparsed_waveform_family:{tag}",
                           asset["raw_path"], asset["source_sha256"])
        queue.append(dict(
            priority=15, record_kind="asset", record_id=sid, event_id=asset["event_id"],
            evidence_gap="retained_body_format_review", identity_gap="separate_review_required",
            attribution_status=selected[asset["event_id"]].get("attribution_status", "unknown"),
            existing_asset_count=1, action="review_clock_units_processing_before_adapter",
            candidate_yield="unknown_not_achieved", achieved_recovered_labels=0,
        ))
    queue.sort(key=lambda r: (r["priority"], r["event_id"], r["record_kind"], r["record_id"]))
    cases.sort(key=lambda r: (r["record_kind"], r["record_id"], r["rule"]))
    counts = dict(
        reports=len(ledger), currently_resolved_pairs=sum(
            r["time_gap"] == "currently_resolved_pair" for r in ledger),
        structural_reports=sum(r["structural_status"] != "accepted_source_row" for r in ledger),
        row_link_occurrences=len(links), structural_link_occurrences=sum(
            r["structural_status"] != "accepted_source_row" for r in links),
        assets=len(assets), retained_unparsed_source=sum(
            a["processing_status"] == UNPARSED for a in assets),
        outside_observation_scope_metadata_only=skipped_scope,
        report_waveform_alternatives=len(joins), representative_cases=len(cases),
        gap_queue_entries=len(queue), achieved_recovered_labels=0,
    )
    if counts["currently_resolved_pairs"] != corpus["exact_pairs"]:
        raise ValueError("resolved-pair conservation failed")
    accounting: list[dict[str, Any]] = []
    for axis, values in [
        ("time_gap", [r["time_gap"] for r in ledger]),
        ("identity_gap", [r["identity_gap"] for r in ledger]),
        ("capture_state", [a["capture_state"] for a in assets]),
        ("processing_status", [a["processing_status"] for a in assets]),
        ("header_family", [r["header_family"] for r in ledger]),
        ("waveform_syntax_tag", [t for a in assets for t in a["waveform_syntax_tags"]]),
    ]:
        accounting.extend(dict(axis=axis, value=value, count=count)
                          for value, count in sorted(Counter(values).items()))
    summary: dict[str, Any] = dict(
        schema_version="arrival-recovery-inventory-v1", counts=counts,
        input_sha256=dict(sorted(hashes.items())),
        limitations=[
            "No recovered timestamps, physical arrivals, target approval or model eligibility.",
            "Clock/date syntax tags do not establish calendar semantics or uncertainty bounds.",
            "Reviewed geographic joins do not validate sensor or deployment continuity.",
            "Repeated requests, days, products and alternatives remain separate source assets.",
            "No mapping is different from no acquired data; candidate yield is unknown.",
            "Raw excerpts remain in frozen evidence; fixtures and inventory "
            "use locators and digests.",
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".arrival-recovery-", dir=output.parent))
    try:
        for name, table in (("reports", ledger), ("assets", assets), ("row_links", links),
                            ("report_waveforms", joins), ("representative_cases", cases),
                            ("gap_queue", queue), ("accounting", accounting)):
            _write_tables(stage, name, table)
        (stage / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for name, digest in hashes.items():
            if _sha(_path(root, name)) != digest:
                raise ValueError(f"input changed before publication: {name}")
        manifest = dict(schema_version=summary["schema_version"],
                        input_sha256=summary["input_sha256"],
                        output_sha256={p.name: _sha(p) for p in sorted(stage.iterdir())})
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    print(json.dumps(inventory_recovery(args.root, output)["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
