"""A finite repair conserves calls and combines independently estimated event scores."""

# pyright: basic
import copy
import json

import numpy as np
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_curvature_precision import GATE, admit, combine, job
from scripts import run_arrival_curvature_precision as controller


def original():
    events = []
    for event, n, value, error in [("usc000phx5", 3, -5.0, 0.001), ("usc000piqj", 1, -19.0, 0.008)]:
        events.append(
            {
                "event_id": event,
                "sequence": job()["sequence"],
                "records": n,
                "joint_log_predictive": n * value,
                "normalized_event_score": value,
                "normalized_mcse": error,
                "overlap": 0.8,
                "precision_passed": event != "usc000piqj",
            }
        )
    return {
        "job": {"id": "fold-008"},
        "status": "precision_failure",
        "prediction_precision_passed": True,
        "events": events,
        "fold_score": {"mcse_equal_event_score": 0.1},
        "observation_measure": "native_minutes_Jacobian_already_applied_once",
    }


def replacement():
    return {
        "event_id": "usc000piqj",
        "sequence": job()["sequence"],
        "records": 1,
        "joint_log_predictive": -18.99,
        "normalized_event_score": -18.99,
        "normalized_mcse": 0.004,
        "overlap": 0.8,
        "precision_passed": True,
    }


def test_independent_new_training_and_retained_event_errors_add_before_event_average():
    old = original()
    before = copy.deepcopy(old)
    out = combine(old, replacement())
    assert old == before and out["job"] == old["job"]
    assert out["events"][0] == old["events"][0]
    assert out["fold_score"]["equal_event_score"] == pytest.approx((-5.0 - 18.99) / 2)
    assert out["fold_score"]["mcse_equal_event_score"] == pytest.approx(
        np.sqrt(0.001**2 + 0.004**2) / 2
    )
    assert out["observation_measure"] == "native_minutes_Jacobian_already_applied_once"


@pytest.mark.parametrize(
    "change",
    ["bad_mcse", "wrong_event", "wrong_sequence", "wrong_membership", "bad_units", "disagreement"],
)
def test_invalid_replacement_is_retained_but_cannot_resolve_fold(change):
    new = replacement()
    if change == "bad_mcse":
        new["normalized_mcse"] = 0.006
    elif change == "wrong_event":
        new["event_id"] = "other"
    elif change == "wrong_sequence":
        new["sequence"] = "other"
    elif change == "wrong_membership":
        new["records"] = 2
    elif change == "bad_units":
        new["joint_log_predictive"] *= 2
    else:
        new["normalized_event_score"] = new["joint_log_predictive"] = -18.0
    with pytest.raises(ValueError):
        combine(original(), new)


def test_incomplete_design_fails_before_loading_any_outcomes(tmp_path, monkeypatch):
    write_json(tmp_path / GATE, {"status": "prepared"})
    monkeypatch.setattr(
        "analysis.arrival.model_curvature_precision.load_lanes",
        lambda root: pytest.fail("must not parse outcomes"),
    )
    with pytest.raises(ValueError, match="independently"):
        admit(tmp_path)


def prepare(root, monkeypatch):
    state = {
        "status": "cv_needs_review",
        "next_fold": 8,
        "calls_charged": 51,
        "calls_started": 51,
        "current": None,
        "accepted": [{"case_id": f"old-{j}"} for j in range(7)],
        "path_amendment": {"kept": 32},
        "continuation": {"kept": True},
    }
    (root / controller.PARENT_OUTPUT).mkdir(parents=True, exist_ok=True)
    write_json(root / controller.STATE, state)
    gate = {
        "resources": controller.resources(),
        "output": controller.OUTPUT,
        "store": controller.STORE,
    }
    monkeypatch.setattr(controller, "admit", lambda root: (gate, {}, original()))
    monkeypatch.setattr(controller, "conserved_parent", lambda *args: None)
    monkeypatch.setattr(controller, "parent_floors", lambda *args: [])
    monkeypatch.setattr(controller, "budget_failure", lambda *args: None)
    monkeypatch.setattr(controller, "working_bytes", lambda *args: 0)
    monkeypatch.setattr(controller, "git_sha", lambda *args: "git")
    return state


