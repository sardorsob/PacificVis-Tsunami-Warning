"""A reviewed resolution counts logically, while every inherited sampler slot persists."""

# pyright: basic
import json
from copy import deepcopy
from typing import Any

import pytest

from scripts.run_arrival_curvature_final_continuation import validate_logical_prefix


def fixture():
    cases = [{"id": f"fold-{j:03d}"} for j in range(23)]
    memberships = {
        c["id"]: {"charged_call_slots": 3 if j == 22 else 2} for j, c in enumerate(cases)
    }
    resolution = {
        f"fold-{j:03d}": {"receipt": f"review{j}.json", "receipt_sha256": "a" * 64}
        for j in [2, 8, 19]
    }
    state = {
        "next_fold": 23,
        "calls_charged": 116,
        "calls_started": 116,
        "accepted": [{"case_id": f"fold-{j:03d}"} for j in range(23) if j not in [2, 8, 19]],
        "final_continuation": {
            "resolutions": resolution,
            "attempts": [
                {
                    "case_id": f"fold-{j:03d}",
                    "cost": 3 if j == 22 else 2,
                    "started": 3 if j == 22 else 2,
                    "outcome": "accepted",
                }
                for j in range(20, 23)
            ],
        },
    }
    return state, cases, memberships, resolution


def test_logical_prefix_keeps_resolved_fold_and_all109_inherited_slots():
    state, cases, memberships, resolution = fixture()
    original = deepcopy(state)
    validate_logical_prefix(state, cases, memberships, resolution)
    assert state == original


@pytest.mark.parametrize(
    "change",
    [
        "refund_parent",
        "omit_direct",
        "omit_resolution",
        "wrong_sequence",
        "wrong_cost",
        "missing_starts",
    ],
)
def test_no_resolution_hole_refund_or_omitted_attempt_can_admit_resume(change):
    s, c, m, r = fixture()
    if change == "refund_parent":
        s["calls_charged"] = 10
    elif change == "omit_direct":
        s["accepted"].pop()
    elif change == "omit_resolution":
        s["final_continuation"]["resolutions"] = {}
    elif change == "wrong_sequence":
        s["final_continuation"]["attempts"][0]["case_id"] = "fold-021"
    elif change == "wrong_cost":
        s["final_continuation"]["attempts"][1]["cost"] = 3
    else:
        s["calls_started"] = 43
    with pytest.raises(ValueError):
        validate_logical_prefix(s, c, m, r)


