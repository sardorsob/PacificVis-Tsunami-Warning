"""Review full historical location labels without inferring deployment continuity."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from analysis.arrival.evidence import (
    Row,
    checked_path,
    file_manifest,
    read_rows,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)
from analysis.arrival.stations import geographic_signature, geographic_site_id

# These rules propose full-label equivalence; only an independent digest-bound
# review can promote a historical header. Region/subsite words are never dropped.
REPLACEMENTS = {
    "san fransico": "san francisco",
    "cresent city": "crescent city",
    "chatam": "chatham",
    "iquiqui": "iquique",
    "gisborn": "gisborne",
    "lunganville": "luganville",
    "valpariso": "valparaiso",
    "nawilwili": "nawiliwili",
    "fr polynesia": "french polynesia",
    "jp": "japan",
    "nz": "new zealand",
    "n z": "new zealand",
    "png": "papua new guinea",
    "fp": "french polynesia",
    "au": "australia",
    "ph": "philippines",
    "si": "solomon islands",
    "vu": "vanuatu",
    "fj": "fiji",
    "to": "tonga",
    "ki": "kiribati",
    "ak": "alaska",
    "hi": "hawaii",
    "ca": "california",
    "wa": "washington",
    "or": "oregon",
    "bc": "british columbia",
    "b c": "british columbia",
    "is": "island",
    "islands": "island",
}


def label_key(value: str) -> str:
    """Normalize a complete location; do not discard country/island qualifiers."""
    text = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()
    text = " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    for source, replacement in REPLACEMENTS.items():
        text = re.sub(r"\b" + re.escape(source) + r"\b", replacement, text)
    return " ".join(text.split())


def distance_km(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Great-circle diagnostic with explicit coordinate bounds and antimeridian."""
    try:
        a, b, c, d = (
            float(row[key])
            for row, key in [
                (left, "latitude"),
                (left, "longitude"),
                (right, "latitude"),
                (right, "longitude"),
            ]
        )
    except (KeyError, TypeError, ValueError):
        return math.inf
    if (
        not all(math.isfinite(x) for x in [a, b, c, d])
        or max(abs(a), abs(c)) > 90
        or max(abs(b), abs(d)) > 180
    ):
        return math.inf
    a, b, c, d = map(math.radians, [a, b, c, d])
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, h))))


def bounded_clusters(points: list[Row], radius_km: float) -> dict[str, str]:
    """Deterministic complete-link diagnostic; no A–B–C transitive bridge."""
    if not math.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("radius must be finite and positive")
    groups: list[list[Row]] = []
    result: dict[str, str] = {}
    for point in sorted(points, key=lambda row: (row["name_key"], row["id"])):
        match = next(
            (
                group
                for group in groups
                if group[0]["name_key"] == point["name_key"]
                and all(distance_km(point, item) <= radius_km for item in group)
            ),
            None,
        )
        if match is None:
            match = list[Row]()
            groups.append(match)
        match.append(point)
        result[point["id"]] = (
            "sensitivity:"
            + hashlib.sha256(
                json.dumps([radius_km, match[0]["name_key"], match[0]["id"]]).encode()
            ).hexdigest()[:20]
        )
    return result


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, list[str]]] = []
        self.row_id = ""
        self.cells: list[str] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.cells = []
            self.row_id = dict(attrs).get("id") or ""
        elif tag == "td":
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and len(self.cells) >= 8:
            self.rows.append((self.row_id, self.cells))


def parse_uhslc(text: str) -> list[Row]:
    """Retain native station row identity and record coverage, not deployment dates."""
    table = _Table()
    table.feed(text)
    fields = [
        "station_id",
        "gloss_id",
        "name",
        "country",
        "latitude",
        "longitude",
        "record_start",
        "record_end",
    ]
    return [
        {
            **dict(zip(fields, cells[:8], strict=True)),
            "native_row_id": row_id,
            "provider": "UHSLC",
            "deployment_continuity": "unknown",
        }
        for row_id, cells in table.rows
    ]


