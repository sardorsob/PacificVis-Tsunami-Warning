"""Freeze bounded development waveform requests and all source-selection dispositions.

No network calls. A four-day acquisition unit is origin day -1 through +2 UTC.
The audit sample balances metadata strata; capture availability never establishes
an onset, a historical deployment, or fit eligibility.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import load_contracts  # noqa: E402
from pipeline.ntwc_archive import link_identity, link_status  # noqa: E402

SEED = "ntwc-development-audit-60-v1"
API_DOCS = "https://api.tidesandcurrents.noaa.gov/api/prod/"
CONTROL_OFFSETS = (-14, -21, -28, -35, -42, -49, -56)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_frozen_events(document: dict[str, Any], selection: Path) -> dict[str, dict[str, Any]]:
    ledger = json.loads(selection.read_text())
    material = {k: v for k, v in ledger.items() if k != "selection_sha256"}
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != ledger.get("selection_sha256") or digest != document.get("selection_sha256"):
        raise ValueError("frozen selection digest mismatch")
    frozen = {e["event_id"]: e for e in ledger["events"]}
    if len(frozen) != len(ledger["events"]):
        raise ValueError("duplicate frozen event identity")
    events: dict[str, dict[str, Any]] = {}
    for event in document["events"].values():
        eid = event["event_id"]
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", eid)
            or eid in events
            or event["role"] not in {"development", "sealed_evaluation"}
            or eid not in frozen
            or any(frozen[eid].get(key) != value for key, value in event.items())
        ):
            raise ValueError("event config differs from frozen selection identity/metadata")
        events[eid] = event
    if set(events) != set(frozen):
        raise ValueError("event config omits frozen selection events")
    return events


def _validate_site_evidence(site: dict[str, str]) -> None:
    """Bind each accepted adapter field to the independently reviewed evidence."""
    text = site.get("evidence", "")
    evidence = json.loads(text or "[]")
    source_ids = json.loads(site.get("source_ids", "[]"))
    if (
        not isinstance(evidence, list)
        or not evidence
        or not isinstance(source_ids, list)
        or not source_ids
        or hashlib.sha256(text.encode()).hexdigest() != site.get("identity_evidence_sha256")
    ):
        raise ValueError("reviewed site evidence or digest is missing/invalid")
    evidence = cast(list[dict[str, Any]], evidence)
    source_ids = cast(list[str], source_ids)
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("reviewed source evidence contains duplicate IDs")
    eid, report, station = site["event_id"], site["report_id"], site["provider_station_id"]
    if not report.startswith(eid + ":") or site.get("physical_site_id") != f"coops:{station}":
        raise ValueError("reviewed site identity differs from evidence")
    observed_sources: set[str] = set()
    for alternative in evidence:
        if (
            alternative.get("event_id") != eid
            or alternative.get("report_id") != report
            or alternative.get("physical_site_id") != site["physical_site_id"]
            or not alternative.get("headers")
        ):
            raise ValueError("reviewed site identity differs from evidence")
        for header in alternative["headers"]:
            if (
                header.get("header_station_id") != station
                or header.get("provider") not in {"NOS", "NOAA", "CO-OPS"}
                or not header.get("source_id")
                or not re.fullmatch(r"[a-f0-9]{64}", header.get("sha256", ""))
            ):
                raise ValueError("reviewed station or source differs from evidence")
            observed_sources.add(header["source_id"])
    if observed_sources != set(source_ids):
        raise ValueError("reviewed source IDs differ from evidence")


def parse_utc(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value):
        raise ValueError("origin must be a full aware UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("unsupported archived URL scheme")
    normalized = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    if parsed.fragment or link_status(normalized, normalized)[0] != "safe_archive_link":
        raise ValueError("unsafe original archive URL")
    return normalized


def _event_prefix(event: dict[str, Any]) -> str:
    key = parse_qs(urlsplit(str(event["archive_url"])).query)["p"][0]
    return _canonical("https://www.tsunami.gov/previous.events/" + key + "/")


def event_window(origin: datetime, offset_days: int = 0) -> tuple[datetime, datetime]:
    start = origin.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=offset_days - 1
    )
    return start, start + timedelta(days=4)


def overlapping_events(start: datetime, stop: datetime, origins: dict[str, datetime]) -> list[str]:
    return sorted(
        eid
        for eid, origin in origins.items()
        if start <= origin + timedelta(hours=48) and stop > origin
    )


def _verified(path: Path, root: Path, receipt: dict[str, Any]) -> bytes:
    target = root / path
    sidecar = target.with_name(target.name + ".sha256")
    if not all(p.resolve().is_relative_to(root.resolve()) for p in (target, sidecar)):
        raise ValueError("source or checksum path escapes root")
    raw = target.read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != receipt["sha256"]
        or _sha(target) != sidecar.read_text().strip()
        or len(raw) != receipt["bytes"]
    ):
        raise ValueError("source checksum/size differs from receipt")
    return raw


def _cached_captures(
    configs: Sequence[Path],
    receipts: Sequence[Path],
    root: Path,
    events: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Reuse only exact capture bytes whose final URL and receipt remain verified."""
    if len(configs) != len(receipts):
        raise ValueError("each reuse config requires a corresponding receipt")
    result: dict[str, dict[str, Any]] = {}
    for config, receipt_path in zip(configs, receipts, strict=True):
        contracts = load_contracts(config)
        outcomes = json.loads(receipt_path.read_text())
        by_id = {r["source_id"]: r for r in outcomes}
        if len(by_id) != len(outcomes) or set(by_id) != {c.source_id for c in contracts}:
            raise ValueError("reuse receipt/contract identities differ")
        for contract in contracts:
            eid = contract.local_path.parent.name
            receipt = by_id[contract.source_id]
            if (
                eid not in events
                or events[eid]["role"] != "development"
                or not re.fullmatch(
                    r"https://web\.archive\.org/web/\d{14}id_/https?://.+", contract.url
                )
                or "ntwc" not in contract.format.lower()
                or "ascii" not in contract.format.lower()
                or receipt["local_path"] != str(contract.local_path)
                or receipt["status"] not in {"downloaded", "cached"}
                or receipt.get("final_url") != contract.url
            ):
                raise ValueError("reuse capture lacks exact development source provenance")
            original = contract.url.split("id_/", 1)[1]
            if not _canonical(original).startswith(_event_prefix(events[eid])):
                raise ValueError("reuse capture is outside its event archive")
            raw = _verified(Path(contract.local_path), root, receipt)
            if not raw.lstrip().startswith(contract.expected_prefix.encode()):
                raise ValueError("reuse source prefix mismatch")
            if contract.url in result:
                raise ValueError("duplicate exact capture in reuse inputs")
            result[contract.url] = dict(
                source_id=contract.source_id,
                event_id=eid,
                local_path=str(contract.local_path),
                expected_prefix=contract.expected_prefix,
                source_sha256=receipt["sha256"],
                source_bytes=len(raw),
                source_config=str(config),
                source_receipt=str(receipt_path),
                final_url=receipt["final_url"],
            )
    return result