def runtime_fixture(root, monkeypatch, *, failure=None):
    import json
    from pathlib import Path

    from analysis.arrival.evidence import sha256, write_json
    from scripts import run_arrival_curvature_final_continuation as runner

    cases = [
        {
            "id": f"fold-{j:03d}",
            "sequence": f"seq-{j}",
            "target": "NCEI-native-duration",
            "kind": "mean-curvature",
            "prior": "base",
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": 2856110800 + 1000 * j,
        }
        for j in range(29)
    ]
    memberships = {
        c["id"]: {"charged_call_slots": 3 if j == 27 else 2} for j, c in enumerate(cases)
    }
    source = root / "stub"
    source.write_text("frozen")
    old_summary = runner.previous.CONTINUATION + "/run-summary.json"
    write_json(root / old_summary, {"status": "original_overlap_stop", "calls_charged": 77})
    pins = {"stub": sha256(source), old_summary: sha256(root / old_summary)}
    resolutions = {
        "fold-002": {"receipt": "review2.json", "receipt_sha256": "a" * 64},
        "fold-008": {"receipt": "review8.json", "receipt_sha256": "b" * 64},
        "fold-019": {"receipt": "review19.json", "receipt_sha256": "c" * 64},
    }
    (root / runner.STORE).mkdir(parents=True)
    write_json(
        root / runner.OUTPUT / "plan.json",
        {"files": pins, "cases": cases, "memberships": memberships},
    )
    state = {
        "next_fold": 19,
        "calls_charged": 109,
        "calls_started": 109,
        "current": None,
        "status": "path_computations_complete",
        "plan_sha256": sha256(root / runner.OUTPUT / "plan.json"),
        "rehearsal_sha256": "original-review",
        "accepted": [
            {"case_id": f"fold-{j:03d}", "files": {}} for j in range(19) if j not in [2, 8]
        ],
        **{name: {"preserved": name} for name in runner.LEDGERS},
    }
    write_json(root / runner.STATE, state)
    design = {
        "files": pins,
        "cases": cases,
        "memberships": memberships,
        "parents": [],
        "worker_pins": pins,
        "resolutions": resolutions,
        "oldplan": {},
        "gate": {},
    }
    monkeypatch.setattr(runner, "admit_continuation", lambda *a: design)
    monkeypatch.setattr(runner, "parent_floors", lambda *a: [])
    monkeypatch.setattr(runner.previous, "storage_failure", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "validate_inherited_path", lambda *a: None)
    monkeypatch.setattr(runner, "verify_rehearsal", lambda *a: "original-review")
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda *a: None)
    monkeypatch.setattr(runner, "git_sha", lambda *a: "fixture-git")

    def case_artifacts(_root, case, member, worker_pins, accepted=None):
        folder = root / runner.OUTPUT / "jobs" / case["id"]
        raw = root / runner.STORE / case["id"]
        manifest = folder / "attempt-evidence.json"
        if case in cases[:19]:
            return {}, manifest
        files = {
            str(p.relative_to(root)): sha256(p)
            for base in [folder, raw]
            for p in base.rglob("*")
            if p.is_file() and p != manifest
        }
        for p in [
            folder.with_name(case["id"] + "-spec.json"),
            folder.with_suffix(".log"),
            folder.with_suffix(".supervisor.json"),
        ]:
            files[str(p.relative_to(root))] = sha256(p)
        if accepted is not None:
            assert accepted["files"] == files
            assert accepted["receipt_sha256"] == sha256(manifest)
            assert json.loads(manifest.read_text()) == {"case_id": case["id"], "files": files}
        return files, manifest

    monkeypatch.setattr(runner, "case_artifacts", case_artifacts)
    calls = []

    def supervise(command, log, stop, timeout):
        calls.append(command)
        spec = Path(command[command.index("--job") + 1])
        case = json.loads(spec.read_text())
        folder = Path(command[command.index("--output") + 1])
        raw = Path(command[command.index("--store") + 1])
        folder.mkdir(parents=True)
        raw.mkdir(parents=True)
        (raw / "posterior.nc").write_bytes(b"posterior")
        for j in range(memberships[case["id"]]["charged_call_slots"]):
            write_json(folder / "sampling-starts" / f"{j:02d}.json", {"slot": j})
        log.write_text("worker")
        write_json(folder / "job.json", case)
        if failure == "corrupt":
            (folder / "result.json").write_text("{")
        else:
            write_json(
                folder / "result.json",
                {
                    "job": case,
                    "status": "precision_failure" if failure else "computed_pending_review",
                },
            )
        return {"returncode": 0, "reason": "worker_exit", "elapsed_seconds": 0.01}

    monkeypatch.setattr(runner, "supervise", supervise)
    return runner, calls


def accept_first(root, runner):
    import json

    from analysis.arrival.evidence import sha256, write_json

    state = json.loads((root / runner.STATE).read_text())
    first = state["accepted"][17]
    write_json(
        root / runner.REHEARSAL,
        {
            "status": "accepted_first_curvature_final_continuation_fold",
            "independent_checker": True,
            "files": {
                **first["files"],
                first["receipt"]: first["receipt_sha256"],
                runner.CONTINUATION + "/plan.json": sha256(
                    root / runner.CONTINUATION / "plan.json"
                ),
            },
        },
    )


