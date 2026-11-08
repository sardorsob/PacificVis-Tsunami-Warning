"""Criticize initial exploration fits without treating in-sample checks as model selection."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json
from analysis.arrival.model_data import METADATA, load_lanes
from analysis.arrival.model_validation_report import write_table

KINDS = ["pooled", "distance", "event"]


def matched_predictive_checks(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    reference: dict[tuple[str, str, str], tuple[float, int]] = {}
    expected: set[tuple[str, str, str]] | None = None
    output: list[dict[str, Any]] = []
    for kind, table in tables.items():
        keys = set()
        for row in table:
            key = row["stratum"], row["scale"], row["quantile"]
            if key in keys:
                raise ValueError("duplicate predictive observation cell")
            keys.add(key)
            value, count = float(row["observed"]), int(row["records"])
            if key in reference and reference[key] != (value, count):
                raise ValueError("comparators use different observations/counts")
            reference[key] = value, count
            lower, median, upper = (
                float(row[k]) for k in ["replicated_q05", "replicated_q50", "replicated_q95"]
            )
            if not lower <= median <= upper or not np.isfinite([value, lower, median, upper]).all():
                raise ValueError("invalid predictive quantile cell")
            output.append(
                {
                    "model": kind,
                    **row,
                    "observed_outside_replicated_central90": not lower <= value <= upper,
                }
            )
        if expected is not None and keys != expected:
            raise ValueError("comparators have different predictive observation cells")
        expected = keys
    return output


def write_fit_report(root: Path, fits: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("preserve earlier report; require a new output path")
    lanes, contract = load_lanes(root)
    lane = lanes["NCEI-native-duration"]
    pins = {p: sha256(root / p) for p in contract["inputs"]}
    tables, parameters, results = {}, [], {}
    for kind in KINDS:
        folder = fits / kind
        result = json.loads((folder / "result.json").read_text())
        if (
            result["status"] != "computed_pending_scientific_review"
            or result["job"]["target"] != lane.target
            or result["job"]["kind"] != kind
            or not result["diagnostics"]["screen_passed"]
        ):
            raise ValueError("require numerically screened source-specific comparator fits")
        inputs = json.loads((folder / "inputs.json").read_text())
        if inputs["source_files"] != contract:
            raise ValueError("comparator evidence/source contract changed")
        for path, digest in inputs["code_and_config"].items():
            if sha256(checked_path(root, path)) != digest:
                raise ValueError("fit consumed source changed; use its recorded code snapshot")
        for path, digest in json.loads((folder / "output-checksums.json").read_text()).items():
            if sha256(folder / path) != digest:
                raise ValueError("fit output changed")
        posterior = checked_path(root, result["posterior"])
        if sha256(posterior) != result["posterior_sha256"]:
            raise ValueError("fit posterior changed")
        pins[str(posterior.relative_to(root))] = sha256(posterior)
        for path in folder.iterdir():
            if path.is_file():
                pins[str(path.relative_to(root))] = sha256(path)
        tables[kind] = read_rows(folder / "conditional-predictive-quantiles-by-distance.csv")
        parameters.extend(
            {"model": kind, **r} for r in read_rows(folder / "population-parameter-quantiles.csv")
        )
        results[kind] = result
    checks = matched_predictive_checks(tables)
    metadata = {r["event_id"]: r for r in read_rows(root / METADATA)}
    counts = {
        event: sum(event == e and ok for e, ok in zip(lane.event_ids, lane.included, strict=True))
        for event in set(lane.event_ids)
    }
    event_posterior = checked_path(root, results["event"]["posterior"])
    events = []
    with xr.open_dataset(event_posterior, group="posterior", engine="h5netcdf") as posterior:
        for event in posterior.event.values:
            values = posterior["event_effect"].sel(event=event).values
            low, median, high = np.quantile(values, [0.05, 0.5, 0.95])
            m = metadata[str(event)]
            events.append(
                {
                    "event_id": str(event),
                    "date": m["origin_utc"][:10],
                    "region": m["region"],
                    "records": int(counts[str(event)]),
                    "log_effect_q05": float(low),
                    "log_effect_q50": float(median),
                    "log_effect_q95": float(high),
                    "median_duration_factor_q05": float(np.exp(low)),
                    "median_duration_factor_q50": float(np.exp(median)),
                    "median_duration_factor_q95": float(np.exp(high)),
                }
            )
    output.mkdir(parents=True)
    write_table(output / "population-parameters-and-derived-duration-ratios.csv", parameters)
    write_table(output / "conditional-report-quantile-checks-by-distance.csv", checks)
    write_table(output / "event-timing-offsets-and-uncertainty.csv", events)
    plot_fit_checks(output, checks, events)
    text = (
        "# Initial models of NCEI reported durations\n\n"
        "Three exploration models use the same 1,064 approved records from 33 events: "
        "a pooled log reference ratio, a distance adjustment, and a distance adjustment "
        "with partially pooled event effects. All numerical screens passed; results remain "
        "exploratory until independent scientific review. No held-out score or model selection "
        "has been computed. The 18 reserved outcomes remain sealed.\n\n"
        "The reference uses epicenter distance and a fixed four-kilometer-depth speed. "
        "Reported-duration definitions and clock/source effects are composite. Neither the "
        "distance exponent nor an event offset identifies a physical wave speed or delay. "
        "The event population center has a different interpretation/weighting from a pooled "
        "record center; a change in alpha between these fits is not an observed forecast bias.\n\n"
        "| Model | Alpha, log ratio (central 90%) | Beta (central 90%) | "
        "Event SD (central 90%) | Record SD (central 90%) |\n"
        "| --- | --- | --- | --- | --- |\n"
    )
    for kind in KINDS:
        by_parameter = {r["parameter"]: r for r in parameters if r["model"] == kind}
        cells = [kind]
        for name in ["alpha", "beta", "tau_event", "sigma"]:
            r = by_parameter.get(name)
            cells.append(
                "fixed zero"
                if r is None
                else f"{float(r['q50']):.3f} [{float(r['q05']):.3f}, {float(r['q95']):.3f}]"
            )
        text += "| " + " | ".join(cells) + " |\n"
    text += (
        "\nPredictive checks replicate reports at the observed distances, conditional on fitted "
        "events. The plotted intervals describe variation in replicated sample quantiles, "
        "not credible intervals for a mean and not new-event validation. Observed quantiles "
        "have no extra uncertainty band. The flags are correlated exploratory discrepancies, "
        "not calibrated tests or a ranking criterion.\n\n"
        "| Model | Modeled-response quantile checks outside central 90% | "
        "Native-minute checks outside central 90% |\n"
        "| --- | ---: | ---: |\n"
    )
    for kind in KINDS:
        cells = []
        for scale in ["modeled-response", "native-minutes"]:
            rows = [r for r in checks if r["model"] == kind and r["scale"] == scale]
            cells.append(
                f"{sum(r['observed_outside_replicated_central90'] for r in rows)}/{len(rows)}"
            )
        text += f"| {kind} | {cells[0]} | {cells[1]} |\n"
    text += (
        "\nThese discrepancies motivate a bounded mean/scale/tail investigation. A smaller fitted "
        "record SD alone does not establish improved prediction. Sequence-held-out refits, "
        "numerical integration checks and sensitivity precede selection. The difficult-scenario "
        "recovery follow-up is complete, with adaptive-selection and conditional-coverage limits. "
        "Separate NTWC computational checks remain required.\n"
    )
    (output / "baseline-findings.md").write_text(text)
    for name in ["analysis/arrival/model_fit_report.py", "scripts/summarize_arrival_model_fits.py"]:
        pins[name] = sha256(root / name)
    write_json(output / "inputs.json", pins)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def plot_fit_checks(
    output: Path, checks: list[dict[str, Any]], events: list[dict[str, Any]]
) -> None:
    """Takeaway: simple Gaussian assumptions leave conditional discrepancies | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"pooled": "#666666", "distance": "#146782", "event": "#b05a24"}
    strata = ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"]
    with plt.rc_context({"font.size": 11, "axes.titlesize": 12}):
        fig, all_axes = plt.subplots(
            4,
            1,
            figsize=(7, 9.5),
            layout="constrained",
            gridspec_kw={"height_ratios": [0.18, 1, 1, 1]},
        )
        legend_axis, axes = all_axes[0], all_axes[1:]
        legend_axis.set_axis_off()
        for ax, quantile in zip(axes, [0.05, 0.5, 0.95], strict=True):
            for kind, offset in zip(KINDS, [-0.18, 0, 0.18], strict=True):
                rows = [
                    next(
                        r
                        for r in checks
                        if r["model"] == kind
                        and r["stratum"] == s
                        and r["scale"] == "modeled-response"
                        and float(r["quantile"]) == quantile
                    )
                    for s in strata
                ]
                med = np.array([float(r["replicated_q50"]) for r in rows])
                low = np.array([float(r["replicated_q05"]) for r in rows])
                high = np.array([float(r["replicated_q95"]) for r in rows])
                ax.errorbar(
                    np.arange(4) + offset,
                    med,
                    yerr=[med - low, high - med],
                    fmt="o",
                    capsize=3,
                    color=colors[kind],
                    label=kind,
                )
            ax.scatter(
                np.arange(4),
                [float(r["observed"]) for r in rows],
                marker="D",
                color="#111111",
                s=30,
                label="observed",
                zorder=5,
            )
            ax.set_title(f"{quantile:.0%} quantile of log(reported/reference duration)", loc="left")
            labels = ["<500 km", "500–2,000 km", "2,000–5,000 km", "≥5,000 km"]
            ax.set_xticks(
                range(4),
                [label + f"\nn={rows[i]['records']}" for i, label in enumerate(labels)],
                fontsize=10.5,
            )
            ax.set_ylabel("Log duration ratio")
            ax.spines[["right", "top"]].set_visible(False)
        handles, labels = axes[0].get_legend_handles_labels()
        legend_axis.legend(handles, labels, ncol=4, loc="center", frameon=False, fontsize=10.5)
        fig.suptitle("Simple models leave distance-specific\ntiming discrepancies", fontsize=14)
        fig.supxlabel(
            "Dots and bars: median and central 90% replicated quantiles.\n"
            "Diamonds: observations. Fitted-event checks, not held-out prediction.\n"
            "Source: NCEI exploration reports and Bayesian baseline fits.",
            fontsize=10.5,
        )
        fig.savefig(output / "distance-conditioned-predictive-quantiles.png", dpi=180)
        fig.savefig(output / "distance-conditioned-predictive-quantiles.svg")
        plt.close(fig)
        rows = sorted(events, key=lambda r: r["log_effect_q50"])
        fig, ax = plt.subplots(figsize=(7, 12), layout="constrained")
        median = np.array([r["log_effect_q50"] for r in rows])
        ax.errorbar(
            median,
            np.arange(len(rows)),
            xerr=[
                median - np.array([r["log_effect_q05"] for r in rows]),
                np.array([r["log_effect_q95"] for r in rows]) - median,
            ],
            fmt="o",
            capsize=2,
            color="#146782",
        )
        ax.axvline(0, color="#666666", ls="--", lw=1)
        region_labels = {
            "northwest_pacific": "NW Pacific",
            "southwest_pacific": "SW Pacific",
            "northeast_pacific": "NE Pacific",
            "southeast_pacific": "SE Pacific",
            "western_pacific": "W Pacific",
            "central_america_mexico": "C Am/Mexico",
            "tonga_kermadec_nz": "Tonga/Kermadec/NZ",
            "alaska_aleutians": "Alaska/Aleutians",
        }
        ax.set_yticks(
            range(len(rows)),
            [r["date"] + " " + region_labels[r["region"]] + f" (n={r['records']})" for r in rows],
            fontsize=10.5,
        )
        ax.set_xlabel("Event effect on log duration ratio\nCentral 90% posterior interval")
        fig.suptitle("Event offsets combine timing differences\nand remain uncertain", fontsize=14)
        ax.spines[["right", "top"]].set_visible(False)
        fig.supxlabel(
            "Geographic/event effects can include source, clock, path and reporting differences.\n"
            "Source: NCEI exploration reports; Gaussian event hierarchy.",
            fontsize=10.5,
        )
        fig.savefig(output / "event-offset-posterior-intervals.png", dpi=180)
        fig.savefig(output / "event-offset-posterior-intervals.svg")
        plt.close(fig)
