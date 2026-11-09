"""Actual path evidence must be independently closed before reading native outcomes."""

# pyright: basic
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_curvature_sumatra_resolution_io import REVIEW, verified_path


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"status": "path_checkpoint", "independent_checker": True},
        {
            "status": "accepted_curvature_sumatra_primary_path_and_independent_repeat",
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
    from analysis.arrival import model_curvature_sumatra_resolution_io as module
    from analysis.arrival.evidence import sha256

    stub = tmp_path / "stub"
    stub.write_text("source")
    write_json(
        tmp_path / REVIEW,
        {
            "status": "accepted_curvature_sumatra_primary_path_and_independent_repeat",
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

    from analysis.arrival import model_curvature_sumatra_resolution_io as module
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
    base_lane = grouped_lane()
    event = "usp000exfn"
    sequence = "seq-usp000exfn"
    events = (
        tuple(f"training-{j % 30}" for j in range(984))
        + (event,) * 49
        + ("usp000f2ab",) * 22
        + ("usp000gsmz",) * 9
    )
    sequences = tuple(f"training-seq-{j % 30}" for j in range(984)) + (sequence,) * 80
    distance = np.linspace(500.0, 9000.0, 1064)
    reference = distance / 12.0
    native = np.full(1064, np.exp(3.0))
    lane = replace(
        base_lane,
        record_ids=tuple(f"r{j:04d}" for j in range(1064)),
        event_ids=events,
        site_ids=tuple(f"site-{j % 90}" for j in range(1064)),
        sequences=sequences,
        rows=tuple({"event_id": event_id} for event_id in events),
        distance_km=distance,
        reference_minutes=reference,
        x=np.log(distance / 1000),
        response=np.log(native / reference),
        y=native,
        included=np.ones(1064, dtype=bool),
    )
    train, fold = bridge_indices(lane, sequence, "training", None)
    original_raw = "data/processed/models/mean-curvature-sequence-v1/fold-019/"
    for name in ["00-training.nc", "01-augmented.nc", "02-augmented.nc", "03-augmented.nc"]:
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
            "id": "fold-019",
            "seed": 2856129800,
        },
        "sampler_calls_started": 4,
        "status": "precision_failure",
        "prediction_precision_passed": True,
        "events": [
            {
                "event_id": name,
                "sequence": sequence,
                "records": n,
                "precision_passed": j != 0,
                "normalized_event_score": -999.0 if j == 0 else -5.0 - j,
            }
            for j, (name, n) in enumerate([(event, 49), ("usp000f2ab", 22), ("usp000gsmz", 9)])
        ],
        "bridge_arrays": original_raw + "bridge-arrays.npz",
        "bridge_arrays_sha256": sha256(bridge),
        "observation_measure": "native_minutes_Jacobian_already_applied_once",
    }
    js(module.SOURCE + "/result.json", original)
    js(
        module.SOURCE + "/inputs.json",
        {"files": {"native.csv": sha256(root / "native.csv")}, "source_files": contract},
    )
    js(module.SOURCE + "/job.json", original["job"])
    js(module.SOURCE + "/attempt-evidence.json", {})
    blob(module.SOURCE + ".log")
    js(module.SOURCE + "-spec.json", original["job"])
    js(module.SOURCE + ".supervisor.json", {})
    js(
        module.SOURCE + "/membership.json",
        {
            "train": [lane.record_ids[int(i)] for i in train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": sequence,
        },
    )
    blob(module.SOURCE + "/held-out-record-predictions.csv")
    for j, event_id in enumerate([None, event, "usp000f2ab", "usp000gsmz"]):
        phase = "training" if j == 0 else "augmented"
        name = f"{j:02d}-{phase}"
        raw = original_raw + name + ".nc"
        job = {
            **original["job"],
            "phase": phase,
            "event": event_id,
            "seed": original["job"]["seed"] + j,
        }
        ids, _ = bridge_indices(lane, sequence, phase, event_id)
        js(module.SOURCE + f"/sampling-starts/{j:02d}.json", job)
        js(module.SOURCE + "/ensembles/" + name + "/job.json", job)
        js(module.SOURCE + "/ensembles/" + name + "/inputs.json", {"source_files": contract})
        js(
            module.SOURCE + "/ensembles/" + name + "/membership.json",
            {"included": [lane.record_ids[int(i)] for i in ids]},
        )
        blob(module.SOURCE + "/ensembles/" + name + "/sampling-diagnostics.csv")
        js(
            module.SOURCE + "/ensembles/" + name + "/result.json",
            {"job": job, "posterior": raw, "posterior_sha256": sha256(root / raw)},
        )
    parent_cases = [{} for _ in range(29)]
    parent_cases[19] = original["job"]
    js(
        "artifacts/models/arrival-timing/mean-curvature-sequence-v1/plan.json",
        {"cases": parent_cases, "files": {"native.csv": sha256(root / "native.csv")}},
    )
    js(
        module.STOP_REVIEW,
        {
            "status": "accepted_curvature_completion_overlap_stop",
            "independent_checker": True,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
            "files": snapshot(),
        },
    )
    js(
        module.SOURCE_GATE,
        {
            "status": "accepted_curvature_sumatra_path_resolution",
            "independent_checker": True,
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
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
    held = [int(i) for i in fold.test if lane.event_ids[int(i)] == event]
    native = lane.y[held]
    primary, influences = path_score(
        [
            (-7.0 + 0.02 * np.sin(np.arange(8000).reshape(4, 2000) * np.sqrt(2) + j))
            for j in range(17)
        ],
        (np.arange(17) / 16) ** 2,
        records=49,
        jacobian=float(np.log(native).sum()),
    )
    primary.update(
        event_id=event,
        sequence=sequence,
        records=49,
        target=lane.target,
        kind="mean-curvature",
        source_training_posterior_sha=training_sha,
    )
    first = influences[0]
    np.savez_compressed(
        bridge,
        training_influence_001=2.5 * first * 22 / 49,
        training_influence_002=-0.5 * first * 9 / 49,
        augmented_influence_001=influences[1] * 0.7,
        augmented_influence_002=influences[2] * 0.8,
    )
    # The bridge bytes become final before receipt snapshots are closed below.
    original["bridge_arrays_sha256"] = sha256(bridge)
    js(module.SOURCE + "/result.json", original)
    for name in [module.STOP_REVIEW, module.SOURCE_GATE]:
        value = __import__("json").loads((root / name).read_text())
        for path in value["files"]:
            value["files"][path] = sha256(root / path)
        js(name, value)
    plan_files = {path: sha256(root / path) for path in plan_files}
    js(module.OUTPUT + "/plan.json", {"jobs": jobs, "files": plan_files})
    for job in jobs:
        base = module.OUTPUT + "/jobs/" + job["id"]
        js(base + "/inputs.json", {"files": plan_files, "source_files": contract})
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
            "combined_mcse": float(
                np.hypot(primary["joint_log_mcse_delta"], repeat["joint_log_mcse_delta"])
            ),
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
            "total_curvature_calls_charged": 109,
            "total_curvature_calls_started": 109,
            "new_slots_charged": 32,
            "max_curvature_slots": 248,
            "active_seconds": active,
        },
    )
    js(
        module.REVIEW,
        {
            "status": "accepted_curvature_sumatra_primary_path_and_independent_repeat",
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


def refresh_proofs(root, module):
    """Re-sign a toy bundle so semantic corruption reaches the intended guard."""
    import json

    from analysis.arrival.evidence import sha256

    for name in [module.STOP_REVIEW, module.SOURCE_GATE]:
        path = root / name
        value = json.loads(path.read_text())
        value["files"] = {p: sha256(root / p) for p in value["files"]}
        write_json(path, value)
    plan = root / module.OUTPUT / "plan.json"
    value = json.loads(plan.read_text())
    value["files"] = {p: sha256(root / p) for p in value["files"]}
    write_json(plan, value)
    for job in module.path_jobs():
        path = root / module.OUTPUT / "jobs" / job["id"] / "inputs.json"
        item = json.loads(path.read_text())
        item["files"] = value["files"]
        write_json(path, item)
    for path in (root / module.OUTPUT / "invocations").glob("*.json"):
        item = json.loads(path.read_text())
        item["plan_sha256"] = sha256(plan)
        for key in ["attempt_receipts", "aggregate_files"]:
            item[key] = {p: sha256(root / p) for p in item[key]}
        write_json(path, item)
    path = root / module.REVIEW
    item = json.loads(path.read_text())
    item["files"] = {p: sha256(root / p) for p in item["files"]}
    write_json(path, item)


def test_shared_49_22_9_covariance_is_combined_before_mcse_and_native_jacobian_once(
    tmp_path, monkeypatch
):
    import json
    import math

    import arviz_stats as azs
    import numpy as np

    from analysis.arrival.evidence import sha256

    module, primary = synthetic_bundle(tmp_path, monkeypatch)
    original_file = tmp_path / module.SOURCE / "result.json"
    original_bytes = original_file.read_bytes()
    original = json.loads(original_bytes)
    with np.load(tmp_path / module.STORE / "primary-combined-influences.npz") as raw:
        phi = [raw[f"node_{j}"] for j in range(17)]
    with np.load(tmp_path / module.ORIGINAL_RAW / "bridge-arrays.npz") as raw:
        bridge = {name: raw[name] for name in raw.files}
    from typing import Any, cast

    def se(v):
        return float(cast(Any, azs).mcse(v, method="mean", chain_axis=0, draw_axis=1))

    shared = (
        phi[0] / 49 + bridge["training_influence_001"] / 22 + bridge["training_influence_002"] / 9
    ) / 3
    independent = (
        sum((se(v) / 49 / 3) ** 2 for v in phi[1:])
        + (se(bridge["augmented_influence_001"]) / 22 / 3) ** 2
        + (se(bridge["augmented_influence_002"]) / 9 / 3) ** 2
    )
    expected = math.sqrt(se(shared) ** 2 + independent)
    naive = math.sqrt(
        (se(phi[0]) / 49 / 3) ** 2
        + (se(bridge["training_influence_001"]) / 22 / 3) ** 2
        + (se(bridge["training_influence_002"]) / 9 / 3) ** 2
        + independent
    )
    output = tmp_path / module.OUTPUT / "resolved-fold-v1"
    module.write_resolution(tmp_path, output)
    result = json.loads((output / "result.json").read_text())
    assert result["fold_score"]["mcse_equal_event_score"] == pytest.approx(expected, rel=1e-12)
    assert not math.isclose(expected, naive, rel_tol=1e-6, abs_tol=0)
    assert result["events"][1:] == original["events"][1:]
    assert result["fold_score"]["equal_event_score"] == pytest.approx(
        np.mean([primary["normalized_event_score"], -6, -7])
    )
    assert primary["native_jacobian_subtracted_once"] == pytest.approx(49 * 3)
    assert original_file.read_bytes() == original_bytes
    prediction = module.SOURCE + "/held-out-record-predictions.csv"
    assert result["training_only_predictions_sha256"] == sha256(tmp_path / prediction)


@pytest.mark.parametrize("missing", ["prediction", "last_original_raw", "one_node"])
def test_full_closure_required_before_native_loader(tmp_path, monkeypatch, missing):
    import json

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    path = {
        "prediction": module.SOURCE + "/held-out-record-predictions.csv",
        "last_original_raw": module.ORIGINAL_RAW + "03-augmented.nc",
        "one_node": module.STORE + "/repeat-node-16.loglikelihood.npz",
    }[missing]
    review = tmp_path / module.REVIEW
    item = json.loads(review.read_text())
    item["files"].pop(path)
    write_json(review, item)

    def forbidden(*args):
        raise AssertionError("native loader must remain unopened")

    monkeypatch.setattr(module, "load_lanes", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


def test_wrong_prediction_hash_rejects_before_native_loader(tmp_path, monkeypatch):
    import json

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    review = tmp_path / module.REVIEW
    item = json.loads(review.read_text())
    item["files"][module.SOURCE + "/held-out-record-predictions.csv"] = "0" * 64
    write_json(review, item)

    def forbidden(*args):
        raise AssertionError("native loader must remain unopened")

    monkeypatch.setattr(module, "load_lanes", forbidden)
    with pytest.raises(ValueError, match="evidence changed"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


@pytest.mark.parametrize(
    "change", ["training_sha", "event_order", "training_row_order", "influence_shape"]
)
def test_wrong_original_training_or_event_alignment_cannot_resolve(tmp_path, monkeypatch, change):
    import json

    import numpy as np

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    if change == "training_sha":
        path = tmp_path / module.OUTPUT / "primary-path-result.json"
        item = json.loads(path.read_text())
        item["source_training_posterior_sha"] = "f" * 64
        write_json(path, item)
    elif change == "event_order":
        path = tmp_path / module.SOURCE / "result.json"
        item = json.loads(path.read_text())
        item["events"][1:] = item["events"][1:][::-1]
        write_json(path, item)
    elif change == "training_row_order":
        path = tmp_path / module.SOURCE / "ensembles/00-training/membership.json"
        item = json.loads(path.read_text())
        item["included"][0:2] = item["included"][0:2][::-1]
        write_json(path, item)
    else:
        path = tmp_path / module.STORE / "primary-combined-influences.npz"
        with np.load(path) as raw:
            item = {name: raw[name] for name in raw.files}
        item["node_0"] = item["node_0"][:, :-1]
        np.savez_compressed(path, **item)
    refresh_proofs(tmp_path, module)
    with pytest.raises(ValueError, match="training draws|ordering|augmentation identity|alignment"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


def test_empty_invocation_receipts_cannot_fake_full_timing_closure(tmp_path, monkeypatch):
    import json

    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    path = tmp_path / module.OUTPUT / "invocations/000.json"
    item = json.loads(path.read_text())
    item["attempt_receipts"] = {}
    write_json(path, item)
    refresh_proofs(tmp_path, module)
    with pytest.raises(ValueError, match="per-invocation"):
        module.write_resolution(tmp_path, tmp_path / module.OUTPUT / "resolved-fold-v1")


def test_output_cannot_escape_counted_store_or_overwrite(tmp_path, monkeypatch):
    module, _ = synthetic_bundle(tmp_path, monkeypatch)
    for output in [tmp_path / "outside", tmp_path / module.OUTPUT]:
        with pytest.raises(ValueError, match="new resolution output"):
            module.write_resolution(tmp_path, output)