def validate_alias_review(alternative: dict[str, Any]) -> str:
    """Validate the explicit alias evidence before the existing header validator."""
    review = alternative["label_alias_review"]
    headers = alternative["headers"]
    key = label_key(alternative["report_label"])
    if (
        review.get("method") != "full_location_key_v1"
        or not key
        or not headers
        or any(label_key(header["header_name"]) != key for header in headers)
    ):
        raise ValueError("reviewed full location conflicts with native header")
    if not alternative.get("registry_id_checks") and not review.get("ncei"):
        raise ValueError("reviewed alias has no geographic corroboration")
    for row in review.get("ncei", []):
        if (
            row["event_id"] != alternative["event_id"]
            or label_key(row["location"] + " " + row["country"]) != key
            or any(distance_km(row, header) > 5 for header in headers)
        ):
            raise ValueError("NCEI alias corroboration conflicts with full location")
    return str(headers[0]["header_name"])


def _registries(root: Path) -> list[Row]:
    result: list[Row] = []
    definitions = [
        ("coops-historicwl-list-20261031.json", "CO-OPS"),
        ("ioc-ssc-20261031.json", "IOC-SSC"),
        ("uhslc-fast-delivery-stations-20261031.html", "UHSLC"),
    ]
    for name, provider in definitions:
        path = checked_path(root, "data/raw/registries/" + name)
        digest = sha256(path)
        if path.with_name(path.name + ".sha256").read_text().strip().split()[0] != digest:
            raise ValueError("registry checksum conflict")
        text = path.read_text(encoding="utf-8")
        if provider == "UHSLC":
            records = parse_uhslc(text)
        else:
            raw = json.loads(text)
            records = [
                {
                    "station_id": str(r.get("id", r.get("ssc_id", "unknown"))),
                    "name": str(r.get("name", "unknown")),
                    "country": str(r.get("country", r.get("state", "unknown"))),
                    "latitude": str(r.get("lat", r.get("geo:lat", "unknown"))),
                    "longitude": str(r.get("lng", r.get("geo:lon", "unknown"))),
                }
                for r in (raw["stations"] if provider == "CO-OPS" else raw)
            ]
        result.extend(
            {
                **row,
                "provider": provider,
                "source_path": str(path.relative_to(root)),
                "source_sha256": digest,
                "coordinate_crs": "unknown",
                "deployment_continuity": "unknown",
            }
            for row in records
        )
    return result


