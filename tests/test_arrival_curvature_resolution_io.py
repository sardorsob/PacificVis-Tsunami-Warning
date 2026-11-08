"""Actual path evidence must be independently closed before reading native outcomes."""

# pyright: basic
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_curvature_resolution_io import REVIEW, verified_path


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"status": "path_checkpoint", "independent_checker": True},
        {
            "status": "accepted_curvature_primary_path_and_independent_repeat",
            "independent_checker": True,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
            "files": {},
        },
    ],
)
def test_partial_or_empty_path_review_blocks_all_science_reads(tmp_path, receipt):
    write_json(tmp_path / REVIEW, receipt)
    with pytest.raises(ValueError, match="complete independently accepted"):
        verified_path(tmp_path)


def test_missing_reviewed_node_evidence_blocks_native_loader_and_output(tmp_path, monkeypatch):
    from analysis.arrival import model_curvature_resolution_io as module
    from analysis.arrival.evidence import sha256

    stub = tmp_path / "stub"
    stub.write_text("source")
    write_json(
        tmp_path / REVIEW,
        {
            "status": "accepted_curvature_primary_path_and_independent_repeat",
            "independent_checker": True,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
            "files": {"stub": sha256(stub)},
        },
    )

    def forbidden(*args):
        raise AssertionError("native outcomes must stay unread")

    monkeypatch.setattr(module, "load_lanes", forbidden)
    output = tmp_path / module.OUTPUT / "resolved-fold-v1"
    with pytest.raises(ValueError, match="before parsing"):
        module.write_resolution(tmp_path, output)
    assert not output.exists()