def test_runtime_requires_first_review_then_conserves_all128_slots_to_completion(
    tmp_path, monkeypatch
):
    import json

    from analysis.arrival.evidence import sha256

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    old_summary = tmp_path / r.previous.CONTINUATION / "run-summary.json"
    old_summary_sha = sha256(old_summary)
    r.run(tmp_path, max_folds=1)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (111, 111, 21)
    assert all(s[name] == {"preserved": name} for name in r.LEDGERS)
    with pytest.raises(ValueError, match="independently reviewed first"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1
    accept_first(tmp_path, r)
    for _ in range(3):
        r.run(tmp_path, resume=True, max_folds=3)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert s["status"] == "cv_computations_complete"
    assert len(s["accepted"]) == 26 and len(s["final_continuation"]["resolutions"]) == 3
    assert sha256(old_summary) == old_summary_sha
    assert (
        s["calls_charged"] == s["calls_started"] == 128 and s["next_fold"] == 29 and len(calls) == 9
    )
    summary = tmp_path / r.CONTINUATION / "run-summary.json"
    digest = sha256(summary)
    r.run(tmp_path, resume=True, max_folds=3)
    assert sha256(summary) == digest and len(calls) == 9


@pytest.mark.parametrize("failure", ["precision", "corrupt"])
def test_runtime_failure_retains_charged_attempt_and_refuses_automatic_resume(
    tmp_path, monkeypatch, failure
):
    import json

    r, calls = runtime_fixture(tmp_path, monkeypatch, failure=failure)
    with pytest.raises(SystemExit):
        r.run(tmp_path, max_folds=1)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (111, 111, 20)
    assert (
        s["status"] == "cv_needs_review" and (tmp_path / r.STORE / "fold-020/posterior.nc").exists()
    )
    assert (tmp_path / r.OUTPUT / "jobs/fold-020/attempt-evidence.json").exists()
    with pytest.raises(ValueError, match="requires reviewed reconciliation"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1


def test_unknown_raw_partial_blocks_terminal_or_new_dispatch(tmp_path, monkeypatch):
    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    (tmp_path / r.STORE / "unreviewed.nc").write_bytes(b"partial")
    with pytest.raises(ValueError, match="unexpected raw"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1


def test_initial_batch_cannot_skip_the_single_fold_rehearsal(tmp_path):
    from scripts import run_arrival_curvature_final_continuation as r

    with pytest.raises(ValueError, match="initial invocation"):
        r.run(tmp_path, max_folds=3)


def test_unaccepted_continuation_gate_blocks_outcome_loading(tmp_path, monkeypatch):
    from analysis.arrival.evidence import write_json
    from scripts import run_arrival_curvature_final_continuation as r

    write_json(tmp_path / r.GATE, {"status": "pending", "files": {}})

    def forbidden(*args):
        raise AssertionError("native outcomes remain unopened")

    monkeypatch.setattr(r.previous, "admit_continuation", forbidden)
    with pytest.raises(ValueError, match="complete independent"):
        r.admit_continuation(tmp_path)


def test_refunded_private_counter_is_rejected_before_another_sampler(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import write_json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    p = tmp_path / r.STATE
    s = json.loads(p.read_text())
    s["calls_charged"] = 109
    write_json(p, s)
    with pytest.raises(ValueError, match="109inherited"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1


def test_copied_path_identity_cannot_be_admitted_by_rehashing_private_plan(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import sha256, write_json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    plan = tmp_path / r.CONTINUATION / "plan.json"
    s = json.loads(plan.read_text())
    s["path_bindings"] = {"copied": True}
    write_json(plan, s)
    p = tmp_path / r.STATE
    s = json.loads(p.read_text())
    s["final_continuation"]["plan_sha256"] = sha256(plan)
    write_json(p, s)
    with pytest.raises(ValueError, match="requires reviewed reconciliation"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1


def test_terminal_validation_rejects_a_new_raw_partial_without_rewriting_summary(
    tmp_path, monkeypatch
):
    from analysis.arrival.evidence import sha256

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    for _ in range(3):
        r.run(tmp_path, resume=True, max_folds=3)
    summary = tmp_path / r.CONTINUATION / "run-summary.json"
    digest = sha256(summary)
    (tmp_path / r.STORE / "extra.nc").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="unexpected raw"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert sha256(summary) == digest and len(calls) == 9


def test_terminal_validation_preserves_first_continuation_review_identity(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import write_json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    for _ in range(3):
        r.run(tmp_path, resume=True, max_folds=3)
    p = tmp_path / r.REHEARSAL
    review = json.loads(p.read_text())
    review["changed_after_acceptance"] = True
    write_json(p, review)
    with pytest.raises(ValueError, match="review identity changed"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 9


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "path_amendment",
        "continuation",
        "precision_amendment",
        "completion",
        "sumatra_path_amendment",
    ],
)
def test_all_five_inherited_ledgers_remain_bound_to_accepted_gate(tmp_path, monkeypatch, changed):
    from analysis.arrival.evidence import sha256, write_json
    from scripts import run_arrival_curvature_final_continuation as runner

    jobs = runner.sumatra.path_jobs()
    part = {
        "next_node": 32,
        "attempts": [],
        "invocations": [],
        "aggregate_files": {},
        "plan_sha256": "p" * 64,
        "final_summary_sha256": "s" * 64,
    }
    pins = {
        runner.resolution_io.OUTPUT + "/plan.json": "p" * 64,
        runner.resolution_io.OUTPUT + "/run-summary.json": "s" * 64,
    }
    for job in jobs:
        receipt = runner.resolution_io.OUTPUT + "/jobs/" + job["id"] + "/attempt-evidence.json"
        write_json(tmp_path / receipt, {"job": job, "outcome": "accepted", "files": {}})
        pins[receipt] = sha256(tmp_path / receipt)
        part["attempts"].append(
            {
                "job": job,
                "outcome": "accepted",
                "files": {},
                "receipt": receipt,
                "receipt_sha256": pins[receipt],
            }
        )
    state: dict[str, Any] = {name: {"preserved": name} for name in runner.LEDGERS}
    state.update(sumatra_path_amendment=part, accepted=[{} for _ in range(17)])
    write_json(
        tmp_path / runner.GATE, {"inherited_ledger_sha256": runner.inherited_ledger_sha256(state)}
    )
    write_json(tmp_path / runner.sumatra.GATE, {})
    monkeypatch.setattr(runner.sumatra, "conserved_parent", lambda *a: None)
    monkeypatch.setattr(runner.sumatra, "attempt_files", lambda *a, **k: {})
    monkeypatch.setattr(runner.sumatra, "validate_timings", lambda *a: None)
    monkeypatch.setattr(runner.sumatra, "validate_aggregates", lambda *a: None)
    if changed:
        state[changed]["tampered"] = True
        with pytest.raises(ValueError, match="five inherited"):
            runner.validate_inherited_path(tmp_path, state, pins)
    else:
        runner.validate_inherited_path(tmp_path, state, pins)


def test_stop_before_first_completion_dispatch_preserves_parent(tmp_path, monkeypatch):

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    before = (tmp_path / r.STATE).read_bytes()
    (tmp_path / r.OUTPUT / "STOP").write_text("stop")
    with pytest.raises(ValueError, match="STOP present"):
        r.run(tmp_path, max_folds=1)
    assert (tmp_path / r.STATE).read_bytes() == before and calls == []
    assert not (tmp_path / r.CONTINUATION).exists()


def test_completion_summary_cannot_hide_late_storage_failure(tmp_path, monkeypatch):
    import json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    summary = tmp_path / r.CONTINUATION / "run-summary.json"
    monkeypatch.setattr(
        r, "storage_failure", lambda *args, **kw: "late_storage" if summary.exists() else None
    )
    with pytest.raises(SystemExit):
        r.run(tmp_path, max_folds=1)
    assert len(calls) == 1
    assert json.loads((tmp_path / r.STATE).read_text())["status"] == "cv_storage_failure"
    assert json.loads(summary.read_text())["status"] == "cv_storage_failure"


def admission_fixture(root, monkeypatch):
    """Future receipts contain synthetic metadata; no real posterior or outcome is read."""
    from analysis.arrival.evidence import sha256, write_json
    from scripts import run_arrival_curvature_final_continuation as r

    cases = [{"id": f"fold-{j:03d}"} for j in range(29)]
    memberships = {
        c["id"]: {"charged_call_slots": 3 if j == 27 else 2} for j, c in enumerate(cases)
    }
    required = {
        r.SELF,
        r.previous.GATE,
        r.sumatra.GATE,
        r.resolution_io.REVIEW,
        r.DERIVED_REVIEW,
        r.DERIVED + "/result.json",
        r.DERIVED + "/inputs.json",
        r.DERIVED + "/output-checksums.json",
        r.resolution_io.SOURCE + "/result.json",
        r.resolution_io.SOURCE + "/held-out-record-predictions.csv",
        "scripts/run_arrival_curvature_sumatra_path.py",
        *r.resolution_io.CODE,
        "path-proof.json",
        "old-proof.json",
        r.OUTPUT + "/plan.json",
        r.resolution_io.OUTPUT + "/primary-path-result.json",
    }
    for name in required:
        write_json(root / name, {})
    path_pins = {"path-proof.json": sha256(root / "path-proof.json")}
    prediction = r.resolution_io.SOURCE + "/held-out-record-predictions.csv"
    primary = r.resolution_io.OUTPUT + "/primary-path-result.json"
    source_result = r.resolution_io.SOURCE + "/result.json"
    write_json(root / source_result, {"job": cases[19], "status": "precision_failure"})
    write_json(
        root / r.DERIVED / "inputs.json",
        {
            "files": path_pins,
            "new_sampler_calls": 0,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        root / r.DERIVED / "result.json",
        {
            "job": cases[19],
            "status": "computed_pending_review",
            "score_precision_passed": True,
            "prediction_precision_passed": True,
            "observation_measure": "native_minutes_Jacobian_already_applied_once",
            "source_result": source_result,
            "source_result_sha256": sha256(root / source_result),
            "training_only_predictions": prediction,
            "training_only_predictions_sha256": sha256(root / prediction),
            "retained_direct_bridge_status": "precision_failure",
            "primary_path": primary,
            "primary_path_sha256": sha256(root / primary),
        },
    )
    write_json(
        root / r.DERIVED / "output-checksums.json",
        {name: sha256(root / r.DERIVED / name) for name in ["inputs.json", "result.json"]},
    )
    derived_result = r.DERIVED + "/result.json"
    write_json(
        root / r.DERIVED_REVIEW,
        {
            "status": "accepted_same_model_curvature_sumatra_fold_resolution",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "derived_result": derived_result,
            "derived_result_sha256": sha256(root / derived_result),
            "files": path_pins,
        },
    )
    pins = {name: sha256(root / name) for name in required}
    resolutions = {f"fold-{j:03d}": {"receipt": f"old-review-{j}"} for j in [2, 8]}
    design = {
        "files": {"old-proof.json": pins["old-proof.json"]},
        "cases": cases,
        "memberships": memberships,
        "worker_pins": {},
        "resolutions": resolutions,
    }
    new_resolutions = {
        **resolutions,
        "fold-019": {
            "receipt": r.DERIVED_REVIEW,
            "receipt_sha256": pins[r.DERIVED_REVIEW],
            "result": derived_result,
            "result_sha256": pins[derived_result],
            "prediction": prediction,
            "prediction_sha256": pins[prediction],
        },
    }
    gate: dict[str, Any] = {
        "status": "accepted_curvature_final_continuation_rehearsal",
        "independent_checker": True,
        "resources": r.resources(),
        "path_bindings": r.bindings(root, root / r.CONTINUATION, root / r.STORE, root / r.STATE),
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "files": pins,
        "resolutions": new_resolutions,
        "remaining_cases": cases[20:],
        "original_plan_sha256": pins[r.OUTPUT + "/plan.json"],
    }
    write_json(root / r.GATE, gate)
    monkeypatch.setattr(r.resolution_io, "verified_path", lambda *a: path_pins)
    loads = []

    def old_admission(*args):
        loads.append(True)
        return design

    monkeypatch.setattr(r.previous, "admit_continuation", old_admission)
    monkeypatch.setattr(r, "parent_floors", lambda *a: [])
    return r, gate, loads


def test_complete_future_three_resolution_metadata_admits_only_original_nine_cases(
    tmp_path, monkeypatch
):
    r, _, loads = admission_fixture(tmp_path, monkeypatch)
    design = r.admit_continuation(tmp_path)
    assert loads == [True]
    assert set(design["resolutions"]) == {"fold-002", "fold-008", "fold-019"}
    assert [c["id"] for c in design["cases"][20:]] == [f"fold-{j:03d}" for j in range(20, 29)]


@pytest.mark.parametrize(
    "change",
    [
        "path_reference",
        "derived_reference",
        "missing_path_review",
        "unaccepted_derived",
        "prediction_identity",
    ],
)
def test_incomplete_future_path_or_derived_proof_blocks_before_old_loader(
    tmp_path, monkeypatch, change
):
    from analysis.arrival.evidence import sha256, write_json

    r, gate, loads = admission_fixture(tmp_path, monkeypatch)
    if change == "path_reference":
        gate["files"].pop("path-proof.json")
    elif change == "derived_reference":
        review = json.loads((tmp_path / r.DERIVED_REVIEW).read_text())
        review["files"]["unreviewed.json"] = "a" * 64
        write_json(tmp_path / r.DERIVED_REVIEW, review)
        gate["files"][r.DERIVED_REVIEW] = sha256(tmp_path / r.DERIVED_REVIEW)
    elif change == "missing_path_review":
        gate["files"].pop(r.resolution_io.REVIEW)
    elif change == "unaccepted_derived":
        review = json.loads((tmp_path / r.DERIVED_REVIEW).read_text())
        review["status"] = "pending"
        write_json(tmp_path / r.DERIVED_REVIEW, review)
        gate["files"][r.DERIVED_REVIEW] = sha256(tmp_path / r.DERIVED_REVIEW)
    else:
        (tmp_path / r.resolution_io.SOURCE / "held-out-record-predictions.csv").write_text(
            "changed"
        )
    write_json(tmp_path / r.GATE, gate)
    with pytest.raises(ValueError):
        r.admit_continuation(tmp_path)
    assert loads == []


def test_absent_future_gate_prevents_private_state_and_outcome_loading(tmp_path, monkeypatch):
    from scripts import run_arrival_curvature_final_continuation as r

    monkeypatch.setattr(r.previous, "admit_continuation", lambda *a: pytest.fail("outcomes loaded"))
    with pytest.raises(ValueError, match="independently accepted"):
        r.run(tmp_path)
    assert not (tmp_path / r.STATE).exists()
    assert not (tmp_path / r.CONTINUATION).exists()


def test_final_resources_keep_global_ceiling_and_all_design_bytes(tmp_path, monkeypatch):
    from scripts import run_arrival_curvature_final_continuation as r

    resources = r.resources()
    assert resources["inherited_charged_slots"] == 109
    assert resources["max_sampler_call_slots"] == 248
    assert resources["global_max_bytes"] == 2048 * r.MIB
    assert resources["local_max_bytes"] == 1024 * r.MIB
    assert resources["cache_max_bytes"] == 256 * r.MIB
    assert resources["job_max_bytes"] == 32 * r.MIB
    assert resources["next_invocation_reserve_bytes"] == 608 * r.MIB
    assert resources["whole_fold_seconds"] == 1200 and resources["cores"] == 2
    monkeypatch.setattr(r, "parent_floors", lambda *a: [])
    monkeypatch.setattr(r.previous, "storage_failure", lambda *a, **kw: None)
    monkeypatch.setattr(r, "working_bytes", lambda *a: r.MAX_GLOBAL + 1)
    assert r.storage_failure(tmp_path, [], gate={}) == "final_continuation_global_storage"
