"""Inspectable evidence artifacts for the preliminary visual-story atlas."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast
from xml.etree import ElementTree

from analysis.story.atlas import AtlasError
from analysis.story.plots import PlotFiles

Disposition = Literal["retain", "revise", "branch", "promote", "reject"]

PLOT_IDS = (
    "01_pacific_evidence_map",
    "02_observation_coverage",
    "03_station_timeseries",
    "04_distance_contour_diagnostic",
)

_PLOT_DETAILS = {
    "01_pacific_evidence_map": {
        "title": "Pacific evidence map",
        "question": "Is the event and candidate observational chain legible at basin scale?",
        "limitation": "Published hourly contours are not a continuous NCTR field.",
        "time_basis": "not applicable",
        "longitude_handling": "source coordinates preserved; linework split at 20E/-340",
    },
    "02_observation_coverage": {
        "title": "Observation coverage",
        "question": "Where do distinct availability mechanisms affect the coastal chain?",
        "limitation": "Coverage does not establish the upstream cause of missingness.",
        "time_basis": "source-supported UTC windows; off-grid timestamps unsnapped",
        "longitude_handling": "not applicable",
    },
    "03_station_timeseries": {
        "title": "Station time series",
        "question": "Are retained station signals inspectable without hiding gaps or datums?",
        "limitation": (
            "Local y-scales and incompatible vertical references prevent amplitude comparison."
        ),
        "time_basis": "verified UTC expressed as hours from earthquake origin",
        "longitude_handling": "not applicable",
    },
    "04_distance_contour_diagnostic": {
        "title": "Distance versus published contour shape",
        "question": "How does geodesic range shape differ from published travel-time contours?",
        "limitation": "Kilometres and hours are not converted; no station arrival is assigned.",
        "time_basis": "published contour hours from earthquake origin",
        "longitude_handling": "source coordinates preserved; linework split at 20E/-340",
    },
}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One explicit adaptive decision for a required Stage A view."""

    plot_id: str
    observation: str
    question: str
    follow_up: str
    result: str
    disposition: Disposition
    storyboard_implication: str
    manual_qa: str


def validate_story_output_path(path: Path) -> None:
    """Reject story evidence written into submission or application-owned locations."""
    normalized = f"/{path.as_posix().strip('/')}/"
    if any(
        p in normalized
        for p in ("/analysis/paper/", "/artifacts/eda/paper/", "/artifacts/eda/arrival-timing/")
    ):
        raise AtlasError(f"paper path is forbidden in story evidence: {normalized}")
    if "/app/public/data/" in normalized:
        raise AtlasError(f"exploratory output cannot be an app asset: {normalized}")


