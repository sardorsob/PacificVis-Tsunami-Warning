"""Descriptive paths for the frozen arrival-timing EDA and its producer scripts."""

from __future__ import annotations

import os
import re
from pathlib import Path

EDA_ROOT = Path("artifacts/eda/arrival-timing")
RESULTS = EDA_ROOT / "results"
FROZEN = EDA_ROOT / "frozen-inputs"
SETTINGS = Path("config/arrival-timing-eda-settings.toml")
SPLIT = Path("config/arrival-timing-exploration-confirmation-split.toml")
LOCK = EDA_ROOT / "frozen-confirmation-definition.json"
CODE_FILES = (
    "analysis/arrival/timing_data_and_descriptive_statistics.py",
    "analysis/arrival/timing_diagnostic_plots.py",
    "scripts/run_arrival_timing_eda.py",
    "analysis/arrival/timing_artifact_names.py",
    "analysis/arrival/timing_group_reporting_and_support_diagnostics.py",
    "analysis/arrival/timing_followup_diagnostics.py",
    "analysis/arrival/evidence.py",
    "analysis/arrival/observations.py",
    "analysis/arrival/site_registry.py",
)

SOURCE_RENAMES = {
    "analysis/arrival/eda.py": "analysis/arrival/timing_data_and_descriptive_statistics.py",
    "analysis/arrival/eda_diagnostics.py": (
        "analysis/arrival/timing_group_reporting_and_support_diagnostics.py"
    ),
    "analysis/arrival/eda_branches.py": "analysis/arrival/timing_followup_diagnostics.py",
    "analysis/arrival/eda_plots.py": "analysis/arrival/timing_diagnostic_plots.py",
    "scripts/run_paper_eda.py": "scripts/run_arrival_timing_eda.py",
    "scripts/freeze_paper_eda.py": "scripts/freeze_arrival_timing_eda_inputs.py",
    "scripts/lock_paper_eda.py": "scripts/lock_arrival_timing_eda_confirmation.py",
    "scripts/report_paper_eda.py": "scripts/build_arrival_timing_eda_report.py",
    "scripts/register_paper_eda.py": "scripts/register_arrival_timing_eda_runs.py",
    "tests/test_paper_eda.py": "tests/test_arrival_timing_statistics.py",
    "tests/test_paper_eda_diagnostics.py": (
        "tests/test_arrival_timing_group_reporting_diagnostics.py"
    ),
    "tests/test_paper_eda_branches.py": "tests/test_arrival_timing_followup_diagnostics.py",
    "tests/test_paper_eda_lock.py": "tests/test_arrival_timing_confirmation_guards.py",
    "tests/test_paper_eda_report.py": "tests/test_arrival_timing_report_dispositions.py",
}


TOPICS = {
    "C1": "data-integrity-and-response-records",
    "C2": "travel-duration-distributions-and-clock-precision",
    "C3": "distance-and-fixed-depth-travel-time-reference",
    "C4": "event-and-station-timing-variation",
    "C5": "source-definitions-and-arrival-comparability",
    "C6": "observed-timestamp-availability",
    "C7": "event-concentration-and-deletion-influence",
    "C8": "estimated-minus-observed-timing-distributions",
    "C9": "repeated-station-and-holdout-support",
    "B1": "distance-trend-and-near-field-checks",
    "B2": "extreme-timing-departures-and-source-review",
    "B3": "station-effect-stability",
    "B4": "event-effects-and-earthquake-covariates",
    "B5": "distance-and-precision-dependent-spread",
    "B6": "within-event-source-and-gauge-family-contrasts",
    "B7": "reporting-era-format-and-peak-availability",
    "B8": "event-deletion-sensitivity",
    "B9": "near-field-and-reference-origin-sensitivity",
    "B10": "within-event-timing-difference-distance-associations",
    "B11": "cross-source-common-arrival-identifiability",
}

DOCUMENTS = {
    "config.json": "analysis-settings.json",
    "inputs.json": "generation-input-and-code-checksums.json",
    "outputs.json": "output-file-checksums.json",
    "meta.json": "original-run-metadata.json",
    "metrics.json": "analysis-metrics.json",
    "summary.json": "descriptive-statistics.json",
    "seeds.json": "random-seeds.json",
    "notes.md": "interpretation-and-limitations.md",
    "report.md": "detailed-findings.md",
}


