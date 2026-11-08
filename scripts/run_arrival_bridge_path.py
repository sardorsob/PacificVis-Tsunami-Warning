"""Frozen fifteen-call geometric-path contingency; stop at the first failed node or edge."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_bridge import bridge_score  # noqa: E402
from analysis.arrival.model_bridge_path import path_held_loglikelihood, path_score  # noqa: E402
from analysis.arrival.model_bridge_path_fit import CONSUMED as NODE_CONSUMED  # noqa: E402
from analysis.arrival.model_bridge_path_fit import (
    PATH_GATE,
    path_jobs,
    validated_design,
    verify_path_gate,
)  # noqa: E402
from analysis.arrival.model_scale import ANCHORS_KM  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha, validate_checkpoint  # noqa: E402
from scripts.run_arrival_model_validation import supervise  # noqa: E402

CONSUMED = sorted(set([*NODE_CONSUMED, PATH_GATE]))
PARENT = "artifacts/models/arrival-timing/bridge-sequence-validation-v1"
PRIMARY_FOLDER = PARENT + "/jobs/NCEI-native-duration-distance-scale-fold-01-attempt-1/ensembles/"
ENDPOINTS = [
    ("primary", 0, PRIMARY_FOLDER + "00-training", 1426110900),
    ("primary", 8, PRIMARY_FOLDER + "01-augmented", 1426110901),
    ("repeat", 8, "artifacts/models/arrival-timing/exploration-distance-scale-v1", 89261107),
]


def _posterior(root, path, digest):
    raw = checked_path(root, path)
    if sha256(raw) != digest:
        raise ValueError("posterior identity changed")
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as ds:
        post = ds.load()
    np.testing.assert_array_equal(post.scale_anchor_km.values, ANCHORS_KM)
    if post.alpha.shape != (4, 2000):
        raise ValueError("fixed four-chain two-thousand-draw ensembles required")
    for key in ["alpha", "beta", "tau_event", "sigma_anchor"]:
        if not np.isfinite(post[key].values).all():
            raise ValueError("nonfinite endpoint/node")
    if (post.tau_event.values < 0).any() or (post.sigma_anchor.values <= 0).any():
        raise ValueError("invalid endpoint/node scale support")
    return raw, post


def _check_observed(root, raw, group, dimension, ids, lane):
    with xr.open_dataset(raw, group=group, engine="h5netcdf") as ds:
        if ds[dimension].values.tolist() != [lane.record_ids[int(i)] for i in ids]:
            raise ValueError("path data membership changed")
        np.testing.assert_array_equal(ds.response.values, lane.response[ids])
        return dict(ds.attrs)


def prepare_path(root):
    verify_path_gate(root, root / PATH_GATE)
    lane, train, held, frozen = validated_design(root)
    parent = root / PARENT
    summary = json.loads((parent / "run-summary.json").read_text())
    plan = json.loads((parent / "plan.json").read_text())
    qa = json.loads((parent / "rehearsal-review-acceptance.json").read_text())
    if (
        summary["status"] != "needs_review"
        or summary["sampler_calls_reserved"] != 4
        or plan["max_sampler_calls"] != 352
        or qa["status"] != "accepted_base_result_and_valid_numerical_stop"
        or len(list((parent / "jobs").glob("*/sampling-starts/*.json"))) != 4
    ):
        raise ValueError("reviewed four-call stopped-parent debit required")
    files = {
        str(p.relative_to(root)): sha256(p)
        for p in [
            parent / "plan.json",
            parent / "run-summary.json",
            parent / "rehearsal-review-acceptance.json",
            parent / "numerical-stopping-receipt.json",
        ]
    }
    logs, metadata = {}, []
    for role, node, folder, seed in ENDPOINTS:
        folder = root / folder
        result = json.loads((folder / "result.json").read_text())
        inputs = json.loads((folder / "inputs.json").read_text())
        job = result["job"]
        if (
            job["kind"] != "distance-scale"
            or job["target"] != "NCEI-native-duration"
            or job.get("prior") != "base"
            or job["seed"] != seed
            or not result["diagnostics"]["screen_passed"]
            or inputs["source_files"] != frozen
        ):
            raise ValueError("independent matching base-prior endpoint required")
        identities = inputs.get("files", inputs.get("code_and_config", {}))
        for p in [
            "analysis/arrival/model_scale.py",
            "analysis/arrival/models.py",
            "analysis/arrival/model_data.py",
            "config/arrival-model-priors-v1.toml",
            "config/arrival-model-contract-v1.toml",
            "pyproject.toml",
            "uv.lock",
        ]:
            if identities.get(p) != sha256(root / p):
                raise ValueError("endpoint model/prior/environment mismatch")
        raw, post = _posterior(root, result["posterior"], result["posterior_sha256"])
        ids = train if node == 0 else np.sort(np.r_[train, held])
        _check_observed(root, raw, "observed_data", "record", ids, lane)
        logs[(role, node)] = path_held_loglikelihood(lane, held, post)
        for p in [folder / "result.json", folder / "inputs.json", raw]:
            files[str(p.relative_to(root))] = sha256(p)
        metadata.append(
            {
                "path_role": role,
                "node": node,
                "seed": seed,
                "posterior": str(raw.relative_to(root)),
                "posterior_sha256": sha256(raw),
                "records": len(ids),
            }
        )
    if set(j["seed"] for j in path_jobs()) & {p[3] for p in ENDPOINTS}:
        raise ValueError("path random stream overlap")
    parent_store = checked_path(root, plan["raw_store"])
    raw_paths = {checked_path(root, m["posterior"]) for m in metadata}
    if len({m["posterior_sha256"] for m in metadata}) != 3:
        raise ValueError("endpoint draws cannot be reused between paths")
    return {
        "lane": lane,
        "train": train,
        "held": held,
        "source_files": frozen,
        "files": files,
        "endpoint_logs": logs,
        "endpoint_metadata": metadata,
        "record_count": len(held),
        "jacobian": float(np.log(lane.y[held]).sum()),
        "parent_calls": 4,
        "parent_call_ceiling": 352,
        "parent_raw_store": parent_store,
        "extra_endpoint_bytes": sum(
            p.stat().st_size for p in raw_paths if not p.is_relative_to(parent_store)
        ),
        "max_raw_bytes": plan["max_posterior_bytes"],
    }


def read_node(root, folder, job, design):
    result = json.loads((folder / "result.json").read_text())
    inputs = json.loads((folder / "inputs.json").read_text())
    expected = {p: sha256(root / p) for p in [*NODE_CONSUMED, PATH_GATE]}
    if (
        result["job"] != job
        or result["status"] != "node_computed_pending_review"
        or not result["diagnostics"]["screen_passed"]
        or inputs["files"] != expected
        or inputs["source_files"] != design["source_files"]
    ):
        raise ValueError("node identities or diagnostics failed")
    raw, post = _posterior(root, result["posterior"], result["posterior_sha256"])
    _check_observed(root, raw, "observed_data", "record", design["train"], design["lane"])
    attrs = _check_observed(
        root, raw, "integration_held_data", "held_record", design["held"], design["lane"]
    )
    if attrs["likelihood_power"] != job["temperature"]:
        raise ValueError("wrong node temperature")
    array = checked_path(root, result["held_loglikelihood"])
    if sha256(array) != result["held_loglikelihood_sha256"]:
        raise ValueError("node likelihood array changed")
    with np.load(array) as z:
        values = z["held_loglikelihood"]
    np.testing.assert_allclose(
        values, path_held_loglikelihood(design["lane"], design["held"], post), rtol=0, atol=1e-10
    )
    return values


def _files(output, spec, raw):
    paths = [
        spec,
        raw,
        raw.with_suffix(".loglikelihood.npz"),
        output.with_suffix(".log"),
        output.with_suffix(".supervisor.json"),
    ]
    paths += [p for p in output.rglob("*") if p.is_file()]
    paths += list(raw.parent.glob("*-combined-influences.npz"))
    run_folder = output.parent.parent
    paths += [
        run_folder / name
        for name in [
            "primary-path-result.json",
            "repeat-path-result.json",
            "independent-repeat-check.json",
        ]
    ]
    return {str(p): sha256(p) for p in paths if p.is_file()}


def _used_bytes(design, store):
    return design["extra_endpoint_bytes"] + sum(
        p.stat().st_size
        for folder in [design["parent_raw_store"], store]
        for p in folder.rglob("*")
        if p.is_file()
    )


def run_path(root, output, store, state_path, *, resume=False, max_cases=None):
    root, output, store, state_path = (p.resolve() for p in [root, output, store, state_path])
    if (
        not all(p.is_relative_to(root) for p in [output, store, state_path])
        or max_cases is not None
        and (type(max_cases) is not int or max_cases < 0)
    ):
        raise ValueError("project-local fixed path and nonnegative invocation ceiling required")
    cases = [{"id": f"{j['path_role']}-node-{j['node']:02d}", "job": j} for j in path_jobs()]
    if resume:
        plan = json.loads((output / "plan.json").read_text())
        state = json.loads(state_path.read_text())
        if plan["raw_store"] != str(store.relative_to(root)):
            raise ValueError("raw store changed")
        if state["current"] is not None:
            raise ValueError("unfinished path node requires reconciliation")
        validate_checkpoint(state, plan)
    elif output.exists() or store.exists() or state_path.exists():
        raise ValueError("new path run paths required")
    design = prepare_path(root)
    pins = {p: sha256(root / p) for p in CONSUMED}
    pins.update(design["files"])
    if resume:
        if (
            plan["cases"] != cases
            or plan["files"] != pins
            or state["plan_sha256"] != sha256(output / "plan.json")
            or plan["max_calls"] != 15
            or plan["parent_calls"] != design["parent_calls"]
            or plan["global_call_ceiling"] != design["parent_call_ceiling"]
            or plan["max_raw_bytes"] != design["max_raw_bytes"]
            or plan["record_count"] != design["record_count"]
            or plan["jacobian"] != design["jacobian"]
        ):
            raise ValueError("path sources or plan changed")
        for item in state["path_results"].values():
            if sha256(Path(item["path"])) != item["sha256"]:
                raise ValueError("retained path result changed")
    else:
        output.mkdir(parents=True)
        plan = {
            "cases": cases,
            "files": pins,
            "base_git_sha": git_sha(root),
            "max_calls": 15,
            "parent_calls": design["parent_calls"],
            "global_call_ceiling": design["parent_call_ceiling"],
            "max_raw_bytes": design["max_raw_bytes"],
            "raw_store": str(store.relative_to(root)),
            "parent_raw_store": str(design["parent_raw_store"].relative_to(root)),
            "endpoint_metadata": design["endpoint_metadata"],
            "record_count": design["record_count"],
            "jacobian": design["jacobian"],
            "temperatures": np.linspace(0, 1, 9).tolist(),
            "per_node_seconds": 600,
            "per_file_bytes": 64 * 1024**2,
            "cores": 2,
            "concurrency": 1,
            "repairs": "none_absolute_fifteen_call_ceiling",
            "primary": "primary_repeat_is_validation_only",
        }
        write_json(output / "plan.json", plan)
        state = {
            "next_case": 0,
            "calls_used": 0,
            "attempts": [],
            "current": None,
            "status": "prepared",
            "path_results": {},
            "plan_sha256": sha256(output / "plan.json"),
        }
    nodes = dict(design["endpoint_logs"])
    for attempt in state["attempts"]:
        if attempt["outcome"] == "accepted":
            job = next(c["job"] for c in cases if c["id"] == attempt["case_id"])
            nodes[(job["path_role"], job["node"])] = read_node(
                root, Path(attempt["output"]), job, design
            )
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    try:
        atomic_state(state_path, state)
        completed_here = 0
        while state["next_case"] < 15:
            if max_cases is not None and completed_here >= max_cases:
                state["status"] = "invocation_limit"
                break
            if (output / "jobs/STOP").exists():
                state["status"] = "stop_signal"
                break
            if any(sha256(root / p) != h for p, h in pins.items()):
                raise ValueError("path inputs changed")
            case = cases[state["next_case"]]
            job = case["job"]
            role, node = job["path_role"], job["node"]
            reserve = (3 if node == 7 else 2) * plan["per_file_bytes"]
            if (
                state["calls_used"] >= 15
                or plan["parent_calls"] + state["calls_used"] >= plan["global_call_ceiling"]
                or _used_bytes(design, store) + reserve > plan["max_raw_bytes"]
            ):
                state["status"] = "budget_limit"
                break
            attempt = output / "jobs" / case["id"]
            spec = output / "jobs" / (case["id"] + "-spec.json")
            raw = store / (case["id"] + ".nc")
            write_json(spec, job)
            state["calls_used"] += 1
            state["current"] = {"case_id": case["id"], "attempt": 1, "output": str(attempt)}
            state["status"] = "running"
            atomic_state(state_path, state)
            outcome = "runtime_failure"
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/sample_arrival_bridge_path.py"),
                        "--worker",
                        "--job",
                        str(spec),
                        "--output",
                        str(attempt),
                        "--store",
                        str(raw),
                    ],
                    attempt.with_suffix(".log"),
                    output / "jobs/STOP",
                    600,
                )
                write_json(attempt.with_suffix(".supervisor.json"), receipt)
                if receipt["returncode"] == 0 and receipt["reason"] == "worker_exit":
                    values = read_node(root, attempt, job, design)
                    nodes[(role, node)] = values
                    outcome = "accepted"
                    for edge in [node - 1, node]:
                        if (role, edge) in nodes and (role, edge + 1) in nodes:
                            check, _, _ = bridge_score(
                                nodes[(role, edge)] / 8,
                                nodes[(role, edge + 1)] / 8,
                                records=design["record_count"],
                            )
                            write_json(
                                attempt / "edge-checks" / f"{edge:02d}-{edge + 1:02d}.json", check
                            )
                            if not check["precision_passed"]:
                                outcome = "edge_failure"
                                break
                    if outcome == "accepted" and node == 7:
                        summary, combined = path_score(
                            [nodes[(role, i)] for i in range(9)],
                            np.linspace(0, 1, 9),
                            records=design["record_count"],
                            jacobian=design["jacobian"],
                        )
                        target = output / f"{role}-path-result.json"
                        write_json(target, summary)
                        state["path_results"][role] = {
                            "path": str(target),
                            "sha256": sha256(target),
                        }
                        np.savez_compressed(
                            store / f"{role}-combined-influences.npz",
                            **{f"node_{i}": a for i, a in enumerate(combined)},
                        )
                        if not summary["precision_passed"]:
                            outcome = "path_precision_failure"
                        elif role == "repeat":
                            primary = json.loads(
                                Path(state["path_results"]["primary"]["path"]).read_text()
                            )
                            difference = abs(
                                primary["joint_log_predictive"] - summary["joint_log_predictive"]
                            )
                            error = math.hypot(
                                primary["joint_log_mcse_delta"], summary["joint_log_mcse_delta"]
                            )
                            agreed = difference <= 3 * error + 1e-6
                            write_json(
                                output / "independent-repeat-check.json",
                                {
                                    "primary_designated_before_fitting": True,
                                    "raw_difference": difference,
                                    "combined_mcse": error,
                                    "agreement_passed": agreed,
                                    "score_to_use": "primary_never_select_favorable_repeat",
                                },
                            )
                            if not agreed:
                                outcome = "independent_repeat_disagreement"
                elif receipt["reason"] == "worker_exit" and receipt["returncode"] == 2:
                    result = json.loads((attempt / "result.json").read_text())
                    if result["job"] != job:
                        outcome = "identity_failure"
                    elif result["status"] in {"backend_failure", "diagnostic_failure"}:
                        outcome = result["status"]
            except KeyboardInterrupt:
                state["attempts"].append(
                    {
                        **state["current"],
                        "outcome": "interrupted",
                        "files": _files(attempt, spec, raw),
                    }
                )
                state.update(current=None, status="interrupted")
                atomic_state(state_path, state)
                raise
            except Exception as exc:
                write_json(attempt / "evaluation-failure.json", {"error": str(exc)})
                outcome = "identity_or_evaluation_failure"
            if any(sha256(root / p) != h for p, h in pins.items()):
                outcome = "identity_failure"
            if _used_bytes(design, store) > plan["max_raw_bytes"]:
                outcome = "storage_budget_failure"
            state["attempts"].append(
                {**state["current"], "outcome": outcome, "files": _files(attempt, spec, raw)}
            )
            state["current"] = None
            if outcome == "accepted":
                state["next_case"] += 1
                completed_here += 1
            else:
                state["status"] = "needs_review"
            atomic_state(state_path, state)
            print(
                f"fixed path {state['next_case']}/15; newcalls {state['calls_used']}; {outcome}",
                flush=True,
            )
            if state["status"] == "needs_review":
                break
        if state["next_case"] == 15:
            state["status"] = "computations_complete"
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "accepted_new_nodes": state["next_case"],
                "new_call_slots_used": state["calls_used"],
                "new_call_ceiling": 15,
                "parent_call_slots": plan["parent_calls"],
                "global_call_ceiling": plan["global_call_ceiling"],
                "remaining_global_calls": plan["global_call_ceiling"]
                - plan["parent_calls"]
                - state["calls_used"],
                "primary_score_acceptance": "pending_independent_actual_replay",
                "reserved_outcomes": "sealed",
            },
        )
    finally:
        lease.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-cases", type=int)
    a = p.parse_args()
    run_path(
        Path(__file__).resolve().parents[1],
        a.output,
        a.store,
        a.state,
        resume=a.resume,
        max_cases=a.max_cases,
    )