@pytest.mark.parametrize("outcome", ["success", "failure", "corrupt"])
def test_two_calls_reserved_once_and_failed_partials_remain_without_retry(
    tmp_path, monkeypatch, outcome
):
    initial = prepare(tmp_path, monkeypatch)

    def worker(command, *, log, stop, timeout):
        on_dispatch = json.loads((tmp_path / controller.STATE).read_text())
        assert on_dispatch["calls_charged"] == 53 and on_dispatch["calls_started"] == 51
        assert timeout == 1200
        folder = tmp_path / controller.OUTPUT
        raw = tmp_path / controller.STORE
        raw.mkdir(parents=True)
        (raw / "partial.nc").write_bytes(b"retained")
        for k in range(2 if outcome != "failure" else 1):
            write_json(
                folder / "sampling-starts" / f"{k:02d}.json",
                {
                    **job(),
                    "phase": "training" if k == 0 else "augmented",
                    "event": None if k == 0 else job()["event"],
                    "seed": job()["seed"] + k,
                },
            )
        if outcome == "success":
            write_json(
                folder / "result.json",
                {
                    "status": "computed_pending_review",
                    "job": original()["job"],
                    "precision_job": job(),
                    "score_precision_passed": True,
                },
            )
        elif outcome == "corrupt":
            (folder / "result.json").write_text("{")
        log.write_text("worker log")
        return {"returncode": 0 if outcome != "failure" else 2, "reason": "worker_exit"}

    monkeypatch.setattr(controller, "supervise", worker)
    if outcome == "success":
        controller.run(tmp_path)
    else:
        with pytest.raises(SystemExit):
            controller.run(tmp_path)
    state = json.loads((tmp_path / controller.STATE).read_text())
    assert state["calls_charged"] == 53
    assert state["calls_started"] == (52 if outcome == "failure" else 53)
    assert state["current"] is None
    assert state["path_amendment"] == initial["path_amendment"]
    assert state["continuation"] == initial["continuation"]
    assert state["accepted"] == initial["accepted"]
    assert (tmp_path / controller.STORE / "partial.nc").read_bytes() == b"retained"
    assert (tmp_path / controller.OUTPUT / "attempt-evidence.json").exists()
    monkeypatch.setattr(
        controller,
        "conserved_parent",
        lambda *args: (_ for _ in ()).throw(ValueError("no retries")),
    )
    with pytest.raises(ValueError):
        controller.run(tmp_path)
    assert json.loads((tmp_path / controller.STATE).read_text()) == state


def test_existing_stop_or_existing_sidecar_dispatches_nothing(tmp_path, monkeypatch):
    initial = prepare(tmp_path, monkeypatch)
    stop = tmp_path / controller.PARENT_OUTPUT / "STOP"
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("stop")
    monkeypatch.setattr(
        controller, "supervise", lambda *args, **kw: pytest.fail("must not dispatch")
    )
    with pytest.raises(ValueError, match="STOP"):
        controller.run(tmp_path)
    assert json.loads((tmp_path / controller.STATE).read_text()) == initial
    stop.unlink()
    allocation = (tmp_path / controller.OUTPUT).with_name("fold-008-precision-v1-allocation.json")
    write_json(allocation, {"partial": "retained"})
    with pytest.raises(ValueError, match="overwrite"):
        controller.run(tmp_path)
    assert json.loads((tmp_path / controller.STATE).read_text()) == initial