def question_directory(base: Path, split: str, question: str) -> Path:
    """Locate a question by scientific subject, retaining its internal registry ID."""
    return base / split / TOPICS[question]


def artifact_filename(name: str) -> str:
    """Name a plot/table by outcome, statistic and grouping rather than a check ID."""
    if name in DOCUMENTS:
        return DOCUMENTS[name]
    path = Path(name)
    stem, suffix = path.stem, path.suffix
    match = re.fullmatch(r"(B\d+)-screen", stem)
    if match:
        return TOPICS[match[1]] + "-diagnostic-summary" + suffix
    exact = {
        "linked-differences": "reviewed-cross-source-geographic-match-duration-differences",
        "linked-geographic-comparisons": "reviewed-cross-source-geographic-comparison-records",
        "posthoc-P1-differences": "unapproved-same-name-2km-duration-differences",
        "posthoc-P1-colocation-comparisons": "unapproved-same-name-2km-comparison-records",
        "documentary-origin-comparison": "documentary-versus-reviewed-earthquake-origin-times",
        "within-event-peak-presence": "within-event-peak-presence-and-timestamp-availability",
        "within-event-peak-size": "within-table-native-peak-size-by-timestamp-availability",
    }
    if stem in exact:
        return exact[stem] + suffix
    if stem.startswith("availability-"):
        grouping = stem.removeprefix("availability-")
        groups = {
            "era": "reporting-era",
            "header_family": "source-table-format",
            "provider": "arrival-pick-provider",
            "distance_band": "distance-band",
            "peak_present": "numeric-peak-presence",
            "by-event": "event",
        }
        return (
            "observed-utc-availability-records"
            if grouping == "records"
            else "observed-utc-availability-by-" + groups[grouping]
        ) + suffix
    for prefix, label in {
        "NCEI-native-duration": "ncei-native-travel-duration",
        "T-OBS": "ntwc-reported-travel-duration",
        "T-CAL": "estimated-minus-observed-time-difference",
    }.items():
        if stem == prefix:
            return label + "-analysis-records" + suffix
        if not stem.startswith(prefix + "-"):
            continue
        detail = stem[len(prefix) + 1 :]
        direct = {
            "distribution": "minutes-histogram" if prefix == "T-CAL" else "log-minutes-histogram",
            "qq": "minutes-normal-quantile-plot"
            if prefix == "T-CAL"
            else "log-minutes-normal-quantile-plot",
            "physics": "versus-distance-and-fixed-depth-reference",
            "physics-bins": "log-reference-departure-by-distance-band",
            "distance": "versus-source-station-distance",
            "event-counts": "records-per-event",
            "event-effects": "component-relative-event-log-timing-effects",
            "site-effects": "component-relative-station-log-timing-effects",
            "C7": "median-log-reference-departure-after-event-deletion",
            "C9": "station-counts-by-minimum-event-repeat",
            "LOEO-support": "leave-one-event-out-station-support",
            "LOSO-support": "leave-one-station-out-event-support",
            "full-influence": "complete-event-deletion-influence-profile",
            "tail-source-cases": "extreme-departures-and-original-source-review",
            "cutoff-profile": "near-far-sensitivity-by-reference-duration-cutoff",
            "native-distance-comparison": "geodesic-versus-unverified-native-distance-values",
            "linked-definition-review": "cross-source-linked-arrival-definition-review",
        }
        if detail in direct:
            return label + "-" + direct[detail] + suffix
        detail = detail.replace("physical_site_id", "reviewed-station-key")
        detail = re.sub(r"site_([125])km", r"same-name-\1km-station-key", detail)
        detail = (
            detail.replace("within-", "within-event-", 1)
            if detail.startswith("within-")
            else detail
        )
        for old, new in {
            "header_family": "source-table-format",
            "event_id": "event",
            "precision_seconds": "reported-clock-precision-seconds",
            "time_evidence_tier": "time-evidence-tier",
            "identity_tier": "station-identity-tier",
            "identity_scope": "station-identity-scope",
            "measurement_family": "gauge-family",
            "provider": "arrival-pick-provider",
            "qualifier": "reported-time-qualifier",
        }.items():
            detail = detail.replace(old, new)
        return label + "-" + detail.replace("_", "-").lower() + suffix
    return stem.replace("_", "-").lower() + suffix


