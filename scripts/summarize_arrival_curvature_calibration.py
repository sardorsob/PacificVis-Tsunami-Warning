"""Summarize closed synthetic computations; never regenerate responses or sample."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_curve_checks import sbc_rank_ecdf_screen  # noqa: E402
from analysis.arrival.model_curvature_validation import CONSUMED  # noqa: E402
from analysis.arrival.model_validation_report import wilson_interval, write_table  # noqa: E402
from scripts.run_arrival_curvature_calibration import (  # noqa: E402
    OUTPUT,
    RECOVERY_GATE,
    STORE,
    case_artifacts,
    make_cases,
)
from scripts.run_arrival_curvature_pilot import make_cases as pilot_cases  # noqa: E402

SELF = "scripts/summarize_arrival_curvature_calibration.py"


def summarize_groups(estimates):
    groups = defaultdict(list)
    for row in estimates:
        groups[row["scenario"], row["parameter"]].append(row)
    summary = []
    for (scenario, parameter), rows in sorted(groups.items()):
        count = len(rows)
        successes = sum(r["covered90"] for r in rows)
        low, high = wilson_interval(successes, count)
        errors = np.array([r["median"] - r["truth"] for r in rows])
        summary.append(
            {
                "scenario": scenario,
                "parameter": parameter,
                "datasets": count,
                "covered90_count": successes,
                "covered90_proportion": successes / count,
                "wilson95_low": low,
                "wilson95_high": high,
                "mean_median_error": float(errors.mean()),
                "mean_median_error_dataset_mcse": float(errors.std(ddof=1) / np.sqrt(count)),
                "median_estimate_rmse": float(np.sqrt(np.mean(errors**2))),
                "mean_posterior_prior_sd_ratio": float(
                    np.mean([r["posterior_prior_sd_ratio"] for r in rows])
                ),
                "mean_posterior_standardized_mean_error": float(
                    np.mean([r["recovery_z"] for r in rows])
                ),
            }
        )
    return summary


def report(root, phase, output):
    if phase not in {"recovery", "sbc"} or output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local report and declared phase required")
    batch, store = root / OUTPUT, root / STORE
    plan = json.loads((batch / "plan.json").read_text())
    if plan["cases"] != make_cases():
        raise ValueError("frozen150-case design changed")
    pins = {**plan["files"], OUTPUT + "/plan.json": sha256(batch / "plan.json")}
    for name, digest in pins.items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("frozen input changed")
    additions = {
        p: sha256(root / p)
        for p in [
            SELF,
            "analysis/arrival/model_validation_report.py",
            "analysis/arrival/model_curvature_curve_checks.py",
        ]
    }
    if any(p in pins and pins[p] != digest for p, digest in additions.items()):
        raise ValueError("report source conflicts with frozen input")
    pins.update(additions)
    cases = plan["cases"][:50] if phase == "recovery" else plan["cases"][50:]
    expected = 50 if phase == "recovery" else 100
    estimates, diagnostics, bands = [], [], []
    fingerprints = set(plan["parent_dataset_sha256"])
    names = None
    if phase == "sbc":
        gate_path = root / RECOVERY_GATE
        gate = json.loads(gate_path.read_text())
        if (
            gate.get("status") != "accepted_fifty_recovery_for_sbc"
            or gate.get("independent_checker") is not True
            or gate.get("recovery_cases") != 50
            or gate.get("files", {}).get(OUTPUT + "/plan.json") != sha256(batch / "plan.json")
        ):
            raise ValueError("independently accepted50-recovery gate required")
        for name, digest in gate["files"].items():
            if sha256(checked_path(root, name)) != digest:
                raise ValueError("accepted recovery proof changed")
        for case in plan["cases"][:50]:
            files, manifest = case_artifacts(root, batch, store, case, plan["files"], CONSUMED)
            required = {**files, str(manifest.relative_to(root)): sha256(manifest)}
            if any(gate["files"].get(p) != h for p, h in required.items()):
                raise ValueError("incomplete recovery gate closure")
            checks = json.loads((manifest.parent / "calibration-checks.json").read_text())
            fingerprints.add(checks["synthetic_observed_data_sha256"])
        pins.update(gate["files"])
        pins[RECOVERY_GATE] = sha256(gate_path)
    for j, case in enumerate(cases):
        attempt = batch / "jobs" / case["id"]
        files, manifest = case_artifacts(root, batch, store, case, plan["files"], CONSUMED)
        original = json.loads(manifest.read_text())
        if original != {"case_id": case["id"], "files": files}:
            raise ValueError("closed attempt proof changed")
        pins.update(files)
        pins[str(manifest.relative_to(root))] = sha256(manifest)
        result = json.loads((attempt / "result.json").read_text())
        checks = json.loads((attempt / "calibration-checks.json").read_text())
        fingerprint = checks["synthetic_observed_data_sha256"]
        if fingerprint in fingerprints:
            raise ValueError("synthetic datasets must be distinct")
        fingerprints.add(fingerprint)
        scenario = pilot_cases()[j // 10]["id"] if phase == "recovery" else "prior-generated"
        rows = checks["estimates"] + checks["functional"]["estimates"]
        current_names = tuple(r["parameter"] for r in rows)
        if len(set(current_names)) != 21 or (names is not None and names != current_names):
            raise ValueError("exactly the same21 ordered quantities required per dataset")
        names = current_names
        estimates += [{"case_id": case["id"], "scenario": scenario, **r} for r in rows]
        d = result["diagnostics"]
        functional = checks["functional"]["maximum_deviation_diagnostics"]
        diagnostics.append(
            {
                "case_id": case["id"],
                "scenario": scenario,
                **{
                    k: d[k]
                    for k in [
                        "max_rhat",
                        "min_ess_bulk",
                        "min_ess_tail",
                        "min_bfmi",
                        "divergences",
                        "maxdepth_reached",
                    ]
                },
                **{"maximum_function_" + k: v for k, v in functional.items()},
                "rank_ready": checks["rank_ready"],
            }
        )
        bands.append(
            {"case_id": case["id"], "scenario": scenario, **checks["functional"]["grid_band90"]}
        )
    if len(diagnostics) != expected or not all(r["rank_ready"] for r in diagnostics):
        raise ValueError("complete phase with retained rank diagnostics required")
    if names is None:
        raise ValueError("no retained quantities")
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "phase": phase,
            "datasets": expected,
            "simulation_repeated": False,
            "posterior_refitted": False,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_table(output / "estimates-by-dataset.csv", estimates)
    write_table(output / "sampling-and-functional-diagnostics.csv", diagnostics)
    parameter_summary = summarize_groups(estimates)
    write_table(output / "pointwise-coverage-and-recovery.csv", parameter_summary)
    write_table(output / "grid-band-by-dataset.csv", bands)
    band_summary = []
    for scenario in sorted({r["scenario"] for r in bands}):
        group = [r for r in bands if r["scenario"] == scenario]
        count, successes = len(group), sum(r["covered"] for r in group)
        lo, hi = wilson_interval(successes, count)
        band_summary.append(
            {
                "scenario": scenario,
                "datasets": count,
                "covered_count": successes,
                "covered_proportion": successes / count,
                "wilson95_low": lo,
                "wilson95_high": hi,
                "borderline_cases": sum(r["borderline"] for r in group),
            }
        )
    write_table(output / "grid-band-coverage.csv", band_summary)
    rank_checks = []
    if phase == "sbc":
        for name in names:
            rows = [r for r in estimates if r["parameter"] == name]
            rank_checks.append(
                {"parameter": name, **sbc_rank_ecdf_screen([r["rank"] for r in rows])}
            )
        write_table(output / "final-discrete-rank-ecdf-screen.csv", rank_checks)
    metrics = {
        "datasets": expected,
        "quantities": 21,
        "estimates": len(estimates),
        "sampler_calls_in_phase": expected,
        "max_rhat": max(r["max_rhat"] for r in diagnostics),
        "min_ess_bulk": min(r["min_ess_bulk"] for r in diagnostics),
        "min_ess_tail": min(r["min_ess_tail"] for r in diagnostics),
        "divergences": sum(r["divergences"] for r in diagnostics),
        "depth_hits": sum(r["maxdepth_reached"] for r in diagnostics),
        "grid_band_borderline_cases": sum(r["borderline"] for r in bands),
        "final_rank_ecdf_screens_exceeded": sum(r["screen_exceeded"] for r in rank_checks)
        if phase == "sbc"
        else None,
    }
    write_json(output / "metrics.json", metrics)
    lines = [
        f"# Mean-curvature {phase} validation",
        "",
        f"The phase retains {expected} distinct synthetic datasets, with four chains of "
        "2,000 posterior draws after 1,000 tuning draws. All retained sampling and "
        "21-quantity rank diagnostics passed their prespecified screens. "
        "The 1,064-record, 33-event design supplies distances and membership; generated "
        "responses supply the likelihood.",
        "",
        "Recovery estimates are in `pointwise-coverage-and-recovery.csv`. Its error measure "
        "is the posterior median minus the generating value. The separate standardized "
        "mean-error column divides posterior-mean error by posterior SD; it is not a "
        "standard-normal test. Wilson intervals describe finite-dataset binomial uncertainty. "
        "Coverage is summarized separately for each quantity and scenario.",
        "",
        "The median-curve band is simultaneous on the nine fixed distances, at zero event "
        "effect. It excludes event and observation noise and makes no claim between grid "
        "points. Borderline flags use uncertainty in the 90th-percentile cutoff only; they "
        "do not quantify all uncertainty in band endpoints or coverage classification.",
        "",
    ]
    if phase == "recovery":
        lines += [
            "Each of the five generating scenarios has ten fresh datasets. Coverage "
            "estimates are correspondingly imprecise. No coverage quota or rank-uniformity "
            "test is applied to these fixed-truth recovery datasets.",
            "",
        ]
    else:
        lines += [
            "Each truth is drawn independently from the frozen base prior. Final rank "
            "checks use the discrete uniform reference on integers 0 through 100 and a "
            "21-quantity DKW union bound at family alpha 0.05. Correlations among quantities "
            "are allowed by the union bound. The 100 spaced posterior states per rank "
            "approximate independent draws; they are not 100 effective samples. The "
            "independent replication count is 100 datasets, not 2,100 parameter estimates.",
            "",
            f"Final rank screens exceeded: {metrics['final_rank_ecdf_screens_exceeded']} of21. "
            "A screen diagnoses computational calibration under the assumed model; passing "
            "does not establish physical correctness or predictive superiority.",
            "",
        ]
    lines += [
        "| Scenario | Parameter | 90% interval containment | 95% Wilson interval | "
        "Mean median error |",
        "| --- | --- | ---: | ---: | ---: |",
        *[
            f"| {r['scenario']} | {r['parameter']} | {r['covered90_count']}/{r['datasets']} | "
            f"{r['wilson95_low']:.1%}–{r['wilson95_high']:.1%} | {r['mean_median_error']:.4f} |"
            for r in parameter_summary
            if r["parameter"] in {"gamma", "tau_event"}
        ],
        "",
        "Gamma is the additional curvature coefficient for the log median; tau_event is the "
        "between-event log-scale SD. Fixed-truth posterior interval containment need not equal "
        "nominal "
        "frequentist coverage at each chosen truth. These finite recovery results and the "
        "curve-band results should be read together; marginal coefficient recovery and "
        "curve recovery answer different questions.",
        "",
    ]
    lines += [
        "| Generating scenario | Median-curve band coverage | 95% Wilson interval | Borderline |",
        "| --- | ---: | ---: | ---: |",
        *[
            f"| {r['scenario']} | {r['covered_count']}/{r['datasets']} | "
            f"{r['wilson95_low']:.1%}–{r['wilson95_high']:.1%} | {r['borderline_cases']} |"
            for r in band_summary
        ],
        "",
        "Reproduce this report from retained files with "
        f"`uv run python scripts/summarize_arrival_curvature_calibration.py --phase {phase} "
        f"--output {output.relative_to(root)}` using a new output directory. "
        "No sampler is called. Confirmation outcomes were not parsed; reserved outcomes "
        "remain sealed. Historical candidate fitting requires independent acceptance of "
        "these computational checks.",
        "",
    ]
    (output / "findings.md").write_text("\n".join(lines))
    write_json(
        output / "output-checksums.json",
        {str(p.relative_to(output)): sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["recovery", "sbc"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report(root, args.phase, (root / args.output).resolve())
