"""Explicit reviewed reconciliation must preserve failures, identities and original budgets."""

# pyright: basic
import json

import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_checkpoint_resolution import (
    attach_resolution,
    validate_reviewed_checkpoint,
)
from analysis.arrival.model_data import CONTRACT


def fixture(root):
    out, raw, statepath = root / "out", root / "raw", root / "state.json"
    for p in [out / "jobs/case-0", raw, root / "old", root / "config"]:
        p.mkdir(parents=True)
    (root / "external.nc").write_bytes(b"existing")
    (root / CONTRACT).write_text("contract")
    source = out / "jobs/case-0/result.json"
    prediction = source.parent / "held-out-record-predictions.csv"
    prediction.write_text("original predictions")
    membership = source.parent / "membership.json"
    write_json(membership, {"test": ["r0", "r1"]})
    job = {
        "target": "T-OBS",
        "kind": "event",
        "prior": "base",
        "sequence": "s",
        "draws": 2000,
        "tune": 1000,
    }
    event = {
        "event_id": "e",
        "sequence": "s",
        "records": 2,
        "joint_log_predictive": -2.0,
        "normalized_event_score": -1.0,
        "precision_passed": False,
    }
    write_json(
        source,
        {
            "job": job,
            "status": "precision_failure",
            "prediction_precision_passed": True,
            "events": [event],
        },
    )
    result = root / "resolved.json"
    write_json(
        result,
        {
            "job": job,
            "source_result": str(source.relative_to(root)),
            "source_result_sha256": sha256(source),
            "events": [{**event, "precision_passed": True}],
            "fold_score": {
                "events": 1,
                "event_precision_passed": True,
                "equal_event_score": -1.0,
                "mcse_equal_event_score": 0.01,
            },
            "training_only_predictions": str(prediction.relative_to(root)),
            "training_only_predictions_sha256": sha256(prediction),
        },
    )
    plan = {
        "cases": [{"id": f"c{i}", "job": job, "ensemble_count": 2} for i in range(2)],
        "max_calls": 4,
        "max_sampler_calls": 4,
        "raw_store": "raw",
        "prior_raw_stores": ["old"],
        "external_endpoint": "external.nc",
        "files": {CONTRACT: sha256(root / CONTRACT)},
        "max_posterior_bytes": 2 * 1024**3,
    }
    write_json(out / "plan.json", plan)
    files = {str(p): sha256(p) for p in [source, prediction, membership]}
    state = {
        "status": "needs_review",
        "next_case": 0,
        "calls_used": 1,
        "sampler_call_slots_used": 2,
        "current": None,
        "plan_sha256": sha256(out / "plan.json"),
        "attempts": [
            {
                "case_id": "c0",
                "attempt": 1,
                "outcome": "diagnostic_or_precision_failure",
                "output": str(source.parent),
                "files": files,
            }
        ],
    }
    write_json(statepath, state)
    qa = root / "qa.json"
    write_json(
        qa,
        {
            "schema_version": "arrival_bridge_fold_resolution_v1",
            "status": "accepted_same_model_fold_resolution",
            "independent_checker": "fixture",
            "reserved_outcomes": "sealed",
            "case_id": "c0",
            "model_contract_sha256": sha256(root / CONTRACT),
            "native_measure": "native_minutes_joint_density_duration_Jacobian_once",
            "derived_result": "resolved.json",
            "new_sampler_calls": 0,
            "sampling_start_files": [],
            "additional_raw_stores": [],
            "files": {
                str(p.relative_to(root)): sha256(p)
                for p in [source, result, membership, prediction]
            },
        },
    )
    return out, raw, statepath, qa


def test_review_advances_logical_fold_without_relabeling_original_failure(tmp_path):
    out, raw, state, qa = fixture(tmp_path)
    attach_resolution(tmp_path, out, raw, state, qa)
    d = json.loads(state.read_text())
    p = json.loads((out / "plan.json").read_text())
    assert d["next_case"] == 1 and d["sampler_call_slots_used"] == 2
    assert d["attempts"][0]["outcome"] == "diagnostic_or_precision_failure"
    assert validate_reviewed_checkpoint(tmp_path, d, p) == (0, [])
    with pytest.raises(ValueError):
        attach_resolution(tmp_path, out, raw, state, qa)


