"""Event weighting, frozen units and pre-outcome gates for new curvature CV."""

# pyright: basic
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from analysis.arrival.evidence import write_json
from analysis.arrival.model_curvature_comparison import (
    assemble_candidate,
    verify_complete_curvature,
)
from analysis.arrival.model_data import sequence_folds
from tests.test_arrival_models import tiny_lane


def toy():
    lane = replace(tiny_lane(), target="NCEI-native-duration")
    results, predictions = [], []
    for j, fold in enumerate(sequence_folds(lane)):
        events = []
        for i in fold.test:
            value = -2.0 if j == 0 else -8.0
            events.append(
                {
                    "event_id": lane.event_ids[i],
                    "sequence": fold.sequence_id,
                    "records": 1,
                    "joint_log_predictive": value,
                    "normalized_event_score": value,
                    "normalized_mcse": 0.001,
                    "precision_passed": True,
                }
            )
        results.append(
            {
                "job": {
                    "sequence": fold.sequence_id,
                    "target": lane.target,
                    "kind": "mean-curvature",
                    "prior": "base",
                },
                "status": "computed_pending_review",
                "score_precision_passed": True,
                "prediction_precision_passed": True,
                "observation_measure": "native_minutes_Jacobian_already_applied_once",
                "events": events,
                "fold_score": {
                    "events": len(events),
                    "equal_event_score": events[0]["normalized_event_score"],
                    "event_precision_passed": True,
                    "mcse_equal_event_score": 0.001,
                },
            }
        )
        for i, seen in zip(fold.test, fold.seen_site, strict=True):
            predictions.append(
                {
                    "record_id": lane.record_ids[i],
                    "event_id": lane.event_ids[i],
                    "sequence": fold.sequence_id,
                    "distance_km": lane.distance_km[i],
                    "seen_site": bool(seen),
                    "observed_native_minutes": lane.y[i],
                    "pit": 0.5,
                    **{f"q{q:02d}": float(q) for q in [5, 25, 50, 75, 95]},
                }
            )
    return lane, results, predictions


def test_two_event_sequence_and_single_event_have_equal_event_not_fold_weights():
    lane, results, predictions = toy()
    out = assemble_candidate(lane, results, predictions, "cohort")
    assert out["summary"]["events"] == 3 and out["summary"]["sequence_refits"] == 2
    assert out["summary"]["equal_event_score"] == pytest.approx(-4.0)
    assert out["summary"]["monte_carlo_standard_error"] == pytest.approx(np.sqrt(5) * 0.001 / 3)
    assert len({e["record_membership_sha256"] for e in out["events"]}) == 3


@pytest.mark.parametrize(
    "change",
    ["duplicate_event", "wrong_measure", "failed_precision", "bad_fold_mean", "missing_fold"],
)
def test_invalid_candidate_cannot_enter_comparison(change):
    lane, original, predictions = toy()
    results = deepcopy(original)
    if change == "duplicate_event":
        results[0]["events"][1] = dict(results[0]["events"][0])
    elif change == "wrong_measure":
        results[0]["observation_measure"] = "log_ratio"
    elif change == "failed_precision":
        results[0]["events"][0]["normalized_mcse"] = 0.006
    elif change == "bad_fold_mean":
        results[0]["fold_score"]["equal_event_score"] = -3.0
    else:
        results.pop()
    with pytest.raises(ValueError):
        assemble_candidate(lane, results, predictions, "cohort")


def test_incomplete_review_rejected_before_science_or_outcome_read(tmp_path):
    write_json(
        tmp_path
        / "artifacts/models/arrival-timing/mean-curvature-sequence-v1/review-acceptance.json",
        {"status": "checkpoint", "files": {}},
    )
    with pytest.raises(ValueError, match="complete independently"):
        verify_complete_curvature(tmp_path)


