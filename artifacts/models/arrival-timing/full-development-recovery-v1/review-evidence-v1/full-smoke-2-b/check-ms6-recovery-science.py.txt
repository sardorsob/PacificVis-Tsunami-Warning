"""Finite independent G6 arithmetic and plot helpers; actual reads require closure.

No top-level audit loops, loaders, sampler, Gate/STATE/public writes or model
selection. Use only Root-admitted selected sources and exact closed-job arrays.
"""

# pyright: basic
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
from scipy import linalg, stats

MANUAL = Path("/private/tmp/recovery_scientific_checker.py")
MANUAL_SHA = "d976791947a9dcbdb672728acf01ee14abc95a2aefd5a05c4442e2560f5f3243"
GRID = np.array([20.0, 50.0, 100.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0])
POSITIVE = {"sigma", "sigma_anchor", "tau_event"}
PROBS = [0.05, 0.5, 0.95]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def close(a, b, atol=2e-10, rtol=1e-10):
    np.testing.assert_allclose(a, b, atol=atol, rtol=rtol)


def ast_manual() -> Callable[..., tuple[float, float]]:
    """Never import the old checker: its top-level compilation loops must not run."""
    from analysis.arrival.model_sensitivity_priors import _population_spec

    require(
        hashlib.sha256(MANUAL.read_bytes()).hexdigest() == MANUAL_SHA,
        "frozen pure manual source changed",
    )
    tree = ast.parse(MANUAL.read_text())
    functions: list[ast.stmt] = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "manual"
    ]
    require(len(functions) == 1, "exact single manual function required")
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    scope: dict[str, Any] = dict(
        np=np, stats=stats, linalg=linalg, _population_spec=_population_spec
    )
    exec(compile(module, str(MANUAL), "exec"), scope)
    return cast(Callable[..., tuple[float, float]], scope["manual"])


def components(pop, distance):
    d = np.asarray(distance)
    mu = np.broadcast_to(
        np.asarray(pop["alpha"])[..., None], (*np.shape(pop["alpha"]), len(d))
    ).copy()
    if "beta" in pop:
        mu += np.asarray(pop["beta"])[..., None] * np.log(d / 1000)
    if "gamma" in pop:
        mu += np.asarray(pop["gamma"])[..., None] * (np.log1p(500 / d) - math.log1p(0.5))
    sd = (
        np.array(
            [
                np.interp(np.log(d), np.log([500, 2000, 5000]), p)
                for p in np.asarray(pop["sigma_anchor"]).reshape(-1, 3)
            ]
        ).reshape(mu.shape)
        if "sigma_anchor" in pop
        else np.broadcast_to(np.asarray(pop["sigma"])[..., None], mu.shape)
    )
    return mu, sd


def independent_generation(design, kind, truth, seed):
    """Exactly sorted shared event u then row noise, including excluded rows."""
    rng = np.random.default_rng(seed)
    events = sorted(set(design.event_ids))
    effects = {event: float(rng.normal() * truth.get("tau_event", 0.0)) for event in events}
    mean, sd = components(truth, design.distance_km)
    response = (
        mean
        + np.array([effects[e] for e in design.event_ids])
        + sd * rng.normal(size=len(design.rows))
    )
    with np.errstate(over="raise", under="raise", invalid="raise"):
        native = (
            response.copy()
            if design.target == "T-CAL"
            else np.exp(response + np.log(design.reference_minutes))
        )
    require(
        np.isfinite(response).all() and np.isfinite(native).all(),
        "unrepresentable simulation; no redraw/clipping",
    )
    require(design.target == "T-CAL" or (native > 0).all(), "positive synthetic native required")
    return response, native, effects


