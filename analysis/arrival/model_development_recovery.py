"""Two frozen known-truth full-design computation smokes per selected source.

These six cases provide neither SBC nor coverage/bias estimates. Historical
responses are stripped before generation. No model, truth, seed or dataset is
retuned or redrawn in response to a result; only Root supervises call budgets.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pymc as pm
import xarray as xr
from scipy import linalg, stats

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_curvature import simulate_curvature_response
from analysis.arrival.model_scale import simulate_scale_response
from analysis.arrival.model_sensitivity_fit import _summary_valid
from analysis.arrival.model_sensitivity_priors import _population_spec, build_sensitivity_model
from analysis.arrival.model_sensitivity_summary import _quantiles, summarize_posterior
from analysis.arrival.model_validation import sampling_diagnostics, simulate_response
from analysis.arrival.model_validation_report import write_table

GATE = data.ART + "full-development-recovery-design-v1/review-acceptance.json"
OUTPUT = data.ART + "full-development-recovery-v1"
STORE = "data/processed/models/arrival-development-recovery-v1"
SUCCESS = fit.SUCCESS
TARGETS = ("NCEI-native-duration", "T-OBS", "T-CAL")
TABLES = ("parameters", "derived", "curves", "conditional_ppc", "record_intervals")
CONSUMED = tuple(
    sorted(
        set(fit.CONSUMED)
        | {
            "analysis/arrival/model_development_recovery.py",
            "scripts/check_arrival_development_recovery.py",
            "tests/test_arrival_model_development_recovery.py",
            "analysis/arrival/model_validation.py",
            "analysis/arrival/model_curvature.py",
            "analysis/arrival/model_scale.py",
        }
    )
)


def _sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def protocol() -> dict[str, Any]:
    return dict(
        schema_version="frozen_full_development_computation_smoke_v1",
        scope="two_fixed_truth_cases_not_calibration_coverage_bias_or_physical_validity",
        design="full_development_primary_geodesic_original_exclusions_no_historical_response",
        seed_base=2966110800,
        lane_stride=10000,
        case_stride=100,
        simulator_offset=1,
        sampler_offset=2,
        conditional_offset=3,
        target_order=list(TARGETS),
        cases=["A", "B"],
        draws=2000,
        tune=1000,
        chains=4,
        cores=2,
        target_accept=0.95,
        backend="nutpie",
        summary_draws=800,
        oracle_positions=[[0, 0], [1, 1000], [3, 1999]],
        oracle_includes_truth=True,
        oracle_logp_atol=2e-7,
        oracle_uncorrected_logp_atol=1e-6,
        prior_normalizer_offset_bound=1e-6,
        prior_only_points=["truth", "truth_coefficients_plus_0.125_scale_positive_times1.125"],
        oracle_qualification=(
            "Uncorrected joint error is bounded independently; prior-only offsets "
            "are measured before joint evaluation, never fitted to likelihood error. "
            "Normal/HalfNormal symbolic log(sigma) dtype evidence is recorded."
        ),
        oracle_gradient_atol=2e-5,
        oracle_gradient_rtol=1e-7,
        interval_inclusion="descriptive_per_case_no_coverage_pass_rule",
        truth_templates={
            f"{target}:{kind}": {case: _truth(target, kind, case) for case in ["A", "B"]}
            for target in TARGETS
            for kind in (
                ["distance-scale", "mean-curvature"]
                if target == "NCEI-native-duration"
                else ["pooled", "distance", "event"]
            )
        },
        regeneration="no_reseed_no_clipping_no_automatic_retry",
    )


def _truth(target, kind, case):
    difficult = case == "B"
    if target == "NCEI-native-duration":
        if kind == "mean-curvature":
            return dict(
                alpha=0.15,
                beta=-0.05,
                gamma=0.5 if difficult else 0.0,
                tau_event=0.05 if difficult else 0.25,
                sigma_anchor=[0.6, 0.6, 0.1] if difficult else [0.3, 0.3, 0.3],
            )
        return dict(
            alpha=0.15,
            beta=-0.2 if difficult else -0.05,
            tau_event=0.05 if difficult else 0.2,
            sigma_anchor=[0.6, 0.3, 0.08] if difficult else [0.3, 0.3, 0.3],
        )
    values = (
        dict(
            alpha=-15.0,
            beta=10.0 if difficult else 5.0,
            tau_event=2.5 if difficult else 10.0,
            sigma=40.0 if difficult else 20.0,
        )
        if target == "T-CAL"
        else dict(
            alpha=0.15,
            beta=-0.2 if difficult else -0.05,
            tau_event=0.05 if difficult else 0.2,
            sigma=0.6 if difficult else 0.3,
        )
    )
    return {name: values[name] for name in _population_spec(target, kind)}


def jobs(freeze):
    result = []
    for lane_order, target in enumerate(TARGETS):
        spec = freeze["models"][target][0]
        for case_order, case in enumerate(["A", "B"]):
            truth = _truth(target, spec["kind"], case)
            seed = 2966110800 + 10000 * lane_order + 100 * case_order
            result.append(
                dict(
                    id=f"full-smoke-{lane_order}-{case.lower()}",
                    order=len(result),
                    role="full_design_recovery",
                    model_key=f"{target}:{spec['kind']}:selected",
                    case=case,
                    truth=truth,
                    truth_sha256=_sha(truth),
                    protocol_sha256=_sha(protocol()),
                    design_protocol_sha256=_sha(protocol()["design"]),
                    model_spec_sha256=_sha(spec),
                    simulator_seed=seed + 1,
                    sampler_seed=seed + 2,
                    conditional_seed=seed + 3,
                )
            )
    return result


def case_paths(root, job):
    if job.get("role") != "full_design_recovery" or job.get("id") not in {
        f"full-smoke-{lane}-{case}" for lane in range(3) for case in ["a", "b"]
    }:
        raise ValueError("one of the six literal full-design smoke jobs required")
    return root / OUTPUT / "jobs" / job["id"], root / STORE / (job["id"] + ".nc")


def verify_gate(root: Path):
    gate = json.loads(data._path(root, GATE).read_text())
    if (
        gate.get("status") != "accepted_frozen_arrival_development_recovery_execution"
        or gate.get("independent_checker") is not True
        or gate.get("specification_freeze") != data.FREEZE
        or gate.get("completed_check") != data.CHECK_REVIEW
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("resources") != fit.resources()
        or gate.get("protocol") != protocol()
        or type(gate.get("max_sampler_call_slots")) is not int
        or gate["max_sampler_call_slots"] < 6
    ):
        raise ValueError("independently accepted frozen full-design smoke execution required")
    files = gate.get("files", {})
    if not set(CONSUMED) | {data.FREEZE, data.CHECK_REVIEW} <= set(files):
        raise ValueError("complete recovery consumer/frozen source closure required")
    pins = {**files, GATE: sha256(root / GATE)}
    data._unchanged(root, pins)
    if (
        gate.get("specification_freeze_sha256") != pins[data.FREEZE]
        or gate.get("completed_check_sha256") != pins[data.CHECK_REVIEW]
    ):
        raise ValueError("same scientific freeze and accepted completed check required")
    freeze, _, _, _ = data.verify_development_sources(root, pins, full=True)
    if gate.get("jobs") != jobs(freeze):
        raise ValueError("exact six predeclared truths/seeds/selected-prior jobs required")
    specs = {
        f"{target}:{entries[0]['kind']}:selected": (target, entries[0])
        for target, entries in freeze["models"].items()
    }
    return dict(gate=gate, files=pins, freeze=freeze, specs=specs)


def _design(lane):
    native = np.zeros(len(lane.rows)) if lane.target == "T-CAL" else lane.reference_minutes.copy()
    rows = tuple(
        dict(
            record_id=rid,
            event_id=event,
            physical_site_id=site,
            target=lane.target,
            distance_km=str(distance),
            reference_minutes=str(reference),
            target_minutes=str(value),
        )
        for rid, event, site, distance, reference, value in zip(
            lane.record_ids,
            lane.event_ids,
            lane.site_ids,
            lane.distance_km,
            lane.reference_minutes,
            native,
            strict=True,
        )
    )
    return replace(lane, rows=rows, y=native, response=np.zeros(len(lane.rows)))


def simulate(lane, kind, truth, seed):
    """Strip all historical responses/row values; share u within event, independent noise."""
    clean = _design(lane)
    if kind == "mean-curvature":
        response, effects = simulate_curvature_response(clean, truth, seed=seed)
    elif kind == "distance-scale":
        response, effects = simulate_scale_response(clean, truth, seed=seed)
    else:
        response, effects = simulate_response(
            clean,
            {**truth, "beta": truth.get("beta", 0.0), "tau_event": truth.get("tau_event", 0.0)},
            seed=seed,
        )
    try:
        with np.errstate(over="raise", under="raise", invalid="raise"):
            native = (
                response.copy()
                if lane.target == "T-CAL"
                else np.exp(response + np.log(clean.reference_minutes))
            )
    except FloatingPointError as error:
        raise ValueError(
            "unrepresentable synthetic native arithmetic; no clipping or reseed"
        ) from error
    if not np.isfinite(native).all() or lane.target != "T-CAL" and (native <= 0).any():
        raise ValueError("finite signed or finite positive synthetic native values required")
    rows = tuple(
        {**row, "target_minutes": str(value)} for row, value in zip(clean.rows, native, strict=True)
    )
    return replace(clean, rows=rows, response=response, y=native), effects


def _design_sha(lane):
    return _sha(
        dict(
            target=lane.target,
            record_ids=lane.record_ids,
            event_ids=lane.event_ids,
            site_ids=lane.site_ids,
            sequences=lane.sequences,
            distance=lane.distance_km.tolist(),
            reference=lane.reference_minutes.tolist(),
            x=lane.x.tolist(),
            included=lane.included.tolist(),
        )
    )


def _dense_logp_gradient(lane, kind, theta, settings):
    """Independent SciPy dense event MVNs, selected global priors and log-transform Jacobian."""
    ids = np.flatnonzero(lane.included)
    distance = lane.distance_km[ids]
    names = list(_population_spec(lane.target, kind))
    design = np.column_stack(
        [
            np.ones(len(ids)),
            *([np.log(distance / 1000)] if "beta" in names else []),
            *([np.log((distance + 500) / (1.5 * distance))] if "gamma" in names else []),
        ]
    )
    coefficients = [name for name in ["alpha", "beta", "gamma"] if name in names]
    mean = design @ np.array([theta[name] for name in coefficients])
    weights = np.column_stack(
        [np.interp(np.log(distance), np.log([500, 2000, 5000]), np.eye(3)[:, j]) for j in range(3)]
    )
    sigma = (
        weights @ np.asarray(theta["sigma_anchor"])
        if "sigma_anchor" in names
        else np.full(len(ids), theta["sigma"])
    )
    tau = theta.get("tau_event", 0.0)
    gradient = {name: np.zeros_like(np.asarray(theta[name], dtype=float)) for name in names}
    total = 0.0
    event_ids = np.asarray(lane.event_ids)[ids]
    for event in sorted(set(event_ids)):
        take = np.flatnonzero(event_ids == event)
        residual = lane.response[ids[take]] - mean[take]
        covariance = np.diag(sigma[take] ** 2) + tau**2 * np.ones((len(take), len(take)))
        total += float(
            stats.multivariate_normal.logpdf(residual, mean=np.zeros(len(take)), cov=covariance)
        )
        factor = linalg.cho_factor(covariance, lower=True)
        q = linalg.cho_solve(factor, residual)
        inverse = linalg.cho_solve(factor, np.eye(len(take)))
        for j, name in enumerate(coefficients):
            gradient[name] += design[take, j] @ q
        diagonal = sigma[take] * (q * q - np.diag(inverse))
        if "sigma_anchor" in names:
            gradient["sigma_anchor"] += weights[take].T @ diagonal
        else:
            gradient["sigma"] += diagonal.sum()
        if "tau_event" in names:
            gradient["tau_event"] += tau * (q.sum() ** 2 - inverse.sum())
    for name, (key, _) in _population_spec(lane.target, kind).items():
        value, scale = np.asarray(theta[name]), settings["distribution_scales"][key]
        positive = name in {"sigma", "sigma_anchor", "tau_event"}
        if positive and (value <= 0).any():
            raise ValueError("positive oracle scale required")
        if settings["family"] == "t4":
            total += float(stats.t.logpdf(value, df=4, loc=0, scale=scale).sum())
            gradient[name] += -5 * value / (4 * scale**2 + value**2)
        else:
            total += float(stats.norm.logpdf(value, loc=0, scale=scale).sum())
            gradient[name] += -value / scale**2
        if positive:
            total += value.size * np.log(2) + float(np.log(value).sum())
            gradient[name] = gradient[name] * value + 1
    return total, gradient


def _scipy_prior_logp(theta, population_spec, settings):
    value = 0.0
    for name, (key, _) in population_spec.items():
        parameter = np.asarray(theta[name])
        scale = settings["distribution_scales"][key]
        density = (
            stats.t.logpdf(parameter, df=4, scale=scale)
            if settings["family"] == "t4"
            else stats.norm.logpdf(parameter, scale=scale)
        )
        value += float(density.sum())
        if name in {"sigma", "sigma_anchor", "tau_event"}:
            value += parameter.size * np.log(2) + float(np.log(parameter).sum())
    return float(value)


def numerical_oracles(model, lane, kind, truth, settings, posterior) -> dict[str, Any]:
    logp, dlogp = model.compile_logp(), model.compile_dlogp()
    # Isolate the prior-only discrepancy BEFORE joint evaluation. The independent
    # uncorrected joint bound still applies; no likelihood offset is fitted.
    prior_terms = list(model.free_RVs) + [
        value
        for value in model.potentials
        if value.name == "sensitivity_population_prior_replacement"
    ]
    prior_logp = model.compile_logp(vars=prior_terms)
    points = [("truth", truth)]
    for chain, draw in protocol()["oracle_positions"]:
        points.append(
            (
                f"chain-{chain}-draw-{draw}",
                {
                    name: posterior[name].values[chain, draw]
                    for name in _population_spec(lane.target, kind)
                },
            )
        )
    population_spec = _population_spec(lane.target, kind)

    def point_for(theta):
        value_names = {model.rvs_to_values[model[name]].name: name for name in theta}
        return {
            value: np.log(np.asarray(theta[name]))
            if name in {"sigma", "sigma_anchor", "tau_event"}
            else np.asarray(theta[name], dtype=float)
            for value, name in value_names.items()
        }

    shifted = {
        name: np.asarray(value) * 1.125
        if name in {"sigma", "sigma_anchor", "tau_event"}
        else np.asarray(value) + 0.125 * settings["distribution_scales"][population_spec[name][0]]
        for name, value in truth.items()
    }
    prior_points = [("truth", truth), ("fixed_prior_shift", shifted), *points[1:]]
    prior_checks: list[dict[str, Any]] = []
    for label, theta in prior_points:
        difference = float(prior_logp(point_for(theta))) - _scipy_prior_logp(
            theta, population_spec, settings
        )
        prior_checks.append(
            dict(point=label, offset=float(difference) if np.isfinite(difference) else None)
        )
    normalizer_offset: float | None = prior_checks[0]["offset"]
    prior_passed = (
        normalizer_offset is not None
        and abs(normalizer_offset) <= protocol()["prior_normalizer_offset_bound"]
        and all(
            row["offset"] is not None
            and abs(row["offset"] - normalizer_offset) <= protocol()["oracle_logp_atol"]
            for row in prior_checks
        )
    )
    dtype_evidence, predicted_scale_offset = {}, 0.0
    if settings["family"] == "normal":
        for name, (key, shape) in population_spec.items():
            scale = settings["distribution_scales"][key]
            dist = (
                pm.HalfNormal if name in {"sigma", "sigma_anchor", "tau_event"} else pm.Normal
            ).dist(sigma=scale)
            dtype = dist.owner.inputs[-1].dtype
            dtype_evidence[name] = str(dtype)
            predicted_scale_offset += (3 if shape else 1) * (
                np.log(float(scale)) - float(np.log(np.asarray(scale, dtype=dtype)))
            )
    rows = []
    for label, theta in points:
        point = point_for(theta)
        value_names = {model.rvs_to_values[model[name]].name: name for name in theta}
        expected, gradient = _dense_logp_gradient(lane, kind, theta, settings)
        expected_gradient = np.concatenate(
            [np.atleast_1d(gradient[value_names[var.name]]) for var in model.value_vars]
        )
        actual, actual_gradient = float(logp(point)), np.asarray(dlogp(point))
        prior_offset = float(prior_logp(point)) - _scipy_prior_logp(
            theta, _population_spec(lane.target, kind), settings
        )
        error = (
            abs(actual - expected - normalizer_offset) if normalizer_offset is not None else np.inf
        )
        raw_error = abs(actual - expected)
        offset_drift = (
            abs(prior_offset - normalizer_offset) if normalizer_offset is not None else np.inf
        )
        gradient_error = float(np.max(np.abs(actual_gradient - expected_gradient)))
        passed = bool(
            np.isfinite([actual, expected, gradient_error]).all()
            and prior_passed
            and raw_error <= protocol()["oracle_uncorrected_logp_atol"]
            and offset_drift <= protocol()["oracle_logp_atol"]
            and error <= protocol()["oracle_logp_atol"]
            and np.allclose(
                actual_gradient,
                expected_gradient,
                atol=protocol()["oracle_gradient_atol"],
                rtol=protocol()["oracle_gradient_rtol"],
            )
        )
        rows.append(
            dict(
                point=label,
                logp_absolute_error=float(raw_error) if np.isfinite(raw_error) else None,
                logp_prior_offset_corrected_error=float(error) if np.isfinite(error) else None,
                prior_normalizer_offset=float(prior_offset) if np.isfinite(prior_offset) else None,
                prior_offset_drift=float(offset_drift) if np.isfinite(offset_drift) else None,
                gradient_max_absolute_error=gradient_error if np.isfinite(gradient_error) else None,
                passed=passed,
            )
        )
    return dict(
        passed=all(row["passed"] for row in rows),
        points=rows,
        prior_only_checks=prior_checks,
        selected_prior_scale_dtypes=dtype_evidence,
        normal_log_scale_offset_prediction=float(predicted_scale_offset)
        if dtype_evidence
        else None,
        normalizer_source=(
            "pymc.distributions.continuous.Normal.logp/HalfNormal.logp symbolic log(sigma)"
        ),
        measure="modeled_response_plus_selected_prior_and_transform_Jacobian",
        prior_normalizer_scope="bounded_data_independent_PyMC_prior_constant_not_likelihood_adjustment",
    )


def _truth_table(post, truth):
    rows = []
    for name, generating in truth.items():
        values = post[name].values
        for j in range(3) if name == "sigma_anchor" else [None]:
            q = _quantiles(values if j is None else values[..., j])
            actual = generating if j is None else generating[j]
            rows.append(
                dict(
                    parameter=name,
                    anchor_km=None if j is None else [500, 2000, 5000][j],
                    truth=actual,
                    **q,
                    within90=None
                    if not q["quantile_valid"]
                    else bool(q["q05"] <= actual <= q["q95"]),
                    interpretation="single_case_inclusion_not_coverage",
                )
            )
    return rows


def run_recovery_job(root: Path, job: dict[str, Any], output: Path, store: Path) -> dict[str, Any]:
    root = root.resolve()
    if (output, store) != case_paths(root, job) or any(
        path.exists() or path.resolve() != path for path in [output, store]
    ):
        raise ValueError("new canonical nonsymlink recovery output/raw paths required")
    admission = verify_gate(root)
    if job not in admission["gate"]["jobs"]:
        raise ValueError("exact predeclared recovery job required")
    target, spec = admission["specs"][job["model_key"]]
    pins = admission["files"]
    output.mkdir(parents=True)
    write_json(output / "job.json", job)
    write_json(output / "inputs.json", dict(files=pins, model_spec=spec, protocol=protocol()))
    result: dict[str, Any] = dict(
        job=job,
        status="worker_failure",
        confirmation_outcomes_parsed=None,
        reserved_outcomes="sealed",
        scope=protocol()["scope"],
        calibration_or_coverage_claim=False,
        sampler_call_started=False,
    )
    raw_saved = False
    try:
        views = data.load_full_development_lanes(root, pins)
        result["confirmation_outcomes_parsed"] = True
        design = views["combined"][target]
        fake, effects = simulate(design, spec["kind"], job["truth"], job["simulator_seed"])
        ids = np.flatnonzero(fake.included)
        base, wider, settings = fit._priors(root, target, spec)
        write_json(
            output / "prior-settings.json", dict(base_prior=base, wider_prior=wider, **settings)
        )
        write_json(
            output / "membership.json",
            dict(
                training_record_ids=[fake.record_ids[int(i)] for i in ids],
                design_sha256=_design_sha(design),
                original_membership=views["membership"][target],
                truth=job["truth"],
                event_effect_truth=effects,
            ),
        )
        model = build_sensitivity_model(
            fake, spec["kind"], base, spec["prior_variant"], wider_prior=wider, indices=ids
        )
        if list(model.coords.get("record") or []) != [fake.record_ids[int(i)] for i in ids]:
            raise ValueError("synthetic graph must contain exactly primary full-design records")
        data._unchanged(root, pins)
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open("xb"):
            pass
        write_json(output / "sampling-start.json", job)
        result["sampler_call_started"] = True
        with model:
            tree = pm.sample(
                draws=2000,
                tune=1000,
                chains=4,
                cores=2,
                target_accept=0.95,
                nuts_sampler="nutpie",
                random_seed=job["sampler_seed"],
                progressbar=False,
            )
        tree["observed_data"] = xr.DataTree(fit._observed(fake, ids, "full_design_recovery"))
        tree.to_netcdf(store, engine="h5netcdf")
        raw_saved = True
        result.update(posterior=str(store.relative_to(root)), posterior_sha256=sha256(store))
        post = fit._read_population(root, store, fake, ids, spec["kind"])
        diagnostics, table = sampling_diagnostics(tree)
        write_json(output / "diagnostics.json", diagnostics)
        table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
        oracle = numerical_oracles(model, fake, spec["kind"], job["truth"], settings, post)
        write_json(output / "numerical-oracles.json", oracle)
        summary = summarize_posterior(
            fake, spec["kind"], post, indices=ids, seed=job["conditional_seed"], draws=800
        )
        write_json(output / "summary.json", summary)
        for name in TABLES:
            write_table(output / (name.replace("_", "-") + ".csv"), summary[name])
        truth_rows = _truth_table(post, job["truth"])
        write_table(output / "truth-quantiles.csv", truth_rows)
        result.update(
            diagnostics=diagnostics,
            numerical_oracles_passed=oracle["passed"],
            status=SUCCESS
            if diagnostics.get("screen_passed") is True
            and oracle["passed"]
            and _summary_valid(summary)
            and all(row["quantile_valid"] for row in truth_rows)
            else "needs_numerical_review",
        )
        tree.close()
        data._unchanged(root, pins)
    except Exception as error:
        result.update(
            status="needs_numerical_review" if raw_saved else "worker_failure",
            error_type=type(error).__name__,
            error=str(error),
        )
        if store.exists() and store.stat().st_size:
            result.update(posterior=str(store.relative_to(root)), posterior_sha256=sha256(store))
        try:
            data._unchanged(root, pins)
        except Exception:
            result["status"] = "source_identity_failure"
    write_json(output / "result.json", result)
    fit._manifest(output)
    return result


def case_artifacts(root: Path, job, pins, accepted=None):
    admission = verify_gate(root)
    data._require(pins, admission["files"])
    if job not in admission["gate"]["jobs"]:
        raise ValueError("exact prospectively admitted recovery job required")
    output, raw = case_paths(root, job)
    manifest_path = str((output / "output-checksums.json").relative_to(root))
    manifest = json.loads(data._path(root, manifest_path).read_text())
    required = (
        fit.FIT_FILES
        | {"numerical-oracles.json", "summary.json", "truth-quantiles.csv"}
        | {name.replace("_", "-") + ".csv" for name in TABLES}
    )
    if not required <= set(manifest):
        raise ValueError("complete recovery artifact inventory required")
    files = {str((output / name).relative_to(root)): digest for name, digest in manifest.items()}
    files.update(
        {
            manifest_path: sha256(output / "output-checksums.json"),
            str(raw.relative_to(root)): sha256(raw),
        }
    )
    data._unchanged(root, files)
    result, inputs, membership = [
        json.loads((output / name).read_text())
        for name in ["result.json", "inputs.json", "membership.json"]
    ]
    target, spec = admission["specs"][job["model_key"]]
    if (
        result.get("status") != SUCCESS
        or result.get("job") != job
        or result.get("posterior") != str(raw.relative_to(root))
        or result.get("posterior_sha256") != files[str(raw.relative_to(root))]
        or result.get("confirmation_outcomes_parsed") is not True
        or result.get("reserved_outcomes") != "sealed"
        or result.get("calibration_or_coverage_claim") is not False
        or inputs != dict(files=admission["files"], model_spec=spec, protocol=protocol())
        or json.loads((output / "job.json").read_text()) != job
    ):
        raise ValueError("exact frozen recovery result/input/scope binding required")
    views = data.load_full_development_lanes(root, admission["files"])
    design = views["combined"][target]
    fake, effects = simulate(design, spec["kind"], job["truth"], job["simulator_seed"])
    ids = np.flatnonzero(fake.included)
    if membership != dict(
        training_record_ids=[fake.record_ids[int(i)] for i in ids],
        design_sha256=_design_sha(design),
        original_membership=views["membership"][target],
        truth=job["truth"],
        event_effect_truth=effects,
    ):
        raise ValueError("full-design identities and seeded synthetic response proof must replay")
    base, wider, settings = fit._priors(root, target, spec)
    fit._replay_fit(root, output, raw, fake, ids, spec, job, result)
    post = fit._read_population(root, raw, fake, ids, spec["kind"])
    model = build_sensitivity_model(
        fake, spec["kind"], base, spec["prior_variant"], wider_prior=wider, indices=ids
    )
    oracle = numerical_oracles(model, fake, spec["kind"], job["truth"], settings, post)
    if (
        not oracle["passed"]
        or json.loads((output / "numerical-oracles.json").read_text()) != oracle
    ):
        raise ValueError("independent full-design density/gradient oracles must replay")
    summary = summarize_posterior(
        fake, spec["kind"], post, indices=ids, seed=job["conditional_seed"], draws=800
    )
    if not _summary_valid(summary) or json.loads((output / "summary.json").read_text()) != summary:
        raise ValueError("conditional_seed800-draw recovery summary must replay")
    for name in TABLES:
        fit._replay_table(output / (name.replace("_", "-") + ".csv"), summary[name])
    fit._replay_table(output / "truth-quantiles.csv", _truth_table(post, job["truth"]))
    if accepted is not None and accepted.get("files") != files:
        raise ValueError("immutable accepted recovery inventory changed")
    data._unchanged(root, {**admission["files"], **files})
    return dict(
        files=files,
        result=str((output / "result.json").relative_to(root)),
        posterior=str(raw.relative_to(root)),
        posterior_sha256=files[str(raw.relative_to(root))],
        role=job["role"],
    )