def migrated_artifact_path(relative: Path) -> Path:
    """Translate one old project-relative artifact path; never modify its contents."""
    if str(relative) in SOURCE_RENAMES:
        return Path(SOURCE_RENAMES[str(relative)])
    old = Path("artifacts/eda/paper")
    if not relative.is_relative_to(old):
        return {
            Path("config/paper-eda-v1.toml"): SETTINGS,
            Path("config/paper-eda-split-v1.toml"): SPLIT,
        }.get(relative, relative)
    parts = list(relative.relative_to(old).parts)
    if not parts:
        return EDA_ROOT
    if parts[0] in {"results", "frozen-inputs", "preliminary-checkpoint"}:
        return EDA_ROOT.joinpath(*parts)
    roots = {
        "README.md": "README.md",
        "report.md": "arrival-timing-findings.md",
        "figures.md": "figure-and-table-index.md",
        "confirmation-lock.json": LOCK.name,
    }
    if len(parts) == 1:
        return EDA_ROOT / roots.get(parts[0], parts[0])
    if parts[0] == "freeze-v1":
        freeze = {
            "inputs.json": "source-file-checksums.json",
            "development-metadata.csv": "development-event-metadata.csv",
            "branch-registry.md": "registered-analysis-questions.md",
            "target-counts.csv": "response-record-event-station-counts.csv",
        }
        return FROZEN / freeze[parts[-1]]
    checkpoint = parts[0] != "final-v1"
    if not checkpoint:
        parts.pop(0)
    match = re.fullmatch(r"(exploration|confirmation)-(C\d+|B\d+)", parts[0])
    if match:
        base = EDA_ROOT / "preliminary-checkpoint" if checkpoint else RESULTS
        return question_directory(base, match[1], match[2]) / artifact_filename(parts[-1])
    summaries = {
        "branch-replication.csv": "followup-pattern-replication.csv",
        "branch-replication.json": "followup-pattern-replication.json",
        "exploration-branch-registry.csv": "exploration-followup-triggers.csv",
        "target-summary.csv": "response-distributions-and-event-station-support.csv",
        "exploration-observable-scales.csv": "exploration-response-quantiles-and-robust-spread.csv",
    }
    return RESULTS / summaries[parts[-1]]


def result_path(base: Path, legacy_relative: str) -> Path:
    """Locate a saved result using its original logical question and table name."""
    old = Path("artifacts/eda/paper/final-v1") / legacy_relative
    return base / migrated_artifact_path(old).relative_to(RESULTS)


def rename_bundle_files(directory: Path) -> None:
    """Publish descriptive names only after every collision has been ruled out."""
    files = [p for p in directory.iterdir() if p.is_file()]
    targets = [directory / artifact_filename(p.name) for p in files]
    if len(set(targets)) != len(targets) or any(
        new.exists() and not new.samefile(old) for old, new in zip(files, targets, strict=True)
    ):
        raise ValueError("EDA filename collision")
    for old, new in zip(files, targets, strict=True):
        if old != new:
            old.rename(new)


def rewrite_markdown_links(text: str, old_document: Path, new_document: Path) -> str:
    """Relocate local Markdown destinations; preserve labels, anchors and external URLs."""

    def replace(match: re.Match[str]) -> str:
        destination = match[1]
        if destination.startswith(("https:", "http:", "#")):
            return match[0]
        name, separator, anchor = destination.partition("#")
        old_target = Path(os.path.normpath(old_document.parent / name))
        new_target = migrated_artifact_path(old_target)
        relative = os.path.relpath(new_target, new_document.parent)
        return "](" + relative + (separator + anchor if separator else "") + ")"

    return re.sub(r"\]\(([^)]+)\)", replace, text)
