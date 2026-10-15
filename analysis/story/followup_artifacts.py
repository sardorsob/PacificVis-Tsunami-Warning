"""Table-derived findings, figure lineage and portable follow-up run evidence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from analysis.story.artifacts import (
    _png_dimensions,  # pyright: ignore[reportPrivateUsage]
    _svg_dimensions,  # pyright: ignore[reportPrivateUsage]
    sha256_file,
    validate_story_output_path,
)
from pipeline.eda_report import write_csv, write_json

FIGURES = {
    "01_regional_context": (
        ["station-reference", "label-audit"],
        "All ten stations remain visible at basin scale; "
        "regional zooms clarify Japan and California.",
        "Source lon/lat degrees; projected metres; unknown horizontal station datums",
    ),
    "02_coverage_common_day": (
        ["coverage-by-window", "coverage-spans", "off-grid"],
        "Six coastal gauges share 1,440 original minute positions on 11 March 2011 UTC.",
        "Exact-grid valid raw samples / expected positions; UTC",
    ),
    "03_coverage_mechanisms": (
        ["coverage-by-window", "gap-blocks"],
        "Source blanks, absent timestamps and off-grid samples have different counting semantics.",
        "Grid positions and coverage percent; UTC",
    ),
    "04_gap_details": (
        ["gap-blocks", "coverage-spans"],
        "Saipan has a long internal gap; Pago Pago also has an absent trailing archive segment.",
        "UTC positions; unequal full requested windows, not a like-for-like rank",
    ),
    "05_signal_support_matrix": (
        ["signal-support", "setting-reference"],
        "Mechanical screens do not validate physical onsets; all failed settings remain.",
        "Counts of 8 settings per station per event/control window; raw versus residual",
    ),
    "06_early_crossing_context": (
        ["signal-windows", "source-references", "setting-reference"],
        "DART 21418 early unclassified threshold crossings "
        "conflict with an approximate NOAA account.",
        "Publisher residual m water column; minutes after origin; vertical datum unknown",
    ),
    "07_control_and_qc_context": (
        ["signal-windows", "source-qc-reference", "setting-reference"],
        "Adak has pre-origin crossings; Valparaíso source flags and raw zero are retained.",
        "Raw water level m; separate STND/unknown datums; hours relative to origin",
    ),
    "08_contour_geometry": (
        ["contour-parts", "contour-distance-envelopes"],
        "Published hour classes span overlapping ranges of source-vertex distances, "
        "not arrival predictions.",
        "Published hours; WGS84 geodesic kilometres to stored vertices, not confidence intervals",
    ),
}


def write_followup_bundle(
    results: dict[str, Any], output: Path, run_id: str, git_sha: str
) -> dict[str, Any]:
    """Synthesize already computed references, preserving negative/blocked claims."""
    tables = results["tables"]
    common = [r for r in tables["coverage-by-window"] if r["window_id"] == "common_day"]
    full = [r for r in tables["coverage-by-window"] if r["window_id"] == "source_full"]

    def rank(rows: list[dict[str, Any]]) -> str:
        return ", ".join(
            r["name"] for r in sorted(rows, key=lambda r: (-r["strict_percent"], r["station_id"]))
        )

    saip = next(r for r in common if r["station_id"] == "saip")
    pago = [
        r
        for r in tables["gap-blocks"]
        if r["station_id"] == "1770000"
        and r["window_id"] == "source_full"
        and r["classification"] == "trailing"
    ]
    settings = tables["setting-reference"]
    dart = [
        r["candidate_elapsed_seconds"] / 60
        for r in settings
        if r["station_id"] == "21418" and r["window"] == "event" and r["status"] == "candidate"
    ]
    adak = next(r for r in tables["signal-support"] if r["station_id"] == "9461380")
    saip_signal = next(r for r in tables["signal-support"] if r["station_id"] == "saip")
    envelopes = tables.get("contour-distance-envelopes", [])
    facts = [
        (
            "F-07",
            "regional context",
            f"All {len(tables['station-reference'])} stations remain; "
            f"required label overlaps: {sum(r['overlap_count'] for r in tables['label-audit'])}.",
            "station-reference.csv;label-audit.csv",
            "retain",
            "Regions are zooms, not cohort exclusions; coarse coastline and unknown datums remain.",
        ),
        (
            "F-08",
            "comparable coverage",
            f"Common-day strict rank: {rank(common)}. Full-requested-window rank: {rank(full)}.",
            "coverage-by-window.csv",
            "retain",
            "Window duration affects support. Six fixed gauges are not a population sample.",
        ),
        (
            "F-09",
            "missing support",
            f"Saipan strict {saip['strict_percent']:.4f}% versus density "
            f"{saip['sample_density_percent']:.4f}%; {saip['off_grid_n']} off-grid samples. "
            f"Pago Pago trailing absent positions: {sum(r['absent_n'] for r in pago)}.",
            "gap-blocks.csv;off-grid.csv;coverage-by-window.csv",
            "retain",
            "A missing grid timestamp need not mean no raw sample. Causal missingness is unknown.",
        ),
        (
            "F-10",
            "signal validity",
            f"{len(settings)} frozen settings; DART21418 candidates "
            f"{min(dart):.3f}–{max(dart):.3f}min versus approximately25min source account. "
            f"Adak controls {adak['control_crossings']}/{adak['total_settings']}; "
            f"{len(tables['source-qc-reference'])} flagged Valparaíso rows retained. "
            f"Saipan event runs: {saip_signal['event_unevaluable']} unevaluable "
            f"({saip_signal['event_baseline_ineligible']} baseline failures), "
            f"{saip_signal['event_no_detection']} evaluable no-detection outcomes.",
            "signal-support.csv;setting-reference.csv;source-qc-reference.csv;source-references.csv",
            "retain",
            "Early signal unclassified; raw tides and retrospective residuals "
            "are not physical arrival picks.",
        ),
    ]
    if envelopes:
        last = envelopes[-1]
        facts.append(
            (
                "F-11",
                "contour geometry",
                f"{sum(r['part_n'] for r in envelopes)} parts, "
                f"{sum(r['vertex_n'] for r in envelopes):,} stored vertices "
                f"across {len(envelopes)} classes. "
                f"{last['published_hours']:g}h range: {last['min_distance_km']:.3f}–"
                f"{last['max_distance_km']:.3f}km.",
                "contour-parts.csv;contour-distance-envelopes.csv",
                "retain-secondary",
                "Stored-vertex extrema are not probabilities, continuous-front bounds "
                "or station arrivals.",
            )
        )
    findings = [
        dict(
            finding_id=fid,
            question=question,
            result=result,
            references=refs,
            decision=decision,
            limitation=limitation,
        )
        for fid, question, result, refs, decision, limitation in facts
    ]
    questions = [
        dict(
            question="What can each archive actually show over the same day?",
            supporting_findings="F-07;F-08;F-09",
            contradicting_findings="unknown",
            permitted_claim="Coverage differs with window and timestamp definition.",
            blocked_claim="Instrumentation cause or formal MCAR/MAR/MNAR classification.",
            recommendation="retain; propose observability-first story to owner; no pivot approved",
        ),
        dict(
            question="Does a stable crossing establish a tsunami arrival?",
            supporting_findings="F-10",
            contradicting_findings="F-10 (mechanical pass vs source conflict)",
            permitted_claim="Mechanical stability and external validation disagree.",
            blocked_claim="Exact physical onset, warning time or modeled arrival error.",
            recommendation="retain as interpretation guardrail; no retuning",
        ),
        dict(
            question="Do published hour lines behave like distance rings?",
            supporting_findings="F-11" if envelopes else "unknown",
            contradicting_findings="unknown",
            permitted_claim="Stored vertices span distance ranges."
            if envelopes
            else "not evaluated",
            blocked_claim="Bathymetry caused the shape or inferred station arrival.",
            recommendation="retain secondary; stop geometry"
            if envelopes
            else "optional check omitted",
        ),
    ]
    tables.update(findings=findings, **{"story-question-evidence": questions})
    for name in ("findings", "story-question-evidence"):
        write_csv(output / f"{name}.csv", tables[name])
    metric_values = {
        "stations": len(tables["station-reference"]),
        "coastal_gauges": len(common),
        "frozen_settings": len(settings),
        "source_qc_flagged": len(tables["source-qc-reference"]),
        "mechanical_screen_passes": sum(
            r["mechanical_screen_pass"] for r in tables["signal-support"]
        ),
        "arrival_comparison_allowed": 0,
        **{f"strict_common_day_{r['station_id']}": r["strict_percent"] for r in common},
    }
    results["run_metrics"] = metric_values
    write_json(output / "metrics.json", metric_values)
    artifacts: list[dict[str, Any]] = []
    for stem, (names, caption, units) in FIGURES.items():
        if not (output / f"{stem}.png").exists():
            continue
        references = [
            {
                "path": f"{name}.csv",
                "sha256": sha256_file(output / f"{name}.csv"),
                "row_n": len(tables[name]),
            }
            for name in names
        ]
        for extension in ("png", "svg"):
            path = output / f"{stem}.{extension}"
            artifacts.append(
                dict(
                    artifact_id=f"{stem}_{extension}",
                    path=path.name,
                    sha256=sha256_file(path),
                    references=references,
                    caption=caption,
                    alt_text=caption,
                    units=units,
                    projection=results["settings"]["display_crs"]
                    if stem.startswith("01_")
                    else "not applicable",
                    event_id=results["settings"]["event_id"],
                    origin_utc="2011-03-11T05:46:24.120Z",
                    sources="Accepted NOAA/NCEI, CO-OPS, IOC, USGS; "
                    "Natural Earth 4.1.0 for coastline",
                    source_date="accepted shared audit 2026-10-05; "
                    "exact retrievals in fingerprinted source manifest",
                    transformations="source-grid slicing; source metadata retained; "
                    "no interpolation or onset promotion",
                    input_counts=results["counts"],
                    output_count=1,
                    dimensions=_png_dimensions(path)
                    if extension == "png"
                    else _svg_dimensions(path),
                    generating_command=results["command"],
                    git_sha=git_sha,
                    evidence_state=results["evidence_state"],
                )
            )
    manifest = dict(
        run_id=run_id,
        git_sha=git_sha,
        lane="story",
        arrival_comparison_allowed=False,
        input_checksums=results["input_fingerprints"],
        artifacts=artifacts,
        optional_geometry="executed" if envelopes else "not executed; no dummy figure",
        output_manifest_semantics="outputs.json hashes all files except itself",
    )
    write_json(output / "manifest.json", manifest)
    coverage_lines = "\n".join(
        f"| {r['name']} [{r['station_id']}] | {r['exact_valid_n']}/{r['expected_n']} | "
        f"{r['strict_percent']:.4f}% | {r['sample_density_percent']:.4f}% | {r['off_grid_n']} |"
        for r in common
    )
    finding_text = "\n\n".join(
        f"### {r['finding_id']} — {r['question']}\n\n{r['result']}\n\n"
        f"References: {r['references']}. Decision: {r['decision']}. {r['limitation']}"
        for r in findings
    )
    images = "\n\n".join(
        f"![{caption}]({stem}.png)\n\n{caption} References: "
        + ", ".join(f"[{name}.csv]({name}.csv)" for name in names)
        for stem, (names, caption, _) in FIGURES.items()
        if (output / f"{stem}.png").exists()
    )
    report = f"""# Visual-story follow-up evidence

