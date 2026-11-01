"""Run the frozen eight-setting raw-excursion diagnostic separately from blind picks.

No arrival labels, predictions, contours, tide subtraction or sentinel inference.
Control assignments are read only after case results have been written and hashed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shutil
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.eda import Sample, detect_crossing  # noqa: E402
from scripts.generate_waveform_contracts import parse_utc  # noqa: E402

VALID_TIMES = {
    "reported_utc",
    "epoch_calendar_agree",
    "epoch_calendar_minute_agree",
    "header_day_end_boundary",
}
UNIT_FACTORS = {"m": 1.0, "meters": 1.0, "metres": 1.0, "cm": 0.01}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("artifact path escapes its root")
    return path


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def protocol(config: Path) -> dict[str, Any]:
    settings = tomllib.loads(config.read_text())
    frozen = dict(
        baseline_hours=[2, 4],
        threshold_floors_m=[0.03, 0.05],
        persistence_seconds=[60, 120],
        noise_multiplier=5.0,
        minimum_baseline_samples=6,
        minimum_baseline_coverage=0.9,
        coastal_max_gap_seconds=120,
        search_hours=30,
    )
    if any(settings.get(k) != v for k, v in frozen.items()):
        raise ValueError("existing eight-setting protocol differs from frozen contract")
    return dict(
        **frozen,
        protocol_id="ntwc-raw-excursion-eight-settings-v1",
        field="raw",
        control_search_hours=30,
        unit_factors_to_m=UNIT_FACTORS,
        duplicate_rule="All samples at duplicate timestamps excluded; one missing marker retained.",
        qc_rule="Nonempty QC without an implemented source-specific interpretation excluded.",
        sentinel_rule="No undocumented numeric sentinel reinterpretation.",
        cadence_rule="Native declared integer seconds; cadence above120s unsupported.",
        interpretation="Raw water-level excursions are tide-confounded diagnostics, "
        "not physical onsets.",
    )


def prepare_case(case: dict[str, Any], blind: Path) -> tuple[list[Sample], dict[str, Any]]:
    selected = [s for s in case["sources"] if s.get("selected_for_chart")]
    report: dict[str, Any] = dict(
        selected_trace_ids=[s["trace_id"] for s in selected],
        source_rows=0,
        row_exclusions={},
        unsupported_reasons=[],
    )
    reasons: list[str] = report["unsupported_reasons"]
    if not selected or any(s["status"] != "normalized_source_samples" for s in selected):
        reasons.append("no_normalized_selected_source")
        return [], report
    units = {s["units"] for s in selected}
    cadences = {s["declared_cadence_seconds"] for s in selected}
    datums = {s["vertical_datum"] for s in selected}
    if len(units) != 1 or not units <= set(UNIT_FACTORS):
        reasons.append("unsupported_or_mixed_units")
    if len(datums) != 1:
        reasons.append("mixed_vertical_datums")
    if len(cadences) != 1 or not all(
        isinstance(c, (int, float)) and math.isfinite(c) and c > 0 and int(c) == c and c <= 120
        for c in cadences
    ):
        reasons.append("unsupported_cadence_for_120s_gap_contract")
    if reasons:
        return [], report
    cadence = int(next(iter(cadences)))
    units_name = next(iter(units))
    factor = UNIT_FACTORS[units_name]
    grouped: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for source in selected:
        path = inside(blind, source["path"])
        if sha(path) != source["sha256"]:
            raise ValueError("blind trace checksum mismatch")
        with gzip.open(path, "rt", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != source["rows"]:
            raise ValueError("blind trace row count mismatch")
        report["source_rows"] += len(rows)
        for row in rows:
            if row["units"] != units_name or row["vertical_datum"] != next(iter(datums)):
                raise ValueError("trace measurement semantics differ from case")
            if row["timestamp_state"] not in VALID_TIMES:
                counts["invalid_timestamp_rows"] += 1
                continue
            grouped[parse_utc(row["timestamp_utc"])].append(row)
    samples: list[Sample] = []
    for at, rows in sorted(grouped.items()):
        row = rows[0]
        bad, value = False, None
        if len(rows) > 1 or any(r["duplicate_timestamp"].casefold() == "true" for r in rows):
            counts["duplicate_timestamp_rows"] += len(rows)
            bad = True
        elif row["value_state"] != "finite_numeric":
            counts["typed_missing_value_rows"] += 1
        elif row["qc_state"] != "not_provided" and json.loads(row["qc_json"]):
            counts["uninterpreted_qc_rows"] += 1
            bad = True
        else:
            value = float(row["numeric_value"]) * factor
            if not math.isfinite(value):
                raise ValueError("finite numeric state conflicts with sample")
        samples.append(Sample(at, row["raw_timestamp"], value, None, None, bad))
    report.update(
        row_exclusions=dict(counts),
        detector_sample_count=len(samples),
        native_units=units_name,
        conversion_factor_to_m=factor,
        declared_cadence_seconds=cadence,
        vertical_datum=next(iter(datums)),
        numeric_sentinel_conventions="unverified; source finite values unchanged",
    )
    return samples, report


def run_case(case: dict[str, Any], blind: Path, settings: dict[str, Any]) -> dict[str, Any]:
    samples, report = prepare_case(case, blind)
    results: list[dict[str, Any]] = []
    for baseline, floor, persistence in product(
        settings["baseline_hours"], settings["threshold_floors_m"], settings["persistence_seconds"]
    ):
        result: dict[str, Any]
        if report["unsupported_reasons"]:
            result = dict(status="unsupported", candidate_utc="unknown")
        else:
            result = dict(
                detect_crossing(
                    samples,
                    origin=parse_utc(case["reference_utc"]),
                    baseline_hours=baseline,
                    threshold_floor=floor,
                    noise_multiplier=settings["noise_multiplier"],
                    persistence_seconds=persistence,
                    max_gap_seconds=settings["coastal_max_gap_seconds"],
                    support_cadence=report["declared_cadence_seconds"],
                    minimum_samples=settings["minimum_baseline_samples"],
                    minimum_coverage=settings["minimum_baseline_coverage"],
                    search_hours=settings["search_hours"],
                    field="raw",
                )
            )
        result.update(
            setting_id=f"baseline{baseline}-floor{floor:g}-persist{persistence}",
            baseline_hours=baseline,
            threshold_floor_m=floor,
            persistence_seconds=persistence,
        )
        results.append(result)
    return dict(
        case_id=case["case_id"],
        reference_utc=case["reference_utc"],
        preparation=report,
        settings=results,
        physical_onset_validated=False,
        modeled_arrival_utc="unavailable",
        interpretation=settings["interpretation"],
    )


def control_summary(results: list[dict[str, Any]], sample: dict[str, Any]) -> dict[str, Any]:
    purposes = {r["case_id"]: r["key"][-1] for r in sample["cases"]}
    if set(purposes) != {r["case_id"] for r in results} or len(purposes) != len(sample["cases"]):
        raise ValueError("frozen case IDs differ from diagnostic case IDs")
    if not set(purposes.values()) <= {"event_window", "quiet_control"}:
        raise ValueError("unknown frozen case purpose")
    controls = [r for r in results if purposes[r["case_id"]] == "quiet_control"]
    settings = [s for r in controls for s in r["settings"]]
    complete = [
        s
        for s in settings
        if isinstance(s.get("search_coverage"), (int, float))
        and s["search_coverage"] >= 0.9
        and s["search_max_gap_seconds"] <= 120
    ]
    crossings = sum(s["status"] == "candidate" for s in settings)
    return dict(
        control_cases=len(controls),
        total_control_settings=len(settings),
        status_counts=dict(Counter(s["status"] for s in settings)),
        settings_with_raw_crossing=crossings,
        raw_crossing_fraction_all_settings=crossings / len(settings) if settings else None,
        complete_search_settings=len(complete),
        raw_crossing_fraction_complete_search=sum(s["status"] == "candidate" for s in complete)
        / len(complete)
        if complete
        else None,
        cases_with_any_raw_crossing=sum(
            any(s["status"] == "candidate" for s in r["settings"]) for r in controls
        ),
        interpretation="Raw-level crossing rate; neither validated false-onset rate "
        "nor independent-trial probability.",
    )


def build(audit: Path, config: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((audit / "manifest.json").read_text())
    if not {"blind/catalog.json", "private/sample.json"} <= set(manifest["output_sha256"]):
        raise ValueError("audit manifest omits required frozen inputs")
    for name, digest in manifest["output_sha256"].items():
        if sha(inside(audit, name)) != digest:
            raise ValueError("frozen audit artifact checksum mismatch")
    cases = json.loads((audit / "blind/catalog.json").read_text())["cases"]
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("duplicate blind case identity")
    settings = protocol(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".waveform-diagnostics-", dir=output.parent))
    try:
        write_json(temporary / "protocol.json", settings)
        results = [
            run_case(case, audit / "blind", settings)
            for case in sorted(cases, key=lambda c: c["case_id"])
        ]
        write_json(temporary / "case-results.json", results)
        results_sha = sha(temporary / "case-results.json")
        # Only now read assignments; they cannot change protocol or case results.
        sample = json.loads((audit / "private/sample.json").read_text())
        material = {k: v for k, v in sample.items() if k != "sample_sha256"}
        sample_sha = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        if sample_sha != sample["sample_sha256"] or sample_sha != manifest["sample_sha256"]:
            raise ValueError("frozen sample digest mismatch")
        control = control_summary(results, sample)
        summary = dict(
            protocol_id=settings["protocol_id"],
            sample_sha256=sample_sha,
            case_count=len(results),
            setting_count=sum(len(r["settings"]) for r in results),
            status_counts=dict(Counter(s["status"] for r in results for s in r["settings"])),
            quiet_controls=control,
            case_results_sha256_before_assignment_read=results_sha,
            physical_onsets_validated=0,
            human_picks_read=False,
            limitations=[
                settings["interpretation"],
                settings["sentinel_rule"],
                settings["qc_rule"],
                "Unsupported, baseline-insufficient and incomplete-search settings "
                "remain in total denominators.",
                "Controls exclude known M>=6.5 catalog events only; smaller events "
                "or other disturbances remain possible.",
            ],
            input_sha256={
                str(p): sha(p)
                for p in [
                    audit / "manifest.json",
                    config,
                    Path(__file__),
                    Path(__file__).resolve().parents[1] / "pipeline/eda.py",
                ]
            },
        )
        write_json(temporary / "summary.json", summary)
        write_json(
            temporary / "manifest.json",
            dict(
                input_sha256=summary["input_sha256"],
                output_sha256={p.name: sha(p) for p in sorted(temporary.iterdir())},
            ),
        )
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/tohoku-arrival-audit.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.audit, args.config, args.output)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("case_count", "setting_count", "status_counts", "quiet_controls")
            }
        )
    )


if __name__ == "__main__":
    main()