def build_registry(
    inputs: Path, output: Path, *, radii_km: tuple[float, ...], review_path: Path | None = None
) -> Path:
    """Propose source-pinned header aliases; apply only independently reviewed digests."""
    from analysis.arrival.stations import validate_reviewed_site_evidence

    document = verify_inputs(inputs)
    root = Path(document["root"])
    if output.exists() or radii_km != (1, 2, 5):
        raise ValueError("fresh output and frozen1/2/5km sensitivity required")
    baseline = read_rows(checked_path(root, document["crosswalk"] + "/unique_report_crosswalk.csv"))
    native = read_rows(checked_path(root, document["ncei"] + "/observations.csv.gz"))
    registries = _registries(root)
    ledger = {
        row["source_id"]: row
        for row in read_rows(root / "artifacts/provenance/paper-source-manifest-v2.csv")
    }
    checked_sources: set[str] = set()
    ncei_by_event: dict[str, list[Row]] = defaultdict(list)
    for row in native:
        ncei_by_event[row["development_event_id"]].append(row)
    crosswalk = copy.deepcopy(baseline)
    proposals: list[Row] = []
    for row in crosswalk:
        if row["review_status"] == "independently_reviewed":
            validate_reviewed_site_evidence(row)
            continue
        alternatives = json.loads(row["evidence"])
        updated: list[dict[str, Any]] = []
        for alternative in alternatives:
            headers = alternative.get("headers", [])
            key = label_key(alternative["report_label"])
            if not headers or any(label_key(h["header_name"]) != key for h in headers):
                break
            if len({json.dumps(geographic_signature(h), sort_keys=True) for h in headers}) != 1:
                break
            for header in headers:
                sid = header["source_id"]
                source = ledger.get(sid)
                if source is None or source["url"] != header["source_url"]:
                    raise ValueError("linked historical header source not in provenance ledger")
                if sid not in checked_sources:
                    if sha256(checked_path(root, source["local_path"])) != header["sha256"]:
                        raise ValueError("historical header hash conflict")
                    checked_sources.add(sid)
            header = headers[0]
            matches = (
                [
                    r
                    for r in registries
                    if r["provider"] == "CO-OPS"
                    and r["station_id"] == str(header["header_station_id"])
                ]
                if (header["provider"] in {"NOS", "NOAA", "CO-OPS"})
                else []
            )
            if matches and any(distance_km(header, r) > 2 for r in matches):
                break
            corroboration = [
                {
                    "event_id": r["development_event_id"],
                    "runup_id": r["ncei_runup_id"],
                    "source_id": r["source_id"],
                    "source_sha256": r["source_sha256"],
                    "location": r["native_locationName"],
                    "country": r["native_country"],
                    "latitude": r["native_latitude"],
                    "longitude": r["native_longitude"],
                }
                for r in ncei_by_event[row["event_id"]]
                if label_key(r["native_locationName"] + " " + r["native_country"]) == key
                and distance_km(
                    header, {"latitude": r["native_latitude"], "longitude": r["native_longitude"]}
                )
                <= 5
            ]
            if not matches and not corroboration:
                break
            scope = "authoritative_provider_site" if matches else "source_qualified_geographic_site"
            site = (
                "coops:" + str(header["header_station_id"])
                if matches
                else geographic_site_id(header)
            )
            alternative.update(
                {
                    "identity_scope": scope,
                    "identity_basis": "reviewed_full_label_alias_v1",
                    "physical_site_id": site,
                    "geographic_signature": geographic_signature(header),
                    "registry_id_checks": matches,
                    "label_alias_review": {"method": "full_location_key_v1", "ncei": corroboration},
                }
            )
            updated.append(alternative)
        if (
            len(updated) != len(alternatives)
            or not updated
            or len({alt["physical_site_id"] for alt in updated}) != 1
        ):
            continue
        first = updated[0]
        header = first["headers"][0]
        evidence = json.dumps(updated, sort_keys=True)
        row.update(
            {
                "identity_tier": "header_exact",
                "identity_scope": first["identity_scope"],
                "identity_basis": first["identity_basis"],
                "physical_site_id": first["physical_site_id"],
                "provider": "CO-OPS" if first["registry_id_checks"] else header["provider"],
                "provider_station_id": (
                    "unknown"
                    if str(header["header_station_id"]).casefold()
                    in {"none", "unknown", "n/a", "na"}
                    else str(header["header_station_id"])
                ),
                "event_site_identity_verified": "True",
                "evidence": evidence,
                "identity_evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            }
        )
        validate_reviewed_site_evidence({**row, "review_status": "independently_reviewed"})
        proposals.append(
            {
                "event_id": row["event_id"],
                "report_id": row["report_id"],
                "identity_evidence_sha256": row["identity_evidence_sha256"],
                "physical_site_id": row["physical_site_id"],
                "decision": "pending",
                "reviewer": "unknown",
                "evidence": evidence,
            }
        )
    review_rows = read_rows(review_path) if review_path else []
    reviews = {r["report_id"]: r for r in review_rows}
    if len(reviews) != len(review_rows):
        raise ValueError("duplicate identity review")
    candidates = {r["report_id"]: r for r in proposals}
    if not reviews.keys() <= candidates.keys():
        raise ValueError("review contains non-candidate report")
    for row in crosswalk:
        if row["report_id"] not in reviews:
            continue
        review = reviews[row["report_id"]]
        if review["event_id"] != row["event_id"] or (
            review["identity_evidence_sha256"] != row["identity_evidence_sha256"]
        ):
            raise ValueError("review digest mismatch")
        if review["decision"] not in {"approved", "rejected"} or review["reviewer"] in {
            "",
            "unknown",
        }:
            raise ValueError("review decision/reviewer required")
        row["review_status"] = (
            "independently_reviewed" if review["decision"] == "approved" else "rejected"
        )
        row["reviewer"] = review["reviewer"]
        row["site_identity_fit_tier"] = str(review["decision"] == "approved")
    links = [
        {
            "source_record_id": r["report_id"],
            "event_id": r["event_id"],
            "physical_site_id": r["physical_site_id"]
            if r["review_status"] == "independently_reviewed"
            else "unknown",
            "proposed_physical_site_id": r["physical_site_id"],
            "source_family": "NTWC",
            "decision": "accepted"
            if r["review_status"] == "independently_reviewed"
            else "unresolved",
            "review_status": r["review_status"],
            "identity_evidence_sha256": r["identity_evidence_sha256"],
            "deployment_continuity": "unknown",
        }
        for r in crosswalk
    ]
    points: list[Row] = []
    for row in native:
        key = label_key(row["native_locationName"] + " " + row["native_country"])
        position = {"latitude": row["native_latitude"], "longitude": row["native_longitude"]}
        site = "unknown"
        if math.isfinite(distance_km(position, position)):
            site = (
                "ncei-native:"
                + hashlib.sha256(
                    json.dumps([key, position, row["measurement_family"]], sort_keys=True).encode()
                ).hexdigest()[:20]
            )
            points.append(
                {
                    "id": row["source_record_id"],
                    "name_key": row["measurement_family"] + ":" + key,
                    **position,
                }
            )
        links.append(
            {
                "source_record_id": row["source_record_id"],
                "event_id": row["development_event_id"],
                "physical_site_id": site,
                "source_family": "NCEI",
                "decision": "source_native_position" if site != "unknown" else "unresolved",
                "review_status": "native_coordinate_not_deployment_review",
                "identity_evidence_sha256": row["source_sha256"],
                "deployment_continuity": "unknown",
            }
        )
    sensitivity = [
        {
            "source_record_id": key,
            "radius_km": str(radius),
            "cluster_id": value,
            "meaning": "diagnostic_complete_link_not_identity_approval",
        }
        for radius in radii_km
        for key, value in bounded_clusters(points, radius).items()
    ]
    write_rows(output / "registry_records.csv.gz", registries)
    write_rows(output / "site_links.csv.gz", links)
    write_rows(output / "crosswalk.csv", crosswalk)
    write_rows(output / "proposed_reviews.csv", proposals)
    write_rows(output / "spatial_sensitivity.csv.gz", sensitivity)
    # Source records retain individual coordinates even when sensitivity keys agree.
    write_rows(output / "native_positions.csv.gz", points)
    write_json(
        output / "data_dictionary.json",
        {
            "evidence_alternative_status": "Original v3 status; see reviewed identity_basis.",
            "site_identity_fit_tier": "Geography reviewed; other approvals remain False.",
            "spatial_sensitivity": "Complete-link diagnostic, without identity approval.",
            "native_positions": "Native coordinates; CRS/datum/precision unknown.",
        },
    )
    write_json(
        output / "summary.json",
        {
            "baseline_reviewed": sum(
                r["review_status"] == "independently_reviewed" for r in baseline
            ),
            "proposed_promotions": len(proposals),
            "reviewed_reports": sum(r["decision"] == "accepted" for r in links),
            "source_records": len(links),
            "registries": dict(Counter(r["provider"] for r in registries)),
            "clock_fields_used_for_identity": False,
            "model_eligible": False,
            "physical_onset_validated": False,
        },
    )
    write_json(
        output / "manifest.json",
        {
            "inputs_sha256": sha256(inputs),
            "files": file_manifest(output),
            "review_sha256": sha256(review_path) if review_path else "unknown",
            "source_ledger_sha256": sha256(
                root / "artifacts/provenance/paper-source-manifest-v2.csv"
            ),
            "code_sha256": {
                str(path.relative_to(root)): sha256(path)
                for path in [
                    root / "analysis/arrival/site_registry.py",
                    root / "analysis/arrival/stations.py",
                    root / "scripts/build_arrival_site_registry.py",
                ]
            },
        },
    )
    return output / "manifest.json"
