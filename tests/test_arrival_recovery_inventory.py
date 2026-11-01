"""Synthetic source evidence exercises the offline recovery inventory contract."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.inventory_arrival_recovery import inventory_recovery

BASE = "artifacts/generated/ntwc-batch"
CORPUS = "data/processed/arrival-corpus/foundation-v4"
WAVES = "data/processed/arrival-waveforms/foundation-v4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(root: Path, name: str, value: Any) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_csv(path: Path, rows: list[dict[str, Any]], compressed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if compressed else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path) -> None:
    """Create five development reports and inaccessible reserved source evidence."""
    write_json(root, f"{BASE}/screen-v1/selection-v2.json", {"events": [
        {"event_id": "dev", "role": "development", "attribution_status": "single"},
        {"event_id": "reserved", "role": "sealed_evaluation"},
    ]})
    raw = root / "data/raw/page.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("<html>Synthetic development page</html>", encoding="utf-8")
    page_hash = sha(raw)
    write_json(root, f"{BASE}/census-v4/census.json", [
        {"event_id": "dev", "source_id": "page", "role": "development",
         "sha256": page_hash, "archive_url": "https://example.test/page", "arrival_tables": []},
        {"event_id": "reserved", "source_id": "sealed", "role": "sealed_evaluation",
         "sha256": "0" * 64, "archive_url": "https://example.test/sealed", "arrival_tables": []},
    ])
    rows: list[dict[str, Any]] = []
    reports: list[dict[str, str]] = []
    for index in range(1, 6):
        rid = f"dev:1:{index}"
        structural = "rejected_unknown_header" if index == 3 else "accepted_source_row"
        links = [{"href": "/a.dat", "text": "Data"}, {"href": "/a.dat", "text": "Again"}]
        row = dict(event_id="dev", source_id="page", role="development", table_index=1,
                   row_index=index, status=structural, fields={}, raw_html="<tr>synthetic</tr>",
                   cells=[{"links": links if index == 3 else [], "text": "synthetic"}])
        rows.append(row)
        estimate, observed = ("1200 (001)", "1210 (001)")
        if index == 2:
            estimate = "No ETA"
        if index == 4:
            estimate, observed = "1200", "1210"
        if index == 5:
            observed = "≈1210 (001)*"
        reports.append(dict(
            event_id="dev", report_id=rid, table_index="1", row_index=str(index), source_id="page",
            source_sha256=page_hash, structural_status=structural,
            header_family="estimated_observed_utc_jday", estimated_raw=estimate,
            observed_raw=observed, legacy_arrival_raw="", legacy_eta_raw="",
            estimate_state="date_ambiguous" if index == 4 else "exact_reported_timestamp",
            observed_state="date_ambiguous" if index == 4 else "exact_reported_timestamp",
            disposition="exact_reported_pair" if index == 1 else "rejected_or_uncertain",
            raw_row_json=json.dumps(row), reason_codes="[]",
        ))
    write_json(root, f"{BASE}/census-v4/rows.json", rows)
    write_json(root, f"{BASE}/census-v4/links.json", [])
    report_path = root / CORPUS / "dev/arrival_report.csv.gz"
    write_csv(report_path, reports, compressed=True)
    write_json(root, f"{CORPUS}/summary.json", dict(
        source_rows=5, exact_pairs=1, rejected_or_uncertain=4,
        events={"dev": {"source_rows": 5}},
        output_sha256={"dev/arrival_report.csv.gz": sha(report_path)},
        input_sha256={"rows": sha(root / f"{BASE}/census-v4/rows.json"),
                      "census": sha(root / f"{BASE}/census-v4/census.json")},
    ))
    crosswalk: list[dict[str, str]] = []
    alternatives: list[dict[str, str]] = []
    for report in reports:
        reviewed = report["row_index"] in {"1", "4"}
        common = dict(
            event_id="dev", report_id=report["report_id"], role="development",
            physical_site_id="coops:42" if reviewed else "unknown", provider="CO-OPS",
            provider_station_id="42", event_site_identity_verified=str(reviewed),
            review_status="independently_reviewed" if reviewed else "pending_independent_review",
            identity_tier="header_exact" if reviewed else "name_only",
            identity_evidence_sha256="a" * 64,
        )
        crosswalk.append({**common, "source_ids": '["wave-a"]' if reviewed else "[]"})
        alternatives.append({**common, "link_code": "alpha", "link_sensor": "A",
                             "report_site_identity_verified": str(reviewed),
                             "source_ids": '["wave-a"]' if reviewed else "[]"})
    alternatives.append({**alternatives[0], "link_sensor": "B", "source_ids": '["wave-b"]'})
    write_csv(root / f"{BASE}/crosswalk-reviewed-v3/unique_report_crosswalk.csv", crosswalk)
    write_csv(root / f"{BASE}/crosswalk-reviewed-v3/event_site.csv", alternatives)
    sources: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = [dict(
        source_id="page", local_path="data/raw/page.html", sha256=page_hash,
                       url="https://example.test/page", license_or_terms="synthetic fixture")]
    for sid, state in [("wave-a", "normalized_source_samples"),
                       ("wave-b", "retained_unparsed_source"), ("wave-c", "unavailable")]:
        source: dict[str, Any] = dict(
                      source_id=sid, event_id="dev", processing_status=state,
                      purpose="event_window",
                      acquisition_status="downloaded" if state != "unavailable" else "quarantined",
                      raw_path=f"data/raw/{sid}.dat", source_rows=0, source_url="https://example.test/data",
                      provider="CO-OPS", provider_station_id="42", sensor="unknown")
        if state != "unavailable":
            data = root / source["raw_path"]
            data.write_text("Synthetic 42 Provider Continuous 1 2 20000101\n"
                            "Radar cm UTC sec Unfiltered\n0 1 20000101000000\n", encoding="utf-8")
            source.update(source_sha256=sha(data), source_bytes=data.stat().st_size)
            provenance.append(dict(source_id=sid, local_path=source["raw_path"], sha256=sha(data),
                                   url=source["source_url"], license_or_terms="synthetic fixture"))
        if state == "normalized_source_samples":
            path = root / WAVES / "dev/wave-a.csv.gz"
            write_csv(path, [dict(source_id=sid, time="2000-01-01T00:00:00Z")], compressed=True)
            source.update(output_path="dev/wave-a.csv.gz", output_sha256=sha(path))
        if state == "retained_unparsed_source":
            source.update(parse_reason="unknown NTWC header shape", source_line_count=3)
        sources.append(source)
    sources.append(dict(source_id="outside", purpose="outside_observation_scope",
                        processing_status="outside_observation_scope", raw_path="unreadable.json"))
    write_json(root, f"{WAVES}/manifest.json", dict(sources=sources, input_sha256={}))
    write_csv(root / "artifacts/provenance/paper-source-manifest.csv", provenance)


def load(root: Path, name: str) -> Any:
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_conservation_gaps_links_alternatives_and_deterministic_replay(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = inventory_recovery(tmp_path, tmp_path / "out")
    assert result["counts"]["reports"] == 5
    assert result["counts"]["retained_unparsed_source"] == 1
    assert result["counts"]["structural_reports"] == 1
    assert result["counts"]["structural_link_occurrences"] == 2
    reports = load(tmp_path, "out/reports.json")
    assert {r["report_id"] for r in reports} == {f"dev:1:{i}" for i in range(1, 6)}
    absent = next(r for r in reports if r["report_id"] == "dev:1:2")
    assert absent["estimate_presence"] == "explicit_absence_token"
    assert absent["time_gap"] == "source_time_absent"
    joins = load(tmp_path, "out/report_waveforms.json")
    assert {r["source_id"] for r in joins if r["report_id"] == "dev:1:1"} == {
        "wave-a", "wave-b", "wave-c"}
    assert all(r["source_id"] == "unknown" for r in joins if r["report_id"] == "dev:1:2")
    assert {r["alternative_index"] for r in joins if r["report_id"] == "dev:1:1"} == {0, 1}
    assert all(r["join_scope"] in {"event_geographic_site_only", "unresolved"} for r in joins)
    samples = load(tmp_path, "out/representative_cases.json")
    assert any(s["record_id"] == "dev:1:3" and s["rule"] == "all_structural_rows" for s in samples)
    assert any(s["record_id"] == "dev:1:5" and "qualifier" in s["rule"] for s in samples)
    assert not any("reserved" in p for p in result["input_sha256"])
    assert "model_eligible" not in (tmp_path / "out/reports.json").read_text()
    inventory_recovery(tmp_path, tmp_path / "replay")
    assert {p.name: p.read_bytes() for p in (tmp_path / "out").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "replay").iterdir()}
    with pytest.raises(FileExistsError):
        inventory_recovery(tmp_path, tmp_path / "out")


@pytest.mark.parametrize("violation", [
    "reserved_row", "reserved_asset", "duplicate_report", "missing_report", "unreviewed_join",
    "changed_page", "changed_waveform", "changed_corpus", "path_escape", "bad_source_list",
])
def test_bad_inputs_never_publish_partial_output(tmp_path: Path, violation: str) -> None:
    fixture(tmp_path)
    rows_path = f"{BASE}/census-v4/rows.json"
    if violation in {"reserved_row", "duplicate_report", "missing_report"}:
        rows = load(tmp_path, rows_path)
        if violation == "reserved_row":
            rows[0]["event_id"], rows[0]["role"] = "reserved", "development"
        elif violation == "duplicate_report":
            rows.append(rows[0])
        else:
            rows.pop()
        write_json(tmp_path, rows_path, rows)
    elif violation in {"reserved_asset", "path_escape"}:
        document = load(tmp_path, f"{WAVES}/manifest.json")
        if violation == "reserved_asset":
            document["sources"][0]["event_id"] = "reserved"
        else:
            document["sources"][0]["raw_path"] = "../outside.dat"
        write_json(tmp_path, f"{WAVES}/manifest.json", document)
    elif violation in {"unreviewed_join", "bad_source_list"}:
        path = tmp_path / f"{BASE}/crosswalk-reviewed-v3/event_site.csv"
        with path.open(encoding="utf-8") as handle:
            alternatives = list(csv.DictReader(handle))
        if violation == "unreviewed_join":
            alternatives[0]["event_id"] = "reserved"
        else:
            alternatives[0]["source_ids"] = '"not a list"'
        write_csv(path, alternatives)
    elif violation == "changed_page":
        (tmp_path / "data/raw/page.html").write_text("changed", encoding="utf-8")
    elif violation == "changed_waveform":
        (tmp_path / "data/raw/wave-b.dat").write_text("changed", encoding="utf-8")
    else:
        (tmp_path / CORPUS / "dev/arrival_report.csv.gz").write_bytes(b"changed")
    with pytest.raises((ValueError, FileNotFoundError)):
        inventory_recovery(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".arrival-recovery-*"))


@pytest.mark.parametrize("estimate_state,observed_state,expected", [
    ("date_ambiguous", "exact_reported_timestamp", "date_context_review"),
    ("exact_reported_timestamp", "date_ambiguous", "date_context_review"),
    ("date_ambiguous", "qualified_value", "qualified_time_review"),
])
def test_frozen_corpus_state_names_are_classified_without_label_changes(
    tmp_path: Path, estimate_state: str, observed_state: str, expected: str,
) -> None:
    fixture(tmp_path)
    path = tmp_path / CORPUS / "dev/arrival_report.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        reports = list(csv.DictReader(handle))
    reports[3].update(estimate_state=estimate_state, observed_state=observed_state)
    write_csv(path, reports, compressed=True)
    summary = load(tmp_path, f"{CORPUS}/summary.json")
    summary["output_sha256"]["dev/arrival_report.csv.gz"] = sha(path)
    write_json(tmp_path, f"{CORPUS}/summary.json", summary)
    inventory_recovery(tmp_path, tmp_path / "out")
    ledger = load(tmp_path, "out/reports.json")
    assert next(r for r in ledger if r["report_id"] == "dev:1:4")["time_gap"] == expected


def test_write_failure_cleans_staging_and_leaves_inputs_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import inventory_arrival_recovery

    fixture(tmp_path)
    before = {
        p.relative_to(tmp_path).as_posix(): sha(p) for p in tmp_path.rglob("*") if p.is_file()}

    def failed_write(stage: Path, name: str, rows: list[dict[str, Any]]) -> None:
        (stage / f"{name}.json").write_text("partial", encoding="utf-8")
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(inventory_arrival_recovery, "_write_tables", failed_write)
    with pytest.raises(OSError, match="synthetic storage failure"):
        inventory_recovery(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".arrival-recovery-*"))
    assert before == {
        p.relative_to(tmp_path).as_posix(): sha(p) for p in tmp_path.rglob("*") if p.is_file()}
