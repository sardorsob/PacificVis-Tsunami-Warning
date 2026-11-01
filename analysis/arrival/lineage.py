"""Retain reference statements separately from primary catalog measurements."""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, cast

from analysis.arrival.evidence import (
    Row,
    checked_path,
    development_reports,
    file_manifest,
    read_rows,
    require_development,
    sha256,
    verify_inputs,
    verify_product,
    write_json,
    write_rows,
)

PILOT_CONFIG_SHA = "debbc63ed0bc68ad6001f9c757fa7656e266e565d7024f6789af7463d83c657c"


def stable_id(kind: str, *keys: str) -> str:
    """IDs depend on source identity, never reported arrival agreement."""
    return kind + ":" + hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:24]


def relation(evidence: Row) -> str:
    """Only explicit ancestry evidence supports a dependence classification."""
    if evidence.get("documented_copy") == "True":
        return "copied"
    if evidence.get("shared_waveform", "unknown") not in {"", "unknown"}:
        return "possibly-dependent"
    return "unknown"


def validate_members(rows: list[Row], expected: set[str]) -> None:
    ids = [row["source_record_id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("source record conservation failure")


def attribution_segments(text: str) -> list[Row]:
    """Extract cited clauses, retaining exact statement text and local reference."""
    result: list[Row] = []
    previous = 0
    for index, match in enumerate(re.finditer(r"\(reference #(\d+)\)", text)):
        clause = html.unescape(re.sub(r"<[^>]*>", " ", text[previous : match.end()])).strip()
        result.append(
            {
                "native_reference_id": match[1],
                "statement_index": str(index),
                "evidence_text": clause,
                "provenance_scope": "arrival_statement"
                if "arrival time" in clause.lower()
                else "amplitude_only",
            }
        )
        previous = match.end()
    return result


def load_pilot(root: Path, receipts: Path) -> list[dict[str, Any]]:
    """Check exact frozen contracts and every retained response before JSON parsing."""
    import tomllib

    config = root / "config/arrival-completion-pilot-v1.toml"
    if sha256(config) != PILOT_CONFIG_SHA:
        raise ValueError("pilot config changed")
    assets = tomllib.loads(config.read_text())["assets"]
    rows = cast(list[dict[str, Any]], json.loads((receipts / "outputs.json").read_text()))
    if {r["source_id"] for r in rows} != set(assets) or len(rows) != len(assets):
        raise ValueError("pilot receipt does not conserve contracts")
    for row in rows:
        asset = assets[row["source_id"]]
        if (
            row["status"] != "downloaded"
            or row["local_path"] != asset["local_path"]
            or row["final_url"] != asset["url"]
            or sha256(checked_path(root, row["local_path"])) != row["sha256"]
        ):
            raise ValueError("pilot raw/contract mismatch")
    return rows


def build_lineage(inputs: Path, sites: Path, receipts: Path, output: Path) -> Path:
    document = verify_inputs(inputs)
    verify_product(sites, required_files=("site_links.csv.gz",), inputs_sha256=sha256(inputs))
    if output.exists():
        raise ValueError("output already exists")
    root = Path(document["root"])
    pilot = load_pilot(root, receipts)
    ntwc = development_reports(document)
    ncei = read_rows(root / document["ncei"] / "observations.csv.gz")
    require_development(ncei, document["events"], "development_event_id")
    links = read_rows(sites / "site_links.csv.gz")
    validate_members(links, {r["report_id"] for r in ntwc} | {r["source_record_id"] for r in ncei})
    members: list[Row] = []
    components: list[Row] = []
    for row in links:
        rid = row["source_record_id"]
        lid = stable_id("lineage-unresolved", rid)
        members.append(
            {
                "source_record_id": rid,
                "lineage_id": lid,
                "member_scope": "primary_source_record",
                "relation": "unknown",
                "independence_established": "False",
                "weighting_approved": "False",
            }
        )
        components.append(
            {
                "lineage_id": lid,
                "original_product_id": "unknown",
                "agency": row["source_family"],
                "method_picker": "unknown",
                "waveform_ancestry": "unknown",
                "processing_ancestry": "unknown",
                "interpretation": "singleton is an unresolved ancestry placeholder",
                "rule_version": "documented_ancestry_v1",
            }
        )
    by_runup = {r["ncei_runup_id"]: r for r in ncei}
    associations: list[Row] = []
    statements: list[Row] = []
    resolved: set[str] = set()
    pins: list[Row] = []
    for receipt in pilot:
        pins.append({"path": receipt["local_path"], "sha256": receipt["sha256"]})
        if not receipt["source_id"].startswith("arrival-pilot-references-"):
            continue
        runup = receipt["source_id"].rsplit("-", 1)[1]
        source = by_runup[runup]
        refpath = root / receipt["local_path"]
        refs = json.loads(refpath.read_text())
        if refs["page"] != 1 or refs["totalPages"] != 1 or len(refs["items"]) != refs["totalItems"]:
            raise ValueError("incomplete reference collection")
        ir = next(r for r in pilot if r["source_id"] == "arrival-pilot-info-" + runup)
        info = json.loads((root / ir["local_path"]).read_text())
        if str(info["id"]) != runup or str(info["tsunamiEventId"]) != source["ncei_event_id"]:
            raise ValueError("info identity mismatch")
        segments = attribution_segments(info.get("comments", ""))
        for segment in segments:
            ref = next(
                (r for r in refs["items"] if str(r["id"]) == segment["native_reference_id"]), None
            )
            if ref is None:
                raise ValueError("statement reference absent from complete collection")
            sid = stable_id("statement", source["source_record_id"], segment["statement_index"])
            statements.append(
                {
                    **segment,
                    "statement_id": sid,
                    "source_record_id": source["source_record_id"],
                    "event_id": source["development_event_id"],
                    "agency": ref.get("author", "unknown"),
                    "original_product_id": "ncei-reference:" + str(ref["id"]),
                    "evidence_path": ir["local_path"],
                    "evidence_sha256": ir["sha256"],
                    "evidence_locator": "comments/reference#" + str(ref["id"]),
                    "relation_to_primary_catalog_pick": "unknown",
                }
            )
            if segment["provenance_scope"] == "arrival_statement":
                resolved.add(runup)
        for ref in refs["items"]:
            segment = next(
                (s for s in segments if s["native_reference_id"] == str(ref["id"])), Row()
            )
            associations.append(
                {
                    "source_record_id": source["source_record_id"],
                    "native_runup_id": runup,
                    "native_event_id": source["ncei_event_id"],
                    "native_reference_id": str(ref["id"]),
                    "native_reference_json": json.dumps(ref, sort_keys=True),
                    "reference_path": receipt["local_path"],
                    "reference_sha256": receipt["sha256"],
                    "info_path": ir["local_path"],
                    "info_sha256": ir["sha256"],
                    "resolution_class": "accessible_derivative" if segment else "unknown",
                    "original_access_state": "not_requested",
                    "relation": "unknown",
                    "provenance_scope": segment.get("provenance_scope", "record_reference_only"),
                    "rule_version": "documented_ancestry_v1",
                    "reason": "catalog attribution does not prove independent picking",
                }
            )
    for name, rows in [
        ("lineage", components),
        ("lineage_members", members),
        ("references", associations),
        ("statements", statements),
    ]:
        write_rows(output / (name + ".csv.gz"), rows)
    write_json(
        output / "summary.json",
        {
            "source_records": len(members),
            "attempted_distinct_records": 8,
            "references": len(associations),
            "arrival_lineage_records": len(resolved),
            "arrival_lineage_yield": len(resolved) / 8,
            "route_expansion": "stopped_below_50_percent",
            "independent_picks_established": 0,
            "primary_measurements_collapsed": 0,
            "limitation": "2/8 catalog arrival attribution, not full original-product resolution",
        },
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": "arrival_lineage_v1",
            "inputs_sha256": sha256(inputs),
            "sites_sha256": sha256(sites / "manifest.json"),
            "pilot_files": sorted(pins, key=lambda r: r["path"]),
            "receipt_sha256": sha256(receipts / "outputs.json"),
            "files": file_manifest(output),
        },
    )
    return output / "manifest.json"
