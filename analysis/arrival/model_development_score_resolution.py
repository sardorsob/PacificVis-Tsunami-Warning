"""Fixed zero-MCMC numerical resolution of the first frozen NCEI event score.

Only the BASE Normal curved model and the original 1,040 training/151 check
records are admitted. Original predictions and passing direct event scores stay
immutable. Compact stream receipts allow one explicit cold replay; ordinary
admission verifies every source/artifact byte without repeating quadrature.
"""

# pyright: basic
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import numpy as np
import xarray as xr
from scipy import special, stats
from threadpoolctl import threadpool_limits

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival.evidence import sha256
from analysis.arrival.model_data import VREF_KM_MIN
from analysis.arrival.model_development_scoring import _diagnostics, direct_event_score

GATE = data.ART + "development-numerical-resolution-design-v1/review-acceptance.json"
OUTPUT = data.ART + "development-score-resolution-v1"
CASE_ID = "case-000"
CASE_OUTPUT = OUTPUT + "/" + CASE_ID
COLD_REVIEW = OUTPUT + "/cold-replay-review.json"
REVIEW = OUTPUT + "/review-acceptance.json"
COLD_REVIEW_STATUS = "accepted_frozen_development_score_cold_replay"
REVIEW_STATUS = "accepted_frozen_development_case0_resolution"
ORIGINAL_STATE_SHA = "8369712a58ef2d1c28527a6850fb8769b684147bbad0c12bf469d3e03907ace8"
UNVERIFIED = "needs_independent_cold_replay"
ORIGINAL = fit.CHECK_OUTPUT + "/jobs/dev-ncei-mean-curvature-selected-check"
RAW = "data/processed/models/mean-curvature-sequence-v1/fold-014/00-training.nc"
RAW_SHA = "81cb836d8c6aa48d5b6a1095330090c43f73079da1c6c7bec5fb4382c4f473bb"
TRAIN = data.TARGET_FILES["NCEI-native-duration"]
CHECK = data.CHECK_FILES["NCEI-native-duration"]
EVENT = "usp0008rpa"
MODEL_KEY = "NCEI-native-duration:mean-curvature:selected"
SUCCESS = "computed_pending_scientific_review"
UNRESOLVED = "needs_numerical_review"
METHOD = "exact_Normal_coefficient_event_marginal_importance_QMC_v1"
SELF = "analysis/arrival/model_development_score_resolution.py"
CLI = "scripts/resolve_arrival_development_score.py"
TEST = "tests/test_arrival_model_development_score_resolution.py"
CONSUMED = tuple(sorted(set(fit.CONSUMED) | {SELF, CLI, TEST}))
PRIOR_SD = np.array([0.5, 0.25, 0.5])
BASE_SPEC = dict(
    base_prior_sd=dict(alpha_sd=0.5, beta_sd=0.25, gamma_sd=0.5, sigma_sd=0.4, tau_sd=0.4),
    kind="mean-curvature",
    prior_variant="base",
    role="selected",
    wider_prior_sd=None,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def protocol() -> dict[str, Any]:
    return dict(
        method=METHOD,
        case_id=CASE_ID,
        event_id=EVENT,
        model_key=MODEL_KEY,
        levels=[65536, 262144],
        proposal_df=[5, 9],
        scrambles=[2996110800 + 100 * r for r in range(4)],
        sobol_dimensions=5,
        stream_block_size=4096,
        arithmetic_batch_size=256,
        proposal="training_only_logtheta_mean_and_unbiased_covariance_variance_matched_t",
        hyperparameter_order=["sigma_500", "sigma_2000", "sigma_5000", "tau_event"],
        training_records=1040,
        check_records=151,
        event_records=20,
        training_draws=8000,
        coefficient_normal_sd=PRIOR_SD.tolist(),
        scale_halfnormal_sd=[0.4] * 4,
        native_jacobian="held_event_once_training_constant_cancels",
        mcse_max=0.005,
        mcse_method="max_paired_pooled_ratio_delta_and_replicate_logratio_SE",
        cross_proposal_dependence="common_Sobol_scrambles_not_independent_evidence",
        weight_concentration_min=100.0,
        agreement_max=0.0005,
        replicate_range="diagnostic_only_range_over_MCSE_bounded_by_2sqrt6",
        aggregate_mcse_max=0.002,
        aggregate_mcse="triangle_bound_old_shared_part_plus_QMC_part",
        final_proposal_df=5,
        crosscheck_proposal_df=9,
        no_clipping=True,
        no_reseed=True,
        no_adaptive_proposal=True,
        no_mcmc=True,
    )


def resources() -> dict[str, Any]:
    return {
        **fit.resources(),
        "chains": 0,
        "draws": 0,
        "tune": 0,
        "cores": 2,
        "sampler_call_slots": 0,
    }


def case_paths(root, job=None):
    if job is not None:
        require(job == job_descriptor(), "literal sole numerical-resolution job required")
    return root / CASE_OUTPUT, None


def job_descriptor() -> dict[str, Any]:
    return dict(
        id=CASE_ID,
        order=0,
        role="numerical_score_resolution",
        model_key=MODEL_KEY,
        event_id=EVENT,
        protocol_sha256=fingerprint(protocol()),
        sampler_calls=0,
    )


def _new_json(path, value):
    payload = encoded(value)
    require(len(payload) <= resources()["file_max_bytes"], "per-file resource allocation exceeded")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def design_matrix(distance):
    distance = np.asarray(distance, dtype=float)
    require(
        distance.ndim == 1 and np.isfinite(distance).all() and (distance > 0).all(),
        "finite positive distance design required",
    )
    return np.column_stack(
        [
            np.ones(len(distance)),
            np.log(distance / 1000),
            np.log((distance + 500) / (1.5 * distance)),
        ]
    )


def weights(distance):
    design_matrix(distance)
    return np.column_stack(
        [np.interp(np.log(distance), np.log([500, 2000, 5000]), np.eye(3)[j]) for j in range(3)]
    )


def training_conditional(design, response, events, anchor_weights, theta):
    """Normalized Gaussian training marginal and coefficient conditional."""
    theta = np.asarray(theta, dtype=float)
    require(
        theta.ndim == 2 and theta.shape[1] == 4 and np.isfinite(theta).all() and (theta > 0).all(),
        "four finite strictly positive hyperparameters required",
    )
    require(
        design.shape == (len(response), 3)
        and anchor_weights.shape == (len(response), 3)
        and len(events) == len(response)
        and np.isfinite(design).all()
        and np.isfinite(response).all(),
        "aligned finite training arrays required",
    )
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        sigma = theta[:, :3] @ anchor_weights.T
        tau = theta[:, 3]
        precision = np.broadcast_to(np.diag(1 / PRIOR_SD**2), (len(theta), 3, 3)).copy()
        rhs = np.zeros((len(theta), 3))
        quadratic = np.zeros(len(theta))
        logdet = np.zeros(len(theta))
        for event in np.unique(events):
            take = events == event
            x, y = design[take], response[take]
            variance = sigma[:, take] ** 2
            w = 1 / variance
            wx = np.einsum("bi,ij->bj", w, x)
            wy = w @ y
            denominator = 1 + tau**2 * w.sum(axis=1)
            factor = tau**2 / denominator
            precision += np.einsum("bi,ij,ik->bjk", w, x, x)
            precision -= factor[:, None, None] * wx[:, :, None] * wx[:, None, :]
            rhs += np.einsum("bi,ij,i->bj", w, x, y) - factor[:, None] * wx * wy[:, None]
            quadratic += w @ (y * y) - factor * wy**2
            logdet += np.log(variance).sum(axis=1) + np.log(denominator)
        mean = np.linalg.solve(precision, rhs[..., None])[..., 0]
        covariance = np.linalg.inv(precision)
        sign, ld = np.linalg.slogdet(precision)
        require((sign == 1).all(), "positive coefficient precision required")
        evidence = -0.5 * (
            len(response) * np.log(2 * np.pi)
            + logdet
            + 2 * np.log(PRIOR_SD).sum()
            + ld
            + quadratic
            - np.sum(rhs * mean, axis=1)
        )
    require(
        all(np.isfinite(v).all() for v in [evidence, mean, covariance]),
        "unrepresentable Gaussian training evidence",
    )
    return evidence, mean, covariance


def predictive_loglik(design, response, native, anchor_weights, theta, mean, covariance):
    require(
        np.isfinite(native).all() and (native > 0).all(),
        "positive finite held native values required",
    )
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        cov = np.einsum("ij,bjk,lk->bil", design, covariance, design) + theta[:, 3, None, None] ** 2
        index = np.arange(len(response))
        cov[:, index, index] += (theta[:, :3] @ anchor_weights.T) ** 2
        residual = response[None, :] - np.einsum("ij,bj->bi", design, mean)
        factor = np.linalg.cholesky(cov)
        z = np.linalg.solve(factor, residual[..., None])[..., 0]
        value = (
            -0.5
            * (
                len(response) * np.log(2 * np.pi)
                + 2 * np.log(np.diagonal(factor, axis1=1, axis2=2)).sum(axis=1)
                + (z * z).sum(axis=1)
            )
            - np.log(native).sum()
        )
    require(np.isfinite(value).all(), "unrepresentable integrated native event density")
    return value


def logscale_prior(logtheta):
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        theta = np.exp(logtheta)
        value = 4 * (np.log(2) - 0.5 * np.log(2 * np.pi) - np.log(0.4))
        value = value - 0.5 * np.sum((theta / 0.4) ** 2, axis=1) + logtheta.sum(axis=1)
    require(
        np.isfinite(value).all() and (theta > 0).all(), "unrepresentable proper prior/log Jacobian"
    )
    return value


def proposal_from_training(theta):
    require(
        theta.shape == (8000, 4) and np.isfinite(theta).all() and (theta > 0).all(),
        "original four-chain2000-draw positive training hyperparameters required",
    )
    logs = np.log(theta)
    mean = logs.mean(axis=0)
    cov = np.cov(logs, rowvar=False, ddof=1)
    np.linalg.cholesky(cov)
    return dict(
        mean=mean.tolist(),
        covariance=cov.tolist(),
        source="original_training_hyperparameters_only",
        training_posterior_sha256=RAW_SHA,
    )


def proposal_nodes(uniform, proposal, df):
    require(
        df in protocol()["proposal_df"]
        and uniform.shape[1] == 5
        and np.isfinite(uniform).all()
        and (uniform > 0).all()
        and (uniform < 1).all(),
        "fixed proposal and strictly interior Sobol nodes; no endpoint repair",
    )
    mean = np.asarray(proposal["mean"])
    covariance = np.asarray(proposal["covariance"])
    shape = covariance * (df - 2) / df
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        nodes = mean + (special.ndtri(uniform[:, :4]) @ np.linalg.cholesky(shape).T) / np.sqrt(
            stats.chi2.ppf(uniform[:, 4], df)[:, None] / df
        )
        logq = stats.multivariate_t.logpdf(nodes, loc=mean, shape=shape, df=df)
    require(
        np.isfinite(nodes).all() and np.isfinite(logq).all(),
        "unrepresentable proposal nodes/density",
    )
    return nodes, logq


def empty_sum() -> dict[str, Any]:
    return dict(count=0, log_sum=None, log_sum_squares=None, maximum=None)


def update_sum(total, values):
    values = np.asarray(values)
    require(
        values.ndim == 1 and len(values) > 0 and np.isfinite(values).all(),
        "retain every finite quadrature weight; no dropping/clipping",
    )
    first = float(cast(Any, special.logsumexp)(values))
    second = float(cast(Any, special.logsumexp)(2 * values))
    return dict(
        count=total["count"] + len(values),
        log_sum=first if total["count"] == 0 else float(np.logaddexp(total["log_sum"], first)),
        log_sum_squares=second
        if total["count"] == 0
        else float(np.logaddexp(total["log_sum_squares"], second)),
        maximum=float(max(values.max(), total["maximum"]))
        if total["count"]
        else float(values.max()),
    )


def sum_summary(total):
    require(total["count"] > 0, "nonempty integration prefix required")
    return dict(
        log_integral=total["log_sum"] - math.log(total["count"]),
        concentration=math.exp(2 * total["log_sum"] - total["log_sum_squares"]),
        maximum_normalized_weight=math.exp(total["maximum"] - total["log_sum"]),
    )


def numeric_block(case, logtheta):
    theta = np.exp(logtheta)
    train, mean, cov = training_conditional(
        case["x"], case["response"], case["events"], case["w"], theta
    )
    prediction = predictive_loglik(
        case["new_x"], case["new_response"], case["new_native"], case["new_w"], theta, mean, cov
    )
    return train + logscale_prior(logtheta), prediction


def library_versions() -> dict[str, Any]:
    return {
        name: importlib.metadata.version(name)
        for name in ["numpy", "scipy", "xarray", "h5netcdf", "threadpoolctl"]
    }


def _resource_check(output, started, clock=time.monotonic):
    require(clock() - started <= resources()["timeout_seconds"], "numerical resolution timeout")
    paths = list(output.rglob("*"))
    require(all(not p.is_symlink() for p in paths), "symlink in numerical output")
    sizes = [p.stat().st_size for p in paths if p.is_file()]
    require(
        all(n <= resources()["file_max_bytes"] for n in sizes)
        and sum(sizes) <= resources()["job_max_bytes"],
        "numerical job/file resource limit",
    )


def _integrate(
    case, proposal, emit: Callable[[str, dict[str, Any]], None], check: Callable[[], None]
):
    """Fixed nested streams; emit a compact immutable receipt after every block."""
    cfg = protocol()
    prefixes = []
    block_count = 0
    for df in cfg["proposal_df"]:
        for rep, seed in enumerate(cfg["scrambles"]):
            engine = cast(Any, stats.qmc.Sobol)(5, scramble=True, seed=seed)
            denominator, numerator = empty_sum(), empty_sum()
            digest = hashlib.sha256()
            for first in range(0, max(cfg["levels"]), cfg["stream_block_size"]):
                check()
                size = min(cfg["stream_block_size"], max(cfg["levels"]) - first)
                uniform = engine.random(size)
                nodes, logq = proposal_nodes(uniform, proposal, df)
                train = np.empty(size)
                predictive = np.empty(size)
                for a in range(0, size, cfg["arithmetic_batch_size"]):
                    b = min(a + cfg["arithmetic_batch_size"], size)
                    train[a:b], predictive[a:b] = numeric_block(case, nodes[a:b])
                logden = train - logq
                lognum = logden + predictive
                denominator = update_sum(denominator, logden)
                numerator = update_sum(numerator, lognum)
                block_hash = hashlib.sha256()
                for values in [uniform, nodes, logq, logden, lognum]:
                    block_hash.update(np.ascontiguousarray(values, dtype="<f8").tobytes())
                digest.update(bytes.fromhex(block_hash.hexdigest()))
                block = dict(
                    df=df,
                    replicate=rep,
                    seed=seed,
                    first=first,
                    count=size,
                    last_exclusive=first + size,
                    block_sha256=block_hash.hexdigest(),
                    cumulative_stream_sha256=digest.hexdigest(),
                    training=denominator,
                    numerator=numerator,
                    probes=[
                        dict(
                            offset=i,
                            uniform=uniform[i].tolist(),
                            logtheta=nodes[i].tolist(),
                            logq=float(logq[i]),
                            training_logweight=float(logden[i]),
                            numerator_logweight=float(lognum[i]),
                        )
                        for i in [0, size - 1]
                    ],
                )
                emit(f"blocks/df{df}-rep{rep}-{first:06d}.json", block)
                block_count += 1
                if first + size in cfg["levels"]:
                    den, num = sum_summary(denominator), sum_summary(numerator)
                    joint = num["log_integral"] - den["log_integral"]
                    prefixes.append(
                        dict(
                            df=df,
                            replicate=rep,
                            seed=seed,
                            n=first + size,
                            training=den,
                            numerator=num,
                            joint_log_predictive=joint,
                            normalized_score=joint / cfg["event_records"],
                            cumulative_stream_sha256=digest.hexdigest(),
                        )
                    )
                check()
    return dict(
        prefixes=prefixes,
        blocks=block_count,
        unique_nodes=len(cfg["proposal_df"]) * len(cfg["scrambles"]) * max(cfg["levels"]),
    )


def integrate(case, proposal, emit, check):
    """Identical bounded BLAS policy for execution and one-time cold replay."""
    with threadpool_limits(limits=2):
        return _integrate(case, proposal, emit, check)


def summarize_integration(stream) -> dict[str, Any]:
    cfg = protocol()
    results = []
    for df in cfg["proposal_df"]:
        for n in cfg["levels"]:
            reps = [r for r in stream["prefixes"] if r["df"] == df and r["n"] == n]
            require(
                len(reps) == 4 and [r["replicate"] for r in reps] == list(range(4)),
                "all four literal scramble prefixes required",
            )
            scores = np.array([r["normalized_score"] for r in reps])
            logratio_mcse = float(scores.std(ddof=1) / 2)
            num = np.array([r["numerator"]["log_integral"] for r in reps])
            den = np.array([r["training"]["log_integral"] for r in reps])
            paired = (
                np.exp(num - cast(Any, special.logsumexp)(num) + np.log(4))
                - np.exp(den - cast(Any, special.logsumexp)(den) + np.log(4))
            ) / cfg["event_records"]
            paired_mcse = float(paired.std(ddof=1) / 2)
            mcse = max(paired_mcse, logratio_mcse)
            joint = float(cast(Any, special.logsumexp)(num) - cast(Any, special.logsumexp)(den))
            ht = min(r["training"]["concentration"] for r in reps)
            hn = min(r["numerator"]["concentration"] for r in reps)
            results.append(
                dict(
                    df=df,
                    n=n,
                    replicates=reps,
                    joint_log_predictive=joint,
                    normalized_score=joint / cfg["event_records"],
                    replicate_mcse_normalized=mcse,
                    paired_pooled_ratio_delta_mcse=paired_mcse,
                    replicate_logratio_mcse=logratio_mcse,
                    mcse_method=cfg["mcse_method"],
                    replicate_score_range=float(np.ptp(scores)),
                    training_log_normalizer_range=float(np.ptp(den)),
                    numerator_log_normalizer_range=float(np.ptp(num)),
                    min_training_weight_concentration=ht,
                    min_numerator_weight_concentration=hn,
                    precision_passed=bool(
                        np.isfinite([mcse, joint, ht, hn]).all()
                        and mcse <= cfg["mcse_max"]
                        and min(ht, hn) >= cfg["weight_concentration_min"]
                    ),
                )
            )
    by = {(r["df"], r["n"]): r for r in results}
    refinement = [
        dict(
            df=df,
            discrepancy=abs(
                by[df, cfg["levels"][0]]["normalized_score"]
                - by[df, cfg["levels"][1]]["normalized_score"]
            ),
        )
        for df in cfg["proposal_df"]
    ]
    cross = [
        dict(n=n, discrepancy=abs(by[5, n]["normalized_score"] - by[9, n]["normalized_score"]))
        for n in cfg["levels"]
    ]
    for entry in refinement + cross:
        entry["passed"] = entry["discrepancy"] <= cfg["agreement_max"]
    selected = by[cfg["final_proposal_df"], max(cfg["levels"])]
    return dict(
        results=results,
        refinement=refinement,
        cross_proposal=cross,
        selected=selected,
        precision_passed=all(r["precision_passed"] for r in results)
        and all(r["passed"] for r in refinement + cross),
        replicate_range_is_independent_gate=False,
        unique_nodes=stream["unique_nodes"],
    )


FAILURE_REVIEW = data.ART + "development-check-diagnostics-v1/case-000/review-acceptance.json"
WORKER_FILES = {
    "direct-score-arrays.npz",
    "event-results.json",
    "held-out-record-predictions.csv",
    "inputs.json",
    "job.json",
    "membership.json",
    "output-checksums.json",
    "result.json",
}
ORIGINAL_FILES = {ORIGINAL + "/" + n for n in WORKER_FILES} | {
    ORIGINAL + "-spec.json",
    ORIGINAL + ".log",
    ORIGINAL + ".supervisor.json",
    fit.CHECK_OUTPUT + "/controller/check-plan.json",
    fit.GATE,
}
ORIGINAL_ATTEMPT = (
    fit.CHECK_OUTPUT + "/controller/attempts/check/dev-ncei-mean-curvature-selected-check.json"
)
ORIGINAL_CLOSURE = (
    data.ART + "development-check-diagnostics-v1/case-000/original-computation-closure.json"
)


def verify_gate(root: Path):
    """Metadata-only admission; never load a target table or native posterior."""
    root = root.resolve()
    gate = json.loads(data._path(root, GATE).read_text())
    require(
        gate.get("status") == "accepted_frozen_arrival_development_numerical_resolution_execution"
        and gate.get("independent_checker") is True
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("source_role") == "frozen_check_numerical_resolution"
        and gate.get("protocol") == protocol()
        and gate.get("resources") == resources()
        and gate.get("job") == job_descriptor()
        and gate.get("sampler_calls") == 0,
        "exact prospective zero-MCMC numerical-resolution Gate required",
    )
    files = gate.get("files", {})
    require(
        set(CONSUMED)
        | ORIGINAL_FILES
        | {
            data.FREEZE,
            fit.GATE,
            FAILURE_REVIEW,
            ORIGINAL_ATTEMPT,
            ORIGINAL_CLOSURE,
            TRAIN,
            CHECK,
            RAW,
        }
        <= set(files),
        "complete original failed case and numerical source closure required",
    )
    pins = {**files, GATE: sha256(root / GATE)}
    data._unchanged(root, pins)
    for key, path in [
        ("specification_freeze", data.FREEZE),
        ("original_execution_gate", fit.GATE),
        ("failure_review", FAILURE_REVIEW),
        ("original_raw", RAW),
    ]:
        require(
            gate.get(key) == path and gate.get(key + "_sha256") == pins[path],
            "literal prospective source identity required: " + key,
        )
    require(pins[RAW] == RAW_SHA, "exact original81cb training posterior required")
    original = fit.verify_gate(root, "check_evaluate")
    data._require(pins, original["files"])
    job = original["gate"]["jobs"][0]
    require(
        job
        == dict(
            id="dev-ncei-mean-curvature-selected-check",
            model_key=MODEL_KEY,
            order=0,
            role="check_evaluate",
            seed=2976110800,
            training_reference={"kind": "historical"},
        )
        and gate.get("original_job") == job
        and original["specs"][MODEL_KEY] == ("NCEI-native-duration", BASE_SPEC),
        "only frozen BASE Normal NCEI first check is eligible",
    )
    failure = data._json(root, pins, FAILURE_REVIEW)
    require(
        failure.get("status") == "accepted_frozen_development_initial_precision_failure"
        and failure.get("independent_checker") is True
        and failure.get("reserved_outcomes") == "sealed",
        "independent original failure and released-lease review required",
    )
    data._require(pins, failure["files"])
    original_files = {p: pins[p] for p in ORIGINAL_FILES}
    require(
        failure.get("persistent_original_files") == original_files,
        "all thirteen immutable original persistent files required",
    )
    closure = data._json(root, pins, ORIGINAL_CLOSURE)
    released = failure.get("released_ephemeral_files")
    require(
        isinstance(released, list)
        and len(released) == 1
        and released[0].get("path") == fit.CHECK_OUTPUT + "/controller/.controller.lock"
        and released[0].get("disposition") == "released_exclusive_lease"
        and released[0]["path"] not in pins
        and isinstance(released[0].get("sha256"), str)
        and len(released[0]["sha256"]) == 64,
        "released original lease is historical evidence, not a live source pin",
    )
    require(
        failure.get("job") == job
        and failure.get("new_sampler_calls") == 0
        and failure.get("prediction_rows_precision_passed") == 151
        and failure.get("usable_event_scores") == 13
        and failure.get("precision_failed_event_count") == 1
        and failure.get("accepted_check") is False
        and failure.get("completed_check") is False
        and failure.get("full57_outcomes_parsed") is False
        and failure.get("original_attempt_receipt") == ORIGINAL_ATTEMPT
        and failure.get("original_attempt_receipt_sha256") == pins[ORIGINAL_ATTEMPT]
        and closure.get("persistent_original_files") == original_files
        and closure.get("persistent_original_file_count") == 13
        and closure.get("released_ephemeral_files") == released
        and closure.get("original_attempt_receipt") == ORIGINAL_ATTEMPT
        and closure.get("original_attempt_receipt_sha256") == pins[ORIGINAL_ATTEMPT]
        and closure.get("sampler_calls_charged") == closure.get("sampler_calls_started") == 0,
        "exact failed case, released lease and zero-call original closure required",
    )
    original_inputs = data._json(root, pins, ORIGINAL + "/inputs.json")
    data._require(pins, original_inputs["files"])
    require(
        original_inputs.get("model_spec") == BASE_SPEC
        and original_inputs.get("specification_freeze_sha256") == pins[data.FREEZE],
        "unchanged original Normal priors and scientific freeze required",
    )
    expected = {
        p: original_files[ORIGINAL + "/" + p] for p in WORKER_FILES - {"output-checksums.json"}
    }
    require(
        data._json(root, pins, ORIGINAL + "/output-checksums.json") == expected,
        "exact original eight-file worker manifest required",
    )
    require(
        {p.name for p in (root / ORIGINAL).iterdir()} == WORKER_FILES,
        "unexpected original worker artifact; preserve for review",
    )
    return dict(
        root=root,
        gate=gate,
        files=pins,
        original_job=job,
        original_files=original_files,
        original_admission=original,
        failure_review=failure,
    )


def load_case(root, admission) -> dict[str, Any]:
    """Read the sole already-executed NCEI target; never use all-target loaders."""
    pins = admission["files"]
    membership = data._json(root, pins, ORIGINAL + "/membership.json")
    ids = membership["training_record_ids"]
    wanted = set(ids)
    require(
        len(ids) == len(wanted) == 1040 and len(membership["check_primary_ids"]) == 151,
        "literal original training/check counts required",
    )
    with data._path(root, TRAIN).open() as stream:
        rows = {
            r["record_id"]: {
                k: r[k]
                for k in [
                    "record_id",
                    "event_id",
                    "distance_km",
                    "reference_minutes",
                    "target_minutes",
                    "physical_site_id",
                ]
            }
            for r in csv.DictReader(stream)
            if r["record_id"] in wanted
        }
    require(set(rows) == wanted, "original training identities missing from frozen source")
    distance = np.array([float(rows[i]["distance_km"]) for i in ids])
    native = np.array([float(rows[i]["target_minutes"]) for i in ids])
    reference = distance / VREF_KM_MIN
    # Only this source's observed group and original hyperparameter draws are opened.
    with xr.open_dataset(root / RAW, group="observed_data", engine="h5netcdf") as observed:
        require(
            observed.record.values.tolist() == ids
            and set(observed.data_vars) == {"response", "native_minutes"},
            "exact original1040 native observation inventory required",
        )
        response = observed.response.values.copy()
        require(
            np.array_equal(observed.native_minutes.values, native)
            and np.allclose(response, np.log(native) - np.log(reference), atol=1e-12, rtol=0),
            "training native values or response transformation changed",
        )
    with (
        xr.open_dataset(root / RAW, group="posterior", engine="h5netcdf") as post,
        xr.open_dataset(root / RAW, group="sample_stats", engine="h5netcdf") as sample_stats,
    ):
        fit.references._native_protocol(post, sample_stats)
        require(
            set(post.data_vars) == {"alpha", "beta", "gamma", "tau_event", "sigma_anchor"}
            and post.scale_anchor_km.values.tolist() == [500, 2000, 5000],
            "literal original curved population/native anchor coordinates required",
        )
        theta = np.column_stack(
            [post.sigma_anchor.values.reshape(8000, 3), post.tau_event.values.reshape(8000)]
        )
        coordinates = dict(chain=post.chain.values.tolist(), draw=post.draw.values.tolist())
    proposal = proposal_from_training(theta)  # Frozen before held native rows are read.
    with data._path(root, CHECK).open() as stream:
        held = {r["record_id"]: r for r in csv.DictReader(stream)}
    require(
        len(held) == 151 and set(held) == set(membership["check_primary_ids"]),
        "all original151 NCEI check identities required",
    )
    with data._path(root, ORIGINAL + "/held-out-record-predictions.csv").open() as stream:
        predictions = list(csv.DictReader(stream))
    require(
        len(predictions) == 151
        and {r["record_id"] for r in predictions} == set(held)
        and all(r["prediction_precision_passed"] == "True" for r in predictions),
        "retain the exact151 previously passing prediction rows",
    )
    for row in predictions:
        source = held[row["record_id"]]
        require(
            source["event_id"] == row["event_id"]
            and source["physical_site_id"] == row["site_id"]
            and float(source["target_minutes"]) == float(row["observed_reported_minutes"])
            and float(source["distance_km"]) == float(row["distance_km"])
            and math.isclose(
                float(row["reference_minutes"]),
                float(row["distance_km"]) / VREF_KM_MIN,
                rel_tol=0,
                abs_tol=1e-10,
            ),
            "prediction source/native/design identity changed",
        )
    event_results = data._json(root, pins, ORIGINAL + "/event-results.json")
    require(len(event_results["events"]) == 14, "original fourteen event slots required")
    originals = []
    with np.load(
        data._path(root, ORIGINAL + "/direct-score-arrays.npz"), allow_pickle=False
    ) as arrays:
        require(
            np.array_equal(arrays["chain_coordinates"], coordinates["chain"])
            and np.array_equal(arrays["draw_coordinates"], coordinates["draw"]),
            "original shared posterior coordinates changed",
        )
        for number, item in enumerate(event_results["events"]):
            score = item["score"]
            event = item["event_id"]
            records = len(item["record_ids"])
            value = xr.DataArray(
                arrays[f"event_{number:03d}_native_loglikelihood"],
                dims=("chain", "draw"),
                coords=coordinates,
                attrs=score["metadata"],
            )
            replay = direct_event_score(value, records)
            require(
                {k: v for k, v in replay.items() if k != "joint_influence"} == score
                and np.array_equal(
                    replay["joint_influence"].values, arrays[f"event_{number:03d}_joint_influence"]
                ),
                "original event scores and shared influences must replay unchanged",
            )
            require(
                score["precision_passed"] == (event != EVENT),
                "only the original failed event may change",
            )
            originals.append(
                dict(
                    event_id=event,
                    records=records,
                    score=score,
                    influence=replay["joint_influence"].values.copy(),
                    record_ids=item["record_ids"],
                )
            )
    focus = next(e for e in originals if e["event_id"] == EVENT)
    require(focus["records"] == 20, "literal failed20-record event required")
    by_id = {r["record_id"]: r for r in predictions}
    new = [by_id[i] for i in focus["record_ids"]]
    nd = np.array([float(r["distance_km"]) for r in new])
    ny = np.array([float(r["observed_reported_minutes"]) for r in new])
    nr = np.array([float(r["reference_minutes"]) for r in new])
    require(
        not set(np.array([rows[i]["event_id"] for i in ids])) & {e["event_id"] for e in originals},
        "frozen training must omit every check event",
    )
    return dict(
        x=design_matrix(distance),
        response=response,
        events=np.array([rows[i]["event_id"] for i in ids]),
        w=weights(distance),
        new_x=design_matrix(nd),
        new_response=np.log(ny) - np.log(nr),
        new_native=ny,
        new_w=weights(nd),
        proposal=proposal,
        originals=originals,
        original_event_ids=event_results["expected_event_ids"],
        coordinates=coordinates,
    )


def combined_aggregates(case, resolution) -> dict[str, Any]:
    """Retain old shared covariance; use a conservative sum of numerical MCSEs."""
    if not resolution["precision_passed"]:
        return dict(
            primary=None,
            without_crossing_event=None,
            available=False,
            reason="unresolved_event_prevents_interpreted_aggregate",
        )
    selected = resolution["selected"]
    results = {}
    for key, excluded in [("primary", None), ("without_crossing_event", data.CROSS_CHECK)]:
        entries = [e for e in case["originals"] if e["event_id"] != excluded]
        old = [e for e in entries if e["event_id"] != EVENT]
        total = len(entries)
        require(
            total == (14 if excluded is None else 13) and len(old) == total - 1,
            "complete primary and crossing-supplement event slots required",
        )
        shared = np.sum([e["influence"] / e["records"] / total for e in old], axis=0)
        error, mixing, failures = _diagnostics(shared)
        qmc_error = selected["replicate_mcse_normalized"] / total
        bound = None if error is None else error + qmc_error
        score = math.fsum(
            [e["score"]["normalized_event_score"] / total for e in old]
            + [selected["normalized_score"] / total]
        )
        passed = not failures and bound is not None and bound <= protocol()["aggregate_mcse_max"]
        results[key] = dict(
            equal_event_score=score,
            events=total,
            original_direct_events=[e["event_id"] for e in old],
            resolved_event_id=EVENT,
            original_shared_part_mcse=error,
            qmc_part_mcse=qmc_error,
            mcse_triangle_bound=bound,
            functional_mixing_original_part=mixing,
            mcse_scope="conservative_sum_of_estimated_MCSEs_not_a_bias_certificate",
            precision_passed=passed,
            status=SUCCESS if passed else UNRESOLVED,
        )
    results["available"] = results["primary"]["precision_passed"]
    if not results["available"]:
        return dict(
            primary=None,
            without_crossing_event=None,
            available=False,
            reason="aggregate_numerical_precision_unresolved",
            diagnostic_estimates=results,
        )
    results["supplement_available"] = results["without_crossing_event"]["precision_passed"]
    if not results["supplement_available"]:
        results["without_crossing_event"] = dict(
            status=UNRESOLVED,
            precision_passed=False,
            equal_event_score=None,
            reason="supplement_only_numerical_precision_unresolved",
            diagnostic_estimate=results["without_crossing_event"],
        )
    return results


def _manifest(output):
    paths = sorted(p for p in output.rglob("*") if p.is_file())
    require(
        all(p.resolve() == p and not p.is_symlink() for p in paths), "regular output files only"
    )
    files = {str(p.relative_to(output)): sha256(p) for p in paths}
    _new_json(output / "output-checksums.json", files)
    return files


def _result(admission, resolution=None, aggregates=None, error=None) -> dict[str, Any]:
    passed = (
        resolution is not None
        and resolution["precision_passed"]
        and aggregates is not None
        and aggregates["available"]
    )
    return dict(
        schema_version=1,
        status=SUCCESS if passed else UNRESOLVED,
        source_role="frozen_check_numerical_resolution",
        method=METHOD,
        job=job_descriptor(),
        original_job=admission["original_job"],
        original_files=admission["original_files"],
        protocol_sha256=fingerprint(protocol()),
        execution_gate=GATE,
        execution_gate_sha256=admission["files"][GATE],
        original_predictions=dict(
            path=ORIGINAL + "/held-out-record-predictions.csv",
            sha256=admission["files"][ORIGINAL + "/held-out-record-predictions.csv"],
            rows=151,
            unchanged=True,
        ),
        original_direct_scores=dict(
            path=ORIGINAL + "/event-results.json",
            sha256=admission["files"][ORIGINAL + "/event-results.json"],
            retained_passing_events=13,
        ),
        original_shared_influences=dict(
            path=ORIGINAL + "/direct-score-arrays.npz",
            sha256=admission["files"][ORIGINAL + "/direct-score-arrays.npz"],
        ),
        training_posterior_sha256=RAW_SHA,
        sampler_calls=0,
        sampler_call_started=False,
        confirmation_outcomes_parsed=True,
        reserved_outcomes="sealed",
        quadrature_complete=resolution is not None,
        resolved_event_score=resolution["selected"] if resolution is not None and passed else None,
        diagnostic_estimate=resolution if not passed else None,
        aggregates=aggregates
        if passed
        else dict(
            available=False,
            primary=None,
            without_crossing_event=None,
            reason="numerical_resolution_unavailable",
        ),
        error=error,
    )


def run_resolution(root: Path, output: Path) -> dict[str, Any]:
    """Single bounded execution. Failures retain blocks; no implicit retry/resume."""
    root = root.resolve()
    output = output.absolute()
    require(
        output == root / CASE_OUTPUT and output.resolve() == output and not output.exists(),
        "new canonical case-000 output required; no overwrite/resume",
    )
    admission = verify_gate(root)
    output.mkdir(parents=True)
    started = time.monotonic()
    resolution = None
    aggregates = None
    error = None
    _new_json(output / "job.json", job_descriptor())
    _new_json(
        output / "inputs.json",
        dict(
            files=admission["files"],
            protocol=protocol(),
            resources=resources(),
            original_job=admission["original_job"],
        ),
    )
    try:
        case = load_case(root, admission)
        _new_json(output / "proposal.json", case["proposal"])
        _new_json(
            output / "runtime.json",
            dict(
                libraries=library_versions(),
                protocol=protocol(),
                source_gate_sha256=admission["files"][GATE],
                training_posterior_sha256=RAW_SHA,
                quadrature_is_not_mcmc=True,
                store_full_nodes=False,
            ),
        )

        def check():
            _resource_check(output, started)

        _new_json(
            output / "integration-start.json",
            dict(job=job_descriptor(), sampler_calls=0, protocol_sha256=fingerprint(protocol())),
        )
        stream = integrate(case, case["proposal"], lambda p, v: _new_json(output / p, v), check)
        _new_json(output / "stream-summary.json", stream)
        resolution = summarize_integration(stream)
        _new_json(output / "precision.json", resolution)
        aggregates = combined_aggregates(case, resolution)
        _new_json(output / "aggregate-diagnostics.json", aggregates)
        check()
        data._unchanged(root, admission["files"])
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
        resolution = None
        aggregates = None
    result = _result(admission, resolution, aggregates, error)
    _new_json(output / "result.json", result)
    _manifest(output)
    _resource_check(output, started)
    return result


def _read_bundle(root, admission):
    output = root / CASE_OUTPUT
    manifest_path = CASE_OUTPUT + "/output-checksums.json"
    manifest = json.loads(data._path(root, manifest_path).read_text())
    require(
        isinstance(manifest, dict) and {"job.json", "inputs.json", "result.json"} <= set(manifest),
        "complete terminal numerical bundle required",
    )
    require(
        all(
            isinstance(p, str)
            and not Path(p).is_absolute()
            and Path(p).as_posix() == p
            and not any(v in {".", ".."} for v in p.split("/"))
            for p in manifest
        ),
        "literal numerical artifact paths required",
    )
    allowed = {
        "job.json",
        "inputs.json",
        "proposal.json",
        "runtime.json",
        "result.json",
        "stream-summary.json",
        "precision.json",
        "aggregate-diagnostics.json",
        "integration-start.json",
    }
    cfg = protocol()
    block_names = {
        f"blocks/df{df}-rep{rep}-{first:06d}.json"
        for df in cfg["proposal_df"]
        for rep in range(4)
        for first in range(0, max(cfg["levels"]), cfg["stream_block_size"])
    }
    require(
        set(manifest) <= allowed | block_names, "unknown numerical artifact; preserve for review"
    )
    actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()}
    require(
        actual == set(manifest) | {"output-checksums.json"}
        and all(p.resolve() == p and not p.is_symlink() for p in output.rglob("*"))
        and all(p.is_file() or str(p.relative_to(output)) == "blocks" for p in output.rglob("*")),
        "exact numerical physical inventory required",
    )
    files = {CASE_OUTPUT + "/" + p: h for p, h in manifest.items()}
    files[manifest_path] = sha256(root / manifest_path)
    data._unchanged(root, files)
    require(
        sum((root / p).stat().st_size for p in files) <= resources()["job_max_bytes"]
        and all((root / p).stat().st_size <= resources()["file_max_bytes"] for p in files),
        "retained numerical resource allocation exceeded",
    )
    values = {p: json.loads((output / p).read_text()) for p in manifest}
    require(
        values["job.json"] == job_descriptor()
        and values["inputs.json"]
        == dict(
            files=admission["files"],
            protocol=protocol(),
            resources=resources(),
            original_job=admission["original_job"],
        ),
        "literal numerical job/input/source binding changed",
    )
    result = values["result.json"]
    require(
        result.get("status") in {SUCCESS, UNRESOLVED}
        and result.get("sampler_calls") == 0
        and result.get("sampler_call_started") is False,
        "typed zero-MCMC terminal result required",
    )
    if result.get("quadrature_complete"):
        require(
            set(manifest) == allowed | block_names, "all fixed numerical stream blocks required"
        )
        require(
            values["integration-start.json"]
            == dict(job=job_descriptor(), sampler_calls=0, protocol_sha256=fingerprint(protocol())),
            "literal zero-MCMC integration marker required",
        )
        require(
            values["runtime.json"]
            == dict(
                libraries=library_versions(),
                protocol=protocol(),
                source_gate_sha256=admission["files"][GATE],
                training_posterior_sha256=RAW_SHA,
                quadrature_is_not_mcmc=True,
                store_full_nodes=False,
            ),
            "fixed numerical runtime/library provenance changed",
        )
        prefixes = []
        for df in cfg["proposal_df"]:
            for rep, seed in enumerate(cfg["scrambles"]):
                digest = hashlib.sha256()
                for first in range(0, max(cfg["levels"]), cfg["stream_block_size"]):
                    block = values[f"blocks/df{df}-rep{rep}-{first:06d}.json"]
                    size = min(cfg["stream_block_size"], max(cfg["levels"]) - first)
                    require(
                        block["df"] == df
                        and block["replicate"] == rep
                        and block["seed"] == seed
                        and block["first"] == first
                        and block["count"] == size
                        and block["last_exclusive"] == first + size
                        and block["training"]["count"]
                        == block["numerator"]["count"]
                        == first + size,
                        "complete exact contiguous numerical stream required",
                    )
                    digest.update(bytes.fromhex(block["block_sha256"]))
                    require(
                        digest.hexdigest() == block["cumulative_stream_sha256"],
                        "numerical stream digest chain changed",
                    )
                    if first + size in cfg["levels"]:
                        den, num = sum_summary(block["training"]), sum_summary(block["numerator"])
                        joint = num["log_integral"] - den["log_integral"]
                        prefixes.append(
                            dict(
                                df=df,
                                replicate=rep,
                                seed=seed,
                                n=first + size,
                                training=den,
                                numerator=num,
                                joint_log_predictive=joint,
                                normalized_score=joint / cfg["event_records"],
                                cumulative_stream_sha256=digest.hexdigest(),
                            )
                        )
        stream = dict(
            prefixes=prefixes,
            blocks=len(block_names),
            unique_nodes=len(cfg["proposal_df"]) * 4 * max(cfg["levels"]),
        )
        require(values["stream-summary.json"] == stream, "numerical prefix summary changed")
        resolution = summarize_integration(stream)
        require(
            values["precision.json"] == resolution, "fixed numerical precision decision changed"
        )
        expected = _result(admission, resolution, values["aggregate-diagnostics.json"])
        require(result == expected, "typed numerical result/availability changed")
    else:
        require(
            result == _result(admission, error=result.get("error"))
            and result.get("error") is not None,
            "incomplete streams remain unresolved",
        )
    return dict(files=files, result=result, values=values)


