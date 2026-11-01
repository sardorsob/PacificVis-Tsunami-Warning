"""Compare two frozen AI-assisted reviews without revising either opinion.

The private assignment join happens only after both review freezes are verified.
All rates and variance summaries describe this sample, not physical ground truth.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import argparse
import hashlib
import json
import shutil
import statistics
import sys
import tempfile
from collections import Counter
from datetime import timedelta
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.stations import (  # noqa: E402
    _original_archive_url,
    validate_reviewed_site_evidence,
)
from scripts.build_multi_event_catalog import (  # noqa: E402
    _inside,
    _json,
    _records,
    _sha,
    _utc,
    _verify,
    _write_csv,
    _write_json,
)

STATUSES = {"provisional_interval", "ambiguous", "unreviewable"}
MIN_PAIRS = 3
MIN_EVENTS = 2


def load_review(
    freeze_path: Path, catalog_path: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A freeze is mandatory; never inspect a work-in-progress review CSV."""
    freeze = _json(freeze_path)
    _utc(freeze["frozen_at_utc"])
    if Path(freeze["catalog_path"]).resolve() != catalog_path.resolve():
        raise ValueError("review refers to a different blind catalog")
    _verify(catalog_path, freeze["catalog_sha256"])
    for name in ("reviews", "methods"):
        suffix = ".csv" if name == "reviews" else ".md"
        _verify(freeze_path.parent / (name + suffix), freeze[name + "_sha256"])
    if freeze["reviewer_type"] != "AI-assisted" or freeze["physical_onset_validated"] is not False:
        raise ValueError("review must retain AI-assisted, unvalidated status")
    required_integrity = {
        "catalog_unchanged_since_inspection",
        "case_metadata_matches_catalog",
        "all_available_source_sha256_match_catalog",
        "all_supplied_chart_sha256_match_catalog",
    }
    if not all(freeze.get("input_integrity", {}).get(k) is True for k in required_integrity):
        raise ValueError("review lacks complete input-integrity declaration")
    for key in (
        "private_assignments_accessed",
        "comparison_labels_accessed",
        "other_reviews_accessed",
    ):
        if freeze.get("blinding", {}).get(key) is not False:
            raise ValueError("review blinding declaration is absent or violated")
    rows = _records(freeze_path.parent / "reviews.csv")
    ids = [r["case_id"] for r in rows]
    if (
        len(ids) != len(set(ids))
        or set(ids) != set(freeze["case_ids"])
        or len(ids) != freeze["assigned_case_count"]
        or len(ids) != freeze["reviewed_case_count"]
    ):
        raise ValueError("review coverage differs from its freeze")
    cases = {c["case_id"]: c for c in _json(catalog_path)["cases"]}
    for row in rows:
        if row["case_id"] not in cases:
            raise ValueError("review contains an unknown case")
        if (
            row["reviewer"] != freeze["reviewer"]
            or row["reviewer_type"] != "AI-assisted"
            or row["physical_onset_validated"].casefold() != "false"
            or row["status"] not in STATUSES
        ):
            raise ValueError("review contains invalid status or validation claim")
        if row["status"] == "provisional_interval":
            lower, upper = _utc(row["onset_lower_utc"]), _utc(row["onset_upper_utc"])
            reference = _utc(cases[row["case_id"]]["reference_utc"])
            if (
                not reference - timedelta(hours=6)
                <= lower
                <= upper
                <= reference + timedelta(hours=30)
            ):
                raise ValueError("review interval is reversed or outside the supplied window")
        elif row["onset_lower_utc"] or row["onset_upper_utc"]:
            raise ValueError("non-provisional review contains an interval")
    return freeze, rows


