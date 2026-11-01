"""Conservative, offline station-identity evidence for development archive rows.

Filename codes and present-day name matches are never promoted to historical
physical sites. Exact archived headers remain event-specific evidence.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import re
import tomllib
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit, urlunsplit

from pipeline.acquisition import SourceContract, load_contracts, verify_cdx_evidence
from pipeline.ntwc_archive import arrival_value_flags, link_identity

TIERS = ("header_exact", "registry_exact", "archive_code", "name_only", "ambiguous", "unmatched")
# These bounded aliases occur in the linked NOS headers and archive labels.
# An alias never supplies identity: the exact header ID, link and coordinates do.
NOS_PLACE_ALIASES = {
    # Independently reviewed against pinned coops-historicwl-list-20261031.json
    # (numeric ID, station name/state and coordinates) and exact historic headers.
    # These five IDs use complete labels, preserving explicit regional qualifiers.
    "9462620": {"unalaskaalaska", "unalaskaak", "dutchharborak"},
    "1611400": {"nawiliwilihi", "nawiliwilikauaihi"},
    "1612340": {"honolulu", "honoluluoahu", "honoluluhi", "honoluluhawaii", "honoluluoahuhi"},
    "1617433": {"kawaihaehi"},
    "1615680": {
        "kahului",
        "kahuluimaui",
        "kahuluihi",
        "kahuluihawaii",
        "kahuluimauihi",
        "kahuluimauihawaii",
    },
    "1619910": {"midwayisland", "midwayisusa", "midwayis", "sandislandmidwayis"},
    "1890000": {"wakeisland", "wakeis"},
}
MAX_REGISTRY_DISTANCE_KM = 2.0


class StationError(ValueError):
    """An input violates source identity, checksum or evaluation-role boundaries."""


def _name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold().replace("_", " "))


def _place(value: str) -> str:
    return _name(value.split(",", 1)[0])


def _label_agrees(label: str, header: dict[str, Any]) -> bool:
    reported, named = _place(label), _place(str(header["header_name"]))
    if reported in {"", "unknown", "none", "na", "station", "gauge", "site"}:
        return False
    station_id = str(header["header_station_id"])
    aliases = NOS_PLACE_ALIASES.get(station_id, set())
    if header["provider"] in {"NOS", "NOAA", "CO-OPS"} and station_id in {
        "9462620",
        "1611400",
        "1612340",
        "1617433",
        "1615680",
    }:
        return {_name(label), _name(str(header["header_name"]))} <= aliases
    if reported == named:
        return True
    return header["provider"] in {"NOS", "NOAA", "CO-OPS"} and {reported, named} <= aliases


def _distance_km(left: dict[str, Any], right: dict[str, Any]) -> float:
    try:
        a, b = (math.radians(float(left[key])) for key in ("latitude", "longitude"))
        c, d = (math.radians(float(right[key])) for key in ("latitude", "longitude"))
    except (TypeError, ValueError):
        return math.inf
    if not all(math.isfinite(x) for x in (a, b, c, d)) or abs(c) > math.pi / 2 or abs(d) > math.pi:
        return math.inf
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _header_identity(
    matches: list[dict[str, Any]], label: str, registries: list[dict[str, Any]]
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]]]:
    """Separate historical header identity from a current registry plausibility check."""
    if not all(_label_agrees(label, header) for header in matches):
        return "ambiguous", "report_header_label_conflict", {}, []
    signatures = {json.dumps(geographic_signature(h), sort_keys=True) for h in matches}
    if len(signatures) != 1:
        return "ambiguous", "header_identity_conflict", {}, []
    header = matches[0]
    if header["provider"] not in {"NOS", "NOAA", "CO-OPS"} or not re.fullmatch(
        r"\d{7}", str(header["header_station_id"])
    ):
        if not all(_name(label) == _name(str(h["header_name"])) for h in matches):
            return "ambiguous", "report_header_qualified_label_conflict", {}, []
        return "header_exact", "event_header_without_provider_site_id", header, []
    exact = [
        station
        for station in registries
        if station["provider"] == "CO-OPS"
        and station["station_id"] == str(header["header_station_id"])
    ]
    if not exact:
        if not all(_name(label) == _name(str(h["header_name"])) for h in matches):
            return "ambiguous", "report_header_qualified_label_conflict", {}, []
        return "header_exact", "header_provider_id_needs_registry_check", header, []
    if any(_distance_km(header, station) > MAX_REGISTRY_DISTANCE_KM for station in exact):
        return "ambiguous", "header_registry_coordinate_conflict", {}, exact
    return "header_exact", "linked_header_provider_id_and_coordinates", header, exact


def geographic_signature(header: dict[str, Any]) -> dict[str, Any]:
    """Exact source-qualified location signature; sensors and dates are not sites."""
    return {
        "provider": header["provider"],
        "archive_code": header["link_code"],
        "header_name": _name(str(header["header_name"])),
        "header_station_id_state": str(header["header_station_id"]),
        "latitude": header["latitude"],
        "longitude": header["longitude"],
        "coordinate_crs": "unknown",
    }


def geographic_site_id(header: dict[str, Any]) -> str:
    payload = json.dumps(geographic_signature(header), sort_keys=True, separators=(",", ":"))
    return "ntwc-header-site:" + hashlib.sha256(payload.encode()).hexdigest()


def validate_reviewed_site_evidence(row: dict[str, Any]) -> None:
    """Validate a reviewed adapter row; raise StationError, return None on success.

    This verifies the digest-bound geographic claim, never deployment continuity
    or measurement interchangeability. Source files remain verified by the builder.
    """
    if (
        row.get("review_status") != "independently_reviewed"
        or str(row.get("event_site_identity_verified")).casefold() != "true"
        or row.get("identity_tier") not in {"header_exact", "registry_exact"}
        or row.get("role", "development") != "development"
    ):
        raise StationError("reviewed identity lacks verified development site")
    evidence = str(row.get("evidence", ""))
    if hashlib.sha256(evidence.encode()).hexdigest() != row.get("identity_evidence_sha256"):
        raise StationError("reviewed site evidence digest mismatch")
    alternatives = json.loads(evidence)
    if not isinstance(alternatives, list) or not alternatives:
        raise StationError("reviewed site evidence requires alternatives")
    scope = row.get("identity_scope", "authoritative_provider_site")
    eid, report, site = str(row["event_id"]), str(row["report_id"]), str(row["physical_site_id"])
    if not report.startswith(eid + ":"):
        raise StationError("reviewed report/event mismatch")
    source_ids: set[str] = set()
    for alternative in cast(list[dict[str, Any]], alternatives):
        if any(
            alternative.get(key) != row[key]
            for key in ("event_id", "report_id", "physical_site_id")
        ):
            raise StationError("reviewed site fields disagree with bound evidence")
        if alternative.get("identity_scope", "authoritative_provider_site") != scope:
            raise StationError("reviewed site scope disagrees with bound evidence")
        if "identity_basis" in row and alternative.get("identity_basis") != row["identity_basis"]:
            raise StationError("reviewed site basis disagrees with bound evidence")
        headers = alternative.get("headers", [])
        if not headers:
            raise StationError("reviewed site has no linked header")
        registry = alternative.get("registry_id_checks", [])
        tier, _, matched, checked = _header_identity(headers, alternative["report_label"], registry)
        if tier != "header_exact" or not matched:
            raise StationError("reviewed site has inconsistent header evidence")
        for header in headers:
            if (
                header.get("link_code") != alternative.get("link_code")
                or header.get("link_sensor") != alternative.get("link_sensor")
                or _original_archive_url(header["source_url"]) != header.get("original_url")
                or not re.fullmatch(r"[0-9a-f]{64}", str(header.get("sha256", "")))
            ):
                raise StationError("reviewed header link or fingerprint mismatch")
            source_ids.add(str(header["source_id"]))
        if scope == "authoritative_provider_site":
            station = str(matched["header_station_id"])
            if (
                not checked
                or not re.fullmatch(r"\d{7}", station)
                or site != f"coops:{station}"
                or row.get("provider") != "CO-OPS"
                or row.get("provider_station_id") != station
            ):
                raise StationError("reviewed provider identity disagrees with header/registry")
        elif scope == "source_qualified_geographic_site":
            station = str(matched["header_station_id"])
            station = (
                "unknown" if station.casefold() in {"none", "unknown", "n/a", "na"} else station
            )
            if (
                site != geographic_site_id(matched)
                or row.get("provider") != matched["provider"]
                or row.get("provider_station_id") != station
                or alternative.get("geographic_signature") != geographic_signature(matched)
            ):
                raise StationError("reviewed geographic signature disagrees with header")
        else:
            raise StationError("unknown reviewed site identity scope")
    if source_ids != set(json.loads(row.get("source_ids", "[]"))):
        raise StationError("reviewed site source IDs disagree with header evidence")


def _records(path: Path) -> list[dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise StationError(f"expected records: {path}")
    return cast(list[dict[str, Any]], records)


def _verified_bytes(contract: SourceContract, root: Path) -> tuple[bytes, str]:
    root = root.resolve()
    path = root / contract.local_path
    sidecar = path.with_name(path.name + ".sha256")
    if not all(item.resolve().is_relative_to(root) for item in (path, sidecar)):
        raise StationError("source path escapes root")
    if contract.expected_cdx_sha1:
        verify_cdx_evidence(contract, root)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sidecar.read_text(encoding="utf-8").strip():
        raise StationError(f"source checksum mismatch: {contract.source_id}")
    if not payload.lstrip().startswith(contract.expected_prefix.encode("utf-8")):
        raise StationError(f"source prefix mismatch: {contract.source_id}")
    if (
        contract.expected_cdx_sha1
        and base64.b32encode(hashlib.sha1(payload, usedforsecurity=False).digest()).decode()
        != contract.expected_cdx_sha1
    ):
        raise StationError(f"source CDX body mismatch: {contract.source_id}")
    return payload, digest


def _original_archive_url(url: str) -> str:
    if urlsplit(url).netloc == "web.archive.org":
        parts = re.split(r"/web/\d+id_/", url, maxsplit=1)
        if len(parts) != 2:
            return "unknown"
        url = parts[1]
    parsed = urlsplit(url)
    if (
        parsed.hostname != "www.tsunami.gov"
        or parsed.netloc != "www.tsunami.gov"
        or parsed.scheme not in {"https", "http"}
        or not parsed.path.startswith("/previous.events/")
    ):
        return "unknown"
    return urlunsplit(("https", "www.tsunami.gov", parsed.path, parsed.query, ""))


def parse_ntwc_header(text: str, filename: str) -> dict[str, str | float]:
    """Read only the documented four-line NTWC ASCII header; reject other shapes."""
    lines = text.splitlines()
    if len(lines) < 4 or lines[0].lstrip().startswith("<"):
        raise StationError("not a four-line NTWC ASCII header")
    identity, measurement = lines[0].split(), lines[1].split()
    if len(identity) != 7 or len(measurement) != 8 or not lines[3].startswith("Data Format:"):
        raise StationError("unknown NTWC header shape")
    date = datetime.strptime(identity[6], "%Y%m%d").date()
    latitude, longitude = float(identity[4]), float(identity[5])
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise StationError("invalid header coordinates")
    tokens = link_identity(filename)
    if tokens["link_code"] == "unknown":
        raise StationError("header filename has no recognized code")
    if tokens["link_year"] not in {"unknown", str(date.year), str(date.year)[-2:]}:
        raise StationError("header date conflicts with filename year")
    if tokens["link_day"] != "unknown" and int(tokens["link_day"]) != date.timetuple().tm_yday:
        raise StationError("header date conflicts with filename day")
    return {
        **tokens,
        "header_name": identity[0],
        "header_station_id": identity[1],
        "provider": identity[2],
        "sampling_mode": identity[3],
        "latitude": latitude,
        "longitude": longitude,
        "header_date": date.isoformat(),
        "measurement_system": measurement[0],
        "units": measurement[1],
        "time_basis": measurement[2],
        "cadence_value": measurement[3],
        "cadence_units": measurement[4],
        "vertical_datum": measurement[5],
        "relay": measurement[6],
        "processing": measurement[7],
        "coordinate_crs": "unknown",
    }


def _load_registries(configs: Sequence[Path], root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for config in configs:
        for contract in load_contracts(config):
            kind = contract.source_class.casefold()
            if contract.availability != "approved" or not (
                "registry" in kind or kind == "station identifier catalog"
            ):
                continue
            raw, digest = _verified_bytes(contract, root)
            payload = json.loads(raw)
            host = urlsplit(contract.url).hostname
            if host == "www.ioc-sealevelmonitoring.org":
                if not isinstance(payload, list):
                    raise StationError("unknown IOC SSC registry schema")
                for station in cast(list[dict[str, Any]], payload):
                    if not station.get("ssc_id") or not station.get("name"):
                        raise StationError("SSC entity missing id or name")
                    identifiers: dict[str, list[str]] = {}
                    for namespace in ("ptwc", "ioc", "uhslc", "psmsl", "gloss"):
                        value = station.get(namespace, [])
                        tokens = cast(list[Any], value) if isinstance(value, list) else [value]
                        if not all(isinstance(token, str) and token for token in tokens):
                            raise StationError("unknown SSC identifier shape")
                        identifiers[namespace] = sorted(set(cast(list[str], tokens)))
                    result.append(
                        {
                            "provider": "IOC-SSC",
                            "station_id": station["ssc_id"],
                            "name": station["name"],
                            "latitude": station.get("geo:lat", "unknown"),
                            "longitude": station.get("geo:lon", "unknown"),
                            "identifiers": identifiers,
                            "modified": station.get("dcterms:modified", "unknown"),
                            "source_id": contract.source_id,
                            "source_url": contract.url,
                            "sha256": digest,
                            "temporal_scope": "identifier_catalog_snapshot",
                        }
                    )
                continue
            if host != "api.tidesandcurrents.noaa.gov":
                raise StationError("unsupported registry source")
            if not isinstance(payload, dict):
                raise StationError("unknown CO-OPS registry schema")
            payload = cast(dict[str, Any], payload)
            stations = payload.get("stations", payload.get("stationList"))
            if not isinstance(stations, list):
                raise StationError("unknown CO-OPS registry schema")
            for station in cast(list[dict[str, Any]], stations):
                if not str(station.get("id", "")) or not station.get("name"):
                    raise StationError("registry station missing id or name")
                result.append(
                    {
                        "provider": "CO-OPS",
                        "station_id": str(station["id"]),
                        "name": station["name"],
                        "latitude": station.get("lat", "unknown"),
                        "longitude": station.get("lng", "unknown"),
                        "details": station.get("details", {}),
                        "source_id": contract.source_id,
                        "source_url": contract.url,
                        "sha256": digest,
                        "temporal_scope": "registry_snapshot",
                    }
                )
    # Multiple source contracts may document the same current provider station.
    return sorted(result, key=lambda row: (row["provider"], row["station_id"], row["source_id"]))


def _load_headers(
    configs: Sequence[Path],
    root: Path,
    allowed_urls: set[str],
    rejected: list[dict[str, Any]],
    receipt_paths: Sequence[Path] = (),
    unavailable: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    contracts = [contract for config in configs for contract in load_contracts(config)]
    contract_ids = {contract.source_id for contract in contracts}
    if len(contract_ids) != len(contracts):
        raise StationError("header contracts have duplicate source IDs")
    receipts = [receipt for path in receipt_paths for receipt in _records(path)]
    outcomes = {receipt["source_id"]: receipt for receipt in receipts}
    pinned_ids = {contract.source_id for contract in contracts if contract.expected_cdx_sha1}
    if len(outcomes) != len(receipts) or not set(outcomes) <= contract_ids:
        raise StationError("header receipts have duplicate or unconfigured source IDs")
    if not pinned_ids <= set(outcomes):
        raise StationError("pinned header contracts require complete final receipts")
    for receipt in receipts:
        if receipt.get("status") not in {
            "downloaded",
            "cached",
            "quarantined",
            "blocked",
            "skipped",
        }:
            raise StationError("header receipt has nonterminal or unknown status")
    for config in configs:
        for contract in load_contracts(config):
            kind = contract.format.casefold()
            if contract.availability != "approved" or "ntwc" not in kind or "ascii" not in kind:
                continue
            original_url = _original_archive_url(contract.url)
            # A mixed contract may contain reserved assets: never read unlinked headers.
            if original_url not in allowed_urls:
                continue
            receipt = outcomes.get(contract.source_id)
            if receipt is not None:
                if receipt.get("local_path") != str(contract.local_path):
                    raise StationError("header receipt path differs from contract")
                if receipt["status"] not in {"downloaded", "cached"}:
                    if unavailable is not None:
                        unavailable.append(
                            {
                                "source_id": contract.source_id,
                                "source_url": contract.url,
                                "original_url": original_url,
                                "status": "acquisition_unavailable",
                                "acquisition_status": receipt["status"],
                                "reason": receipt.get("reason", "unknown"),
                            }
                        )
                    continue
            raw, digest = _verified_bytes(contract, root)
            if receipt is not None and (
                receipt.get("sha256") != digest
                or receipt.get("bytes") != len(raw)
                or (
                    contract.expected_cdx_sha1
                    and receipt.get("verified_cdx_sha1") != contract.expected_cdx_sha1
                )
            ):
                raise StationError("header receipt fingerprint or CDX verification differs")
            try:
                header = parse_ntwc_header(
                    b"\n".join(raw.splitlines()[:4]).decode("utf-8"), contract.local_path.name
                )
            except ValueError as error:
                rejected.append(
                    {
                        "source_id": contract.source_id,
                        "source_url": contract.url,
                        "sha256": digest,
                        "original_url": original_url,
                        "status": "unrecognized_header_format",
                        "reason": str(error),
                    }
                )
                continue
            result.append(
                {
                    **header,
                    "source_id": contract.source_id,
                    "source_url": contract.url,
                    "sha256": digest,
                    "original_url": original_url,
                }
            )
    return result


def _coops_availability(
    config: Path | None, receipts: Path | None, root: Path, events: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], list[str]]:
    if (config is None) != (receipts is None):
        raise StationError("CO-OPS config and receipts must be supplied together")
    available: dict[tuple[str, str], list[str]] = defaultdict(list)
    if config is None or receipts is None:
        return available
    contracts = load_contracts(config)
    records = _records(receipts)
    by_id = {row["source_id"]: row for row in records}
    if len(by_id) != len(records) or set(by_id) != {c.source_id for c in contracts}:
        raise StationError("CO-OPS receipt/contract IDs differ")
    for contract in contracts:
        if contract.source_class != "coastal water-level observation":
            continue
        receipt = by_id[contract.source_id]
        if receipt["status"] not in {"downloaded", "cached"}:
            continue
        event_id = contract.local_path.parent.name
        if event_id not in events or events[event_id]["role"] != "development":
            raise StationError("CO-OPS observation belongs to absent or reserved event")
        if receipt["local_path"] != str(contract.local_path):
            raise StationError("CO-OPS receipt path mismatch")
        raw, digest = _verified_bytes(contract, root)
        if digest != receipt["sha256"] or len(raw) != receipt["bytes"]:
            raise StationError("CO-OPS receipt fingerprint mismatch")
        query = parse_qs(urlsplit(contract.url).query)
        station_id = query["station"][0]
        day = datetime.fromisoformat(events[event_id]["usgs_time"]).date()
        if (
            query.get("begin_date") != [(day - timedelta(days=1)).strftime("%Y%m%d")]
            or query.get("end_date") != [(day + timedelta(days=2)).strftime("%Y%m%d")]
            or query.get("time_zone") != ["gmt"]
        ):
            raise StationError("CO-OPS window does not match event-origin rule")
        payload = json.loads(raw)
        if str(payload.get("metadata", {}).get("id")) != station_id or "data" not in payload:
            raise StationError("CO-OPS observation identity missing or different")
        available[(event_id, station_id)].append(contract.source_id)
    return available


def _components(edges: set[tuple[str, str]]) -> dict[str, Any]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for event, station in edges:
        adjacency[f"event:{event}"].add(f"site:{station}")
        adjacency[f"site:{station}"].add(f"event:{event}")
    remaining = set(adjacency)
    components: list[dict[str, int]] = []
    while remaining:
        stack, visited = [min(remaining)], set[str]()
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adjacency[node] - visited)
        remaining -= visited
        components.append(
            {
                "events": sum(node.startswith("event:") for node in visited),
                "identifiers": sum(node.startswith("site:") for node in visited),
            }
        )
    return {
        "edges": len(edges),
        "components": sorted(components, key=lambda x: (-x["events"], -x["identifiers"])),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], empty_columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else empty_columns)
        writer.writeheader()
        writer.writerows(rows)


def _unique_reports(event_sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse only agreeing documented alternatives; never choose the first match."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_sites:
        grouped[row["report_id"]].append(row)
    result: list[dict[str, Any]] = []
    for report_id, alternatives in sorted(grouped.items()):
        first = alternatives[0]
        sites = {row["physical_site_id"] for row in alternatives}
        verified = len(sites) == 1 and all(
            row["event_site_identity_verified"] for row in alternatives
        )
        evidence = json.dumps([json.loads(row["evidence"]) for row in alternatives], sort_keys=True)
        result.append(
            {
                "event_id": first["event_id"],
                "report_id": report_id,
                "role": "development",
                "identity_tier": (
                    "header_exact"
                    if verified
                    else "ambiguous"
                    if len(alternatives) > 1
                    else first["identity_tier"]
                ),
                "physical_site_id": first["physical_site_id"] if verified else "unknown",
                "identity_scope": first["identity_scope"] if verified else "unknown",
                "identity_basis": first["identity_basis"] if verified else "unknown",
                "provider": first["provider"] if verified else "unknown",
                "provider_station_id": first["provider_station_id"] if verified else "unknown",
                "event_site_identity_verified": verified,
                "deployment_id": "unknown",
                "deployment_continuity_verified": False,
                "source_ids": json.dumps(
                    sorted(
                        {
                            source_id
                            for row in alternatives
                            for source_id in json.loads(row["source_ids"])
                        }
                    )
                ),
                "evidence": evidence,
                "identity_evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
                "alternative_count": len(alternatives),
                "explicit_both_values": first["explicit_both_values"],
                "legacy_both_values": first["legacy_both_values"],
                "review_status": "pending_independent_review",
                "reviewer": "unknown",
                "site_identity_fit_tier": False,
                "fit_eligible": False,
                "model_eligible": False,
                "physical_onset_validated": False,
            }
        )
    return result


def _apply_review(reports: list[dict[str, Any]], path: Path | None) -> None:
    if path is None:
        return
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"event_id", "report_id", "identity_evidence_sha256", "decision", "reviewer"} <= set(
            reader.fieldnames or []
        ):
            raise StationError(
                "identity review requires report, evidence digest, decision and reviewer"
            )
        reviews = list(reader)
    by_report = {row["report_id"]: row for row in reports}
    seen: set[str] = set()
    for review in reviews:
        key = review["report_id"]
        if key not in by_report or key in seen or review["event_id"] != by_report[key]["event_id"]:
            raise StationError("identity review has absent, reserved or duplicate report")
        seen.add(key)
        row = by_report[key]
        if review["identity_evidence_sha256"] != row["identity_evidence_sha256"]:
            raise StationError("identity review evidence fingerprint changed")
        if review["decision"] not in {"approved", "rejected"} or not review["reviewer"].strip():
            raise StationError("unknown identity review decision or reviewer")
        if review["decision"] == "approved" and not row["event_site_identity_verified"]:
            raise StationError("review cannot promote an unresolved event-site identity")
        row["review_status"] = (
            "independently_reviewed" if review["decision"] == "approved" else "rejected"
        )
        row["reviewer"] = review["reviewer"]
        row["site_identity_fit_tier"] = review["decision"] == "approved"


def _identity_delta(reports: list[dict[str, Any]], previous: Path) -> list[dict[str, Any]]:
    with previous.open(encoding="utf-8", newline="") as stream:
        prior = list(csv.DictReader(stream))
    by_id = {row["report_id"]: row for row in prior}
    if len(by_id) != len(prior) or set(by_id) != {row["report_id"] for row in reports}:
        raise StationError("previous crosswalk must contain each report exactly once")
    result: list[dict[str, Any]] = []
    for row in reports:
        old = by_id[row["report_id"]]
        if old["event_id"] != row["event_id"] or old["role"] != "development":
            raise StationError("previous crosswalk has mismatched or reserved report")
        if hashlib.sha256(old["evidence"].encode()).hexdigest() != old["identity_evidence_sha256"]:
            raise StationError("previous crosswalk evidence digest mismatch")
        if old["review_status"] == "independently_reviewed":
            validate_reviewed_site_evidence(old)
        before = old["event_site_identity_verified"].casefold() == "true"
        after = row["event_site_identity_verified"]
        same = old["identity_evidence_sha256"] == row["identity_evidence_sha256"]
        if before and after:
            status = (
                "changed_identity"
                if old["physical_site_id"] != row["physical_site_id"]
                else ("unchanged_identity_evidence" if same else "existing_identity_new_evidence")
            )
        elif after:
            status = "new_identity"
        elif before:
            status = "lost_identity_conflict"
        else:
            status = "unchanged_unresolved" if same else "unresolved_evidence_changed"
        result.append(
            {
                "event_id": row["event_id"],
                "report_id": row["report_id"],
                "change": status,
                "previous_physical_site_id": old["physical_site_id"],
                "current_physical_site_id": row["physical_site_id"],
                "previous_identity_tier": old["identity_tier"],
                "current_identity_tier": row["identity_tier"],
                "previous_review_status": old["review_status"],
                "current_review_status": row["review_status"],
                "previous_evidence_sha256": old["identity_evidence_sha256"],
                "current_evidence_sha256": row["identity_evidence_sha256"],
            }
        )
    return result


def build_crosswalk(
    events_config: Path,
    census_dir: Path,
    root: Path,
    output: Path,
    *,
    registry_configs: Sequence[Path] = (),
    header_configs: Sequence[Path] = (),
    header_receipts: Sequence[Path] = (),
    coops_config: Path | None = None,
    coops_receipts: Path | None = None,
    identity_review: Path | None = None,
    previous_crosswalk: Path | None = None,
) -> dict[str, Any]:
    """Write a provisional event/code/sensor/year crosswalk and evidence pull list."""
    if output.exists():
        raise FileExistsError(f"refusing to replace crosswalk: {output}")
    values = cast(
        dict[str, dict[str, Any]],
        tomllib.loads(events_config.read_text(encoding="utf-8"))["events"],
    )
    events = {event["event_id"]: event for event in values.values()}
    if len(events) != len(values):
        raise StationError("duplicate event IDs")
    rows, links = _records(census_dir / "rows.json"), _records(census_dir / "links.json")
    row_keys = {(row["event_id"], row["table_index"], row["row_index"]) for row in rows}
    if len(row_keys) != len(rows):
        raise StationError("duplicate source row identity")
    for row in rows + links:
        eid = row.get("event_id")
        if (
            eid not in events
            or row.get("role") != "development"
            or events[eid]["role"] != "development"
        ):
            raise StationError("reserved or unknown event values in crosswalk inputs")
        if row.get("source_id") != events[eid]["archive_source_id"]:
            raise StationError("archive source identity mismatch")
    by_row: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for link in links:
        if (link["event_id"], link["table_index"], link["row_index"]) not in row_keys:
            raise StationError("archive link has no source row")
        if link["status"] == "safe_archive_link":
            by_row[(link["event_id"], link["table_index"], link["row_index"])].append(link)
    rejected_headers: list[dict[str, Any]] = []
    unavailable_headers: list[dict[str, Any]] = []
    registries, headers = (
        _load_registries(registry_configs, root),
        _load_headers(
            header_configs,
            root,
            {link["resolved_url"] for group in by_row.values() for link in group},
            rejected_headers,
            header_receipts,
            unavailable_headers,
        ),
    )
    available = _coops_availability(coops_config, coops_receipts, root, events)
    event_sites: list[dict[str, Any]] = []
    pulls: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in sorted(
        rows, key=lambda item: (item["event_id"], item["table_index"], item["row_index"])
    ):
        eid = row["event_id"]
        year = str(datetime.fromisoformat(events[eid]["usgs_time"]).year)
        key = (eid, row["table_index"], row["row_index"])
        related = by_row[key]
        identities = sorted(
            {
                (link["link_code"], link["link_sensor"])
                for link in related
                if link["link_code"] != "unknown"
            }
        ) or [("unknown", "unknown")]
        label = " ".join(row["fields"].get("location", "").split())
        candidates = [
            station
            for station in registries
            if station["provider"] == "CO-OPS"
            and label
            and _place(label) == _place(station["name"])
        ]
        candidate_ids = sorted({station["station_id"] for station in candidates})
        for code, sensor in identities:
            catalog_candidates = [
                {
                    "catalog_id": station["station_id"],
                    "name": station["name"],
                    "source_id": station["source_id"],
                    "matching_namespaces": [
                        namespace
                        for namespace in ("ptwc", "ioc")
                        if code in station["identifiers"][namespace]
                    ],
                    "provider_identifiers": station["identifiers"],
                    "place_label_agrees": _place(label) == _place(station["name"]),
                }
                for station in registries
                if station["provider"] == "IOC-SSC"
                and code != "unknown"
                and any(code in station["identifiers"][ns] for ns in ("ptwc", "ioc"))
            ]
            code_links = [
                link
                for link in related
                if (link["link_code"], link["link_sensor"]) == (code, sensor)
            ]
            matches = [
                header
                for header in headers
                if header["original_url"] in {link["resolved_url"] for link in code_links}
            ]
            unsupported = [
                source
                for source in rejected_headers
                if source["original_url"] in {link["resolved_url"] for link in code_links}
            ]
            unavailable = [
                source
                for source in unavailable_headers
                if source["original_url"] in {link["resolved_url"] for link in code_links}
            ]
            consistent = [header for header in matches if _label_agrees(label, header)]
            tier = "archive_code" if code != "unknown" else "name_only" if label else "unmatched"
            evidence_status = "header_needed" if code != "unknown" else "identity_needed"
            header: dict[str, Any] = {}
            exact_registry: list[dict[str, Any]] = []
            if matches:
                tier, evidence_status, header, exact_registry = _header_identity(
                    matches, label, registries
                )
            elif len(identities) > 1 or len(candidate_ids) > 1:
                tier, evidence_status = "ambiguous", "independent_review_required"
            elif candidate_ids:
                evidence_status = "name_candidate_not_historical_match"
            if unsupported and not matches:
                evidence_status = "unrecognized_header_format"
            elif unavailable and not matches:
                evidence_status = "header_acquisition_unavailable"
            physical_id, identity_scope, identity_basis = "unknown", "unknown", "unknown"
            if header and tier == "header_exact":
                if exact_registry:
                    physical_id = f"coops:{header['header_station_id']}"
                    identity_scope = "authoritative_provider_site"
                    identity_basis = "linked_header_provider_id_and_registry_coordinates"
                else:
                    physical_id = geographic_site_id(header)
                    identity_scope = "source_qualified_geographic_site"
                    identity_basis = "exact_linked_header_name_code_coordinates"
            verified = physical_id != "unknown"
            provider_station_id = str(header.get("header_station_id", "unknown"))
            if provider_station_id.casefold() in {"none", "unknown", "n/a", "na"}:
                provider_station_id = "unknown"
            flags = arrival_value_flags(row["fields"])
            report_id = f"{eid}:{row['table_index']}:{row['row_index']}"
            registry_checks: list[dict[str, Any]] = []
            for item in exact_registry:
                distance = _distance_km(matches[0], item)
                registry_checks.append(
                    {
                        **item,
                        "header_distance_km": distance if math.isfinite(distance) else "unknown",
                    }
                )
            evidence = {
                "event_id": eid,
                "report_id": report_id,
                "report_label": label,
                "link_code": code,
                "link_sensor": sensor,
                "status": evidence_status,
                "physical_site_id": physical_id,
                "identity_scope": identity_scope,
                "identity_basis": identity_basis,
                "geographic_signature": geographic_signature(header) if header else {},
                "headers": matches,
                "registry_id_checks": registry_checks,
                "registry_distance_limit_km": MAX_REGISTRY_DISTANCE_KM,
                "deployment_continuity": "unknown",
            }
            if unsupported:
                evidence["unrecognized_header_sources"] = unsupported
            if unavailable:
                evidence["unavailable_header_sources"] = unavailable
            event_sites.append(
                {
                    "report_id": report_id,
                    "event_id": eid,
                    "role": "development",
                    "source_row_status": row["status"],
                    "location_label": label or "unknown",
                    "link_code": code,
                    "link_sensor": sensor,
                    "era_key": year,
                    "identity_tier": tier,
                    "evidence_status": evidence_status,
                    "physical_site_id": physical_id,
                    "identity_scope": identity_scope,
                    "identity_basis": identity_basis,
                    "provider": "CO-OPS"
                    if exact_registry and verified
                    else header.get("provider", "unknown"),
                    "provider_station_id": provider_station_id if verified else "unknown",
                    "event_site_identity_verified": verified,
                    "deployment_id": "unknown",
                    "deployment_continuity_verified": False,
                    "latitude": header.get("latitude", "unknown"),
                    "longitude": header.get("longitude", "unknown"),
                    "coordinate_basis": "event_header" if header else "unknown",
                    "coordinate_crs": "unknown",
                    "historical_deployment_verified": False,
                    "source_ids": json.dumps(sorted(str(item["source_id"]) for item in matches)),
                    "evidence": json.dumps(evidence, sort_keys=True),
                    "header_source_ids": json.dumps(
                        sorted(str(x["source_id"]) for x in consistent)
                    ),
                    "linked_header_source_ids": json.dumps(
                        sorted(str(x["source_id"]) for x in matches)
                    ),
                    "header_metadata": json.dumps(
                        [
                            {
                                name: item[name]
                                for name in (
                                    "source_id",
                                    "header_name",
                                    "header_station_id",
                                    "provider",
                                    "latitude",
                                    "longitude",
                                    "header_date",
                                    "cadence_value",
                                    "cadence_units",
                                    "units",
                                    "time_basis",
                                    "vertical_datum",
                                    "sampling_mode",
                                    "processing",
                                )
                            }
                            for item in matches
                        ],
                        sort_keys=True,
                    ),
                    "candidate_coops_ids": json.dumps(candidate_ids),
                    "candidate_registry_source_ids": json.dumps(
                        sorted({x["source_id"] for x in candidates})
                    ),
                    "exact_registry_source_ids": json.dumps(
                        sorted({x["source_id"] for x in exact_registry})
                    ),
                    "candidate_catalog_matches": json.dumps(catalog_candidates, sort_keys=True),
                    "catalog_match_scope": (
                        "token_equality_namespace_and_history_unverified"
                        if catalog_candidates
                        else "unknown"
                    ),
                    "available_alternative_source_ids": json.dumps(
                        sorted(
                            {
                                source
                                for station in (
                                    [str(header["header_station_id"])]
                                    if verified
                                    else candidate_ids
                                )
                                for source in available.get((eid, station), [])
                            }
                        )
                    ),
                    "explicit_both_values": flags["both_values"],
                    "legacy_both_values": flags["estimate_and_arrival_as_labeled_values"],
                    "fit_eligible": False,
                    "model_eligible": False,
                    "physical_onset_validated": False,
                    "review_status": "pending_independent_review",
                }
            )
            if code_links and not matches and not unsupported and not unavailable:
                first = min(code_links, key=lambda link: link["resolved_url"])
                pull_key = (eid, code, sensor, year)
                candidate = {
                    "event_id": eid,
                    "role": "development",
                    "link_code": code,
                    "link_sensor": sensor,
                    "era_key": year,
                    "request_kind": "ia_header_discovery",
                    "original_url": first["resolved_url"],
                    "source_report_id": report_id,
                    "identity_tier": tier,
                    "physical_site_id": "unknown",
                    "status": "requires_cdx_capture_and_contract",
                    "direct_ntwc_fetch": False,
                    "waveform_pull_allowed": False,
                }
                if (
                    pull_key not in pulls
                    or candidate["original_url"] < pulls[pull_key]["original_url"]
                ):
                    pulls[pull_key] = candidate
    reports = _unique_reports(event_sites)
    _apply_review(reports, identity_review)
    delta = _identity_delta(reports, previous_crosswalk) if previous_crosswalk else []
    by_report = {row["report_id"]: row for row in reports}
    for row in event_sites:
        report = by_report[row["report_id"]]
        for name in (
            "review_status",
            "reviewer",
            "site_identity_fit_tier",
            "identity_evidence_sha256",
        ):
            row[name] = report[name]
        row["report_site_identity_verified"] = report["event_site_identity_verified"]
    acquisition_candidates = [
        {
            key: row[key]
            for key in (
                "event_id",
                "report_id",
                "role",
                "identity_tier",
                "physical_site_id",
                "identity_scope",
                "identity_basis",
                "provider",
                "provider_station_id",
                "event_site_identity_verified",
                "deployment_id",
                "deployment_continuity_verified",
                "source_ids",
                "evidence",
                "identity_evidence_sha256",
                "review_status",
            )
        }
        | {
            "request_kind": "coops_event_window",
            "waveform_pull_allowed": row["site_identity_fit_tier"],
            "status": "requires_window_and_contract_checks"
            if row["site_identity_fit_tier"]
            else "requires_independent_identity_review",
        }
        for row in reports
        if row["event_site_identity_verified"]
        and row["identity_scope"] == "authoritative_provider_site"
        and row["provider"] == "CO-OPS"
        and re.fullmatch(r"\d{7}", row["provider_station_id"])
    ]
    support: list[dict[str, Any]] = []
    for eid, event in sorted(events.items()):
        if event["role"] != "development":
            continue
        selected = [row for row in reports if row["event_id"] == eid]
        verified = [row for row in selected if row["event_site_identity_verified"]]
        reviewed = [row for row in selected if row["site_identity_fit_tier"]]
        pairs = [row for row in reviewed if row["explicit_both_values"]]
        candidate_pairs = [row for row in verified if row["explicit_both_values"]]
        exclusion_reasons: list[str] = []
        if event.get("cohort") != "thrust_core":
            exclusion_reasons.append("not_thrust_core")
        if event.get("attribution_status") != "single_source_metadata":
            exclusion_reasons.append("source_attribution_unresolved")
        if len({row["physical_site_id"] for row in pairs}) < 5:
            exclusion_reasons.append("lt5_reviewed_explicit_pair_sites")
        support.append(
            {
                "event_id": eid,
                "cohort": event.get("cohort", "unknown"),
                "attribution_status": event.get("attribution_status", "unknown"),
                "source_reports": len(selected),
                "verified_site_reports": len(verified),
                "verified_physical_sites": len({row["physical_site_id"] for row in verified}),
                "verified_explicit_pair_reports": len(candidate_pairs),
                "verified_explicit_pair_sites": len(
                    {row["physical_site_id"] for row in candidate_pairs}
                ),
                "reviewed_site_reports": len(reviewed),
                "reviewed_physical_sites": len({row["physical_site_id"] for row in reviewed}),
                "reviewed_explicit_pair_reports": len(pairs),
                "reviewed_explicit_pair_sites": len({row["physical_site_id"] for row in pairs}),
                "stage_d_identity_support": len({row["physical_site_id"] for row in pairs}) >= 5,
                "s4_identity_support": not exclusion_reasons,
                "s4_exclusion_reasons": exclusion_reasons,
                "physical_onset_validated": False,
            }
        )
    s4_events = sum(row["s4_identity_support"] for row in support)
    counts = Counter(row["identity_tier"] for row in event_sites)
    graphs: dict[str, Any] = {}
    for tier in TIERS:
        subset = [row for row in event_sites if row["identity_tier"] == tier]
        # Codes are an explicitly provisional network; unknown identities are never merged.
        edges = {
            (row["event_id"], f"{row['link_code']}:{row['link_sensor']}:{row['era_key']}")
            for row in subset
            if row["link_code"] != "unknown"
        }
        graphs[tier] = {
            "rows": len(subset),
            "identifier_basis": "archive_code_sensor_calendar_year",
            **_components(edges),
        }
    summary: dict[str, Any] = {
        "status": "reviewed_event_site_inventory"
        if identity_review
        else "candidate_event_site_inventory",
        "source_rows": len(rows),
        "event_site_rows": len(event_sites),
        "distinct_source_reports": len({x["report_id"] for x in event_sites}),
        "tier_counts": {tier: counts[tier] for tier in TIERS},
        "connectivity_by_tier": graphs,
        "fit_eligible_rows": 0,
        "verified_event_site_reports": sum(row["event_site_identity_verified"] for row in reports),
        "reviewed_event_site_reports": sum(row["site_identity_fit_tier"] for row in reports),
        "unique_report_rows": len(reports),
        "s4_thrust_events_with_five_reviewed_sites": s4_events,
        "s4_site_count_basis": "distinct_reviewed_sites_with_explicit_estimate_and_observed_values",
        "s4_thrust_events_with_five_reviewed_explicit_pair_sites": s4_events,
        "s4_disposition": "identity_support_met_other_gates_pending"
        if s4_events >= 10
        else "audit_only_fewer_than_ten_thrust_events_with_five_reviewed_sites",
        "event_identity_support": support,
        "acquisition_candidates": len(acquisition_candidates),
        "header_probe_candidates": len(pulls),
        "registry_records": len(registries),
        "rows_with_catalog_token_candidates": sum(
            row["candidate_catalog_matches"] != "[]" for row in event_sites
        ),
        "verified_header_assets": len(headers),
        "alternative_coops_event_station_windows": len(available),
        "limitations": [
            "Calendar-year era keys do not assert stable deployments.",
            "Registry name candidates are not historical NTWC-to-provider matches.",
            "IOC catalog token equality does not establish the NTWC code namespace or era.",
            "Historical NOS IDs, compatible labels and registry coordinates "
            "identify provider sites.",
            "Other linked headers identify source-qualified geographic sites by "
            "exact name/code/coordinates.",
            "Source-qualified IDs exclude sensors; they do not merge measurements "
            "or assert deployment continuity.",
            "Exact geographic grouping does not establish a coordinate CRS or "
            "resolve changed/rounded coordinates.",
            "S4 requires five distinct reviewed explicit-pair sites "
            "per single-source thrust event.",
            "A 2 km registry check is a plausibility bound, not evidence of unchanged deployment.",
            "Review applies to evidence digests; models and physical onset remain unvalidated.",
            "Acquisition candidates additionally require identity review and window checks.",
        ],
        "source_evidence": [
            {key: header[key] for key in ("source_id", "source_url", "sha256")}
            for header in headers
        ],
        "registry_evidence": [
            {
                key: station[key]
                for key in (
                    "provider",
                    "station_id",
                    "source_id",
                    "source_url",
                    "sha256",
                    "temporal_scope",
                )
            }
            for station in registries
        ],
        "input_sha256": {
            "events_config": hashlib.sha256(events_config.read_bytes()).hexdigest(),
            **{
                name: hashlib.sha256((census_dir / f"{name}.json").read_bytes()).hexdigest()
                for name in ("rows", "links")
            },
        },
        "contract_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                *registry_configs,
                *header_configs,
                *([coops_config] if coops_config else []),
            )
        },
        "coops_receipts_sha256": (
            hashlib.sha256(coops_receipts.read_bytes()).hexdigest() if coops_receipts else "unknown"
        ),
        "identity_review_sha256": (
            hashlib.sha256(identity_review.read_bytes()).hexdigest()
            if identity_review
            else "unknown"
        ),
    }
    if previous_crosswalk:
        summary["previous_crosswalk_sha256"] = hashlib.sha256(
            previous_crosswalk.read_bytes()
        ).hexdigest()
        summary["identity_delta_counts"] = dict(
            sorted(Counter(row["change"] for row in delta).items())
        )
    if header_receipts:
        summary["header_receipt_sha256"] = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in header_receipts
        }
    if unavailable_headers:
        summary["unavailable_header_assets"] = len(unavailable_headers)
        summary["header_acquisition_unavailable"] = unavailable_headers
    if rejected_headers:
        summary["unrecognized_header_assets"] = len(rejected_headers)
        summary["header_rejections"] = rejected_headers
    output.mkdir(parents=True, exist_ok=False)
    if previous_crosswalk:
        _write_csv(output / "identity_delta.csv", delta, ["event_id", "report_id", "change"])
    _write_csv(output / "event_site.csv", event_sites, ["report_id", "event_id", "identity_tier"])
    _write_csv(
        output / "unique_report_crosswalk.csv", reports, ["report_id", "event_id", "identity_tier"]
    )
    _write_csv(
        output / "acquisition_candidates.csv", acquisition_candidates, ["event_id", "report_id"]
    )
    _write_csv(
        output / "pull_list.csv",
        [pulls[key] for key in sorted(pulls)],
        ["event_id", "original_url"],
    )
    (output / "connectivity.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