def load_captures(
    config: Path, receipts: Path, root: Path, events: dict[str, dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Read exact receipt-backed CDX indexes; no URL synthesis from station names."""
    contracts = load_contracts(config)
    outcomes = json.loads(receipts.read_text())
    by_id = {r["source_id"]: r for r in outcomes}
    if len(by_id) != len(outcomes) or set(by_id) != {c.source_id for c in contracts}:
        raise ValueError("CDX receipt/contract IDs differ")
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dispositions: list[dict[str, Any]] = []
    for contract in contracts:
        matches = [
            eid
            for eid in events
            if contract.source_id == f"ia-cdx-{eid}"
            or contract.source_id.startswith(f"ia-cdx-{eid}-")
        ]
        if len(matches) != 1 or events[matches[0]]["role"] != "development":
            raise ValueError("CDX contract belongs to absent/ambiguous/reserved event")
        eid = matches[0]
        receipt = by_id[contract.source_id]
        if receipt["local_path"] != str(contract.local_path):
            raise ValueError("CDX receipt path differs")
        disposition: dict[str, Any] = dict(
            event_id=eid,
            source_id=contract.source_id,
            status=receipt["status"],
            reason=receipt["reason"],
        )
        dispositions.append(disposition)
        query_prefix = parse_qs(urlsplit(contract.url).query)["url"][0].rstrip("*")
        if not _canonical(query_prefix).startswith(_event_prefix(events[eid])):
            disposition["status"] = "rejected_overbroad_cdx_scope"
            continue
        if receipt["status"] not in {"downloaded", "cached"}:
            continue
        cdx_raw = _verified(Path(contract.local_path), root, receipt)
        rows = json.loads(cdx_raw)
        if not rows:
            disposition["capture_rows"] = 0
            continue
        if not isinstance(rows[0], list) or not {
            "timestamp",
            "original",
            "digest",
            "length",
        } <= set(rows[0]):
            raise ValueError("unknown CDX schema")
        if len(rows) - 1 >= 5000:
            raise ValueError("CDX index reached request cap; completeness unresolved")
        disposition["capture_rows"] = len(rows) - 1
        for values in rows[1:]:
            record = dict(zip(rows[0], values, strict=True))
            if not re.fullmatch(r"\d{14}", record["timestamp"]) or not re.fullmatch(
                r"[A-Z2-7]{32}", record["digest"]
            ):
                continue
            try:
                original = _canonical(record["original"])
                if not original.startswith(_event_prefix(events[eid])):
                    continue
                length = int(record["length"])
                if length <= 0:
                    continue
            except (ValueError, TypeError):
                continue
            result[original].append(
                dict(
                    event_id=eid,
                    original_url=original,
                    capture_url=f"https://web.archive.org/web/{record['timestamp']}id_/{record['original']}",
                    capture_timestamp=record["timestamp"],
                    cdx_digest=record["digest"],
                    cdx_compressed_length=length,
                    cdx_source_id=contract.source_id,
                    cdx_evidence_path=str(contract.local_path),
                    cdx_evidence_sha256=hashlib.sha256(cdx_raw).hexdigest(),
                )
            )
    return result, dispositions


def _file_day(url: str, start: datetime, stop: datetime) -> datetime | None:
    tokens = link_identity(url)
    if tokens["link_day"] == "unknown":
        return None
    candidates: list[datetime] = []
    for offset in range((stop - start).days):
        day = start + timedelta(days=offset)
        if int(tokens["link_day"]) == day.timetuple().tm_yday and tokens["link_year"] in {
            "unknown",
            str(day.year),
            str(day.year)[-2:],
        }:
            candidates.append(day)
    return candidates[0] if len(candidates) == 1 else None


def select_pairs(
    pairs: list[tuple[str, str, str]], events: dict[str, dict[str, Any]], count: int
) -> list[tuple[str, str, str]]:
    """Balance era, region, event and code before a seeded deterministic tie-break."""
    chosen: list[tuple[str, str, str]] = []
    era_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    remaining = set(pairs)
    while remaining and len(chosen) < count:

        def key(pair: tuple[str, str, str]) -> tuple[Any, ...]:
            eid, code, _ = pair
            era = str(int(events[eid]["usgs_time"][:4]) // 5 * 5)
            return (
                era_counts[era],
                region_counts[str(events[eid].get("region", "unknown"))],
                event_counts[eid],
                code_counts[code],
                hashlib.sha256(f"{SEED}:{':'.join(pair)}".encode()).hexdigest(),
            )

        pair = min(remaining, key=key)
        remaining.remove(pair)
        chosen.append(pair)
        eid, code, _ = pair
        era_counts[str(int(events[eid]["usgs_time"][:4]) // 5 * 5)] += 1
        region_counts[str(events[eid].get("region", "unknown"))] += 1
        event_counts[eid] += 1
        code_counts[code] += 1
    return chosen


def _contract(
    sid: str, url: str, local: str, prefix: str, provider: str, reason: str
) -> dict[str, str]:
    ia = provider == "ia"
    return dict(
        source_id=sid,
        source_class="Internet Archive NTWC station day record"
        if ia
        else "coastal water-level observation",
        availability="approved",
        reason=reason,
        url=url,
        local_path=local,
        format="NTWC event archive ASCII" if ia else "CO-OPS Data API JSON",
        publisher="NOAA NTWC and original header provider; Internet Archive capture"
        if ia
        else "NOAA CO-OPS",
        expected_content_signature="Observed exact-capture prefix; validate header and timestamps"
        if ia
        else "Provider JSON observation or explicit error response",
        expected_prefix=prefix,
        units="source header" if ia else "meters",
        crs="unknown",
        horizontal_datum="unknown",
        vertical_datum="source header" if ia else "STND",
        coordinate_order="source header" if ia else "source metadata",
        temporal_semantics="UTC source samples; no onset inference",
        station_metadata="Within-event evidence only; historical deployment continuity unverified",
    )


def _toml(contracts: list[dict[str, str]], windows: dict[str, dict[str, str]]) -> str:
    lines = [
        'contract_version = "2026-10-31"',
        'terms = "Retain source attribution; research snapshots; redistribution unreviewed"',
        f"api_docs = {json.dumps(API_DOCS)}",
        "",
    ]
    for contract in contracts:
        lines.append(f"[assets.{json.dumps(contract['source_id'])}]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        lines.append("")
        lines.append(f"[source_windows.{json.dumps(contract['source_id'])}]")
        lines.extend(
            f"{key} = {json.dumps(value)}" for key, value in windows[contract["source_id"]].items()
        )
        lines.append("")
    return "\n".join(lines)


def generate(
    events_config: Path,
    census: Path,
    cdx_config: Path,
    cdx_receipts: Path,
    root: Path,
    output: Path,
    *,
    selection: Path,
    reviewed_sites: Path | None = None,
    prefixes: Sequence[Path] = (),
    known_catalog: Path | None = None,
    existing_contracts: Sequence[Path] = (),
    reuse_configs: Sequence[Path] = (),
    reuse_receipts: Sequence[Path] = (),
    use_cdx_digests: bool = False,
    max_pairs: int = 60,
    controls: int = 9,
    remaining_bytes: int = 1_500_000_000,
    max_contracts: int = 200,
) -> dict[str, Any]:
    """Publish immutable contracts, prefix requests, and request-level rejection evidence."""
    if output.exists():
        raise FileExistsError(output)
    if max_pairs < 1 or controls < 0 or remaining_bytes < 1 or not 1 <= max_contracts <= 200:
        raise ValueError("invalid acquisition budgets")
    document = tomllib.loads(events_config.read_text())
    events = validate_frozen_events(document, selection)
    cached = _cached_captures(reuse_configs, reuse_receipts, root, events)
    existing_paths = {
        c.source_id: str(c.local_path) for p in existing_contracts for c in load_contracts(p)
    }
    reused: dict[str, dict[str, Any]] = {}
    reserved = {
        eid: parse_utc(e["usgs_time"])
        for eid, e in events.items()
        if e["role"] == "sealed_evaluation"
    }
    windows: dict[str, tuple[datetime, datetime]] = {}
    event_dispositions: list[dict[str, Any]] = []
    for eid, event in sorted(events.items()):
        if event["role"] != "development":
            continue
        reason = "eligible"
        try:
            start, stop = event_window(parse_utc(event["usgs_time"]))
        except (ValueError, KeyError):
            event_dispositions.append(dict(event_id=eid, status="unknown_origin"))
            continue
        if reason == "eligible" and event.get("attribution_status") != "single_source_metadata":
            reason = "compound_or_unresolved_origin"
        if reason == "eligible":
            overlaps = overlapping_events(start, stop, reserved)
            if overlaps:
                reason = "reserved_window_overlap:" + ";".join(overlaps)
            else:
                windows[eid] = (start, stop)
        event_dispositions.append(dict(event_id=eid, status=reason))
    captures, cdx_status = load_captures(cdx_config, cdx_receipts, root, events)
    links = json.loads((census / "links.json").read_text())
    dispositions: list[dict[str, Any]] = []
    by_pair: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for link in links:
        eid = link["event_id"]
        if (
            eid not in events
            or events[eid]["role"] != "development"
            or link["role"] != "development"
            or link["source_id"] != events[eid]["archive_source_id"]
        ):
            raise ValueError("unknown/reserved/mismatched census link")
        url = link["resolved_url"]
        entry = dict(event_id=eid, original_url=url, status="unusable_link")
        dispositions.append(entry)
        if eid not in windows:
            entry["status"] = "event_window_blocked"
            continue
        if link["status"] != "safe_archive_link":
            continue
        original = _canonical(url)
        if not original.startswith(_event_prefix(events[eid])):
            href = str(link.get("href", ""))
            if urlsplit(href).scheme or urlsplit(href).netloc or href.startswith("/"):
                entry["status"] = "outside_event_directory"
                continue
            reconstructed = sorted(
                {
                    u
                    for u, items in captures.items()
                    if Path(urlsplit(u).path).name == Path(href).name
                    and any(c["event_id"] == eid for c in items)
                }
            )
            if len(reconstructed) != 1:
                entry["status"] = "relative_link_reconstruction_unresolved"
                continue
            original = reconstructed[0]
            entry.update(
                source_href=href,
                reconstructed_url=original,
                link_resolution_rule="unique_event_scoped_cdx_filename",
            )
        tokens = link_identity(original)
        if tokens["link_code"] == "unknown":
            entry["status"] = "unrecognized_filename"
            continue
        day = _file_day(original, *windows[eid])
        if day is None:
            entry["status"] = "day_outside_window_or_unresolved"
            continue
        options = [c for c in captures.get(original, []) if c["event_id"] == eid]
        if not options:
            entry["status"] = "no_verified_cdx_capture"
            continue
        selected = min(options, key=lambda c: (c["capture_timestamp"], c["cdx_digest"]))
        pair = (eid, tokens["link_code"], tokens["link_sensor"])
        by_pair[pair][original] = {
            **selected,
            **tokens,
            "file_day_utc": day.isoformat(),
            "role": "development",
        }
        entry["status"] = "capture_candidate"
    selected = select_pairs(list(by_pair), events, max_pairs)
    selected_keys = set(selected)
    for entry in dispositions:
        if entry["status"] == "capture_candidate":
            tokens = link_identity(entry.get("reconstructed_url", entry["original_url"]))
            pair = (entry["event_id"], tokens["link_code"], tokens["link_sensor"])
            entry["status"] = (
                "audit_pair_selected" if pair in selected_keys else "outside_seeded_audit_sample"
            )
    observed: dict[str, dict[str, Any]] = {}
    for path in prefixes:
        for item in json.loads(path.read_text())["requests"]:
            if item.get("probe_status") == "success" and item.get("expected_prefix"):
                text = item.get("prefix_text", "")
                if not text.lstrip().startswith(item["expected_prefix"]) or hashlib.sha256(
                    text.encode()
                ).hexdigest() != item.get("prefix_sha256"):
                    raise ValueError("prefix evidence text/hash mismatch")
                if (
                    item["capture_url"] in observed
                    and observed[item["capture_url"]]["prefix_sha256"] != item["prefix_sha256"]
                ):
                    raise ValueError("conflicting capture prefix evidence")
                observed[item["capture_url"]] = item
    probes: list[dict[str, Any]] = []
    header_probes: list[dict[str, Any]] = []
    contracts: dict[str, list[dict[str, str]]] = {"ia": [], "coops": []}
    source_windows: dict[str, dict[str, str]] = {}
    request_logs: list[dict[str, Any]] = []
    estimates: dict[str, int] = {}
    for pair in selected:
        files = sorted(by_pair[pair].values(), key=lambda x: (x["file_day_utc"], x["original_url"]))
        header_probes.append(files[0])
        for item in files:
            sid = "ia-window-" + hashlib.sha256(item["original_url"].encode()).hexdigest()[:20]
            entry = {**item, "source_id": sid, "request_status": "prefix_required"}
            request_logs.append(entry)
            estimates[sid] = max(131072, item["cdx_compressed_length"] * 12)
            reuse = cached.get(item["capture_url"])
            if reuse and sid in existing_paths and reuse["local_path"] != existing_paths[sid]:
                # A new header witness must not move an already contracted window body.
                reuse = None
            if reuse and reuse["event_id"] != pair[0]:
                raise ValueError("reused capture event differs from candidate")
            prefix = (reuse or observed.get(item["capture_url"], {})).get("expected_prefix")
            if not prefix and not use_cdx_digests:
                probes.append(item)
                continue
            filename = Path(urlsplit(str(item["original_url"])).path).name
            contract = _contract(
                sid,
                item["capture_url"],
                reuse["local_path"]
                if reuse
                else f"data/raw/ia/windows-v1/{sid}/{pair[0]}/{filename}",
                prefix or "",
                "ia",
                f"Exact development-linked capture; CDX digest={item['cdx_digest']}",
            )
            if use_cdx_digests:
                contract.update(
                    expected_cdx_sha1=item["cdx_digest"],
                    cdx_evidence_path=item["cdx_evidence_path"],
                    cdx_evidence_sha256=item["cdx_evidence_sha256"],
                    expected_content_signature=(
                        "Exact capture plus pinned full-body CDX SHA1; reject HTML"
                    ),
                )
            contracts["ia"].append(contract)
            entry["request_status"] = "contracted"
            if reuse:
                reused[sid] = reuse
                entry.update(request_status="cached_capture_reuse", reused_source=reuse)
            start, stop = windows[pair[0]]
            source_windows[sid] = dict(
                event_id=pair[0],
                purpose="event_window",
                start_utc=start.isoformat(),
                stop_utc=stop.isoformat(),
                original_url=item["original_url"],
            )
            estimates[sid] = 0 if reuse else max(131072, item["cdx_compressed_length"] * 12)
    sites = []
    if reviewed_sites:
        with reviewed_sites.open(newline="") as f:
            sites = list(csv.DictReader(f))
    verified: dict[tuple[str, str], dict[str, str]] = {}
    seen_reports: set[str] = set()
    for site in sites:
        eid = site["event_id"]
        if site["report_id"] in seen_reports:
            raise ValueError("duplicate reviewed report identity")
        seen_reports.add(site["report_id"])
        if eid not in events or events[eid]["role"] != "development":
            raise ValueError("reviewed site has unknown/reserved event")
        station = site.get("provider_station_id", "")
        accepted = (
            site.get("event_site_identity_verified", "").lower() == "true"
            and site.get("identity_scope", "authoritative_provider_site")
            == "authoritative_provider_site"
            and site.get("identity_tier") in {"header_exact", "registry_exact"}
            and site.get("provider") in {"NOS", "NOAA", "CO-OPS"}
            and re.fullmatch(r"\d{7}", station)
            and site.get("review_status") == "independently_reviewed"
        )
        if accepted:
            _validate_site_evidence(site)
        if accepted and eid in windows:
            verified[(eid, station)] = site
        else:
            request_logs.append(
                dict(
                    event_id=eid,
                    report_id=site["report_id"],
                    request_status="coops_identity_or_window_unresolved",
                )
            )
    catalog_origins = {}
    if controls and verified:
        if known_catalog is None:
            raise ValueError("quiet controls require a known-earthquake catalog")
        payload = known_catalog.read_bytes()
        if (
            _sha(known_catalog)
            != known_catalog.with_name(known_catalog.name + ".sha256").read_text().strip()
        ):
            raise ValueError("catalog checksum mismatch")
        catalog_origins = {
            r["id"]: parse_utc(r["time"])
            for r in csv.DictReader(io.StringIO(payload.decode()))
            if r["type"] == "earthquake"
        }
    control_sites = sorted(
        verified, key=lambda pair: hashlib.sha256(f"{SEED}:control:{pair}".encode()).hexdigest()
    )[:controls]
    for (eid, station), site in sorted(verified.items()):
        kinds = [("event_window", 0)] + (
            [("quiet_control", offset) for offset in CONTROL_OFFSETS]
            if (eid, station) in control_sites
            else []
        )
        for purpose, offset in kinds:
            start, stop = event_window(parse_utc(events[eid]["usgs_time"]), offset)
            if purpose == "quiet_control" and (
                not catalog_origins
                or start < min(catalog_origins.values())
                or stop > max(catalog_origins.values())
            ):
                request_logs.append(
                    dict(
                        event_id=eid,
                        provider_station_id=station,
                        purpose=purpose,
                        offset_days=offset,
                        start_utc=start.isoformat(),
                        stop_utc=stop.isoformat(),
                        request_status="outside_known_catalog_span",
                    )
                )
                continue
            conflicts = overlapping_events(
                start, stop, reserved if purpose == "event_window" else catalog_origins
            )
            if conflicts:
                request_logs.append(
                    dict(
                        event_id=eid,
                        provider_station_id=station,
                        purpose=purpose,
                        offset_days=offset,
                        start_utc=start.isoformat(),
                        stop_utc=stop.isoformat(),
                        request_status="window_overlap",
                        conflicting_event_ids=conflicts,
                    )
                )
                continue
            for product in ("one_minute_water_level", "water_level"):
                sid = f"coops-window-{eid}-{station}-{product}-{purpose}"
                query = dict(
                    product=product,
                    application="pacific_tsunami_warning_time",
                    begin_date=start.strftime("%Y%m%d"),
                    end_date=(stop - timedelta(days=1)).strftime("%Y%m%d"),
                    datum="STND",
                    station=station,
                    time_zone="gmt",
                    units="metric",
                    format="json",
                )
                url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urlencode(
                    query
                )
                contract = _contract(
                    sid,
                    url,
                    f"data/raw/coops/windows-v1/{eid}/{station}-{product}-{purpose}.json",
                    "{",
                    "coops",
                    f"Reviewed event-site identity; {purpose}; report {site['report_id']}",
                )
                contracts["coops"].append(contract)
                source_windows[sid] = dict(
                    event_id=eid,
                    purpose=purpose,
                    start_utc=start.isoformat(),
                    stop_utc=stop.isoformat(),
                    offset_days=str(offset),
                    evidence=site.get("evidence", "unknown"),
                )
                estimates[sid] = 524288 if product == "one_minute_water_level" else 131072
                request_logs.append(
                    dict(
                        event_id=eid,
                        source_id=sid,
                        provider_station_id=station,
                        purpose=purpose,
                        offset_days=offset,
                        request_status="contracted",
                        url=url,
                    )
                )
            if purpose == "quiet_control":
                break  # First catalog-clear candidate under the predeclared ladder.
    prior: dict[str, tuple[dict[str, str], Path, dict[str, Any]]] = {}
    for path in existing_contracts:
        old = tomllib.loads(path.read_text())
        for source in load_contracts(path):
            sid = source.source_id
            if sid in prior:
                raise ValueError("duplicate source across existing contract inputs")
            prior[sid] = (
                dict(
                    url=source.url,
                    local_path=str(source.local_path),
                    format=source.format,
                    expected_prefix=source.expected_prefix,
                ),
                path,
                old.get("source_windows", {}).get(sid, {}),
            )
    retained: set[str] = set()
    for provider, assets in contracts.items():
        delta: list[dict[str, str]] = []
        for asset in assets:
            sid = asset["source_id"]
            if sid not in prior:
                delta.append(asset)
                continue
            old, path, old_window = prior[sid]
            if any(asset[key] != value for key, value in old.items()) or any(
                old_window.get(key) != source_windows[sid].get(key)
                for key in ("event_id", "purpose", "start_utc", "stop_utc")
            ):
                raise ValueError("existing source identity/window conflicts with candidate")
            retained.add(sid)
            estimates.pop(sid)
            for entry in request_logs:
                if entry.get("source_id") == sid:
                    entry.update(
                        request_status="existing_contract_retained", existing_contract=str(path)
                    )
        contracts[provider] = delta
    projected = sum(estimates.values())
    preflight: dict[str, Any] = dict(
        selection_seed=SEED,
        selection_sha256=document.get("selection_sha256", "unknown"),
        eligible_capture_pairs=len(by_pair),
        selected_pairs=[dict(event_id=e, link_code=c, link_sensor=s) for e, c, s in selected],
        selected_pairs_count=len(selected),
        requested_audit_pairs=max_pairs,
        coops_reviewed_event_site_windows=len(verified),
        remaining_raw_byte_budget=remaining_bytes,
        estimated_transfer_bytes=projected,
        within_budget=projected <= remaining_bytes,
        status="ready"
        if projected <= remaining_bytes and not probes
        else "prefixes_required"
        if projected <= remaining_bytes
        else "over_budget",
        provider_policy={"coops": {"min_interval_seconds": 1}, "ia": {"min_interval_seconds": 4}},
        max_contracts_per_run=max_contracts,
        max_consecutive_provider_errors=3,
        existing_source_ids_retained=sorted(retained),
        previous_source_ids_outside_current_selection=sorted(set(prior) - retained),
        api_docs=API_DOCS,
        quiet_control_offset_days=list(CONTROL_OFFSETS),
        quiet_control_rule="First catalog-clear four-day window under the predeclared weekly "
        "offset ladder; exclude catalog origin..+48h. M>=6.5 catalog is incomplete for "
        "smaller events. Candidates are neither validated quiet nor independent controls.",
        limitations=[
            "S4 audit sample; no model acceptance implied.",
            "Metadata acquisition sample only; the F6 blind waveform audit remains separate.",
            "CDX absence is capture unavailability, not proof of no original record.",
            "Six-minute fallback products remain separate from one-minute products.",
            "Numeric missing/sentinel and station history require downstream review.",
        ],
        event_dispositions=event_dispositions,
        cdx_dispositions=cdx_status,
        input_sha256={
            str(p): _sha(p)
            for p in [
                events_config,
                selection,
                census / "links.json",
                cdx_config,
                cdx_receipts,
                *prefixes,
                *existing_contracts,
                *([reviewed_sites] if reviewed_sites else []),
                *([known_catalog] if known_catalog else []),
            ]
        },
        batches=[],
    )
    if reuse_configs:
        preflight["cached_capture_reuse"] = reused
        preflight["input_sha256"].update(
            {str(p): _sha(p) for p in [*reuse_configs, *reuse_receipts]}
        )
    if use_cdx_digests:
        preflight["capture_identity_rule"] = "exact_url_and_verified_scoped_cdx_full_body_sha1"
    output.mkdir(parents=True)
    for name, data in [
        ("preflight.json", preflight),
        ("request-dispositions.json", request_logs),
        ("link-dispositions.json", dispositions),
        ("prefix-probes.json", {"requests": probes}),
        (
            "header-probe-suggestions.json",
            {"requests": [p for p in header_probes if p["capture_url"] not in observed]},
        ),
    ]:
        (output / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    if projected <= remaining_bytes:
        for provider, assets in contracts.items():
            ordered = sorted(assets, key=lambda x: x["source_id"])
            for i in range(0, len(ordered), max_contracts):
                batch = ordered[i : i + max_contracts]
                filename = f"{provider}-{i // max_contracts + 1:03d}.toml"
                (output / filename).write_text(_toml(batch, source_windows))
                load_contracts(output / filename)
                preflight["batches"].append(
                    dict(
                        path=filename,
                        contracts=len(batch),
                        estimated_bytes=sum(estimates[a["source_id"]] for a in batch),
                        sha256=_sha(output / filename),
                    )
                )
        (output / "preflight.json").write_text(
            json.dumps(preflight, indent=2, sort_keys=True) + "\n"
        )
    return preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("events", "selection", "census", "cdx-config", "cdx-receipts", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("reviewed-sites", "known-catalog"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--prefixes", type=Path, action="append", default=[])
    parser.add_argument("--existing-contracts", type=Path, action="append", default=[])
    parser.add_argument("--reuse-config", type=Path, action="append", default=[])
    parser.add_argument("--reuse-receipts", type=Path, action="append", default=[])
    parser.add_argument("--use-cdx-digests", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--max-pairs", type=int, default=60)
    parser.add_argument("--controls", type=int, default=9)
    parser.add_argument("--remaining-bytes", type=int, default=1_500_000_000)
    args = parser.parse_args()
    result = generate(
        args.events,
        args.census,
        args.cdx_config,
        args.cdx_receipts,
        args.root,
        args.output,
        selection=args.selection,
        reviewed_sites=args.reviewed_sites,
        prefixes=args.prefixes,
        known_catalog=args.known_catalog,
        existing_contracts=args.existing_contracts,
        reuse_configs=args.reuse_config,
        reuse_receipts=args.reuse_receipts,
        use_cdx_digests=args.use_cdx_digests,
        max_pairs=args.max_pairs,
        controls=args.controls,
        remaining_bytes=args.remaining_bytes,
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("status", "selected_pairs_count", "estimated_transfer_bytes", "batches")
            }
        )
    )
    return 2 if not result["within_budget"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
