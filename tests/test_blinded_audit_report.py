"""Post-freeze comparison preserves uncertainty, assignments and separate opinions."""

# pyright: reportPrivateUsage=false
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.build_blinded_audit_report import (
    agreement,
    build,
    candidate_reports,
    load_review,
    variance_summary,
)
from scripts.build_multi_event_catalog import _json, _records, _sha, _write_csv, _write_json


def fixture(root: Path) -> tuple[Path, list[Path], Path, Path]:
    package = root / "package"
    cases: list[dict[str, Any]] = [
        {"case_id": f"case-{i:03}", "reference_utc": "2011-03-11T05:46:24Z", "sources": []}
        for i in range(69)
    ]
    _write_json(package / "blind/catalog.json", {"cases": cases})
    private: list[dict[str, Any]] = [
        {
            "case_id": c["case_id"],
            "key": [
                "event-1",
                "CO-OPS",
                "site",
                "sensor",
                "quiet_control" if i % 8 == 0 else "event_window",
            ],
            "aliases": [],
        }
        for i, c in enumerate(cases)
    ]
    sample: dict[str, Any] = {"cases": private}
    sample["sample_sha256"] = hashlib.sha256(
        json.dumps(sample, sort_keys=True).encode()
    ).hexdigest()
    _write_json(package / "private/sample.json", sample)
    _write_json(package / "private/mapping.json", private)
    _write_json(
        package / "manifest.json",
        {
            "sample_sha256": sample["sample_sha256"],
            "input_sha256": {},
            "output_sha256": {
                str(p.relative_to(package)): _sha(p) for p in package.rglob("*") if p.is_file()
            },
        },
    )
    freezes: list[Path] = []
    for reviewer, subset in (("auditor-a", cases[:45]), ("auditor-b", cases[-45:])):
        folder = root / reviewer
        rows: list[dict[str, Any]] = [
            {
                "case_id": c["case_id"],
                "reviewer": reviewer,
                "reviewer_type": "AI-assisted",
                "status": "ambiguous",
                "onset_lower_utc": "",
                "onset_upper_utc": "",
                "physical_onset_validated": False,
                "reason": "synthetic ambiguity",
            }
            for c in subset
        ]
        if reviewer == "auditor-a":
            rows[0].update(
                status="provisional_interval",
                onset_lower_utc="2011-03-11T06:00:00Z",
                onset_upper_utc="2011-03-11T06:10:00Z",
            )
        _write_csv(folder / "reviews.csv", rows)
        (folder / "methods.md").write_text("Synthetic frozen test review.")
        freeze: dict[str, Any] = {
            "reviewer": reviewer,
            "reviewer_type": "AI-assisted",
            "physical_onset_validated": False,
            "frozen_at_utc": "2026-10-31T21:00:00Z",
            "catalog_path": str(package / "blind/catalog.json"),
            "catalog_sha256": _sha(package / "blind/catalog.json"),
            "reviews_sha256": _sha(folder / "reviews.csv"),
            "methods_sha256": _sha(folder / "methods.md"),
            "case_ids": [c["case_id"] for c in subset],
            "assigned_case_count": 45,
            "reviewed_case_count": 45,
            "input_integrity": {
                k: True
                for k in (
                    "catalog_unchanged_since_inspection",
                    "case_metadata_matches_catalog",
                    "all_available_source_sha256_match_catalog",
                    "all_supplied_chart_sha256_match_catalog",
                )
            },
            "blinding": {
                k: False
                for k in (
                    "private_assignments_accessed",
                    "comparison_labels_accessed",
                    "other_reviews_accessed",
                )
            },
        }
        _write_json(folder / "freeze.json", freeze)
        freezes.append(folder / "freeze.json")
    crosswalk = root / "crosswalk.csv"
    _write_csv(crosswalk, [], ["review_status"])
    corpus = root / "corpus"
    _write_json(corpus / "summary.json", {"events": {}, "output_sha256": {}})
    return package, freezes, crosswalk, corpus


def test_complete_coverage_keeps_all_opinions_and_candidate_control_denominator(
    tmp_path: Path,
) -> None:
    package, freezes, crosswalk, corpus = fixture(tmp_path)
    result = build(tmp_path, package, freezes, crosswalk, corpus, tmp_path / "out")
    assert (result["case_count"], result["review_count"], result["overlap_count"]) == (69, 90, 21)
    assert result["status_agreement_count"] == 21
    assert any("shared model bias" in note for note in result["limitations"])
    a = result["reviewers"]["auditor-a"]
    assert a["candidate_control_assigned"] == 6
    assert a["candidate_control_provisional_intervals"] == 1
    assert a["candidate_control_provisional_fraction_all"] == 1 / 6
    assert a["anchoring"]["status"] == "not_estimable"
    assert len(_records(tmp_path / "out/reviews_preserved.csv")) == 90
    assert build(tmp_path, package, freezes, crosswalk, corpus, tmp_path / "replay") == result
    assert _json(tmp_path / "out/manifest.json") == _json(tmp_path / "replay/manifest.json")
    with pytest.raises(FileExistsError):
        build(tmp_path, package, freezes, crosswalk, corpus, tmp_path / "out")


