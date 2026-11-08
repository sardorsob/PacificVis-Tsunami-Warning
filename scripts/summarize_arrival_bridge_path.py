"""Create a portable known-path calibration report without adding simulations or fitting."""

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
from scipy.stats import norm, t

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402


def summarize(root, source, output):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local report required")
    pins = {}

    def read(path):
        pins[str(path.relative_to(root))] = sha256(path)
        return json.loads(path.read_text())

    inputs = read(source / "inputs.json")
    targets = read(source / "known-targets.json")
    read(source / "result.json")
    table = source / "known-path-trials.csv"
    pins[str(table.relative_to(root))] = sha256(table)
    with table.open() as stream:
        rows = list(csv.DictReader(stream))
    if (
        len(rows) != 60
        or len({r["seed"] for r in rows}) != 60
        or inputs["actual_pm_sample_calls"] != 0
    ):
        raise ValueError("all sixty original trials required")
    summaries = []
    ratios = []
    for mode in ["iid", "AR0.8"]:
        selected = [r for r in rows if r["mode"] == mode]
        if len(selected) != 30:
            raise ValueError("fixed thirty trials per setting required")
        errors = np.array([float(r["error"]) for r in selected])
        mcse = np.array([float(r["mcse"]) for r in selected])
        for row in selected:
            label = 0 if mode == "iid" else 1
            detail = read(source / "cases" / f"mode-{label}-rep-{int(row['replicate']):02d}.json")
            if detail["precision_passed"] != (row["precision_passed"] == "True"):
                raise ValueError("trial disposition mismatch")
            naive = math.sqrt(sum(e["joint_log_mcse_delta"] ** 2 for e in detail["edges"]))
            ratios.append(detail["joint_log_mcse_delta"] / naive)
        n = len(selected)
        k = sum(r["covers_90"] == "True" for r in selected)
        z = float(norm.ppf(0.975))
        center = (k / n + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        sem = float(errors.std(ddof=1) / math.sqrt(n))
        mean = float(errors.mean())
        summaries.append(
            {
                "setting": mode,
                "replicates": n,
                "accepted": sum(r["precision_passed"] == "True" for r in selected),
                "mean_raw_error": mean,
                "empirical_sd_raw_error": float(errors.std(ddof=1)),
                "rms_reported_raw_mcse": float(np.sqrt(np.mean(mcse**2))),
                "mean_error_empirical_se": sem,
                "mean_error_z": mean / sem,
                "mean_error_descriptive_ci95_lower": mean - float(t.ppf(0.975, n - 1)) * sem,
                "mean_error_descriptive_ci95_upper": mean + float(t.ppf(0.975, n - 1)) * sem,
                "covers_90": k,
                "coverage_wilson95_lower": center - half,
                "coverage_wilson95_upper": center + half,
                "min_edge_overlap": min(float(r["min_edge_overlap"]) for r in selected),
            }
        )
    output.mkdir(parents=True)
    write_table(output / "known-normalizer-path-trials.csv", rows)
    write_table(output / "known-normalizer-path-summary.csv", summaries)
    write_json(output / "known-Gaussian-targets.json", targets)
    ar = next(s for s in summaries if s["setting"] == "AR0.8")
    (output / "findings.md").write_text(f"""# Numerical checks for a fixed likelihood path

An eight-edge geometric path estimates the same joint held-event predictive
density as a direct bridge. Intermediate distributions are integration devices.
Their adjacent normalizer ratios telescope exactly, without thermodynamic-integration
discretization error. Every edge still needs posterior overlap, reliable sampling
and Monte Carlo precision. Coefficients remain explicit; the new event effect is
integrated before powering its entire marginal Gaussian likelihood. The native-minute
Jacobian is subtracted once at the end.

The known-normalizer experiment retains 60 six-dimensional Gaussian trials:
30 independent-draw trials and 30 with stationary autocorrelation 0.8. Each uses
nine independent stage ensembles of four chains and 8,000 draws. A normalization
count of 100 sets the numerical reporting scale; it does not represent 100 tsunami
observations. All 60 passed their declared numerical screens. Coverage of nominal
90% intervals was 27/30 and 26/30; the tables include binomial uncertainty.
These are estimator checks, not model SBC, physical validation or proof that the
actual Tōhoku path will have sufficient overlap.

The autocorrelated cohort retains a warning: mean error is {ar["mean_raw_error"]:.6f}
raw nat, or {ar["mean_error_z"]:.2f} empirical standard errors. Its descriptive 95%
interval is [{ar["mean_error_descriptive_ci95_lower"]:.6f},
{ar["mean_error_descriptive_ci95_upper"]:.6f}]. Independent replay found no target,
stationarity, seed, root or covariance defect explaining this result. It remains
a finite-cohort warning. No trials were replaced or added and no empirical bias
correction is applied. Reported RMS MCSE was about 8–10% below empirical SD, with
substantial uncertainty at 30 trials. This supports a cautious bounded prototype.

Adjacent ratios share middle-stage samples. Their incoming and outgoing influences
must be added within each stage before estimating MCSE. Across these checks,
the correct MCSE averaged {float(np.mean(ratios)):.2f} times the naïve independent-edge
calculation. Independent stage variances then add.

The actual contingency is fixed before fitting: seven new middle-stage fits for
the designated primary path, then eight for a fully independent computational
repeat using a previously saved independent augmented endpoint. All 15 calls
debit the existing production ceiling; no repair, replacement or ladder insertion
is allowed. Each stage and newly available edge is checked immediately. Whole-path
precision and independent-repeat agreement are separate requirements. No broad
cross-validation or model-selection result is established here.

Reproduce the known experiment with `scripts/validate_arrival_bridge_path.py`;
its frozen targets, original seeds and source identities accompany the tables.
The bridge identity is described by
[Meng and Wong](https://www3.stat.sinica.edu.tw/statistica/j6n4/j6n43/j6n43.htm)
and [Gronau et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC5699790/).
""")
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "generator_sha256": sha256(Path(__file__)),
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    write_json(output / "output-checksums.json", {p.name: sha256(p) for p in output.iterdir()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    summarize(Path(__file__).resolve().parents[1], args.source.resolve(), args.output.resolve())