def generation_checks(design, kind, truth, seed):
    from analysis.arrival import model_development_recovery as G

    synthetic, effects = G.simulate(design, kind, truth, seed)
    response, native, expected_effects = independent_generation(design, kind, truth, seed)
    close(synthetic.response, response, atol=1e-12, rtol=1e-14)
    close(synthetic.y, native, atol=1e-12, rtol=1e-14)
    require(effects == expected_effects, "shared event effects/generator ordering differs")
    poison = replace(
        design,
        y=np.full_like(design.y, 1234567.0),
        response=np.full_like(design.response, -987654.0),
        rows=tuple(
            {**r, "target_minutes": "987654321", "unapproved_historical_y": "poison"}
            for r in design.rows
        ),
    )
    regenerated, other = G.simulate(poison, kind, truth, seed)
    require(
        np.array_equal(synthetic.response, regenerated.response)
        and np.array_equal(synthetic.y, regenerated.y)
        and effects == other,
        "historical response leaked into synthetic generator",
    )
    require(
        G._design_sha(design) == G._design_sha(poison),
        "design digest must exclude all response values",
    )
    allowed = {
        "record_id",
        "event_id",
        "physical_site_id",
        "target",
        "distance_km",
        "reference_minutes",
        "target_minutes",
    }
    require(
        all(set(r) == allowed for r in G._design(poison).rows),
        "historical row payload survives design strip",
    )
    for attr in ["record_ids", "event_ids", "site_ids", "sequences"]:
        require(
            getattr(design, attr) == getattr(synthetic, attr), "source design identities changed"
        )
    require(np.array_equal(design.included, synthetic.included), "primary exclusions changed")
    return synthetic, dict(
        passed=True,
        rows=len(design.rows),
        primary_rows=int(design.included.sum()),
        events=len(effects),
        independent_simulation_passed=True,
        historical_Y_and_rows_poison_invariance=True,
        design_sha256=G._design_sha(design),
    )


def density_checks(model, lane, kind, truth, settings, post):
    """Independent dense event MVNs; independent prior offset precedes joint checks."""
    import pymc as pm

    from analysis.arrival.model_sensitivity_priors import _population_spec

    manual = ast_manual()
    spec = _population_spec(lane.target, kind)
    value_to_name = {model.rvs_to_values[model[n]].name: n for n in spec}

    def point(theta):
        return {
            v: np.log(np.asarray(theta[n])) if n in POSITIVE else np.asarray(theta[n], float)
            for v, n in value_to_name.items()
        }

    def theta(p):
        return {n: np.exp(p[v]) if n in POSITIVE else p[v] for v, n in value_to_name.items()}

    prior_terms = list(model.free_RVs) + [
        v for v in model.potentials if v.name == "sensitivity_population_prior_replacement"
    ]
    prior = model.compile_logp(vars=prior_terms)
    logp = model.compile_logp()
    gradient = model.compile_dlogp()
    shifted = {
        n: np.asarray(v) * 1.125
        if n in POSITIVE
        else np.asarray(v) + 0.125 * settings["distribution_scales"][spec[n][0]]
        for n, v in truth.items()
    }
    prior_offsets = []
    for label, t in [("truth", truth), ("fixed_prior_shift", shifted)]:
        expected = manual(lane, kind, t, settings["family"], settings["distribution_scales"])[1]
        prior_offsets.append(dict(point=label, offset=float(prior(point(t)) - expected)))
    offset = prior_offsets[0]["offset"]
    require(abs(offset) <= 1e-6, "unbounded prior-only discrepancy")
    require(
        max(abs(p["offset"] - offset) for p in prior_offsets) <= 2e-7,
        "prior offset not constant at independently fixed points",
    )
    dtype_evidence = {}
    predicted = 0.0
    if settings["family"] == "normal":
        for n, (key, shape) in spec.items():
            scale = settings["distribution_scales"][key]
            rv = (pm.HalfNormal if n in POSITIVE else pm.Normal).dist(sigma=scale)
            dtype = rv.owner.inputs[-1].dtype
            dtype_evidence[n] = str(dtype)
            predicted += (3 if shape else 1) * (
                math.log(float(scale)) - float(np.log(np.asarray(scale, dtype=dtype)))
            )
        close(predicted, offset, atol=2e-7, rtol=0)
    points = [("truth", truth)] + [
        (f"chain-{c}-draw-{d}", {n: post[n].values[c, d] for n in spec})
        for c, d in [(0, 0), (1, 1000), (3, 1999)]
    ]
    if "tau_event" in post:
        for label, index in [
            ("tau_minimum", np.argmin(post.tau_event.values)),
            ("tau_maximum", np.argmax(post.tau_event.values)),
        ]:
            c, d = np.unravel_index(index, post.tau_event.shape)
            points.append((label, {n: post[n].values[c, d] for n in spec}))
    results = []
    for label, t in points:
        p = point(t)
        expected, _ = manual(lane, kind, t, settings["family"], settings["distribution_scales"])
        numeric = []
        for variable in model.value_vars:
            v = variable.name
            value = np.asarray(p[v])
            for idx in np.ndindex(value.shape) if value.shape else [()]:
                plus = {k: np.array(vv, copy=True) for k, vv in p.items()}
                minus = {k: np.array(vv, copy=True) for k, vv in p.items()}
                plus[v][idx] += 1e-5
                minus[v][idx] -= 1e-5
                numeric.append(
                    (
                        manual(
                            lane,
                            kind,
                            theta(plus),
                            settings["family"],
                            settings["distribution_scales"],
                        )[0]
                        - manual(
                            lane,
                            kind,
                            theta(minus),
                            settings["family"],
                            settings["distribution_scales"],
                        )[0]
                    )
                    / 2e-5
                )
        actual = float(logp(p))
        actualg = np.asarray(gradient(p))
        rawerr = abs(actual - expected)
        corrected = abs(actual - expected - offset)
        close(actualg, numeric, atol=2e-5, rtol=1e-7)
        require(
            rawerr <= 1e-6 and corrected <= 2e-7,
            "joint density discrepancy; no likelihood-fitted offset allowed",
        )
        this_offset = float(
            prior(p) - manual(lane, kind, t, settings["family"], settings["distribution_scales"])[1]
        )
        require(abs(this_offset - offset) <= 2e-7, "prior offset drift at posterior point")
        results.append(
            dict(
                point=label,
                uncorrected_joint_error=rawerr,
                prior_offset_corrected_error=corrected,
                finite_difference_gradient_max_error=float(np.max(abs(actualg - numeric))),
            )
        )
    return dict(
        passed=True,
        points=results,
        prior_only_checks=prior_offsets,
        selected_scale_dtypes=dtype_evidence,
        normal_logscale_offset_prediction=predicted if dtype_evidence else None,
        native_observation_log_jacobian=0.0
        if lane.target == "T-CAL"
        else -float(np.log(lane.y[lane.included]).sum()),
        measure="modeled_response_plus_selected_global_priors_and_positive_parameter_log_Jacobian",
        native_observation_Jacobian_separate_and_theta_constant=True,
    )


