"""Screen the complete NTWC index using origin metadata, never arrival tables.

This is an offline metadata gate. Acquisition belongs to the contract runner;
the existing table inventory may run only after the reservation freeze.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_ntwc_batch import reserve_events, verified_text, write_identical_or_new

TIME_TOLERANCE_SECONDS = 120
DISTANCE_TOLERANCE_KM = 150
EARTH_RADIUS_KM = 6371.0088
SOURCE_MAP = "artifacts/generated/ntwc-batch/screen-v1/source-map.json"
CATALOG = "data/raw/usgs/ntwc-1996-2018-m65-all-depth.csv"
SUPPLEMENTS = "data/raw/usgs/screen-v1/supplement-*.csv"
OUTPUT = "artifacts/generated/ntwc-batch/screen-v1"
V2_SEED = "ntwc-all118-metadata-groups-2026-10-31-v2"
GK_CITATION = (
    "https://docs.openquake.org/oq-engine/master/manual/_modules/"
    "openquake/hmtk/seismicity/declusterer/distance_time_windows.html"
)
WC_CITATION = "https://doi.org/10.1785/BSSA0840040974"
# These pages had incidental published-outcome exposure during source research.
# They cannot participate in a previously unexamined holdout draw.
EXPOSED_NEW_EVENTS = frozenset({"usp000db93", "usp0008rpa"})
# Source-summary associations supplement the geometric heuristic. They are not
# declarations that all members share an identical physical rupture mechanism.
SEQUENCE_OVERRIDES = (
    ("usp000juhz", "ak0138esnzr", "Craig/Haida relationship in USGS Craig summary"),
    ("usc000f1s0", "us20002yaw", "USGS Solomon2015 summary places source in Santa Cruz sequence"),
)
MONTHS = (
    "January February March April May June July August September October November December"
).split()
COORDINATES = re.compile(
    r"(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*[°º�]?\s*([NS])"
    r"\s*[,;\s]+\s*(?:Longitude:\s*)?"
    r"([+-]?\d+(?:\.\d+)?)\s*[°º�]?\s*([EW])\b",
    re.I,
)
ORIGIN_TIME = re.compile(
    r"\b(?:at|occurring at|Origin Time:)\s*"
    r"(\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?|\d{6}|\d{4})"
    r"\s*(UTC|GMT|Z)?\b",
    re.I,
)
MAGNITUDE = re.compile(r"\bmagnitude(?:\s+of)?\s+(\d+(?:\.\d+)?)\b", re.I)


class _IntroText(HTMLParser):
    """Discard active content; the caller stops before the first HTML table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.fragments.append(data)


def intro_text(document: str) -> str:
    """Read only text before the first table, including malformed escaped markup."""
    prefix = re.split(r"<table\b", document, maxsplit=1, flags=re.I)[0]
    parser = _IntroText()
    parser.feed(prefix)
    text = html.unescape(" ".join(parser.fragments))
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def index_date(label: str) -> datetime | None:
    """Read the first index date; multi-day/multi-source ambiguity remains explicit."""
    months = "|".join(MONTHS)
    match = re.search(
        rf"\b({months})\s+(\d{{1,2}})(?:-\d{{1,2}})?(?:\s*,)?\s+(\d{{4}})\b",
        label,
        re.I,
    )
    if not match:
        return None
    month = [name.casefold() for name in MONTHS].index(match[1].casefold()) + 1
    return datetime(int(match[3]), month, int(match[2]), tzinfo=UTC)


