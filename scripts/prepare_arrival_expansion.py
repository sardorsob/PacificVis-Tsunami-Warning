"""Freeze metadata candidates without importing outcome fields into the screen."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import (  # noqa: E402
    Row,
    file_manifest,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)
from analysis.arrival.lineage import load_pilot  # noqa: E402

METADATA_FIELDS = (
    "id",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "latitude",
    "longitude",
    "eqDepth",
    "eqMagnitude",
    "causeCode",
    "earthquakeEventId",
    "volcanoEventId",
    "country",
    "locationName",
    "regionCode",
    "area",
)


def project_metadata(native: dict[str, Any]) -> Row:
    """Project before any selection, value inspection or downstream export."""
    return {
        key: str(native[key]) if key in native and native[key] is not None else "unknown"
        for key in METADATA_FIELDS
    }


def prepare_expansion(inputs: Path, receipts: Path, output: Path) -> Path:
    document = verify_inputs(inputs)
    root = Path(document["root"])
    pilot = load_pilot(root, receipts)
    if output.exists():
        raise ValueError("output already exists")
    candidates: list[Row] = []
    queries: list[Row] = []
    for receipt in pilot:
        if not receipt["source_id"].startswith("arrival-pilot-metadata-"):
            continue
        raw = json.loads((root / receipt["local_path"]).read_text())
        safe = [project_metadata(item) for item in raw["items"]]
        if raw["page"] != 1 or raw["totalPages"] != 1 or len(safe) != raw["totalItems"]:
            raise ValueError("incomplete metadata query")
        query = receipt["source_id"].removeprefix("arrival-pilot-metadata-")
        queries.append(
            {
                "query_id": query,
                "status": receipt["status"],
                "retained_items": str(len(safe)),
                "source_sha256": receipt["sha256"],
                "source_path": receipt["local_path"],
            }
        )
        for row in safe:
            candidates.append(
                {
                    **row,
                    "query_id": query,
                    "native_event_id": row["id"],
                    "source_path": receipt["local_path"],
                    "source_sha256": receipt["sha256"],
                    "source_locator": "items[id=" + row["id"] + "]",
                    "frozen_role": "not_in_frozen_selection",
                    "proposed_role": "conditional_development_gap"
                    if query == "sulawesi-gap"
                    else "prospective_evaluation_candidate",
                    "adoption_state": "deferred_by_scope",
                    "sequence_group": "candidate-seq-ncei-20210304"
                    if len(safe) > 1
                    else "candidate-seq-ncei-" + row["id"],
                    "sequence_status": "requires_independence_and_attribution_review",
                    "compound_source_flag": str(
                        row["volcanoEventId"] != "unknown" and row["earthquakeEventId"] != "unknown"
                    ),
                    "evaluation_outcome_access": "not_authorized",
                    "model_eligible": "False",
                    "magnitude_type": "unknown",
                    "depth_units": "unknown",
                    "coordinate_crs": "unknown",
                    "time_basis": "source_native_not_reproved_UTC",
                    "selection_rule": "frozen_date_region_era_gap_v1",
                    "coverage_gap": "archive_gap" if query == "sulawesi-gap" else "post_2018_era",
                    "coordinator_metadata_exposure": "embedded_outcome_diagnostic_disclosed",
                }
            )
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for event_id, event in document["events"].items():
        groups[event["sequence_group"]].append((event_id, event["role"]))
    crossrole = [
        {
            "sequence_group": group,
            "event_id": event,
            "role": role,
            "role_change_allowed": "False",
            "outcomes_inspected": "False",
        }
        for group, members in groups.items()
        if len({r for _, r in members}) > 1
        for event, role in members
    ]
    branches = [
        {
            "branch": "F1",
            "status": "deferred_by_scope",
            "next_contract": "NCEI5689 runups after comparable target/source approval",
        },
        {
            "branch": "F2",
            "status": "deferred_by_scope",
            "next_contract": (
                "NCEI5769/5770/5771/5799/6044 outcomes after protocol/model freeze "
                "and exposure review"
            ),
        },
        {
            "branch": "F3",
            "status": "deferred_by_scope",
            "next_contract": "DART target and reviewed20-contract/50MB pilot before acquisition",
        },
        {
            "branch": "F4",
            "status": "deferred_by_scope",
            "next_contract": "Scope approval for bulletins/JMA/IOC/UHSLC/ETOPO",
        },
    ]
    for name, rows in [
        ("candidates", candidates),
        ("queries", queries),
        ("cross_role_sequences", crossrole),
        ("branches", branches),
    ]:
        write_rows(output / (name + ".csv.gz"), rows)
    write_json(
        output / "summary.json",
        {
            "queries": len(queries),
            "native_event_candidates": len(candidates),
            "outcomes_used_for_selection": False,
            "roles_redrawn": False,
            "coordinator_exposure": (
                "Raw-schema diagnostic printed embedded outcomes after query freeze. "
                "No blindness claim. Independent metadata review used whitelist before inspection."
            ),
            "model_or_outcome_acquisition_authorized": False,
        },
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": "arrival_expansion_metadata_v1",
            "inputs_sha256": sha256(inputs),
            "receipt_sha256": sha256(receipts / "outputs.json"),
            "metadata_whitelist": list(METADATA_FIELDS),
            "files": file_manifest(output),
        },
    )
    return output / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["inputs", "receipts", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(prepare_expansion(args.inputs, args.receipts, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
