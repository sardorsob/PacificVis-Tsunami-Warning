"""Reject a changed confirmation definition before reading any outcome table."""

import json
from pathlib import Path

import pytest

from analysis.arrival.evidence import sha256
from analysis.arrival.timing_artifact_names import CODE_FILES, artifact_filename, question_directory
from scripts.run_arrival_timing_eda import run


@pytest.fixture
def frozen_root(tmp_path: Path) -> Path:
    files = [
        "analysis/arrival/timing_data_and_descriptive_statistics.py",
        "analysis/arrival/timing_diagnostic_plots.py",
        "analysis/arrival/timing_artifact_names.py",
        "scripts/run_arrival_timing_eda.py",
        "analysis/arrival/timing_group_reporting_and_support_diagnostics.py",
        "analysis/arrival/timing_followup_diagnostics.py",
        "analysis/arrival/evidence.py",
        "analysis/arrival/observations.py",
        "analysis/arrival/site_registry.py",
    ]
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture only")
    f = tmp_path / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
    f.parent.mkdir(parents=True)
    f.write_text(
        json.dumps(
            {
                "schema_version": "paper_eda_inputs_v1",
                "root": str(tmp_path),
                "files": [{"path": files[0], "sha256": sha256(tmp_path / files[0])}],
            }
        )
    )
    config = tmp_path / "config/arrival-timing-exploration-confirmation-split.toml"
    config.parent.mkdir()
    config.write_text('confirmation = ["confirm"]\n')
    return tmp_path


def test_confirmation_drift_is_checked_before_outcome_loading(frozen_root: Path) -> None:
    tmp_path = frozen_root
    f = tmp_path / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
    lock = tmp_path / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json"
    lock.write_text(
        json.dumps(
            {
                "code": {"changed": "wrong"},
                "inputs_sha256": sha256(f),
                "artifact_root": str(tmp_path / "outputs"),
            }
        )
    )
    with pytest.raises(ValueError, match="drift"):
        run(tmp_path, "confirmation", "C1", tmp_path / "outputs/confirmation-C1")


def test_confirmation_replay_requires_existing_canonical_before_outcomes(frozen_root: Path) -> None:
    root = frozen_root
    files = [str(p.relative_to(root)) for p in (root / "analysis/arrival").glob("*.py")]
    files.append("scripts/run_arrival_timing_eda.py")
    lock = root / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json"
    lock.write_text(
        json.dumps(
            {
                "code": {name: sha256(root / name) for name in files},
                "inputs_sha256": sha256(
                    root / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
                ),
                "artifact_root": str(root / "outputs"),
                "questions": ["C1"],
            }
        )
    )
    with pytest.raises(ValueError, match="existing canonical"):
        run(root, "confirmation", "C1", root / "replay/confirmation-C1", replay=True)


def test_unselected_confirmation_question_is_rejected_before_outcomes(frozen_root: Path) -> None:
    root = frozen_root
    files = [str(p.relative_to(root)) for p in (root / "analysis/arrival").glob("*.py")]
    files.append("scripts/run_arrival_timing_eda.py")
    (root / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json").write_text(
        json.dumps(
            {
                "code": {name: sha256(root / name) for name in files},
                "inputs_sha256": sha256(
                    root / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
                ),
                "artifact_root": str(root / "outputs"),
                "questions": ["C1"],
            }
        )
    )
    with pytest.raises(ValueError, match="not selected"):
        run(root, "confirmation", "B11", root / "outputs/confirmation-B11")


def test_renamed_replay_rejects_changed_generation_metadata_before_outcomes(
    frozen_root: Path,
) -> None:
    root = frozen_root
    canonical = question_directory(root / "outputs", "confirmation", "C1")
    canonical.mkdir(parents=True)
    metadata = canonical / artifact_filename("inputs.json")
    metadata.write_text("original generation pins")
    digest = sha256(metadata)
    metadata.write_text("tampered generation pins")
    lock = {
        "code": {"original_generation_code": "retained"},
        "layout_replay_code": {name: sha256(root / name) for name in CODE_FILES},
        "inputs_sha256": sha256(
            root / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
        ),
        "artifact_root": str(root / "outputs"),
        "questions": ["C1"],
        "generation_metadata_sha256": {"confirmation:C1": {metadata.name: digest}},
    }
    (root / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json").write_text(
        json.dumps(lock)
    )
    with pytest.raises(ValueError, match="generation metadata changed"):
        run(root, "confirmation", "C1", root / "scratch/replay", replay=True)