def quantiles(values):
    a = np.asarray(values)
    require(np.isfinite(a).all(), "nonfinite summary values may not be dropped")
    return np.quantile(a, PROBS)


def native_quantiles(values, positive):
    q = quantiles(values)
    if not positive:
        return q, None
    with np.errstate(over="raise", under="raise", invalid="raise"):
        native = np.exp(q)
    require(
        np.isfinite(native).all() and (native > 0).all(),
        "native representability failure must not be clipped",
    )
    return native, q


def summary_checks(lane, kind, post, conditional_seed, summary, truth, truth_rows):
    """Independent selected draws, conditional Normal u and native/log-native tables."""
    ids = np.flatnonzero(lane.included)
    positive = lane.target != "T-CAL"
    n = 4 * post.sizes["draw"]
    hyper = {k: post[k].values for k in post.data_vars}
    flat = {k: v.reshape((n, *v.shape[2:])) for k, v in hyper.items()}
    seeds = np.random.SeedSequence(conditional_seed).generate_state(4)
    take = np.sort(np.random.default_rng(seeds[0]).choice(n, 800, replace=False))
    require(
        summary["stream_seeds"] == seeds.tolist()
        and summary["posterior_flat_indices"] == take.tolist(),
        "conditional_seed index/stream convention changed",
    )
    require(summary["membership"] == [lane.record_ids[i] for i in ids], "summary membership order")
    pop = {k: v[take] for k, v in flat.items()}
    d = lane.distance_km[ids]
    y = lane.response[ids]
    events = sorted(set(np.asarray(lane.event_ids)[ids]))
    event_ids = np.asarray(lane.event_ids)[ids]
    mean, sd = components(hyper, d)
    effects = np.zeros((4, post.sizes["draw"], len(events)))
    if "tau_event" in hyper:
        noise = np.random.default_rng(seeds[1]).normal(size=effects.shape)
        for j, e in enumerate(events):
            mask = event_ids == e
            w = 1 / sd[:, :, mask] ** 2
            variance = hyper["tau_event"] ** 2 / (1 + hyper["tau_event"] ** 2 * w.sum(-1))
            u = variance * np.sum(w * (y[mask] - mean[:, :, mask]), axis=-1)
            effects[:, :, j] = u + np.sqrt(variance) * noise[:, :, j]
    selected_effects = effects.reshape(n, len(events))[take][:, np.searchsorted(events, event_ids)]
    mu, sigma = components(pop, d)
    conditional = (
        mu + selected_effects + sigma * np.random.default_rng(seeds[2]).normal(size=mu.shape)
    )
    measure = conditional + np.log(lane.reference_minutes[ids]) if positive else conditional
    gridmu, gridsd = components(pop, GRID)
    rng = np.random.default_rng(seeds[3])
    new = gridmu.copy()
    if "tau_event" in pop:
        new += pop["tau_event"][:, None] * rng.normal(size=(800, 1))
    new += gridsd * rng.normal(size=new.shape)
    speed = math.sqrt(9.80665 * 4000) * 60 / 1000
    if positive:
        new += np.log(GRID / speed)
    allmu, allsd = components(flat, GRID)
    medians = allmu + np.log(GRID / speed) if positive else allmu
    parameters = {(r["parameter"], r["anchor_km"]): r for r in summary["parameters"]}
    for name, value in hyper.items():
        for j in range(3) if name == "sigma_anchor" else [None]:
            anchor = None if j is None else [500, 2000, 5000][j]
            v = value if j is None else value[..., j]
            q = quantiles(v)
            row = parameters[name, anchor]
            close([row[k] for k in ["q05", "q50", "q95"]], q)
            tr = next(
                r
                for r in truth_rows
                if r["parameter"] == name
                and (None if r["anchor_km"] in [None, ""] else int(r["anchor_km"])) == anchor
            )
            actual = truth[name] if j is None else truth[name][j]
            close(float(tr["truth"]), actual)
            close([float(tr[k]) for k in ["q05", "q50", "q95"]], q)
            require(
                str(tr["within90"]) == str(bool(q[0] <= actual <= q[2])),
                "truth inclusion is descriptive and exact",
            )
    for j, row in enumerate(summary["record_intervals"]):
        require(row["record_id"] == lane.record_ids[ids[j]], "record interval identity")
        q, logq = native_quantiles(measure[:, j], positive)
        close([row[k] for k in ["q05", "q50", "q95"]], q)
        if positive:
            close([row["log_" + k] for k in ["q05", "q50", "q95"]], logq)
    lo, hi = d.min(), d.max()
    for row in summary["curves"]:
        j = int(np.flatnonzero(GRID == row["distance_km"])[0])
        values = medians[:, j] if row["curve"] == "population_median" else new[:, j]
        q, logq = native_quantiles(values, positive)
        close([row[k] for k in ["q05", "q50", "q95"]], q)
        if positive:
            close([row["log_" + k] for k in ["q05", "q50", "q95"]], logq)
        expected = "below" if GRID[j] < lo else "above" if GRID[j] > hi else "within"
        require(
            row["support"] == expected
            and row["within_training_distance_range"] == (expected == "within"),
            "curve support",
        )
        require(
            row["residual_scale_endpoint_clamped"]
            == ("sigma_anchor" in pop and (GRID[j] < 500 or GRID[j] > 5000)),
            "curve SD clamps",
        )
    for row in summary["derived"]:
        j = int(np.flatnonzero(GRID == row["distance_km"])[0])
        value = (
            allsd[:, j]
            if row["quantity"] == "residual_sd_modeled_response"
            else 1
            + flat.get("beta", np.zeros(n))
            - flat.get("gamma", np.zeros(n)) * 500 / (GRID[j] + 500)
        )
        require(
            positive or row["quantity"] == "residual_sd_modeled_response",
            "signed source has no elasticity",
        )
        close([row[k] for k in ["q05", "q50", "q95"]], quantiles(value))
    strata = {
        "all": np.ones(len(ids), bool),
        "under-500km": d < 500,
        "500-to-2000km": (d >= 500) & (d < 2000),
        "2000-to-5000km": (d >= 2000) & (d < 5000),
        "5000km-and-above": d >= 5000,
    }
    expected_cells = {
        (label, scale, q)
        for label, mask in strata.items()
        if mask.any()
        for scale in ["modeled-response", "native-minutes"]
        for q in PROBS
    }
    require(
        {(r["stratum"], r["scale"], r["quantile"]) for r in summary["conditional_ppc"]}
        == expected_cells,
        "exact nonempty PPC strata",
    )
    for row in summary["conditional_ppc"]:
        mask = strata[row["stratum"]]
        native = row["scale"] == "native-minutes"
        rep = measure if native else conditional
        observed = (np.log(lane.y[ids]) if positive else lane.y[ids]) if native else y
        q = quantiles(np.quantile(rep[:, mask], row["quantile"], axis=1))
        oq = float(np.quantile(observed[mask], row["quantile"]))
        if native and positive:
            close([row["replicated_log_" + k] for k in ["q05", "q50", "q95"]], q)
            q = np.exp(q)
            close(row["observed_log_native"], oq)
            oq = math.exp(oq)
        close([row["replicated_" + k] for k in ["q05", "q50", "q95"]], q)
        close(row["observed"], oq)
    return dict(
        passed=True,
        all_population_draws=n,
        selected_predictive_draws=800,
        parameter_rows=len(parameters),
        record_intervals=len(ids),
        curve_rows=len(summary["curves"]),
        derived_rows=len(summary["derived"]),
        conditional_ppc_rows=len(summary["conditional_ppc"]),
        truth_inclusions_not_pass_rule=True,
        signed_target_preserved=not positive,
        new_event_u_shared_across_grid=True,
        no_unused_u_rng_consumed=("tau_event" not in pop),
    )