def candidate_artifacts(root: Path, pins=None, accepted=None):
    """Unverified bytes/inventory only; never an accepted numerical result.

    Internal summary consistency does not prove that reported numbers reproduce
    the frozen computation. Only the explicit full replay and independent review
    can establish that; this API cannot authorize continuation.
    """
    root = root.resolve()
    admission = verify_gate(root)
    if pins is not None:
        data._require(pins, admission["files"])
    checked = _read_bundle(root, admission)
    if accepted is not None:
        require(
            accepted.get("files") == checked["files"],
            "immutable accepted numerical inventory changed",
        )
    data._unchanged(root, {**admission["files"], **checked["files"]})
    return dict(
        files=checked["files"],
        result=CASE_OUTPUT + "/result.json",
        status=UNVERIFIED,
        computed_status=checked["result"]["status"],
        semantics_verified=False,
        proof_scope="unverified_bytes_inventory_and_internal_consistency_only",
        sampler_calls=0,
        source_role="frozen_check_numerical_resolution",
        original_job=admission["original_job"],
    )


def _independent_anchors(root, admission, candidate):
    """Require two acyclic independent reviews of this exact candidate closure."""
    expected_sources = {p: admission["files"][p] for p in [SELF, CLI, TEST]}
    expected_replay = dict(
        passed=True,
        blocks=len(protocol()["proposal_df"])
        * 4
        * (max(protocol()["levels"]) // protocol()["stream_block_size"]),
        unique_nodes=len(protocol()["proposal_df"]) * 4 * max(protocol()["levels"]),
        sampler_calls=0,
    )
    closure = {**admission["files"], **candidate["files"]}
    for path, status in [(COLD_REVIEW, COLD_REVIEW_STATUS), (REVIEW, REVIEW_STATUS)]:
        require((root / path).is_file(), "needs_independent_cold_replay: missing " + path)
        review = json.loads(data._path(root, path).read_text())
        require(
            review.get("status") == status
            and review.get("independent_checker") is True
            and review.get("original_job") == admission["original_job"],
            "independent review of the exact original case required",
        )
        files = review.get("files", {})
        require(path not in files, "independent review must not pin itself")
        if path == COLD_REVIEW:
            require(
                REVIEW not in files
                and review.get("full_stream_replay") == expected_replay
                and review.get("sampler_calls") == 0
                and review.get("reserved_outcomes") == "sealed"
                and review.get("source_role") == "frozen_check_numerical_resolution"
                and review.get("job") == job_descriptor()
                and review.get("execution_gate") == GATE
                and review.get("execution_gate_sha256") == admission["files"][GATE]
                and review.get("protocol_sha256") == fingerprint(protocol())
                and review.get("worker_sources") == expected_sources
                and review.get("candidate_files") == candidate["files"]
                and review.get("computed_status") == candidate["computed_status"],
                "independent full fixed-stream replay must anchor exact source/candidate bytes",
            )
        else:
            resolved = candidate["computed_status"] == SUCCESS
            prediction = ORIGINAL + "/held-out-record-predictions.csv"
            result_path = CASE_OUTPUT + "/result.json"
            require(
                review.get("original_state_sha256") == ORIGINAL_STATE_SHA
                and review.get("specification_freeze_sha256") == admission["files"][data.FREEZE]
                and review.get("case0_outcome")
                == ("accepted_resolution" if resolved else "accepted_unresolved_gap")
                and review.get("primary_aggregate_available") is resolved
                and review.get("resolved_result") == (result_path if resolved else None)
                and review.get("resolved_result_sha256")
                == (candidate["files"][result_path] if resolved else None)
                and review.get("prediction_file") == prediction
                and review.get("prediction_sha256") == admission["files"][prediction],
                "typed science review must preserve outcome, original predictions and state",
            )
        data._require(files, closure)
        data._unchanged(root, files)
        closure = {**closure, **files, path: sha256(root / path)}
    return closure


def case_artifacts(root: Path, pins=None, accepted=None):
    """Trusted compact reuse only after an independently anchored cold replay."""
    root = root.resolve()
    candidate = candidate_artifacts(root, pins, accepted)
    admission = verify_gate(root)
    closure = _independent_anchors(root, admission, candidate)
    data._unchanged(root, closure)
    return {
        **candidate,
        "status": candidate["computed_status"],
        "semantics_verified": True,
        "proof_scope": "independent_cold_replay_plus_fresh_complete_bytes",
        "cold_replay_review": COLD_REVIEW,
        "cold_replay_review_sha256": closure[COLD_REVIEW],
        "scientific_review": REVIEW,
        "scientific_review_sha256": closure[REVIEW],
        "review_files": closure,
    }


def replay_resolution(root: Path):
    """Explicit one-time cold semantic replay, read-only; never invoked by cached proof."""
    root = root.resolve()
    candidate = candidate_artifacts(root)
    admission = verify_gate(root)
    bundle = _read_bundle(root, admission)
    require(bundle["files"] == candidate["files"], "candidate changed before cold replay")
    require(
        bundle["result"]["quadrature_complete"],
        "cold complete replay needs a finished fixed stream",
    )
    case = load_case(root, admission)
    require(case["proposal"] == bundle["values"]["proposal.json"], "training-only proposal changed")
    started = time.monotonic()
    compared = []

    def emit(name, value):
        require(
            value == bundle["values"][name], "cold regenerated numerical block differs: " + name
        )
        compared.append(name)

    stream = integrate(
        case, case["proposal"], emit, lambda: _resource_check(root / CASE_OUTPUT, started)
    )
    resolution = summarize_integration(stream)
    aggregate = combined_aggregates(case, resolution)
    require(
        stream == bundle["values"]["stream-summary.json"]
        and resolution == bundle["values"]["precision.json"]
        and aggregate == bundle["values"]["aggregate-diagnostics.json"]
        and _result(admission, resolution, aggregate) == bundle["result"],
        "cold numerical/aggregate semantic replay differs",
    )
    data._unchanged(root, {**admission["files"], **bundle["files"]})
    return dict(
        passed=True,
        blocks=len(compared),
        unique_nodes=stream["unique_nodes"],
        files=bundle["files"],
        status=bundle["result"]["status"],
        sampler_calls=0,
    )
