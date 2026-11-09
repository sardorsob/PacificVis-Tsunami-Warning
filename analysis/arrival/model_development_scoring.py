"""Pure direct new-event scores from one explicit population posterior.

Only the new Normal event effect is integrated, before averaging likelihoods;
alpha/beta/gamma remain explicit under Normal or Student-t population priors.
No loader, fit, repair or acceptance gate is called. Callers must bind the supplied
posterior file SHA to these draws and validate the frozen development cohort.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import xarray as xr

from analysis.arrival.model_bridge import _mixing as functional_mixing
from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_data import VREF_KM_MIN, Lane
from analysis.arrival.model_evaluation import native_event_logpdf
from analysis.arrival.model_scale import scale_weights
from analysis.arrival.model_scoring import mean_mcse
from analysis.arrival.model_sensitivity_priors import _population_spec

EVENT_MCSE = 0.005
AGGREGATE_MCSE = 0.002
WEIGHT_CONCENTRATION = 100
QUALIFICATION = (
    "Chain-aware delta-method MCSE and functional Rhat/ESS are finite-run numerical "
    "screens, not finite-sample certificates or proof of global posterior exploration; "
    "weight concentration is not autocorrelation ESS. No tail clipping or repair."
)


def _coordinates(value):
    if value.dims[:2] != ("chain", "draw") or value.sizes.get("chain") != 4:
        raise ValueError("exact four aligned chain/draw dimensions required")
    coordinates = {}
    for axis in ["chain", "draw"]:
        if axis not in value.coords or value[axis].dims != (axis,):
            raise ValueError("explicit chain and draw coordinates required")
        labels = value[axis].values.tolist()
        if (
            not labels
            or not value.get_index(axis).is_unique
            or any(
                type(v) not in {str, int, float}
                or isinstance(v, float)
                and not math.isfinite(v)
                or isinstance(v, str)
                and not v
                for v in labels
            )
        ):
            raise ValueError("unique finite literal chain/draw coordinates required")
        coordinates[axis] = labels
    return coordinates


def _fingerprint(population, coordinates):
    digest = hashlib.sha256(json.dumps(coordinates, sort_keys=True).encode())
    for name, values in sorted(population.items()):
        digest.update(name.encode())
        digest.update(str(values.shape).encode())
        digest.update(np.ascontiguousarray(values, dtype="<f8").tobytes())
    return digest.hexdigest()


def event_loglikelihood(lane: Lane, held_indices, kind: str, posterior: xr.Dataset):
    """Return native logL[chain,draw] and metadata for one wholly new event.

    The pure input is a caller-validated held-event Lane, never a training-data
    loader. This function cannot verify that a file-backed posterior omitted the
    event; that provenance belongs to the later frozen adapter/controller.
    """
    spec = _population_spec(lane.target, kind)
    held = np.asarray(held_indices)
    count = len(lane.rows)
    if (
        held.ndim != 1
        or held.dtype.kind not in "iu"
        or not len(held)
        or len(set(held.tolist())) != len(held)
        or (held < 0).any()
        or (held >= count).any()
        or lane.included.shape != (count,)
        or lane.included.dtype != np.bool_
        or not lane.included[held].all()
    ):
        raise ValueError("nonempty unique primary held indices required")
    for ids in [lane.record_ids, lane.event_ids, lane.sequences, lane.site_ids]:
        if len(ids) != count or any(not isinstance(v, str) or not v for v in ids):
            raise ValueError("aligned literal held record/event/sequence/site identities required")
    if (
        len(set(lane.record_ids)) != count
        or len({lane.event_ids[int(i)] for i in held}) != 1
        or len({lane.sequences[int(i)] for i in held}) != 1
    ):
        raise ValueError("one held event and sequence with unique native records required")
    for values in [lane.y, lane.distance_km, lane.reference_minutes, lane.x, lane.response]:
        if (
            values.shape != (count,)
            or values.dtype.kind not in "iuf"
            or not np.isfinite(values[held]).all()
        ):
            raise ValueError("aligned finite real held native and modeled quantities required")
    distance, native, reference = [
        v[held] for v in [lane.distance_km, lane.y, lane.reference_minutes]
    ]
    if (
        (distance <= 0).any()
        or (reference <= 0).any()
        or lane.target != "T-CAL"
        and (native <= 0).any()
    ):
        raise ValueError("positive km/reference and positive duration target required")
    expected = native if lane.target == "T-CAL" else np.log(native) - np.log(reference)
    if (
        not np.allclose(reference, distance / VREF_KM_MIN, rtol=0, atol=1e-10)
        or not np.allclose(lane.x[held], np.log(distance / 1000), rtol=0, atol=1e-12)
        or not np.allclose(lane.response[held], expected, rtol=0, atol=1e-12)
    ):
        raise ValueError("native minutes/km and coherent reference/predictor/response required")
    if not isinstance(posterior, xr.Dataset) or not set(spec) <= set(posterior.data_vars):
        raise ValueError("explicit population coefficient and scale posterior required")
    if posterior.sizes.get("chain") != 4 or posterior.sizes.get("draw", 0) < 1:
        raise ValueError("four nonempty chains required")
    population = {}
    for name, (_, shape) in spec.items():
        variable = posterior[name]
        coordinates = _coordinates(variable)
        dims = ("chain", "draw", "scale_anchor_km") if shape else ("chain", "draw")
        values = np.asarray(variable.values)
        if (
            variable.dims != dims
            or values.shape != (4, posterior.sizes["draw"], *shape)
            or values.dtype.kind not in "iuf"
            or not np.isfinite(values).all()
        ):
            raise ValueError("finite literal population parameter dimensions required")
        if name in {"sigma", "sigma_anchor"} and (values <= 0).any():
            raise ValueError("strictly positive residual scales required")
        if name == "tau_event" and (values < 0).any():
            raise ValueError("nonnegative Normal event scale required")
        population[name] = values.astype(float, copy=False)
    if "sigma_anchor" in population and (
        posterior.scale_anchor_km.dims != ("scale_anchor_km",)
        or posterior.scale_anchor_km.values.tolist() != [500, 2000, 5000]
    ):
        raise ValueError("literal500/2000/5000km residual SD anchor order required")
    mean = np.broadcast_to(population["alpha"][..., None], (4, posterior.sizes["draw"], len(held)))
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            if "beta" in population:
                mean = mean + population["beta"][..., None] * lane.x[held]
            if "gamma" in population:
                mean = mean + population["gamma"][..., None] * curvature_basis(distance)
            sigma = (
                np.einsum("cdj,ij->cdi", population["sigma_anchor"], scale_weights(distance))
                if "sigma_anchor" in population
                else population["sigma"][..., None]
            )
            log_density = native_event_logpdf(
                native, reference, lane.target, mean, sigma, population.get("tau_event", 0.0)
            )
    except FloatingPointError as error:
        raise ValueError("unrepresentable native event likelihood") from error
    if not np.isfinite(log_density).all():
        raise ValueError("finite native event likelihood required")
    metadata = {
        "target": lane.target,
        "kind": kind,
        "event_id": lane.event_ids[int(held[0])],
        "sequence": lane.sequences[int(held[0])],
        "record_ids": [lane.record_ids[int(i)] for i in held],
        "records": len(held),
        "measure": "native_minutes_joint_density",
        "distance_units": "km",
        "native_log_jacobian": 0.0 if lane.target == "T-CAL" else -float(np.log(native).sum()),
        "new_event_effect": "Normal_u_integrated_before_likelihood_averaging"
        if "tau_event" in population
        else "absent_in_pooled_or_distance_form",
        "coefficient_treatment": "explicit_no_Gaussian_prior_collapse",
        "training_draw_identity": _fingerprint(population, coordinates),
    }
    return xr.DataArray(
        log_density,
        dims=("chain", "draw"),
        coords=coordinates,
        attrs=metadata,
        name="native_event_loglikelihood",
    ), metadata


def _diagnostics(influence):
    failures = []
    try:
        error = mean_mcse(influence)
    except (ValueError, FloatingPointError, OverflowError):
        error = None
        failures.append("unresolved_delta_mcse")
    try:
        # Zero within-chain variance can warn; nonfinite ArviZ diagnostics still fail.
        with np.errstate(divide="ignore", invalid="ignore"):
            mixing = functional_mixing(influence)
    except (ValueError, FloatingPointError, OverflowError):
        mixing = {"passed": False, "constant": False, "reason": "unresolved_functional_mixing"}
    if not mixing["passed"]:
        failures.append("functional_mixing")
    return error, mixing, failures


def direct_event_score(logL, records: int):
    """Stable log-mean likelihood and numerical screens, preserving every draw.

    joint_influence is (L/mean(L)−1), on the JOINT log-normalizer delta scale.
    Divide it by records when aggregating. ndarray inputs support pure oracles;
    shared-training production aggregation requires the labelled output of
    event_loglikelihood. Underflow of negligible exp(logL−max) is not clipping
    or dropping finite log likelihoods; their original values remain the input.
    """
    labelled = isinstance(logL, xr.DataArray)
    values = np.asarray(logL.values if labelled else logL)
    if (
        values.ndim != 2
        or values.shape[0] != 4
        or values.shape[1] < 100
        or values.dtype.kind not in "iuf"
        or not np.isfinite(values).all()
        or type(records) is not int
        or records < 1
    ):
        raise ValueError(
            "finite four-chain/atleast100draw likelihood and positive event size required"
        )
    metadata = dict(logL.attrs) if labelled else {}
    coordinates = _coordinates(logL) if labelled else None
    if labelled and (
        metadata.get("records") != records
        or metadata.get("measure") != "native_minutes_joint_density"
    ):
        raise ValueError("event count and native-minute density measure must match")
    maximum = float(values.max())
    with np.errstate(over="ignore", under="ignore"):
        weights = np.exp(values - maximum)
    relative = weights / weights.mean()
    joint = maximum + math.log(float(weights.mean()))
    if not math.isfinite(joint):
        raise ValueError("unrepresentable log mean native likelihood")
    influence = relative - 1
    error, mixing, failures = _diagnostics(influence / records)
    concentration = float(weights.sum() ** 2 / np.square(weights).sum())
    chain_scores = []
    for row in values:
        anchor = float(row.max())
        with np.errstate(over="ignore", under="ignore"):
            chain_scores.append(anchor + math.log(float(np.exp(row - anchor).mean())))
    with np.errstate(over="ignore", invalid="ignore"):
        spread = float(np.ptp(np.asarray(chain_scores)))
    if concentration < WEIGHT_CONCENTRATION:
        failures.append("density_weight_concentration")
    if error is None or error > EVENT_MCSE:
        failures.append("event_mcse")
    if not math.isfinite(spread) or error is None or spread / records > max(EVENT_MCSE, 6 * error):
        failures.append("chain_log_normalizer_disagreement")
    return {
        "joint_log_predictive": joint,
        "normalized_event_score": joint / records,
        "records": records,
        "normalized_mcse": error,
        "joint_log_mcse_delta": None if error is None else error * records,
        "density_weight_concentration_ess": concentration,
        "functional_mixing": mixing,
        "chain_joint_log_predictive": chain_scores,
        "chain_joint_log_predictive_range": spread if math.isfinite(spread) else None,
        "precision_passed": not failures,
        "status": "computed_pending_review" if not failures else "needs_numerical_review",
        "numerical_failures": failures,
        "metadata": metadata,
        "joint_influence": xr.DataArray(
            influence, dims=("chain", "draw"), coords=coordinates, attrs=metadata
        )
        if labelled
        else influence,
        "method": "single_training_posterior_direct_new_event_likelihood_average",
        "qualification": QUALIFICATION,
    }


def aggregate_shared_training_events(events, training_posterior_sha: str):
    """Equal-event score and covariance-aware MCSE for one training draw stream.

    A supplied SHA is a caller-bound provenance label, never a file read here.
    Shared influences are summed BEFORE mean_mcse; independent-event quadrature
    would lose covariance and can materially understate Monte Carlo uncertainty.
    """
    if (
        not isinstance(events, list)
        or not events
        or not isinstance(training_posterior_sha, str)
        or len(training_posterior_sha) != 64
        or any(c not in "0123456789abcdef" for c in training_posterior_sha)
    ):
        raise ValueError("nonempty event scores and literal training posterior SHA256 required")
    first = events[0]["joint_influence"]
    if not isinstance(first, xr.DataArray):
        raise ValueError("labelled shared-training influence coordinates required")
    coordinates = _coordinates(first)
    metadata = events[0]["metadata"]
    identity = {key: metadata.get(key) for key in ["target", "kind", "training_draw_identity"]}
    if (
        identity["target"] not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or not isinstance(identity["training_draw_identity"], str)
        or len(identity["training_draw_identity"]) != 64
        or any(c not in "0123456789abcdef" for c in identity["training_draw_identity"])
    ):
        raise ValueError("explicit source/form and training draw-content identity required")
    _population_spec(identity["target"], identity["kind"])
    seen, arrays, scores = set(), [], []
    for event in events:
        influence, meta = event["joint_influence"], event["metadata"]
        records = event["records"]
        if (
            not isinstance(influence, xr.DataArray)
            or influence.dims != ("chain", "draw")
            or _coordinates(influence) != coordinates
            or any(meta.get(k) != v for k, v in identity.items())
            or influence.attrs != meta
            or meta.get("measure") != "native_minutes_joint_density"
            or type(records) is not int
            or records < 1
            or meta.get("records") != records
            or not isinstance(meta.get("event_id"), str)
            or not meta["event_id"]
            or meta["event_id"] in seen
            or not np.isfinite(influence.values).all()
            or not math.isfinite(event["normalized_event_score"])
        ):
            raise ValueError(
                "unique same-source/form/event scores on identical training draws required"
            )
        seen.add(meta["event_id"])
        arrays.append(influence.values / records)
        scores.append(event["normalized_event_score"])
    shared = np.mean(np.stack(arrays), axis=0)
    error, mixing, failures = _diagnostics(shared)
    if error is None or error > AGGREGATE_MCSE:
        failures.append("aggregate_mcse")
    if not all(e["precision_passed"] for e in events):
        failures.append("event_numerical_review")
    return {
        "equal_event_score": math.fsum(value / len(events) for value in scores),
        "mcse_equal_event_score": error,
        "events": len(events),
        "records": sum(e["records"] for e in events),
        "event_precision_passed": all(e["precision_passed"] for e in events),
        "functional_mixing": mixing,
        "precision_passed": not failures,
        "status": "computed_pending_review" if not failures else "needs_numerical_review",
        "numerical_failures": failures,
        "training_posterior_sha256": training_posterior_sha,
        **identity,
        "shared_influence": xr.DataArray(shared, dims=("chain", "draw"), coords=coordinates),
        "mcse_scope": "shared_training_influences_divided_by_records_and_events_before_mean_mcse",
        "qualification": QUALIFICATION,
    }
