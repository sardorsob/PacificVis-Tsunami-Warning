"""Auditable fixed-anchor recovery and calibration reports, separate from scientific selection."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from statistics import NormalDist

import numpy as np
import xarray as xr

from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json
from analysis.arrival.model_validation_report import (
    calibration_summary,
    recovery_summary,
    write_table,
)
from analysis.arrival.models import read_prior


def read_scale_quantities(path: Path) -> dict[str, np.ndarray]:
    with xr.open_dataset(path, group="posterior", engine="h5netcdf") as ds:
        values = {p: ds[p].values for p in ["alpha", "beta", "tau_event"]}
        for j, distance in enumerate([500, 2000, 5000]):
            values[f"sigma_{distance}km"] = ds.sigma_anchor.values[..., j]
        values["sigma_1000km"] = ds.sigma_anchor.values[..., :2].mean(axis=-1)
        values["event_effect_first"] = ds.event_effect.isel(event=0).values
    return values


def scale_validation_report(root: Path, batch: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("new report path required")
    plan = json.loads((batch / "plan.json").read_text())
    summary = json.loads((batch / "run-summary.json").read_text())
    dispositions = read_rows(batch / "trial-dispositions.csv")
    accepted = [d for d in dispositions if d["outcome"] == "accepted"]
    if (
        plan["protocol"] != "distance-scale"
        or summary["plan_sha256"] != sha256(batch / "plan.json")
        or len(dispositions) != summary["calls_used"]
        or len(accepted) != summary["completed_datasets"]
        or [d["case_id"] for d in accepted] != [c["id"] for c in plan["cases"][: len(accepted)]]
    ):
        raise ValueError("candidate trial conservation failed")
    pins = {
        str(p.relative_to(root)): sha256(p)
        for p in [
            batch / "plan.json",
            batch / "run-summary.json",
            batch / "trial-dispositions.csv",
            root / "analysis/arrival/model_scale_report.py",
            root / "analysis/arrival/model_validation_report.py",
            root / "scripts/summarize_arrival_scale_validation.py",
            root / "config/arrival-model-priors-v1.toml",
        ]
    }
    cases = {c["id"]: c for c in plan["cases"]}
    estimates, diagnostics = [], []
    for d in dispositions:
        name = d["case_id"] + "-attempt-" + d["attempt"]
        path = batch / "jobs" / name / "result.json"
        if not path.exists():
            if d["outcome"] == "accepted":
                raise ValueError("accepted candidate result missing")
            diagnostics.append({**d, "has_result": False})
            continue
        result = json.loads(path.read_text())
        expected = dict(cases[d["case_id"]]["job"])
        if d["attempt"] == "2":
            expected.update(draws=min(4000, expected["draws"] * 2), tune=2000)
        posterior = checked_path(root, result["posterior"])
        if (
            result["job"] != expected
            or result["synthetic_only"] is not True
            or result["code_and_config"]
            != {
                p: digest
                for p, digest in plan["code_and_config"].items()
                if p != "scripts/run_arrival_model_batch.py"
            }
            or sha256(posterior) != result["posterior_sha256"]
        ):
            raise ValueError("candidate trial identity changed")
        pins[str(path.relative_to(root))] = sha256(path)
        pins[str(posterior.relative_to(root))] = sha256(posterior)
        diagnostics.append(
            {
                **d,
                **result["diagnostics"],
                "elapsed_seconds": result["elapsed_seconds"],
                "has_result": True,
            }
        )
        if d["outcome"] != "accepted":
            continue
        if not result["diagnostics"]["screen_passed"]:
            raise ValueError("accepted candidate has failed diagnostics")
        quantities = read_scale_quantities(posterior)
        if set(quantities) != {e["parameter"] for e in result["estimates"]}:
            raise ValueError("candidate quantities changed")
        for row in result["estimates"]:
            values = quantities[row["parameter"]]
            q = np.quantile(values, [0.05, 0.5, 0.95])
            sd = float(values.std(ddof=1))
            if (
                not np.allclose(
                    [values.mean(), *q],
                    [row["mean"], row["q05"], row["median"], row["q95"]],
                    rtol=1e-12,
                    atol=1e-12,
                )
                or not np.isfinite(sd)
                or sd <= 0
            ):
                raise ValueError("candidate posterior summary mismatch")
            estimates.append(
                {
                    "case_id": d["case_id"],
                    "scenario": cases[d["case_id"]]["scenario"],
                    "replicate": cases[d["case_id"]]["replicate"],
                    "seed": expected["seed"],
                    **row,
                    "posterior_sd": sd,
                    "standardized_mean_error": (row["mean"] - row["truth"]) / sd,
                }
            )
    output.mkdir(parents=True)
    write_table(output / "parameter-estimates-by-dataset.csv", estimates)
    write_table(output / "attempt-diagnostics.csv", diagnostics)
    prior = read_prior(root, "NCEI-native-duration", "base")
    normal = NormalDist()
    widths = {
        "alpha": 2 * normal.inv_cdf(0.95) * prior["alpha_sd"],
        "beta": 2 * normal.inv_cdf(0.95) * prior["beta_sd"],
        **{
            p: (normal.inv_cdf(0.975) - normal.inv_cdf(0.525)) * prior[k]
            for p, k in [
                ("tau_event", "tau_sd"),
                ("sigma_500km", "sigma_sd"),
                ("sigma_2000km", "sigma_sd"),
                ("sigma_5000km", "sigma_sd"),
            ]
        },
    }
    recovery = summary["phase"] == "recovery"
    table = (
        recovery_summary(estimates, widths)
        if recovery
        else calibration_summary(estimates, planned_quantities=8)
    )
    write_table(
        output
        / (
            "recovery-bias-coverage-and-contraction.csv" if recovery else "sbc-rank-calibration.csv"
        ),
        table,
    )
    summary["complete"] = summary["status"] == "computations_complete" and len(accepted) == len(
        plan["cases"]
    )
    summary["scientific_acceptance"] = "pending_independent_review"
    write_json(output / "status.json", summary)
    write_json(output / "inputs.json", pins)
    plot_scale_validation(output, summary, table, estimates)
    text = (
        "# Distance-dependent reported-duration spread: computational checks\n\n"
        f"{len(accepted)} of {len(plan['cases'])} predefined synthetic datasets completed in "
        f"{len(dispositions)} attempts. The fixed NCEI exploration design has 1,064 records "
        "and 33 events. Actual reported responses did not enter these simulated likelihoods. "
        "All attempts, including failed precision checks, remain in the diagnostics table.\n\n"
        "The six population parameters are alpha and beta (log-ratio center/distance adjustment), "
        "tau (between-event log-ratio SD), and three residual SD anchors at500/2000/5000km. "
        "SD1000 is the interpolation midpoint of the first two anchors. The first effect is "
        "the lexically first fitted event's latent effect, reconstructed by its exact conditional "
        "Normal. These quantities describe composite reports, not physical noise or accuracy.\n\n"
    )
    if recovery:
        text += (
            "Each setting allocates 15 independent datasets; completed counts are in the table. "
            "Coverage is the fraction of true values "
            "inside central posterior 90% intervals. Wilson 95% intervals express finite-replicate "
            "uncertainty; individual fluctuations do not certify or refute identifiability. "
            "Contraction is one minus posterior/prior central-90% width, where analytic prior "
            "widths exist. Standardized error uses posterior SD and is not a Normal-test z.\n\n"
        )
    else:
        text += (
            "Eight prespecified quantities use 100 spaced posterior draws for ranks while "
            "retaining all original chains and ESS. The simultaneous DKW/Bonferroni band has "
            "familywise reference alpha.05 under independent uniform ranks; MCMC dependence "
            "makes it approximate. A crossing needs diagnosis. No crossing is not proof of "
            "computational correctness or physical validity.\n\n"
        )
    text += (
        "Recovery and calibration under an assumed simulator do not establish model adequacy, "
        "predictive transfer, archive representativeness or a model-selection decision. "
        "The 18 reserved outcomes remain sealed.\n"
    )
    (output / "findings.md").write_text(text)
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in sorted(output.iterdir()) if p.is_file()},
    )


def plot_scale_validation(output: Path, status: dict, table: list[dict], estimates: list[dict]):
    """Takeaway: finite simulation uncertainty accompanies calibration screens | expert | report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [
        "alpha",
        "beta",
        "tau_event",
        "sigma_500km",
        "sigma_2000km",
        "sigma_5000km",
        "sigma_1000km",
        "event_effect_first",
    ]
    with plt.rc_context({"font.size": 11}):
        fig, axes = plt.subplots(4, 2, figsize=(7, 12), layout="constrained")
        recovery = status["phase"] == "recovery"
        for ax, name in zip(axes.flat, names, strict=True):
            ax.set_title(name.replace("_", " "), fontsize=12)
            if recovery:
                cells = [r for r in table if r["parameter"] == name]
                for j, cell in enumerate(cells):
                    ax.plot(
                        [cell["coverage90_wilson95_low"], cell["coverage90_wilson95_high"]],
                        [j, j],
                        color="#146782",
                        lw=2,
                    )
                    ax.plot(cell["coverage90"], j, "o", color="#146782")
                ax.axvline(0.9, color="#777777", ls="--")
                ax.set(
                    yticks=range(len(cells)),
                    yticklabels=[c["scenario"].replace("-spread", "") for c in cells],
                    xlim=(-0.04, 1.04),
                    xticks=[0, 0.5, 1],
                    xlabel="Coverage",
                )
            else:
                u = np.sort([e["randomized_rank_pit"] for e in estimates if e["parameter"] == name])
                epsilon = next(r["simultaneous_epsilon"] for r in table if r["parameter"] == name)
                x = np.linspace(0, 1, 101)
                ax.fill_between(
                    x, np.maximum(0, x - epsilon), np.minimum(1, x + epsilon), color="#dddddd"
                )
                ax.plot(x, x, color="#777777", ls="--")
                ax.step(
                    np.r_[0, u, 1],
                    np.r_[0, np.arange(1, len(u) + 1) / len(u), 1],
                    where="post",
                    color="#146782",
                )
                ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Randomized rank", ylabel="ECDF")
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(
            "Finite recovery checks" if recovery else "Prior-generated inference calibration",
            fontsize=16,
        )
        counts = sorted({r["datasets"] for r in table})
        n = str(counts[0]) if len(counts) == 1 else f"{min(counts)}–{max(counts)}"
        caption = (
            "Dots: coverage by central 90% posterior intervals.\n"
            f"Bars: Wilson 95%; dashed: nominal 90%; {n} datasets/setting."
            if recovery
            else "100 datasets; ranks from 100 spaced posterior draws.\n"
            "Gray: approximate simultaneous band; MCMC caveats apply."
        )
        fig.supxlabel(
            caption + "\nSynthetic NCEI design: 1,064 reports / 33 events; no physical validation.",
            fontsize=10.5,
        )
        fig.savefig(output / "simulation-uncertainty.png", dpi=180)
        fig.savefig(output / "simulation-uncertainty.svg")
        plt.close(fig)