@pytest.mark.parametrize("mode", ["prediction", "measure", "count", "lease", "swapped_prediction"])
def test_reconciliation_rejects_corruption_and_leaves_state_unchanged(tmp_path, mode):
    out, raw, state, qa = fixture(tmp_path)
    before = state.read_bytes()
    if mode == "prediction":
        (out / "jobs/case-0/held-out-record-predictions.csv").write_text("changed")
    elif mode == "lease":
        (out / ".controller.lock").write_text("running")
    elif mode == "swapped_prediction":
        replacement = tmp_path / "different-predictions.csv"
        replacement.write_text("new forecasts,other rows")
        result = tmp_path / "resolved.json"
        detail = json.loads(result.read_text())
        detail["training_only_predictions"] = str(replacement.relative_to(tmp_path))
        detail["training_only_predictions_sha256"] = sha256(replacement)
        write_json(result, detail)
        d = json.loads(qa.read_text())
        d["files"]["resolved.json"] = sha256(result)
        d["files"][str(replacement.relative_to(tmp_path))] = sha256(replacement)
        write_json(qa, d)
    else:
        d = json.loads(qa.read_text())
        d["native_measure" if mode == "measure" else "new_sampler_calls"] = (
            "wrong" if mode == "measure" else 1
        )
        write_json(qa, d)
    with pytest.raises(ValueError):
        attach_resolution(tmp_path, out, raw, state, qa)
    assert state.read_bytes() == before


@pytest.mark.parametrize("calls,allowed", [(1, True), (3, False)])
def test_external_calls_are_retained_and_debited_without_resetting_ceiling(
    tmp_path, calls, allowed
):
    out, raw, state, qa = fixture(tmp_path)
    before = state.read_bytes()
    extra = tmp_path / "data/processed/models/extra"
    extra.mkdir(parents=True)
    review = json.loads(qa.read_text())
    review["new_sampler_calls"] = calls
    review["additional_raw_stores"] = [str(extra.relative_to(tmp_path))]
    starts = []
    for i in range(calls):
        posterior = extra / f"{i}.nc"
        posterior.write_bytes(f"posterior-{i}".encode())
        start = tmp_path / f"start-{i}.json"
        write_json(
            start,
            {
                "target": "T-OBS",
                "kind": "event",
                "prior": "base",
                "sequence": "s",
                "seed": 9000 + i,
            },
        )
        starts.append(str(start.relative_to(tmp_path)))
        for p in [posterior, start]:
            review["files"][str(p.relative_to(tmp_path))] = sha256(p)
    review["sampling_start_files"] = starts
    write_json(qa, review)
    if allowed:
        attach_resolution(tmp_path, out, raw, state, qa)
        saved = json.loads(state.read_text())
        assert saved["sampler_call_slots_used"] == 3
        assert validate_reviewed_checkpoint(
            tmp_path, saved, json.loads((out / "plan.json").read_text())
        ) == (1, [str(extra.relative_to(tmp_path))])
    else:
        with pytest.raises(ValueError, match="ceiling"):
            attach_resolution(tmp_path, out, raw, state, qa)
        assert state.read_bytes() == before


@pytest.mark.parametrize("name", ["state", "output", "store"])
def test_paths_outside_project_are_rejected_before_reading_or_writing(tmp_path, name):
    root = tmp_path / "project"
    out, raw, state, qa = fixture(root)
    external = tmp_path / "external-state.json"
    external.write_bytes(state.read_bytes())
    original = state.read_bytes()
    saved = external.read_bytes()
    args = {"output": out, "store": raw, "state": state}
    args[name] = external
    with pytest.raises(ValueError, match="project-local"):
        attach_resolution(root, args["output"], args["store"], args["state"], qa)
    assert state.read_bytes() == original and external.read_bytes() == saved