def render_diagnostics(post, sample_stats, job, output):
    """S5 accessible chain styles generalized to every selected population coordinate."""
    import matplotlib

    matplotlib.use("Agg")
    from textwrap import fill

    import matplotlib.pyplot as plt
    from scipy.stats import rankdata

    output = Path(output)
    require(output.is_dir(), "explicit existing TEMP audit folder required")
    colors = ["#0072B2", "#D55E00", "#6A3D9A", "#333333"]
    styles = ["-", "--", "-.", ":"]
    columns = []
    for name in post.data_vars:
        value = post[name].values
        columns.extend(
            [(f"{name}[{[500, 2000, 5000][j]}km]", value[:, :, j]) for j in range(3)]
            if value.ndim == 3
            else [(str(name), value)]
        )
    require(all(v.shape == (4, 2000) for _, v in columns), "literal four-by2000 diagnostics")
    divergence = np.asarray(sample_stats.diverging.values)
    require(divergence.shape == (4, 2000), "complete divergence coordinates")
    fig, axs = plt.subplots(len(columns), 2, figsize=(12, 2.1 * len(columns) + 0.8), squeeze=False)
    maxrank = 0
    for row, (name, value) in enumerate(columns):
        ranks = rankdata(value.ravel()).reshape(4, 2000)
        counts = [np.histogram(v, bins=np.linspace(0.5, 8000.5, 21))[0] for v in ranks]
        maxrank = max(maxrank, int(np.max(abs(np.array(counts) - 100))))
        for chain in range(4):
            style = dict(color=colors[chain], linestyle=styles[chain], label=f"Chain {chain + 1}")
            axs[row, 0].plot(value[chain], lw=0.5, **style)
            axs[row, 1].step(np.arange(20) + 0.5, counts[chain], where="mid", lw=1.3, **style)
            ix = np.flatnonzero(divergence[chain])
            axs[row, 0].scatter(ix, value[chain, ix], s=13, c="#B22222", marker="x", zorder=5)
        axs[row, 0].set(xlabel="Retained draw", ylabel=name)
        axs[row, 1].set(xlabel="Pooled rank bin", ylabel="Count per chain")
        axs[row, 1].axhline(100, c="#999999", lw=0.6)
    handles, labels = axs[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        ncol=4,
        frameon=False,
        fontsize=10,
    )
    fig.suptitle(
        fill(job["id"], 76)
        + f"\nFour chains ×2000; divergences={int(divergence.sum())}; computational smoke only",
        fontsize=11,
        y=0.995,
    )
    fig.text(
        0.02,
        0.006,
        (
            "Source: supplied closed native population draws. "
            "Pooled ranks are descriptive; no coverage claim."
        ),
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.025, 1, 0.9))
    trace = output / "trace-rank.png"
    require(not trace.exists(), "no plot overwrite")
    fig.savefig(trace, dpi=110)
    plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.8))
    for chain in range(4):
        e = sample_stats.energy.values[chain]
        style = dict(
            bins=40,
            density=True,
            histtype="step",
            color=colors[chain],
            linestyle=styles[chain],
            linewidth=1.4,
            label=f"Chain {chain + 1}",
        )
        axs[0].hist(e - e.mean(), **style)
        axs[1].hist(np.diff(e), **style)
    axs[0].set(xlabel="Centered energy (nat)", ylabel="Density")
    axs[1].set(xlabel="Energy transition (nat)", ylabel="Density")
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.85),
        ncol=4,
        frameon=False,
        fontsize=10,
    )
    fig.suptitle(fill(job["id"] + " | energy overlap", 90), fontsize=11, y=0.995)
    fig.text(
        0.02,
        0.015,
        (
            "Source: supplied closed sample statistics. "
            "Visual inspection does not replace numerical screens."
        ),
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.76))
    energy = output / "energy.png"
    require(not energy.exists(), "no plot overwrite")
    fig.savefig(energy, dpi=120)
    plt.close(fig)
    return dict(
        trace_rank=str(trace),
        energy=str(energy),
        maximum_rank_bin_deviation=maxrank,
        visual_review="PENDING_REQUIRED_AFTER_CLOSED_ACTUAL_DATA",
    )


