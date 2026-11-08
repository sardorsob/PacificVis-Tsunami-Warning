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


def event_effect_summary(values: np.ndarray, target: str) -> dict[str, Any]:
    signed = target == "T-CAL"
    prefix = "minute_effect" if signed else "log_effect"
    low, median, high = np.quantile(values, [0.05, 0.5, 0.95])
    result = {
        prefix + "_q05": float(low),
        prefix + "_q50": float(median),
        prefix + "_q95": float(high),
        "units": "minutes" if signed else "log_reference_ratio",
    }
    if not signed:
        result.update(
            {
                "median_duration_factor_q05": float(np.exp(low)),
                "median_duration_factor_q50": float(np.exp(median)),
                "median_duration_factor_q95": float(np.exp(high)),
            }
        )
    return result


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


def write_fit_report(
    root: Path, fits: Path, output: Path, *, target: str = "NCEI-native-duration"
) -> None:
    if output.exists():
        raise ValueError("preserve earlier report; require a new output path")
    lanes, contract = load_lanes(root)
    if target not in lanes:
        raise ValueError("unknown source-specific fit target")
    lane = lanes[target]
    signed = target == "T-CAL"
    source = {
        "NCEI-native-duration": "NCEI reported durations",
        "T-OBS": "NTWC reported durations",
        "T-CAL": "NTWC estimate-minus-observation minutes",
    }[target]
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
            m = metadata[str(event)]
            events.append(
                {
                    "event_id": str(event),
                    "date": m["origin_utc"][:10],
                    "region": m["region"],
                    "records": int(counts[str(event)]),
                    **event_effect_summary(values, target),
                }
            )
    output.mkdir(parents=True)
    parameter_file = (
        "population-signed-minute-parameters.csv"
        if signed
        else "population-parameters-and-derived-duration-ratios.csv"
    )
    write_table(output / parameter_file, parameters)
    write_table(output / "conditional-report-quantile-checks-by-distance.csv", checks)
    write_table(output / "event-timing-offsets-and-uncertainty.csv", events)
    plot_fit_checks(output, checks, events, target=target)
    reference_description = (
        "The signed response is estimated UTC minus reported observed UTC in minutes. "
        "The predictor is ln(source–station distance/1000km); this response uses no "
        "distance/reference-duration transformation. Population means describe archived "
        "products, not prospective warning performance or a causal forecaster error.\n\n"
        if signed
        else "The reference uses epicenter distance and a fixed four-kilometer-depth speed. "
        "Reported-duration definitions and clock/source effects are composite. Neither the "
        "distance exponent nor an event offset identifies a physical wave speed or delay. "
        "The event population center differs from a pooled record center; a change in alpha "
        "does not identify historical forecast bias.\n\n"
    )
    units = "minutes" if signed else "log ratio"
    text = (
        f"# Initial models of {source}\n\n"
        f"Three exploration models use the same {int(lane.included.sum()):,} approved records "
        f"from {len(events)} events: "
        "a pooled population center, a distance adjustment, and a distance adjustment "
        "with partially pooled event effects. All numerical screens passed. These are exploratory "
        "development fits; the review receipt records what was independently verified. "
        "No held-out score or model selection "
        "has been computed. The 18 reserved outcomes remain sealed.\n\n"
        + reference_description
        + f"| Model | Alpha, {units} (central 90%) | Beta (central 90%) | "
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
        + (
            "For T-CAL the modeled and native scales are both minutes, so the two columns "
            "repeat the same checks and are not independent evidence.\n\n"
            if signed
            else ""
        )
        + "| Model | Modeled-response quantile checks outside central 90% | "
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
        "numerical integration checks and sensitivity precede selection. "
        "Each source's computational readiness is reviewed separately; its finite-check "
        "and interpretation limits remain. Source likelihoods are never independently pooled.\n"
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
    output: Path,
    checks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    target: str = "NCEI-native-duration",
) -> None:
    """Takeaway: simple Gaussian assumptions leave conditional discrepancies | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"pooled": "#666666", "distance": "#146782", "event": "#b05a24"}
    strata = ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"]
    strata = [s for s in strata if any(r["stratum"] == s for r in checks)]
    signed = target == "T-CAL"
    source = "NCEI" if target == "NCEI-native-duration" else "NTWC " + target
    prefix = "minute_effect" if signed else "log_effect"
    response_label = (
        "signed estimate−observation minutes" if signed else "log(reported/reference duration)"
    )
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
                    np.arange(len(strata)) + offset,
                    med,
                    yerr=[med - low, high - med],
                    fmt="o",
                    capsize=3,
                    color=colors[kind],
                    label=kind,
                )
            ax.scatter(
                np.arange(len(strata)),
                [float(r["observed"]) for r in rows],
                marker="D",
                color="#111111",
                s=30,
                label="observed",
                zorder=5,
            )
            ax.set_title(f"{quantile:.0%} quantile of {response_label}", loc="left")
            label_map = dict(
                zip(
                    ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"],
                    ["<500 km", "500–2,000 km", "2,000–5,000 km", "≥5,000 km"],
                    strict=True,
                )
            )
            labels = [label_map[s] for s in strata]
            ax.set_xticks(
                range(len(strata)),
                [label + f"\nn={rows[i]['records']}" for i, label in enumerate(labels)],
                fontsize=10.5,
            )
            ax.set_ylabel("Signed difference (minutes)" if signed else "Log duration ratio")
            ax.spines[["right", "top"]].set_visible(False)
        handles, labels = axes[0].get_legend_handles_labels()
        legend_axis.legend(handles, labels, ncol=4, loc="center", frameon=False, fontsize=10.5)
        fig.suptitle("Simple models leave distance-specific\ntiming discrepancies", fontsize=14)
        fig.supxlabel(
            "Dots and bars: median and central 90% replicated quantiles.\n"
            "Diamonds: observations. Fitted-event checks, not held-out prediction.\n"
            f"Source: {source} exploration reports and Bayesian baseline fits.",
            fontsize=10.5,
        )
        fig.savefig(output / "distance-conditioned-predictive-quantiles.png", dpi=180)
        fig.savefig(output / "distance-conditioned-predictive-quantiles.svg")
        plt.close(fig)
        rows = sorted(events, key=lambda r: r[prefix + "_q50"])
        fig, ax = plt.subplots(figsize=(7, max(6, len(rows) * 0.24 + 4)), layout="constrained")
        median = np.array([r[prefix + "_q50"] for r in rows])
        ax.errorbar(
            median,
            np.arange(len(rows)),
            xerr=[
                median - np.array([r[prefix + "_q05"] for r in rows]),
                np.array([r[prefix + "_q95"] for r in rows]) - median,
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
            [
                r["date"]
                + " "
                + region_labels.get(r["region"], r["region"].replace("_", " "))
                + f" (n={r['records']})"
                for r in rows
            ],
            fontsize=10.5,
        )
        ax.set_xlabel(
            (
                "Event effect on signed difference (minutes)"
                if signed
                else "Event effect on log duration ratio"
            )
            + "\nCentral 90% posterior interval"
        )
        fig.suptitle("Event offsets combine timing differences\nand remain uncertain", fontsize=14)
        ax.spines[["right", "top"]].set_visible(False)
        fig.supxlabel(
            "Geographic/event effects can include source, clock, path and reporting differences.\n"
            f"Source: {source} exploration reports; Gaussian event hierarchy.",
            fontsize=10.5,
        )
        fig.savefig(output / "event-offset-posterior-intervals.png", dpi=180)
        fig.savefig(output / "event-offset-posterior-intervals.svg")
        plt.close(fig)
