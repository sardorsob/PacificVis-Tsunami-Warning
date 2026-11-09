"""Reviewed MS-5 summaries: 55 sensitivity fits and 14 historical views.

No fitting, ranking, cross-cohort score comparison or physical-onset inference.
All admission checks precede native loaders, NetCDF reads and summary metrics.
The plotting functions consume supplied tables and open no scientific inputs.
"""

# pyright: basic
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from analysis.arrival import model_sensitivity_fit as fit
from analysis.arrival import model_sensitivity_references as refs
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_data import load_lanes
from analysis.arrival.model_sensitivity_design import FORMS, NONPRIOR_SCENARIOS
from analysis.arrival.model_sensitivity_priors import (
    T4_MATCHED_SCALE,
    _population_spec,
    _prior_settings,
)
from analysis.arrival.model_sensitivity_summary import GRID_KM, summarize_posterior
from analysis.arrival.model_validation_report import write_table
from analysis.arrival.models import read_prior

GATE = fit.OUTPUT + "/review-acceptance.json"
PLAN = fit.OUTPUT + "/plan.json"
RUN_SUMMARY = fit.OUTPUT + "/run-summary.json"
REFERENCE_SUMMARY = {"seed_base": 2916110800, "seed_stride": 1000, "draws": 800}
CONSUMED = tuple(
    sorted(
        set(fit.CONSUMED)
        | set(refs.CONSUMED)
        | {
            "analysis/arrival/model_sensitivity_report.py",
            "scripts/summarize_arrival_sensitivities.py",
            "scripts/run_arrival_sensitivities.py",
        }
    )
)
TABLES = (
    "posterior-parameters",
    "population-median-and-predictive-quantiles",
    "supported-distance-sensitivity-changes",
    "conditional-predictive-checks",
    "training-cohorts-and-omissions",
)
SCENARIO_LABELS = {
    "coastal-only": "Coastal tide gauges only",
    "era-pre2007": "Reports before 2007",
    "era-2007-2013": "Reports in 2007–2013",
    "era-2014plus": "Reports from 2014 onward",
    "publisher-distance": "Publisher distance (algorithm unknown)",
    "omit-triage": "Omit four source triage flags",
    "component-assessed": "Component-assessed reports only",
    "omit-native-below10": "Omit durations below 10 minutes",
    "omit-lata-only": "Omit LATA report only",
    "omit-tohoku-and-chile": "Omit Tohoku and Chile 2010 sequences",
    "omit-definition": "Omit both definition-flag reports",
    "reuse-tohoku": "Omit Tohoku sequence (existing fit)",
    "reuse-chile2010": "Omit Chile 2010 sequence (existing fit)",
    "reuse-influential2014": "Omit SW Pacific 2014 sequence (existing fit)",
}
QUALIFICATIONS = (
    "These are source-specific reported-data sensitivities, conditional on reporting; "
    "they do not identify physical first arrival or actionable warning time.",
    "Population median 90% posterior bands describe parameter uncertainty. New-event "
    "report 90% predictive quantiles include event and report variation; "
    "they are a different type.",
    "Predictive summaries use 800 simulated draws and finite posterior draws. Tiny changes "
    "are not automatically material; interval overlap establishes neither "
    "equivalence nor a winner.",
    "The original NCEI linear and curved fits each retained 8/15 conditional predictive-check "
    "misses. The 1,125-minute LATA report remains a hard case in the full cohorts.",
    "Conditional checks use fitted events and are in-sample model criticism, not held-out "
    "validation. Finite autocorrelation calibration checks do not establish physical validity.",
    "Matched Student-t4 population priors change priors, not the Normal residual likelihood. "
    "Positive-native predictive means and variances can be infinite even under a posterior; "
    "only medians and quantiles are reported, with log-space validity retained.",
    "Priors are analyst choices informed by exploration, not expert facts. Era and omission "
    "stresses do not correct values or identify selection or missingness; omitting short rows "
    "does not fit a truncated population or a verified rounding model.",
    "Publisher distance units are km, but its algorithm is unknown. All dependent response, "
    "reference and predictor quantities change coherently; native durations and IDs stay fixed.",
    "The 1/2/5-km site keys preserve the mask and likelihood without a retained site effect; "
    "this does not demonstrate the absence of site effects. T-CAL lineage is unknown; "
    "independent cross-source pooling is not justified.",
    "Changes are compared within source and form on the common training-distance range only. "
    "This range check does not prove dense coverage between endpoints or geographic transfer. "
    "Changed cohorts receive no ELPD ranking, Bayes factor or new model selection.",
    "The 19-event development check is not revisited; 18 reserved outcomes remain sealed. "
    "This report remains pending independent scientific and figure review.",
)


