"""Native-unit sequence prediction for the same pooled/distance models via 1D evidence."""

# pyright: basic
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import numpy as np

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_fit import verify_computational_gate
from analysis.arrival.model_quadrature import RegressionQuadrature
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import read_prior

CONSUMED = [
    "analysis/arrival/model_analytic_baselines.py",
    "analysis/arrival/model_quadrature.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/model_fit.py",
    "analysis/arrival/model_validation_report.py",
    "analysis/arrival/models.py",
    "analysis/arrival/evidence.py",
    "scripts/score_arrival_regression.py",
    "config/arrival-model-contract-v1.toml",
    "config/arrival-model-priors-v1.toml",
    "config/arrival-model-scoring-v1.toml",
    "pyproject.toml",
    "uv.lock",
]


def run_analytic_baseline(
    root: Path,
    target: str,
    kind: str,
    gate: Path,
    output: Path,
    store: Path,
    *,
    max_folds: int | None = None,
) -> None:
    if (
        kind not in {"pooled", "distance"}
        or target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or output.exists()
        or store.exists()
        or not store.resolve().is_relative_to(root.resolve())
        or (max_folds is not None and (type(max_folds) is not int or max_folds < 1))
    ):
        raise ValueError("new paths and declared analytic Gaussian baseline required")
    verify_computational_gate(root, gate, target)
    lanes, frozen = load_lanes(root)
    lane = lanes[target]
    priors = read_prior(root, target, "base")
    columns = (
        np.ones((len(lane.rows), 1)) if kind == "pooled" else np.c_[np.ones(len(lane.rows)), lane.x]
    )
    sd = np.array(
        [priors["alpha_sd"]] if kind == "pooled" else [priors["alpha_sd"], priors["beta_sd"]]
    )
    pins = {
        p: sha256(root / p) for p in [*CONSUMED, *frozen["inputs"], str(gate.relative_to(root))]
    }
    tolerance = tomllib.loads((root / "config/arrival-model-scoring-v1.toml").read_text())
    folds = sequence_folds(lane)
    output.mkdir(parents=True)
    store.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "prior_variant": "base",
        },
    )
    write_json(
        output / "plan.json",
        {
            "target": target,
            "kind": kind,
            "sequences": [f.sequence_id for f in folds],
            "maximum_folds": len(folds),
            "per_integral_evaluation_cap": 80000,
            "integration": "analytic_Normal_coefficients_log_SD_quadrature",
            "monte_carlo_used": False,
            "reserved_outcomes": "sealed",
        },
    )
    scores = []
    predictions = []
    diagnostics = []
    membership = {}
    rawfiles = {}
    for f in folds[:max_folds]:
        if any(sha256(root / p) != h for p, h in pins.items()):
            raise ValueError("analytic fit inputs changed")
        model = RegressionQuadrature(
            lane.response[f.train], columns[f.train], sd, priors["sigma_sd"]
        )
        means, covs = model.conditional_coefficients(model.node_sigma)
        raw = store / (f"fold-{len(membership) + 1:02d}.npz")
        np.savez_compressed(
            raw,
            sigma=model.node_sigma,
            weight=model.node_weights,
            coefficient_mean=means,
            coefficient_covariance=covs,
        )
        rawfiles[str(raw.relative_to(root))] = sha256(raw)
        membership[f.sequence_id] = {
            "train": [lane.record_ids[int(i)] for i in f.train],
            "test": [lane.record_ids[int(i)] for i in f.test],
        }
        diag = {
            "sequence": f.sequence_id,
            "training_records": len(f.train),
            "heldout_records": len(f.test),
            "log_training_evidence": model.log_evidence,
            "rank": model.rank,
            "prior_design_condition": float(model.s.max() / model.s.min())
            if len(model.s)
            else None,
            "evidence_error_estimate": model.relative_error,
            "log_total_tail_fraction_bound": model.log_tail_fraction_bound,
            "normalizer_refinement": model.log_evidence_refinement,
            "node_normalizer_error": model.node_normalizer_error,
            "detected_peaks": len(model.peaks),
        }
        for event in sorted({lane.event_ids[int(i)] for i in f.test}):
            ids = np.array([i for i in f.test if lane.event_ids[int(i)] == event])
            score = model.joint_logpdf(lane.response[ids], columns[ids])
            jacobian = 0.0 if target == "T-CAL" else float(np.log(lane.y[ids]).sum())
            numerical_error = (
                score["log_error_estimate"]
                + score["tail_fraction_bound"]
                + score["refinement_change"]
                + score["direct_integral_agreement"]
            ) / len(ids)
            scores.append(
                {
                    "event_id": event,
                    "sequence": f.sequence_id,
                    "records": len(ids),
                    "joint_log_predictive": score["log_predictive"] - jacobian,
                    "normalized_event_score": (score["log_predictive"] - jacobian) / len(ids),
                    "normalized_numerical_error_estimate": numerical_error,
                    "direct_conditional_agreement_nats": score["direct_integral_agreement"],
                    "monte_carlo_used": False,
                    "precision_passed": numerical_error
                    <= tolerance["max_event_score_mcse_nats_per_record"],
                }
            )
        pred = model.marginal_predictions(lane.response[f.test], columns[f.test])
        diag["cdf_refinement_maximum"] = pred.pop("maximum_cdf_refinement_difference")
        for j, i in enumerate(f.test):
            predictions.append(
                {
                    "record_id": lane.record_ids[int(i)],
                    "event_id": lane.event_ids[int(i)],
                    "sequence": f.sequence_id,
                    "distance_km": float(lane.distance_km[i]),
                    "seen_site_in_training": bool(f.seen_site[j]),
                    "observed_minutes": float(lane.y[i]),
                    "pit": float(pred["pit"][j]),
                    **{
                        q: float(
                            pred[q][j]
                            if target == "T-CAL"
                            else np.exp(pred[q][j]) * lane.reference_minutes[i]
                        )
                        for q in ["q05", "q25", "q50", "q75", "q95"]
                    },
                }
            )
        diag["evaluations"] = model.evaluations
        diagnostics.append(diag)
        # Persist the completed prefix before continuing the next exact training fit.
        write_table(output / "event-joint-scores.csv", scores)
        write_table(output / "held-out-record-predictions.csv", predictions)
        write_table(output / "numerical-integration-diagnostics.csv", diagnostics)
        write_json(output / "sequence-membership.json", membership)
        write_json(output / "raw-posterior-nodes.json", rawfiles)
        print(f"{target} {kind}: {len(membership)}/{len(folds)} exact sequence fits", flush=True)
    complete = len(membership) == len(folds)
    error = float(np.mean([s["normalized_numerical_error_estimate"] for s in scores]))
    summary = {
        "target": target,
        "kind": kind,
        "events": len(scores),
        "sequence_fits": len(membership),
        "complete": complete,
        "equal_event_score": float(np.mean([s["normalized_event_score"] for s in scores])),
        "monte_carlo_used": False,
        "monte_carlo_standard_error": "not_applicable",
        "mean_numerical_error_estimate": error,
        "numerical_error_scope": (
            "quadrature_estimates_and_refinement_not_rigorous_floating_point_certificate"
        ),
        "precision_passed": all(s["precision_passed"] for s in scores)
        and error <= tolerance["max_primary_score_mcse_nats_per_record"],
        "scientific_acceptance": "pending_independent_review",
        "reserved_outcomes": "sealed",
    }
    summary["eligible_for_comparison"] = complete and summary["precision_passed"]
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("analytic fit inputs changed")
    write_json(output / "summary.json", summary)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
