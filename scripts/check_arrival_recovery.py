"""Check a recovered corpus and publish target-specific descriptive support.

No scientific labels are generated here. Graph ranks describe repeated event/site
support; they do not establish posterior identifiability or model eligibility.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import statistics
import sys
import tempfile
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.design import incidence_rank  # noqa: E402
from analysis.arrival.stations import validate_reviewed_site_evidence  # noqa: E402

TARGETS = {
    "T-OBS": "reported_duration_from_reviewed_reference_v1",
    "T-CAL": "reported_absolute_difference_v1",
}
RAW_FIELDS = (
    "source_id",
    "source_sha256",
    "table_index",
    "row_index",
    "header_family",
    "structural_status",
    "estimated_raw",
    "observed_raw",
    "legacy_arrival_raw",
    "legacy_eta_raw",
    "raw_row_json",
)
UNKNOWN = {"", "unknown"}
EXACT = "exact_reported_timestamp"


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _index(
    rows: list[dict[str, str]], keys: tuple[str, ...]
) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in keys)
        if any(not value for value in key) or key in result:
            raise ValueError(f"missing or duplicate record key: {key}")
        result[key] = row
    return result


def _strings(raw: str) -> list[str]:
    value: Any = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("expected JSON string list")
    values = cast(list[Any], value)
    if not all(isinstance(item, str) for item in values):
        raise ValueError("expected JSON string list")
    return cast(list[str], values)


def _stamp(raw: str) -> datetime | None:
    if raw in UNKNOWN:
        return None
    result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise ValueError("timestamp must explicitly use UTC")
    return result


def _native_day_agrees(raw: str, stamp: datetime) -> bool:
    match = re.fullmatch(
        r"\s*(?P<clock>\d{4}|\d{1,2}:\d{2})\s*\((?:JD\s*)?(?P<day>\d{1,3})\)\s*",
        raw,
        re.I,
    )
    if match is None:
        return False
    clock = match["clock"].replace(":", "").zfill(4)
    return (
        int(clock[:2]) == stamp.hour
        and int(clock[2:]) == stamp.minute
        and int(match["day"]) == stamp.timetuple().tm_yday
        and stamp.second == stamp.microsecond == 0
    )


def _inline_literal_agrees(
    raw: str,
    stamp: datetime,
    context: dict[str, str],
    review: dict[str, str],
) -> bool:
    """Compare literal source fields independently of the recovered parser."""
    fields = raw.split()
    if len(fields) != 2:
        return False
    date_index = next(
        (
            index
            for index, field in enumerate(fields)
            if re.fullmatch(r"\d{1,2}[-/]\d{1,2}(?:[-/](?:\d{2}|\d{4}))?", field)
        ),
        None,
    )
    if date_index is None:
        return False
    date_parts = re.split(r"[-/]", fields[date_index])
    clock = fields[1 - date_index]
    if not re.fullmatch(r"\d{4}|\d{1,2}:\d{2}", clock):
        return False
    clock = clock.replace(":", "").zfill(4)
    month, day = int(date_parts[0]), int(date_parts[1])
    if (month, day, int(clock[:2]), int(clock[2:]), 0, 0) != (
        stamp.month,
        stamp.day,
        stamp.hour,
        stamp.minute,
        stamp.second,
        stamp.microsecond,
    ):
        return False
    base_year = int(context["calendar_year"])
    origin = _stamp(context["origin_utc"])
    if origin is None:
        return False
    boundary = (origin.month, month) in {(12, 1), (1, 12)}
    adjacent_year = base_year + (1 if origin.month == 12 else -1)
    if len(date_parts) == 3:
        literal = date_parts[2]
        possible = {base_year, adjacent_year} if boundary else {base_year}
        years = {
            year
            for year in possible
            if (year == int(literal) if len(literal) == 4 else year % 100 == int(literal))
        }
        return years == {stamp.year}
    if boundary:
        # Recovered timestamps never supply missing-year rollover authority.
        return review.get("rollover_year") == str(adjacent_year) and stamp.year == adjacent_year
    return stamp.year == base_year


def _reviewed(site: dict[str, str]) -> bool:
    return (
        site.get("review_status") == "independently_reviewed"
        and site.get("event_site_identity_verified") == "True"
        and site.get("physical_site_id", "unknown") not in UNKNOWN
    )


def _write(stage: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (stage / f"{name}.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if rows:
        with (stage / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(value, sort_keys=True)
                        if isinstance(value, (list, dict))
                        else value
                        for key, value in row.items()
                    }
                )


def _support(
    target: str, records: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    edges = {(row["event_id"], row["physical_site_id"]) for row in records}
    graph = incidence_rank(edges)
    events, sites = {event for event, _ in edges}, {site for _, site in edges}
    folds: list[dict[str, Any]] = []
    for kind, index, held_values in (("LOEO", 0, events), ("LOSO", 1, sites)):
        for held in sorted(held_values):
            training = {edge for edge in edges if edge[index] != held}
            rank = incidence_rank(training)
            folds.append(
                dict(
                    target_id=target,
                    target_version=TARGETS[target],
                    fold=kind,
                    held_out=held,
                    held_out_edges=len(edges - training),
                    training_edges=len(training),
                    training_events=rank["events"],
                    training_sites=rank["sites"],
                    training_components=rank["components"],
                    active_columns=rank["active_columns"],
                    indicator_matrix_rank=rank["indicator_matrix_rank"],
                    fixed_full_design_columns=graph["active_columns"],
                    fixed_columns_nullity=graph["active_columns"] - rank["indicator_matrix_rank"],
                    unseen_events=sorted(events - {event for event, _ in training}),
                    unseen_sites=sorted(sites - {site for _, site in training}),
                )
            )
    degrees: list[dict[str, Any]] = [
        dict(
            target_id=target,
            physical_site_id=site,
            event_degree=sum(linked == site for _, linked in edges),
            events=sorted(event for event, linked in edges if linked == site),
        )
        for site in sorted(sites)
    ]
    result: dict[str, Any] = dict(
        target_version=TARGETS[target],
        eligible_reports=len(records),
        graph=graph,
        median_site_event_degree=statistics.median(r["event_degree"] for r in degrees)
        if degrees
        else None,
        repeated_sites=sum(r["event_degree"] > 1 for r in degrees),
        network_by_identity_scope={
            scope: incidence_rank(
                {
                    (row["event_id"], row["physical_site_id"])
                    for row in records
                    if row["identity_scope"] == scope
                }
            )
            for scope in sorted({row["identity_scope"] for row in records})
        },
        network_by_time_evidence={
            tier: incidence_rank(
                {
                    (row["event_id"], row["physical_site_id"])
                    for row in records
                    if row["time_evidence_tier"] == tier
                }
            )
            for tier in sorted({row["time_evidence_tier"] for row in records})
        },
    )
    return result, folds, degrees


def check_recovery(
    corpus: Path,
    baseline: Path,
    events_config: Path,
    output: Path,
    *,
    root: Path | None = None,
    crosswalk: Path | None = None,
    time_evidence: Path | None = None,
    time_context: Path | None = None,
) -> dict[str, Any]:
    """Validate conserved evidence and publish new descriptive target support.

    Raises:
        ValueError: Counts, source hashes, typed target gates or recovered clocks disagree.
        FileExistsError: The immutable output already exists.
    """
    root = (root or Path.cwd()).resolve()
    corpus, baseline, output = corpus.resolve(), baseline.resolve(), output.resolve()
    events_config = events_config.resolve()
    if output.exists():
        raise FileExistsError(output)
    hashes: dict[str, str] = {}

    def pin(path: Path, expected: str = "") -> Path:
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("input path escapes project root")
        digest = _sha(path)
        if expected and digest != expected:
            raise ValueError(f"checksum mismatch: {path.relative_to(root)}")
        key = path.relative_to(root).as_posix()
        if key in hashes and hashes[key] != digest:
            raise ValueError("input changed during recovery QA")
        hashes[key] = digest
        return path

    document: dict[str, Any] = tomllib.loads(pin(events_config).read_text(encoding="utf-8"))
    metadata: dict[str, dict[str, Any]] = {}
    for raw in document["events"].values():
        event_metadata: dict[str, Any] = raw
        if event_metadata["event_id"] in metadata:
            raise ValueError("duplicate event identity")
        metadata[event_metadata["event_id"]] = event_metadata
    development = {eid for eid, event in metadata.items() if event["role"] == "development"}
    reserved = {eid for eid, event in metadata.items() if event["role"] == "sealed_evaluation"}

    def guard(row: dict[str, Any]) -> None:
        if row["event_id"] not in development or row.get("role", "development") != "development":
            raise ValueError("reserved, unknown or mismatched event identity")
        for flag in ("model_eligible", "physical_onset_validated"):
            if flag in row and row[flag] != "False":
                raise ValueError(f"scientific approval must remain false: {flag}")

    def load(
        directory: Path, candidate: bool
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
        summary: dict[str, Any] = json.loads(
            pin(directory / "summary.json").read_text(encoding="utf-8")
        )
        if summary["input_sha256"]["config"] != _sha(events_config):
            raise ValueError("corpus/config checksum mismatch")
        for relative, digest in summary["output_sha256"].items():
            path = Path(relative)
            if path.is_absolute() or path.parts[0] not in development or ".." in path.parts:
                raise ValueError("corpus manifest includes non-development or escaping path")
            pin(directory / path, digest)
        if set(summary["events"]) != development:
            raise ValueError("corpus event accounting differs from development config")
        tables: dict[str, list[dict[str, str]]] = {
            name: [] for name in ("event", "arrival_report", "pair", "site")
        }
        if candidate:
            tables.update(reported_time_value=[], target_eligibility=[])
        for event in sorted(development):
            for table, rows in tables.items():
                relative = f"{event}/{table}.csv.gz"
                if relative not in summary["output_sha256"]:
                    raise ValueError("required corpus table missing from manifest")
                for row in _read_csv(directory / relative):
                    guard(row)
                    if row["event_id"] != event:
                        raise ValueError("table event disagrees with directory")
                    rows.append(row)
        return summary, tables

    old_summary, old = load(baseline, False)
    summary, current = load(corpus, True)
    old_reports = _index(old["arrival_report"], ("report_id",))
    reports = _index(current["arrival_report"], ("report_id",))
    pairs = _index(current["pair"], ("report_id",))
    old_pairs = _index(old["pair"], ("report_id",))
    sites = _index(current["site"], ("report_id",))
    old_sites = _index(old["site"], ("report_id",))
    events = _index(current["event"], ("event_id",))
    values = _index(current["reported_time_value"], ("report_id", "field_role"))
    targets = _index(current["target_eligibility"], ("report_id", "target_id"))
    if set(reports) != set(old_reports) or not set(old_pairs) <= set(pairs):
        raise ValueError("report IDs or baseline pairs were lost")
    if set(old_pairs) != {
        key
        for key, row in old_reports.items()
        if _stamp(row["estimated_utc"]) is not None and _stamp(row["observed_utc"]) is not None
    }:
        raise ValueError("baseline pair ledger does not conserve its exact report clocks")
    if set(events) != {(eid,) for eid in development}:
        raise ValueError("event table conservation failed")
    if set(values) != {(rid[0], side) for rid in reports for side in ("estimated", "observed")}:
        raise ValueError("reported-time value conservation failed")
    if set(targets) != {(rid[0], target) for rid in reports for target in TARGETS}:
        raise ValueError("target eligibility conservation failed")
    if not set(sites) <= set(reports) or not set(pairs) <= set(reports):
        raise ValueError("orphan site or pair record")
    for key, prior_pair in old_pairs.items():
        if any(
            prior_pair[field] != pairs[key][field]
            for field in ("event_id", "source_id", "source_sha256", "estimated_utc", "observed_utc")
        ):
            raise ValueError("baseline exact pair source or clocks changed")
    contracts = {asset["source_id"]: asset for asset in document["assets"].values()}
    for report in reports.values():
        contract = contracts[report["source_id"]]
        pin(root / contract["local_path"], report["source_sha256"])

    evidence: dict[tuple[str, ...], dict[str, str]] = {}
    if time_evidence is None:
        time_evidence = root / "config/ntwc-time-evidence-v1.csv"
    evidence_rows = _read_csv(pin(time_evidence, summary["input_sha256"]["time_evidence"]))
    evidence = _index(evidence_rows, ("evidence_id",))
    for entry in evidence.values():
        guard(entry)
        if entry["review_status"] != "independently_reviewed" or not entry["reviewer"]:
            raise ValueError("time evidence lacks independent review")
        pin(root / entry["source_path"], entry["source_sha256"])
        _strings(entry["rule_ids"])
        if not json.loads(entry["evidence_locator_json"]):
            raise ValueError("time evidence lacks source locators")
    if summary.get("time_evidence_records") != len(evidence):
        raise ValueError("time evidence counter mismatch")
    calendar: dict[tuple[str, ...], dict[str, str]] = {}
    if "time_context" in summary["input_sha256"]:
        time_context = time_context or root / "config/ntwc-reported-clock-context-v2.csv"
        calendar = _index(
            _read_csv(pin(time_context, summary["input_sha256"]["time_context"])), ("event_id",)
        )
        for key, entry in calendar.items():
            guard(entry)
            origin = events[key]
            if any(
                origin[f"elapsed_{field}"] != entry[field]
                for field in ("origin_utc", "origin_basis", "origin_provenance")
            ):
                raise ValueError("event reference origin disagrees with pinned calendar context")
    if crosswalk is not None:
        crosswalk_rows = _read_csv(pin(crosswalk, summary["input_sha256"]["crosswalk"]))
        reviewed = _index(crosswalk_rows, ("report_id",))
        if set(reviewed) != set(reports):
            raise ValueError("crosswalk report conservation failed")
        for key, row in reviewed.items():
            guard(row)
            if row["event_id"] != reports[key]["event_id"]:
                raise ValueError("crosswalk event/report mismatch")
            if _reviewed(row):
                validate_reviewed_site_evidence(cast(dict[str, Any], row))
            if key in sites and _reviewed(sites[key]):
                if not _reviewed(row) or row["physical_site_id"] != sites[key]["physical_site_id"]:
                    raise ValueError("corpus geography differs from reviewed crosswalk")

    delta: list[dict[str, Any]] = []
    views: dict[str, list[dict[str, Any]]] = {target: [] for target in TARGETS}
    observed_exact = qualified = promoted_clocks = 0
    for key, report in sorted(reports.items()):
        rid, event = key[0], report["event_id"]
        prior, site = old_reports[key], sites.get(key, {})
        if prior["event_id"] != event or any(prior[f] != report[f] for f in RAW_FIELDS):
            raise ValueError("raw report evidence changed")
        origin = events[(event,)]
        old_exact_pair = key in old_pairs
        new_exact_pair = key in pairs
        item: dict[str, Any] = dict(
            report_id=rid,
            event_id=event,
            source_id=report["source_id"],
            source_sha256=report["source_sha256"],
            raw_row_sha256=hashlib.sha256(report["raw_row_json"].encode()).hexdigest(),
            old_pair=old_exact_pair,
            new_pair=new_exact_pair,
            promoted_pair=new_exact_pair and not old_exact_pair,
            old_time_rule_id=prior["time_rule_id"],
            new_time_rule_id=report["time_rule_id"],
            physical_site_id=site.get("physical_site_id", "unknown"),
        )
        roles = {"estimated": "estimate", "observed": "observed"}
        for side, state_field in roles.items():
            value = values[(rid, side)]
            raw_field = (
                ("legacy_eta_raw" if side == "estimated" else "legacy_arrival_raw")
                if (report["header_family"].startswith("arrival_eta_"))
                else f"{side}_raw"
            )
            if (
                value["event_id"] != event
                or value["source_id"] != report["source_id"]
                or value["source_sha256"] != report["source_sha256"]
                or value["raw_value"] != report[raw_field]
                or value["state"] != report[f"{state_field}_state"]
                or value["timestamp_utc"] != report[f"{side}_utc"]
            ):
                raise ValueError("reported value/report source, state or timestamp mismatch")
            stamp = _stamp(value["timestamp_utc"])
            if (value["state"] == EXACT) != (stamp is not None):
                raise ValueError("exact-state/timestamp mismatch")
            if stamp is not None and (
                int(value["hour"]) != stamp.hour
                or int(value["minute"]) != stamp.minute
                or (
                    value["day_of_year"] not in UNKNOWN
                    and int(value["day_of_year"]) != stamp.timetuple().tm_yday
                )
            ):
                raise ValueError("exact timestamp disagrees with typed source components")
            if (value["state"] == "qualified_value" and not value["qualifier"]) or (
                value["state"] == "footnoted_value" and not value["footnote"]
            ):
                raise ValueError("qualifier or footnote annotation was lost")
            if stamp is not None and (
                re.search(r"[?~≈]|approx", value["raw_value"], re.I) or "*" in value["raw_value"]
            ):
                raise ValueError("qualified source clock promoted to exact")
            if value["qualifier"] or value["footnote"]:
                qualified += 1
                if stamp is not None:
                    raise ValueError("qualified or footnoted timestamp promoted to exact")
            before = _stamp(prior[f"{side}_utc"])
            if before is not None and before != stamp:
                raise ValueError("baseline exact reported timestamp changed")
            promoted = before is None and stamp is not None
            if promoted:
                review = evidence.get((value["evidence_id"],))
                native_calendar = calendar.get((event,))
                reviewed_native = (
                    value["rule_id"] == "reported_hhmm_explicit_doy_v1"
                    and report["header_family"].endswith("_jday")
                    and native_calendar is not None
                    and report["source_sha256"] in native_calendar["calendar_year_provenance"]
                    and stamp is not None
                    and stamp.year == int(native_calendar["calendar_year"])
                    and _native_day_agrees(value["raw_value"], stamp)
                )
                scoped = (
                    review is not None
                    and all(
                        review[f] == report[f]
                        for f in (
                            "event_id",
                            "source_id",
                            "source_sha256",
                            "table_index",
                            "header_family",
                        )
                    )
                    and set(value["rule_id"].split("+")) <= set(_strings(review["rule_ids"]))
                )
                if not (scoped or reviewed_native):
                    raise ValueError("promoted clock lacks matching source-scoped time evidence")
                if scoped:
                    assert review is not None and stamp is not None
                    context_bound = (
                        native_calendar is not None
                        and report["source_sha256"] in native_calendar["calendar_year_provenance"]
                    )
                    literal_agrees = False
                    if context_bound and native_calendar is not None:
                        if "inline_month_day_v1" in value["rule_id"].split("+"):
                            literal_agrees = _inline_literal_agrees(
                                value["raw_value"], stamp, native_calendar, review
                            )
                        elif "source_doy_semantics_v1" in value["rule_id"].split("+"):
                            literal_agrees = _native_day_agrees(
                                value["raw_value"], stamp
                            ) and stamp.year == int(native_calendar["calendar_year"])
                    if not literal_agrees:
                        raise ValueError("promoted clock disagrees with source literal/calendar")
                promoted_clocks += 1
            item.update(
                {
                    f"old_{side}_state": prior[f"{state_field}_state"],
                    f"new_{side}_state": value["state"],
                    f"old_{side}_utc": prior[f"{side}_utc"],
                    f"new_{side}_utc": value["timestamp_utc"],
                    f"{side}_rule_id": value["rule_id"],
                    f"{side}_evidence_id": value["evidence_id"],
                    f"{side}_promoted": promoted,
                }
            )
        rules: set[str] = set()
        for side in roles:
            rules.update(values[(rid, side)]["rule_id"].split("+"))
        if set(report["time_rule_id"].split("+")) != rules:
            raise ValueError("report time rule does not conserve its field-specific rules")
        obs, est = _stamp(report["observed_utc"]), _stamp(report["estimated_utc"])
        observed_exact += obs is not None
        if new_exact_pair != (obs is not None and est is not None) or new_exact_pair != (
            report["disposition"] == "exact_reported_pair"
        ):
            raise ValueError("pair ledger does not conserve exact reported clocks")
        if new_exact_pair:
            pair = pairs[key]
            if any(
                pair[field] != report[field]
                for field in (
                    "event_id",
                    "source_id",
                    "source_sha256",
                    "estimated_utc",
                    "observed_utc",
                    "time_rule_id",
                )
            ) or pair["physical_site_id"] != site.get("physical_site_id", "unknown"):
                raise ValueError("pair source, clocks, rule or site mismatch")
        for target in TARGETS:
            eligible = targets[(rid, target)]
            reasons: list[str] = []
            if report["structural_status"] != "accepted_source_row":
                reasons.append("structural_or_header_unresolved")
            if metadata[event].get("attribution_status") != "single_source_metadata":
                reasons.append("event_attribution_unresolved")
            if not _reviewed(site):
                reasons.append("geographic_identity_unreviewed")
            if obs is None:
                reasons.append("observed:" + report["observed_state"])
            reference = _stamp(origin["elapsed_origin_utc"])
            if target == "T-OBS":
                if (
                    reference is None
                    or origin["elapsed_origin_basis"] in UNKNOWN
                    or origin["elapsed_origin_provenance"] in UNKNOWN
                ):
                    reasons.append("reference_origin_unreviewed")
                elif obs is not None and obs <= reference:
                    reasons.append("observed:nonpositive_elapsed")
            elif est is None:
                reasons.append("estimate:" + report["estimate_state"])
            if (
                eligible["event_id"] != event
                or eligible["target_version"] != TARGETS[target]
                or eligible["eligible"] not in {"True", "False"}
                or (eligible["eligible"] == "True") != (not reasons)
                or set(_strings(eligible["reason_codes"])) != set(reasons)
                or eligible["physical_site_id"] != site.get("physical_site_id", "unknown")
                or eligible["origin_basis"] != origin["elapsed_origin_basis"]
            ):
                raise ValueError(f"typed target eligibility mismatch: {rid} {target}")
            item[target + "_eligible"] = not reasons
            item[target + "_reasons"] = sorted(reasons)
            if reasons:
                continue
            relevant = ("observed",) if target == "T-OBS" else tuple(roles)
            tier = (
                "source_reviewed_rule"
                if any(
                    values[(rid, side)]["rule_id"] != "reported_hhmm_explicit_doy_v1"
                    for side in relevant
                )
                else "native_explicit_doy"
            )
            views[target].append(
                dict(
                    report_id=rid,
                    event_id=event,
                    physical_site_id=site["physical_site_id"],
                    identity_scope=site.get("identity_scope", "unknown"),
                    identity_tier=site.get("identity_tier", "unknown"),
                    time_evidence_tier=tier,
                    observed_utc=report["observed_utc"],
                    estimated_utc=report["estimated_utc"],
                    observed_elapsed_seconds=(obs - reference).total_seconds()
                    if target == "T-OBS" and obs is not None and reference is not None
                    else "not applicable",
                    estimated_minus_observed_seconds=(est - obs).total_seconds()
                    if target == "T-CAL" and est is not None and obs is not None
                    else "not applicable",
                    target_id=target,
                    target_version=TARGETS[target],
                    origin_basis=origin["elapsed_origin_basis"],
                    model_eligible=False,
                    physical_onset_validated=False,
                )
            )
        delta.append(item)
    for source_summary, tables in ((old_summary, old), (summary, current)):
        if (
            source_summary["source_rows"] != len(tables["arrival_report"])
            or source_summary["exact_pairs"] != len(tables["pair"])
            or source_summary["rejected_or_uncertain"]
            != len(tables["arrival_report"]) - len(tables["pair"])
            or source_summary["development_events"] != len(development)
            or source_summary["reserved_events_excluded"] != len(reserved)
        ):
            raise ValueError("corpus counter mismatch")
    if summary["exact_observed_values"] != observed_exact or summary["target_eligible"] != {
        target: len(rows) for target, rows in views.items()
    }:
        raise ValueError("target/observed counter mismatch")
    target_summary: dict[str, Any] = {}
    folds: list[dict[str, Any]] = []
    degrees: list[dict[str, Any]] = []
    balance: list[dict[str, Any]] = []
    for target, rows in views.items():
        support, target_folds, target_degrees = _support(target, rows)
        target_summary[target] = support
        folds += target_folds
        degrees += target_degrees
        for axis in ("region", "magnitude_band", "era", "identity_scope", "time_evidence_tier"):
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                meta = metadata[row["event_id"]]
                if axis == "magnitude_band":
                    mag = float(meta.get("usgs_mag", "nan"))
                    value = (
                        "unknown"
                        if not math.isfinite(mag)
                        else (
                            "under_7"
                            if mag < 7
                            else "7_to_7.49"
                            if mag < 7.5
                            else "7.5_to_7.99"
                            if mag < 8
                            else "8_or_above"
                        )
                    )
                elif axis == "era":
                    year = str(meta.get("usgs_time", "unknown"))[:4]
                    value = year[:3] + "0s" if year.isdigit() else "unknown"
                else:
                    value = str(row.get(axis, meta.get(axis, "unknown")))
                groups[value].append(row)
            balance.extend(
                dict(
                    target_id=target,
                    axis=axis,
                    value=value,
                    reports=len(group),
                    events=len({r["event_id"] for r in group}),
                    sites=len({r["physical_site_id"] for r in group}),
                )
                for value, group in sorted(groups.items())
            )
    queue: list[dict[str, Any]] = []
    site_degrees: dict[str, int] = {}
    for row in degrees:
        site_degrees[row["physical_site_id"]] = max(
            site_degrees.get(row["physical_site_id"], 0), row["event_degree"]
        )
    for row in delta:
        if row["T-OBS_eligible"] and row["T-CAL_eligible"]:
            continue
        reasons = sorted(set(row["T-OBS_reasons"] + row["T-CAL_reasons"]))
        blocked = "event_attribution_unresolved" in reasons
        degree = site_degrees.get(row["physical_site_id"], 0)
        action = (
            "resolve_event_attribution"
            if blocked
            else (
                "review_site_identity"
                if "geographic_identity_unreviewed" in reasons
                else "seek_original_dated_report_or_note"
            )
        )
        queue.append(
            dict(
                priority=100 if blocked else 10 if degree > 1 else 20,
                report_id=row["report_id"],
                event_id=row["event_id"],
                physical_site_id=row["physical_site_id"],
                current_site_event_degree=degree,
                remaining_reason_codes=reasons,
                next_evidence_action=action,
                acquisition_eligible=False,
                acquisition_status="needs_scoped_source_contract",
            )
        )
    queue.sort(key=lambda r: (r["priority"], r["event_id"], r["report_id"]))
    counts = dict(
        reports=len(reports),
        baseline_pairs=len(old_pairs),
        baseline_pairs_with_reviewed_geography=sum(
            _reviewed(old_sites.get(k, {})) for k in old_pairs
        ),
        new_pairs=len(pairs),
        new_pairs_with_reviewed_geography=sum(_reviewed(sites.get(k, {})) for k in pairs),
        promoted_pairs=len(set(pairs) - set(old_pairs)),
        promoted_clock_values=promoted_clocks,
        exact_observed_values=observed_exact,
        qualified_or_footnoted_values=qualified,
        reported_time_values=len(values),
        target_eligibility_rows=len(targets),
        reserved_rows=0,
        gap_queue_entries=len(queue),
    )
    result: dict[str, Any] = dict(
        schema_version="arrival-recovery-qa-v1",
        counts=counts,
        targets=target_summary,
        input_sha256=dict(sorted(hashes.items())),
        crosswalk_validation="independent_digest_bound_review"
        if crosswalk
        else "corpus_review_flags_only",
        interpretation=[
            "T-OBS is duration from its named reviewed reference origin.",
            "T-CAL is an absolute estimated-minus-observed clock difference; it does not assert "
            "historical model-origin equivalence or pre-arrival forecast availability.",
            "Counts refer to reports; graph edges collapse duplicate event/geographic-site pairs.",
            "Ranks and folds describe support, not variance identification or model readiness.",
            "Geographic sites do not establish sensor or deployment continuity.",
            "Queue order uses repeated-site support and attribution, never forecast residuals.",
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".recovery-qa-", dir=output.parent))
    try:
        for name, rows in [
            ("recovery_delta", delta),
            ("fold_support", folds),
            ("site_degrees", degrees),
            ("balance", balance),
            ("evidence_gap_queue", queue),
        ]:
            _write(stage, name, rows)
        for target, rows in views.items():
            _write(stage, target.lower(), rows)
        (stage / "summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for name, digest in hashes.items():
            if _sha(root / name) != digest:
                raise ValueError("input changed before recovery QA publication")
        manifest = dict(
            input_sha256=result["input_sha256"],
            output_sha256={p.name: _sha(p) for p in sorted(stage.iterdir())},
        )
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--events-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--crosswalk", type=Path)
    parser.add_argument("--time-evidence", type=Path)
    parser.add_argument("--time-context", type=Path)
    args = parser.parse_args()
    result = check_recovery(
        args.corpus,
        args.baseline,
        args.events_config,
        args.output,
        root=args.root,
        crosswalk=args.crosswalk,
        time_evidence=args.time_evidence,
        time_context=args.time_context,
    )
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
