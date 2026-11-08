"""Reviewed external numerical resolutions advance logical folds without rewriting failures."""

# pyright: basic
from __future__ import annotations

import copy
import json
import math

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_data import CONTRACT
from scripts.run_arrival_model_batch import atomic_state, validate_checkpoint


def verify_resolution(root, record, case, attempt):
    path = checked_path(root, record["path"])
    if sha256(path) != record["sha256"]:
        raise ValueError("reviewed resolution receipt changed")
    qa = json.loads(path.read_text())
    source = checked_path(root, attempt["output"]) / "result.json"
    original = json.loads(source.read_text())
    derived_path = checked_path(root, qa["derived_result"])
    derived = json.loads(derived_path.read_text())
    expected_job = {
        **case["job"],
        **({"draws": 4000, "tune": 2000} if attempt["attempt"] == 2 else {}),
    }
    prediction = source.parent / "held-out-record-predictions.csv"
    prediction_hash = sha256(prediction)
    if (
        qa.get("schema_version") != "arrival_bridge_fold_resolution_v1"
        or qa.get("status") != "accepted_same_model_fold_resolution"
        or not qa.get("independent_checker")
        or qa.get("reserved_outcomes") != "sealed"
        or qa.get("case_id") != case["id"]
        or qa.get("model_contract_sha256") != sha256(root / CONTRACT)
        or qa.get("native_measure") != "native_minutes_joint_density_duration_Jacobian_once"
        or original["job"] != expected_job
        or derived["job"] != expected_job
        or original["status"] != "precision_failure"
        or not original["prediction_precision_passed"]
        or derived["source_result"] != str(source.relative_to(root))
        or derived["source_result_sha256"] != sha256(source)
        or derived["training_only_predictions"] != str(prediction.relative_to(root))
        or derived.get("training_only_predictions_sha256") != prediction_hash
        or attempt["files"].get(str(prediction)) != prediction_hash
        or not derived["fold_score"]["event_precision_passed"]
        or qa.get("new_sampler_calls") != record["new_sampler_calls"]
    ):
        raise ValueError("same native model, clean predictions and independent resolution required")
    required = [
        str(source.relative_to(root)),
        str(derived_path.relative_to(root)),
        str((source.parent / "membership.json").relative_to(root)),
        str(prediction.relative_to(root)),
    ]
    if not set(required) <= set(qa["files"]):
        raise ValueError("resolution membership and prediction evidence required")
    for p, h in qa["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("retained resolution evidence changed")
    prior = {e["event_id"]: e for e in original["events"]}
    events = derived["events"]
    if (
        len(events) != len(prior)
        or {e["event_id"] for e in events} != set(prior)
        or derived["fold_score"]["events"] != len(prior)
    ):
        raise ValueError("resolved fold event membership changed")
    for e in events:
        old = prior[e["event_id"]]
        if (
            e["records"] != old["records"]
            or e["sequence"] != old["sequence"]
            or e["precision_passed"] is not True
            or not math.isfinite(e["joint_log_predictive"])
            or not math.isclose(
                e["joint_log_predictive"] / e["records"],
                e["normalized_event_score"],
                abs_tol=1e-10,
                rel_tol=0,
            )
        ):
            raise ValueError("resolved native event score identity changed")
    score = derived["fold_score"]
    if (
        not math.isclose(
            sum(e["normalized_event_score"] for e in events) / len(events),
            score["equal_event_score"],
            abs_tol=1e-10,
            rel_tol=0,
        )
        or not math.isfinite(score["mcse_equal_event_score"])
        or score["mcse_equal_event_score"] < 0
    ):
        raise ValueError("finite equal-event aggregation and nonnegative MCSE required")
    calls = record["new_sampler_calls"]
    starts = qa["sampling_start_files"]
    if (
        type(calls) is not int
        or calls < 0
        or len(starts) != calls
        or len(set(starts)) != calls
        or not set(starts) <= set(qa["files"])
        or bool(calls) != bool(qa["additional_raw_stores"])
    ):
        raise ValueError("external sampler-call conservation failed")
    seeds = []
    for p in starts:
        started = json.loads(checked_path(root, p).read_text())
        job = started.get("job", started)
        if (
            any(job.get(k) != expected_job[k] for k in ["target", "kind", "prior", "sequence"])
            or type(job.get("seed")) is not int
        ):
            raise ValueError("external sampler model/seed identity changed")
        seeds.append(job["seed"])
    stores = []
    for p in qa["additional_raw_stores"]:
        folder = checked_path(root, p)
        if not folder.is_relative_to(root / "data/processed/models") or not folder.is_dir():
            raise ValueError("project-local existing numerical raw store required")
        if any(
            str(f.relative_to(root)) not in qa["files"] for f in folder.rglob("*") if f.is_file()
        ):
            raise ValueError("all external raw files must remain pinned")
        stores.append(p)
    if calls and sum(len(list(checked_path(root, p).glob("*.nc"))) for p in stores) < calls:
        raise ValueError("each external sampling call needs its retained posterior")
    return qa, seeds, stores


def validate_reviewed_checkpoint(root, state, plan):
    logical = copy.deepcopy(state)
    latest = {a["case_id"]: i for i, a in enumerate(state["attempts"])}
    seeds, stores = [], []
    extra = 0
    for cid, record in state.get("reviewed_resolutions", {}).items():
        case = next(c for c in plan["cases"] if c["id"] == cid)
        index = latest[cid]
        attempt = state["attempts"][index]
        if attempt["outcome"] != "diagnostic_or_precision_failure":
            raise ValueError("only retained numerical failures can receive a resolution")
        _, new_seeds, new_stores = verify_resolution(root, record, case, attempt)
        seeds += new_seeds
        stores += new_stores
        extra += record["new_sampler_calls"]
        # This copy represents logical completion; on-disk failure outcomes stay intact.
        logical["attempts"][index]["outcome"] = "accepted"
    if (
        len(seeds) != len(set(seeds))
        or set(seeds) & set(plan.get("original_seed_channels", []))
        or len(stores) != len(set(stores))
    ):
        raise ValueError("external stream/store reuse would invalidate covariance or accounting")
    validate_checkpoint(logical, plan)
    return extra, stores


def attach_resolution(root, output, store, state_path, receipt):
    root, output, store, state_path = [p.resolve() for p in [root, output, store, state_path]]
    if not all(p.is_relative_to(root) for p in [output, store, state_path]):
        raise ValueError("project-local output, raw store and state paths required")
    receipt = checked_path(root, str(receipt))
    if (output / ".controller.lock").exists():
        raise ValueError("cannot reconcile while a sampler controller holds the lease")
    plan = json.loads((output / "plan.json").read_text())
    state = json.loads(state_path.read_text())
    if (
        state["status"] != "needs_review"
        or state["current"] is not None
        or plan["raw_store"] != str(store.relative_to(root))
        or state["plan_sha256"] != sha256(output / "plan.json")
        or any(sha256(checked_path(root, p)) != h for p, h in plan["files"].items())
    ):
        raise ValueError("unchanged stopped plan and source identities required")
    case = plan["cases"][state["next_case"]]
    qa = json.loads(receipt.read_text())
    record = {
        "path": str(receipt.relative_to(root)),
        "sha256": sha256(receipt),
        "new_sampler_calls": qa["new_sampler_calls"],
    }
    state.setdefault("reviewed_resolutions", {})[case["id"]] = record
    state["next_case"] += 1
    state["sampler_call_slots_used"] += record["new_sampler_calls"]
    state["status"] = "invocation_limit"
    extra, stores = validate_reviewed_checkpoint(root, state, plan)
    used = (
        sum(
            next(c["ensemble_count"] for c in plan["cases"] if c["id"] == a["case_id"])
            for a in state["attempts"]
        )
        + extra
    )
    if used != state["sampler_call_slots_used"] or used > plan["max_sampler_calls"]:
        raise ValueError("resolution exceeds the original conserved sampler ceiling")
    folders = [store, *[checked_path(root, p) for p in [*plan["prior_raw_stores"], *stores]]]
    if len(set(folders)) != len(folders) or any(
        a.is_relative_to(b) or b.is_relative_to(a)
        for j, a in enumerate(folders)
        for b in folders[j + 1 :]
    ):
        raise ValueError("resolution raw stores must be disjoint")
    size = checked_path(root, plan["external_endpoint"]).stat().st_size
    size += sum(p.stat().st_size for folder in folders for p in folder.rglob("*") if p.is_file())
    if size > plan["max_posterior_bytes"]:
        raise ValueError("resolution exceeds the shared raw-byte ceiling")
    atomic_state(state_path, state)
    write_json(output / "reviewed-resolutions.json", state["reviewed_resolutions"])
