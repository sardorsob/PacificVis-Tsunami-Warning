"""Retained failures and reused independent tensors must preserve target identity."""

# pyright: basic
from copy import deepcopy

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_normalizer import PositiveProposal
from analysis.arrival.model_scaled_cubature import retained_tensor, verify_pointcap_failure


def test_only_exact_bounded_pointcap_failure_can_enter_next_allocation(tmp_path):
    source = tmp_path / "source"
    write_json(source / "result.json", {"job": {"target": "T-OBS"}})
    failed = tmp_path / "failed"
    write_json(
        failed / "inputs.json",
        {
            "job": {"target": "T-OBS"},
            "event_id": "e",
            "max_points_per_integral": 1000000,
            "files": {"source/result.json": sha256(source / "result.json")},
        },
    )
    failed.with_suffix(".log").write_text("ValueError: cubature point ceiling reached\n")
    write_json(failed.with_suffix(".supervisor.json"), {"reason": "worker_exit", "returncode": 1})
    assert len(verify_pointcap_failure(tmp_path, failed, source, "e")) == 3
    write_json(failed / "training.json", {"status": "converged"})
    with pytest.raises(ValueError, match="exact retained"):
        verify_pointcap_failure(tmp_path, failed, source, "e")
    (failed / "training.json").unlink()
    write_json(failed / "result.json", {"status": "precision_failure"})
    with pytest.raises(ValueError, match="exact retained"):
        verify_pointcap_failure(tmp_path, failed, source, "e")


@pytest.mark.parametrize("change", ["source", "proposal", "nodes", "nan", "shape"])
def test_tensor_reuse_requires_both_original_sources_and_finite_declared_refinements(change):
    proposal = PositiveProposal([1, 2], [0.2, 0.3])
    expected = {"a.nc": "a" * 64, "b.nc": "b" * 64}
    data = {
        "files": expected,
        "nodes": [512, 768],
        "proposal_location": [1, 2],
        "proposal_scale": [0.2, 0.3],
        "normalizers": {"512": [-20, -150], "768": [-20, -150]},
    }
    assert retained_tensor(proposal, data, expected) == data["normalizers"]
    invalid = deepcopy(data)
    if change == "source":
        invalid["files"] = {}
    elif change == "proposal":
        invalid["proposal_location"][0] = 2
    elif change == "nodes":
        invalid["nodes"] = [256, 512]
    elif change == "nan":
        invalid["normalizers"]["512"][0] = np.nan
    else:
        invalid["normalizers"]["768"] = [-150]
    with pytest.raises(ValueError):
        retained_tensor(proposal, invalid, expected)
