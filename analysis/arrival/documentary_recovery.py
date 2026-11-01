"""Extract dated forecast instances without repairing unrelated archive cells."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

from analysis.arrival.evidence import Row
from analysis.arrival.lineage import stable_id

MONTHS = {name: number for number, name in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1
)}
OFFSETS = {"UTC": 0, "PST": -8, "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10}
ISSUE = re.compile(
    r"\b(\d{1,2})(\d{2})\s+(AM|PM)\s+(PST|PDT|AKST|AKDT|HST|UTC)\s+"
    r"[A-Z]{3}\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})", re.IGNORECASE
)
LOCAL_FORECAST = re.compile(
    r"([A-Z][A-Z0-9 .'/()-]*?-[A-Z]{2})\s+(\d{4})\s+"
    r"(AKST|AKDT|PST|PDT|HST|UTC)\s+([A-Z]{3})\s+(\d{1,2})\b", re.IGNORECASE
)
PTWC_FORECAST = re.compile(
    r"^(.*?)\s+(\d+\.\d+[NS])\s+(\d+\.\d+[EW])\s+"
    r"(\d{4})Z\s+(\d{1,2})\s+([A-Z]{3})\s*$", re.MULTILINE | re.IGNORECASE
)
JMA_FORECAST = re.compile(
    r"^\s*([A-Z][A-Z0-9_. -]*?)\s+(\d+\.\d+[NS])\s+(\d+\.\d+[EW])\s+"
    r"(\d{4})Z\s+(\d{1,2})\s+([A-Z]{3})\s+[\d.]+M\s*$", re.MULTILINE | re.I
)
START_FORECAST = re.compile(
    r"([A-Z][A-Z0-9 .'/()-]*?)\s+(\d{4})\s+"
    r"(AKST|AKDT|PST|PDT|HST)\s+([A-Z]{3})\s+(\d{1,2})\b", re.IGNORECASE
)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def local_clock(year: int, month: int, day: int, hm: str, zone: str) -> datetime:
    """Convert explicitly named fixed zones; never guess a geographic timezone."""
    return datetime(year, month, day, int(hm[:2]), int(hm[2:]),
                    tzinfo=timezone(timedelta(hours=OFFSETS[zone])))


def native_origins(text: str) -> set[str]:
    """Read explicit UTC origin lines; never substitute the reference origin."""
    origins: set[str] = set()
    for match in re.finditer(r"(\d{4})\s+UTC\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})",
                             text, re.IGNORECASE):
        hm, month, day, year = match.groups()
        origins.add(iso(local_clock(int(year), MONTHS[month.upper()], int(day), hm, "UTC")))
    for match in re.finditer(r"ORIGIN TIME\s*[-:]\s*(\d{4})Z\s+(\d{1,2})\s+"
                             r"([A-Z]{3})\s+(\d{4})", text, re.IGNORECASE):
        hm, day, month, year = match.groups()
        origins.add(iso(local_clock(int(year), MONTHS[month.upper()], int(day), hm, "UTC")))
    return origins


def extract_forecasts(
    text: str, event_id: str, source_id: str, *, reference_origin: str | None = None
) -> list[Row]:
    """Parse original WCATWC and PTWC bulletins, retaining version and issue time.

    Omitted forecast years inherit a dated bulletin only in that same month.
    This deliberately leaves cross-year/month context unresolved.
    """
    records: list[Row] = []
    # A collection may reproduce several original products. No station collapse.
    blocks = re.split(r"(?=TSUNAMI BULLETIN NUMBER|TSUNAMI MESSAGE NUMBER)", text, flags=re.I)
    for block in blocks:
        version = re.match(r"TSUNAMI (?:BULLETIN|MESSAGE) NUMBER\s+(\d+)", block, re.I)
        if not version:
            continue
        origins = native_origins(block)
        if reference_origin is not None:
            reference = datetime.fromisoformat(reference_origin.replace("Z", "+00:00"))
            if len(origins) != 1 or abs((
                datetime.fromisoformat(next(iter(origins)).replace("Z", "+00:00")) - reference
            ).total_seconds()) > 120:
                continue
        issue_match = ISSUE.search(block)
        ptwc_issue = re.search(r"ISSUED AT (\d{4})Z (\d{1,2}) ([A-Z]{3}) (\d{4})", block, re.I)
        if ptwc_issue:
            hm, day, mon, year = ptwc_issue.groups()
            issue = local_clock(int(year), MONTHS[mon.upper()], int(day), hm, "UTC")
            center = "NWPTAC(JMA)" if "NWPTAC(JMA)" in block.upper() else "PTWC"
        elif issue_match:
            hour, minute, ap, zone, mon, day, year = issue_match.groups()
            hour24 = int(hour) % 12 + (12 if ap.upper() == "PM" else 0)
            issue = local_clock(int(year), MONTHS[mon.upper()], int(day),
                                f"{hour24:02}{minute}", zone.upper())
            center = "NTWC" if "NATIONAL TSUNAMI WARNING CENTER" in block.upper() else "WCATWC"
        else:
            continue
        product = f"{center}:{iso(issue)}:{int(version[1])}"
        rows: list[tuple[str, str, str, int, int, str, str, str]] = []
        for match in LOCAL_FORECAST.finditer(block):
            label, clock, zone, mon, day = match.groups()
            rows.append((label.strip(), clock, zone.upper(), MONTHS[mon.upper()], int(day),
                         match[0], "unknown", "unknown"))
        forecast_section = re.search(
            r"FORECASTS OF TSUNAMI ACTIVITY(.*?)(?:OBSERVATIONS OF TSUNAMI|"
            r"TSUNAMI OBSERVATIONS|PRELIMINARY EARTHQUAKE|RECOMMENDED ACTIONS|$$)",
            block, re.DOTALL | re.IGNORECASE
        )
        sections = [forecast_section[1]] if forecast_section else []
        sections.extend(m[0] for m in re.finditer(
            r"ESTIMATED TIMES OF INITIAL WAVE ARRIVAL.*?"
            r"(?=FOR ARRIVAL TIMES AT ADDITIONAL|\$\$|\Z)", block, re.DOTALL | re.I
        ))
        for section in sections:
            matches = list(START_FORECAST.finditer(section))
            clock_count = len(re.findall(
                r"\b\d{4}\s+(?:AKST|AKDT|PST|PDT|HST)\s+[A-Z]{3}\s+\d{1,2}\b",
                section, re.I
            ))
            if len(matches) != clock_count:
                raise ValueError("forecast-section clock accounting failed")
            for match in matches:
                if LOCAL_FORECAST.search(match[0]):
                    continue
                label, clock, zone, mon, day = match.groups()
                rows.append((label.strip(), clock, zone.upper(), MONTHS[mon.upper()], int(day),
                             match[0].strip(), "unknown", "unknown"))
        # PTWC coordinates belong to a forecast point, not an observing deployment.
        if center in {"PTWC", "NWPTAC(JMA)"}:
            pattern = JMA_FORECAST if center == "NWPTAC(JMA)" else PTWC_FORECAST
            for match in pattern.finditer(block):
                prefix, lat, lon, clock, day, mon = match.groups()
                label = re.split(r"\s{2,}", prefix.strip())[-1]
                rows.append((label, clock, "UTC", MONTHS[mon.upper()], int(day), match[0].strip(),
                             lat, lon))
        for position, (label, clock, zone, month, day, excerpt, lat, lon) in enumerate(rows):
            candidate = local_clock(issue.year, month, day, clock, zone)
            utc = "unknown"
            if month == issue.month:
                utc = iso(candidate)
            before = "unknown" if utc == "unknown" else str(iso(issue) <= utc)
            records.append({
                "record_id": stable_id("documentary", source_id, product, str(position)),
                "event_id": event_id, "source_id": source_id, "product_id": product,
                "issuing_center": center, "issue_utc": iso(issue),
                "message_version": str(int(version[1])), "station_label": label,
                "kind": "forecast_start_of_tsunami" if forecast_section
                else "estimated_tsunami_arrival" if center == "NWPTAC(JMA)"
                else "estimated_initial_arrival", "native_clock": clock,
                "native_zone": zone, "native_month": str(month), "native_day": str(day),
                "arrival_utc": utc, "date_basis": "explicit_month_day_same_month_dated_bulletin"
                if utc != "unknown" else "unresolved_cross_month_year",
                "available_before_predicted_arrival": before,
                "latitude_native": lat, "longitude_native": lon,
                "raw_excerpt": excerpt, "model_approved": "False",
                "parent_table_replacement_allowed": "False",
                "independence": "unknown", "deployment_identity": "unknown",
                "native_origin_utc": next(iter(origins)) if len(origins) == 1 else "unknown",
                "reported_resolution_seconds": "60", "pick_uncertainty_seconds": "unknown",
                "issue_native_text": ptwc_issue[0] if ptwc_issue else
                issue_match[0] if issue_match else "unknown",
                "product_heading_native": version[0],
            })
    return records


def observation_day(event_date: str, origin_hm: str, clock: str, travel: str) -> str:
    """A documented native duration and clock must agree before calendar recovery."""
    if clock == "?" or travel == "?":
        return "unknown"
    hour, minute = map(int, travel.split(":"))
    if hour < 0 or not 0 <= minute < 60:
        raise ValueError("invalid documented travel duration")
    origin = datetime.fromisoformat(f"{event_date}T{origin_hm}:00+00:00")
    arrival = origin + timedelta(hours=hour, minutes=minute)
    if arrival.strftime("%H:%M") != clock:
        raise ValueError("documented clock and native travel time disagree")
    return iso(arrival)
