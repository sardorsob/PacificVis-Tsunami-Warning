"""Naming changes preserve outcome distinctions and registered question identity."""

from pathlib import Path

from analysis.arrival.timing_artifact_names import (
    EDA_ROOT,
    artifact_filename,
    migrated_artifact_path,
    rename_bundle_files,
    rewrite_markdown_links,
)


def test_names_explain_transformation_and_preserve_signed_target() -> None:
    assert artifact_filename("T-OBS-distribution.png") == (
        "ntwc-reported-travel-duration-log-minutes-histogram.png"
    )
    assert artifact_filename("T-CAL-distribution.png") == (
        "estimated-minus-observed-time-difference-minutes-histogram.png"
    )
    assert artifact_filename("B3-screen.csv") == "station-effect-stability-diagnostic-summary.csv"


def test_split_and_checkpoint_paths_never_collide() -> None:
    paths = [
        Path("artifacts/eda/paper") / p
        for p in [
            "exploration-C2/T-OBS-distribution.png",
            "final-v1/exploration-C2/T-OBS-distribution.png",
            "final-v1/confirmation-C2/T-OBS-distribution.png",
        ]
    ]
    renamed = [migrated_artifact_path(p) for p in paths]
    assert len(set(renamed)) == 3
    assert all(p.is_relative_to(EDA_ROOT) for p in renamed)


def test_link_relocation_preserves_anchor_and_external_source() -> None:
    old = Path("artifacts/eda/paper/README.md")
    text = "[results](report.md#distance) [source](https://example.org/source#section)"
    new = rewrite_markdown_links(text, old, migrated_artifact_path(old))
    assert new == (
        "[results](arrival-timing-findings.md#distance) "
        "[source](https://example.org/source#section)"
    )


def test_case_only_filename_rename_preserves_payload_on_macos(tmp_path: Path) -> None:
    original = tmp_path / "NTWC-reports-availability-era.csv"
    original.write_bytes(b"accepted_rows,availability\n5,0.8\n")
    rename_bundle_files(tmp_path)
    renamed = tmp_path / "ntwc-reports-availability-era.csv"
    assert renamed.read_bytes() == b"accepted_rows,availability\n5,0.8\n"
    assert [p.name for p in tmp_path.iterdir()] == [renamed.name]
