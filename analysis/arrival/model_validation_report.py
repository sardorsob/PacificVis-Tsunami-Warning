"""Portable recovery and SBC summaries; computation checks do not validate physical targets."""

# pyright: basic
from __future__ import annotations

import json
import math
import os
import tomllib
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json, write_rows
from analysis.arrival.model_data import CONTRACT


def validation_design(root: Path, target: str) -> dict[str, Any]:
    if target not in {"NCEI-native-duration", "T-OBS", "T-CAL"}:
        raise ValueError("unknown validation source target")
    lane = tomllib.loads((root / CONTRACT).read_text())["lanes"][target]
    return {
        "target": target,
        "design_records": lane["primary_rows"],
        "design_events": lane["events"],
        "source_label": {
            "NCEI-native-duration": "NCEI reported-duration",
            "T-OBS": "NTWC T-OBS",
            "T-CAL": "NTWC T-CAL",
        }[target],
        "modeled_units": "minutes" if target == "T-CAL" else "log_reference_ratio",
        "response_definition": lane["response"],
    }


def csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {key: "" if value is None else str(value) for key, value in row.items()} for row in rows
    ]


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    write_rows(path, csv_rows(rows), columns=columns or ["record_id"])


def wilson_interval(successes: int, count: int) -> tuple[float, float]:
    """95% binomial reference uncertainty across independent simulation datasets."""
    if not 0 <= successes <= count or count < 1:
        raise ValueError("invalid binomial counts")
    z = NormalDist().inv_cdf(0.975)
    fraction = successes / count
    denominator = 1 + z * z / count
    center = (fraction + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(fraction * (1 - fraction) / count + z * z / (4 * count**2)) / denominator
    return center - radius, center + radius


def recovery_summary(
    estimates: list[dict[str, Any]], prior_widths: dict[str, float]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in estimates:
        groups[row["scenario"], row["parameter"]].append(row)
    results: list[dict[str, Any]] = []
    for (scenario, parameter), rows in sorted(groups.items()):
        error = np.array([r["mean"] - r["truth"] for r in rows])
        widths = np.array([r["q95"] - r["q05"] for r in rows])
        coverage = [r["covered90"] for r in rows if r["covered90"] is not None]
        low, high = wilson_interval(sum(coverage), len(coverage)) if coverage else (None, None)
        prior_width = prior_widths.get(parameter)
        standardized = [
            r["standardized_mean_error"] for r in rows if "standardized_mean_error" in r
        ]
        results.append(
            {
                "scenario": scenario,
                "parameter": parameter,
                "datasets": len(rows),
                "mean_truth": float(np.mean([r["truth"] for r in rows])),
                "mean_error": float(error.mean()),
                "mean_error_mcse": float(error.std(ddof=1) / math.sqrt(len(rows)))
                if len(rows) > 1
                else None,
                "root_mean_squared_error": float(np.sqrt(np.mean(error**2))),
                "mean_standardized_error": float(np.mean(standardized)) if standardized else None,
                "coverage_denominator": len(coverage),
                "coverage90": sum(coverage) / len(coverage) if coverage else None,
                "coverage90_wilson95_low": low,
                "coverage90_wilson95_high": high,
                "mean_interval_width90": float(widths.mean()),
                "prior_interval_width90": prior_width,
                "mean_interval_width_contraction": float(1 - widths.mean() / prior_width)
                if prior_width
                else None,
                "mean_q95_upper_bound": float(np.mean([r["q95"] for r in rows]))
                if any(r["zero_variance_boundary"] for r in rows)
                else None,
                "correct_model_scenario": scenario != "reported-time-addition-stress",
            }
        )
    return results


def calibration_summary(
    estimates: list[dict[str, Any]], *, planned_quantities: int = 6
) -> list[dict[str, Any]]:
    """Bonferroni/DKW reference bands; approximate when rank draws are MCMC-dependent."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in estimates:
        if not row["rank_ready"] or not 0 <= row["randomized_rank_pit"] <= 1:
            raise ValueError("unresolved SBC rank diagnostics")
        groups[row["parameter"]].append(row)
    if not 1 <= len(groups) <= planned_quantities:
        raise ValueError("invalid calibration quantity count")
    output: list[dict[str, Any]] = []
    for name, rows in sorted(groups.items()):
        u = np.sort([row["randomized_rank_pit"] for row in rows])
        count = len(u)
        distance = max(
            float(np.max(np.arange(1, count + 1) / count - u)),
            float(np.max(u - np.arange(count) / count)),
        )
        epsilon = math.sqrt(math.log(2 * planned_quantities / 0.05) / (2 * count))
        output.append(
            {
                "parameter": name,
                "datasets": count,
                "ks_distance": distance,
                "simultaneous_epsilon": epsilon,
                "outside_reference_band": distance > epsilon,
                "familywise_alpha_reference": 0.05,
                "planned_quantities": planned_quantities,
                "reference_scope": "approximate_MCMC_rank_iid_reference_not_physical_validation",
            }
        )
    return output


def posterior_quantities(path: Path) -> dict[str, np.ndarray]:
    """Read only the retained synthetic posterior, retaining chain/draw ordering."""
    with xr.open_dataset(path, group="posterior", engine="h5netcdf") as posterior:
        values = {
            p: np.asarray(posterior[p].values)
            for p in ["alpha", "beta", "tau_event", "sigma"]
            if p in posterior
        }
        if "event_effect" in posterior:
            values["event_effect_first"] = posterior["event_effect"].isel(event=0).values
        if "beta" in values:
            values["mean_response_at_5000km"] = values["alpha"] + values["beta"] * math.log(5)
    return values


def collect_batch(
    root: Path, batch: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Conserve planned datasets and audit retained worker identities before aggregation."""
    plan = json.loads((batch / "plan.json").read_text())
    summary = json.loads((batch / "run-summary.json").read_text())
    dispositions = read_rows(batch / "trial-dispositions.csv")
    accepted = [row for row in dispositions if row["outcome"] == "accepted"]
    if (
        len(dispositions) != summary["calls_used"]
        or len(accepted) != summary["completed_datasets"]
        or len({r["case_id"] for r in accepted}) != len(accepted)
        or {r["case_id"] for r in accepted} != {c["id"] for c in plan["cases"][: len(accepted)]}
        or sha256(batch / "plan.json") != summary["plan_sha256"]
    ):
        raise ValueError("batch conservation/plan identity mismatch")
    cases = {case["id"]: case for case in plan["cases"]}
    estimates, diagnostics = [], []
    pins = {
        str(p.relative_to(root)): sha256(p)
        for p in [batch / "plan.json", batch / "run-summary.json", batch / "trial-dispositions.csv"]
    }
    for disposition in dispositions:
        name = disposition["case_id"] + "-attempt-" + disposition["attempt"]
        attempt = batch / "jobs" / name
        result_path, spec_path = attempt / "result.json", batch / "jobs" / (name + "-spec.json")
        case = cases[disposition["case_id"]]
        pins[str(spec_path.relative_to(root))] = sha256(spec_path)
        if not result_path.exists():
            if disposition["outcome"] == "accepted":
                raise ValueError("accepted result is missing")
            diagnostics.append({**disposition, "has_result": False})
            continue
        pins[str(result_path.relative_to(root))] = sha256(result_path)
        result = json.loads(result_path.read_text())
        job = json.loads(spec_path.read_text())
        expected_job = dict(case["job"])
        if disposition["attempt"] == "2":
            expected_job.update(draws=min(4000, expected_job["draws"] * 2), tune=2000)
        if result["job"] != job or job != expected_job or result["synthetic_only"] is not True:
            raise ValueError("trial identity mismatch")
        posterior = checked_path(root, result["posterior"])
        if sha256(posterior) != result["posterior_sha256"]:
            raise ValueError("retained posterior identity mismatch")
        pins[str(posterior.relative_to(root))] = sha256(posterior)
        diagnostics.append(
            {
                **disposition,
                **result["diagnostics"],
                "elapsed_seconds": result["elapsed_seconds"],
                "has_result": True,
            }
        )
        if disposition["outcome"] != "accepted":
            continue
        if not result["diagnostics"]["screen_passed"]:
            raise ValueError("accepted result has failed diagnostics")
        quantities = posterior_quantities(posterior)
        for row in result["estimates"]:
            values = quantities[row["parameter"]]
            sd = float(np.std(values, ddof=1))
            if (
                sd <= 0
                or not math.isfinite(sd)
                or not np.isclose(values.mean(), row["mean"], rtol=1e-12, atol=1e-12)
            ):
                raise ValueError("retained posterior estimate/uncertainty mismatch")
            estimates.append(
                {
                    "case_id": case["id"],
                    "scenario": case["scenario"],
                    "replicate": case["replicate"],
                    "seed": job["seed"],
                    **row,
                    "posterior_sd": sd,
                    "standardized_mean_error": (row["mean"] - row["truth"]) / sd,
                }
            )
    complete = summary["status"] == "computations_complete" and len(accepted) == len(cases)
    return (
        {
            **summary,
            "complete": complete,
            "base_git_sha": plan["base_git_sha"],
            "target": plan.get("target", "NCEI-native-duration"),
        },
        estimates,
        diagnostics,
        pins,
    )


def write_validation_report(root: Path, batch: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("preserve previous reports; use a new output path")
    status, estimates, diagnostics, pins = collect_batch(root, batch)
    status.update(validation_design(root, status["target"]))
    pins[CONTRACT] = sha256(root / CONTRACT)
    output.mkdir(parents=True)
    write_table(output / "parameter-estimates-by-dataset.csv", estimates)
    write_table(output / "attempt-diagnostics.csv", diagnostics)
    if status["phase"] == "recovery":
        # Same base priors as the worker; other quantities have no analytic width here.
        from analysis.arrival.models import PRIORS, read_prior

        prior = read_prior(root, status["target"], "base")
        pins[PRIORS] = sha256(root / PRIORS)
        normal = NormalDist()
        widths = {
            p: (
                2 * normal.inv_cdf(0.95)
                if p in {"alpha", "beta"}
                else normal.inv_cdf(0.975) - normal.inv_cdf(0.525)
            )
            * prior[k]
            for p, k in [
                ("alpha", "alpha_sd"),
                ("beta", "beta_sd"),
                ("tau_event", "tau_sd"),
                ("sigma", "sigma_sd"),
            ]
        }
        table = recovery_summary(estimates, widths)
        write_table(output / "recovery-bias-coverage-and-contraction.csv", table)
    else:
        table = calibration_summary(estimates)
        write_table(output / "sbc-rank-calibration.csv", table)
    status["scientific_acceptance"] = (
        "pending_independent_review" if status["complete"] else "incomplete_not_accepted"
    )
    write_json(output / "status.json", status)
    pins["analysis/arrival/model_validation_report.py"] = sha256(
        root / "analysis/arrival/model_validation_report.py"
    )
    write_json(output / "inputs.json", pins)
    plot_validation(output, status, table, estimates)
    title = "Design recovery" if status["phase"] == "recovery" else "Simulation-based calibration"
    text = (
        f"# {title}\n\n"
        f"{status['completed_datasets']} of {status['planned_datasets']} predefined synthetic "
        "datasets completed "
        f"in {status['calls_used']} attempts. Status: **{status['scientific_acceptance']}**. "
        f"The {status['source_label']} exploration design has {status['design_records']} "
        f"approved records across {status['design_events']} events. Actual reported responses "
        "were not fitted in these simulations.\n\n"
        "All attempts remain in the diagnostics table and original local logs/chains. "
        "Posterior estimates use accepted attempts only; repairs reuse the same dataset. "
        "Unresolved datasets prevent stage acceptance. Computation under the assumed "
        "simulator does not validate physical onset, archive representativeness "
        "or predictive accuracy.\n\n"
    )
    if status["phase"] == "recovery":
        text += (
            "Coverage is the fraction of generating values inside central posterior 90% intervals; "
            "Wilson 95% intervals describe independent simulation-replicate uncertainty. "
            "These finite-replicate estimates are noisy. At tau=0 a positive equal-tailed interval "
            "cannot contain the boundary: use the reported posterior 95% upper bound. "
            "Any additive-time stress changes the response-generating mechanism and is "
            "reported separately from correct-model coverage. Width contraction is 1 minus "
            "mean posterior central-90% width / analytic prior central-90% width, "
            "not variance contraction.\n"
            "Standardized mean error z=(posterior mean−truth)/posterior SD; this is a "
            "descriptive recovery diagnostic, not a Normal-test statistic.\n"
        )
    else:
        text += (
            "Ranks use 100 spaced draws while retaining all original chains. Rank R-hat, ESS and "
            "lag screens do not make MCMC draws exactly independent. The ECDF reference band "
            "uses DKW with a Bonferroni correction across six planned quantities (familywise 0.05 "
            "under independent uniform ranks). Its interpretation is approximate for MCMC. "
            "A crossing calls for investigation; no crossing is not proof of correctness.\n"
        )
    if status["target"] == "T-CAL":
        text += (
            "\nParameter meanings: alpha is population signed estimate-minus-observation minutes "
            "at 1,000 km; beta changes that mean per unit ln(distance/1000). Tau_event "
            "and sigma are between-event and record SDs in minutes. Event_effect_first "
            "is the first sorted event's latent minute effect. Mean_response_at_5000km "
            "is alpha+beta*ln(5), a signed-minute population mean. This retrospective "
            "archive discrepancy is not operational warning performance.\n"
        )
    else:
        text += (
            "\nParameter meanings: alpha is the population log median/reference ratio at 1,000 km; "
            "beta changes that log ratio per unit ln(distance/1000). Tau_event and sigma are "
            "between-event and record SDs on the log-ratio scale. Event_effect_first is the "
            "first sorted event's latent log-ratio effect. Mean_response_at_5000km is "
            "alpha+beta*ln(5), the population mean log ratio, not an arithmetic mean duration.\n"
        )
    if status["phase"] == "recovery":
        core = [r for r in table if r["parameter"] in {"alpha", "beta", "tau_event", "sigma"}]
        eligible = [
            r["coverage90"]
            for r in core
            if r["correct_model_scenario"] and r["coverage90"] is not None
        ]
        text += (
            f"\nAcross the core parameters in correctly specified scenarios, coverage ranges "
            f"from {min(eligible):.1%} to {max(eligible):.1%}. This range spans multiple "
            "noisy comparisons; it is not an automatic identification certificate.\n\n"
            "| Setting | Parameter | Mean error | Coverage (90% interval) | "
            "95% reference uncertainty |\n"
            "| --- | --- | ---: | ---: | --- |\n"
        )
        for r in core:
            coverage = (
                "Boundary: upper bound" if r["coverage90"] is None else f"{r['coverage90']:.1%}"
            )
            interval = (
                "—"
                if r["coverage90"] is None
                else (f"{r['coverage90_wilson95_low']:.1%}–{r['coverage90_wilson95_high']:.1%}")
            )
            text += (
                f"| {r['scenario']} | {r['parameter']} | {r['mean_error']:.4f} | "
                f"{coverage} | {interval} |\n"
            )
    (output / "findings.md").write_text(text)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def register_validation_report(root: Path, batch: Path, output: Path) -> None:
    """Mirror meaningful simulation scenarios in the existing project-local experiment."""
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    import mlflow

    receipt = output / "mlflow-receipt.json"
    if receipt.exists():
        raise ValueError("registration receipt already exists; verify before retry")
    status = json.loads((output / "status.json").read_text())
    estimates = read_rows(output / "parameter-estimates-by-dataset.csv")
    diagnostics = read_rows(output / "attempt-diagnostics.csv")
    fingerprint = sha256(output / "output-checksums.json")
    mlflow.set_tracking_uri((root / ".mlflow/mlruns").as_uri())
    mlflow.set_experiment("arrival-model")
    runs = {}
    for scenario in sorted({row["scenario"] for row in estimates}):
        key = fingerprint + ":" + scenario
        existing = mlflow.search_runs(
            filter_string=f"tags.validation_scenario_fingerprint = '{key}'", output_format="list"
        )
        if existing:
            if len(existing) != 1 or existing[0].info.status != "FINISHED":
                raise ValueError("ambiguous/unfinished registration; inspect before retry")
            runs[scenario] = existing[0].info.run_id
            continue
        cases = {row["case_id"] for row in estimates if row["scenario"] == scenario}
        selected = [row for row in diagnostics if row["case_id"] in cases]
        with mlflow.start_run(run_name="MS-2-" + status["phase"] + "-" + scenario) as run:
            mlflow.log_params(
                {
                    "phase": status["phase"],
                    "scenario": scenario,
                    "datasets_completed": len(cases),
                    "synthetic_only": True,
                    "target": status.get("target", "NCEI-native-duration"),
                    "design_records": status.get("design_records", 1064),
                    "design_events": status.get("design_events", 33),
                }
            )
            mlflow.set_tags(
                {
                    "git_sha": status["base_git_sha"],
                    "decision": status["scientific_acceptance"],
                    "validation_scenario_fingerprint": key,
                    "data_contract": "exploration-contract-v1",
                }
            )
            for name, function in [
                ("max_rhat", max),
                ("min_ess_bulk", min),
                ("min_ess_tail", min),
                ("min_bfmi", min),
            ]:
                values = [float(row[name]) for row in selected if row.get(name)]
                if values:
                    mlflow.log_metric(name, function(values))
            mlflow.log_metrics(
                {
                    "attempts": len(selected),
                    "diagnostic_failures": sum(r["outcome"] != "accepted" for r in selected),
                }
            )
            mlflow.log_artifacts(str(output))
            mlflow.log_artifact(str(batch / "plan.json"))
            runs[scenario] = run.info.run_id
    write_json(receipt, {"scenario_runs": runs, "bundle_fingerprint": fingerprint})


def plot_validation(
    output: Path,
    status: dict[str, Any],
    table: list[dict[str, Any]],
    estimates: list[dict[str, Any]],
) -> None:
    """Takeaway: uncertainty is finite-simulation evidence | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.size": 11, "axes.titlesize": 12, "axes.labelsize": 11}):
        source = status.get("source_label", "NCEI reported-duration")
        if status["phase"] == "recovery":
            settings = {r["scenario"] for r in table if r["correct_model_scenario"]}
            fig, axes = plt.subplots(
                4, 1, figsize=(7, 13 if len(settings) > 4 else 9), sharex=True, layout="constrained"
            )
            for ax, parameter in zip(
                axes.flat, ["alpha", "beta", "tau_event", "sigma"], strict=True
            ):
                rows = [
                    r for r in table if r["parameter"] == parameter and r["correct_model_scenario"]
                ]
                for i, row in enumerate(rows):
                    if row["coverage90"] is None:
                        ax.text(0.02, i, "Boundary: use upper bound", va="center", fontsize=10.5)
                        continue
                    value = row["coverage90"]
                    ax.errorbar(
                        value,
                        i,
                        xerr=[
                            [value - row["coverage90_wilson95_low"]],
                            [row["coverage90_wilson95_high"] - value],
                        ],
                        fmt="o",
                        color="#146782",
                        capsize=3,
                    )
                ax.axvline(0.9, color="#666666", ls="--", lw=1)
                ax.set_yticks(
                    range(len(rows)), [r["scenario"].replace("-", " ") for r in rows], fontsize=10.5
                )
                ax.set_xlim(0, 1.02)
                ax.set_xlabel("Coverage of central 90% interval")
                ax.set_title(parameter, loc="left")
                ax.spines[["right", "top"]].set_visible(False)
            counts = sorted({r["datasets"] for r in table if r["correct_model_scenario"]})
            repeats = str(counts[0]) if len(counts) == 1 else f"{counts[0]}–{counts[-1]}"
            fig.suptitle(f"Coverage estimates use {repeats} repeats per setting", fontsize=14)
            stress_note = (
                "\nAdditive-time stress shown separately."
                if any(not r["correct_model_scenario"] for r in table)
                else ""
            )
            fig.supxlabel(
                "Dots: 90% interval coverage; bars: Wilson 95% uncertainty.\n"
                "Dashed: nominal 90%. Tau=0 uses an upper bound instead.\n"
                f"Source: simulations on the {source} exploration design." + stress_note,
                fontsize=10.5,
            )
            name = "parameter-recovery-coverage"
        else:
            fig, axes = plt.subplots(3, 2, figsize=(7, 9), layout="constrained")
            for ax, row in zip(axes.flat, table, strict=True):
                u = np.sort(
                    [
                        r["randomized_rank_pit"]
                        for r in estimates
                        if r["parameter"] == row["parameter"]
                    ]
                )
                grid = np.linspace(0, 1, 201)
                eps = row["simultaneous_epsilon"]
                ax.fill_between(
                    grid, np.maximum(0, grid - eps), np.minimum(1, grid + eps), color="#dddddd"
                )
                ax.plot([0, 1], [0, 1], color="#777777", lw=1)
                ax.step(
                    np.r_[0, u, 1],
                    np.r_[0, np.arange(1, len(u) + 1) / len(u), 1],
                    where="post",
                    color="#146782",
                    lw=1.5,
                )
                ax.set(
                    xlim=(0, 1),
                    ylim=(0, 1),
                    xlabel="Randomized rank (0–1)",
                    ylabel="Cumulative fraction",
                )
                ax.set_title(row["parameter"].replace("_", " "), loc="left", fontsize=11)
                ax.spines[["right", "top"]].set_visible(False)
            fig.suptitle(
                f"Rank calibration across {status['completed_datasets']} synthetic datasets",
                fontsize=14,
            )
            fig.supxlabel(
                "Gray: simultaneous 95% iid reference for six quantities; MCMC approximation.\n"
                f"Source: base-prior simulations on the {source} design.",
                fontsize=10.5,
            )
            name = "sbc-rank-ecdfs"
        fig.savefig(output / (name + ".png"), dpi=180)
        fig.savefig(output / (name + ".svg"))
        plt.close(fig)