def sha256_file(path: Path) -> str:
    """Hash a file without loading large normalized tables into memory."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AtlasError(f"could not hash input {path}: {error}") from error
    return digest.hexdigest()


def display_path(path: Path) -> str:
    """Prefer a repository-relative display path when one exists."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def write_json(path: Path, value: object) -> None:
    """Write stable human-readable JSON."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _required_text(document: dict[str, object], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AtlasError(f"decision input {field} must be nonblank text")
    return value


def load_decision_input(path: Path) -> tuple[DecisionRecord, ...]:
    """Load a complete reviewed Stage A decision input without mutating its prose."""
    try:
        document = cast(dict[str, object], tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AtlasError(f"could not read decision input {path}: {error}") from error
    if document.get("schema_version") != "1":
        raise AtlasError("decision input schema_version must be '1'")
    if document.get("evidence_state") != "preliminary_storyboard_evidence":
        raise AtlasError("decision input evidence_state is not preliminary_storyboard_evidence")
    _required_text(document, "reviewer")
    review_date = _required_text(document, "review_date")
    try:
        date.fromisoformat(review_date)
    except ValueError as error:
        raise AtlasError("decision input review_date must be ISO YYYY-MM-DD") from error
    raw_decisions = document.get("decisions")
    if not isinstance(raw_decisions, list):
        raise AtlasError("decision input requires [[decisions]] rows")
    decisions: list[DecisionRecord] = []
    allowed = {"retain", "revise", "branch", "reject"}
    fields = (
        "plot_id",
        "observation",
        "question",
        "follow_up",
        "result",
        "disposition",
        "storyboard_implication",
        "manual_qa",
    )
    for raw_decision in cast(list[object], raw_decisions):
        if not isinstance(raw_decision, dict):
            raise AtlasError("each decision input row must be an object")
        decision = cast(dict[str, object], raw_decision)
        values = {field: _required_text(decision, field) for field in fields}
        disposition = values["disposition"]
        if disposition not in allowed:
            raise AtlasError("Stage A disposition must be retain, revise, branch, or reject")
        decisions.append(
            DecisionRecord(
                plot_id=values["plot_id"],
                observation=values["observation"],
                question=values["question"],
                follow_up=values["follow_up"],
                result=values["result"],
                disposition=cast(Disposition, disposition),
                storyboard_implication=values["storyboard_implication"],
                manual_qa=values["manual_qa"],
            )
        )
    if tuple(decision.plot_id for decision in decisions) != PLOT_IDS:
        raise AtlasError("decision input must contain each atlas plot once in atlas order")
    return tuple(decisions)


def preview_decisions(metrics: dict[str, int | float]) -> tuple[DecisionRecord, ...]:
    """Create factual, non-promoting rows for an unreviewed preview run."""
    results = (
        (
            f"Mapped {metrics['station_count']:.0f} candidate stations and "
            f"{metrics['contour_count']:.0f} published contour parts.",
            "Inspect label collisions and Pacific seam behavior.",
        ),
        (
            f"Represented {metrics['coverage_grid_positions']:.0f} exact-grid positions and "
            f"{metrics['coverage_off_grid']:.0f} separate off-grid observations.",
            "Inspect missingness luminance and the weakest metric-derived stations.",
        ),
        (
            f"Displayed {metrics['series_point_count']:.0f} numeric points on "
            "station-local scales.",
            "Inspect density, gaps, and datum labels without comparing amplitudes.",
        ),
        (
            f"Compared {metrics['range_radius_count']:.0f} geodesic radii with "
            f"{metrics['highlighted_contour_hour_count']:.0f} published hour classes.",
            "Inspect shape differences only; do not infer arrivals or speed.",
        ),
    )
    return tuple(
        DecisionRecord(
            plot_id=plot_id,
            observation=result,
            question=_PLOT_DETAILS[plot_id]["question"],
            follow_up=follow_up,
            result=result,
            disposition="retain",
            storyboard_implication="Await manual atlas review; no storyboard promotion.",
            manual_qa="Pending manual atlas review.",
        )
        for plot_id, (result, follow_up) in zip(PLOT_IDS, results, strict=True)
    )


def write_decision_ledger(path: Path, decisions: tuple[DecisionRecord, ...]) -> None:
    """Write the adaptive decision chain in deterministic atlas order."""
    validate_story_output_path(path)
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=list(asdict(decisions[0]).keys()),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(asdict(decision) for decision in decisions)


def _png_dimensions(path: Path) -> dict[str, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AtlasError(f"generated file is not a valid PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    return {"height_px": height, "width_px": width}


def _svg_dimensions(path: Path) -> dict[str, str]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise AtlasError(f"generated file is not valid SVG: {path}") from error
    view_box = root.attrib.get("viewBox")
    if not view_box:
        raise AtlasError(f"generated SVG lacks viewBox: {path}")
    return {"view_box": view_box}


def write_atlas_manifest(
    path: Path,
    *,
    plots: tuple[PlotFiles, ...],
    decisions: tuple[DecisionRecord, ...],
    run_id: str,
    command: str,
    git_sha: str,
    candidate_build_id: str,
    input_records: list[dict[str, str]],
    evidence_state: str,
    rejection_count: int,
    published_artifact_dir: Path,
) -> None:
    """Write complete per-file lineage for each generated diagnostic."""
    validate_story_output_path(path)
    decision_by_plot = {decision.plot_id: decision for decision in decisions}
    if tuple(plot.plot_id for plot in plots) != PLOT_IDS:
        raise AtlasError("manifest plots must match the fixed atlas order")
    artifacts: list[dict[str, object]] = []
    for plot in plots:
        detail = _PLOT_DETAILS[plot.plot_id]
        decision = decision_by_plot[plot.plot_id]
        for media_type, source_path in (("image/png", plot.png), ("image/svg+xml", plot.svg)):
            suffix = "png" if media_type == "image/png" else "svg"
            published_path = published_artifact_dir / f"{plot.plot_id}.{suffix}"
            validate_story_output_path(published_path)
            artifacts.append(
                {
                    "artifact_id": f"{plot.plot_id}_{suffix}",
                    "title": detail["title"],
                    "question": detail["question"],
                    "lane": "story",
                    "generating_command": command,
                    "git_sha": git_sha,
                    "candidate_build_id": candidate_build_id,
                    "input_checksums": input_records,
                    "projection": plot.projection,
                    "time_basis": detail["time_basis"],
                    "units": plot.units,
                    "longitude_handling": detail["longitude_handling"],
                    "input_count": plot.input_parts,
                    "output_count": plot.output_parts,
                    "rejection_count": rejection_count,
                    "path": display_path(published_path),
                    "media_type": media_type,
                    "dimensions": (
                        _png_dimensions(source_path)
                        if media_type == "image/png"
                        else _svg_dimensions(source_path)
                    ),
                    "sha256": sha256_file(source_path),
                    "evidence_state": evidence_state,
                    "finding": decision.result,
                    "limitation": detail["limitation"],
                    "disposition": decision.disposition,
                    "storyboard_implication": decision.storyboard_implication,
                    "manual_qa": decision.manual_qa,
                }
            )
    write_json(
        path,
        {
            "schema_version": "1",
            "run_id": run_id,
            "lane": "story",
            "evidence_state": evidence_state,
            "artifacts": artifacts,
        },
    )


def render_story_report(
    *,
    run_id: str,
    git_sha: str,
    command: str,
    candidate_build_id: str,
    decisions: tuple[DecisionRecord, ...],
    metrics: dict[str, int | float],
    input_records: list[dict[str, str]],
    output_records: list[dict[str, str]],
    reviewed: bool,
) -> str:
    """Render the canonical Stage A report with the required section order."""
    decision_lines = "\n".join(
        f"- **{decision.plot_id} — {decision.disposition}:** {decision.observation} "
        f"Question: {decision.question} Follow-up: {decision.follow_up} Result: "
        f"{decision.result} Storyboard: {decision.storyboard_implication} Manual QA: "
        f"{decision.manual_qa}"
        for decision in decisions
    )
    input_lines = "\n".join(
        f"| `{Path(record['path']).name}` | `{record['sha256']}` |" for record in input_records
    )
    output_lines = "\n".join(
        f"| `{Path(record['path']).name}` | `{record['sha256']}` |" for record in output_records
    )
    if reviewed:
        interpretation = """These views test geography, observability, source-preserving