def synthetic_bundle(root, monkeypatch, *, include_code=True):
    """Trusted toy receipts/posterior placeholders, with no sampling or live data."""
    from dataclasses import replace

    import numpy as np

    from analysis.arrival import model_curvature_resolution_io as module
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_bridge_path import path_score
    from analysis.arrival.model_bridge_sampling import bridge_indices
    from tests.test_arrival_model_scale import grouped_lane

    def js(name, value):
        write_json(root / name, value)

    def blob(name, data=b"fixture"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def snapshot():
        return {
            str(p.relative_to(root)): sha256(p)
            for p in root.rglob("*")
            if p.is_file() and (include_code or str(p.relative_to(root)) not in module.CODE)
        }

    for name in module.CODE:
        blob(name)
    blob("native.csv")
    contract = {"inputs": {"native.csv": sha256(root / "native.csv")}}
    p = root / module.CONTRACT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('[inputs]\n"native.csv" = "' + contract["inputs"]["native.csv"] + '"\n')
    lane = grouped_lane()
    event = "official20110311054624120_30"
    sequence = "seq-" + event
    events = ("training", "training", event)
    lane = replace(
        lane,
        event_ids=events,
        sequences=("training-seq", "training-seq", sequence),
        rows=tuple({**r, "event_id": events[i]} for i, r in enumerate(lane.rows)),
    )
    train, fold = bridge_indices(lane, sequence, "training", None)
    original_raw = "data/processed/models/mean-curvature-sequence-v1/fold-002/"
    for name in ["00-training.nc", "01-augmented.nc"]:
        blob(original_raw + name)
    bridge = root / original_raw / "bridge-arrays.npz"
    np.savez_compressed(bridge, unused=np.zeros(1))
    training_sha = sha256(root / original_raw / "00-training.nc")
    original = {
        "job": {
            "kind": "mean-curvature",
            "target": lane.target,
            "prior": "base",
            "sequence": sequence,
        },
        "status": "precision_failure",
        "prediction_precision_passed": True,
        "events": [
            {
                "event_id": event,
                "sequence": sequence,
                "records": 1,
                "precision_passed": False,
                "normalized_event_score": -999.0,
            }
        ],
        "bridge_arrays": original_raw + "bridge-arrays.npz",
        "bridge_arrays_sha256": sha256(bridge),
        "observation_measure": "native_minutes_Jacobian_already_applied_once",
    }
    js(module.SOURCE + "/result.json", original)
    js(module.SOURCE + "/inputs.json", {"fixture": True})
    js(
        module.SOURCE + "/membership.json",
        {
            "train": [lane.record_ids[int(i)] for i in train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": sequence,
        },
    )
    blob(module.SOURCE + "/held-out-record-predictions.csv")
    for name in ["00-training", "01-augmented"]:
        raw = original_raw + name + ".nc"
        js(
            module.SOURCE + "/ensembles/" + name + "/result.json",
            {"posterior": raw, "posterior_sha256": sha256(root / raw)},
        )
    js(
        module.STOP_REVIEW,
        {
            "status": "accepted_fold001_retained_fold002_numerical_stop",
            "independent_checker": True,
            "files": snapshot(),
        },
    )
    js(
        module.SOURCE_GATE,
        {
            "status": "accepted_curvature_path_resolution",
            "independent_checker": True,
            "files": snapshot(),
        },
    )
    plan_files = snapshot()
    jobs = module.path_jobs()
    js(module.OUTPUT + "/plan.json", {"jobs": jobs, "files": plan_files})
    for job in jobs:
        base = module.OUTPUT + "/jobs/" + job["id"]
        raw = module.STORE + "/" + job["id"] + ".nc"
        blob(raw)
        blob(module.STORE + "/" + job["id"] + ".loglikelihood.npz")
        for name in ["job.json", "sampling-start.json"]:
            js(base + "/" + name, job)
        js(base + "/inputs.json", {"files": plan_files, "source_files": contract})
        js(
            base + "/result.json",
            {"job": job, "posterior": raw, "posterior_sha256": sha256(root / raw)},
        )
        for name in ["membership.json", "attempt-evidence.json"]:
            js(base + "/" + name, {})
        blob(base + "/sampling-diagnostics.csv")
        js(base + "-spec.json", job)
        blob(base + ".log")
        js(base + ".supervisor.json", {})
    native = lane.y[fold.test]
    primary, influences = path_score(
        [np.full((4, 2000), -7.0) for _ in range(17)],
        (np.arange(17) / 16) ** 2,
        records=1,
        jacobian=float(np.log(native).sum()),
    )
    primary.update(
        event_id=event,
        sequence=sequence,
        records=1,
        target=lane.target,
        kind="mean-curvature",
        source_training_posterior_sha=training_sha,
    )
    repeat_raw = module.STORE + "/repeat-node-00.nc"
    repeat = {**primary, "source_training_posterior_sha": sha256(root / repeat_raw)}
    for role, value in [("primary", primary), ("repeat", repeat)]:
        js(module.OUTPUT + "/" + role + "-path-result.json", value)
        np.savez_compressed(
            root / module.STORE / (role + "-combined-influences.npz"),
            **{f"node_{i}": v for i, v in enumerate(influences)},
        )
    js(
        module.OUTPUT + "/independent-repeat-check.json",
        {
            "agreement_passed": True,
            "primary_designated_before_fitting": True,
            "score_to_use": "primary_never_select_favorable_repeat",
            "raw_difference": 0.0,
            "combined_mcse": 0.0,
        },
    )
    cursor = 0
    active = 0.0
    for j in range(11):
        end = min(cursor + 3, 32)
        active += 0.1
        aggregates = (
            {
                module.OUTPUT + "/primary-path-result.json": sha256(
                    root / module.OUTPUT / "primary-path-result.json"
                ),
                module.STORE + "/primary-combined-influences.npz": sha256(
                    root / module.STORE / "primary-combined-influences.npz"
                ),
            }
            if end >= 15
            else {}
        )
        if end == 32:
            aggregates.update(
                {
                    module.OUTPUT + "/repeat-path-result.json": sha256(
                        root / module.OUTPUT / "repeat-path-result.json"
                    ),
                    module.STORE + "/repeat-combined-influences.npz": sha256(
                        root / module.STORE / "repeat-combined-influences.npz"
                    ),
                    module.OUTPUT + "/independent-repeat-check.json": sha256(
                        root / module.OUTPUT / "independent-repeat-check.json"
                    ),
                }
            )
        receipts = {
            module.OUTPUT + "/jobs/" + job["id"] + "/attempt-evidence.json": sha256(
                root / module.OUTPUT / "jobs" / job["id"] / "attempt-evidence.json"
            )
            for job in jobs[cursor:end]
        }
        js(
            module.OUTPUT + f"/invocations/{j:03d}.json",
            {
                "start_node": cursor,
                "end_node": end,
                "seconds": 0.1,
                "plan_sha256": sha256(root / module.OUTPUT / "plan.json"),
                "attempt_receipts": receipts,
                "aggregate_files": aggregates,
            },
        )
        cursor = end
    js(
        module.OUTPUT + "/run-summary.json",
        {
            "status": "path_computations_complete",
            "accepted_nodes": 32,
            "total_curvature_calls_charged": 38,
            "total_curvature_calls_started": 38,
            "new_slots_charged": 32,
            "max_curvature_slots": 248,
            "active_seconds": active,
        },
    )
    js(
        module.REVIEW,
        {
            "status": "accepted_curvature_primary_path_and_independent_repeat",
            "independent_checker": True,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
            "files": snapshot(),
        },
    )
    monkeypatch.setattr(module, "load_lanes", lambda *a: ({"NCEI-native-duration": lane}, contract))
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "fixture-git\n")
    return module, primary


def test_complete_synthetic_bundle_preserves_native_score_and_prediction_source(
    tmp_path, monkeypatch
):
    import json

    module, primary = synthetic_bundle(tmp_path, monkeypatch)
    output = tmp_path / module.OUTPUT / "resolved-fold-v1"
    module.write_resolution(tmp_path, output)
    result = json.loads((output / "result.json").read_text())
    assert result["events"][0]["normalized_event_score"] == pytest.approx(
        primary["normalized_event_score"]
    )
    assert result["training_only_predictions"] == module.SOURCE + "/held-out-record-predictions.csv"
    assert result["retained_direct_bridge_status"] == "precision_failure"
    pins = json.loads((output / "inputs.json").read_text())["files"]
    assert "analysis/arrival/model_path_fold_resolution.py" in pins


def test_missing_original_pin_is_rejected_before_native_loader(tmp_path, monkeypatch):
    import json

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    p = tmp_path / module.REVIEW
    review = json.loads(p.read_text())
    review["files"].pop(module.SOURCE + "/result.json")
    write_json(p, review)

    def forbidden(*args):
        raise AssertionError("native loader must stay unopened")

    monkeypatch.setattr(module, "load_lanes", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", "other-event"),
        ("kind", "distance-scale"),
        ("joint_log_mcse_delta", -0.1),
        ("source_training_posterior_sha", "b" * 64),
    ],
)
def test_wrong_repeat_certificate_cannot_enter_resolution(tmp_path, monkeypatch, field, value):
    import json

    from analysis.arrival.evidence import sha256

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    p = tmp_path / module.OUTPUT / "repeat-path-result.json"
    item = json.loads(p.read_text())
    item[field] = value
    write_json(p, item)
    timing = tmp_path / module.OUTPUT / "invocations/010.json"
    item = json.loads(timing.read_text())
    item["aggregate_files"][str(p.relative_to(tmp_path))] = sha256(p)
    write_json(timing, item)
    review = tmp_path / module.REVIEW
    item = json.loads(review.read_text())
    item["files"][str(p.relative_to(tmp_path))] = sha256(p)
    item["files"][str(timing.relative_to(tmp_path))] = sha256(timing)
    write_json(review, item)
    with pytest.raises(ValueError, match="certificate|training identity"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


def test_scientific_helper_changed_during_handoff_is_rejected_without_repinning(
    tmp_path, monkeypatch
):
    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    verify = module.verified_path

    def changed(root):
        pins = verify(root)
        p = root / "analysis/arrival/model_path_fold_resolution.py"
        p.write_text("changed after review")
        return pins

    monkeypatch.setattr(module, "verified_path", changed)
    output = tmp_path / module.OUTPUT / "resolved-fold-v1"
    with pytest.raises(ValueError, match="scientific helper source changed"):
        module.write_resolution(tmp_path, output)
    assert not output.exists()


def test_unreviewed_helper_changed_after_initial_snapshot_is_not_silently_pinned(
    tmp_path, monkeypatch
):
    module, _ = synthetic_bundle(tmp_path, monkeypatch, include_code=False)
    resolve = module.resolved_path_result

    def changed(*args, **kwargs):
        result = resolve(*args, **kwargs)
        (tmp_path / "analysis/arrival/model_curvature_resolution.py").write_text(
            "changed during execution"
        )
        return result

    monkeypatch.setattr(module, "resolved_path_result", changed)
    output = tmp_path / module.OUTPUT / "resolved-fold-v1"
    with pytest.raises(ValueError, match="executed scientific helper source changed"):
        module.write_resolution(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize("which", ["bridge", "training"])
def test_metadata_cannot_point_to_an_unreviewed_array_or_endpoint(tmp_path, monkeypatch, which):
    import json

    from analysis.arrival.evidence import sha256

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    p = (
        tmp_path
        / module.SOURCE
        / ("result.json" if which == "bridge" else "ensembles/00-training/result.json")
    )
    item = json.loads(p.read_text())
    item["bridge_arrays" if which == "bridge" else "posterior"] = "unreviewed.npz"
    write_json(p, item)
    for name in [module.STOP_REVIEW, module.SOURCE_GATE]:
        q = tmp_path / name
        r = json.loads(q.read_text())
        r["files"][str(p.relative_to(tmp_path))] = sha256(p)
        if name == module.SOURCE_GATE:
            r["files"][module.STOP_REVIEW] = sha256(tmp_path / module.STOP_REVIEW)
        write_json(q, r)
    plan = tmp_path / module.OUTPUT / "plan.json"
    r = json.loads(plan.read_text())
    for key in [str(p.relative_to(tmp_path)), module.STOP_REVIEW, module.SOURCE_GATE]:
        r["files"][key] = sha256(tmp_path / key)
    write_json(plan, r)
    for job in module.path_jobs():
        q = tmp_path / module.OUTPUT / "jobs" / job["id"] / "inputs.json"
        v = json.loads(q.read_text())
        v["files"] = r["files"]
        write_json(q, v)
    for q in (tmp_path / module.OUTPUT / "invocations").glob("*.json"):
        v = json.loads(q.read_text())
        v["plan_sha256"] = sha256(plan)
        write_json(q, v)
    review = tmp_path / module.REVIEW
    r = json.loads(review.read_text())
    for key in r["files"]:
        r["files"][key] = sha256(tmp_path / key)
    write_json(review, r)
    with pytest.raises(ValueError, match="canonical reviewed original"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")
