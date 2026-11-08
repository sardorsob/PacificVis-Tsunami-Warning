"""Compare fitted log-median shape and residual spread without selecting by PPC."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json
from analysis.arrival.model_curvature import curvature_basis
from analysis.arrival.model_scale import scale_weights
from analysis.arrival.model_validation_report import write_table

FOLDERS = {
    "linear": "artifacts/models/arrival-timing/exploration-distance-scale-v1",
    "curvature": "artifacts/models/arrival-timing/exploration-mean-curvature-v1",
}
COLORS = {"linear": "#777777", "curvature": "#0072B2"}
LABELS = {"linear": "Linear log-median ratio", "curvature": "Curved log-median ratio"}


def population_curves(post, distance, curved):
    a, b = [post[p].reshape(-1) for p in ["alpha", "beta"]]
    mean = a[:, None] + b[:, None] * np.log(distance / 1000)
    if curved:
        mean += post["gamma"].reshape(-1, 1) * curvature_basis(distance)
    sigma = post["sigma_anchor"].reshape(-1, 3) @ scale_weights(distance).T
    return np.quantile(mean, [0.05, 0.5, 0.95], axis=0), np.quantile(
        sigma, [0.05, 0.5, 0.95], axis=0
    )


def validate_identity(result, record_ids, event_ids, name):
    expected = "mean-curvature" if name == "curvature" else "distance-scale"
    if (
        result.get("records") != 1064
        or result.get("events") != 33
        or result.get("job", {}).get("target") != "NCEI-native-duration"
        or result["job"].get("prior") != "base"
        or result["job"].get("kind") != expected
        or len(record_ids) != 1064
        or len(set(record_ids)) != 1064
        or len(event_ids) != 33
        or len(set(event_ids)) != 33
    ):
        raise ValueError("exact base-prior primary1064/33 fit identities required")


def validate_ppc(checks):
    strata = {"all", "under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"}
    expected = {
        (s, c, q)
        for s in strata
        for c in ["modeled-response", "native-minutes"]
        for q in [0.05, 0.5, 0.95]
    }
    models = {}
    for model in FOLDERS:
        rows = [r for r in checks if r["model"] == model]
        cells = {(r["stratum"], r["scale"], r["quantile"]): r for r in rows}
        if len(rows) != 30 or set(cells) != expected:
            raise ValueError("exact5strata2scales3quantiles required for each fit")
        counts = {}
        for s in strata:
            sizes = {
                cells[s, c, q]["records"]
                for c in ["modeled-response", "native-minutes"]
                for q in [0.05, 0.5, 0.95]
            }
            if len(sizes) != 1 or any(n <= 0 or n != int(n) for n in sizes):
                raise ValueError("consistent positive integral stratum counts required")
            counts[s] = sizes.pop()
        if counts["all"] != 1064 or sum(v for s, v in counts.items() if s != "all") != 1064:
            raise ValueError("disjoint stratum counts must account for the full1064cohort")
        for r in rows:
            values = [
                r[k] for k in ["observed", "replicated_q05", "replicated_q50", "replicated_q95"]
            ]
            if not np.isfinite(values).all() or not values[1] <= values[2] <= values[3]:
                raise ValueError("finite ordered predictive statistics required")
        models[model] = cells
    for key, row in models["linear"].items():
        other = models["curvature"][key]
        if row["records"] != other["records"] or not np.isclose(
            row["observed"], other["observed"], rtol=0, atol=1e-12
        ):
            raise ValueError("both models must use identical observed statistics and counts")


def report(root: Path, output: Path) -> None:
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local report required")
    posts, pins, checks = {}, {}, []
    ids = None
    response = None
    for name, relative in FOLDERS.items():
        folder = root / relative
        result = json.loads((folder / "result.json").read_text())
        if not result["diagnostics"]["screen_passed"] or result.get("records") != 1064:
            raise ValueError("same accepted computational cohort required")
        for p, h in result["code_and_config"].items():
            if sha256(checked_path(root, p)) != h:
                raise ValueError("fit source changed")
            pins[p] = h
        outputs = json.loads((folder / "output-checksums.json").read_text())
        required = {
            "inputs.json",
            "job.json",
            "result.json",
            "sampling-diagnostics.csv",
            "conditional-predictive-quantiles-by-distance.csv",
            "population-parameter-quantiles.csv",
            "in-sample-record-predictions.csv",
        }
        if not required.issubset(outputs):
            raise ValueError("complete fitted scientific tables required")
        for p, h in outputs.items():
            if Path(p).name != p or sha256(folder / p) != h:
                raise ValueError("fit output changed")
            pins[str((folder / p).relative_to(root))] = h
        pins[relative + "/output-checksums.json"] = sha256(folder / "output-checksums.json")
        path = checked_path(root, result["posterior"])
        if sha256(path) != result["posterior_sha256"]:
            raise ValueError("fit posterior changed")
        pins[str(path.relative_to(root))] = sha256(path)
        tree = xr.open_datatree(path, engine="h5netcdf")
        try:
            observed = tree["observed_data"]
            validate_identity(
                result,
                observed.record.values.tolist(),
                tree["posterior"].coords["event"].values.tolist(),
                name,
            )
            if ids is not None:
                np.testing.assert_array_equal(observed.record.values, ids)
                np.testing.assert_array_equal(observed.response.values, response)
            ids, response = observed.record.values.copy(), observed.response.values.copy()
            posterior = cast(Any, tree["posterior"])
            posts[name] = {str(p): posterior[str(p)].values.copy() for p in posterior.data_vars}
        finally:
            tree.close()
        checks += [
            {
                "model": name,
                **{k: v if k in {"stratum", "scale"} else float(v) for k, v in row.items()},
            }
            for row in read_rows(folder / "conditional-predictive-quantiles-by-distance.csv")
        ]
    validate_ppc(checks)
    distance = np.unique(np.r_[np.geomspace(20, 20000, 120), 500, 1000, 2000, 5000])
    curves, event_sd = [], []
    for name, post in posts.items():
        means, scales = population_curves(post, distance, name == "curvature")
        curves += [
            {
                "model": name,
                "distance_km": float(d),
                **{
                    f"log_median_ratio_q{q:02d}": float(means[k, j])
                    for k, q in enumerate([5, 50, 95])
                },
                **{f"residual_sd_q{q:02d}": float(scales[k, j]) for k, q in enumerate([5, 50, 95])},
            }
            for j, d in enumerate(distance)
        ]
        q = np.quantile(post["tau_event"], [0.05, 0.5, 0.95])
        event_sd.append(
            {"model": name, **{f"q{level:02d}": float(q[k]) for k, level in enumerate([5, 50, 95])}}
        )
    post = posts["curvature"]
    names = ["alpha", "beta", "gamma", "tau_event", "sigma_500km", "sigma_2000km", "sigma_5000km"]
    values = [post[p].reshape(-1) for p in names[:4]] + [
        post["sigma_anchor"][..., j].reshape(-1) for j in range(3)
    ]
    correlations = np.corrcoef(values)
    coupling = [
        {"parameter_a": a, "parameter_b": b, "posterior_correlation": float(correlations[i, j])}
        for i, a in enumerate(names)
        for j, b in enumerate(names)
        if j > i
    ]
    output.mkdir(parents=True)
    write_table(output / "log-median-and-residual-spread-curves.csv", curves)
    write_table(output / "between-event-spread-by-model.csv", event_sd)
    write_table(output / "posterior-parameter-coupling.csv", coupling)
    write_table(output / "conditional-reported-quantile-checks.csv", checks)
    plot(output, curves, event_sd, checks)
    gamma = np.quantile(post["gamma"], [0.05, 0.5, 0.95])
    elasticity = np.quantile(1 + post["beta"] - post["gamma"] / 3, [0.05, 0.5, 0.95])
    cells = [r for r in checks if r["model"] == "curvature" and r["scale"] == "modeled-response"]
    misses = [r for r in cells if not r["replicated_q05"] <= r["observed"] <= r["replicated_q95"]]
    text = [
        "# Curvature in reported arrival duration",
        "",
        "The additional mean basis changes the distance relationship while the residual-spread "
        "model stays fixed. Both fits use the same 1,064 NCEI reports from 33 exploration events, "
        "with the six ambiguous repeated-edge records excluded together. The target is native "
        "reported positive duration, not a universally verified physical onset or warning time.",
        "",
        f"Gamma is {gamma[1]:.3f} [{gamma[0]:.3f}, {gamma[2]:.3f}] and local median elasticity at "
        f"1,000 km is {elasticity[1]:.3f} [{elasticity[0]:.3f}, {elasticity[2]:.3f}], "
        "with central 90% "
        "posterior intervals. The curvature basis is log((d+500)/(1.5d)); alpha remains the "
        "population log-median ratio at 1,000 km. Beta alone is not a global distance exponent "
        "for this candidate. Coefficient correlations describe posterior coupling, not causation.",
        "",
        "| Model | Between-event log-scale SD | Central90% interval |",
        "| --- | ---: | ---: |",
        *[
            f"| {LABELS[r['model']]} | {r['q50']:.4f} | [{r['q05']:.4f}, {r['q95']:.4f}] |"
            for r in event_sd
        ],
        "",
        "Between-event variation is conditional on the specified mean and residual-spread "
        "model. Its magnitude does not identify clock, source, path or reporting mechanisms.",
        "",
        f"Of 15 correlated fitted-event log-ratio quantile checks, {len(misses)} "
        "observed statistics "
        "fall outside their central 90% replicated ranges. These checks criticize the model; "
        "they are neither independent tests nor a selection score. Inspect the table and figure "
        "for which strata and tails remain mismatched. New-sequence prediction and sensitivity "
        "analysis remain necessary before selection.",
        "",
        "Curve bands are pointwise central 90% posterior parameter intervals at zero event "
        "effect, not simultaneous or noisy-observation bands. Predictive-check bars are "
        "central 90% variation in sample quantiles replicated conditional on the fitted events. "
        "The plotted grid extends from 20 to 20,000 km; endpoint behavior remains model-imposed.",
        "",
        "Reproduce with `uv run python scripts/summarize_arrival_curvature_fit.py --output "
        f"{output.relative_to(root)}` using a new output directory. Confirmation outcomes were "
        "not parsed and reserved outcomes remain sealed.",
        "",
    ]
    (output / "findings.md").write_text("\n".join(text))
    for p in [
        "analysis/arrival/model_curvature_fit_report.py",
        "scripts/summarize_arrival_curvature_fit.py",
        "analysis/arrival/model_curvature.py",
        "analysis/arrival/model_scale.py",
        "analysis/arrival/model_validation_report.py",
    ]:
        h = sha256(root / p)
        if p in pins and pins[p] != h:
            raise ValueError("report conflicts with frozen fit source")
        pins[p] = h
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "historical_refit": False,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def plot(output, curves, event_sd, checks):
    """Takeaway: compare median shape and residual/event variation | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.size": 11}):
        fig, axes = plt.subplots(
            3, 1, figsize=(8, 10), layout="constrained", height_ratios=[1, 1, 0.55]
        )
        for name in COLORS:
            rows = sorted(
                [r for r in curves if r["model"] == name], key=lambda r: float(r["distance_km"])
            )
            d = [r["distance_km"] for r in rows]
            for ax, prefix in zip(axes[:2], ["log_median_ratio", "residual_sd"], strict=True):
                ax.fill_between(
                    d,
                    [r[prefix + "_q05"] for r in rows],
                    [r[prefix + "_q95"] for r in rows],
                    color=COLORS[name],
                    alpha=0.15,
                )
                ax.plot(
                    d, [r[prefix + "_q50"] for r in rows], color=COLORS[name], label=LABELS[name]
                )
                ax.set(xscale="log", xlabel="Distance (km, log scale)")
        axes[0].set(
            title="The added basis changes the near-distance median",
            ylabel="Population ln(reported / t₀)",
        )
        axes[0].legend(frameon=False)
        axes[1].set(
            title="Residual spread uses the same three fixed anchors",
            ylabel="Residual SD (log-ratio)",
            ylim=(0, None),
        )
        for j, r in enumerate(event_sd):
            axes[2].errorbar(
                r["q50"],
                j,
                xerr=[[r["q50"] - r["q05"]], [r["q95"] - r["q50"]]],
                fmt="o",
                capsize=3,
                color=COLORS[r["model"]],
            )
        axes[2].set(
            yticks=range(2),
            yticklabels=[LABELS[r["model"]] for r in event_sd],
            xlabel="Between-event SD (log-ratio)",
            ylim=(-0.6, 1.6),
        )
        for ax in axes:
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle("Mean curvature and the allocation of reported-timing variation")
        fig.supxlabel(
            "Bands/bars: pointwise central 90% posterior parameter intervals.\n"
            "Source: NCEI exploration, 1,064 reports / 33 events; same varying-spread priors.",
            fontsize=10,
        )
        fig.savefig(output / "mean-curvature-and-event-attribution.png", dpi=160)
        fig.savefig(output / "mean-curvature-and-event-attribution.svg")
        plt.close(fig)
        fig, axes = plt.subplots(3, 1, figsize=(8, 9), layout="constrained")
        strata = ["under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above"]
        for ax, q in zip(axes, [0.05, 0.5, 0.95], strict=True):
            for name, offset in [("linear", -0.12), ("curvature", 0.12)]:
                rows = [
                    next(
                        r
                        for r in checks
                        if r["model"] == name
                        and r["stratum"] == s
                        and r["scale"] == "modeled-response"
                        and r["quantile"] == q
                    )
                    for s in strata
                ]
                for j, r in enumerate(rows):
                    ax.plot(
                        [j + offset, j + offset],
                        [r["replicated_q05"], r["replicated_q95"]],
                        color=COLORS[name],
                        linewidth=4,
                        alpha=0.6,
                    )
                    ax.scatter(
                        j + offset,
                        r["replicated_q50"],
                        color=COLORS[name],
                        s=25,
                        label=LABELS[name] if j == 0 else None,
                    )
                if name == "linear":
                    ax.scatter(
                        range(4),
                        [r["observed"] for r in rows],
                        color="black",
                        marker="x",
                        s=45,
                        label="Observed statistic",
                    )
            ax.set(
                title=f"Reported log-ratio quantile: {q:.0%}",
                ylabel="ln(reported / t₀)",
                xticks=range(4),
                xticklabels=["<500", "500–2,000", "2,000–5,000", "≥5,000"],
            )
            ax.spines[["top", "right"]].set_visible(False)
        axes[0].legend(frameon=False, ncol=1, fontsize=10)
        axes[-1].set_xlabel("Distance band (km)")
        fig.suptitle("Conditional model criticism by distance")
        fig.supxlabel(
            "Bars: central 90% replicated sample-quantile ranges; dots: replicated medians.\n"
            "Source: same 1,064 NCEI reports / 33 fitted events; 800 conditional replicates/model.",
            fontsize=10,
        )
        fig.savefig(output / "conditional-quantile-checks-by-distance.png", dpi=160)
        fig.savefig(output / "conditional-quantile-checks-by-distance.svg")
        plt.close(fig)