def extract_origins(text: str, label: str) -> list[dict[str, str]]:
    """Extract source time/location pairs; never use an arrival or peak as origin."""
    day = index_date(label)
    if day is None:
        return []
    result: list[dict[str, str]] = []
    matches = list(ORIGIN_TIME.finditer(text))
    for position, match in enumerate(matches):
        # Restrict to an earthquake origin sentence, before following source/gauge prose.
        before = text[max(0, match.start() - 350) : match.start()]
        if not re.search(r"earthquake|\bquake\b|magnitude", before, re.I):
            continue
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        after = text[match.end() : end]
        coordinate = COORDINATES.search(after[:550])
        if coordinate is None and match[0].lower().startswith("origin time:"):
            coordinate = COORDINATES.search(before)
        if coordinate is None:
            continue
        clock = match[1]
        second_precision = len(clock) == 6 or clock.count(":") == 2
        if ":" in clock:
            parts = [float(value) for value in clock.split(":")]
            hour, minute = int(parts[0]), int(parts[1])
            second = parts[2] if len(parts) == 3 else 0.0
        else:
            hour, minute = int(clock[:2]), int(clock[2:4])
            second = float(clock[4:]) if len(clock) == 6 else 0.0
        if hour > 23 or minute > 59 or second >= 60:
            continue
        latitude = float(coordinate[1]) * (-1 if coordinate[2].upper() == "S" else 1)
        longitude = float(coordinate[3]) * (-1 if coordinate[4].upper() == "W" else 1)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            continue
        magnitudes = list(MAGNITUDE.finditer(before))
        origin_time = day + timedelta(hours=hour, minutes=minute, seconds=second)
        if not match[2]:
            # Keep an unstated timezone naive until an independent review
            # establishes the interpretation from catalog time and location.
            origin_time = origin_time.replace(tzinfo=None)
        result.append(
            {
                "origin_time": origin_time.isoformat(),
                "origin_precision": "second" if second_precision else "minute",
                "latitude": str(latitude),
                "longitude": str(longitude),
                "raw_time": match[0],
                "raw_coordinates": coordinate[0],
                "reported_magnitude": magnitudes[-1][1] if magnitudes else "unknown",
                "time_basis": match[2].upper() if match[2] else "unknown",
            }
        )
    return result


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle screening distance in km, with antimeridian-safe longitude."""
    a, b = math.radians(lat1), math.radians(lat2)
    dlat, dlon = b - a, math.radians((lon2 - lon1 + 180) % 360 - 180)
    hav = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, hav))))


def match_origins(origins: list[dict[str, str]], catalog: list[dict[str, str]]) -> list[str]:
    """Require both source-origin time and location agreement; retain all candidates."""
    candidates: set[str] = set()
    for origin in origins:
        if origin.get("time_basis", "UTC") == "unknown":
            continue
        timestamp = datetime.fromisoformat(origin["origin_time"])
        for row in catalog:
            delta = abs((datetime.fromisoformat(row["time"]) - timestamp).total_seconds())
            if delta > TIME_TOLERANCE_SECONDS:
                continue
            km = distance_km(
                float(origin["latitude"]),
                float(origin["longitude"]),
                float(row["latitude"]),
                float(row["longitude"]),
            )
            if km <= DISTANCE_TOLERANCE_KM:
                candidates.add(row["id"])
    return sorted(candidates)


def pacific_region(row: dict[str, str]) -> str:
    """Conservative source-region screen; marginal boundary calls require overrides.

    These documented boxes are screening heuristics, not an IHO polygon claim.
    Ambiguous Indian/Pacific and subantarctic boundaries are never guessed.
    """
    lat, lon = float(row["latitude"]), float(row["longitude"])
    if lat < -45:
        return "boundary_review" if 120 <= lon or lon <= -145 else "non_pacific"
    if 95 <= lon < 125 and lat < 15:
        return "boundary_review"
    if 125 <= lon <= 180:
        if lat >= 25:
            return "northwest_pacific" if lat < 52 else "alaska_aleutians"
        return "southwest_pacific" if lat < 0 else "western_pacific"
    if -180 <= lon <= -145:
        return "alaska_aleutians" if lat >= 45 else "tonga_kermadec_nz"
    if -145 < lon <= -115 and lat >= 25:
        return "northeast_pacific"
    if -120 <= lon <= -80 and 0 <= lat < 30:
        return "central_america_mexico"
    if -120 <= lon <= -65 and lat < 0:
        return "southeast_pacific"
    return "non_pacific"


def stage_m_reason(row: dict[str, str], region: str) -> str:
    """Return exactly one ordered metadata disposition, preserving source subtypes."""
    if row.get("type") != "earthquake":
        return "not_earthquake_source"
    if region == "non_pacific":
        return "non_pacific"
    if region == "boundary_review":
        return "ambiguous_basin"
    if not row.get("magType", "").casefold().startswith("mw"):
        return "no_mw_family_magnitude"
    magnitude, depth = float(row["mag"]), float(row["depth"])
    if not math.isfinite(magnitude) or not math.isfinite(depth) or depth < 0:
        return "invalid_catalog_metadata"
    if depth > 70:
        return "depth_gt_70"
    if magnitude < 7:
        return "mw_lt_7"
    return "metadata_eligible"


def load_overrides(path: Path) -> dict[str, dict[str, str]]:
    """Require explicit evidence and two distinct reviewers for every exception."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row["archive_key"]
        if key in result:
            raise ValueError(f"duplicate identity override: {key}")
        if not all(row.get(name) for name in ("reason", "citation", "reviewer_1", "reviewer_2")):
            raise ValueError(f"unreviewed identity override: {key}")
        if row["reviewer_1"] == row["reviewer_2"] or any(
            row[name].casefold() in {"pending", "unreviewed", "unknown"}
            for name in ("reviewer_1", "reviewer_2")
        ):
            raise ValueError(f"identity override requires distinct reviewers: {key}")
        result[key] = row
    return result


