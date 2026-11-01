"""Build a source-backed availability supplement without changing arrival labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import (  # noqa: E402
    Row,
    checked_path,
    development_reports,
    read_rows,
    require_development,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)
from analysis.arrival.source_process import (  # noqa: E402
    ABSENT,
    CALENDAR,
    account,
    first_blocker,
    validate_alternative,
)


def build(root: Path, inputs: Path, review: Path, ledger: Path, output: Path) -> None:
    """Validate frozen identities, raw membership and reviewed claim applicability."""
    if output.exists():
        raise ValueError("output already exists; use a new version or replay directory")
    frozen = verify_inputs(inputs)
    if Path(frozen["root"]).resolve() != root:
        raise ValueError("input root does not match project root")
    reports = development_reports(frozen)
    require_development(reports, frozen["events"], "event_id")
    curated = cast(dict[str, Any], json.loads(review.read_text(encoding="utf-8")))
    if curated["schema_version"] != "reviewed_source_process_curation_v1":
        raise ValueError("unknown curation schema")
    claims = cast(list[Row], curated["claims"])
    claims_by_id = {c["claim_id"]: c for c in claims}
    if len(claims_by_id) != len(claims):
        raise ValueError("duplicate claim ID")
    for claim in claims:
        if any(not value for value in claim.values()):
            raise ValueError("blank claim metadata; use unknown")
        if claim["event_id"] != "unknown":
            require_development([claim], frozen["events"], "event_id")
    source_rows = read_rows(ledger)
    sources = {r["source_id"]: r for r in source_rows}
    if len(sources) != len(source_rows):
        raise ValueError("duplicate source identity in ledger")
    pins = {p.relative_to(root).as_posix(): sha256(p) for p in (inputs, review, ledger)}
    used_sources: set[str] = set()

    def source(source_id: str) -> Row:
        record = sources[source_id]
        if record["sha256"] == "unknown":
            raise ValueError(f"source lacks retained original: {source_id}")
        path = checked_path(root, record["local_path"])
        if sha256(path) != record["sha256"]:
            raise ValueError(f"source hash mismatch: {source_id}")
        pins[record["local_path"]] = record["sha256"]
        used_sources.add(source_id)
        return record

    for claim in claims:
        s = source(claim["source_id"])
        claim.update(source_sha256=s["sha256"], url=s["url"], publisher=s["publisher"],
                     accessed_on=s["accessed_on"])
    by_id = {r["report_id"]: r for r in reports}
    links = cast(list[Row], curated["ntwc_field_links"])
    for link in links:
        row, claim = by_id[link["report_id"]], claims_by_id[link["claim_id"]]
        if (claim["event_id"] != row["event_id"] or
                link["expected_source_label"] != " ".join(row["source_label"].split())):
            raise ValueError("evidence event or reviewed station label does not match report")
        if (link["relation"] == "direct_field_reason" and
                (claim["affected_field"] != link["field"] or
                 claim["evidence_class"] != "documented_availability_reason" or
                 claim["source_id"] != row["source_id"])):
            raise ValueError("direct link requires field-specific documented reason")
        link.update(event_id=row["event_id"], source_label=" ".join(row["source_label"].split()),
                    report_source_sha256=row["source_sha256"],
                    claim_source_sha256=claim["source_sha256"])
    summary = account(reports, links)
    availability: list[Row] = []
    policy_sources: set[str] = set()
    for row in reports:
        s = source(row["source_id"])
        if s["sha256"] != row["source_sha256"]:
            raise ValueError("report/raw binding changed")
        text = checked_path(root, s["local_path"]).read_bytes().decode("utf-8")
        raw = cast(dict[str, Any], json.loads(row["raw_row_json"]))
        if raw["raw_html"] not in text:
            raise ValueError("report row absent from original source")
        policy = "where it could be determined" in text
        if policy:
            policy_sources.add(row["source_id"])
        own = [x for x in links if x["report_id"] == row["report_id"]]
        accepted = row["structural_status"] == "accepted_source_row"
        availability.append({
            k: row[k] for k in ("report_id", "event_id", "source_id", "source_sha256",
                               "structural_status", "estimate_state", "observed_state")
        } | {
            "source_label": " ".join(row["source_label"].split()) or "unknown",
            "first_blocker": first_blocker(row),
            "estimate_absent": str(accepted and row["estimate_state"] in ABSENT),
            "observed_absent": str(accepted and row["observed_state"] in ABSENT),
            "any_calendar_problem": str(accepted and bool(
                {row["estimate_state"], row["observed_state"]} & CALENDAR)),
            "conditional_observed_reporting_policy": str(policy),
            "policy_locator": "introductory paragraph: where it could be determined"
                              if policy else "unknown",
            "direct_reason_claims": json.dumps(sorted({x["claim_id"] for x in own
                                                       if x["relation"] == "direct_field_reason"})),
            "technical_root_cause": "unknown", "timestamp_replacement_allowed": "False",
        })
    ncei_path = root / "data/processed/ncei-arrivals/foundation-v1/observations.csv.gz"
    documentary_path = (root / "data/processed/arrival-evidence/documentary-v1" /
                        "first_wave_observations.csv.gz")
    pins[ncei_path.relative_to(root).as_posix()] = sha256(ncei_path)
    pins[documentary_path.relative_to(root).as_posix()] = sha256(documentary_path)
    ncei = read_rows(ncei_path)
    require_development(ncei, frozen["events"], "development_event_id")
    conflicts: list[Row] = []
    for item in cast(list[Row], curated["ncei_definition_candidates"]):
        claim = claims_by_id[item["claim_id"]]
        matches = [r for r in ncei if r["ncei_runup_id"] == item["ncei_runup_id"] and
                   r["development_event_id"] == claim["event_id"]]
        if len(matches) != 1:
            raise ValueError("NCEI comparison identity is not unique")
        row = matches[0]
        source(row["source_id"])
        conflicts.append(item | {k: row[k] for k in (
            "source_record_id", "source_id", "native_locationName", "native_arrDay",
            "native_arrHour", "native_arrMin", "native_travHours", "native_travMins"
        )} | {"event_id": row["development_event_id"],
              "raw_path": row["raw_path"], "raw_sha256": sha256(root / row["raw_path"]),
              "claim_source_sha256": claim["source_sha256"], "parent_write_allowed": "False"})
    documentary = read_rows(documentary_path)
    require_development(documentary, frozen["events"], "event_id")
    doc_links = cast(list[Row], curated["documentary_links"])
    for item in doc_links:
        row = next(r for r in documentary if r["record_id"] == item["record_id"])
        claim = claims_by_id[item["claim_id"]]
        if (row["native_clock"] != "?" or claim["event_id"] != row["event_id"] or
                row["station_label"] != claim["station_scope"] or
                row["source_id"] != claim["source_id"] or
                row["source_sha256"] != claim["source_sha256"]):
            raise ValueError("documentary missing-arrival linkage mismatch")
        item.update(event_id=row["event_id"], station_label=row["station_label"],
                    native_clock=row["native_clock"], source_sha256=row["source_sha256"])
    alternatives = cast(list[Row], curated["alternative_observations"])
    require_development(alternatives, frozen["events"], "event_id")
    for item in alternatives:
        s = source(item["source_id"])
        validate_alternative(item, claims_by_id[item["claim_id"]],
                             by_id[item["parent_report_candidate"]])
        item.update(source_sha256=s["sha256"], url=s["url"])
    tables = {"claims": claims, "ntwc_field_links": links, "report_availability": availability,
              "ncei_definition_candidates": conflicts, "documentary_field_links": doc_links,
              "alternative_observations": alternatives,
              "sources": [sources[s] for s in sorted(used_sources)],
              "acquisition_dispositions": [r for r in source_rows
                                           if r["source_id"].startswith("source-process-")]}
    for name, rows in tables.items():
        write_rows(output / f"{name}.csv.gz", rows)
    summary.update({
        "schema_version": "arrival_source_process_v1", "review_date": curated["review_date"],
        "claims": len(claims), "retained_sources_used": len(used_sources),
        "ntwc_source_pages": len({r["source_id"] for r in reports}),
        "ntwc_conditional_observed_policy_pages": len(policy_sources),
        "absent_observed_fields_with_policy_context": sum(
            r["observed_absent"] == "True" and
            r["conditional_observed_reporting_policy"] == "True" for r in availability),
        "ntwc_field_evidence_links": len(links),
        "ncei_definition_candidates": len(conflicts), "ncei_denominator": len(ncei),
        "documentary_direct_reason_records": len(doc_links),
        "documentary_denominator": len(documentary),
        "documentary_absent_arrival_cells": sum(r["native_clock"] in {"?", "unknown"}
                                                for r in documentary),
        "alternative_approximate_observations": len(alternatives),
        "technical_failure_causes_assigned_to_ntwc_blanks": 0,
        "new_exact_pairs_approved": 0, "model_fitted": False,
        "interpretation": "Direct support explains availability at the documented phenomenon "
                          "level; policy context is not a case-specific cause. Denominators "
                          "remain separate; no primary labels or model eligibility changed.",
    })
    write_json(output / "summary.json", summary)
    write_json(output / "schema.json", {
        "grain": "one source, claim, field-evidence link or retained report per named table",
        "missing_value": "unknown; native absence states are preserved",
        "direct_field_reason": "explicit applicable published availability reason; technical "
                               "failure mechanism may remain unknown",
        "incident_context": "applicable incident without demonstrated first-arrival cause",
        "positive_control": "incident coexists with reported arrival; not a missing-field cause",
        "policy_context": "conditional product definition; not an individually attributed cause",
        "ncei_definition_candidates": "event/name comparisons only; no deployment identity, "
                                      "source ancestry, error or replacement approval",
        "alternative_observations": "approximate local-clock source statement, no exact UTC",
        "causal_identification": "MCAR/MAR/MNAR not established; unknown stays unknown",
        "coordinates": "no coordinate conversion or spatial identity promotion performed",
    })
    for relative in ["analysis/arrival/source_process.py", "analysis/arrival/evidence.py",
                     "scripts/build_source_process.py"]:
        pins[relative] = sha256(root / relative)
    write_json(output / "inputs.json", {"files": pins, "frozen_inputs_verified": True})
    write_json(output / "manifest.json", {p.name: sha256(p) for p in sorted(output.iterdir())})
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.root.resolve(), args.inputs.resolve(), args.review.resolve(),
          args.ledger.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