def agreement(left: dict[str, str], right: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "case_id": left["case_id"],
        "reviewer_a": left["reviewer"],
        "reviewer_b": right["reviewer"],
        "status_a": left["status"],
        "status_b": right["status"],
        "status_agrees": left["status"] == right["status"],
        "interval_comparison": "not_both_provisional",
        "onset_lower_utc_a": left["onset_lower_utc"],
        "onset_upper_utc_a": left["onset_upper_utc"],
        "onset_lower_utc_b": right["onset_lower_utc"],
        "onset_upper_utc_b": right["onset_upper_utc"],
    }
    if left["status"] == right["status"] == "provisional_interval":
        a, b = _utc(left["onset_lower_utc"]), _utc(left["onset_upper_utc"])
        c, d = _utc(right["onset_lower_utc"]), _utc(right["onset_upper_utc"])
        overlap = (min(b, d) - max(a, c)).total_seconds()
        result.update(
            interval_comparison="overlap" if overlap >= 0 else "disjoint",
            overlap_seconds=max(0, overlap),
            gap_seconds=max(0, -overlap),
            absolute_midpoint_difference_seconds=abs(((a - c) + (b - d)).total_seconds() / 2),
        )
    return result


def candidate_reports(
    case: dict[str, Any], private: dict[str, Any], reviewed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    selected_aliases = {s["trace_id"] for s in case["sources"] if s["selected_for_chart"]}
    sources = [a["source"] for a in private["aliases"] if a["trace_id"] in selected_aliases]
    candidates: dict[str, dict[str, Any]] = {}
    for row in reviewed:
        if row["event_id"] != private["key"][0]:
            continue
        headers = [h for alt in json.loads(row["evidence"]) for h in alt["headers"]]
        source_matches: list[bool] = []
        for source in sources:
            url = str(source["source_url"])
            if urlsplit(url).hostname == "api.tidesandcurrents.noaa.gov":
                matches = (
                    row["identity_scope"] == "authoritative_provider_site"
                    and row["provider"] == "CO-OPS"
                    and row["provider_station_id"] == source.get("provider_station_id")
                )
            else:
                original = _original_archive_url(url)
                matches = original != "unknown" and any(
                    h["original_url"] == original for h in headers
                )
            source_matches.append(matches)
        if source_matches and all(source_matches):
            candidates[row["report_id"]] = row
    return [candidates[k] for k in sorted(candidates)]


def variance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in rows if r["anchoring_status"] == "included_descriptive_proxy"]
    n, events = len(accepted), len({r["event_id"] for r in accepted})
    summary: dict[str, Any] = {
        "unique_pairs": n,
        "events": events,
        "minimum_pairs": MIN_PAIRS,
        "minimum_events": MIN_EVENTS,
        "status": "not_estimable",
        "exclusion_counts": dict(Counter(r["anchoring_status"] for r in rows)),
        "units": "seconds_squared",
        "interpretation": (
            "Sample variance with n-1 denominator; interval midpoint is a descriptive proxy, "
            "not a physical onset."
        ),
    }
    if n < MIN_PAIRS or events < MIN_EVENTS:
        summary["reason"] = "insufficient_unique_pairs_or_event_spread"
        return summary
    lower = [float(r["audit_lower_minus_est_seconds"]) for r in accepted]
    upper = [float(r["audit_upper_minus_est_seconds"]) for r in accepted]
    midpoint = [(a + b) / 2 for a, b in zip(lower, upper, strict=True)]
    # Var(x) = sum_{i<j}(xi-xj)^2 / [n(n-1)]. Each interval pair supplies
    # conservative bounds; pairwise extremes need not be jointly attainable.
    bounds = list(zip(lower, upper, strict=True))
    low = sum(max(0.0, a - d, c - b) ** 2 for (a, b), (c, d) in combinations(bounds, 2))
    high = sum(max(abs(a - d), abs(b - c)) ** 2 for (a, b), (c, d) in combinations(bounds, 2))
    summary.update(
        status="descriptive_only",
        observed_minus_est_variance=statistics.variance(
            float(r["observed_minus_est_seconds"]) for r in accepted
        ),
        audit_midpoint_minus_est_variance=statistics.variance(midpoint),
        all_lower_endpoints_variance=statistics.variance(lower),
        all_upper_endpoints_variance=statistics.variance(upper),
        conservative_interval_variance_lower_bound=low / (n * (n - 1)),
        conservative_interval_variance_upper_bound=high / (n * (n - 1)),
        bounds_note=(
            "Conservative pairwise bounds, not jointly optimized endpoints or confidence intervals."
        ),
    )
    return summary


