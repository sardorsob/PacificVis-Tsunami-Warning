"""Frozen raw diagnostic tests use synthetic traces, never arrival labels."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.run_waveform_diagnostics import build, prepare_case, protocol, run_case

ORIGIN = datetime(2011, 3, 11, 6, tzinfo=UTC)
CONFIG = Path(__file__).resolve().parents[1] / "config/tohoku-arrival-audit.toml"


def trace(root: Path, *, units: str = "m", cadence: int = 60, mode: str = "step") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for second in range(-4 * 3600, 30 * 3600, cadence):
        value = 0 if second < 0 or mode == "quiet" else 0.1
        if units == "cm":
            value *= 100
        row = dict(
            timestamp_utc=(ORIGIN + timedelta(seconds=second)).isoformat(),
            timestamp_state="reported_utc",
            raw_timestamp=str(second),
            value_state="finite_numeric",
            numeric_value=str(value),
            units=units,
            vertical_datum="STND",
            duplicate_timestamp="False",
            qc_state="not_provided",
            qc_json="{}",
        )
        rows.append(row)
    path = root / "trace.csv.gz"
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            with io.TextIOWrapper(zipped, newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    return dict(
        case_id="masked-case",
        reference_utc=ORIGIN.isoformat(),
        sources=[
            dict(
                trace_id="trace-01",
                selected_for_chart=True,
                status="normalized_source_samples",
                units=units,
                vertical_datum="STND",
                declared_cadence_seconds=cadence,
                path=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                rows=len(rows),
            )
        ],
    )


def test_existing_grid_has_eight_raw_candidates_and_explicit_unit_conversion(
    tmp_path: Path,
) -> None:
    case = trace(tmp_path, units="cm")
    result = run_case(case, tmp_path, protocol(CONFIG))
    assert len(result["settings"]) == 8
    assert {r["status"] for r in result["settings"]} == {"candidate"}
    assert {r["candidate_utc"] for r in result["settings"]} == {"2011-03-11T06:00:00Z"}
    assert result["preparation"]["conversion_factor_to_m"] == 0.01
    assert result["physical_onset_validated"] is False
    assert result["modeled_arrival_utc"] == "unavailable"


@pytest.mark.parametrize("units,cadence,reason", [("unknown", 60, "units"), ("m", 360, "cadence")])
def test_unsupported_semantics_remain_in_all_eight_settings(
    tmp_path: Path, units: str, cadence: int, reason: str
) -> None:
    case = trace(tmp_path, units=units, cadence=cadence)
    result = run_case(case, tmp_path, protocol(CONFIG))
    assert len(result["settings"]) == 8 and all(
        r["status"] == "unsupported" for r in result["settings"]
    )
    assert any(reason in r for r in result["preparation"]["unsupported_reasons"])


def rewrite(root: Path, case: dict[str, Any], rows: list[dict[str, str]]) -> None:
    path = root / case["sources"][0]["path"]
    with gzip.open(path, "wt", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    case["sources"][0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=len(rows))


def test_duplicate_qc_and_typed_missing_break_samples_without_sentinel_guess(
    tmp_path: Path,
) -> None:
    case = trace(tmp_path)
    with gzip.open(tmp_path / "trace.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    rows[0]["numeric_value"] = "9999"  # No invented sentinel rule.
    rows[1].update(value_state="blank", numeric_value="unknown")
    rows[2].update(qc_state="provided", qc_json='{"f":"0,1"}')
    rows.append(dict(rows[3]))
    rewrite(tmp_path, case, rows)
    samples, report = prepare_case(case, tmp_path)
    assert samples[0].raw == 9999 and samples[1].raw is None
    assert samples[2].qc_bad and samples[3].qc_bad
    assert report["row_exclusions"] == dict(
        typed_missing_value_rows=1, uninterpreted_qc_rows=1, duplicate_timestamp_rows=2
    )


def test_baseline_failures_and_long_gaps_remain_explicit(tmp_path: Path) -> None:
    case = trace(tmp_path, mode="quiet")
    with gzip.open(tmp_path / "trace.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    rewrite(tmp_path, case, [r for r in rows if int(r["raw_timestamp"]) >= 0])
    result = run_case(case, tmp_path, protocol(CONFIG))
    assert {s["status"] for s in result["settings"]} == {"ineligible_baseline"}
    case = trace(tmp_path, mode="quiet")
    with gzip.open(tmp_path / "trace.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    rewrite(tmp_path, case, [r for r in rows if not 60 <= int(r["raw_timestamp"]) < 600])
    result = run_case(case, tmp_path, protocol(CONFIG))
    assert {s["status"] for s in result["settings"]} == {"incomplete_search"}
    assert all(s["search_max_gap_seconds"] == 600 for s in result["settings"])


def audit_package(root: Path) -> Path:
    audit = root / "audit"
    blind = audit / "blind"
    blind.mkdir(parents=True)
    (audit / "private").mkdir()
    case = trace(blind)
    (blind / "catalog.json").write_text(json.dumps({"cases": [case]}))
    sample: dict[str, Any] = dict(
        cases=[
            dict(
                case_id="masked-case",
                key=["event-a", "provider", "site", "sensor", "quiet_control"],
            )
        ]
    )
    sample["sample_sha256"] = hashlib.sha256(
        json.dumps(sample, sort_keys=True).encode()
    ).hexdigest()
    (audit / "private/sample.json").write_text(json.dumps(sample))
    outputs = {
        str(p.relative_to(audit)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in audit.rglob("*")
        if p.is_file()
    }
    (audit / "manifest.json").write_text(
        json.dumps(dict(sample_sha256=sample["sample_sha256"], output_sha256=outputs))
    )
    return audit


def test_frozen_package_replay_and_postfreeze_control_rate(tmp_path: Path) -> None:
    audit = audit_package(tmp_path)
    one, two = tmp_path / "one", tmp_path / "two"
    result = build(audit, CONFIG, one)
    build(audit, CONFIG, two)
    assert (
        result["setting_count"] == 8
        and result["quiet_controls"]["raw_crossing_fraction_all_settings"] == 1
    )
    assert (
        result["case_results_sha256_before_assignment_read"]
        == hashlib.sha256((one / "case-results.json").read_bytes()).hexdigest()
    )
    for path in one.iterdir():
        assert path.read_bytes() == (two / path.name).read_bytes()
    with pytest.raises(FileExistsError):
        build(audit, CONFIG, one)
    (audit / "blind/trace.csv.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        build(audit, CONFIG, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_changed_detector_settings_refused(tmp_path: Path) -> None:
    config = tmp_path / "changed.toml"
    config.write_text(CONFIG.read_text().replace("[0.03, 0.05]", "[0.04, 0.05]"))
    with pytest.raises(ValueError, match="frozen contract"):
        protocol(config)
