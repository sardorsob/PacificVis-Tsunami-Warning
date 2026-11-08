"""Every later fixed path must retain earlier external posteriors in its global cap."""
# pyright: basic

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts.run_arrival_path_with_storage import audit_storage


def fixture(root):
    prior = root / "prior"
    prior.mkdir()
    (prior / "a.nc").write_bytes(b"abc")
    extra = root / "extra"
    extra.mkdir()
    (extra / "b.nc").write_bytes(b"abcd")
    (root / "endpoint.nc").write_bytes(b"ab")
    write_json(
        root / "qa.json",
        {
            "status": "accepted_same_model_fold_resolution",
            "independent_checker": "checker",
            "additional_raw_stores": ["extra"],
            "files": {"extra/b.nc": sha256(extra / "b.nc")},
        },
    )
    registry = {"oldcase": {"path": "qa.json", "sha256": sha256(root / "qa.json")}}
    write_json(root / "previous.json", registry)
    write_json(root / "parent/reviewed-resolutions.json", registry)
    return {
        "previous_resolutions_snapshot": "previous.json",
        "parent_output": "parent",
        "files": {
            "previous.json": sha256(root / "previous.json"),
            "qa.json": sha256(root / "qa.json"),
        },
        "prior_raw_stores": ["prior"],
        "external_endpoint": "endpoint.nc",
        "max_raw_bytes": 2**31,
    }


def test_storage_includes_prior_external_files_and_reserves_next_worst_case(tmp_path):
    spec = fixture(tmp_path)
    assert audit_storage(tmp_path, spec, tmp_path / "new") == 9
    spec["max_raw_bytes"] = 3 * 64 * 1024**2 + 8
    with pytest.raises(ValueError, match="budget exhausted"):
        audit_storage(tmp_path, spec, tmp_path / "new")


@pytest.mark.parametrize(
    "change", ["raw", "registry", "overlap", "deleted_file", "deleted_folder", "added_file"]
)
def test_changed_or_overlapping_external_evidence_cannot_start_next_node(tmp_path, change):
    spec = fixture(tmp_path)
    if change == "raw":
        (tmp_path / "extra/b.nc").write_bytes(b"changed")
    elif change == "registry":
        write_json(tmp_path / "parent/reviewed-resolutions.json", {})
    elif change == "deleted_file":
        (tmp_path / "extra/b.nc").unlink()
    elif change == "deleted_folder":
        (tmp_path / "extra/b.nc").unlink()
        (tmp_path / "extra").rmdir()
    elif change == "added_file":
        (tmp_path / "extra/new.nc").write_bytes(b"new")
    else:
        spec["prior_raw_stores"].append("extra")
    with pytest.raises(ValueError):
        audit_storage(tmp_path, spec, tmp_path / "new")
