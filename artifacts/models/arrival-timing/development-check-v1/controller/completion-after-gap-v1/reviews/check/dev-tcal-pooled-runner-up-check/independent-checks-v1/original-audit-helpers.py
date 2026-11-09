"""Independent failed curved NCEI check audit only; no other lane/fit or state body."""

# pyright: basic
from __future__ import annotations

import importlib.util
import json
import math
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import arviz_stats as azs
import numpy as np

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival import model_development_references as refs
from analysis.arrival.evidence import read_rows, sha256
from analysis.arrival.model_data import lane_arrays
from scripts import run_arrival_development as controller

ROOT = Path("/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times")
JOB_ID = "dev-ncei-mean-curvature-selected-check"
TARGET = "NCEI-native-duration"
RAW = "data/processed/models/mean-curvature-sequence-v1/fold-014/00-training.nc"
RAW_SHA = "81cb836d8c6aa48d5b6a1095330090c43f73079da1c6c7bec5fb4382c4f473bb"
spec = importlib.util.spec_from_file_location(
    "independent_math", "/private/tmp/check-tsunami-development-math.py"
)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def close(actual, expected, message, atol=5e-8, rtol=2e-12):
    require(np.allclose(actual, expected, atol=atol, rtol=rtol), message)
    return float(np.max(np.abs(np.asarray(actual) - np.asarray(expected))))


def mcse(values):
    return (
        0.0
        if np.ptp(values) == 0
        else float(cast(Any, azs).mcse(values, method="mean", chain_axis=0, draw_axis=1))
    )


def mixing(values):
    return dict(
        rhat=float(cast(Any, azs).rhat(values)),
        ess_bulk=float(cast(Any, azs).ess(values, method="bulk")),
        ess_tail=float(cast(Any, azs).ess(values, method="tail", prob=(0.05, 0.95))),
    )


