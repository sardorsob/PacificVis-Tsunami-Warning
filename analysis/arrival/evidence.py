"""Lossless table I/O and pinned inputs for reviewed arrival evidence."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, cast

UNKNOWN = {"", "unknown"}
Row = dict[str, str]


def sha256(path: Path) -> str:
    """Hash bytes without interpreting scientific contents."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    """Resolve a project-contained input, rejecting symlink escapes."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"input outside project root: {relative}")
    return path


def read_rows(path: Path) -> list[Row]:
    """Read literal UTF-8 cells; no missing-value or numeric coercion."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, value: Any) -> None:
    """Write a deterministic scientific manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def write_rows(path: Path, rows: list[Row], *, columns: list[str] | None = None) -> None:
    """Write sorted literal rows with reproducible gzip headers."""
    fields = columns or sorted({key for row in rows for key in row}) or ["record_id"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda row: tuple(row.get(key, "") for key in fields)))
    payload = buffer.getvalue().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload, mtime=0) if path.suffix == ".gz" else payload)


def verify_inputs(
    manifest: Path, *, expected_schema: str = "arrival_evidence_inputs_v1"
) -> dict[str, Any]:
    """Fail before processing when an immutable input is absent or changed."""
    document = cast(dict[str, Any], json.loads(manifest.read_text(encoding="utf-8")))
    root = Path(document["root"])
    if not document.get("files"):
        raise ValueError("missing pinned inputs")
    if document.get("schema_version") != expected_schema:
        raise ValueError("missing or unsupported input schema")
    pins = {item["path"]: item["sha256"] for item in document["files"]}
    if len(pins) != len(document["files"]):
        raise ValueError("duplicate input pins")
    for item in document["files"]:
        path = checked_path(root, item["path"])
        if not path.is_file():
            raise ValueError(f"missing pinned input: {item['path']}")
        if sha256(path) != item["sha256"]:
            raise ValueError(f"input hash mismatch: {item['path']}")
    if document.get("schema_version") == "arrival_evidence_inputs_v1":
        import tomllib

        config = document["event_config"]
        if config not in pins:
            raise ValueError("event config is not pinned")
        events = tomllib.loads(checked_path(root, config).read_text(encoding="utf-8"))["events"]
        if document["events"] != events:
            raise ValueError("manifest event roles disagree with pinned config")
        required = {f"{document['ncei']}/observations.csv.gz"}
        for event_id, event in events.items():
            if event["role"] == "development":
                required.update(f"{document['corpus']}/{event_id}/{name}.csv.gz"
                                for name in ["arrival_report", "target_eligibility"])
        if not required <= pins.keys():
            raise ValueError("derived source paths are not all pinned")
    return document


def development_reports(document: dict[str, Any], *, targets: bool = False) -> list[Row]:
    """Read only explicitly development event directories, never scan roles."""
    root = Path(document["root"])
    name = "target_eligibility.csv.gz" if targets else "arrival_report.csv.gz"
    rows: list[Row] = []
    for event_id, event in sorted(document["events"].items()):
        if event["role"] != "development":
            continue
        path = checked_path(root, f"{document['corpus']}/{event_id}/{name}")
        if not path.is_file():
            raise ValueError(f"missing development source file: {path}")
        values = read_rows(path)
        if any(row["event_id"] != event_id for row in values):
            raise ValueError(f"unexpected event inside development file: {path}")
        rows.extend(values)
    return rows


def require_development(rows: list[Row], events: dict[str, Any], key: str) -> None:
    """Reject a sealed or unknown event before deriving observations."""
    if any(events.get(row.get(key, ""), {}).get("role") != "development" for row in rows):
        raise ValueError("non-development event in source table")


def file_manifest(directory: Path) -> list[dict[str, str]]:
    """Bind generated scientific files without a self-referential manifest hash."""
    return [{"path": str(path.relative_to(directory)), "sha256": sha256(path)}
            for path in sorted(directory.rglob("*")) if path.is_file()
            and path.name != "manifest.json"]
