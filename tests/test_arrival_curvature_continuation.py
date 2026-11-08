"""A reviewed resolution counts logically, while every inherited sampler slot persists."""

# pyright: basic
from copy import deepcopy

import pytest

from scripts.run_arrival_curvature_continuation import validate_logical_prefix


def fixture():
    cases = [{"id": f"fold-{j:03d}"} for j in range(5)]
    memberships = {
        case["id"]: {"charged_call_slots": 4 if j == 4 else 2} for j, case in enumerate(cases)
    }
    resolution = {"fold-002": {"receipt": "review.json", "receipt_sha256": "a" * 64}}
    state = {
        "next_fold": 5,
        "calls_charged": 44,
        "calls_started": 44,
        "accepted": [{"case_id": f"fold-{j:03d}"} for j in [0, 1, 3, 4]],
        "continuation": {
            "resolutions": resolution,
            "attempts": [
                {"case_id": "fold-003", "cost": 2, "started": 2, "outcome": "accepted"},
                {"case_id": "fold-004", "cost": 4, "started": 4, "outcome": "accepted"},
            ],
        },
    }
    return state, cases, memberships, resolution


def test_logical_prefix_keeps_resolved_fold_and_all38_inherited_slots():
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
        s["continuation"]["resolutions"] = {}
    elif change == "wrong_sequence":
        s["continuation"]["attempts"][0]["case_id"] = "fold-004"
    elif change == "wrong_cost":
        s["continuation"]["attempts"][1]["cost"] = 2
    else:
        s["calls_started"] = 43
    with pytest.raises(ValueError):
        validate_logical_prefix(s, c, m, r)


def runtime_fixture(root, monkeypatch, *, failure=None):
    import json
    from pathlib import Path

    from analysis.arrival.evidence import sha256, write_json
    from scripts import run_arrival_curvature_continuation as runner

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
        c["id"]: {"charged_call_slots": 4 if j in [26, 27] else 2} for j, c in enumerate(cases)
    }
    source = root / "stub"
    source.write_text("frozen")
    pins = {"stub": sha256(source)}
    resolutions = {"fold-002": {"receipt": "review.json", "receipt_sha256": "a" * 64}}
    (root / runner.STORE).mkdir(parents=True)
    write_json(
        root / runner.OUTPUT / "plan.json",
        {"files": pins, "cases": cases, "memberships": memberships},
    )
    state = {
        "next_fold": 2,
        "calls_charged": 38,
        "calls_started": 38,
        "current": None,
        "status": "path_computations_complete",
        "plan_sha256": sha256(root / runner.OUTPUT / "plan.json"),
        "rehearsal_sha256": "original-review",
        "accepted": [{"case_id": f"fold-{j:03d}", "files": {}} for j in range(2)],
        "path_amendment": {"preserved": True},
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
    monkeypatch.setattr(runner, "validate_inherited_path", lambda *a: None)
    monkeypatch.setattr(runner, "verify_rehearsal", lambda *a: "original-review")
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda *a: None)
    monkeypatch.setattr(runner, "git_sha", lambda *a: "fixture-git")

    def case_artifacts(_root, case, member, worker_pins, accepted=None):
        folder = root / runner.OUTPUT / "jobs" / case["id"]
        raw = root / runner.STORE / case["id"]
        manifest = folder / "attempt-evidence.json"
        if case["id"] in ["fold-000", "fold-001"]:
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
    first = state["accepted"][2]
    write_json(
        root / runner.REHEARSAL,
        {
            "status": "accepted_first_curvature_continuation_fold",
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


def test_runtime_requires_first_review_then_conserves_all94_slots_to_completion(
    tmp_path, monkeypatch
):
    import json

    from analysis.arrival.evidence import sha256

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (40, 40, 4)
    assert s["path_amendment"] == {"preserved": True}
    with pytest.raises(ValueError, match="independently reviewed first"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 1
    accept_first(tmp_path, r)
    for _ in range(9):
        r.run(tmp_path, resume=True, max_folds=3)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert s["status"] == "cv_computations_complete"
    assert (
        s["calls_charged"] == s["calls_started"] == 94 and s["next_fold"] == 29 and len(calls) == 26
    )
    summary = tmp_path / r.CONTINUATION / "run-summary.json"
    digest = sha256(summary)
    r.run(tmp_path, resume=True, max_folds=3)
    assert sha256(summary) == digest and len(calls) == 26


@pytest.mark.parametrize("failure", ["precision", "corrupt"])
def test_runtime_failure_retains_charged_attempt_and_refuses_automatic_resume(
    tmp_path, monkeypatch, failure
):
    import json

    r, calls = runtime_fixture(tmp_path, monkeypatch, failure=failure)
    with pytest.raises(SystemExit):
        r.run(tmp_path, max_folds=1)
    s = json.loads((tmp_path / r.STATE).read_text())
    assert (s["calls_charged"], s["calls_started"], s["next_fold"]) == (40, 40, 3)
    assert (
        s["status"] == "cv_needs_review" and (tmp_path / r.STORE / "fold-003/posterior.nc").exists()
    )
    assert (tmp_path / r.OUTPUT / "jobs/fold-003/attempt-evidence.json").exists()
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
    from scripts import run_arrival_curvature_continuation as r

    with pytest.raises(ValueError, match="initial invocation"):
        r.run(tmp_path, max_folds=3)


def test_unaccepted_continuation_gate_blocks_outcome_loading(tmp_path, monkeypatch):
    from analysis.arrival.evidence import write_json
    from scripts import run_arrival_curvature_continuation as r

    write_json(tmp_path / r.GATE, {"status": "pending", "files": {}})

    def forbidden(*args):
        raise AssertionError("native outcomes remain unopened")

    monkeypatch.setattr(r, "make_design", forbidden)
    with pytest.raises(ValueError, match="complete independently"):
        r.admit_continuation(tmp_path)


def test_refunded_private_counter_is_rejected_before_another_sampler(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import write_json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    p = tmp_path / r.STATE
    s = json.loads(p.read_text())
    s["calls_charged"] = 38
    write_json(p, s)
    with pytest.raises(ValueError, match="38inherited"):
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
    s["continuation"]["plan_sha256"] = sha256(plan)
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
    for _ in range(9):
        r.run(tmp_path, resume=True, max_folds=3)
    summary = tmp_path / r.CONTINUATION / "run-summary.json"
    digest = sha256(summary)
    (tmp_path / r.STORE / "extra.nc").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="unexpected raw"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert sha256(summary) == digest and len(calls) == 26


def test_terminal_validation_preserves_first_continuation_review_identity(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import write_json

    r, calls = runtime_fixture(tmp_path, monkeypatch)
    r.run(tmp_path, max_folds=1)
    accept_first(tmp_path, r)
    for _ in range(9):
        r.run(tmp_path, resume=True, max_folds=3)
    p = tmp_path / r.REHEARSAL
    review = json.loads(p.read_text())
    review["changed_after_acceptance"] = True
    write_json(p, review)
    with pytest.raises(ValueError, match="review identity changed"):
        r.run(tmp_path, resume=True, max_folds=3)
    assert len(calls) == 26
