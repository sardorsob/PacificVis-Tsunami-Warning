"""Freeze the development evidence inputs and finite identity-review queues."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import (  # noqa: E402
    Row,
    checked_path,
    development_reports,
    file_manifest,
    read_rows,
    require_development,
    sha256,
    write_json,
    write_rows,
)

CORPUS = "data/processed/arrival-corpus/foundation-v5"
NCEI = "data/processed/ncei-arrivals/foundation-v1"
WAVES = "data/processed/arrival-waveforms/foundation-v5"
CROSSWALK = "artifacts/generated/ntwc-batch/crosswalk-reviewed-v3"
CENSUS = "artifacts/generated/ntwc-batch/census-v4"
CONFIG = "config/ntwc-archive-batch-v2.toml"
ACCEPTED_RELEASE = "data/processed/multi-event/foundation-v2/manifest.json"
ACCEPTED_RELEASE_SHA256 = "aeec2d24fc18002c2eae2cc85afab11818a051649804aa1fb0c0c3d5141cb2ec"
ACCEPTED_NCEI_OBSERVATIONS_SHA256 = (
    "61a936eb5cac291612cabbf330ce1bde34bcffff540f34e03ae522ee82253299"
)


def _pins(root: Path, paths: set[Path]) -> list[dict[str, str]]:
    """Validate containment before hashing each discovered leaf."""
    result: list[dict[str, str]] = []
    for path in sorted(paths):
        relative = str(path.relative_to(root))
        result.append({"path": relative, "sha256": sha256(checked_path(root, relative))})
    return result


def prepare(root: Path, output: Path) -> Path:
    """Pin current inputs and inventory geography opportunities without clocks."""
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite snapshot: {output}")
    # Trust the accepted release before reading any development outcome cells.
    release = checked_path(root, ACCEPTED_RELEASE)
    if not release.is_file() or sha256(release) != ACCEPTED_RELEASE_SHA256:
        raise ValueError("accepted release manifest missing or hash mismatch")
    accepted = json.loads(release.read_text(encoding="utf-8"))
    for relative, digest in accepted["input_sha256"].items():
        path = checked_path(root, relative)
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"accepted input missing or hash mismatch: {relative}")
    native = checked_path(root, f"{NCEI}/observations.csv.gz")
    if not native.is_file() or sha256(native) != ACCEPTED_NCEI_OBSERVATIONS_SHA256:
        raise ValueError("accepted NCEI observations missing or hash mismatch")
    config = checked_path(root, CONFIG)
    events: dict[str, Any] = tomllib.loads(config.read_text(encoding="utf-8"))["events"]
    document: dict[str, Any] = {
        "schema_version": "arrival_evidence_inputs_v1", "root": str(root),
        "events": events, "corpus": CORPUS, "ncei": NCEI, "waveforms": WAVES,
        "crosswalk": CROSSWALK, "census": CENSUS, "event_config": CONFIG,
    }
    reports = development_reports(document)
    targets = development_reports(document, targets=True)
    ncei = read_rows(checked_path(root, f"{NCEI}/observations.csv.gz"))
    require_development(ncei, events, "development_event_id")
    by_id = {row["report_id"]: row for row in reports}
    if len(by_id) != len(reports):
        raise ValueError("duplicate NTWC report ID")
    priorities: dict[str, set[str]] = {}
    counts: Counter[str] = Counter()
    for row in targets:
        reasons = json.loads(row["reason_codes"])
        if row["eligible"] == "True":
            counts[row["target_id"]] += 1
        if "geographic_identity_unreviewed" in reasons:
            tags = priorities.setdefault(row["report_id"], set())
            tags.add("geography_unreviewed")
            if reasons == ["geographic_identity_unreviewed"]:
                tags.add(row["target_id"] + "_geography_only")
    queue: list[Row] = []
    for report_id, tags in sorted(priorities.items()):
        row = by_id[report_id]
        queue.append({"event_id": row["event_id"], "report_id": report_id,
                      "source_label": row["source_label"],
                      "priority_flags": json.dumps(sorted(tags)),
                      "source_id": row.get("source_id", "unknown"),
                      "source_sha256": row.get("source_sha256", "unknown")})
    baseline = {
        "ntwc_source_rows": len(reports), "ncei_source_rows": len(ncei),
        "exact_pairs": sum(row.get("estimate_state") == row.get("observed_state")
                           == "exact_reported_timestamp" for row in reports),
        "exact_observed": sum(row.get("observed_state") == "exact_reported_timestamp"
                              for row in reports),
        "exact_estimated": sum(row.get("estimate_state") == "exact_reported_timestamp"
                               for row in reports),
        "target_counts": dict(counts), "geography_candidates": len(queue),
        "geography_only": dict(Counter(tag for tags in priorities.values()
                                       for tag in tags if tag.endswith("_only"))),
        "roles": dict(Counter(event["role"] for event in events.values())),
    }
    paths: set[Path] = {config, release}
    paths.update(checked_path(root, relative) for relative in accepted["input_sha256"])
    for name in [NCEI, WAVES, CROSSWALK, CENSUS, "data/raw/registries"]:
        directory = checked_path(root, name)
        if directory.exists():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    for event_id, event in events.items():
        if event["role"] == "development":
            directory = checked_path(root, f"{CORPUS}/{event_id}")
            if directory.exists():
                paths.update(path for path in directory.rglob("*") if path.is_file())
    paths.update(path for path in (root / "config").glob("*") if path.is_file())
    for row in ncei:
        paths.add(checked_path(root, row["raw_path"]))
    document["files"] = _pins(root, paths)
    protected_paths: set[Path] = set()
    for name in ["data", "public", "app/public"]:
        directory = root / name
        if directory.exists():
            protected_paths.update(path for path in directory.rglob("*") if path.is_file()
                                   and not path.is_relative_to(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".arrival-snapshot-", dir=output.parent))
    try:
        write_json(stage / "inputs.json", document)
        write_json(stage / "protected.json", {"schema_version": "protected_files_v1",
                                             "root": str(root),
                                             "files": _pins(root, protected_paths)})
        write_json(stage / "baseline.json", baseline)
        write_rows(stage / "geography_queue.csv.gz", queue)
        write_json(stage / "manifest.json", {"files": file_manifest(stage)})
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return output / "inputs.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.root, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