def _path(root, name):
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or Path(name).as_posix() != name
        or any(p in {".", ".."} for p in name.split("/"))
    ):
        raise ValueError("literal project-relative path required")
    path = root / name
    if path.resolve() != path or not path.is_file():
        raise ValueError("project-local nonsymlink file required")
    return path


def _unchanged(root, pins):
    if not isinstance(pins, dict) or not pins:
        raise ValueError("complete reviewed pins required")
    for name, digest in pins.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or sha256(_path(root, name)) != digest
        ):
            raise ValueError("reviewed report source SHA changed")


def _require(pins, entries):
    if (
        not isinstance(entries, dict)
        or not entries
        or any(pins.get(p) != h for p, h in entries.items())
    ):
        raise ValueError("complete reviewed file closure required before loading")


def _read(root, pins, name):
    if name not in pins:
        raise ValueError("required metadata missing from accepted report closure")
    value = json.loads(_path(root, name).read_text())
    if not isinstance(value, dict):
        raise ValueError("metadata object required")
    return value


def verify_report_sources(root: Path) -> dict[str, Any]:
    """Hash the entire acceptance closure and all55 receipts before any loaders.

    No private controller state is read. More than55 charged calls would require
    an independently implemented/reviewed repair provenance map; this reader
    admits only the current original-attempt controller, without inventing one.
    """
    root = root.resolve()
    gate = json.loads(_path(root, GATE).read_text())
    if (
        gate.get("status") != "accepted_all_exploration_sensitivity_computations"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("reference_summary") != REFERENCE_SUMMARY
        or not set(CONSUMED) | {PLAN, RUN_SUMMARY, fit.GATE} <= set(gate.get("files", {}))
    ):
        raise ValueError("independently accepted complete MS-5 computations required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    _unchanged(root, pins)
    # Both APIs below inspect hashes, contracts and JSON metadata only.
    admission = fit.verify_gate(root)
    _require(pins, admission["files"])
    refs.verify_reference_sources(root, pins)
    plan, summary = (_read(root, pins, name) for name in [PLAN, RUN_SUMMARY])
    jobs = admission["gate"]["jobs"]
    if (
        plan.get("jobs") != jobs
        or plan.get("files") != admission["files"]
        or plan.get("gate_sha256") != pins[fit.GATE]
        or len(jobs) != 55
        or len({job["id"] for job in jobs}) != 55
    ):
        raise ValueError("immutable exact55case source/plan binding required")
    charged, started = summary.get("calls_charged"), summary.get("calls_started")
    if (
        type(charged) is not int
        or type(started) is not int
        or not 55 <= charged == started <= 110
        or summary.get("status") != "sensitivity_computations_complete"
        or summary.get("next_case") != 55
        or summary.get("planned_cases") != 55
        or summary.get("max_sampler_call_slots") != 110
        or summary.get("monitor_failures")
        or summary.get("confirmation_outcomes_parsed") is not False
        or summary.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("complete bounded controller summary required")
    if charged != 55:
        raise ValueError("separately reviewed repair provenance is not implemented by this reader")
    accepted = gate.get("accepted")
    if (
        not isinstance(accepted, list)
        or len(accepted) != 55
        or [entry.get("case_id") for entry in accepted] != [job["id"] for job in jobs]
    ):
        raise ValueError("exact55ordered accepted evidence entries required")
    for job, entry in zip(jobs, accepted, strict=True):
        folder = fit.OUTPUT + "/jobs/" + job["id"]
        receipt = folder + "/attempt-evidence.json"
        if (
            entry.get("charged_slots") != 1
            or entry.get("receipt") != receipt
            or entry.get("receipt_sha256") != pins.get(receipt)
        ):
            raise ValueError("literal accepted original-attempt receipt required")
        _require(pins, entry.get("files"))
        manifest = _read(root, pins, receipt)
        if manifest != {"case_id": job["id"], "files": entry["files"]}:
            raise ValueError("accepted receipt and file inventory differ")
        required = (
            {
                folder + "/" + name
                for name in [
                    "job.json",
                    "inputs.json",
                    "membership.json",
                    "sampling-start.json",
                    "result.json",
                    "diagnostics.json",
                    "sampling-diagnostics.csv",
                    "summary.json",
                    "parameters.csv",
                    "derived.csv",
                    "curves.csv",
                    "conditional-ppc.csv",
                    "record-intervals.csv",
                ]
            }
            | {fit.STORE + "/" + job["id"] + ".nc"}
            | {folder + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"]}
        )
        if not required <= set(entry["files"]):
            raise ValueError("all55 raw/summary/process artifacts required before any parsing")
    _unchanged(root, pins)
    return {
        "gate": gate,
        "files": pins,
        "jobs": jobs,
        "accepted": accepted,
        "admission": admission,
        "run_summary": summary,
    }


def _priors(root, target, kind, variant, inputs=None):
    if inputs is not None:
        base, wider = inputs["base_prior"], inputs.get("wider_prior")
    else:
        base = (
            read_curvature_prior(root, "base")
            if kind == "mean-curvature"
            else read_prior(root, target, "base")
        )
        wider = None
    family, scales = _prior_settings(kind, base, variant, wider)
    population = {}
    for name, (key, shape) in _population_spec(target, kind).items():
        positive = name in {"sigma", "sigma_anchor", "tau_event"}
        distribution = "StudentT4" if family == "t4" else "Normal"
        population[name] = {
            "distribution": ("Half" if positive else "") + distribution,
            "location": 0,
            "scale": float(scales[key]),
            "shape": list(shape),
            "scale_is_sd": family == "normal" and not positive,
            "units": "signed minutes" if target == "T-CAL" else "log reference ratio",
        }
    return {
        "variant": variant,
        "base": base,
        "joint_wider": wider,
        "global_power": {"power_0.5": 0.5, "power_1.5": 1.5}.get(variant),
        "population_priors": population,
        "event_conditional": "Normal(0,tau_event) unchanged; absent in pooled/distance forms",
        "t4_scale_factor": T4_MATCHED_SCALE if variant == "t4_matched" else None,
        "gamma_only_sd": 0.8 if variant == "gamma_wider_only" else None,
    }


def collect_views(root: Path):
    """Read verified new summaries; recompute only14 frozen historical references."""
    root = root.resolve()
    checked = verify_report_sources(root)
    pins, admission = checked["files"], checked["admission"]
    # Every case is replayed by the accepted worker, using its exact original pins.
    views = []
    for job, entry in zip(checked["jobs"], checked["accepted"], strict=True):
        files, receipt = fit.case_artifacts(root, job, admission["files"], accepted=entry)
        _require(pins, {**files, str(receipt.relative_to(root)): sha256(receipt)})
        folder = fit.OUTPUT + "/jobs/" + job["id"]
        summary = _read(root, pins, folder + "/summary.json")
        inputs = _read(root, pins, folder + "/inputs.json")
        views.append(
            {
                "view_id": job["id"],
                "target": job["target"],
                "kind": job["kind"],
                "role": "sensitivity",
                "scenario": job["scenario"],
                "prior_variant": job["prior_variant"],
                "distance_mode": job["distance_mode"],
                "training_record_ids": job["training_record_ids"],
                "omitted_record_ids": job["omitted_record_ids"],
                "excluded_record_ids": job["excluded_record_ids"],
                "summary": summary,
                "prior_specification": _priors(
                    root, job["target"], job["kind"], job["prior_variant"], inputs
                ),
                "provenance": {
                    "receipt": entry["receipt"],
                    "receipt_sha256": entry["receipt_sha256"],
                    "prediction_seed": job["seed"] + 1,
                    "new_sampler_calls": 1,
                },
            }
        )
    lanes, contract = load_lanes(root)
    if contract != admission["contract"]:
        raise ValueError("reference and sensitivity source contracts differ")
    provenance = []
    for order, descriptor in enumerate(refs.descriptors()):
        lane, kind, indices, posterior, proof = refs.load_reference(
            root, descriptor["key"], lanes, pins
        )
        seed = REFERENCE_SUMMARY["seed_base"] + REFERENCE_SUMMARY["seed_stride"] * order
        summary = summarize_posterior(
            lane, kind, posterior, indices=indices, seed=seed, draws=REFERENCE_SUMMARY["draws"]
        )
        if not fit._summary_valid(summary):
            raise ValueError("finite valid historical reference summary required")
        original = lanes[lane.target]
        chosen = set(summary["membership"])
        proof = {
            **proof,
            "summary_seed": seed,
            "summary_draws": REFERENCE_SUMMARY["draws"],
            "descriptor_order": order,
        }
        provenance.append(proof)
        views.append(
            {
                "view_id": descriptor["key"],
                "target": lane.target,
                "kind": kind,
                "role": descriptor["role"],
                "scenario": descriptor["role"],
                "prior_variant": "base",
                "distance_mode": descriptor["distance_mode"],
                "training_record_ids": summary["membership"],
                "omitted_record_ids": [
                    rid
                    for rid, keep in zip(original.record_ids, original.included, strict=True)
                    if keep and rid not in chosen
                ],
                "excluded_record_ids": [
                    rid
                    for rid, keep in zip(original.record_ids, original.included, strict=True)
                    if not keep
                ],
                "summary": summary,
                "prior_specification": _priors(root, lane.target, kind, "base"),
                "provenance": proof,
            }
        )
    _unchanged(root, pins)
    return views, provenance, pins, checked["run_summary"]


def _identity(view):
    return {
        key: view[key]
        for key in [
            "view_id",
            "target",
            "kind",
            "role",
            "scenario",
            "prior_variant",
            "distance_mode",
        ]
    }


def _valid_summary(view):
    summary = view["summary"]
    if (
        summary.get("target") != view["target"]
        or summary.get("kind") != view["kind"]
        or summary.get("membership") != view["training_record_ids"]
        or not fit._summary_valid(summary)
        or summary.get("conditional_predictive_draws") != 800
        or summary.get("native_predictive_means_or_variances_reported") is not False
    ):
        raise ValueError("coherent accepted quantile-only summary required")
    cohorts = [
        view[k] for k in ["training_record_ids", "omitted_record_ids", "excluded_record_ids"]
    ]
    joined = [rid for group in cohorts for rid in group]
    if (
        not cohorts[0]
        or any(not isinstance(rid, str) or not rid for rid in joined)
        or len(joined) != len(set(joined))
    ):
        raise ValueError("nonempty unique disjoint ordered training/omission cohorts required")
    support = summary["support"]
    if support["records"] != len(cohorts[0]) or any(
        sum(support[name].values()) != len(cohorts[0])
        for name in ["event_counts", "sequence_counts"]
    ):
        raise ValueError("training/event/sequence count reconciliation required")
    for group in ["parameters", "derived"]:
        for row in summary[group]:
            values = [row[k] for k in ["q05", "q50", "q95"]]
            if any(v is None or not math.isfinite(v) for v in values) or not (
                values[0] <= values[1] <= values[2]
            ):
                raise ValueError("finite ordered parameter/derived quantiles required")
    curves = summary["curves"]
    if len(curves) != 18 or {(r["curve"], r["distance_km"]) for r in curves} != {
        (c, float(d)) for c in ["population_median", "new_event"] for d in GRID_KM
    }:
        raise ValueError("exact fixed nine-distance/two-type curves required")
    low, high = [summary["support"][k] for k in ["distance_km_min", "distance_km_max"]]
    if not 0 < low <= high < math.inf:
        raise ValueError("finite positive ordered training distance support required")
    for row in curves:
        within = low <= row["distance_km"] <= high
        if row["within_training_distance_range"] is not within:
            raise ValueError("curve support flag differs from literal training range")
        for keys in [["q05", "q50", "q95"]] + (
            [["log_q05", "log_q50", "log_q95"]] if view["target"] != "T-CAL" else []
        ):
            values = [row[k] for k in keys]
            if (
                any(type(v) not in {int, float} or not math.isfinite(v) for v in values)
                or not values[0] <= values[1] <= values[2]
            ):
                raise ValueError("finite ordered curve quantiles required")
        if view["target"] != "T-CAL" and any(
            not math.isclose(math.log(row[k]), row["log_" + k], abs_tol=1e-12)
            for k in ["q05", "q50", "q95"]
        ):
            raise ValueError("native quantiles must retain their exact log-space meaning")


def sensitivity_tables(views: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Pure within-form summaries; differences of marginal medians, not paired draws.

    Changes have no posterior interval: subtracting independent marginal bounds
    would not be an interval for a difference. Unsupported cells keep None.
    """
    if len(views) != 69 or len({v["view_id"] for v in views}) != 69:
        raise ValueError("exact69unique views required")
    base = {(v["target"], v["kind"]): v for v in views if v["role"] == "base"}
    if set(base) != set(FORMS) or sum(v["role"] == "base" for v in views) != 8:
        raise ValueError("exact eight source/form base references required")
    if (
        sum(v["role"] == "sensitivity" for v in views) != 55
        or sum(v["role"].startswith("reuse-") for v in views) != 6
    ):
        raise ValueError("55 new plus six existing deletion views required")
    tables = {name: [] for name in TABLES}
    for view in views:
        _valid_summary(view)
        same_base = base[view["target"], view["kind"]]
        if set(view["training_record_ids"] + view["omitted_record_ids"]) != set(
            same_base["training_record_ids"]
        ):
            raise ValueError("every view must partition its full source-specific base cohort")
        identity, summary = _identity(view), view["summary"]
        positive = view["target"] != "T-CAL"
        modeled_units = "log reference ratio" if positive else "signed minutes"
        for group in ["parameters", "derived"]:
            for row in summary[group]:
                if "distance_km" in row and not row["within_training_distance_range"]:
                    continue
                units = (
                    "dimensionless"
                    if row.get("quantity", "").endswith("elasticity")
                    else modeled_units
                )
                tables[TABLES[0]].append(
                    {
                        **identity,
                        "row_type": group,
                        **row,
                        "units": units,
                        "interval_type": "90% marginal posterior interval",
                        "prior_specification": json.dumps(
                            view["prior_specification"], sort_keys=True
                        ),
                    }
                )
        for row in summary["curves"]:
            if row["within_training_distance_range"]:
                tables[TABLES[1]].append(
                    {
                        **identity,
                        **row,
                        "units": "minutes",
                        "interval_type": "90% posterior band for population median"
                        if row["curve"] == "population_median"
                        else "90% new-event report predictive quantiles",
                    }
                )
        originals = {
            r["distance_km"]: r
            for r in same_base["summary"]["curves"]
            if r["curve"] == "population_median"
        }
        for row in summary["curves"]:
            if row["curve"] != "population_median":
                continue
            original = originals[row["distance_km"]]
            supported = (
                row["within_training_distance_range"] and original["within_training_distance_range"]
            )
            change = (
                None
                if not supported
                else (
                    row["log_q50"] - original["log_q50"]
                    if positive
                    else row["q50"] - original["q50"]
                )
            )
            with np.errstate(over="ignore", under="ignore"):
                ratio = None if change is None or not positive else float(np.exp(change))
            representable = ratio is None or math.isfinite(ratio) and ratio > 0
            tables[TABLES[2]].append(
                {
                    **identity,
                    "distance_km": row["distance_km"],
                    "baseline_view_id": same_base["view_id"],
                    "common_supported": bool(supported),
                    "median_log_shift": change if positive else None,
                    "native_median_ratio": ratio if representable else None,
                    "native_ratio_representable": representable if supported and positive else None,
                    "signed_median_shift_minutes": change if not positive else None,
                    "comparison": "difference_of_marginal_posterior_medians_no_difference_interval",
                    "support_rule": (
                        "intersection_of_training_distance_ranges_not_dense_coverage_proof"
                    ),
                }
            )
        for row in summary["conditional_ppc"]:
            observed = row["observed"]
            low, high = row["replicated_q05"], row["replicated_q95"]
            if any(x is None or not math.isfinite(x) for x in [observed, low, high]):
                raise ValueError("finite observed and replicated PPC quantiles required")
            tables[TABLES[3]].append(
                {
                    **identity,
                    **row,
                    "observed_outside_replicated_90": not low <= observed <= high,
                    "units": "minutes" if row["scale"] == "native-minutes" else modeled_units,
                    "check_scope": "conditional_fitted_events_in_sample_not_held_out",
                }
            )
        tables[TABLES[4]].append(
            {
                **identity,
                **summary["support"],
                "event_counts": json.dumps(summary["support"]["event_counts"], sort_keys=True),
                "sequence_counts": json.dumps(
                    summary["support"]["sequence_counts"], sort_keys=True
                ),
                "training_record_ids": json.dumps(view["training_record_ids"]),
                "omitted_record_ids": json.dumps(view["omitted_record_ids"]),
                "excluded_record_ids": json.dumps(view["excluded_record_ids"]),
                "omitted_count": len(view["omitted_record_ids"]),
                "excluded_count": len(view["excluded_record_ids"]),
                "new_sampler_calls": 1 if view["role"] == "sensitivity" else 0,
                "selection_interpretation": (
                    "conditional_on_reporting_no_missingness_identification"
                ),
            }
        )
    return tables


def figures(tables, output: Path):
    """Two figure families only; consume trusted supplied tables, no data loaders.

    Takeaway: show assumption sensitivity within each supported source/form.
    Audience: scientific readers. Destination: report. Baseline bands describe
    population medians, and heatmap cells are descriptive marginal-median shifts.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.lines import Line2D

    output = Path(output)
    curve_rows = tables[TABLES[1]]
    colors = {
        "power_0.5": "#0072B2",
        "power_1.5": "#0072B2",
        "joint_wider": "#D55E00",
        "t4_matched": "#009E73",
        "gamma_wider_only": "#CC79A7",
    }
    styles: dict[str, Any] = {
        "power_0.5": "-",
        "power_1.5": "--",
        "joint_wider": "-",
        "t4_matched": "-",
        "gamma_wider_only": ":",
    }
    labels = {
        "power_0.5": "Prior power 0.5",
        "power_1.5": "Prior power 1.5",
        "joint_wider": "Joint wider",
        "t4_matched": "Matched Student-t4",
        "gamma_wider_only": "Gamma SD 0.8 only",
    }
    with plt.rc_context(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    ):
        fig, axes = plt.subplots(4, 2, figsize=(13, 15), layout="constrained")
        for ax, (target, kind) in zip(axes.flat, FORMS, strict=True):
            rows = [
                r
                for r in curve_rows
                if r["target"] == target and r["kind"] == kind and r["curve"] == "population_median"
            ]
            baseline = sorted(
                [r for r in rows if r["role"] == "base"], key=lambda r: r["distance_km"]
            )
            d = [r["distance_km"] for r in baseline]
            ax.fill_between(
                d,
                [r["q05"] for r in baseline],
                [r["q95"] for r in baseline],
                color="0.85",
                label="Base 90% posterior band",
            )
            ax.plot(d, [r["q50"] for r in baseline], color="0.2", linewidth=2)
            for variant in labels:
                chosen = sorted(
                    [
                        r
                        for r in rows
                        if r["role"] == "sensitivity"
                        and r["scenario"] == "prior"
                        and r["prior_variant"] == variant
                    ],
                    key=lambda r: r["distance_km"],
                )
                if chosen:
                    ax.plot(
                        [r["distance_km"] for r in chosen],
                        [r["q50"] for r in chosen],
                        color=colors[variant],
                        linestyle=styles[variant],
                        linewidth=1.5,
                    )
            ax.set(
                xscale="log",
                xlabel="Distance (km; log scale)",
                ylabel="Reported duration (minutes; log scale)",
                title=(
                    f"{'NCEI' if target == 'NCEI-native-duration' else 'NTWC ' + target} · {kind}"
                ),
            )
            if target != "T-CAL":
                ax.set_yscale("log")
            else:
                ax.set_ylabel("Signed T-CAL (minutes)")
                ax.axhline(0, color="0.75", linewidth=0.7)
            ax.grid(axis="y", color="0.9", linewidth=0.5)
        fig.suptitle(
            "Prior assumptions and population medians\n"
            "Base posterior bands; alternative median lines; supported distances only",
            fontsize=15,
        )
        handles = [Line2D([], [], color="0.2", linewidth=2, label="Base (90% posterior band)")]
        handles += [
            Line2D([], [], color=colors[v], linestyle=styles[v], label=labels[v]) for v in labels
        ]
        fig.legend(
            handles=handles,
            loc="outside lower center",
            ncol=3,
            frameon=False,
            title="Source: NCEI reported durations; NTWC T-OBS and T-CAL",
            title_fontsize=10,
        )
        for ext in ["png", "svg"]:
            fig.savefig(output / f"prior-population-median-curves.{ext}", dpi=160)
        plt.close(fig)
        scenarios = [
            *NONPRIOR_SCENARIOS,
            "reuse-tohoku",
            "reuse-chile2010",
            "reuse-influential2014",
        ]
        rows = tables[TABLES[2]]
        arrays = []
        for kind in ["distance-scale", "mean-curvature"]:
            lookup = {
                (r["scenario"], r["distance_km"]): r
                for r in rows
                if r["target"] == "NCEI-native-duration" and r["kind"] == kind
            }
            arrays.append(
                np.array(
                    [
                        [
                            lookup[s, float(d)]["median_log_shift"]
                            if lookup[s, float(d)]["common_supported"]
                            else np.nan
                            for d in GRID_KM
                        ]
                        for s in scenarios
                    ],
                    dtype=float,
                )
            )
        finite = np.concatenate([a[np.isfinite(a)] for a in arrays])
        limit = max(float(np.max(np.abs(finite))) if finite.size else 0, 1e-6)
        fig, axes = plt.subplots(1, 2, figsize=(16, 9), layout="constrained", sharey=True)
        cmap = plt.get_cmap("RdBu_r").with_extremes(bad="0.92")
        for ax, kind, values in zip(
            axes, ["distance-scale", "mean-curvature"], arrays, strict=True
        ):
            image = ax.imshow(
                np.ma.masked_invalid(values),
                cmap=cmap,
                norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit),
                aspect="auto",
            )
            ax.set_xticks(range(9), ["20", "50", "100", "500", "1k", "2k", "5k", "10k", "20k"])
            ax.set_yticks(range(14), [SCENARIO_LABELS[s] for s in scenarios])
            ax.set(title=kind, xlabel="Distance (km)")
        fig.colorbar(image, ax=list(axes), label="Log change in population median versus full base")
        fig.suptitle(
            "NCEI data stresses within each mean form\n"
            "Gray: outside common distance support; 2014: SW Pacific sequence",
            fontsize=15,
        )
        fig.supxlabel(
            "Source: NCEI native reported durations; marginal posterior medians", fontsize=10
        )
        for ext in ["png", "svg"]:
            fig.savefig(output / f"ncei-data-stress-log-changes.{ext}", dpi=160)
        plt.close(fig)


def findings(tables, run_summary):
    """Reader-facing interpretation generated from tables without a winner rule."""
    curves = tables[TABLES[1]]
    changes = tables[TABLES[2]]
    ppc = tables[TABLES[3]]
    lines = [
        "# Sensitivity of reported arrival durations",
        "",
        f"This exploration report contains 55 new fits and 14 historical posterior views "
        f"(eight full base fits and six sequence-deletion training fits). The controller "
        f"charged {run_summary['calls_charged']} calls within a 110-call ceiling. "
        "Historical views require no new fits.",
        "",
        "T-OBS is reported observed UTC minus the reviewed USGS origin: a positive "
        "reported travel duration. T-CAL is reported estimated UTC minus reported "
        "observed UTC: a signed archive discrepancy, distinct from travel duration. "
        "Positive T-CAL means the estimate was later than the observation; negative "
        "T-CAL means the estimate was earlier. These definitions retain the reviewed "
        "source observation and forecast calendar contexts; they do not establish "
        "physical onset or independent timestamp accuracy.",
        "",
        "## What the tables show",
        "",
        "Each source and mean form has its own base comparison. Positive-duration changes "
        "are log shifts and native median ratios; signed T-CAL changes are absolute minutes. "
        "Changes subtract marginal posterior medians, without pretending they are paired "
        "posterior differences or assigning them difference intervals.",
        "",
        f"The curve table contains {len(curves)} supported typed intervals; "
        f"{sum(r['common_supported'] for r in changes)} of {len(changes)} change cells "
        "lie within both training-distance ranges. Unsupported change cells are blank. "
        "For publisher distances, a numeric km grid comparison is conditional on that "
        "alternative distance definition, not a matched-site prediction.",
        "",
        f"There are {sum(r['observed_outside_replicated_90'] for r in ppc)} observed "
        f"quantile checks outside their replicated 90% bounds among {len(ppc)} checks "
        "across all 69 views. These dependent, partly overlapping in-sample checks "
        "are descriptive; their count is not a calibration test or a model ranking.",
        "",
    ]
    lines += [
        "The following spans describe supported grid-cell changes across the scenarios "
        "in each row. They are descriptive spans, not uncertainty intervals or "
        "materiality thresholds; exact scenario results are in the change table.",
        "",
        "| Source | Mean form | Sensitivities | Supported cells | Median-change span |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for target, kind in FORMS:
        for prior in [True, False]:
            selected = [
                r
                for r in changes
                if r["target"] == target
                and r["kind"] == kind
                and r["role"] != "base"
                and r["common_supported"]
                and (r["scenario"] == "prior") == prior
            ]
            if not selected:
                continue
            key = "signed_median_shift_minutes" if target == "T-CAL" else "median_log_shift"
            values = [r[key] for r in selected]
            units = "minutes" if target == "T-CAL" else "log units"
            label = "Prior assumptions" if prior else "Data stresses and sequence deletions"
            lines.append(
                f"| {target} | {kind} | {label} | {len(selected)} | "
                f"{min(values):.4g} to {max(values):.4g} {units} |"
            )
    lines += ["", "## Interpretation and limits", ""]
    lines.extend(paragraph + "\n" for paragraph in QUALIFICATIONS)
    lines += [
        "## Reproduce and inspect",
        "",
        "Run `uv run --locked --offline python scripts/summarize_arrival_sensitivities.py "
        "--output <new-project-local-directory>` after the complete independent computation "
        "review exists. The reader checks all 55 attempt proofs, raw posterior bindings, "
        "source and reference closures before any scientific loading.",
        "",
        "Reference predictive seeds are 2916110800 + 1000 × descriptor order, with 800 draws. "
        "New cases retain their accepted seeded summaries. Exact inputs and source credits "
        "are retained in [inputs](inputs.json) and "
        "[reference provenance](reference-provenance.json). "
        "NCEI native reported durations and NTWC T-OBS/T-CAL remain separate targets.",
        "",
        "Tables: " + ", ".join(f"[{name}]({name}.csv)" for name in TABLES) + ".",
        "",
        "Figures: [prior curves](prior-population-median-curves.png) and "
        "[NCEI data stresses](ncei-data-stress-log-changes.png); matching SVG files are supplied.",
        "Inspect these multi-panel figures at full size or zoom the SVG; "
        "a 600-pixel thumbnail does not preserve their label sizes. "
        "The prior figure has eight source/form facets, log-distance axes, "
        "log-duration axes for positive targets and signed-minute axes for T-CAL. "
        "The NCEI heatmaps have 14 data/deletion scenarios and nine distance cells per form; "
        "unsupported cells are gray and colors encode signed log changes around zero.",
        "",
    ]
    return "\n".join(lines)


def report(root: Path, output: Path):
    """Create a new reproducible report only after complete computation acceptance."""
    root, output = root.resolve(), Path(output).absolute()
    if output.resolve() != output or not output.is_relative_to(root) or output.exists():
        raise ValueError("new nonsymlink project-local report directory required")
    views, provenance, pins, run_summary = collect_views(root)
    tables = sensitivity_tables(views)
    _unchanged(root, pins)
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "reference_summary": REFERENCE_SUMMARY,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    for name, rows in tables.items():
        write_table(output / (name + ".csv"), rows)
    write_json(output / "reference-provenance.json", {"references": provenance})
    write_json(
        output / "summary.json",
        {
            "status": "pending_independent_scientific_and_figure_review",
            "views": 69,
            "new_fits": 55,
            "base_references": 8,
            "reused_training_posteriors": 6,
            "calls_charged": run_summary["calls_charged"],
            "reference_summary": REFERENCE_SUMMARY,
            "table_rows": {name: len(rows) for name, rows in tables.items()},
            "qualifications": QUALIFICATIONS,
            "selection": "none",
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    figures(tables, output)
    (output / "findings.md").write_text(findings(tables, run_summary))
    _unchanged(root, pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
