"""Build a separate paper source ledger from explicit immutable acquisition runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.provenance import REQUIRED_COLUMNS, validate_manifest  # noqa: E402


def build(root: Path, runs: list[Path]) -> list[dict[str, str]]:
    """Retain one source identity, all attempt references, and verified local bytes."""
    records: dict[str, dict[str, Any]] = {}
    for run in sorted(runs):
        meta = json.loads((run / "meta.json").read_text())
        inputs = {x["source_id"]: x for x in json.loads((run / "inputs.json").read_text())}
        config = json.loads((run / "config.json").read_text())
        terms = str(tomllib.loads(config["toml"]).get("terms", "unknown"))
        for outcome in json.loads((run / "outputs.json").read_text()):
            sid = outcome["source_id"]
            source = inputs[sid]
            if sid in records:
                previous = records[sid]["source"]
                for key in ("url", "local_path", "source_class"):
                    if source[key] != previous[key]:
                        raise ValueError(f"source identity changed: {sid}: {key}")
            else:
                records[sid] = {
                    "source": source, "terms": terms, "attempts": [], "metadata_changes": [],
                    "success": None, "last": outcome, "date": meta["timestamp_utc"][:10],
                }
            item = records[sid]
            if source["publisher"] != item["source"]["publisher"]:
                item["metadata_changes"].append({
                    "field": "publisher", "previous": item["source"]["publisher"],
                    "updated": source["publisher"], "run": run.name,
                })
                item["source"] = source
            item["attempts"].append({
                "run": run.name, "status": outcome["status"], "reason": outcome["reason"]
            })
            item["last"] = outcome
            if outcome["status"] in {"downloaded", "cached"}:
                previous_success = item["success"]
                if previous_success and previous_success["sha256"] != outcome["sha256"]:
                    raise ValueError(f"successful source bytes changed: {sid}")
                if previous_success is None:
                    item["date"] = meta["timestamp_utc"][:10]
                item["success"] = outcome
                item["source"] = source
    result: list[dict[str, str]] = []
    for sid, item in sorted(records.items()):
        source = item["source"]
        success = item["success"]
        if success:
            path = root / source["local_path"]
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"source path outside project: {sid}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sidecar = path.with_name(path.name + ".sha256").read_text().strip()
            if digest != success["sha256"] or digest != sidecar:
                raise ValueError(f"source checksum mismatch: {sid}")
        else:
            digest = "not-downloaded"
        result.append({
            "source_id": sid,
            "title": source["source_class"] + ": " + sid,
            "publisher": source["publisher"],
            "url": source["url"],
            "accessed_on": item["date"],
            "status": "candidate" if success else "blocked",
            "version_or_date": "immutable snapshot; acquisition runs in notes",
            "license_or_terms": item["terms"],
            "spatial_reference": source["crs"],
            "horizontal_datum": source["horizontal_datum"],
            "vertical_datum": source["vertical_datum"],
            "coordinate_order": source["coordinate_order"],
            "temporal_reference": source["temporal_semantics"],
            "units": source["units"],
            "processing_level": "raw source snapshot" if success else "unavailable request",
            "missingness": "unassessed; see product QC" if success else item["last"]["reason"],
            "sha256": digest,
            "local_path": source["local_path"] if success else "not-downloaded",
            "notes": json.dumps({"station_metadata": source["station_metadata"],
                                 "attempts": item["attempts"],
                                 "metadata_changes": item["metadata_changes"],
                                 "scientific_acceptance": "not implied"}, sort_keys=True),
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/provenance/paper-source-manifest.csv"))
    args = parser.parse_args()
    baseline = args.root / "artifacts/provenance/source-manifest.csv"
    if args.output.resolve() == baseline.resolve():
        parser.error("paper ledger must not replace the story manifest")
    rows = build(args.root, args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        validate_manifest(temporary)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"sources": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