Run `{run_id}` · implementation `{git_sha}` · preliminary storyboard evidence.

Command: `{results["command"]}`

## Scope and source boundary

One 2011 Tōhoku event, ten fixed stations, six coastal gauges. Origin:
2011-03-11T05:46:24.120Z (USGS). All selected source bytes were checked before
analysis. The continuous NCTR field is still unavailable; published NCEI hour
contours are not a replacement. This is retrospective, descriptive story work,
separate from paper modeling. No app assets, public scenes or arrival claims.

## Comparable coastal coverage

11 March 2011 [00:00,24:00) UTC; 1,440 original source-minute positions each.
Valid means numeric raw value present, not quality-approved. Blank is not zero.
Density counts valid off-grid samples but caps at the same denominator; they do
not repair the grid. Event-relative windows slice that original phase, never
re-anchor it to the fractional earthquake timestamp. Full windows are separate.

| Gauge | Exact valid / expected | Strict | Sample density | Off-grid n |
| --- | --- | --- | --- | --- |
{coverage_lines}

## Findings and thoughts

{finding_text}

## Interpretation and limitations

Observability has the clearest current support for a visual story: archive
window and timestamp semantics change what a reader can see. It does not show
why measurements are absent. MCAR, MAR and MNAR cannot be identified from these
patterns alone; no instrumentation-age or collection-error cause is invented.
Acquisition failures, source blanks, missing timestamps, parser rejects and QC
are distinct. Accepted source bytes and earlier accounting remain available via
inputs.json; {results["counts"]["previously_rejected_records"]} previously rejected
records remain excluded, not repaired.

