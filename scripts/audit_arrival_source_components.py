"""Census native NCEI exploration time fields without changing analysis records."""

# pyright: basic
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json  # noqa: E402
from analysis.arrival.model_data import CONTRACT, load_lanes  # noqa: E402
from analysis.arrival.model_source_components import audit_records  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402

DESIGN = "config/arrival-source-component-audit-v1.toml"


def run(root: Path, output: Path):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local output required")
    design = tomllib.loads((root / DESIGN).read_text())
    if (
        design["schema_version"] != "arrival_native_component_census_v1"
        or design["large_disagreement_minutes"] != 60
    ):
        raise ValueError("unsupported frozen census rule")
    manifest = checked_path(root, design["source_manifest"])
    if sha256(manifest) != design["source_manifest_sha256"]:
        raise ValueError("source manifest hash mismatch before metadata parse")
    lanes, contract = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    rows, pins = audit_records(
        root, list(lane.rows), lane.included.tolist(), read_rows(manifest), set(lane.event_ids), 60
    )
    if len(rows) != 1070 or sum(r["included_primary"] for r in rows) != 1064:
        raise ValueError("frozen census conservation failed")
    pins.update(contract["inputs"])
    for relative in [
        DESIGN,
        CONTRACT,
        design["source_manifest"],
        "analysis/arrival/model_source_components.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/evidence.py",
        "analysis/arrival/model_validation_report.py",
        "scripts/audit_arrival_source_components.py",
    ]:
        pins[relative] = sha256(root / relative)
    summary = []
    event_summary = []
    for cohort in ["all_exploration", "primary"]:
        group = [r for r in rows if cohort == "all_exploration" or r["included_primary"]]
        for event in [None, *sorted({r["event_id"] for r in group})]:
            subset = [r for r in group if event is None or r["event_id"] == event]
            assessed = [r for r in subset if r["assessment"] == "assessed"]
            flagged = [r for r in assessed if r["large_component_disagreement"]]
            result = {
                "cohort": cohort,
                "event_id": event or "all",
                "records": len(subset),
                "assessed": len(assessed),
                "unassessed": len(subset) - len(assessed),
                "flagged": len(flagged),
                "flagged_events": len({r["event_id"] for r in flagged}),
                "flagged_fraction_all": len(flagged) / len(subset),
                "flagged_fraction_assessed": len(flagged) / len(assessed) if assessed else None,
            }
            (summary if event is None else event_summary).append(result)
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "design": design,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "raw_pages": len({r["record_id"].rsplit(":", 1)[0] for r in rows}),
        },
    )
    for name, values in [
        ("native-time-component-records", rows),
        ("cohort-summary", summary),
        ("event-summary", event_summary),
    ]:
        write_table(
            output / f"{name}.csv",
            [{k: ("not_applicable" if v is None else v) for k, v in r.items()} for r in values],
        )
    write_json(
        output / "summary.json",
        {
            "cohorts": summary,
            "unassessed_reasons": dict(
                Counter(r["reason"] for r in rows if r["assessment"] == "unassessed")
            ),
            "selection": "none; original values, eligibility and definition flags unchanged",
        },
    )
    lines = [
        "# Native reported time-component consistency",
        "",
        "This census applies one posthoc rule to every frozen exploration NCEI duration record. "
        "It tests internal agreement of source time-of-day fields and reported duration, "
        "using the pinned NCEI origin rather than the USGS origin. "
        "It does not validate physical arrival accuracy.",
        "",
        "| Cohort | Records | Assessed | Unassessed | Flagged above 60 min |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in summary:
        lines.append(
            f"| {r['cohort']} | {r['records']} | {r['assessed']} | "
            f"{r['unassessed']} | {r['flagged']} |"
        )
    lines += [
        "",
        "The signed residual is ((arrival time of day − source time of day − reported duration "
        "+ 720) mod 1440) − 720 minutes, in [−720,720). Arrival day is checked for range only; "
        "no arrival month, year or absolute date is inferred. Explicit complete valid components "
        "are required. Missing components remain unassessed.",
        "",
        "The 60-minute threshold is a posthoc triage choice, not an accuracy tolerance or rounding "
        "assumption. Small residuals can hide whole-day discrepancies, compensating errors or "
        "incorrect event association. Flags identify cases for sensitivity analysis and source "
        "clarification; they establish neither cause nor corrected values.",
        "",
        "The rule was recorded after the influential LATA 1,125-minute case was traced. The "
        "census retains all original values and all six rows already excluded from the primary "
        "model view in their original roles. No missing forecast/observation pair is recovered.",
        "",
        "Raw page hashes and all event/request metadata are checked before any selected raw JSON "
        "is parsed. Only pages belonging to frozen exploration events are read. Native item IDs "
        "are bound by immutable page hash and frozen one-based item position; the exploration "
        "table contains no independent native item-ID column. The 19 previously inspected "
        "confirmation outcomes and 18 reserved outcomes are not parsed.",
        "",
        "Source: NOAA/NCEI historical tsunami catalog, retained HaZEL runup responses. "
        "[Field definitions](https://data.noaa.gov/metaview/page?view=xml2text/xml-to-text-ISO&xml=NOAA/NESDIS/NGDC/MGG/Hazards/iso/xml/G02151.xml).",
        "",
        "Reproduce: `uv run --locked --offline python scripts/audit_arrival_source_components.py "
        "--output <new-project-path>`. Exact inputs accompany this census.",
    ]
    (output / "findings.md").write_text("\n".join(lines) + "\n")
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run(project, (project / args.output).resolve())