def screen(root: Path, *, allow_missing: bool = False) -> dict[str, object]:
    """Account for every index entry without importing or calling the arrival parser."""
    sources = cast(
        list[dict[str, str]], json.loads((root / SOURCE_MAP).read_text(encoding="utf-8"))
    )
    if len(sources) != 118 or len({row["archive_key"] for row in sources}) != 118:
        raise ValueError("source map must contain 118 distinct archive entries")
    catalog_text = verified_text(root / CATALOG)
    catalog = list(csv.DictReader(io.StringIO(catalog_text)))
    catalog_sources = {CATALOG: hashlib.sha256((root / CATALOG).read_bytes()).hexdigest()}
    for supplement in sorted(root.glob(SUPPLEMENTS)):
        catalog.extend(csv.DictReader(io.StringIO(verified_text(supplement))))
        catalog_sources[str(supplement.relative_to(root))] = hashlib.sha256(
            supplement.read_bytes()
        ).hexdigest()
    by_id = {row["id"]: row for row in catalog}
    overrides = load_overrides(root / "config/ntwc-identity-overrides.csv")
    dispositions: list[dict[str, str]] = []
    eligible: list[dict[str, str]] = []
    for source in sources:
        row = dict(source)
        row.update(
            event_id="unknown",
            reason="ambiguous_identity",
            identity_status="unresolved",
            candidate_ids="",
            region="unknown",
            flags="",
            origin_evidence="[]",
            component_event_ids="",
            attribution_status="single_source_metadata",
        )
        path = root / source["local_path"]
        if not path.exists():
            if not allow_missing:
                raise ValueError(f"missing contracted page: {path}")
            row["reason"] = "source_unavailable"
            dispositions.append(row)
            continue
        document = verified_text(path)
        row["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        intro = intro_text(document)
        origins = extract_origins(intro, source["label"])
        row["origin_evidence"] = json.dumps(origins, sort_keys=True)
        candidates = match_origins(origins, catalog)
        row["candidate_ids"] = ";".join(candidates)
        key = source["archive_key"]
        if key in {
            "MeteoTsunami5-15-2018",
            "06-13-13",
            "10-18-15_Icy_Bay",
            "Sarigan_05-29-10",
            "08-08-08-Kasatochi",
        }:
            row.update(reason="not_earthquake_source", identity_status="source_class_exclusion")
            dispositions.append(row)
            continue
        override = overrides.get(key)
        if override:
            row.update(
                override_citation=override["citation"],
                override_reviewers=f"{override['reviewer_1']};{override['reviewer_2']}",
                component_event_ids=override.get("component_event_ids", ""),
            )
            if len(row["component_event_ids"].split(";")) > 1:
                row["attribution_status"] = "compound_unresolved"
            if override.get("disposition"):
                row.update(
                    override_candidate_id=override.get("event_id") or "unknown",
                    reason=override["disposition"],
                    identity_status="reviewed_exclusion",
                    flags=override["reason"],
                )
                dispositions.append(row)
                continue
            event_id = override["event_id"]
            if event_id not in by_id:
                raise ValueError(f"override event absent from frozen catalog: {key}: {event_id}")
            row.update(
                event_id=event_id, identity_status="reviewed_override", flags=override["reason"]
            )
        elif len(candidates) == 1:
            row.update(event_id=candidates[0], identity_status="origin_time_and_coordinates")
        else:
            row["flags"] = "multiple_source_candidates" if candidates else "no_unique_origin_match"
            dispositions.append(row)
            continue
        event = by_id[row["event_id"]]
        if source["prior_event_id"] != "unknown" and source["prior_event_id"] != row["event_id"]:
            raise ValueError(f"v1 event identity disagrees with re-screen: {key}")
        region = override.get("region", "") if override else ""
        region = region or pacific_region(event)
        row.update(region=region, reason=stage_m_reason(event, region))
        row.update({f"usgs_{name}": value for name, value in event.items()})
        dispositions.append(row)
        if row["reason"] == "metadata_eligible":
            eligible.append(row.copy())
    return {
        "schema_version": "ntwc-origin-screen-v1",
        "arrival_tables_read": False,
        "source_map_sha256": hashlib.sha256((root / SOURCE_MAP).read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256((root / CATALOG).read_bytes()).hexdigest(),
        "catalog_sources": catalog_sources,
        "identity_overrides_sha256": hashlib.sha256(
            (root / "config/ntwc-identity-overrides.csv").read_bytes()
        ).hexdigest()
        if overrides
        else "none",
        "time_tolerance_seconds": TIME_TOLERANCE_SECONDS,
        "distance_tolerance_km": DISTANCE_TOLERANCE_KM,
        "dispositions": dispositions,
        "eligible_events": eligible,
    }


def write_screen(result: dict[str, object], output: Path) -> None:
    """Publish deterministic, non-overwriting screen artifacts."""
    rows = cast(list[dict[str, str]], result["dispositions"])
    fields = sorted({key for row in rows for key in row})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda row: row["archive_key"]))
    write_identical_or_new(output / "dispositions.csv", stream.getvalue())
    write_identical_or_new(
        output / "screen.json", json.dumps(result, indent=2, sort_keys=True) + "\n"
    )


