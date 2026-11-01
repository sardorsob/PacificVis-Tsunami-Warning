"""Source attribution must not become an independence claim."""

from pathlib import Path

import pytest

from analysis.arrival.evidence import file_manifest, verify_product, write_json
from analysis.arrival.lineage import attribution_segments, relation, validate_members


def test_equal_counts_cannot_hide_duplicate_and_missing_records() -> None:
    with pytest.raises(ValueError, match="conservation"):
        validate_members([{"source_record_id": "a"}, {"source_record_id": "a"}], {"a", "b"})
    validate_members([{"source_record_id": "b"}, {"source_record_id": "a"}], {"a", "b"})


def test_consumed_stage_tables_and_input_binding_are_required(tmp_path: Path) -> None:
    (tmp_path / "sites.csv").write_text("id\na\n")
    manifest = {"inputs_sha256": "original", "files": file_manifest(tmp_path)}
    write_json(tmp_path / "manifest.json", manifest)
    verify_product(tmp_path, required_files=("sites.csv",), inputs_sha256="original")
    with pytest.raises(ValueError, match="required stage pins"):
        verify_product(tmp_path, required_files=("site_links.csv.gz",))
    with pytest.raises(ValueError, match="input manifest"):
        verify_product(tmp_path, inputs_sha256="changed")


def test_same_clock_and_different_publishers_are_not_independence() -> None:
    assert relation({"agency": "PTWC", "time": "21:00"}) == "unknown"
    assert relation({"agency": "NTWC", "time": "21:00"}) == "unknown"
    assert relation({"agency": "NTWC", "time": "21:02"}) == "unknown"
    assert relation({"documented_copy": "True"}) == "copied"
    assert relation({"shared_waveform": "x"}) == "possibly-dependent"


def test_separate_cited_statements_are_not_collapsed() -> None:
    text = (
        "September 29, 2009 21:00 UTC arrival time (reference #5356)"
        "<p>September 29, 2009 21:02 UTC arrival time (reference #5406)</p>"
    )
    rows = attribution_segments(text)
    assert [r["native_reference_id"] for r in rows] == ["5356", "5406"]
    assert all(r["provenance_scope"] == "arrival_statement" for r in rows)
    assert "21:00" in rows[0]["evidence_text"]
    assert "21:02" in rows[1]["evidence_text"]
    assert (
        attribution_segments("0.539 m peak to peak (reference #10439)")[0]["provenance_scope"]
        == "amplitude_only"
    )
    assert attribution_segments("") == []
