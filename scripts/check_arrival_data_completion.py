"""Assemble and independently recheck the development arrival-evidence release."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.design import incidence_rank  # noqa: E402
from analysis.arrival.evidence import (  # noqa: E402
    Row,
    checked_path,
    development_reports,
    file_manifest,
    read_rows,
    sha256,
    verify_inputs,
    verify_product,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import load_pilot, validate_members  # noqa: E402
from analysis.arrival.stations import validate_reviewed_site_evidence  # noqa: E402
from pipeline.provenance import REQUIRED_COLUMNS, validate_manifest  # noqa: E402
from scripts.build_paper_manifest import build as build_ledger  # noqa: E402

REVIEW_SHA = "21ee65bc707bf7a417d0b6cdb4988605aa5395906f38b91cf23ba40e9a9021af"
LEDGER_SHA = "a6c4a2584899affd4e18f57ba0eb2c4c4c430735e805db877226c6795ee122ac"
INPUT_SHA = "3e79bb69fffedf550698afc622e490e4961a67a44123d96385f331ef8742786e"
PROTECTED_SHA = "ac1a7c72c126a3cacb900b51d5dd5d229637e75fbbfe18df4f2cadab120c3b9b"
ACCEPTED_STAGES = {
    "sites-reviewed": "1da55e3b28c163761d6e628fcc9af6aad91c900c00a5e13eb53a6aa370ecedfb",
    "lineage": "53a34c1c04ef9c6f0e9894faa9820efadf4d50f302443d6c3bfcac93c15030e8",
    "calendars": "0e60818a562d7825934419e7ee2bfbee7847de5fb323478545a27d112993f1ca",
    "observations": "8de740f7c2653c2797932b06b0be465614efb72e8e189ffffc5c4339b9b62b55",
    "waveform-quality": "a5ca227eead4748e8dfbc0cd7af8ca8b3f8f00712a14759a8cad1c3512f5d26f",
    "expansion": "7962eb83640378d9b4dbb6a02f243e7de3dbd3059aa012559e0029070f855f85",
}


def verify_stage_copies(inputs: Path, release: Path, manifest: dict[str, Any]) -> None:
    """Compare copied payloads to independently accepted stages, not self-issued hashes."""
    if manifest["upstream_manifests"] != ACCEPTED_STAGES:
        raise ValueError("release does not bind accepted stage hashes")
    stages = inputs.parent.parent
    for name, digest in ACCEPTED_STAGES.items():
        source = stages / name
        if sha256(source / "manifest.json") != digest:
            raise ValueError("accepted upstream manifest changed")
        product = verify_product(source, inputs_sha256=sha256(inputs))
        copies: dict[str, str] = {}
        if name == "observations":
            copies = {
                item["path"]: item["path"]
                for item in product["files"]
                if item["path"]
                not in {"design_summary.json", "dispositions.csv.gz", "opportunities.csv.gz"}
            }
        elif name == "waveform-quality":
            for item in product["files"]:
                path = item["path"]
                if path.startswith("packet/") or path in {
                    "selection.csv.gz",
                    "recipe.json",
                    "summary.json",
                }:
                    copies[path] = "audit/" + path
                elif path in {
                    "waveform_coverage.csv.gz",
                    "waveform_dispositions.csv.gz",
                    "overlapping_assets.csv.gz",
                }:
                    copies[path] = path
        elif name in {"lineage", "calendars", "expansion"}:
            copies = {
                item["path"]: "metadata/" + name + "-" + item["path"] for item in product["files"]
            }
            copies["manifest.json"] = "metadata/" + name + "-manifest.json"
        for original, destination in copies.items():
            if sha256(checked_path(release, destination)) != sha256(checked_path(source, original)):
                raise ValueError("release payload differs from accepted upstream stage")


def validate_ledger_preservation(rows: list[Row], baseline: list[Row], pilot_ids: set[str]) -> None:
    current = {r["source_id"]: r for r in rows}
    original = {r["source_id"]: r for r in baseline}
    if len(current) != len(rows) or set(current) != set(original) | pilot_ids:
        raise ValueError("source ledger identity conservation failure")
    if any(current[sid] != row for sid, row in original.items()):
        raise ValueError("baseline provenance row changed")


def validate_source_records(rows: list[Row], expected: dict[str, Row]) -> None:
    validate_members(rows, set(expected))
    for row in rows:
        source = expected[row["source_record_id"]]
        if (
            json.loads(row["native_record_json"]) != source
            or row["source_sha256"] != source["source_sha256"]
            or row["event_id"] != source.get("event_id", source.get("development_event_id"))
        ):
            raise ValueError("native source record changed")


def assemble_release(inputs: Path, stages: Path, receipts: Path, release: Path) -> Path:
    document = verify_inputs(inputs)
    root = Path(document["root"])
    if release.exists():
        raise ValueError("release already exists")
    upstream: dict[str, str] = {}
    for name in [
        "sites-reviewed",
        "lineage",
        "calendars",
        "observations",
        "waveform-quality",
        "expansion",
    ]:
        verify_product(stages / name, inputs_sha256=sha256(inputs))
        upstream[name] = sha256(stages / name / "manifest.json")
    if upstream != ACCEPTED_STAGES:
        raise ValueError("unaccepted upstream stage")
    pilot = load_pilot(root, receipts)
    observations = stages / "observations"
    release.mkdir(parents=True)
    for path in sorted(observations.iterdir()):
        if path.name != "manifest.json":
            shutil.copyfile(path, release / path.name)
    for name in [
        "waveform_coverage.csv.gz",
        "waveform_dispositions.csv.gz",
        "overlapping_assets.csv.gz",
    ]:
        shutil.copyfile(stages / "waveform-quality" / name, release / name)
    shutil.copytree(stages / "waveform-quality" / "packet", release / "audit/packet")
    for name in ["selection.csv.gz", "recipe.json", "summary.json"]:
        shutil.copyfile(stages / "waveform-quality" / name, release / "audit" / name)
    (release / "metadata").mkdir()
    for stage in ["lineage", "calendars", "expansion"]:
        for path in sorted((stages / stage).iterdir()):
            if path.is_file():
                shutil.copyfile(path, release / "metadata" / (stage + "-" + path.name))
    # Preserve the existing target graph diagnostics as a separate, versioned method product.
    summary = json.loads((release / "design_summary.json").read_text())
    summary["target_graphs"] = {
        target: incidence_rank(
            {
                (r["event_id"], r["physical_site_id"])
                for r in read_rows(release / (target + ".csv.gz"))
            }
        )
        for target in ["T-OBS", "T-CAL", "NCEI-native-duration"]
    }
    summary["waveform_quality"] = json.loads((stages / "waveform-quality/summary.json").read_text())
    summary["lineage_pilot"] = json.loads((stages / "lineage/summary.json").read_text())
    summary["calendar_diagnostics"] = json.loads((stages / "calendars/summary.json").read_text())
    write_json(release / "design_summary.json", summary)
    dispositions = read_rows(release / "dispositions.csv.gz")
    dispositions.extend(read_rows(release / "waveform_dispositions.csv.gz"))
    dispositions.extend(
        {
            "candidate_id": r["source_id"],
            "candidate_kind": "pilot_contract",
            "terminal_disposition": r["status"],
            "reason": r["reason"],
        }
        for r in pilot
    )
    dispositions.extend(
        {
            "candidate_id": r["native_event_id"],
            "candidate_kind": "expansion_event",
            "terminal_disposition": "deferred_by_scope",
            "reason": r["coverage_gap"],
        }
        for r in read_rows(stages / "expansion/candidates.csv.gz")
    )
    dispositions.extend(
        {
            "candidate_id": r["branch"],
            "candidate_kind": "conditional_branch",
            "terminal_disposition": r["status"],
            "reason": r["next_contract"],
        }
        for r in read_rows(stages / "expansion/branches.csv.gz")
    )
    write_rows(release / "dispositions.csv.gz", dispositions)
    opportunities = read_rows(release / "opportunities.csv.gz")
    for row in read_rows(release / "waveform_dispositions.csv.gz"):
        opportunities.append(
            {
                "opportunity_id": "waveform-opportunity:" + row["candidate_id"],
                "source_record_id": "unknown",
                "event_id": row["event_id"],
                "asset_source_id": row["candidate_id"],
                "opportunity_state": "documented_request_or_source",
                "reporting_state": row["terminal_disposition"],
                "historical_operating_state": "unknown",
                "availability_interval": "unknown",
                "nonreport_or_nondetection": "unknown",
                "negative_observation": "False",
                "scope": "source_acquisition_disposition_not_operating_network_census",
            }
        )
    write_rows(release / "opportunities.csv.gz", opportunities)
    old_ledger = checked_path(root, "artifacts/provenance/paper-source-manifest-v2.csv")
    if sha256(old_ledger) != LEDGER_SHA:
        raise ValueError("old source ledger changed")
    old_rows = read_rows(old_ledger)
    new_rows = build_ledger(root, [receipts])
    if {r["source_id"] for r in old_rows} & {r["source_id"] for r in new_rows}:
        raise ValueError("pilot ledger identity collision")
    write_rows(release / "source_manifest.csv", old_rows + new_rows, columns=list(REQUIRED_COLUMNS))
    validate_manifest(release / "source_manifest.csv")
    write_json(release / "upstream_manifests.json", upstream)
    write_json(
        release / "schema.json",
        {
            "source_records": "one source record; native_record_json preserves parser output",
            "observations": "one measurement; entity clusters do not establish independent picks",
            "pair_members": "one original NTWC pair; estimated minus observed in seconds",
            "forecast_instances": "one estimate cell; original issue/version/origin unresolved",
            "opportunities": "actual records/requests only; no Cartesian station cross-product",
            "calendar_evidence": "source components and cited statements; no new primary exact UTC",
            "sites": "lexical source record selects coordinate; native alternatives retained",
            "lineage_members": "unresolved placeholders are not independent replicate weights",
            "missing": "unknown is missing; native_record_json retains literal blank cells",
            "CRS_datum_units": "native metadata; unknown is not a common CRS/datum/unit claim",
            "audit": "stripped CSVs; nonexpert structural review, no blindness/onset claim",
            "model_eligible": False,
            "physical_onset_validated": False,
        },
    )
    write_json(
        release / "manifest.json",
        {
            "schema_version": "arrival_evidence_release_v1",
            "inputs_sha256": sha256(inputs),
            "upstream_manifests": upstream,
            "source_contracts": [
                {"source_id": r["source_id"], "path": r["local_path"], "sha256": r["sha256"]}
                for r in pilot
            ],
            "files": file_manifest(release),
        },
    )
    return release / "manifest.json"


def check_release(inputs: Path, release: Path, output: Path) -> int:
    if sha256(inputs) != INPUT_SHA:
        raise ValueError("accepted M0 input manifest changed")
    document = verify_inputs(inputs)
    root = Path(document["root"])
    manifest = verify_product(
        release,
        required_files=(
            "source_records.csv.gz",
            "observations.csv.gz",
            "pair_members.csv.gz",
            "crosswalk.csv",
            "dispositions.csv.gz",
            "calendar_evidence.csv.gz",
            "forecast_instances.csv.gz",
            "lineage_members.csv.gz",
            "source_manifest.csv",
            "waveform_coverage.csv.gz",
            "waveform_dispositions.csv.gz",
            "site_links.csv.gz",
            "target_eligibility.csv.gz",
            "T-OBS.csv.gz",
            "T-CAL.csv.gz",
            "NCEI-native-duration.csv.gz",
        ),
        inputs_sha256=sha256(inputs),
    )
    verify_stage_copies(inputs, release, manifest)
    ntwc = development_reports(document)
    ncei = read_rows(root / document["ncei"] / "observations.csv.gz")
    expected = {r["report_id"]: r for r in ntwc} | {r["source_record_id"]: r for r in ncei}
    validate_source_records(read_rows(release / "source_records.csv.gz"), expected)
    observations = read_rows(release / "observations.csv.gz")
    validate_members(observations, set(expected))
    by_id = {r["source_record_id"]: r for r in observations}
    site_links = read_rows(release / "site_links.csv.gz")
    validate_members(site_links, set(expected))
    sites_by_id = {r["source_record_id"]: r for r in site_links}
    if any(
        r["physical_site_id"] != sites_by_id[r["source_record_id"]]["physical_site_id"]
        for r in observations
    ):
        raise ValueError("observation site differs from reviewed link")
    for source in ntwc:
        if by_id[source["report_id"]]["observed_utc"] != (source["observed_utc"] or "unknown"):
            raise ValueError("unsupported primary date or changed observation")
    for source in ncei:
        row = by_id[source["source_record_id"]]
        if (
            row["observed_utc"] != source["arrival_utc"]
            or row["duration_minutes"] != source["reported_duration_minutes"]
        ):
            raise ValueError("source-native NCEI target changed")
        match = json.loads(source["event_match_json"])
        if row["source_native_origin"] != match.get("ncei_origin_utc", "unknown"):
            raise ValueError("source-native origin changed")
    for row in observations:
        if row["model_eligible"] != "False" or row["physical_onset_validated"] != "False":
            raise ValueError("unapproved model/onset claim")
    validate_members(read_rows(release / "lineage_members.csv.gz"), set(expected))
    forecasts = read_rows(release / "forecast_instances.csv.gz")
    validate_members(forecasts, {r["report_id"] for r in ntwc})
    forecasts_by_id = {r["source_record_id"]: r for r in forecasts}
    for row in ntwc:
        if forecasts_by_id[row["report_id"]]["estimated_utc"] != (
            row["estimated_utc"] or "unknown"
        ):
            raise ValueError("original forecast instance replaced")
    pairs = read_rows(release / "pair_members.csv.gz")
    original = {r["report_id"]: r for r in ntwc if r["disposition"] == "exact_reported_pair"}
    validate_members(pairs, set(original))
    for row in pairs:
        source = original[row["source_record_id"]]
        estimate, observed = (
            datetime.fromisoformat(source[k].replace("Z", "+00:00"))
            for k in ["estimated_utc", "observed_utc"]
        )
        if (
            row["estimated_utc"] != source["estimated_utc"]
            or row["observed_utc"] != source["observed_utc"]
            or float(row["estimated_minus_observed_seconds"])
            != (estimate - observed).total_seconds()
        ):
            raise ValueError("original signed pair changed")
    review = checked_path(root, "config/ntwc-station-review-v4.csv")
    if sha256(review) != REVIEW_SHA:
        raise ValueError("independent review delta changed")
    delta = {r["report_id"]: r for r in read_rows(review)}
    baseline = {
        r["report_id"]: r
        for r in read_rows(root / document["crosswalk"] / "unique_report_crosswalk.csv")
    }
    crosswalk = read_rows(release / "crosswalk.csv")
    if len(crosswalk) != len(ntwc) or {r["report_id"] for r in crosswalk} != {
        r["report_id"] for r in ntwc
    }:
        raise ValueError("crosswalk report conservation failure")
    for row in crosswalk:
        if row["review_status"] != "independently_reviewed":
            continue
        old = baseline[row["report_id"]]
        if old["review_status"] != "independently_reviewed":
            approved = delta.get(row["report_id"], {})
            if (
                approved.get("identity_evidence_sha256") != row["identity_evidence_sha256"]
                or approved.get("physical_site_id") != row["physical_site_id"]
            ):
                raise ValueError("unreviewed site promotion")
        elif old["identity_evidence_sha256"] != row["identity_evidence_sha256"]:
            raise ValueError("accepted baseline identity changed")
        validate_reviewed_site_evidence(row)
    crosswalk_by_id = {r["report_id"]: r for r in crosswalk}
    for row in ntwc:
        cross = crosswalk_by_id[row["report_id"]]
        link = sites_by_id[row["report_id"]]
        site = (
            cross["physical_site_id"]
            if cross["review_status"] == "independently_reviewed"
            else "unknown"
        )
        if site != link["physical_site_id"]:
            raise ValueError("unreviewed site link promotion")
    expected_targets = development_reports(document, targets=True)
    for row in expected_targets:
        link = sites_by_id[row["report_id"]]
        reasons = json.loads(row["reason_codes"])
        if link["decision"] == "accepted":
            reasons = [r for r in reasons if r != "geographic_identity_unreviewed"]
            row["physical_site_id"] = link["physical_site_id"]
        row["reason_codes"] = json.dumps(reasons, separators=(",", ":"))
        row["eligible"] = str(not reasons)
    actual_targets = read_rows(release / "target_eligibility.csv.gz")

    def index(rows: list[Row]) -> dict[tuple[str, str], Row]:
        return {(r["report_id"], r["target_id"]): r for r in rows}

    if len(actual_targets) != len(expected_targets) or index(actual_targets) != index(
        expected_targets
    ):
        raise ValueError("target eligibility changed beyond reviewed geography")
    for target in ["T-OBS", "T-CAL"]:
        ids = {
            r["report_id"]
            for r in expected_targets
            if r["target_id"] == target and r["eligible"] == "True"
        }
        view = read_rows(release / (target + ".csv.gz"))
        validate_members(view, ids)
        canonical = by_id if target == "T-OBS" else {r["source_record_id"]: r for r in pairs}
        if any(row != canonical[row["source_record_id"]] for row in view):
            raise ValueError("target view differs from individual source measurement")
    native_ids = {r["source_record_id"] for r in ncei if r["duration_candidate"] == "True"}
    native_view = read_rows(release / "NCEI-native-duration.csv.gz")
    validate_members(native_view, native_ids)
    if any(row != by_id[row["source_record_id"]] for row in native_view):
        raise ValueError("native duration view differs from individual measurement")
    if any(
        r["primary_exact_write_allowed"] != "False"
        for r in read_rows(release / "calendar_evidence.csv.gz")
    ):
        raise ValueError("unsupported primary calendar write")
    wave_manifest = json.loads((root / document["waveforms"] / "manifest.json").read_text())
    source_ids = {r["source_id"] for r in wave_manifest["sources"]}
    wd = read_rows(release / "waveform_dispositions.csv.gz")
    if len(wd) != len(source_ids) or {r["candidate_id"] for r in wd} != source_ids:
        raise ValueError("missing waveform failure disposition")
    dispositions = read_rows(release / "dispositions.csv.gz")
    required = {("source_record", rid) for rid in expected} | {
        ("waveform_source", sid) for sid in source_ids
    }
    required |= {("pilot_contract", r["source_id"]) for r in manifest["source_contracts"]}
    actual = [(r["candidate_kind"], r["candidate_id"]) for r in dispositions]
    required |= {
        ("expansion_event", r["native_event_id"])
        for r in read_rows(release / "metadata/expansion-candidates.csv.gz")
    }
    required |= {
        ("conditional_branch", r["branch"])
        for r in read_rows(release / "metadata/expansion-branches.csv.gz")
    }
    if not required <= set(actual) or len(actual) != len(set(actual)):
        raise ValueError("missing or duplicate terminal disposition")
    opportunities = read_rows(release / "opportunities.csv.gz")
    expected_opportunities = {"waveform-opportunity:" + sid for sid in source_ids}
    from analysis.arrival.lineage import stable_id

    expected_opportunities |= {stable_id("opportunity", rid) for rid in expected}
    ids = [r["opportunity_id"] for r in opportunities]
    if (
        len(ids) != len(set(ids))
        or set(ids) != expected_opportunities
        or any(
            r["negative_observation"] != "False"
            or r["historical_operating_state"] != "unknown"
            or r["nonreport_or_nondetection"] != "unknown"
            for r in opportunities
        )
    ):
        raise ValueError("unsupported negative or Cartesian opportunity")
    protected_path = inputs.parent / "protected.json"
    if sha256(protected_path) != PROTECTED_SHA:
        raise ValueError("accepted protected manifest changed")
    protected = json.loads(protected_path.read_text())
    for item in protected["files"]:
        if sha256(checked_path(root, item["path"])) != item["sha256"]:
            raise ValueError("sealed/story/baseline protected bytes changed")
    validate_manifest(release / "source_manifest.csv")
    ledger_rows = read_rows(release / "source_manifest.csv")
    old_ledger = checked_path(root, "artifacts/provenance/paper-source-manifest-v2.csv")
    if sha256(old_ledger) != LEDGER_SHA:
        raise ValueError("accepted original ledger changed")
    import tomllib

    from analysis.arrival.lineage import PILOT_CONFIG_SHA

    config = checked_path(root, "config/arrival-completion-pilot-v1.toml")
    if sha256(config) != PILOT_CONFIG_SHA:
        raise ValueError("pilot contracts changed")
    assets = tomllib.loads(config.read_text())["assets"]
    if len(manifest["source_contracts"]) != len(assets) or {
        r["source_id"] for r in manifest["source_contracts"]
    } != set(assets):
        raise ValueError("missing pilot contract disposition")
    validate_ledger_preservation(ledger_rows, read_rows(old_ledger), set(assets))
    ledger = {r["source_id"]: r for r in ledger_rows}
    for row in manifest["source_contracts"]:
        if (
            sha256(checked_path(root, row["path"])) != row["sha256"]
            or ledger[row["source_id"]]["sha256"] != row["sha256"]
        ):
            raise ValueError("stale acquired source hash")
    write_json(
        output / "report.json",
        {
            "status": "PASS",
            "schema_version": "arrival_release_check_v1",
            "candidate_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "release_manifest_sha256": sha256(release / "manifest.json"),
            "input_manifest_sha256": sha256(inputs),
            "source_records": len(expected),
            "original_exact_pairs": len(pairs),
            "protected_files": len(protected["files"]),
            "terminal_dispositions": len(dispositions),
            "source_ledger_ids": len(ledger),
            "target_counts": {
                t: len(read_rows(release / (t + ".csv.gz")))
                for t in ["T-OBS", "T-CAL", "NCEI-native-duration"]
            },
            "files": file_manifest(release),
            "model_fitted": False,
            "unattended_readiness": "blocked_separately",
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "release", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--assemble-from", type=Path)
    parser.add_argument("--receipts", type=Path)
    args = parser.parse_args()
    if args.assemble_from:
        if args.receipts is None:
            parser.error("assembly requires pilot receipts")
        assemble_release(args.inputs, args.assemble_from, args.receipts, args.release)
    return check_release(args.inputs, args.release, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
