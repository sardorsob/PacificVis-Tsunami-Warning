"""Summarize the finite bridge calibration without rebuilding or sampling its inputs."""

# pyright: basic
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402


def summarize(root: Path, source: Path, references: Path, output: Path):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local report required")
    pins = {}

    def read(path):
        pins[str(path.relative_to(root))] = sha256(path)
        return json.loads(path.read_text())

    known = source / "known-normalizers"
    read(known / "inputs.json")
    meta = read(known / "result.json")
    trials = known / "known-normalizer-calibration.csv"
    pins[str(trials.relative_to(root))] = sha256(trials)
    with trials.open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 170 or meta["replicates"] != 170 or len({r["seed"] for r in rows}) != 170:
        raise ValueError("all 170 original distinct trials required")
    summary = []
    for case in sorted({r["case"] for r in rows}):
        selected = [r for r in rows if r["case"] == case]
        for r in selected:
            detail = read(known / "cases" / f"{case}-{int(r['replicate']):02d}.json")
            if detail["precision_passed"] != (r["numerical_screen_passed"] == "True"):
                raise ValueError("trial disposition mismatch")
        n = len(selected)
        k = sum(r["covers_90"] == "True" for r in selected)
        z = norm.ppf(0.975)
        center = (k / n + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        err = np.array([float(r["error"]) for r in selected])
        errors = np.array([float(r["mcse"]) for r in selected])
        summary.append(
            {
                "case": case,
                "replicates": n,
                "accepted": sum(r["numerical_screen_passed"] == "True" for r in selected),
                "mean_error": float(err.mean()),
                "empirical_sd": float(err.std(ddof=1)),
                "rms_reported_mcse": float(np.sqrt(np.mean(errors**2))),
                "covers_90": k,
                "coverage_wilson95_lower": center - half,
                "coverage_wilson95_upper": center + half,
                "min_overlap": min(float(r["overlap"]) for r in selected),
            }
        )
    comparisons = []
    for name, ref in [
        ("blocked-existing", "event-fold-06-v2"),
        ("ordinary-existing", "event-fold-01-v1"),
        ("blocked-independent-repeat", "event-fold-06-v2"),
    ]:
        score = read(source / name / "result.json")
        fit_inputs = read(source / name / "source-fits.json")
        read(source / name / "inputs.json")
        exact = read(references / ref / "result.json")
        read(references / ref / "inputs.json")
        delta = score["joint_log_predictive"] - exact["joint_native_score"]
        comparisons.append(
            {
                "prototype": name,
                "sequence": fit_inputs["sequence"],
                "records": score["records"],
                "normalized_event_score": score["normalized_event_score"],
                "normalized_mcse": score["normalized_mcse"],
                "overlap": score["overlap"],
                "difference_from_quadrature_raw_nats": delta,
                "difference_in_reported_mcse_units": delta / score["joint_log_mcse_delta"],
                "precision_passed": score["precision_passed"],
                "reference_proposal_refinement_raw_nats": exact["proposal_refinement_difference"],
            }
        )
    output.mkdir(parents=True)
    write_table(output / "known-normalizer-trials.csv", rows)
    write_table(output / "known-normalizer-summary.csv", summary)
    write_table(output / "real-event-integration-checks.csv", comparisons)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "generator": {str(Path(__file__).resolve().relative_to(root)): sha256(Path(__file__))},
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    adequate = [r for r in summary if r["case"] != "poor-overlap"]
    accepted = sum(r["accepted"] for r in adequate)
    poor = next(r for r in summary if r["case"] == "poor-overlap")
    max_difference = max(abs(r["difference_in_reported_mcse_units"]) for r in comparisons)
    overlap_min = min(r["overlap"] for r in comparisons)
    overlap_max = max(r["overlap"] for r in comparisons)
    initial = read(source / "blocked-existing/result.json")
    repeat = read(source / "blocked-independent-repeat/result.json")
    repeat_difference = abs(initial["joint_log_predictive"] - repeat["joint_log_predictive"])
    repeat_difference /= math.hypot(initial["joint_log_mcse_delta"], repeat["joint_log_mcse_delta"])
    max_refinement = max(r["reference_proposal_refinement_raw_nats"] for r in comparisons)
    (output / "findings.md").write_text(f"""# Checking the joint predictive-density estimator

A two-posterior bridge estimates the same new-event joint predictive density as
the original integration. It uses independent training and training-plus-one-held-event
posterior ensembles. The latter is an integration device; it supplies no training-only
predictions or parameter conclusions. Whole related sequences still leave training
together. Other held-out events never enter the augmented fit.

Normal coefficients and event effects are integrated at fixed variance parameters.
With f₀ the training hyperparameter density and f₁ its product with the joint
conditional held-event density, the bridge estimates Z₁/Z₀. For durations, subtract
Σ log(y_minutes) to return to native-minute density. This ratio scores a held event
within one model; no Bayes-factor interpretation is used for predictive differences
between models. See [Meng and Wong](https://www3.stat.sinica.edu.tw/statistica/)
and [Gronau et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC5699790/).

The finite experiment retains all {len(rows)} known-normalizer trials.
{accepted} of 160 adequate-overlap trials passed; {poor["accepted"]} of 10 deliberately
separated cases passed. Cases include unequal ensemble sizes, changed covariance,
four dimensions and stationary autocorrelation 0.8. The 90% interval coverage counts
range from {min(r["covers_90"] for r in adequate)} to {max(r["covers_90"] for r in adequate)}
of 40 for the adequate-overlap settings; the table gives binomial uncertainty.
These are computation checks, not model SBC or physical validation, and cannot
certify arbitrary posterior geometry.

Two real exploration folds and an independent two-fit repeat agree with separately
checked two-dimensional quadrature within {max_difference:.3f} reported Monte Carlo
standard errors. Overlap ranges from {overlap_min:.3f} to {overlap_max:.3f}.
The two independent estimates of the difficult event differ by {repeat_difference:.3f}
combined standard errors. Reference quadrature refinement differences are at most
{max_refinement:.3g} raw nats; finite refinement and routine error estimates do not
prove exhaustive mode coverage.

Numerical screens keep event-score MCSE ≤0.005 and aggregate MCSE ≤0.002 nat per
record. Additional analyst screens require overlap ≥0.1, |empirical fixed-point
derivative| ≤0.25, both bridge weight concentrations ≥100, functional R-hat ≤1.01
and bulk/tail ESS ≥400. Weight concentration is distinct from MCMC ESS. A bounded
monotone root checks algebraic accuracy separately from sampling precision.
Shared-training influences are summed before computing MCSE; independent augmented
ensembles contribute separate variances. Overlap and clean diagnostics do not prove
global exploration. MCSE is asymptotic and gives no deterministic tail certificate.

Original failed importance estimates remain unresolved and retained. This validation
supports review of the integration method only. Four-variance production scoring,
completed sequence comparisons, model selection and sensitivity remain separate gates.
Previously inspected confirmation outcomes and 18 reserved outcomes were not read
in these checks.
""")
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(
        Path(__file__).resolve().parents[1],
        args.source.resolve(),
        args.references.resolve(),
        args.output.resolve(),
    )