def require_closed_notice(notice, job_id):
    require(
        notice.get("root_closed_authorization") is True
        and notice.get("closed") is True
        and job_id in notice.get("job_ids", []),
        "Root closed-job notice required before Gate/full-design/native reads",
    )
    require(
        notice.get("accepted_check_review") is True,
        "accepted one-check review required before full-design reads",
    )


def audit_closed_job(root, job_id, *, notice, process_proof, output):
    """Explicit future entry; source/native loading is downstream of closure guards.

    Root/PILOT supplies a public immutable closed runtime proof with cost1,
    marker1, complete process files and fresh inclusive quota/closed-prefix QA.
    It must not contain a live private STATE pin. Mathematical acceptance and
    plots are recorded for Root review; this never publishes a Gate or resumes.
    """
    require_closed_notice(notice, job_id)
    require(
        process_proof.get("closed") is True
        and process_proof.get("job_id") == job_id
        and type(process_proof.get("cost")) is int
        and process_proof.get("cost") == 1
        and type(process_proof.get("start_markers")) is int
        and process_proof.get("start_markers") == 1
        and process_proof.get("quota_and_closed_prefix_passed") is True,
        "independently checked closed one-call runtime/physical/quota proof required",
    )
    import xarray as xr

    from analysis.arrival import model_development_data as data
    from analysis.arrival import model_development_recovery as G
    from analysis.arrival.evidence import read_rows, sha256
    from analysis.arrival.model_sensitivity_priors import build_sensitivity_model

    root = Path(root).resolve()
    admission = G.verify_gate(root)
    job = next(j for j in admission["gate"]["jobs"] if j["id"] == job_id)
    require(
        process_proof.get("job") == job,
        "closed process proof must bind exact literal truth/model/seeds job",
    )
    require(job["role"] == "full_design_recovery", "literal admitted recovery role")
    process_files = process_proof["files"]
    require(
        not any(
            "STATE" in p or p.endswith("development-state.json") or p.startswith("context/")
            for p in process_files
        ),
        "no private state/context proof paths",
    )
    data._unchanged(root, {**admission["files"], **process_files})
    # Unconditional full native/diagnostic/seeded5CSV/truth/oracle semantic replay.
    proof: dict[str, Any] = G.case_artifacts(root, job, admission["files"])
    folder, raw = G.case_paths(root, job)
    target, spec = admission["specs"][job["model_key"]]
    views = data.load_full_development_lanes(root, admission["files"])
    design = views["combined"][target]
    fake, generation = generation_checks(design, spec["kind"], job["truth"], job["simulator_seed"])
    ids = np.flatnonzero(fake.included)
    post = G.fit._read_population(root, raw, fake, ids, spec["kind"])
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        require(
            set(observed.data_vars)
            == {
                "response",
                "native_minutes",
                "distance_km",
                "reference_minutes",
                "event_id",
                "sequence",
                "site_id",
            },
            "seven synthetic observed variables required",
        )
        require(
            observed.record.values.tolist() == [fake.record_ids[i] for i in ids],
            "raw synthetic ordered membership",
        )
        for name, value in dict(
            response=fake.response[ids],
            native_minutes=fake.y[ids],
            distance_km=fake.distance_km[ids],
            reference_minutes=fake.reference_minutes[ids],
            event_id=np.asarray(fake.event_ids)[ids],
            sequence=np.asarray(fake.sequences)[ids],
            site_id=np.asarray(fake.site_ids)[ids],
        ).items():
            require(
                np.array_equal(observed[name].values, value),
                "independent simulation/raw native identity: " + name,
            )
        require(
            observed.attrs.get("target") == target
            and observed.attrs.get("role") == "full_design_recovery",
            "native synthetic source/role",
        )
    base, wider, settings = G.fit._priors(root, target, spec)
    model = build_sensitivity_model(
        fake, spec["kind"], base, spec["prior_variant"], wider_prior=wider, indices=ids
    )
    density = density_checks(model, fake, spec["kind"], job["truth"], settings, post)
    summary = json.loads((folder / "summary.json").read_text())
    tables = summary_checks(
        fake,
        spec["kind"],
        post,
        job["conditional_seed"],
        summary,
        job["truth"],
        read_rows(folder / "truth-quantiles.csv"),
    )
    output = Path(output).absolute()
    require(
        output == Path("/private/tmp") / ("ms6-recovery-science-" + job_id)
        and output.resolve() == output
        and not output.exists(),
        "one new literal TEMP scientific output required",
    )
    output.mkdir()
    with xr.open_dataset(raw, group="sample_stats", engine="h5netcdf") as sample_stats:
        G.fit.references._native_protocol(post, sample_stats)
        pictures = render_diagnostics(post, sample_stats, job, output)
        native = dict(
            inference_library=post.attrs["inference_library"],
            inference_library_version=post.attrs["inference_library_version"],
            tuning_steps=int(post.attrs["tuning_steps"]),
            settings=json.loads(sample_stats.attrs["inference_library_settings"]),
            user_sampler_seed=job["sampler_seed"],
            native_seed_scope=(
                "Internal native seed may be derived; literal user seed "
                "is bound by source/job/process proof."
            ),
        )
    files = {**admission["files"], **proof["files"], **process_files}
    for p, h in files.items():
        require(sha256(root / p) == h, "source/raw/producer drift after scientific QA: " + p)
    diagnostics = json.loads((folder / "diagnostics.json").read_text())
    require(
        diagnostics.get("screen_passed") is True, "no reinterpretation of failed native diagnostics"
    )
    result = dict(
        status="independent_recovery_numerics_passed_visual_review_pending",
        job=job,
        generation=generation,
        density=density,
        summary=tables,
        native_protocol=native,
        diagnostics=diagnostics,
        figures=pictures,
        files=files,
        runtime_proof=process_proof,
        visual_review="PENDING_REQUIRED",
        coverage_or_calibration_or_physical_claim=False,
        truth_inclusion_never_pass_rule=True,
        new_sampler_calls_in_QA=0,
        project_Gates_or_STATE_written=False,
    )
    with (output / "scientific-check.json").open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args()
    if args.describe:
        print(
            json.dumps(
                {
                    "api": [
                        "ast_manual",
                        "generation_checks",
                        "density_checks",
                        "summary_checks",
                        "render_diagnostics",
                        "require_closed_notice",
                        "audit_closed_job",
                    ],
                    "actual_use": (
                        "After Root acceptedcheck+closedG2: verify Gate/source/process and "
                        "unconditional G.case_artifacts first; then admitted arrays only. "
                        "Every picture must be reopened and chart-checked. "
                        "No actual-read or sampling CLI."
                    ),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