def main():
    # Metadata/source admission before opening the named NCEI check table or reference.
    admission = controller.admit(ROOT, "check")
    pins = admission["files"]
    job = admission["gate"]["jobs"][0]
    require(
        job["id"] == JOB_ID
        and job["role"] == "check_evaluate"
        and job["model_key"] == TARGET + ":mean-curvature:selected",
        "only named closed job0 authorized",
    )
    require(
        job["training_reference"] == {"kind": "historical"}, "literal historical reference only"
    )
    frozen, contract, roles, sequences = data.verify_development_sources(ROOT, pins)
    model = admission["specs"][job["model_key"]][1]
    require(
        model["kind"] == "mean-curvature" and model["prior_variant"] == "base",
        "unchanged BASE curvature",
    )
    folder, raw = fit.case_paths(ROOT, job)
    require(raw is None, "zero-call evaluator has no new posterior")
    manifest = read(folder / "output-checksums.json")
    require(
        set(manifest)
        == {
            "job.json",
            "inputs.json",
            "membership.json",
            "result.json",
            "event-results.json",
            "direct-score-arrays.npz",
            "held-out-record-predictions.csv",
        },
        "literal failed producer inventory",
    )
    require(
        {p.name for p in folder.iterdir()} == set(manifest) | {"output-checksums.json"},
        "no unknown partial file",
    )
    files = {str((folder / name).relative_to(ROOT)): digest for name, digest in manifest.items()}
    files[str((folder / "output-checksums.json").relative_to(ROOT))] = sha256(
        folder / "output-checksums.json"
    )
    siblings = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    files.update({str(p.relative_to(ROOT)): sha256(p) for p in siblings})
    attempt_path = controller.attempt_path(ROOT, job)
    files[str(attempt_path.relative_to(ROOT))] = sha256(attempt_path)
    data._unchanged(ROOT, {**pins, **files})
    require(read(siblings[0]) == read(folder / "job.json") == job, "exact native job/spec")
    inputs = read(folder / "inputs.json")
    require(
        inputs == dict(files=pins, model_spec=model, specification_freeze_sha256=pins[data.FREEZE]),
        "full exact admission inputs",
    )
    runtime = read(siblings[2])
    attempt = read(attempt_path)
    result = read(folder / "result.json")
    require(
        runtime["returncode"] == 2
        and runtime["reason"] == "worker_exit"
        and runtime["cost"] == runtime["start_markers"] == 0
        and runtime["job_sha256"] == sha256(siblings[0])
        and not runtime["monitor_failures"]
        and runtime["plan_sha256"] == sha256(ROOT / controller.CONTROL / "check-plan.json")
        and re.fullmatch("[0-9a-f]{40}", runtime["invocation_git_sha"]),
        "retained zero-call failed process",
    )
    require(
        attempt["job_id"] == JOB_ID
        and attempt["outcome"] == "needs_review"
        and attempt["cost"] == attempt["start_markers"] == 0
        and not attempt["worker_files"]
        and not list(folder.glob("sampling-start*")),
        "failed evaluator cannot manufacture sampler cost/pilot",
    )
    released_leases = [name for name in attempt["files"] if not (ROOT / name).is_file()]
    require(
        released_leases == [controller.CONTROL + "/.controller.lock"],
        "only the normally released controller lease may be absent from failure snapshot",
    )
    data._unchanged(ROOT, {p: h for p, h in attempt["files"].items() if p not in released_leases})
    require(
        result["status"] == "needs_numerical_review"
        and result["confirmation_outcomes_parsed"] is True
        and result["reserved_outcomes"] == "sealed"
        and result["sampler_call_started"] is False,
        "truthful failed/current exposure status",
    )
    # Target-specific reconstruction: NEVER call the all-three-lane loader here.
    original = read_rows(data._path(ROOT, data.TARGET_FILES[TARGET]))
    held_rows = read_rows(data._path(ROOT, data.CHECK_FILES[TARGET]))
    require((len(original), len(held_rows)) == (1070, 151), "literal NCEI source sizes")
    edges = Counter((r["event_id"], r["physical_site_id"]) for r in held_rows)
    require(all(v == 1 for v in edges.values()), "no new check ambiguity")
    source = lane_arrays(TARGET, original, sequences, roles["exploration"])
    held = lane_arrays(TARGET, held_rows, sequences, roles["confirmation"])
    check_sequences = {sequences[event] for event in roles["confirmation"]}
    mask = source.included & ~np.isin(source.sequences, sorted(check_sequences))
    training = replace(source, included=mask)
    require(
        int(mask.sum()) == 1040
        and int(source.included.sum()) == 1064
        and int(held.included.sum()) == 151
        and {rid for rid, keep in zip(source.record_ids, source.included, strict=True) if not keep}
        == data.OLD_EXCLUSIONS,
        "1040 purged, six old exclusions,151 held; no repairs",
    )
    removed = [
        rid
        for rid, keep, retain in zip(source.record_ids, source.included, mask, strict=True)
        if keep and not retain
    ]
    require(
        len(removed) == 24
        and {source.event_ids[i] for i in np.flatnonzero(source.included & ~mask)}
        == {data.CROSS_EXPLORATION},
        "whole crossing-sequence24-row purge",
    )
    membership = read(folder / "membership.json")
    require(
        membership["training_record_ids"] == [source.record_ids[i] for i in np.flatnonzero(mask)]
        and membership["check_primary_ids"] == list(held.record_ids)
        and membership["purged_primary_ids"] == removed
        and membership["excluded_ids"] == sorted(data.OLD_EXCLUSIONS),
        "exact ordered native membership",
    )
    post, provenance = refs.load_frozen_training_reference(ROOT, job["model_key"], training, pins)
    require(
        provenance["raw"] == RAW and provenance["raw_sha256"] == RAW_SHA and pins[RAW] == RAW_SHA,
        "only authorized original1040 BASE posterior",
    )
    require(
        dict(post.sizes) == {"chain": 4, "draw": 2000, "scale_anchor_km": 3},
        "literal4x2k original population",
    )
    pop = {name: post[name].values for name in post.data_vars}
    # Source semantic replay is allowed to stay failed; no success flag is patched.
    replay = fit._evaluate(ROOT, folder, training, held, model, post, provenance, verify=True)
    require(
        replay["status"] == "needs_numerical_review"
        and all(result[k] == v for k, v in replay.items()),
        "entire failed event/prediction output must replay unchanged",
    )
    events = read(folder / "event-results.json")
    predicted = read_rows(folder / "held-out-record-predictions.csv")
    require(
        len(predicted) == 151 and len({r["record_id"] for r in predicted}) == 151,
        "all151 rows retained",
    )
    rows = {r["record_id"]: r for r in predicted}
    event_oracles = []
    scores = []
    sizes = []
    max_cdf = max_pit = max_mcse = 0.0
    failed_diagnosis = {}
    with np.load(folder / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        require(
            np.array_equal(arrays["chain_coordinates"], post.chain.values)
            and np.array_equal(arrays["draw_coordinates"], post.draw.values),
            "literal aligned chains/draws",
        )
        for order, event in enumerate(events["events"]):
            event_id = event["event_id"]
            ids = np.flatnonzero(held.included & (np.asarray(held.event_ids) == event_id))
            require(
                event["record_ids"] == [held.record_ids[i] for i in ids], "ordered event native IDs"
            )
            native, reference, distance = (
                held.y[ids],
                held.reference_minutes[ids],
                held.distance_km[ids],
            )
            independent, jac = oracle.block_loglikelihood(native, reference, distance, pop, TARGET)
            dense = oracle.dense_points(native, reference, distance, pop, TARGET)
            ll_error = close(
                arrays[f"event_{order:03d}_native_loglikelihood"],
                independent,
                "all8k native Gaussian logL",
            )
            score = oracle.score_arrays(independent, len(ids))
            scores.append(score)
            sizes.append(len(ids))
            influence_error = close(
                arrays[f"event_{order:03d}_joint_influence"],
                score["joint_influence"],
                "all8k exact influences",
                atol=2e-8,
            )
            saved = event["score"]
            err = mcse(score["joint_influence"] / len(ids))
            mix = mixing(score["joint_influence"] / len(ids))
            close(
                saved["joint_log_predictive"],
                score["joint_log_predictive"],
                "joint density average",
            )
            close(
                saved["normalized_event_score"], score["normalized_event_score"], "normalized score"
            )
            close(saved["normalized_mcse"], err, "event chain-aware MCSE", atol=1e-11)
            close(
                saved["density_weight_concentration_ess"],
                score["weight_concentration"],
                "concentration",
                atol=1e-7,
            )
            close(
                saved["chain_joint_log_predictive"],
                score["chain_joint_scores"],
                "each chain normalizer",
            )
            require(saved["metadata"]["native_log_jacobian"] == jac, "native Jonce")
            spread = float(np.ptp(score["chain_joint_scores"]))
            expected_failures = []
            if not (mix["rhat"] <= 1.01 and mix["ess_bulk"] >= 400 and mix["ess_tail"] >= 400):
                expected_failures.append("functional_mixing")
            if score["weight_concentration"] < 100:
                expected_failures.append("density_weight_concentration")
            if err > 0.005:
                expected_failures.append("event_mcse")
            if spread / len(ids) > max(0.005, 6 * err):
                expected_failures.append("chain_log_normalizer_disagreement")
            require(
                saved["numerical_failures"] == expected_failures,
                "all numerical failure guards unchanged",
            )
            q = {
                key: np.array([float(rows[held.record_ids[i]][key]) for i in ids])
                for key in ["q05", "q25", "q50", "q75", "q95"]
            }
            streams = oracle.marginal_streams(native, reference, distance, pop, TARGET, q)
            for j, i in enumerate(ids):
                row = rows[held.record_ids[i]]
                require(
                    row["event_id"] == event_id
                    and row["sequence"] == held.sequences[i]
                    and row["site_id"] == held.site_ids[i],
                    "literal row/event/site",
                )
                for key, value in [
                    ("observed_reported_minutes", native[j]),
                    ("modeled_response", held.response[i]),
                    ("distance_km", distance[j]),
                    ("reference_minutes", reference[j]),
                ]:
                    close(float(row[key]), value, "native row field", atol=1e-12)
                support = [
                    float(training.distance_km[mask].min()),
                    float(training.distance_km[mask].max()),
                ]
                within = support[0] <= distance[j] <= support[1]
                require(
                    row["within_training_distance_range"] == str(within)
                    and row["residual_scale_endpoint_clamped"]
                    == str(distance[j] < 500 or distance[j] > 5000),
                    "support/clamping",
                )
                max_pit = max(
                    max_pit, close(float(row["pit"]), streams["pit"][j], "PIT", atol=2e-12)
                )
                close(
                    float(row["pit_chain_range"]),
                    streams["pit_chain_range"][j],
                    "PIT chain range",
                    atol=2e-12,
                )
                pit_error = mcse(streams["pit_stream"][..., j])
                width = q["q95"][j] - q["q05"][j]
                max_mcse = max(
                    max_mcse, close(float(row["pit_mcse"]), pit_error, "PIT MCSE", atol=1e-11)
                )
                cdf_errors = []
                relative_errors = []
                for key, prob in zip(q, [0.05, 0.25, 0.5, 0.75, 0.95], strict=True):
                    max_cdf = max(max_cdf, abs(float(streams[key]["cdf"][j]) - prob))
                    require(
                        abs(float(streams[key]["cdf"][j]) - prob) <= 1e-8,
                        "every saved quantile inverts marginal CDF",
                    )
                    se = mcse(streams[key]["cdf_stream"][..., j])
                    native_se = se / streams[key]["native_density"][j]
                    close(float(row[key + "_cdf_mcse"]), se, "quantile CDF MCSE", atol=1e-11)
                    close(
                        float(row[key + "_mcse_native"]),
                        native_se,
                        "native quantile deltaMCSE",
                        atol=1e-8,
                    )
                    cdf_errors.append(se)
                    relative_errors.append(native_se / width)
                require(
                    row["prediction_precision_passed"]
                    == str(
                        pit_error <= 0.005
                        and max(cdf_errors) <= 0.005
                        and max(relative_errors) <= 0.01
                    ),
                    "all prediction precision screens",
                )
                require(
                    row["coverage90_numerically_ambiguous"]
                    == str(any(abs(streams["pit"][j] - b) <= 3 * pit_error for b in [0.05, 0.95])),
                    "coverage ambiguity retained",
                )
            event_oracles.append(
                dict(
                    event_id=event_id,
                    records=len(ids),
                    dense=dense,
                    max_logL_error=ll_error,
                    max_influence_error=influence_error,
                    normalized_score=score["normalized_event_score"],
                    mcse=err,
                    weight_concentration=score["weight_concentration"],
                    chain_scores=score["chain_joint_scores"].tolist(),
                    failures=expected_failures,
                    precision_passed=not expected_failures,
                )
            )
            if event_id == "usp0008rpa":
                weights = np.exp(independent - independent.max())
                normalized = weights / weights.sum()
                sorted_w = np.sort(normalized.ravel())[::-1]
                fields = {}
                for name, value in pop.items():
                    for column in range(3) if name == "sigma_anchor" else [None]:
                        x = value[..., column] if column is not None else value
                        label = (
                            f"{name}_{[500, 2000, 5000][column]}" if column is not None else name
                        )
                        fields[label] = dict(
                            mean=float(x.mean()),
                            density_weighted_mean=float(np.sum(x * normalized)),
                            pearson_logL=float(np.corrcoef(x.ravel(), independent.ravel())[0, 1]),
                            unweighted_quantiles=np.quantile(x, [0.05, 0.5, 0.95]).tolist(),
                        )
                failed_diagnosis = dict(
                    event_id=event_id,
                    records=len(ids),
                    distance_km_range=[float(distance.min()), float(distance.max())],
                    native_minutes_range=[float(native.min()), float(native.max())],
                    native_log_jacobian=jac,
                    logL_quantiles=np.quantile(
                        independent, [0, 0.01, 0.1, 0.5, 0.9, 0.99, 1]
                    ).tolist(),
                    relative_chain_density_mass=normalized.sum(axis=1).tolist(),
                    per_chain_weight_concentration=[
                        float(w.sum() ** 2 / np.sum(w * w)) for w in weights
                    ],
                    top_weight_mass={
                        str(k): float(sorted_w[:k].sum()) for k in [1, 10, 50, 80, 100, 400]
                    },
                    parameters=fields,
                )
        for key, keep, saved in [
            ("aggregate_shared_influence", list(range(len(scores))), events["aggregate"]),
            (
                "aggregate_without_crossing_shared_influence",
                [i for i, e in enumerate(events["events"]) if e["event_id"] != data.CROSS_CHECK],
                events["aggregate_without_crossing_event"],
            ),
        ]:
            stream = oracle.shared_influence([scores[i] for i in keep], [sizes[i] for i in keep])
            error = mcse(stream)
            score = math.fsum(scores[i]["normalized_event_score"] / len(keep) for i in keep)
            # Failed supplemental results intentionally have no NPZ influence key.
            if key in arrays:
                close(arrays[key], stream, "shared influence before MCSE", atol=2e-8)
            close(saved["equal_event_score"], score, "equal-event native score")
            close(
                saved["mcse_equal_event_score"], error, "covariance-aware aggregateMCSE", atol=1e-11
            )
            require(
                saved["status"] == "needs_numerical_review"
                and saved["numerical_failures"] == ["event_numerical_review"],
                "primary failure not rescued by crossing supplement",
            )
    data._unchanged(ROOT, {**pins, **files, RAW: RAW_SHA})
    receipt = dict(
        status="independently_confirmed_frozen_development_direct_score_precision_failure",
        independent_checker=True,
        job=job,
        actual_new_sampler_calls=0,
        zero_cost_process=runtime,
        expected_released_lease_snapshot_entries=released_leases,
        primary_result_status=result["status"],
        model_spec=model,
        training_records=1040,
        held_records=151,
        events=event_oracles,
        training_reference=provenance,
        failed_event_diagnosis=failed_diagnosis,
        semantic_failed_result_replay_passed=True,
        all151_prediction_rows_independently_verified=True,
        max_PIT_error=max_pit,
        max_quantile_CDF_error=max_cdf,
        max_prediction_MCSE_error=max_mcse,
        other_targets_native_tables_parsed=False,
        other_models_or_posteriors_audited=False,
        full57_or_reserved_outcomes_parsed=False,
        development_check_outcomes_parsed=True,
        reserved_outcomes="sealed",
        thresholds_or_models_changed=False,
        accepted_check_review_created=False,
        qualification=(
            "Correct values with insufficient direct-density precision; "
            "no posterior mixing or model-validity certificate."
        ),
        source_gate_sha256=pins[fit.GATE],
        specification_freeze_sha256=pins[data.FREEZE],
        files={**pins, **files, RAW: RAW_SHA},
    )
    out = Path("/private/tmp/tsunami-development-case000-independent.json")
    with out.open("x") as f:
        json.dump(receipt, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    print(
        json.dumps(
            dict(
                receipt=str(out),
                sha256=sha256(out),
                events=14,
                records=151,
                failed=[e for e in event_oracles if not e["precision_passed"]],
                max_dense_error=max(e["dense"]["max_abs_error"] for e in event_oracles),
                max_PIT_error=max_pit,
                max_quantile_CDF_error=max_cdf,
                diagnosis=failed_diagnosis,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