def complete_bundle(root, monkeypatch):
    from analysis.arrival import model_curvature_sumatra_resolution_io as sumatra_io
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from analysis.arrival.model_data import CONTRACT
    from scripts import run_arrival_curvature_final_continuation as final
    from scripts.run_arrival_curvature_completion import PRECISION_OUTPUT, PRECISION_REVIEW
    from scripts.run_arrival_curvature_continuation import DERIVED, DERIVED_REVIEW

    source = root / "stub.py"
    source.write_text("source")
    worker = {"stub.py": sha256(source)}
    native = root / "native.csv"
    native.write_text("synthetic native inputs; never parsed")
    contract = root / CONTRACT
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text('[inputs]\n"native.csv" = "' + sha256(native) + '"\n')
    cases = [{"id": f"fold-{j:03d}", "sequence": f"seq-{j}"} for j in range(29)]
    plan = {"cases": cases, "memberships": {c["id"]: {} for c in cases}, "files": worker}
    write_json(root / OUTPUT / "plan.json", plan)
    write_json(root / OUTPUT / "run-summary.json", {"status": "cv_needs_review"})
    stopped = OUTPUT + "/continuation-v2/run-summary.json"
    write_json(root / stopped, {"status": "cv_needs_review", "calls_charged": 77})
    source_events = [
        {
            "event_id": e,
            "records": n,
            "normalized_event_score": -5.0 - j,
            "precision_passed": j != 0,
        }
        for j, (e, n) in enumerate([("usp000exfn", 49), ("usp000f2ab", 22), ("usp000gsmz", 9)])
    ]
    for case in cases:
        folder = root / OUTPUT / "jobs" / case["id"]
        raw = root / "data/processed/models/mean-curvature-sequence-v1" / case["id"]
        raw.mkdir(parents=True)
        (raw / "raw.nc").write_bytes(b"raw")
        if case["id"] == "fold-019":
            (raw / "00-training.nc").write_bytes(b"original aligned training draws")
        result = {
            "job": case,
            "status": "precision_failure"
            if case["id"] in {"fold-002", "fold-008", "fold-019"}
            else "computed_pending_review",
        }
        if case["id"] == "fold-019":
            result.update(events=source_events, heldout_records=80)
        write_json(folder / "result.json", result)
        (folder / "held-out-record-predictions.csv").write_text("original prediction")
        for path in [
            folder.with_name(case["id"] + "-spec.json"),
            folder.with_suffix(".supervisor.json"),
        ]:
            write_json(path, {})
        folder.with_suffix(".log").write_text("log")
        files = {
            str(p.relative_to(root)): sha256(p)
            for base in [folder, raw]
            for p in base.rglob("*")
            if p.is_file()
        }
        files.update(
            {
                str(p.relative_to(root)): sha256(p)
                for p in [
                    folder.with_name(case["id"] + "-spec.json"),
                    folder.with_suffix(".supervisor.json"),
                    folder.with_suffix(".log"),
                ]
            }
        )
        write_json(folder / "attempt-evidence.json", {"case_id": case["id"], "files": files})
    proof = {
        "independent_checker": True,
        "files": worker,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
    primary = sumatra_io.OUTPUT + "/primary-path-result.json"
    write_json(root / primary, {"synthetic": True})
    resolution = {}
    for j, derived, receipt, status in [
        (2, DERIVED, DERIVED_REVIEW, "accepted_same_model_curvature_fold_resolution"),
        (
            8,
            PRECISION_OUTPUT,
            PRECISION_REVIEW,
            "accepted_same_model_curvature_precision_resolution",
        ),
        (
            19,
            final.DERIVED,
            final.DERIVED_REVIEW,
            "accepted_same_model_curvature_sumatra_fold_resolution",
        ),
    ]:
        case_id = f"fold-{j:03d}"
        failed = OUTPUT + "/jobs/" + case_id + "/result.json"
        prediction = OUTPUT + "/jobs/" + case_id + "/held-out-record-predictions.csv"
        result_path = derived + "/result.json"
        result = {
            "job": cases[j],
            "source_result": failed,
            "source_result_sha256": sha256(root / failed),
            "training_only_predictions": prediction,
            "training_only_predictions_sha256": sha256(root / prediction),
            "status": "computed_pending_review",
            "score_precision_passed": True,
            "prediction_precision_passed": True,
            "observation_measure": "native_minutes_Jacobian_already_applied_once",
        }
        if j == 19:
            result.update(
                events=[
                    {**source_events[0], "normalized_event_score": -4.5, "precision_passed": True},
                    *source_events[1:],
                ],
                retained_direct_bridge_status="precision_failure",
                prediction_source="unchanged_original_training_only_predictions",
                score_resolution="predesignated_same_model_full_coefficient_power_path",
                primary_path=primary,
                primary_path_sha256=sha256(root / primary),
                fold_score={
                    "events": 3,
                    "event_precision_passed": True,
                    "source_training_posterior_sha": sha256(
                        root / sumatra_io.ORIGINAL_RAW / "00-training.nc"
                    ),
                    "mcse_scope": (
                        "path_and_other_event_training_influences_combined_"
                        "before_independent_stage_variances"
                    ),
                    "primary_path_training_variance": (
                        "included_once_in_shared_vector_not_added_again"
                    ),
                },
            )
        write_json(root / result_path, result)
        write_json(
            root / receipt,
            {
                **proof,
                "status": status,
                "derived_result": result_path,
                "derived_result_sha256": sha256(root / result_path),
            },
        )
        resolution[case_id] = {
            "receipt": receipt,
            "receipt_sha256": sha256(root / receipt),
            "result": result_path,
            "result_sha256": sha256(root / result_path),
            "prediction": prediction,
            "prediction_sha256": sha256(root / prediction),
        }
    write_json(
        root / final.DERIVED / "inputs.json",
        {
            "files": worker,
            "new_sampler_calls": 0,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        root / final.DERIVED / "output-checksums.json",
        {name: sha256(root / final.DERIVED / name) for name in ["inputs.json", "result.json"]},
    )
    path_closure = {**worker, stopped: sha256(root / stopped)}
    write_json(
        root / sumatra_io.REVIEW,
        {
            **proof,
            "files": path_closure,
            "status": "accepted_curvature_sumatra_primary_path_and_independent_repeat",
        },
    )
    binding = final.bindings(
        root, root / final.CONTINUATION, root / final.STORE, root / final.STATE
    )
    write_json(
        root / final.GATE,
        {
            **proof,
            "status": "accepted_curvature_final_continuation_rehearsal",
            "resolutions": resolution,
            "resources": final.resources(),
            "path_bindings": binding,
            "remaining_cases": cases[20:],
            "original_plan_sha256": sha256(root / OUTPUT / "plan.json"),
        },
    )
    write_json(
        root / final.REHEARSAL,
        {**proof, "status": "accepted_first_curvature_final_continuation_fold"},
    )
    write_json(
        root / final.CONTINUATION / "plan.json",
        {
            "cases": cases,
            "original_plan_sha256": sha256(root / OUTPUT / "plan.json"),
            "original_worker_files": worker,
            "resolutions": resolution,
            "files": worker,
            "inherited_slots": 109,
            "remaining_nominal_slots": 19,
            "global_call_ceiling": 248,
            "resources": final.resources(),
            "path_bindings": binding,
            "canonical_state_path": final.STATE,
        },
    )
    write_json(
        root / final.CONTINUATION / "run-summary.json",
        {
            "status": "cv_computations_complete",
            "logical_completed_folds": 29,
            "planned_folds": 29,
            "direct_accepted_folds": 26,
            "reviewed_resolutions": 3,
            "calls_charged": 128,
            "calls_started": 128,
            "max_sampler_call_slots": 248,
            "inherited_slots": 109,
            "remaining_nominal_calls_at_start": 19,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    gate = {
        "status": "accepted_all_curvature_sequence_computations",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "resolutions": resolution,
        "files": {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()},
    }
    write_json(root / OUTPUT / "review-acceptance.json", gate)

    def checked_attempt(root, case, member, worker):
        path = root / OUTPUT / "jobs" / case["id"] / "attempt-evidence.json"
        import json

        return json.loads(path.read_text())["files"], path

    monkeypatch.setattr("scripts.run_arrival_curvature_sequences.case_artifacts", checked_attempt)
    monkeypatch.setattr(sumatra_io, "verified_path", lambda root: path_closure)
    return gate


def test_complete_continuation_maps_only_resolved_score_and_keeps_original_failure(
    tmp_path, monkeypatch
):
    import json

    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts.run_arrival_curvature_continuation import DERIVED

    complete_bundle(tmp_path, monkeypatch)
    plan, pins = verify_complete_curvature(tmp_path)
    assert len(plan["cases"]) == 29
    assert plan["resolutions"]["fold-002"]["result"] == DERIVED + "/result.json"
    assert OUTPUT + "/run-summary.json" in pins
    assert (
        json.loads((tmp_path / OUTPUT / "jobs/fold-002/result.json").read_text())["status"]
        == "precision_failure"
    )


@pytest.mark.parametrize(
    "change",
    [
        "unreviewed_attempt",
        "refunded_slots",
        "missing_resolution",
        "drop_lata_resolution",
        "wrong_prediction",
        "unreviewed_source",
        "old_summary_only",
    ],
)
def test_incomplete_continuation_cannot_enter_science(tmp_path, monkeypatch, change):
    import json

    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts.run_arrival_curvature_continuation import DERIVED

    gate = complete_bundle(tmp_path, monkeypatch)
    if change == "unreviewed_attempt":
        path = tmp_path / OUTPUT / "jobs/fold-000/extra.json"
        write_json(path, {})
    elif change == "refunded_slots":
        path = tmp_path / OUTPUT / "continuation-v3/run-summary.json"
        value = json.loads(path.read_text())
        value["calls_charged"] = value["calls_started"] = 126
        write_json(path, value)
        gate["files"][str(path.relative_to(tmp_path))] = sha256(path)
    elif change == "missing_resolution":
        gate["resolutions"] = {}
    elif change == "drop_lata_resolution":
        del gate["resolutions"]["fold-008"]
    elif change == "wrong_prediction":
        path = tmp_path / DERIVED / "result.json"
        value = json.loads(path.read_text())
        value["training_only_predictions"] = "alternate.csv"
        write_json(path, value)
        gate["files"][str(path.relative_to(tmp_path))] = sha256(path)
    elif change == "unreviewed_source":
        del gate["files"]["stub.py"]
    else:
        del gate["files"][OUTPUT + "/continuation-v2/run-summary.json"]
    write_json(tmp_path / OUTPUT / "review-acceptance.json", gate)
    with pytest.raises(ValueError):
        verify_complete_curvature(tmp_path)


def test_contract_input_gap_blocks_outcome_loader(tmp_path, monkeypatch):
    from analysis.arrival import model_curvature_comparison as module
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_data import CONTRACT

    p = tmp_path / CONTRACT
    p.parent.mkdir(parents=True)
    p.write_text('[inputs]\n"unreviewed.csv" = "' + "a" * 64 + '"\n')
    monkeypatch.setattr(module, "verify_complete_curvature", lambda _: ({}, {CONTRACT: sha256(p)}))

    def forbidden(*args):
        raise AssertionError("native outcome loader must remain unopened")

    monkeypatch.setattr("analysis.arrival.model_data.load_lanes", forbidden)
    with pytest.raises(ValueError, match="before parsing"):
        module.collect_curvature(tmp_path)


def test_collector_uses_resolved_result_with_original_prediction_file(tmp_path, monkeypatch):
    import json

    from analysis.arrival import model_curvature_comparison as module
    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_data import CONTRACT

    lane, results, predictions = toy()
    contract_file = tmp_path / CONTRACT
    contract_file.parent.mkdir(parents=True)
    contract_file.write_text('[inputs]\n"native.csv" = "reviewed"\n')
    cases, resolutions, tables = [], {}, {}
    for j, result in enumerate(results):
        case = {**result["job"], "id": f"fold-{j:03d}"}
        result["job"] = case
        cases.append(case)
        folder = tmp_path / module.OUTPUT / "jobs" / case["id"]
        target = folder / "result.json" if j == 0 else tmp_path / "resolved/result.json"
        write_json(target, result)
        prediction_path = folder / "held-out-record-predictions.csv"
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text("original prediction")
        tables[str(prediction_path)] = [p for p in predictions if p["sequence"] == case["sequence"]]
        if j:
            write_json(
                folder / "result.json", {"status": "precision_failure", "unusable_score": 999}
            )
            resolutions[case["id"]] = {
                "result": str(target.relative_to(tmp_path)),
                "prediction": str(prediction_path.relative_to(tmp_path)),
            }
    pins = {str(p.relative_to(tmp_path)): sha256(p) for p in tmp_path.rglob("*") if p.is_file()}
    # Input closure is exercised independently; this isolates score/prediction routing.
    pins["native.csv"] = "reviewed"
    monkeypatch.setattr(
        module,
        "verify_complete_curvature",
        lambda _: ({"cases": cases, "resolutions": resolutions}, pins),
    )
    monkeypatch.setattr(
        "analysis.arrival.model_data.load_lanes",
        lambda _: ({lane.target: lane}, {"contract": "toy"}),
    )
    monkeypatch.setattr(module, "read_rows", lambda p: tables[str(p)])
    monkeypatch.setattr(module, "normalize_predictions", lambda p, _: p)
    real_hash = module.sha256
    monkeypatch.setattr(
        module, "sha256", lambda p: "reviewed" if p.name == "native.csv" else real_hash(p)
    )
    (tmp_path / "native.csv").write_text("native")
    candidate, _ = module.collect_curvature(tmp_path)
    assert candidate["summary"]["equal_event_score"] == pytest.approx(-4)
    assert candidate["predictions"] == predictions
    failed = tmp_path / module.OUTPUT / "jobs/fold-001/result.json"
    assert json.loads(failed.read_text())["status"] == "precision_failure"


def test_report_requires_curvature_acceptance_before_baseline_outcomes(tmp_path, monkeypatch):
    from scripts import summarize_arrival_curvature_comparison as report_module

    for path in report_module.CODE:
        source = tmp_path / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("source")

    def missing_gate(root):
        raise ValueError("complete independently reviewed curvature CV required")

    def forbidden(root):
        raise AssertionError("baseline outcomes must remain unopened")

    monkeypatch.setattr(report_module, "collect_curvature", missing_gate)
    monkeypatch.setattr(report_module, "collect_models", forbidden)
    with pytest.raises(ValueError, match="independently reviewed"):
        report_module.report(tmp_path, tmp_path / "report")
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("missing", ["native.csv", "late_attempt", "sumatra_closure"])
def test_complete_closure_precedes_every_prediction_parser(tmp_path, monkeypatch, missing):
    from analysis.arrival.model_curvature_comparison import OUTPUT

    gate = complete_bundle(tmp_path, monkeypatch)
    name = {
        "native.csv": "native.csv",
        "late_attempt": OUTPUT + "/jobs/fold-028/attempt-evidence.json",
        "sumatra_closure": OUTPUT + "/continuation-v2/run-summary.json",
    }[missing]
    gate["files"].pop(name)
    write_json(tmp_path / OUTPUT / "review-acceptance.json", gate)

    def forbidden(*args):
        raise AssertionError("prediction parser ran before complete closure")

    monkeypatch.setattr("scripts.run_arrival_curvature_sequences.case_artifacts", forbidden)
    with pytest.raises(ValueError):
        verify_complete_curvature(tmp_path)


def test_old_96_call_summary_cannot_be_relabelled_as_final_continuation(tmp_path, monkeypatch):
    import json

    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts import run_arrival_curvature_final_continuation as final

    gate = complete_bundle(tmp_path, monkeypatch)
    path = tmp_path / final.CONTINUATION / "run-summary.json"
    summary = json.loads(path.read_text())
    summary.update(
        calls_charged=96,
        calls_started=96,
        direct_accepted_folds=27,
        reviewed_resolutions=2,
        inherited_slots=53,
        remaining_nominal_calls_at_start=43,
    )
    write_json(path, summary)
    gate["files"][str(path.relative_to(tmp_path))] = sha256(path)
    write_json(tmp_path / OUTPUT / "review-acceptance.json", gate)
    with pytest.raises(ValueError, match="128sampler"):
        verify_complete_curvature(tmp_path)


def test_verification_rechecks_evidence_after_reading_attempts(tmp_path, monkeypatch):
    from scripts import run_arrival_curvature_sequences as sequence_runner

    complete_bundle(tmp_path, monkeypatch)
    checked = sequence_runner.case_artifacts

    def drift(*args):
        value = checked(*args)
        (tmp_path / "stub.py").write_text("changed during metadata read")
        return value

    monkeypatch.setattr(sequence_runner, "case_artifacts", drift)
    with pytest.raises(ValueError, match="changed during complete-CV"):
        verify_complete_curvature(tmp_path)


@pytest.mark.parametrize("change", ["shared_mcse_scope", "double_t0", "other_event", "measure"])
def test_self_consistent_sumatra_metadata_cannot_change_the_accepted_measure_or_covariance(
    tmp_path, monkeypatch, change
):
    import json

    from analysis.arrival.evidence import sha256
    from analysis.arrival.model_curvature_comparison import OUTPUT
    from scripts import run_arrival_curvature_final_continuation as final

    gate = complete_bundle(tmp_path, monkeypatch)
    path = tmp_path / final.DERIVED / "result.json"
    result = json.loads(path.read_text())
    if change == "shared_mcse_scope":
        result["fold_score"]["mcse_scope"] = "incorrect_independent_training_events"
    elif change == "double_t0":
        result["fold_score"]["primary_path_training_variance"] = "added_twice"
    elif change == "other_event":
        result["events"][1]["normalized_event_score"] = 999.0
    else:
        result["observation_measure"] = "extra_native_Jacobian_subtracted"
    write_json(path, result)
    checksums = tmp_path / final.DERIVED / "output-checksums.json"
    values = json.loads(checksums.read_text())
    values["result.json"] = sha256(path)
    write_json(checksums, values)
    review_path = tmp_path / final.DERIVED_REVIEW
    review = json.loads(review_path.read_text())
    review["derived_result_sha256"] = sha256(path)
    write_json(review_path, review)
    resolution = gate["resolutions"]["fold-019"]
    resolution.update(result_sha256=sha256(path), receipt_sha256=sha256(review_path))
    for name in [final.GATE, final.CONTINUATION + "/plan.json"]:
        value = json.loads((tmp_path / name).read_text())
        value["resolutions"] = gate["resolutions"]
        write_json(tmp_path / name, value)
    full_review = tmp_path / OUTPUT / "review-acceptance.json"
    gate["files"] = {
        str(p.relative_to(tmp_path)): sha256(p)
        for p in tmp_path.rglob("*")
        if p.is_file() and p != full_review
    }
    write_json(full_review, gate)
    with pytest.raises(ValueError):
        verify_complete_curvature(tmp_path)


def test_33_event_29_sequence_assembly_keeps_49_22_9_scores_and_shared_fold_mcse():
    event_ids = tuple(
        ["usp000exfn"] * 49
        + ["usp000f2ab"] * 22
        + ["usp000gsmz"] * 9
        + [f"other-{j}" for j in range(30)]
    )
    sequences = ("sumatra",) * 80 + tuple(
        "pair-a" if j < 2 else "pair-b" if j < 4 else f"single-{j}" for j in range(30)
    )
    size = len(event_ids)
    lane = replace(
        tiny_lane(),
        target="NCEI-native-duration",
        rows=tuple({} for _ in event_ids),
        event_ids=event_ids,
        sequences=sequences,
        record_ids=tuple(f"r-{j}" for j in range(size)),
        site_ids=tuple(f"s-{j}" for j in range(size)),
        y=np.full(size, 100.0),
        distance_km=np.full(size, 1000.0),
        reference_minutes=np.full(size, 80.0),
        x=np.zeros(size),
        response=np.full(size, np.log(1.25)),
        included=np.ones(size, dtype=bool),
    )
    results, predictions = [], []
    scores = {"usp000exfn": -4.5, "usp000f2ab": -6.0, "usp000gsmz": -7.0}
    for fold in sequence_folds(lane):
        rows = []
        for event in sorted({lane.event_ids[int(i)] for i in fold.test}):
            count = sum(lane.event_ids[int(i)] == event for i in fold.test)
            value = scores.get(event, -5.0)
            rows.append(
                {
                    "event_id": event,
                    "sequence": fold.sequence_id,
                    "records": count,
                    "joint_log_predictive": value * count,
                    "normalized_event_score": value,
                    "normalized_mcse": 0.001,
                    "precision_passed": True,
                }
            )
        results.append(
            {
                "job": {
                    "sequence": fold.sequence_id,
                    "target": lane.target,
                    "kind": "mean-curvature",
                    "prior": "base",
                },
                "status": "computed_pending_review",
                "score_precision_passed": True,
                "prediction_precision_passed": True,
                "observation_measure": "native_minutes_Jacobian_already_applied_once",
                "events": rows,
                "fold_score": {
                    "events": len(rows),
                    "event_precision_passed": True,
                    "equal_event_score": float(
                        np.mean([row["normalized_event_score"] for row in rows])
                    ),
                    "mcse_equal_event_score": 0.00123 if fold.sequence_id == "sumatra" else 0.001,
                },
            }
        )
        for i, seen in zip(fold.test, fold.seen_site, strict=True):
            predictions.append(
                {
                    "record_id": lane.record_ids[int(i)],
                    "event_id": lane.event_ids[int(i)],
                    "sequence": fold.sequence_id,
                    "distance_km": 1000.0,
                    "seen_site": bool(seen),
                    "observed_native_minutes": 100.0,
                    "pit": 0.5,
                    **{f"q{q:02d}": float(q) for q in [5, 25, 50, 75, 95]},
                }
            )
    out = assemble_candidate(lane, results, predictions, "synthetic-33-event-cohort")
    assert out["summary"]["events"] == 33 and out["summary"]["sequence_refits"] == 29
    assert out["summary"]["equal_event_score"] == pytest.approx((sum(scores.values()) - 150) / 33)
    expected_mcse = np.sqrt((3 * 0.00123) ** 2 + 2 * (2 * 0.001) ** 2 + 26 * 0.001**2) / 33
    assert out["summary"]["monte_carlo_standard_error"] == pytest.approx(expected_mcse)
    for row in out["events"]:
        if row["event_id"] in scores:
            assert row["normalized_event_score"] == scores[row["event_id"]]
            assert row["joint_log_predictive"] == scores[row["event_id"]] * row["records"]
    assert out["predictions"] == predictions