def build(
    root: Path, package: Path, freezes: list[Path], crosswalk: Path, corpus: Path, output: Path
) -> dict[str, Any]:
    root = root.resolve()
    package, crosswalk, corpus = (_inside(root, p) for p in (package, crosswalk, corpus))
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if len(freezes) != 2:
        raise ValueError("exactly two frozen reviews are required")
    freezes = [_inside(root, p) for p in freezes]
    catalog_path = package / "blind/catalog.json"
    # Both freeze files must exist and verify before any private assignment is read.
    loaded = [load_review(p, catalog_path) for p in freezes]
    all_reviews = [r for _, rows in loaded for r in rows]
    cases = {c["case_id"]: c for c in _json(catalog_path)["cases"]}
    a, b = ({r["case_id"]: r for r in rows} for _, rows in loaded)
    if len(cases) != 69 or len(a) != 45 or len(b) != 45 or len(a.keys() & b.keys()) != 21:
        raise ValueError("audit requires 69 cases, two 45-case reviews and 21 overlapping cases")
    if a.keys() | b.keys() != cases.keys() or loaded[0][0]["reviewer"] == loaded[1][0]["reviewer"]:
        raise ValueError("audit coverage is incomplete or reviewers are identical")
    manifest = _json(package / "manifest.json")
    for name, digest in manifest["output_sha256"].items():
        _verify(_inside(package, Path(name)), digest)
    for name, digest in manifest["input_sha256"].items():
        _verify(_inside(root, Path(name)), digest)
    sample = _json(package / "private/sample.json")
    sample_digest = hashlib.sha256(
        json.dumps(
            {k: v for k, v in sample.items() if k != "sample_sha256"}, sort_keys=True
        ).encode()
    ).hexdigest()
    if sample_digest != sample["sample_sha256"] or sample_digest != manifest["sample_sha256"]:
        raise ValueError("audit sample checksum mismatch")
    private = {c["case_id"]: c for c in _json(package / "private/mapping.json")}
    if private.keys() != cases.keys() or {c["case_id"] for c in sample["cases"]} != cases.keys():
        raise ValueError("private assignment coverage mismatch")
    if Counter(c["key"][-1] for c in private.values()) != {"event_window": 60, "quiet_control": 9}:
        raise ValueError("frozen sample requires 60 event and 9 candidate-control cases")
    reviewed = [r for r in _records(crosswalk) if r["review_status"] == "independently_reviewed"]
    for row in reviewed:
        validate_reviewed_site_evidence(row)
    corpus_summary = _json(corpus / "summary.json")
    for name, digest in corpus_summary["output_sha256"].items():
        _verify(_inside(corpus, Path(name)), digest)
    pairs: dict[str, dict[str, str]] = {}
    for eid in corpus_summary["events"]:
        for pair in _records(corpus / eid / "pair.csv.gz"):
            if pair["event_id"] != eid or pair["report_id"] in pairs:
                raise ValueError("corpus event/report identity is inconsistent")
            pairs[pair["report_id"]] = pair
    overlaps = [agreement(a[cid], b[cid]) for cid in sorted(a.keys() & b.keys())]
    comparison: list[dict[str, Any]] = []
    for review in all_reviews:
        cid = review["case_id"]
        assignment = private[cid]
        row: dict[str, Any] = {
            **review,
            "event_id": assignment["key"][0],
            "assignment": assignment["key"][-1],
            "anchoring_status": "not_provisional",
            "candidate_report_ids": "[]",
        }
        if row["assignment"] == "quiet_control":
            row["anchoring_status"] = "candidate_control"
        elif review["status"] == "provisional_interval":
            candidates = candidate_reports(cases[cid], assignment, reviewed)
            row["candidate_report_ids"] = json.dumps([r["report_id"] for r in candidates])
            row["anchoring_status"] = (
                "unmatched_reviewed_site" if not candidates else "ambiguous_report_mapping"
            )
            if len(candidates) == 1:
                report_id = candidates[0]["report_id"]
                row["report_id"] = report_id
                pair = pairs.get(report_id)
                row["anchoring_status"] = "no_compatible_reported_clock_pair"
                if (
                    pair is not None
                    and pair["event_id"] == row["event_id"]
                    and pair["time_rule_id"] not in {"", "unknown"}
                ):
                    est, obs = _utc(pair["estimated_utc"]), _utc(pair["observed_utc"])
                    lower, upper = _utc(review["onset_lower_utc"]), _utc(review["onset_upper_utc"])
                    row.update(
                        anchoring_status="included_descriptive_proxy",
                        estimated_utc=pair["estimated_utc"],
                        observed_utc=pair["observed_utc"],
                        time_rule_id=pair["time_rule_id"],
                        reported_precision_seconds=pair["reported_precision_seconds"],
                        observed_minus_est_seconds=(obs - est).total_seconds(),
                        audit_lower_minus_est_seconds=(lower - est).total_seconds(),
                        audit_upper_minus_est_seconds=(upper - est).total_seconds(),
                        identity_scope=candidates[0]["identity_scope"],
                    )
        comparison.append(row)
    duplicate_counts = Counter(
        (r["reviewer"], r.get("report_id"))
        for r in comparison
        if r["anchoring_status"] == "included_descriptive_proxy"
    )
    for row in comparison:
        if (
            row["anchoring_status"] == "included_descriptive_proxy"
            and duplicate_counts[(row["reviewer"], row["report_id"])] > 1
        ):
            row["anchoring_status"] = "repeated_report_alias_for_reviewer"
    summaries: dict[str, Any] = {}
    for freeze, reviews in loaded:
        controls = [r for r in reviews if private[r["case_id"]]["key"][-1] == "quiet_control"]
        picks = sum(r["status"] == "provisional_interval" for r in controls)
        interpretable = sum(r["status"] != "unreviewable" for r in controls)
        summaries[freeze["reviewer"]] = {
            "status_counts": dict(Counter(r["status"] for r in reviews)),
            "candidate_control_assigned": len(controls),
            "candidate_control_interpretable": interpretable,
            "candidate_control_provisional_intervals": picks,
            "candidate_control_provisional_fraction_all": picks / len(controls)
            if controls
            else None,
            "candidate_control_provisional_fraction_interpretable": picks / interpretable
            if interpretable
            else None,
            "anchoring": variance_summary(
                [r for r in comparison if r["reviewer"] == freeze["reviewer"]]
            ),
        }
    summary = {
        "schema_version": "ai-assisted-blind-audit-comparison-v1",
        "sample_sha256": sample_digest,
        "case_count": len(cases),
        "review_count": len(all_reviews),
        "overlap_count": len(overlaps),
        "status_agreement_count": sum(r["status_agrees"] for r in overlaps),
        "interval_comparisons": dict(Counter(r["interval_comparison"] for r in overlaps)),
        "reviewers": summaries,
        "physical_onset_validated": False,
        "expert_ground_truth": False,
        "limitations": [
            "AI-assisted provisional judgments; both opinions remain unchanged, "
            "with no consensus truth.",
            "The reviewers were isolated fresh contexts of the same model family, "
            "not independent human experts; agreement may reflect shared model bias.",
            "Candidate controls are not independently certified tsunami-free; "
            "fractions are not validated false-positive rates.",
            "Metadata-balanced available-source sample, "
            "not representative archive-wide error rates.",
            "Raw water levels lack verified tide removal; "
            "visible dates and station metadata permit partial unblinding.",
            "Variance comparison is descriptive, subject to interval uncertainty, source "
            "dependence and incomplete pair matching; it cannot establish anchoring or causation.",
            "Reported UTC clocks and waveform timestamps are compared directly; "
            "no claim that NTWC used the same rupture origin.",
        ],
        "input_sha256": {
            str(p.relative_to(root)): _sha(p)
            for p in [package / "manifest.json", *freezes, crosswalk, corpus / "summary.json"]
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".audit-comparison-", dir=output.parent))
    try:
        _write_csv(temporary / "reviews_preserved.csv", all_reviews)
        _write_csv(temporary / "overlap.csv", overlaps)
        _write_csv(temporary / "case_comparison.csv", comparison)
        _write_json(temporary / "summary.json", summary)
        _write_json(
            temporary / "manifest.json",
            {
                "input_sha256": summary["input_sha256"],
                "output_sha256": {p.name: _sha(p) for p in sorted(temporary.iterdir())},
            },
        )
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--review-freeze", type=Path, action="append", required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        args.root, args.package, args.review_freeze, args.crosswalk, args.corpus, args.output
    )
    print(json.dumps({k: result[k] for k in ("case_count", "review_count", "overlap_count")}))


if __name__ == "__main__":
    main()
