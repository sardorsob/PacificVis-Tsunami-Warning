"""Exact sequence refits for native-minute new-event predictive comparisons."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any, cast

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_evaluation import native_event_logpdf
from analysis.arrival.model_fit import verify_computational_gate
from analysis.arrival.model_prediction import marginal_report_predictions, posterior_components
from analysis.arrival.model_scale import build_scale_model, conditional_scale_effects
from analysis.arrival.model_scoring import aggregate_score, event_score, fold_score
from analysis.arrival.model_validation import conditional_event_effects, sampling_diagnostics
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import build_model, read_prior

CONSUMED = [
    "analysis/arrival/model_cv.py",
    "analysis/arrival/model_prediction.py",
    "analysis/arrival/model_scoring.py",
    "analysis/arrival/model_evaluation.py",
    "analysis/arrival/model_fit.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/models.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/model_validation.py",
    "analysis/arrival/model_validation_report.py",
    "analysis/arrival/evidence.py",
    "config/arrival-model-scoring-v1.toml",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "scripts/fit_arrival_sequence.py",
    "scripts/run_arrival_model_validation.py",
    "pyproject.toml",
    "uv.lock",
]


def verify_prediction_gate(root: Path, gate_path: Path, target: str, kind: str) -> None:
    if kind != "distance-scale":
        verify_computational_gate(root, gate_path, target)
        return
    gate = json.loads(gate_path.read_text())
    required = {
        "analysis/arrival/model_scale.py",
        "analysis/arrival/model_scale_validation.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/models.py",
        "analysis/arrival/model_validation.py",
        "config/arrival-model-priors-v1.toml",
        "config/arrival-model-contract-v1.toml",
        "pyproject.toml",
        "uv.lock",
        "artifacts/models/arrival-timing/distance-scale-prior-v1/review-acceptance.json",
        "artifacts/models/arrival-timing/distance-scale-validation-report-v1/recovery/output-checksums.json",
        "artifacts/models/arrival-timing/distance-scale-validation-report-v1/sbc/output-checksums.json",
    }
    if (
        target != "NCEI-native-duration"
        or gate.get("status") != "accepted"
        or gate.get("schema_version") != "arrival_ms4_scale_acceptance_v1"
        or not gate.get("independent_checker")
        or gate.get("reserved_outcomes") != "sealed"
        or not required <= set(gate.get("files", {}))
        or gate.get("prior_variant") != "base"
    ):
        raise ValueError("accepted candidate-specific inference validation required")
    for p, digest in gate["files"].items():
        if sha256(checked_path(root, p)) != digest:
            raise ValueError("candidate validation identity changed")


def fit_sequence_job(root: Path, job: dict[str, Any], output: Path, store: Path) -> None:
    if (
        output.exists()
        or store.exists()
        or not store.resolve().is_relative_to(root.resolve())
        or job.get("kind") not in {"pooled", "distance", "event", "distance-scale"}
        or job.get("target") not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or job.get("prior", "base") not in {"base", "wider"}
        or any(type(job[k]) is not int or not 1000 <= job[k] <= 4000 for k in ["draws", "tune"])
        or type(job.get("cores")) is not int
        or not 1 <= job["cores"] <= 2
        or type(job.get("seed")) is not int
        or not 0 <= job["seed"] <= 2**32 - 20
    ):
        raise ValueError("new paths and bounded source-specific sequence job required")
    gate = checked_path(root, job["gate"])
    verify_prediction_gate(root, gate, job["target"], job["kind"])
    pins = {p: sha256(root / p) for p in CONSUMED}
    pins[job["gate"]] = sha256(gate)
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    folds = [f for f in sequence_folds(lane) if f.sequence_id == job["sequence"]]
    if len(folds) != 1:
        raise ValueError("exact frozen exploration sequence required")
    fold = folds[0]
    if set(lane.event_ids[int(i)] for i in fold.train) & {
        lane.event_ids[int(i)] for i in fold.test
    }:
        raise ValueError("training/held-out event overlap")
    prior = read_prior(root, lane.target, job.get("prior", "base"))
    model = (
        build_scale_model(lane, prior, indices=fold.train)
        if job["kind"] == "distance-scale"
        else build_model(
            lane, prior, kind=job["kind"], indices=fold.train, parameterization="marginal"
        )
    )
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        {
            "code_and_config": pins,
            "source_files": frozen,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    write_json(
        output / "membership.json",
        {
            "train": [lane.record_ids[int(i)] for i in fold.train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": fold.sequence_id,
        },
    )
    started = time.monotonic()
    with model:
        tree = pm.sample(
            draws=job["draws"],
            tune=job["tune"],
            chains=4,
            cores=job["cores"],
            random_seed=job["seed"],
            target_accept=0.95,
            progressbar=False,
        )
    tree.to_netcdf(store)
    posterior = cast(Any, tree["posterior"])
    if job["kind"] in {"event", "distance-scale"}:
        keys = [
            "alpha",
            "beta",
            "tau_event",
            "sigma_anchor" if job["kind"] == "distance-scale" else "sigma",
        ]
        hyper = {p: posterior[p].values for p in keys}
        conditional = (
            conditional_scale_effects
            if job["kind"] == "distance-scale"
            else conditional_event_effects
        )
        effects, events = conditional(lane, hyper, indices=fold.train, seed=job["seed"] + 1)
        posterior["event_effect"] = xr.DataArray(
            effects, dims=("chain", "draw", "event"), coords={"event": events}
        )
        tree.to_netcdf(store, mode="w")
    diagnostics, table = sampling_diagnostics(tree)
    table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
    write_json(output / "diagnostics.json", diagnostics)
    result = {
        "job": job,
        "diagnostics": diagnostics,
        "posterior": str(store.relative_to(root)),
        "posterior_sha256": sha256(store),
        "code_and_config": pins,
        "elapsed_seconds": time.monotonic() - started,
        "reserved_outcomes": "sealed",
    }
    if not diagnostics["screen_passed"]:
        write_json(output / "result.json", {**result, "status": "diagnostic_failure"})
        return
    mean, sigma, tau = posterior_components(posterior, job["kind"], lane.distance_km[fold.test])
    events = sorted({lane.event_ids[int(i)] for i in fold.test})
    densities, scores, sizes = [], [], []
    for event in events:
        mask = np.array([lane.event_ids[int(i)] == event for i in fold.test])
        ids = fold.test[mask]
        density = native_event_logpdf(
            lane.y[ids],
            lane.reference_minutes[ids],
            lane.target,
            mean[..., mask],
            sigma[..., mask],
            tau,
        )
        score, _ = event_score(density, records=len(ids))
        scores.append({"event_id": event, "sequence": fold.sequence_id, **score})
        densities.append(density)
        sizes.append(len(ids))
    fold_summary = fold_score(np.stack(densities), np.asarray(sizes))
    tolerance = tomllib.loads((root / "config/arrival-model-scoring-v1.toml").read_text())
    precision = all(
        s["normalized_mcse"] <= tolerance["max_event_score_mcse_nats_per_record"]
        and s["density_weight_concentration_ess"]
        >= tolerance["minimum_density_weight_concentration_ess"]
        for s in scores
    )
    write_table(output / "event-joint-scores.csv", scores)
    predictions = marginal_report_predictions(
        lane.response[fold.test], mean, sigma, tau, lane.reference_minutes[fold.test], lane.target
    )
    write_table(
        output / "held-out-record-predictions.csv",
        [
            {
                "record_id": lane.record_ids[int(i)],
                "event_id": lane.event_ids[int(i)],
                "sequence": fold.sequence_id,
                "distance_km": float(lane.distance_km[i]),
                "seen_site_in_training": bool(fold.seen_site[j]),
                "observed_minutes": float(lane.y[i]),
                **{key: float(value[j]) for key, value in predictions.items()},
            }
            for j, i in enumerate(fold.test)
        ],
    )
    tree["heldout_event_density"] = xr.DataTree(
        xr.Dataset(
            {"native_log_density": (("event", "chain", "draw"), np.stack(densities))},
            coords={"event": events},
        )
    )
    tree.to_netcdf(store, mode="w")
    if any(sha256(root / p) != digest for p, digest in pins.items()):
        raise ValueError("prediction source changed during fit")
    result.update(
        {
            "status": "computed_pending_review" if precision else "score_precision_failure",
            "posterior_sha256": sha256(store),
            "score_precision_passed": precision,
            "fold_score": fold_summary,
            "training_records": len(fold.train),
            "heldout_records": len(fold.test),
            "heldout_events": len(events),
            "elapsed_seconds": time.monotonic() - started,
        }
    )
    write_json(output / "result.json", result)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def summarize_sequence_scores(root: Path, fits: list[Path], output: Path) -> None:
    """Verify fold membership and consume the frozen aggregate precision screen."""
    if output.exists() or not fits:
        raise ValueError("new output and at least one exact refit required")
    results = [json.loads((p / "result.json").read_text()) for p in fits]
    first = results[0]["job"]
    signature = {k: first.get(k, "base") for k in ["kind", "target", "prior"]}
    lanes, _ = load_lanes(root)
    lane = lanes[first["target"]]
    expected = {f.sequence_id: f for f in sequence_folds(lane)}
    used, seeds, folds, events, records = set(), set(), [], [], []
    pins = {p: sha256(root / p) for p in CONSUMED}
    for p, result in zip(fits, results, strict=True):
        job = result["job"]
        sequence = job["sequence"]
        if (
            sequence in used
            or job["seed"] in seeds
            or sequence not in expected
            or {k: job.get(k, "base") for k in signature} != signature
            or result["status"] not in {"computed_pending_review", "score_precision_failure"}
            or not result["diagnostics"]["screen_passed"]
        ):
            raise ValueError("inconsistent or failed sequence result")
        used.add(sequence)
        seeds.add(job["seed"])
        fold = expected[sequence]
        membership = json.loads((p / "membership.json").read_text())
        if membership != {
            "train": [lane.record_ids[int(i)] for i in fold.train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": sequence,
        }:
            raise ValueError("frozen fold membership changed")
        posterior = checked_path(root, result["posterior"])
        if sha256(posterior) != result["posterior_sha256"] or any(
            sha256(checked_path(root, k)) != v for k, v in result["code_and_config"].items()
        ):
            raise ValueError("sequence fit source/posterior identity changed")
        for name, digest in json.loads((p / "output-checksums.json").read_text()).items():
            if sha256(p / name) != digest:
                raise ValueError("sequence output changed")
        event_rows = read_rows(p / "event-joint-scores.csv")
        predicted = read_rows(p / "held-out-record-predictions.csv")
        if (
            {r["event_id"] for r in event_rows} != {lane.event_ids[int(i)] for i in fold.test}
            or len(event_rows) != result["heldout_events"]
            or [r["record_id"] for r in predicted] != [lane.record_ids[int(i)] for i in fold.test]
        ):
            raise ValueError("sequence score/record identity mismatch")
        folds.append(
            {**result["fold_score"], "event_precision_passed": result["score_precision_passed"]}
        )
        events.extend(event_rows)
        records.extend(predicted)
        pins[str((p / "output-checksums.json").relative_to(root))] = sha256(
            p / "output-checksums.json"
        )
    tolerances = tomllib.loads((root / "config/arrival-model-scoring-v1.toml").read_text())
    summary = aggregate_score(folds, max_mcse=tolerances["max_primary_score_mcse_nats_per_record"])
    summary.update(
        {
            **signature,
            "complete": used == set(expected),
            "planned_sequence_refits": len(expected),
            "sampling_uncertainty": "not_in_MCSE; paired_sequence_clusters_for_comparisons",
            "reserved_outcomes": "sealed",
        }
    )
    summary["eligible_for_comparison"] = summary["complete"] and summary["precision_passed"]
    if not np.isclose(
        summary["equal_event_score"],
        np.mean([float(e["normalized_event_score"]) for e in events]),
        atol=1e-12,
    ):
        raise ValueError("equal-event fold aggregation mismatch")
    output.mkdir(parents=True)
    write_json(output / "summary.json", summary)
    write_table(output / "event-joint-scores.csv", events)
    write_table(output / "held-out-record-predictions.csv", records)
    write_json(output / "inputs.json", pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