Signal interpretation is a useful guardrail, not a new timing result. The
early DART signal is unclassified; the NCTR account is approximate, not an exact
25-minute timestamp. Adak control UTC values are plotted relative to origin,
not their control-search elapsed field. Raw coastal tidal levels and publisher
retrospective residuals (fit window unknown) are not comparable onset fields.
Source flags are retained for inspection, not an invented exclusion algorithm.
Unknown datums stay unknown. No amplitude comparison across incompatible datums.

Geometry is secondary: fragmented stored parts, nonuniform sampling and unknown
continuous-front behavior limit interpretation. Geodesic extrema use WGS84 and
original source vertices, including tiny longitude boundary roundoff; they are
not probabilities or confidence intervals. No bathymetry was acquired or inferred.

## Decisions and next smallest questions

See story-question-evidence.csv for supporting/contradicting evidence and blocked
claims. Propose observability-first framing to the owner; no story pivot is
approved here. Retain signal limitations; stop contour analysis after this check.
At most two subsequent checks: (1) test a plain-language explanation of strict
versus density coverage (F-08/F-09); (2) test whether readers distinguish a
threshold crossing from a validated arrival (F-10). No further analysis is run.

Arrival comparison permission remains **false**; arrival-based story work is blocked.
These are analytical figures, not mobile-ready story components. At 400px,
check the thumbnail message only; detailed labels require the analytical view.