def test_missing_freeze_stops_before_private_assignment_read(tmp_path: Path) -> None:
    package, freezes, crosswalk, corpus = fixture(tmp_path)
    freezes[1].unlink()
    (package / "private/mapping.json").write_text("invalid JSON must not be reached")
    with pytest.raises(FileNotFoundError):
        build(tmp_path, package, freezes, crosswalk, corpus, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("change", ["reviews", "catalog", "blinding", "physical_claim"])
def test_review_freeze_is_enforced(tmp_path: Path, change: str) -> None:
    package, freezes, _, _ = fixture(tmp_path)
    freeze = _json(freezes[0])
    if change == "reviews":
        (freezes[0].parent / "reviews.csv").write_text("corruption")
    elif change == "catalog":
        (package / "blind/catalog.json").write_text("corruption")
    else:
        if change == "blinding":
            freeze["blinding"]["other_reviews_accessed"] = True
        else:
            freeze["physical_onset_validated"] = True
        _write_json(freezes[0], freeze)
    with pytest.raises(ValueError):
        load_review(freezes[0], package / "blind/catalog.json")


def test_interval_agreement_keeps_disjoint_and_different_statuses() -> None:
    a = {
        "case_id": "c",
        "reviewer": "a",
        "status": "provisional_interval",
        "onset_lower_utc": "2011-03-11T06:00:00Z",
        "onset_upper_utc": "2011-03-11T06:10:00Z",
    }
    b = {
        **a,
        "reviewer": "b",
        "onset_lower_utc": "2011-03-11T06:15:00Z",
        "onset_upper_utc": "2011-03-11T06:25:00Z",
    }
    r = agreement(a, b)
    assert r["interval_comparison"] == "disjoint" and r["gap_seconds"] == 300
    assert r["absolute_midpoint_difference_seconds"] == 900
    b.update(status="ambiguous", onset_lower_utc="", onset_upper_utc="")
    assert agreement(a, b)["status_agrees"] is False
    assert agreement(a, b)["interval_comparison"] == "not_both_provisional"


def test_variance_bounds_enclose_midpoint_and_endpoint_sensitivity() -> None:
    rows = [
        {
            "event_id": f"event-{i % 2}",
            "anchoring_status": "included_descriptive_proxy",
            "observed_minus_est_seconds": i * 10,
            "audit_lower_minus_est_seconds": i * 20 - 3,
            "audit_upper_minus_est_seconds": i * 20 + 7,
        }
        for i in range(3)
    ]
    result = variance_summary(rows)
    assert result["status"] == "descriptive_only"
    assert result["observed_minus_est_variance"] == 100
    assert result["audit_midpoint_minus_est_variance"] == 400
    assert (
        result["conservative_interval_variance_lower_bound"]
        <= 400
        <= result["conservative_interval_variance_upper_bound"]
    )
    assert variance_summary(rows[:2])["status"] == "not_estimable"
    assert (
        variance_summary([{**r, "event_id": "single"} for r in rows])["status"] == "not_estimable"
    )


def test_source_join_requires_all_selected_sources_and_keeps_multiple_reports() -> None:
    url = "https://www.tsunami.gov/previous.events/E/Data/abcd_A_2011.070"
    source = {"source_url": url}
    case: dict[str, Any] = {"sources": [{"trace_id": "trace-01", "selected_for_chart": True}]}
    private: dict[str, Any] = {
        "key": ["event-1"],
        "aliases": [{"trace_id": "trace-01", "source": source}],
    }
    row: dict[str, Any] = {
        "event_id": "event-1",
        "report_id": "event-1:1",
        "evidence": json.dumps([{"headers": [{"original_url": url}]}]),
    }
    assert len(candidate_reports(case, private, [row, {**row, "report_id": "event-1:2"}])) == 2
    case["sources"].append({"trace_id": "trace-02", "selected_for_chart": True})
    private["aliases"].append({"trace_id": "trace-02", "source": {"source_url": url + "1"}})
    assert not candidate_reports(case, private, [row])