def sequence_windows(magnitude: float) -> tuple[float, float]:
    """Return heuristic window (days, km), not physical independence guarantees.

    Gardner-Knopoff formula as documented by OpenQuake uses days before its
    conversion to years. Wells-Coppersmith all-slip subsurface length is km:
    log10(L)=-2.44+0.59*M. Applying this crustal regression to megathrusts is an
    explicit extrapolation; these conservative screening groups need sensitivity
    review before claiming independence in model validation.
    """
    days = 10 ** (0.032 * magnitude + 2.7389)
    if magnitude < 6.5:
        days = 10 ** (0.5409 * magnitude - 0.547)
    distance = max(10 ** (0.1238 * magnitude + 0.983), 0.5 * 10 ** (-2.44 + 0.59 * magnitude))
    return days, distance


def sequence_groups(
    events: list[dict[str, str]], catalog: dict[str, dict[str, str]]
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Group source components conservatively, retaining every reason for an edge."""
    parent = {row["event_id"]: row["event_id"] for row in events}
    edges: list[dict[str, object]] = []

    def find(event_id: str) -> str:
        while parent[event_id] != event_id:
            event_id = parent[event_id]
        return event_id

    def join(first: str, second: str, evidence: dict[str, object]) -> None:
        a, b = find(first), find(second)
        parent[max(a, b)] = min(a, b)
        edges.append({"event_a": first, "event_b": second, **evidence})

    # An archive page is one attribution unit even if its introduction describes
    # multiple earthquakes. Components do not become separate usable pairs.
    for position, first in enumerate(events):
        first_ids = set(filter(None, first.get("component_event_ids", "").split(";")))
        first_ids.add(first["event_id"])
        for second in events[position + 1 :]:
            second_ids = set(filter(None, second.get("component_event_ids", "").split(";")))
            second_ids.add(second["event_id"])
            matched = False
            for a_id in sorted(first_ids):
                for b_id in sorted(second_ids):
                    a, b = catalog[a_id], catalog[b_id]
                    magnitude = max(float(a["mag"]), float(b["mag"]))
                    days, km_limit = sequence_windows(magnitude)
                    delta_days = (
                        abs(
                            (
                                datetime.fromisoformat(a["time"])
                                - datetime.fromisoformat(b["time"])
                            ).total_seconds()
                        )
                        / 86400
                    )
                    km = distance_km(
                        float(a["latitude"]),
                        float(a["longitude"]),
                        float(b["latitude"]),
                        float(b["longitude"]),
                    )
                    if delta_days <= days and km <= km_limit:
                        join(
                            first["event_id"],
                            second["event_id"],
                            {
                                "method": "symmetric_GK_plus_half_WC_screening_heuristic",
                                "source_component_a": a_id,
                                "source_component_b": b_id,
                                "delta_days": delta_days,
                                "distance_km": km,
                                "time_window_days": days,
                                "distance_window_km": km_limit,
                                "wc_extrapolation_above_m8": magnitude > 8,
                            },
                        )
                        matched = True
                        break
                if matched:
                    break
    for first, second, reason in SEQUENCE_OVERRIDES:
        if first in parent and second in parent:
            join(
                first,
                second,
                {
                    "method": "reviewed_source_summary_override",
                    "reason": reason,
                    "citation": f"https://earthquake.usgs.gov/fdsnws/event/1/query?eventid={second}&format=geojson",
                },
            )
    return {event_id: "seq-" + find(event_id) for event_id in sorted(parent)}, edges


def assign_roles(events: list[dict[str, str]], groups: dict[str, str]) -> dict[str, object]:
    """Preserve v1 roles; draw only genuinely new metadata groups for v2."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in events:
        grouped.setdefault(groups[row["event_id"]], []).append(row)
    candidates: list[dict[str, str]] = []
    group_roles: dict[str, str] = {}
    for group, members in sorted(grouped.items()):
        prior_roles = {row["prior_role"] for row in members} - {"unassigned", "unknown", ""}
        if "sealed_evaluation" in prior_roles:
            group_roles[group] = "sealed_evaluation"
        elif "development" in prior_roles or any(
            row["event_id"] in EXPOSED_NEW_EVENTS for row in members
        ):
            group_roles[group] = "development"
        else:
            cohorts = {row["cohort"] for row in members}
            cohort = next(iter(cohorts)) if len(cohorts) == 1 else "mixed"
            magnitude = max(
                float(row.get("grouping_magnitude", row["usgs_mag"])) for row in members
            )
            band = "ge7.8" if magnitude >= 7.8 else "lt7.8"
            candidates.append({"event_id": group, "stratum": f"{cohort}:{band}"})
    sizes = Counter(row["stratum"] for row in candidates)
    capacity = sum(max(0, size - 1) for size in sizes.values())
    target = min(round(0.25 * len(candidates)), capacity)
    reserved = reserve_events(candidates, target, stratum_key="stratum", seed=V2_SEED)
    for row in candidates:
        group_roles[row["event_id"]] = (
            "sealed_evaluation" if row["event_id"] in reserved else "development"
        )
    for row in events:
        group = groups[row["event_id"]]
        members = grouped[group]
        old_roles = {member["prior_role"] for member in members} - {"unassigned", "unknown", ""}
        row["sequence_group"] = group
        row["role"] = (
            row["prior_role"]
            if row["prior_role"] in {"development", "sealed_evaluation"}
            else group_roles[group]
        )
        row["role_basis"] = (
            "v1_preserved"
            if row["prior_role"] in {"development", "sealed_evaluation"}
            else "prior_sequence_group"
            if old_roles
            else "prefreeze_outcome_exposure"
            if any(member["event_id"] in EXPOSED_NEW_EVENTS for member in members)
            else "metadata_group_stratified_hash_draw"
        )
        row["sequence_validation_status"] = (
            "within_sequence" if len(members) > 1 else "independent_under_screening_heuristic"
        )
        row["legacy_role_conflict"] = str(len(old_roles) > 1).lower()
    return {
        "new_independent_candidate_groups": len(candidates),
        "reserved_new_groups": len(reserved),
        "strata": dict(sorted(sizes.items())),
        "new_group_target_fraction": 0.25,
    }


def reserve(root: Path, result: dict[str, object], output: Path) -> dict[str, object]:
    """Freeze metadata roles before any new archive table is parsed."""
    dispositions = cast(list[dict[str, str]], result["dispositions"])
    if any(row["identity_status"] == "unresolved" for row in dispositions):
        raise ValueError("unreviewed identity dispositions prevent reservation")
    events = [dict(row) for row in cast(list[dict[str, str]], result["eligible_events"])]
    annotations_path = root / "config/ntwc-event-annotations-v2.csv"
    annotations = {
        row["event_id"]: row for row in csv.DictReader(annotations_path.open(encoding="utf-8"))
    }
    for row in events:
        annotation = annotations[row["event_id"]]
        detail_path = root / annotation["detail_path"]
        verified_text(detail_path)
        if hashlib.sha256(detail_path.read_bytes()).hexdigest() != annotation["detail_sha256"]:
            raise ValueError(f"changed source annotation: {row['event_id']}")
        row.update(
            {
                key: annotation[key]
                for key in ("mechanism_class", "cohort", "citation", "qualification")
            }
        )
        row["archive_source_id"] = row["source_id"]
        row["archive_url"] = row["url"]
        row["name"] = row["label"]
        row["mechanism_status"] = (
            "review_required" if row["cohort"] == "review_required" else "source_summary_reviewed"
        )
    old = cast(
        dict[str, object],
        json.loads((root / "artifacts/generated/ntwc-batch/selection.json").read_text()),
    )
    old_events = cast(list[dict[str, str]], old["events"])
    if {row["event_id"] for row in old_events} - {row["event_id"] for row in events}:
        raise ValueError("Stage-M screening dropped a v1 event; review explicitly before freezing")
    catalog = {row["id"]: row for row in csv.DictReader(io.StringIO(verified_text(root / CATALOG)))}
    for row in events:
        components = set(filter(None, row["component_event_ids"].split(";")))
        components.add(row["event_id"])
        row["grouping_magnitude"] = str(max(float(catalog[key]["mag"]) for key in components))
    groups, edges = sequence_groups(events, catalog)
    draw = assign_roles(events, groups)
    for previous in old_events:
        current = next(row for row in events if row["event_id"] == previous["event_id"])
        if current["role"] != previous["role"]:
            raise ValueError("v1 role changed")
    events.sort(key=lambda row: (row["usgs_time"], row["event_id"]))
    ledger: dict[str, object] = {
        "schema_version": "ntwc-selection-v2",
        "seed": V2_SEED,
        "events": events,
        "v1_selection_sha256": old["selection_sha256"],
        "arrival_tables_read": False,
        "screen_sha256": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
        "annotation_sha256": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
        "grouping_citations": [
            GK_CITATION,
            WC_CITATION,
            "https://pubs.usgs.gov/of/1995/0005/report.pdf",
        ],
        "grouping_limitations": (
            "Symmetric maximum-magnitude windows and transitive closure are "
            "conservative heuristics, not proof of independent physical sequences; WC crustal "
            "scaling extrapolated to megathrusts. Preserve legacy mixed-role groups and report "
            "within-sequence evaluation separately."
        ),
        "sequence_edges": edges,
        "reservation": draw,
        "reviewed_ineligible_uncertainties": [
            {"archive_key": row["archive_key"], "reason": row["reason"]}
            for row in dispositions
            if row["reason"] in {"ambiguous_identity", "ambiguous_basin"}
        ],
        "prefreeze_exposed_new_events": sorted(EXPOSED_NEW_EVENTS),
    }
    digest = hashlib.sha256(
        json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger["selection_sha256"] = digest
    old_config = cast(
        dict[str, object], tomllib.loads((root / "config/ntwc-archive-batch.toml").read_text())
    )
    old_assets = cast(dict[str, dict[str, object]], old_config["assets"])
    template = next(iter(old_assets.values()))
    lines = [
        f'selection_sha256 = "{digest}"',
        f'selection_seed = "{V2_SEED}"',
        'contract_version = "2026-10-31"',
        'selection_design = "All-index metadata screen; retain source uncertainty"',
        "",
    ]
    for row in events:
        lines.append(f"[events.{row['event_id']}]")
        for key in (
            "event_id",
            "name",
            "region",
            "role",
            "archive_source_id",
            "archive_url",
            "usgs_time",
            "usgs_mag",
            "usgs_magType",
            "mechanism_status",
            "cohort",
            "sequence_group",
            "sequence_validation_status",
            "attribution_status",
            "component_event_ids",
        ):
            lines.append(f"{key} = {json.dumps(row[key])}")
        asset = dict(old_assets.get(row["event_id"], template))
        asset.update(
            source_id=row["source_id"],
            url=row["url"],
            local_path=row["local_path"],
            expected_content_signature=(
                f"Reviewed origin metadata for archive {row['archive_key']}; "
                "arrival attribution remains gated"
            ),
        )
        lines.extend(["", f"[assets.{row['event_id']}]"])
        for key, value in asset.items():
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")
    write_identical_or_new(
        output / "selection-v2.json", json.dumps(ledger, indent=2, sort_keys=True) + "\n"
    )
    write_identical_or_new(output / "selection-v2.sha256", digest + "\n")
    write_identical_or_new(root / "config/ntwc-archive-batch-v2.toml", "\n".join(lines))
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["screen", "reserve"], default="screen")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-missing", action="store_true", help="Diagnostic only; never a freeze"
    )
    args = parser.parse_args()
    result = screen(args.root, allow_missing=args.allow_missing)
    write_screen(result, args.output or args.root / OUTPUT)
    if args.stage == "reserve":
        if args.allow_missing:
            raise ValueError("diagnostic missing-source mode cannot freeze roles")
        ledger = reserve(args.root, result, args.output or args.root / OUTPUT)
        print(
            json.dumps(
                {
                    "selection_sha256": ledger["selection_sha256"],
                    "reservation": ledger["reservation"],
                }
            )
        )
    rows = cast(list[dict[str, str]], result["dispositions"])
    counts = {
        reason: sum(row["reason"] == reason for row in rows)
        for reason in sorted({row["reason"] for row in rows})
    }
    print(json.dumps(counts, sort_keys=True))
    return int(any(row["identity_status"] == "unresolved" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