## Figures and reference tables

{images}

## Reproducibility

manifest.json records figure hashes, CSV references, dimensions, units, origin,
sources, projection, counts, command and implementation SHA. inputs.json hashes
the accepted evidence; outputs.json hashes all stable files except itself.
No randomness is used. Local MLflow recording is paired with a portable run
bundle; tracking receipt IDs are intentionally outside stable scientific files.
Independent QA and owner story selection are separate from this evidence bundle.
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    return manifest


def validate_run_paths(output: Path, run_dir: Path) -> None:
    """Portable logs must never add files to or pre-create a scientific bundle."""
    output, run_dir = output.resolve(), run_dir.resolve()
    validate_story_output_path(run_dir)
    if output.is_relative_to(run_dir) or run_dir.is_relative_to(output):
        raise ValueError("artifact and run directories must be disjoint, not nested")


def record_followup_run(results: dict[str, Any], output: Path, run_dir: Path) -> None:
    """Keep a portable run even if optional local tracking is unavailable."""
    validate_run_paths(output, run_dir)
    if run_dir.exists():
        raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True)
    for name, value in (
        (
            "config",
            {
                "settings": results["settings"],
                "tasks": results["tasks"],
                "command": results["command"],
                "git_sha": results["git_sha"],
                "randomness": "none",
            },
        ),
        ("inputs", results["input_fingerprints"]),
        ("metrics", results["run_metrics"]),
        ("outputs", [{"path": p.name, "sha256": sha256_file(p)} for p in sorted(output.iterdir())]),
    ):
        write_json(run_dir / f"{name}.json", value)
    (run_dir / "notes.md").write_text(
        (output / "report.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    import mlflow

    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "true")
    root = Path(__file__).resolve().parents[2]
    mlflow.set_tracking_uri((root / ".mlflow").resolve().as_uri())
    mlflow.set_experiment("story-followup-eda")  # pyright: ignore[reportUnknownMemberType]
    with mlflow.start_run(
        run_name=results["run_id"],
        tags={
            "git_sha": results["git_sha"],
            "lane": "story",
            "portable_run_id": results["run_id"],
            "evidence_state": results["evidence_state"],
            "input_manifest_sha256": sha256_file(output / "inputs.json"),
            "selection": "propose observability; retain signal guardrail; "
            "stop geometry; no pivot approved",
        },
    ) as active:
        mlflow.log_params(
            {
                "tasks": ",".join(results["tasks"]),
                "randomness": "none",
                "config_sha256": sha256_file(run_dir / "config.json"),
            }
        )
        mlflow.log_metrics({k: float(v) for k, v in results["run_metrics"].items()})
        mlflow.log_artifacts(str(output), artifact_path="scientific-bundle")
        mlflow.log_artifacts(str(run_dir), artifact_path="portable-run")
        write_json(
            run_dir / "tracking.json",
            {
                "status": "recorded",
                "run_id": active.info.run_id,
                "tracking_uri": "project-local .mlflow",
                "scientific_outputs_immutable": True,
            },
        )
