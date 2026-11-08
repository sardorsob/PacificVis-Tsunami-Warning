"""Compare a frozen follow-up with its selected initial scenario without hiding selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analysis.arrival.evidence import read_rows, sha256, write_json
from analysis.arrival.model_validation_report import recovery_summary, write_table

SCENARIO = "combined-weak-event-large-spread"


def compare_cohorts(
    initial: list[dict[str, Any]], followup: list[dict[str, Any]], widths: dict[str, float]
) -> list[dict[str, Any]]:
    seeds = [{int(r["seed"]) for r in rows} for rows in [initial, followup]]
    if seeds[0] & seeds[1]:
        raise ValueError("follow-up reuses initial simulation seeds")
    for name in {r["parameter"] for r in initial} - {"event_effect_first"}:
        truths = [
            {r["truth"] for r in rows if r["parameter"] == name} for rows in [initial, followup]
        ]
        if len(truths[0]) != 1 or truths[0] != truths[1]:
            raise ValueError("follow-up generating truth differs from the initial setting")
    results: list[dict[str, Any]] = []
    for label, rows in [
        ("initial", initial),
        ("independent-followup", followup),
        ("pooled-descriptive-adaptive-followup", initial + followup),
    ]:
        if len({(r["case_id"], r["parameter"], r["seed"]) for r in rows}) != len(rows):
            raise ValueError("duplicate cohort parameter identities")
        results.extend({"cohort": label, **r} for r in recovery_summary(rows, widths))
    return results


def write_followup_comparison(root: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("new comparison path required")
    base = root / "artifacts/models/arrival-timing"
    folders = ["design-recovery-summary-v1", "design-recovery-combined-followup-summary-v1"]
    cohorts: list[list[dict[str, Any]]] = []
    pins: dict[str, str] = {}
    for folder in folders:
        path = base / folder
        for name, digest in json.loads((path / "output-checksums.json").read_text()).items():
            if sha256(path / name) != digest:
                raise ValueError("source summary changed")
            pins[str((path / name).relative_to(root))] = digest
        rows: list[dict[str, Any]] = []
        for r in read_rows(path / "parameter-estimates-by-dataset.csv"):
            if r["scenario"] != SCENARIO:
                continue
            rows.append(
                {
                    **r,
                    **{
                        k: float(r[k])
                        for k in ["mean", "truth", "q05", "q95", "standardized_mean_error"]
                    },
                    "covered90": None if not r["covered90"] else r["covered90"] == "True",
                    "zero_variance_boundary": r["zero_variance_boundary"] == "True",
                }
            )
        if len(rows) != 180 or len({r["case_id"] for r in rows}) != 30:
            raise ValueError("require both complete thirty-dataset six-quantity cohorts")
        cohorts.append(rows)
    widths = {
        r["parameter"]: float(r["prior_interval_width90"])
        for r in read_rows(base / folders[0] / "recovery-bias-coverage-and-contraction.csv")
        if r["prior_interval_width90"]
    }
    table = compare_cohorts(cohorts[0], cohorts[1], widths)
    summaries: list[dict[str, Any]] = []
    for name in ["design-recovery-v1", "design-recovery-combined-followup-v1"]:
        path = base / name / "run-summary.json"
        summaries.append(json.loads(path.read_text()))
        pins[str(path.relative_to(root))] = sha256(path)
    calls = sum(s["calls_used"] for s in summaries)
    ceiling = summaries[0]["max_calls"]
    posteriors = [
        p
        for name in ["design-recovery-v1", "design-recovery-combined-followup-v1"]
        for p in (root / "data/processed/models" / name).glob("*.nc")
    ]
    expected_draws = {
        p: h
        for folder in folders
        for p, h in json.loads((base / folder / "inputs.json").read_text()).items()
        if p.endswith(".nc")
    }
    if len(posteriors) != calls:
        raise ValueError("retained posterior storage accounting is incomplete")
    for path in posteriors:
        relative = str(path.relative_to(root))
        if sha256(path) != expected_draws[relative]:
            raise ValueError("retained posterior storage identity changed")
        pins[relative] = expected_draws[relative]
    used_bytes = sum(p.stat().st_size for p in posteriors)
    output.mkdir(parents=True)
    write_table(output / "initial-followup-and-pooled-recovery.csv", table)
    text = (
        "# Difficult-scenario recovery follow-up\n\n"
        "The weak-event/wide-record setting was selected after sigma coverage was low in "
        "the initial thirty datasets. Thirty new datasets were then frozen before their outcomes, "
        "with unchanged truth and independent seeds. Every original dataset remains included. "
        "The pooled Wilson interval is descriptive under this adaptive follow-up; it is not "
        "fresh confirmation or a guarantee of nominal conditional coverage.\n\n"
        "| Cohort | Sigma mean error | Coverage of central 90% interval | Wilson 95% reference |\n"
        "| --- | ---: | ---: | --- |\n"
    )
    for row in table:
        if row["parameter"] != "sigma":
            continue
        n = row["coverage_denominator"]
        success = round(row["coverage90"] * n)
        text += (
            f"| {row['cohort']} | {row['mean_error']:.6f} | {success}/{n} | "
            f"{row['coverage90_wilson95_low']:.2%}–{row['coverage90_wilson95_high']:.2%} |\n"
        )
    text += (
        "\nAll thirty follow-up fits passed without repairs. Independent review reproduced "
        "all new posterior means, quantiles, SDs and standardized errors; representative "
        "chains also passed independent rank and sampler-statistic checks. Recovery used "
        f"{calls} of the original {ceiling} calls and {used_bytes:,} of "
        f"{2 * 1024**3:,} posterior bytes. "
        "The accepted 200-dataset SBC results and all original recovery chains remain intact.\n\n"
        "This completes the bounded follow-up. Fixed-truth Bayesian coverage need not equal "
        "nominal probability at every parameter setting. These results limit conditional "
        "interval claims; they justify neither forcing priors to achieve 90% nor claiming "
        "a physical model has been validated. No further iterations are scheduled.\n"
    )
    (output / "followup-findings.md").write_text(text)
    pins["analysis/arrival/model_recovery_followup.py"] = sha256(
        root / "analysis/arrival/model_recovery_followup.py"
    )
    pins["scripts/summarize_arrival_model_followup.py"] = sha256(
        root / "scripts/summarize_arrival_model_followup.py"
    )
    write_json(output / "inputs.json", pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
