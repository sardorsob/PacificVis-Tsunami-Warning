"""Manifest policy and exhausted-first-cap provenance remain closed and source-bound."""

# pyright: basic
from copy import deepcopy

import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_bounded_cubature import validate_manifest, verify_first_cap
from analysis.arrival.model_exhausted_cubature import verify_exhausted
from tests.test_arrival_exhausted_cubature import fixture


def test_exhausted_first_cap_retains_its_second_proof_and_rejects_completed_stages(tmp_path):
    source, state = fixture(tmp_path)
    import json

    job = json.loads((source / "result.json").read_text())["job"]
    proof = verify_exhausted(tmp_path, source, state)
    failed = tmp_path / "failed"
    write_json(
        failed / "inputs.json",
        {
            "job": job,
            "event_id": "e",
            "max_points_per_integral": 1000000,
            "exhausted_repair": proof,
            "files": {
                str((source / "result.json").relative_to(tmp_path)): sha256(source / "result.json")
            },
        },
    )
    write_json(failed / "exhausted-repair-evidence.json", proof)
    failed.with_suffix(".log").write_text("ValueError: cubature point ceiling reached\n")
    write_json(failed.with_suffix(".supervisor.json"), {"reason": "worker_exit", "returncode": 1})
    pins, validated = verify_first_cap(tmp_path, failed, source, "e", state, "exhausted_first_cap")
    assert len(pins) == 4 and validated == proof
    write_json(failed / "training.json", {"status": "converged"})
    with pytest.raises(ValueError):
        verify_first_cap(tmp_path, failed, source, "e", state, "exhausted_first_cap")
    (failed / "training.json").unlink()
    bad = {**proof, "second_result_sha256": "wrong"}
    write_json(failed / "exhausted-repair-evidence.json", bad)
    with pytest.raises(ValueError):
        verify_first_cap(tmp_path, failed, source, "e", state, "exhausted_first_cap")


@pytest.mark.parametrize(
    "change", ["budget", "unreviewed", "count", "hash", "profile", "rtol", "missing_science"]
)
def test_manifest_rejects_unreviewed_or_changed_policy_before_outcomes(
    tmp_path, monkeypatch, change
):
    monkeypatch.setattr("analysis.arrival.model_bounded_cubature.CONSUMED", ["stub.py"])
    (tmp_path / "stub.py").write_text("frozen")
    spec = {
        "schema_version": "arrival_bounded_event_cubature_v1",
        "status": "accepted_for_bounded_event_cubature",
        "independent_checker": "checker",
        "reserved_outcomes": "sealed",
        "case_id": "case",
        "event_id": "e",
        "target": "T-CAL",
        "records": 5,
        "admission_profile": "exhausted_first_cap",
        "max_points_per_integral": 2000000,
        "adaptive_integrals": 5,
        "new_sampler_calls": 0,
        "prior_failed_point_ceiling": 1000000,
        "retained_tensor_points": 1703936,
        "cumulative_point_ceiling": 12703936,
        "final_score_tolerance_per_record": 1e-6,
        "primary_rtol": 1.25e-6,
        "refined_rtol": 6.25e-7,
        "files": {"stub.py": sha256(tmp_path / "stub.py")},
        "source_fold": "case-attempt-2",
        "failed_calculation": "failed",
        "retained_tensor": "tensor.json",
        "output": "new",
    }
    for name in [
        "case-attempt-2/result.json",
        "case-attempt-2/inputs.json",
        "case-attempt-2/membership.json",
        "case-attempt-2/held-out-record-predictions.csv",
        "failed/inputs.json",
        "failed/exhausted-repair-evidence.json",
        "failed.log",
        "failed.supervisor.json",
        "tensor.json",
    ]:
        write_json(tmp_path / name, {})
        spec["files"][name] = sha256(tmp_path / name)
    manifest = tmp_path / "design.json"
    write_json(manifest, spec)
    assert validate_manifest(tmp_path, manifest) == spec
    bad = deepcopy(spec)
    if change == "budget":
        bad["max_points_per_integral"] = 3000000
    elif change == "unreviewed":
        bad["status"] = "pending"
    elif change == "count":
        bad["records"] = True
    elif change == "hash":
        bad["files"]["stub.py"] = "a" * 64
    elif change == "profile":
        bad["admission_profile"] = "loose"
    elif change == "rtol":
        bad["primary_rtol"] = 1e-5
    else:
        del bad["files"]["tensor.json"]
    write_json(manifest, bad)
    with pytest.raises(ValueError):
        validate_manifest(tmp_path, manifest)


def test_unreviewed_ensemble_posterior_is_rejected_before_dataset_reader(tmp_path, monkeypatch):
    from analysis.arrival.model_bounded_cubature import reviewed_ensemble

    folder = tmp_path / "ensemble"
    write_json(folder / "result.json", {"posterior": "posterior.nc"})
    files = {"ensemble/result.json": sha256(folder / "result.json")}
    for name in [
        "inputs.json",
        "job.json",
        "membership.json",
        "diagnostics.json",
        "sampling-diagnostics.csv",
    ]:
        write_json(folder / name, {})
        files["ensemble/" + name] = sha256(folder / name)

    def forbidden(*_):
        raise AssertionError("unreviewed dataset reader called")

    monkeypatch.setattr("analysis.arrival.model_bounded_cubature._read_ensemble", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        reviewed_ensemble(tmp_path, {"files": files}, folder)
