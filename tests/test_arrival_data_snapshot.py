"""Completion snapshots must protect source bytes and exclude held-out rows."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from analysis.arrival.evidence import checked_path, read_rows, verify_inputs, write_rows
from scripts import prepare_arrival_data_completion as snapshot
from scripts.prepare_arrival_data_completion import prepare


def test_reproducible_gzip_and_missing_states(tmp_path: Path) -> None:
    rows = [{"id": "b", "value": "unknown"}, {"id": "a", "value": "0"}]
    first, second = tmp_path / "a.csv.gz", tmp_path / "b.csv.gz"
    write_rows(first, rows)
    write_rows(second, list(reversed(rows)))
    assert first.read_bytes() == second.read_bytes()
    assert read_rows(first) == [{"id": "a", "value": "0"}, {"id": "b", "value": "unknown"}]


def test_manifest_rejects_changed_or_missing_input(tmp_path: Path) -> None:
    raw = tmp_path / "raw.txt"
    raw.write_text("native\n", encoding="utf-8")
    manifest = tmp_path / "inputs.json"
    manifest.write_text(json.dumps({"schema_version": "file_pins_v1",
                                   "root": str(tmp_path), "files": [
        {"path": "raw.txt", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}
    ]}), encoding="utf-8")
    assert verify_inputs(manifest, expected_schema="file_pins_v1")["root"] == str(tmp_path)
    raw.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        verify_inputs(manifest, expected_schema="file_pins_v1")
    raw.unlink()
    with pytest.raises(ValueError, match="missing"):
        verify_inputs(manifest, expected_schema="file_pins_v1")


def test_containment_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("protected", encoding="utf-8")
    (root / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        checked_path(root, "escape")


def test_snapshot_does_not_parse_sealed_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/ntwc-archive-batch-v2.toml").write_text(
        '[events.dev]\nrole="development"\nusgs_time="2011-03-11T05:46:00Z"\n'
        '[events.sealed]\nrole="sealed_evaluation"\n', encoding="utf-8"
    )
    corpus = tmp_path / "data/processed/arrival-corpus/foundation-v5"
    (corpus / "dev").mkdir(parents=True)
    (corpus / "sealed").mkdir()
    # If parsed, this intentionally malformed gzip would fail.
    (corpus / "sealed/arrival_report.csv.gz").write_bytes(b"sealed-outcome-sentinel")
    row = {"event_id": "dev", "report_id": "dev:0:1", "source_label": "Example",
           "observed_state": "exact_reported_timestamp", "estimate_state": "source_absent",
           "observed_utc": "2011-03-11T06:00:00Z"}
    write_rows(corpus / "dev/arrival_report.csv.gz", [row])
    write_rows(corpus / "dev/target_eligibility.csv.gz", [{
        "event_id": "dev", "report_id": "dev:0:1", "target_id": "T-OBS",
        "eligible": "False", "reason_codes": '["geographic_identity_unreviewed"]'}])
    ncei = tmp_path / "data/processed/ncei-arrivals/foundation-v1"
    ncei.mkdir(parents=True)
    write_rows(ncei / "observations.csv.gz", [])
    release = tmp_path / snapshot.ACCEPTED_RELEASE
    release.parent.mkdir(parents=True)
    raw = tmp_path / "data/raw/ntwc/dev.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("native source", encoding="utf-8")
    pinned = [raw, tmp_path / snapshot.CONFIG, corpus / "dev/arrival_report.csv.gz",
              corpus / "dev/target_eligibility.csv.gz"]
    release.write_text(json.dumps({"input_sha256": {
        str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in pinned}}), encoding="utf-8")
    monkeypatch.setattr(snapshot, "ACCEPTED_RELEASE_SHA256",
                        hashlib.sha256(release.read_bytes()).hexdigest())
    monkeypatch.setattr(snapshot, "ACCEPTED_NCEI_OBSERVATIONS_SHA256",
                        hashlib.sha256((ncei / "observations.csv.gz").read_bytes()).hexdigest())
    first = prepare(tmp_path, tmp_path / "first")
    first_rows = read_rows(first.parent / "geography_queue.csv.gz")
    (corpus / "sealed/arrival_report.csv.gz").write_bytes(b"different-sealed-outcome")
    second = prepare(tmp_path, tmp_path / "second")
    assert first_rows == read_rows(second.parent / "geography_queue.csv.gz")
    assert len(first_rows) == 1
    assert first_rows[0]["event_id"] == "dev"
    assert not any("utc" in key or key.endswith("_raw") for key in first_rows[0])
    verify_inputs(first)
    changed = json.loads(first.read_text(encoding="utf-8"))
    changed.pop("schema_version")
    changed["events"]["sealed"]["role"] = "development"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        verify_inputs(bad)
    raw.write_text("corrupted source", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        verify_inputs(first)
    raw.write_text("native source", encoding="utf-8")
    registry = tmp_path / "data/raw/registries"
    registry.mkdir()
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text("not an authorized input", encoding="utf-8")
    (registry / "escaped.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        prepare(tmp_path, tmp_path / "escaped-output")
    (registry / "escaped.txt").unlink()
    changed = json.loads(first.read_text(encoding="utf-8"))
    changed["events"]["sealed"]["role"] = "development"
    first.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="roles"):
        verify_inputs(first)
    (corpus / "dev/arrival_report.csv.gz").unlink()
    with pytest.raises(ValueError, match="missing"):
        prepare(tmp_path, tmp_path / "third")


def test_empty_pin_manifest_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"root": str(tmp_path), "files": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing pinned"):
        verify_inputs(path)


def test_csv_read_keeps_zero_distinct_from_missing(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["value"])
        writer.writeheader()
        writer.writerows([{"value": "0"}, {"value": "unknown"}])
    assert [row["value"] for row in read_rows(path)] == ["0", "unknown"]