signals, and shape. They do not test an arrival-time claim. The recorded
dispositions are Maker review inputs: `retain` keeps a diagnostic visible,
while `branch` records a new question without promoting a scene or selecting
stations from its result."""
        takeaways = """The manual review branches the crowded basin context toward a
regional view and the coverage finding toward an observability-first candidate.
It retains the signal and non-radial shape diagnostics as preliminary evidence.
No scene, station, waveform, or arrival claim is promoted."""
        next_steps = """Hand this preliminary atlas to the independent Checker for scientific and
cartographic review. Keep T-003A in review, carry the regional-context and
observability branches as separately reviewed work, and do not begin
arrival-based Stage B before T-002E."""
    else:
        interpretation = """These views test geography, observability, source-preserving
signals, and shape. They do not test an arrival-time claim. A `retain` preview
disposition means only that the required diagnostic remains visible for review."""
        takeaways = """The fixed atlas can now be rebuilt and reviewed as one evidence
unit. Negative or weak findings remain eligible for `revise`, `branch`, or
`reject` decisions."""
        next_steps = """Inspect all four figures at full and thumbnail size, in grayscale and common
color-vision simulations; trace three displayed values; then record the observed
review in the decision input. Do not begin arrival-based Stage B before T-002E."""
    return f"""# Visual-Story EDA Report

## Run and evidence state

- Run ID: `{run_id}`
- Git SHA: `{git_sha}`
- Command: `{command}`
- Evidence state: `preliminary_storyboard_evidence`
- Candidate build: `{candidate_build_id}`

This is story-lane diagnostic evidence. No story claim has been promoted.

## Inputs and source boundary

The atlas consumes one explicit accepted candidate build, the shared missingness
contract and summary, and the separately governed coastline. The continuous NCTR
field is unavailable; published NCEI hourly contours are not a substitute for a
continuous field.

## Fixed diagnostic atlas

- Pacific evidence map: {metrics["station_count"]:.0f} candidate stations and
  {metrics["contour_count"]:.0f} published contour parts.
- Observation coverage: {metrics["coverage_grid_positions"]:.0f} exact-grid
  positions and {metrics["coverage_off_grid"]:.0f} unsnapped off-grid samples.
- Station time series: {metrics["series_point_count"]:.0f} retained numeric
  points. Panels use local scales; amplitudes are not comparable.
- Distance/contour diagnostic: {metrics["range_radius_count"]:.0f} WGS84 distance
  rings and {metrics["highlighted_contour_hour_count"]:.0f} published hour
  classes. The two sides compare shape in different units; no speed conversion
  or station arrival assignment is made.

## Adaptive decision ledger

{decision_lines}

## Interpretation

{interpretation}

## Limitations

No arrival pick, modeled-versus-observed arrival residual comparison, station
promotion, or story claim occurred. Unknown horizontal and vertical datums remain
explicit. Coastal raw levels and DART residual signals are separate quantities.

## Takeaways

{takeaways}

## Next steps

{next_steps}

## Input and output fingerprints

### Inputs

| File | SHA-256 |
| --- | --- |
{input_lines}

### Generated atlas evidence

| File | SHA-256 |
| --- | --- |
{output_lines}
"""
