"""Prepare finite direct-ancestral MS-5 prior checks; this never authorizes a fit."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_sensitivity_inputs as source_io  # noqa: E402
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_prior import read_curvature_prior  # noqa: E402
from analysis.arrival.model_data import load_lanes  # noqa: E402
from analysis.arrival.model_sensitivity_design import (  # noqa: E402
    FORMS,
    PRIOR_VARIANTS,
    build_sensitivity_design,
)
from analysis.arrival.model_sensitivity_fit import (  # noqa: E402
    COMPARISON_REVIEW,
    CV_REVIEW,
    sensitivity_jobs,
)
from analysis.arrival.model_sensitivity_fit import (
    CONSUMED as FIT_CONSUMED,
)
from analysis.arrival.model_sensitivity_priors import (  # noqa: E402
    POSITIVE_NATIVE_MOMENTS,
    PRIOR_ORIGIN,
    T4_MATCHED_SCALE,
    _prior_settings,
    population_prior_draws,
    prior_predictive_log_or_native,
)
from analysis.arrival.model_sensitivity_summary import (  # noqa: E402
    GRID_KM,
    _native_quantiles,
    _quantiles,
)
from analysis.arrival.model_validation_report import write_table  # noqa: E402
from analysis.arrival.models import read_prior  # noqa: E402

CONSUMED = sorted(
    set(
        [
            *FIT_CONSUMED,
            "scripts/prepare_arrival_sensitivity_priors.py",
            "tests/test_arrival_sensitivity_prior_preparation.py",
        ]
    )
)


def prior_configurations():
    """Eight base forms,32 matched form/variant changes, then the gamma-only change."""
    specs = [(target, kind, "base") for target, kind in FORMS]
    specs += [(target, kind, variant) for target, kind in FORMS for variant in PRIOR_VARIANTS]
    specs += [("NCEI-native-duration", "mean-curvature", "gamma_wider_only")]
    return [
        {
            "order": j,
            "target": target,
            "kind": kind,
            "prior_variant": variant,
            "draws": 2000,
            "seed": 2896110800 + 1000 * j,
            "prediction_seed": 2896110801 + 1000 * j,
        }
        for j, (target, kind, variant) in enumerate(specs)
    ]


def _unchanged(root, pins):
    if any(sha256(checked_path(root, name)) != digest for name, digest in pins.items()):
        raise ValueError("prior-preparation source identity changed")


def admit_sources(root):
    """Only receipt/reference metadata is interpreted before source admission."""
    if not (root / COMPARISON_REVIEW).is_file():
        raise ValueError(
            "independently accepted curvature comparison required before prior preparation"
        )
    review = json.loads((root / COMPARISON_REVIEW).read_text())
    if (
        review.get("status") != "accepted_curvature_sequence_predictive_comparison"
        or review.get("independent_checker") is not True
        or review.get("confirmation_outcomes_parsed") is not False
        or review.get("reserved_outcomes") != "sealed"
        or not review.get("files")
    ):
        raise ValueError("complete independently accepted curvature comparison required")
    pins = {**review["files"], COMPARISON_REVIEW: sha256(root / COMPARISON_REVIEW)}
    _unchanged(root, pins)
    if CV_REVIEW not in pins:
        raise ValueError("comparison must close the accepted complete curvature CV")
    cv = json.loads((root / CV_REVIEW).read_text())
    if (
        cv.get("status") != "accepted_all_curvature_sequence_computations"
        or cv.get("independent_checker") is not True
        or cv.get("confirmation_outcomes_parsed") is not False
        or cv.get("reserved_outcomes") != "sealed"
        or not cv.get("files")
        or any(pins.get(name) != digest for name, digest in cv["files"].items())
    ):
        raise ValueError("complete accepted CV closure required before any outcome loader")

    def merge(entries):
        for name, digest in entries.items():
            if name in pins and pins[name] != digest:
                raise ValueError("conflicting accepted source identity")
            if sha256(checked_path(root, name)) != digest:
                raise ValueError("unmatched accepted source identity")
            pins[name] = digest

    merge(
        {
            name: sha256(checked_path(root, name))
            for name in [*CONSUMED, *source_io.required_sensitivity_paths()]
        }
    )
    census = json.loads((root / source_io.CENSUS_REVIEW).read_text())
    merge(census.get("files", {}))
    inputs = json.loads((root / source_io.CENSUS_INPUTS).read_text())
    merge(inputs.get("files", {}))
    source_io.verify_sensitivity_inputs(root, pins)
    _unchanged(root, pins)
    return pins


def _prior(root, target, kind, variant):
    base = (
        read_curvature_prior(root, "base")
        if kind == "mean-curvature"
        else read_prior(root, target, "base")
    )
    wider = None
    if variant == "joint_wider":
        wider = (
            read_curvature_prior(root, "joint_wider")
            if kind == "mean-curvature"
            else read_prior(root, target, "wider")
        )
    return base, wider


def _strict_json(path, value):
    json.dumps(value, allow_nan=False)
    write_json(path, value)


def _new_output(root, output):
    if (
        not output.is_absolute()
        or not output.is_relative_to(root)
        or output.resolve() != output
        or output.exists()
        or any(path.is_symlink() for path in [output, *output.parents])
    ):
        raise ValueError("new nonsymlink project-local prior-preparation output required")


def prepare(root: Path, output: Path):
    """Generate41 reproducible prior checks and the prospective55-job manifest."""
    root = root.resolve()
    _new_output(root, output)
    pins = admit_sources(root)
    lanes, contract = load_lanes(root)
    metadata = source_io.load_sensitivity_inputs(root, lanes, pins)
    design = build_sensitivity_design(lanes, metadata)
    jobs = sensitivity_jobs(design)
    configurations = prior_configurations()
    parameters, predictions, checks, settings = [], [], [], []
    for config in configurations:
        target, kind, variant = [config[key] for key in ["target", "kind", "prior_variant"]]
        identity = {key: config[key] for key in ["order", "target", "kind", "prior_variant"]}
        base, wider = _prior(root, target, kind, variant)
        family, scales = _prior_settings(kind, base, variant, wider)
        settings.append(
            {
                **config,
                "family": family,
                "distribution_scales": scales,
                "base_prior_sd": base,
                "wider_prior_sd": wider,
            }
        )
        population = population_prior_draws(
            target,
            kind,
            base,
            variant,
            draws=config["draws"],
            seed=config["seed"],
            wider_prior=wider,
        )
        for name, values in population.items():
            for anchor in range(3) if name == "sigma_anchor" else [None]:
                parameters.append(
                    {
                        **identity,
                        "parameter": name,
                        "anchor_km": None if anchor is None else [500, 2000, 5000][anchor],
                        "measure": "signed_minutes"
                        if target == "T-CAL"
                        else "log_ratio_parameters",
                        **_quantiles(values if anchor is None else values[:, anchor]),
                    }
                )
        if kind == "mean-curvature":
            with np.errstate(over="ignore", invalid="ignore"):
                elasticity = 1 + population["beta"] - population["gamma"] / 3
            parameters.append(
                {
                    **identity,
                    "parameter": "median_log_distance_elasticity_1000km",
                    "anchor_km": None,
                    "measure": "dimensionless",
                    **_quantiles(elasticity),
                }
            )
        simulated = prior_predictive_log_or_native(
            target, kind, population, GRID_KM, seed=config["prediction_seed"]
        )
        positive = target != "T-CAL"
        native_measure = simulated["log_native_minutes" if positive else "native_minutes"]
        unrepresentable = 0
        if positive:
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                native = np.exp(native_measure)
            unrepresentable = int(np.count_nonzero(~np.isfinite(native) | (native <= 0)))
        for j, distance in enumerate(GRID_KM):
            labels = {**identity, "distance_km": float(distance)}
            predictions.append(
                {
                    **labels,
                    "space": "modeled-response",
                    "measure": simulated["response_measure"],
                    **_quantiles(simulated["response"][:, j]),
                }
            )
            if positive:
                predictions.append(
                    {
                        **labels,
                        "space": "log-native-minutes",
                        "measure": "log_minutes",
                        **_quantiles(native_measure[:, j]),
                    }
                )
            predictions.append(
                {
                    **labels,
                    "space": "native-minutes",
                    "measure": "positive_minutes" if positive else "signed_minutes",
                    **_native_quantiles(native_measure[:, j], positive),
                }
            )
        checks.append(
            {
                **identity,
                "draws": config["draws"],
                "population_nonfinite_values": int(
                    sum(np.count_nonzero(~np.isfinite(v)) for v in population.values())
                ),
                "response_nonfinite_values": simulated["nonfinite_output_values"],
                "modeled_response_nonfinite_values": int(
                    np.count_nonzero(~np.isfinite(simulated["response"]))
                ),
                "unrepresentable_native_values": unrepresentable,
                "positive_native_moments": POSITIVE_NATIVE_MOMENTS
                if positive
                else "not_applicable_signed_target",
            }
        )
    _unchanged(root, pins)
    _new_output(root, output)
    output.mkdir(parents=True)
    summary = {
        "status": "computed_pending_prior_predictive_review",
        "configurations": len(configurations),
        "base_configurations": 8,
        "perturbed_configurations": 33,
        "ancestral_draws_per_configuration": 2000,
        "total_ancestral_draws": 82000,
        "initial_fit_jobs": len(jobs),
        "reused_training_posteriors": len(design["reuse_training_posteriors"]),
        "max_sampler_call_slots": 110,
        "sampler_calls": 0,
        "fit_authorized": False,
        "human_interpretation_review_required": True,
        "prior_origin": PRIOR_ORIGIN,
        "prior_scale_origin": (
            "existing_declared_base_and_wider_SD_settings_plus_analyst_post_EDA_perturbations"
        ),
        "t4_matched_scale_factor": T4_MATCHED_SCALE,
        "t4_match": "absolute_central95percent_quantile_not_standard_deviation",
        "moment_warning": POSITIVE_NATIVE_MOMENTS,
        "parameter_variance_warning": (
            "finite_Student_t4_parameter_variance_does_not_establish_"
            "finite_positive_native_predictive_moments"
        ),
        "quantile_policy": "stable_empirical_quantiles_no_nonfinite_draw_filtering_or_clipping",
        "predictive_means_or_variances_reported": False,
        "checks": checks,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
    try:
        _strict_json(
            output / "inputs.json",
            {
                "files": pins,
                "source_files": contract,
                "comparison_review": COMPARISON_REVIEW,
                "prior_configurations": settings,
                "grid_distance_km": GRID_KM.tolist(),
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        _strict_json(
            output / "case-manifest.json",
            {
                **design,
                "jobs": jobs,
                "prior_configurations": configurations,
                "max_sampler_call_slots": 110,
                "fit_authorized": False,
                "prior_predictions_reviewed": False,
            },
        )
        write_table(output / "population-prior-quantiles.csv", parameters)
        write_table(output / "new-event-prior-quantiles.csv", predictions)
        _strict_json(output / "summary.json", summary)
        _unchanged(root, pins)
        _strict_json(
            output / "output-checksums.json",
            {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()},
        )
        _unchanged(root, pins)
    except Exception:
        summary["status"] = "prior_preparation_failure"
        _strict_json(output / "summary.json", summary)
        raise
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(Path(__file__).resolve().parents[1], args.output.absolute())
