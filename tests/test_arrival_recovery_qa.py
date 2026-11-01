"""Recovery QA rejects scientific/data-contract drift using synthetic evidence."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_arrival_recovery import check_recovery

VERSIONS = {
    "T-OBS": "reported_duration_from_reviewed_reference_v1",
    "T-CAL": "reported_absolute_difference_v1",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["event_id", "report_id"]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def update_table(
    root: Path, version: str, event: str, table: str, rows: list[dict[str, Any]]
) -> None:
    path = root / version / event / f"{table}.csv.gz"
    write_rows(path, rows)
    summary_path = root / version / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["output_sha256"][f"{event}/{table}.csv.gz"] = sha(path)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def fixture(root: Path, *, late_origin: bool = False) -> None:
    config = root / "events.toml"
    raw = root / "raw"
    raw.mkdir()
    lines: list[str] = []
    for event in ("one", "two", "reserved"):
        (raw / f"{event}.html").write_text(f"synthetic {event} source", encoding="utf-8")
        role = "sealed_evaluation" if event == "reserved" else "development"
        lines += [
            f"[events.{event}]",
            f'event_id="{event}"',
            f'role="{role}"',
            'attribution_status="single_source_metadata"',
            'region="fixture"',
            'usgs_mag="7.5"',
            'usgs_time="2000-01-01T00:00:00Z"',
            f"[assets.{event}]",
            f'source_id="page-{event}"',
            f'local_path="raw/{event}.html"',
        ]
    config.write_text("\n".join(lines), encoding="utf-8")
    evidence_path = root / "time-evidence.csv"
    evidence = dict(
        event_id="one",
        source_id="page-one",
        source_sha256=sha(raw / "one.html"),
        source_path="raw/one.html",
        table_index="1",
        header_family="computed_observed_utc",
        rule_ids='["inline_month_day_v1"]',
        evidence_id="review-one",
        review_status="independently_reviewed",
        reviewer="synthetic reviewer",
        scope="Explicit dates only",
        evidence_locator_json='[{"text":"synthetic"}]',
    )
    with evidence_path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=list(evidence))
        writer.writeheader()
        writer.writerow(evidence)
    context_path = root / "config/ntwc-reported-clock-context-v2.csv"
    context_path.parent.mkdir()
    context_rows = [
        dict(
            event_id=event,
            calendar_year="2000",
            calendar_year_provenance=sha(raw / f"{event}.html"),
            origin_utc="2000-01-01T12:30:00Z" if late_origin else "2000-01-01T00:00:00Z",
            origin_basis="reviewed_reference",
            origin_provenance="synthetic reviewed origin",
        )
        for event in ("one", "two")
    ]
    with context_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(context_rows[0]))
        writer.writeheader()
        writer.writerows(context_rows)
    for version in ("old", "new"):
        all_reports: list[dict[str, Any]] = []
        pair_count = observed_count = 0
        target_counts = {target: 0 for target in VERSIONS}
        output_hashes: dict[str, str] = {}
        for event in ("one", "two"):
            event_rows = [
                dict(
                    event_id=event,
                    role="development",
                    region="fixture",
                    elapsed_origin_utc="2000-01-01T12:30:00Z"
                    if late_origin
                    else "2000-01-01T00:00:00Z",
                    elapsed_origin_basis="reviewed_reference",
                    elapsed_origin_provenance="synthetic reviewed origin",
                )
            ]
            reports: list[dict[str, Any]] = []
            pairs: list[dict[str, Any]] = []
            sites: list[dict[str, Any]] = []
            values: list[dict[str, Any]] = []
            eligibility: list[dict[str, Any]] = []
            for local_index in (1, 2):
                number = local_index if event == "one" else local_index + 2
                rid = f"{event}:1:{local_index}"
                source_hash = sha(raw / f"{event}.html")
                estimate_raw = "1200 1/1" if number == 2 else "1200 (001)"
                observed_raw = "1210 1/1" if number == 2 else "1210 (001)"
                if number == 3:
                    estimate_raw = "No ETA"
                if number == 4:
                    observed_raw = "~1210 (001)"
                estimate_exact = number in {1, 4} or (number == 2 and version == "new")
                observed_exact = number in {1, 3} or (number == 2 and version == "new")
                estimate_state = (
                    "exact_reported_timestamp"
                    if estimate_exact
                    else ("source_absent_explicit" if number == 3 else "date_ambiguous")
                )
                observed_state = (
                    "exact_reported_timestamp"
                    if observed_exact
                    else ("qualified_value" if number == 4 else "date_ambiguous")
                )
                recovered = version == "new" and number == 2
                rule = "inline_month_day_v1" if recovered else "reported_hhmm_explicit_doy_v1"
                if number == 4:
                    rule = "reported_hhmm_explicit_doy_v1+qualifier_v1"
                if number == 3:
                    rule = "explicit_absent_v1+reported_hhmm_explicit_doy_v1"
                report = dict(
                    event_id=event,
                    report_id=rid,
                    table_index="1",
                    row_index=str(local_index),
                    source_id=f"page-{event}",
                    source_sha256=source_hash,
                    structural_status="accepted_source_row",
                    header_family="computed_observed_utc",
                    estimated_raw=estimate_raw,
                    observed_raw=observed_raw,
                    legacy_arrival_raw="",
                    legacy_eta_raw="",
                    raw_row_json=json.dumps({"id": rid}),
                    estimate_state=estimate_state,
                    observed_state=observed_state,
                    estimated_utc="2000-01-01T12:00:00Z" if estimate_exact else "unknown",
                    observed_utc="2000-01-01T12:10:00Z" if observed_exact else "unknown",
                    disposition="exact_reported_pair"
                    if estimate_exact and observed_exact
                    else "rejected_or_uncertain",
                    time_rule_id=rule,
                )
                reports.append(report)
                site = dict(
                    event_id=event,
                    report_id=rid,
                    site_record_id=rid + ":site",
                    physical_site_id="site:shared" if number != 4 else "site:other",
                    event_site_identity_verified="True",
                    review_status="independently_reviewed",
                    identity_scope="source_qualified_geographic_site",
                    identity_tier="header_exact",
                    identity_evidence="[]",
                    fit_tier_identity="True",
                    deployment_continuity_verified="False",
                )
                sites.append(site)
                if estimate_exact and observed_exact:
                    pair_count += 1
                    pairs.append(
                        dict(
                            event_id=event,
                            report_id=rid,
                            source_id=f"page-{event}",
                            source_sha256=source_hash,
                            estimated_utc=report["estimated_utc"],
                            observed_utc=report["observed_utc"],
                            time_rule_id=rule,
                            physical_site_id=site["physical_site_id"],
                            model_eligible="False",
                            physical_onset_validated="False",
                        )
                    )
                observed_count += observed_exact
                for side, raw_value, state in [
                    ("estimated", estimate_raw, estimate_state),
                    ("observed", observed_raw, observed_state),
                ]:
                    side_rule = rule
                    if number == 3:
                        side_rule = (
                            "explicit_absent_v1"
                            if side == "estimated"
                            else ("reported_hhmm_explicit_doy_v1")
                        )
                    if number == 4:
                        side_rule = (
                            "qualifier_v1"
                            if side == "observed"
                            else ("reported_hhmm_explicit_doy_v1")
                        )
                    values.append(
                        dict(
                            event_id=event,
                            report_id=rid,
                            field_role=side,
                            source_id=f"page-{event}",
                            source_sha256=source_hash,
                            raw_value=raw_value,
                            state=state,
                            hour="12" if state == "exact_reported_timestamp" else "unknown",
                            minute=("0" if side == "estimated" else "10")
                            if state == "exact_reported_timestamp"
                            else "unknown",
                            day_of_year="1" if state == "exact_reported_timestamp" else "unknown",
                            timestamp_utc=report[f"{side}_utc"],
                            rule_id=side_rule,
                            evidence_id="review-one" if recovered else "unknown",
                            qualifier="~" if number == 4 and side == "observed" else "",
                            footnote="",
                        )
                    )
                for target, target_version in VERSIONS.items():
                    reasons: list[str] = []
                    if not observed_exact:
                        reasons.append("observed:" + observed_state)
                    if target == "T-CAL" and not estimate_exact:
                        reasons.append("estimate:" + estimate_state)
                    if target == "T-OBS" and late_origin and observed_exact:
                        reasons.append("observed:nonpositive_elapsed")
                    target_counts[target] += not reasons
                    eligibility.append(
                        dict(
                            event_id=event,
                            report_id=rid,
                            target_id=target,
                            target_version=target_version,
                            eligible=str(not reasons),
                            reason_codes=json.dumps(reasons),
                            physical_site_id=site["physical_site_id"],
                            origin_basis=event_rows[0]["elapsed_origin_basis"],
                            model_eligible="False",
                        )
                    )
            all_reports += reports
            tables = dict(event=event_rows, arrival_report=reports, pair=pairs, site=sites)
            if version == "new":
                tables.update(reported_time_value=values, target_eligibility=eligibility)
            for table, rows in tables.items():
                path = root / version / event / f"{table}.csv.gz"
                write_rows(path, rows)
                output_hashes[f"{event}/{table}.csv.gz"] = sha(path)
        summary: dict[str, Any] = dict(
            source_rows=len(all_reports),
            exact_pairs=pair_count,
            rejected_or_uncertain=len(all_reports) - pair_count,
            development_events=2,
            reserved_events_excluded=1,
            output_sha256=output_hashes,
            input_sha256={"config": sha(config)},
            events={"one": {}, "two": {}},
        )
        if version == "new":
            summary.update(
                exact_observed_values=observed_count,
                target_eligible=target_counts,
                time_evidence_records=1,
            )
            summary["input_sha256"]["time_evidence"] = sha(evidence_path)
            summary["input_sha256"]["time_context"] = sha(context_path)
        (root / version / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def run(root: Path, output: str = "out") -> dict[str, Any]:
    return check_recovery(
        root / "new",
        root / "old",
        root / "events.toml",
        root / output,
        root=root,
        time_evidence=root / "time-evidence.csv",
    )


def test_recovery_conservation_support_and_deterministic_replay(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = run(tmp_path)
    assert result["counts"]["reports"] == 4
    assert result["counts"]["baseline_pairs"] == 1
    assert result["counts"]["new_pairs"] == 2
    assert result["counts"]["promoted_pairs"] == 1
    assert result["counts"]["exact_observed_values"] == 3
    assert result["targets"]["T-OBS"]["eligible_reports"] == 3
    assert result["targets"]["T-OBS"]["graph"]["edges"] == 2
    assert result["targets"]["T-CAL"]["graph"]["edges"] == 1
    assert result["counts"]["qualified_or_footnoted_values"] == 1
    folds = json.loads((tmp_path / "out/fold_support.json").read_text(encoding="utf-8"))
    held_site = next(r for r in folds if r["target_id"] == "T-OBS" and r["fold"] == "LOSO")
    assert held_site["held_out"] == "site:shared"
    assert held_site["training_edges"] == held_site["indicator_matrix_rank"] == 0
    assert held_site["fixed_columns_nullity"] == 3
    assert held_site["unseen_events"] == ["one", "two"]
    run(tmp_path, "again")
    assert {p.name: p.read_bytes() for p in (tmp_path / "out").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "again").iterdir()
    }
    with pytest.raises(FileExistsError):
        run(tmp_path)


def test_absolute_clock_target_does_not_require_positive_origin_duration(tmp_path: Path) -> None:
    fixture(tmp_path, late_origin=True)
    result = run(tmp_path)
    assert result["targets"]["T-CAL"]["eligible_reports"] == 2
    assert result["targets"]["T-OBS"]["eligible_reports"] == 0


@pytest.mark.parametrize(
    "violation",
    [
        "retimed_pair",
        "raw_change",
        "reserved_report",
        "duplicate_value",
        "bad_site_join",
        "qualified_promoted",
        "counter",
        "target_version",
        "model_flag",
        "source_hash",
        "missing_allowlist",
        "mismatched_evidence_scope",
        "missing_target",
    ],
)
def test_invalid_recovery_never_publishes_output(tmp_path: Path, violation: str) -> None:
    fixture(tmp_path)
    table = "arrival_report"
    path = tmp_path / "new/one/arrival_report.csv.gz"
    rows = read_rows(path)
    if violation == "retimed_pair":
        rows[0]["observed_utc"] = "2000-01-01T12:11:00Z"
    elif violation == "raw_change":
        rows[0]["estimated_raw"] = "1201 (001)"
    elif violation == "reserved_report":
        rows[0]["event_id"] = "reserved"
    elif violation in {"duplicate_value", "qualified_promoted", "missing_allowlist"}:
        table = "reported_time_value"
        rows = read_rows(tmp_path / "new/one/reported_time_value.csv.gz")
        if violation == "duplicate_value":
            rows.append(rows[0])
        elif violation == "missing_allowlist":
            rows[2]["evidence_id"] = "unknown"
        else:
            rows[0]["qualifier"] = "~"
    elif violation in {"bad_site_join", "target_version", "model_flag", "missing_target"}:
        table = "target_eligibility"
        rows = read_rows(tmp_path / "new/one/target_eligibility.csv.gz")
        if violation == "bad_site_join":
            rows[0]["physical_site_id"] = "site:invented"
        elif violation == "target_version":
            rows[0]["target_version"] = "duration_offset_as_if_absolute"
        elif violation == "model_flag":
            rows[0]["model_eligible"] = "True"
        else:
            rows.pop()
    elif violation == "source_hash":
        (tmp_path / "raw/one.html").write_text("changed", encoding="utf-8")
    elif violation == "mismatched_evidence_scope":
        evidence = tmp_path / "time-evidence.csv"
        evidence.write_text(
            evidence.read_text().replace("computed_observed_utc", "different_header")
        )
        summary_path = tmp_path / "new/summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["input_sha256"]["time_evidence"] = sha(evidence)
        summary_path.write_text(json.dumps(summary))
    else:
        summary_path = tmp_path / "new/summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["exact_pairs"] = 900
        summary_path.write_text(json.dumps(summary))
    if violation not in {"source_hash", "counter", "mismatched_evidence_scope"}:
        update_table(tmp_path, "new", "one", table, rows)
    with pytest.raises((ValueError, KeyError)):
        run(tmp_path)
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".recovery-qa-*"))


def test_partial_write_failure_never_publishes_or_mutates_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import check_arrival_recovery

    fixture(tmp_path)
    before = {
        p.relative_to(tmp_path).as_posix(): sha(p) for p in tmp_path.rglob("*") if p.is_file()
    }

    def fail(stage: Path, name: str, rows: list[dict[str, Any]]) -> None:
        (stage / f"{name}.json").write_text("partial", encoding="utf-8")
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(check_arrival_recovery, "_write", fail)
    with pytest.raises(OSError, match="synthetic storage failure"):
        run(tmp_path)
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".recovery-qa-*"))
    assert before == {
        p.relative_to(tmp_path).as_posix(): sha(p) for p in tmp_path.rglob("*") if p.is_file()
    }


def test_old_pair_clock_cannot_disagree_with_preserved_report_clock(tmp_path: Path) -> None:
    fixture(tmp_path)
    rows = read_rows(tmp_path / "old/one/pair.csv.gz")
    rows[0]["observed_utc"] = "2000-01-01T12:11:00Z"
    update_table(tmp_path, "old", "one", "pair", rows)
    with pytest.raises(ValueError, match="baseline exact pair"):
        run(tmp_path)


@pytest.mark.parametrize("approved_calendar", [True, False])
def test_native_day_clock_recovery_requires_hash_bound_calendar_context(
    tmp_path: Path,
    approved_calendar: bool,
) -> None:
    fixture(tmp_path)
    for version in ("old", "new"):
        rows = read_rows(tmp_path / version / "one/arrival_report.csv.gz")
        for row in rows:
            row["header_family"] = "computed_observed_utc_jday"
            row["time_rule_id"] = "reported_hhmm_explicit_doy_v1"
            row["estimated_raw"] = "1200 (001)"
            row["observed_raw"] = "1210 (001)"
        update_table(tmp_path, version, "one", "arrival_report", rows)
    pairs = read_rows(tmp_path / "new/one/pair.csv.gz")
    for pair in pairs:
        pair["time_rule_id"] = "reported_hhmm_explicit_doy_v1"
    update_table(tmp_path, "new", "one", "pair", pairs)
    rows = read_rows(tmp_path / "new/one/reported_time_value.csv.gz")
    for row in rows:
        row["rule_id"] = "reported_hhmm_explicit_doy_v1"
        row["evidence_id"] = "unknown"
        row["raw_value"] = "1200 (001)" if row["field_role"] == "estimated" else "1210 (001)"
    update_table(tmp_path, "new", "one", "reported_time_value", rows)
    context = tmp_path / "config/ntwc-reported-clock-context-v2.csv"
    context.parent.mkdir(exist_ok=True)
    source_hash = sha(tmp_path / "raw/one.html") if approved_calendar else "not-source-bound"
    row = dict(
        event_id="one",
        calendar_year="2000",
        calendar_year_provenance=source_hash,
        origin_utc="2000-01-01T00:00:00Z",
        origin_basis="reviewed_reference",
        origin_provenance="synthetic reviewed origin",
    )
    with context.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    summary_path = tmp_path / "new/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["input_sha256"]["time_context"] = sha(context)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    if approved_calendar:
        assert run(tmp_path)["counts"]["promoted_pairs"] == 1
    else:
        with pytest.raises(ValueError, match="source-scoped time evidence"):
            run(tmp_path)


def test_new_exact_clock_must_agree_with_preserved_source_components(tmp_path: Path) -> None:
    fixture(tmp_path)
    for table, column in [("arrival_report", "observed_utc"), ("pair", "observed_utc")]:
        rows = read_rows(tmp_path / f"new/one/{table}.csv.gz")
        next(row for row in rows if row["report_id"] == "one:1:2")[column] = "2000-01-02T12:10:00Z"
        update_table(tmp_path, "new", "one", table, rows)
    rows = read_rows(tmp_path / "new/one/reported_time_value.csv.gz")
    next(row for row in rows if row["report_id"] == "one:1:2" and row["field_role"] == "observed")[
        "timestamp_utc"
    ] = "2000-01-02T12:10:00Z"
    update_table(tmp_path, "new", "one", "reported_time_value", rows)
    with pytest.raises(ValueError, match="typed source components"):
        run(tmp_path)


def test_coherent_promoted_date_corruption_cannot_override_source_literal(tmp_path: Path) -> None:
    fixture(tmp_path)
    for table, column in [("arrival_report", "observed_utc"), ("pair", "observed_utc")]:
        rows = read_rows(tmp_path / f"new/one/{table}.csv.gz")
        next(row for row in rows if row["report_id"] == "one:1:2")[column] = "2000-01-02T12:10:00Z"
        update_table(tmp_path, "new", "one", table, rows)
    rows = read_rows(tmp_path / "new/one/reported_time_value.csv.gz")
    row = next(
        row for row in rows if row["report_id"] == "one:1:2" and row["field_role"] == "observed"
    )
    row.update(timestamp_utc="2000-01-02T12:10:00Z", day_of_year="2")
    update_table(tmp_path, "new", "one", "reported_time_value", rows)
    with pytest.raises(ValueError, match="source literal"):
        run(tmp_path)


def test_direct_cli_works_without_pythonpath(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    fixture(tmp_path)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    script = Path(__file__).resolve().parents[1] / "scripts/check_arrival_recovery.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--corpus",
            str(tmp_path / "new"),
            "--baseline",
            str(tmp_path / "old"),
            "--events-config",
            str(tmp_path / "events.toml"),
            "--root",
            str(tmp_path),
            "--time-evidence",
            str(tmp_path / "time-evidence.csv"),
            "--output",
            str(tmp_path / "cli-output"),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["promoted_pairs"] == 1


@pytest.mark.parametrize(
    "raw,stamp,year,origin,review,agrees",
    [
        ("6/23 2121", "2001-06-23T21:21:00Z", "2001", "2001-06-23T00:00:00Z", {}, True),
        ("2121 6-23-01", "2001-06-23T21:21:00Z", "2001", "2001-06-23T00:00:00Z", {}, True),
        ("6/23/2001 21:21", "2001-06-23T21:21:00Z", "2001", "2001-06-23T00:00:00Z", {}, True),
        ("2121 6/23", "2001-06-23T21:22:00Z", "2001", "2001-06-23T00:00:00Z", {}, False),
        ("2121 6/23", "2001-06-23T21:21:01Z", "2001", "2001-06-23T00:00:00Z", {}, False),
        ("2121 6/23/2002", "2001-06-23T21:21:00Z", "2001", "2001-06-23T00:00:00Z", {}, False),
        ("0007 1/1", "2013-01-01T00:07:00Z", "2012", "2012-12-31T00:00:00Z", {}, False),
        ("0007 1/1/13", "2013-01-01T00:07:00Z", "2012", "2012-12-31T00:00:00Z", {}, True),
        ("0007 1/1/1913", "2013-01-01T00:07:00Z", "2012", "2012-12-31T00:00:00Z", {}, False),
        ("12/31/12 2359", "2012-12-31T23:59:00Z", "2013", "2013-01-01T00:00:00Z", {}, True),
        ("12/31 2359", "2012-12-31T23:59:00Z", "2013", "2013-01-01T00:00:00Z", {}, False),
        (
            "0007 1/1",
            "2013-01-01T00:07:00Z",
            "2012",
            "2012-12-31T00:00:00Z",
            {"rollover_year": "2013"},
            True,
        ),
    ],
)
def test_independent_inline_literal_check_respects_calendar_and_explicit_rollover(
    raw: str,
    stamp: str,
    year: str,
    origin: str,
    review: dict[str, str],
    agrees: bool,
) -> None:
    from datetime import datetime

    from scripts.check_arrival_recovery import (
        _inline_literal_agrees,  # pyright: ignore[reportPrivateUsage]
    )

    assert (
        _inline_literal_agrees(
            raw,
            datetime.fromisoformat(stamp),
            {"calendar_year": year, "origin_utc": origin},
            review,
        )
        == agrees
    )