@pytest.mark.parametrize("fault", [None, "native_mismatch", "draw_shape", "diagnostic"])
def test_worker_selects_only_train_and_lata_and_reuses_original_predictions(
    tmp_path, monkeypatch, fault
):
    from types import SimpleNamespace

    import xarray as xr

    from analysis.arrival import model_curvature_precision as worker
    from analysis.arrival.evidence import sha256

    train = np.arange(1060)
    held = np.arange(1060, 1064)
    names = [f"r-{i}" for i in range(1064)]
    events = ["train"] * 1060 + ["usc000phx5"] * 3 + ["usc000piqj"]
    lane = SimpleNamespace(
        record_ids=names,
        event_ids=events,
        y=np.full(1064, 70.0),
        response=np.zeros(1064),
        distance_km=np.full(1064, 1000.0),
    )
    old = original()
    write_json(tmp_path / worker.SOURCE / "result.json", old)
    prediction = tmp_path / worker.SOURCE / "held-out-record-predictions.csv"
    prediction.write_text("original four predictions")
    write_json(
        tmp_path / worker.SOURCE / "membership.json", {"train": names[:1060], "test": names[1060:]}
    )
    pins = {str(p.relative_to(tmp_path)): sha256(p) for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(worker, "admit", lambda root: ({}, pins, old))
    monkeypatch.setattr(worker, "load_lanes", lambda root: ({"NCEI-native-duration": lane}, {}))

    def indices(lane, sequence, phase, event):
        assert sequence == job()["sequence"]
        assert event in {None, "usc000piqj"}
        return (train if phase == "training" else np.r_[train, 1063]), SimpleNamespace(test=held)

    monkeypatch.setattr(worker, "bridge_indices", indices)
    calls = []

    def sample(root, spec, ids, lane, frozen, output, store, source_pins):
        calls.append((dict(spec), ids.copy()))
        output.mkdir(parents=True)
        store.parent.mkdir(parents=True, exist_ok=True)
        native = lane.y[ids].copy()
        if fault == "native_mismatch":
            native[0] += 1
        observed = xr.DataTree(
            xr.Dataset(
                {"response": ("record", lane.response[ids]), "native_minutes": ("record", native)},
                coords={"record": [names[int(i)] for i in ids]},
            )
        )
        tree = xr.DataTree()
        tree["observed_data"] = observed
        tree.to_netcdf(store)
        tree.close()
        draws = 7999 if fault == "draw_shape" else 8000
        post = xr.Dataset(
            {
                "sigma_anchor": (("chain", "draw", "scale_anchor_km"), np.full((4, draws, 3), 0.4)),
                "tau_event": (("chain", "draw"), np.full((4, draws), 0.1)),
            },
            coords={"scale_anchor_km": [500.0, 2000.0, 5000.0]},
        )
        return {
            "diagnostics": {"screen_passed": fault != "diagnostic"},
            "posterior": str(store.relative_to(root)),
            "posterior_sha256": sha256(store),
        }, post

    monkeypatch.setattr(worker, "sample_ensemble", sample)
    monkeypatch.setattr(worker, "read_curvature_prior", lambda *args: {})
    monkeypatch.setattr(worker, "curvature_kernel", lambda *args: None)
    monkeypatch.setattr(
        worker, "native_event_logpdf", lambda kernel, v, *args: np.full(len(v), -19.0)
    )
    if fault == "diagnostic":
        worker.run(tmp_path)
        assert len(calls) == 1
        assert (
            json.loads((tmp_path / worker.OUTPUT / "result.json").read_text())["status"]
            == "diagnostic_failure"
        )
        return
    if fault:
        with pytest.raises((ValueError, AssertionError)):
            worker.run(tmp_path)
        assert not (tmp_path / worker.OUTPUT / "result.json").exists()
        return
    worker.run(tmp_path)
    assert len(calls) == 2
    assert [s["seed"] for s, _ in calls] == [2866118800, 2866118801]
    assert all(s["draws"] == 8000 and s["tune"] == 2000 for s, _ in calls)
    np.testing.assert_array_equal(calls[0][1], train)
    np.testing.assert_array_equal(calls[1][1], np.r_[train, 1063])
    result = json.loads((tmp_path / worker.OUTPUT / "result.json").read_text())
    assert result["status"] == "computed_pending_review"
    assert result["job"] == old["job"] and result["precision_job"] == job()
    assert result["training_only_predictions_sha256"] == sha256(prediction)
    assert prediction.read_text() == "original four predictions"
    assert json.loads((tmp_path / worker.SOURCE / "result.json").read_text()) == old


@pytest.mark.parametrize(
    "missing", ["result.json", "membership.json", "held-out-record-predictions.csv", "raw"]
)
def test_missing_original_science_pin_fails_before_source_values_or_outcomes(
    tmp_path, monkeypatch, missing
):
    from analysis.arrival import model_curvature_precision as module
    from analysis.arrival.evidence import sha256

    files = {}
    for relative in [
        *module.CODE,
        *module.RUNTIME,
        module.CONTRACT,
        module.SOURCE + "/attempt-evidence.json",
        module.SOURCE + "/result.json",
        module.SOURCE + "/membership.json",
        module.SOURCE + "/held-out-record-predictions.csv",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "must not parse original values" if relative.endswith("result.json") else "source"
        )
        if relative.endswith("attempt-evidence.json"):
            write_json(path, {"files": {"reviewed.py": "placeholder"}})
        files[relative] = sha256(path)
    (tmp_path / "reviewed.py").write_text("source")
    files["reviewed.py"] = sha256(tmp_path / "reviewed.py")
    write_json(
        tmp_path / module.SOURCE / "attempt-evidence.json",
        {"files": {"reviewed.py": files["reviewed.py"]}},
    )
    files[module.SOURCE + "/attempt-evidence.json"] = sha256(
        tmp_path / module.SOURCE / "attempt-evidence.json"
    )
    write_json(
        tmp_path / module.STOP_REVIEW,
        {
            "status": "accepted_curvature_continuation_precision_stop",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {"reviewed.py": files["reviewed.py"]},
        },
    )
    files[module.STOP_REVIEW] = sha256(tmp_path / module.STOP_REVIEW)
    if missing != "raw":
        del files[module.SOURCE + "/" + missing]
    write_json(
        tmp_path / module.GATE,
        {
            "status": "accepted_lata_precision_supplement",
            "independent_checker": True,
            "job": job(),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": files,
        },
    )
    monkeypatch.setattr(module, "load_lanes", lambda *args: pytest.fail("must not load outcomes"))
    monkeypatch.setattr(
        module, "original_gate", lambda *args: pytest.fail("must not parse old result")
    )
    with pytest.raises(ValueError):
        module.admit(tmp_path)


def test_job_storage_and_deleted_parent_floor_trip_without_sampling(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "storage_failure", lambda *args: None)
    monkeypatch.setattr(controller, "working_bytes", lambda *args: 0)
    monkeypatch.setattr(controller, "parent_floors", lambda *args: [])
    file = tmp_path / controller.STORE / "large.nc"
    file.parent.mkdir(parents=True)
    with file.open("wb") as stream:
        stream.truncate(32 * 1024**2 + 1)
    assert controller.budget_failure(tmp_path, [], {}) == "precision_job_storage"
    file.unlink()
    monkeypatch.setattr(
        controller, "parent_floors", lambda *args: (_ for _ in ()).throw(ValueError("deleted"))
    )
    assert controller.budget_failure(tmp_path, [], {}) == "parent_floor_failure"


def test_finalization_storage_overshoot_cannot_retain_success(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)

    def budget(*args):
        return (
            "late_overshoot"
            if (tmp_path / controller.OUTPUT / "run-summary.json").exists()
            else None
        )

    monkeypatch.setattr(controller, "budget_failure", budget)

    def worker(command, *, log, stop, timeout):
        folder = tmp_path / controller.OUTPUT
        for k in range(2):
            write_json(
                folder / "sampling-starts" / f"{k:02d}.json",
                {
                    **job(),
                    "phase": "training" if k == 0 else "augmented",
                    "event": None if k == 0 else job()["event"],
                    "seed": job()["seed"] + k,
                },
            )
        write_json(
            folder / "result.json",
            {
                "status": "computed_pending_review",
                "job": original()["job"],
                "precision_job": job(),
                "score_precision_passed": True,
            },
        )
        log.write_text("log")
        return {"returncode": 0, "reason": "worker_exit"}

    monkeypatch.setattr(controller, "supervise", worker)
    with pytest.raises(SystemExit):
        controller.run(tmp_path)
    state = json.loads((tmp_path / controller.STATE).read_text())
    assert (
        state["status"] == "precision_needs_review"
        and state["calls_charged"] == state["calls_started"] == 53
    )
    assert (
        json.loads((tmp_path / controller.OUTPUT / "run-summary.json").read_text())["status"]
        == "precision_needs_review"
    )
    manifest = tmp_path / controller.OUTPUT / "attempt-evidence.json"
    assert json.loads(manifest.read_text())["outcome"] == "failed_retained"
    from analysis.arrival.evidence import sha256

    assert sha256(manifest) == state["precision_amendment"]["receipt_sha256"]


def test_private_resolution_pointer_cannot_drift_from_pinned_public_plan(tmp_path):
    from analysis.arrival.evidence import sha256

    public = controller.PARENT_OUTPUT + "/continuation-v1/plan.json"
    original_plan = controller.PARENT_OUTPUT + "/plan.json"
    rehearsal = controller.PARENT_OUTPUT + "/continuation-v1/rehearsal-review-acceptance.json"
    write_json(tmp_path / public, {"resolutions": {"fold-002": {"result": "accepted-result.json"}}})
    write_json(tmp_path / original_plan, {})
    write_json(tmp_path / rehearsal, {})
    pins = {p: sha256(tmp_path / p) for p in [public, original_plan, rehearsal]}
    state = {
        "status": "cv_needs_review",
        "current": None,
        "next_fold": 8,
        "accepted": [{}] * 7,
        "calls_charged": 51,
        "calls_started": 51,
        "plan_sha256": pins[original_plan],
        "continuation": {
            "plan_sha256": pins[public],
            "rehearsal_sha256": pins[rehearsal],
            "resolutions": {"fold-002": {"result": "foreign-result.json"}},
        },
    }
    with pytest.raises(ValueError, match="accepted resolution registry"):
        controller.conserved_parent(tmp_path, state, pins)


@pytest.mark.parametrize("change", [None, "files", "original_receipt", "charged_slots"])
def test_every_inherited_direct_attempt_is_bound_to_public_evidence(tmp_path, monkeypatch, change):
    from analysis.arrival.evidence import sha256

    cases = [{"id": f"fold-{j:03d}"} for j in range(29)]
    members = {c["id"]: {"charged_call_slots": 3 if c["id"] == "fold-008" else 2} for c in cases}
    plan = controller.PARENT_OUTPUT + "/plan.json"
    cont = controller.PARENT_OUTPUT + "/continuation-v1/plan.json"
    first = controller.PARENT_OUTPUT + "/continuation-v1/rehearsal-review-acceptance.json"
    resolutions = {"fold-002": {"result": "accepted-result.json"}}
    write_json(tmp_path / plan, {"cases": cases, "memberships": members})
    write_json(tmp_path / cont, {"resolutions": resolutions})
    write_json(tmp_path / first, {})
    source = tmp_path / "source.py"
    source.write_text("source")
    files = {"source.py": sha256(source)}
    pins = {**files, **{p: sha256(tmp_path / p) for p in [plan, cont, first]}}
    accepted = []
    attempts = []
    for j in [0, 1, 3, 4, 5, 6, 7, 8]:
        case = f"fold-{j:03d}"
        receipt = controller.PARENT_OUTPUT + "/jobs/" + case + "/attempt-evidence.json"
        write_json(tmp_path / receipt, {"case_id": case, "files": files})
        pins[receipt] = sha256(tmp_path / receipt)
        if j < 8:
            accepted.append(
                {
                    "case_id": case,
                    "charged_slots": 2,
                    "files": dict(files),
                    "receipt": receipt,
                    "receipt_sha256": pins[receipt],
                }
            )
        if j >= 3:
            attempts.append(
                {
                    "case_id": case,
                    "cost": 3 if j == 8 else 2,
                    "started": 3 if j == 8 else 2,
                    "outcome": "precision_failure" if j == 8 else "accepted",
                    "receipt": receipt,
                    "receipt_sha256": pins[receipt],
                }
            )
    state = {
        "status": "cv_needs_review",
        "current": None,
        "next_fold": 8,
        "accepted": accepted,
        "calls_charged": 51,
        "calls_started": 51,
        "plan_sha256": pins[plan],
        "continuation": {
            "plan_sha256": pins[cont],
            "rehearsal_sha256": pins[first],
            "resolutions": resolutions,
            "attempts": attempts,
        },
    }
    (tmp_path / controller.PARENT_STORE).mkdir(parents=True)
    monkeypatch.setattr(controller, "validate_inherited_path", lambda *args: None)
    if change == "files":
        state["accepted"][0]["files"] = {}
    elif change == "original_receipt":
        state["accepted"][0]["receipt"] = "foreign.json"
    elif change == "charged_slots":
        state["accepted"][0]["charged_slots"] = 0
    if change:
        with pytest.raises(ValueError, match="accepted"):
            controller.conserved_parent(tmp_path, state, pins)
    else:
        controller.conserved_parent(tmp_path, state, pins)
