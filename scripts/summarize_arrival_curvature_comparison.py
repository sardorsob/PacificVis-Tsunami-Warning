"""Compare the reviewed curvature candidate with the same NCEI sequence holdouts."""

# pyright: basic
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_curvature_comparison import collect_curvature  # noqa: E402
from analysis.arrival.model_sequence_comparison import collect_models  # noqa: E402
from analysis.arrival.model_sequence_tables import comparison_tables  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402

LABELS = {
    "event": "Linear mean, constant spread",
    "distance-scale": "Linear mean, varying spread",
    "mean-curvature": "Curved mean, varying spread",
}
COLORS = {"event": "#777777", "distance-scale": "#5B8FA8", "mean-curvature": "#286B55"}
CODE = [
    "scripts/summarize_arrival_curvature_comparison.py",
    "analysis/arrival/model_curvature_comparison.py",
    "analysis/arrival/model_sequence_comparison.py",
    "analysis/arrival/model_sequence_tables.py",
    "analysis/arrival/model_sequence_report.py",
    "analysis/arrival/model_comparison.py",
]


def figures(tables, output):
    plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 1, figsize=(9, 11), layout="constrained")
    pairs = [r for r in tables["paired-score-differences"] if r["first_model"] == "mean-curvature"]
    ax = axes[0]
    for j, row in enumerate(pairs):
        mid = row["paired_mean_difference"]
        ax.errorbar(
            mid,
            j,
            xerr=[
                [mid - row["sequence_cluster_ci95_lower"]],
                [row["sequence_cluster_ci95_upper"] - mid],
            ],
            fmt="o",
            color=COLORS["mean-curvature"],
            capsize=4,
        )
    ax.axvline(0, color="#777777", linestyle="--", linewidth=0.8)
    ax.set(
        yticks=range(len(pairs)),
        yticklabels=["Curved mean minus\n" + LABELS[r["second_model"]] for r in pairs],
        xlabel="Equal-event score difference (nats per report)",
        title="Descriptive 95% sequence-cluster intervals",
    )
    ax.grid(axis="x", alpha=0.2)
    ax.invert_yaxis()
    ax = axes[1]
    styles = {"event": ":", "distance-scale": "--", "mean-curvature": "-"}
    for kind, label in LABELS.items():
        rows = [
            r for r in tables["event-weighted-pit"] if r["model"] == kind and r["stratum"] == "all"
        ]
        x = np.array([r["pit_probability"] for r in rows])
        y = np.array([r["equal_event_cdf"] for r in rows])
        ax.plot(x, y, label=label, color=COLORS[kind], linestyle=styles[kind], linewidth=1.8)
        if kind == "mean-curvature":
            radius = float(rows[0]["bootstrap_supnorm_radius95"])
            ax.fill_between(
                x,
                np.maximum(0, y - radius),
                np.minimum(1, y + radius),
                color=COLORS[kind],
                alpha=0.12,
            )
    ax.plot([0, 1], [0, 1], color="#777777", linestyle="--", linewidth=0.8)
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Held-sequence predictive probability",
        ylabel="Equal-event empirical CDF",
        title="Marginal calibration; curved-mean bootstrap band",
        aspect="equal",
    )
    ax.legend(loc="upper left", fontsize=11, frameon=False)
    fig.suptitle("Curvature compared on the same held-out sequences", fontsize=17)
    fig.supxlabel(
        "NCEI native durations: 1,064 reports, 33 events, 29 sequence groups.\n"
        "Descriptive uncertainty; overlapping training and heuristic groups limit "
        "interpretation.\nPIT band: 95% sequence-bootstrap sup-norm band, not a "
        "uniformity test.",
        fontsize=11,
    )
    for suffix in ["png", "svg"]:
        fig.savefig(output / f"curvature-score-and-calibration.{suffix}", dpi=160)
    plt.close(fig)


def report(root, output):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local comparison report required")
    code = {p: sha256(root / p) for p in CODE}
    candidate, new_pins = collect_curvature(root)
    old, pins = collect_models(root)
    if any(p in pins and pins[p] != h for p, h in new_pins.items()):
        raise ValueError("comparison source identity conflict")
    pins.update(new_pins)
    pins.update(code)
    models = {
        ("NCEI-native-duration", k): old[("NCEI-native-duration", k)]
        for k in ["event", "distance-scale"]
    }
    models[("NCEI-native-duration", "mean-curvature")] = candidate
    tables = comparison_tables(models)
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("comparison inputs changed")
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "selection": "none; exploration comparison before sensitivity",
            "bootstrap_replicates": 2000,
            "bootstrap_seed": 25261108,
        },
    )
    for name, rows in tables.items():
        write_table(
            output / f"{name}.csv",
            [{k: ("not_applicable" if v is None else v) for k, v in row.items()} for row in rows],
        )
    figures(tables, output)
    lines = [
        "# Curvature and held-sequence prediction",
        "",
        "The curved mean is compared with linear means using the same 1,064 NCEI "
        "reported durations, 33 events and 29 sequence holdouts. Each event's joint "
        "native-minute log predictive density is divided by its report count; these 33"
        " values receive equal weight. Higher scores indicate better prediction for "
        "this reported-data target.",
        "",
        "| Mean and spread | Equal-event score | Monte Carlo SE |",
        "| --- | ---: | ---: |",
    ]
    for row in tables["model-scores"]:
        lines.append(
            f"| {LABELS[row['model']]} | {row['equal_event_score']:.6f} | "
            f"{row['monte_carlo_standard_error']:.6f} |"
        )
    for row in tables["paired-score-differences"]:
        if row["first_model"] != "mean-curvature":
            continue
        lines += [
            "",
            f"Curvature minus {LABELS[row['second_model']].lower()} is "
            f"{row['paired_mean_difference']:.4f} nats/report, with a descriptive 95% "
            f"sequence-cluster interval [{row['sequence_cluster_ci95_lower']:.4f}, "
            f"{row['sequence_cluster_ci95_upper']:.4f}].",
        ]
    lines += [
        "",
        "![Native-duration score differences and held-sequence "
        "calibration](curvature-score-and-calibration.png)",
        "",
        "The curved mean adds gamma times log((d+500)/(1.5d)) to the log median ratio."
        " Both varying-spread models use the same three fixed spread anchors. Gamma is"
        " a phenomenological curvature coefficient; it does not identify shelf delay, "
        "propagation physics or recording error. Its prior and this revisit were "
        "chosen after exploration EDA and earlier model criticism.",
        "",
        "Tōhoku's direct bridge estimate failed the overlap checks despite clean "
        "posterior diagnostics. Its score is replaced by an independently accepted "
        "fixed-temperature normalizer path for the same model, prior and held-out "
        "data, with a fresh repeat. The original failed estimate and its training-only"
        " predictions remain unchanged. The native-duration Jacobian is applied once; "
        "numerical uncertainty is separate from between-sequence uncertainty. A finite "
        "Gaussian AR calibration experiment showed a small empirical shift in its finite cohort. "
        "Clean diagnostics and repeat agreement do not certify global posterior "
        "exploration.",
        "",
        "LATA's one-report event in another sequence exceeded the original Monte Carlo "
        "precision screen despite adequate bridge overlap. Two fresh, longer ensembles "
        "for the same training data and LATA-only augmentation passed that screen. "
        "Its fold retains the other event's original score and every original prediction. "
        "Numerical variances for the old and fresh training streams add independently; "
        "the two events remain one sequence for sampling uncertainty. The reported "
        "1,125-minute duration is unchanged.",
        "",
        "The paired intervals use sequence-cluster sandwich uncertainty with "
        "small-group t critical values. The metadata-defined groups and overlapping "
        "training sets limit interpretation. The PIT bands resample sequences and "
        "event counts together; they are descriptive rather than uniformity tests. "
        "Calibration tables also show fixed distance and seen/unseen geographic-site "
        "strata. A geographic repeat does not establish instrument continuity or "
        "transfer to new regions.",
        "",
        "The actual full-exploration curved-mean fit still misses 8 of 15 correlated "
        "conditional predictive checks. The LATA 1,125-minute report remains in the "
        "data, well beyond its fitted-event 90% interval. Source-process flags are not"
        " proof that a value is wrong. Sensitivity analysis must precede any model "
        "selection or specification freeze. This comparison does not recover "
        "historical timestamp pairs or evaluate operational warnings.",
        "",
        "The 19 previously inspected development-check events have not been reopened; "
        "the 18 reserved outcomes remain sealed. No source likelihoods are pooled or "
        "ranked against one another.",
        "",
        "Tables: [model scores](model-scores.csv), [paired "
        "differences](paired-score-differences.csv), [event joint "
        "scores](event-joint-scores.csv), [sequence "
        "influence](sequence-score-influence.csv), [predictive "
        "strata](predictive-calibration-by-stratum.csv), "
        "[PIT](event-weighted-pit.csv).",
        "",
        "Reproduce with `uv run --locked --offline python "
        "scripts/summarize_arrival_curvature_comparison.py --output "
        "<new-project-path>`. The complete independently accepted curvature "
        "continuation is required before any collection. Exact source, native-input "
        "and artifact hashes are in inputs.json and output-checksums.json.",
        "",
    ]
    (output / "findings.md").write_text("\n".join(lines))
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("comparison evidence changed during report")
    write_json(
        output / "output-checksums.json",
        {p.name: sha256(p) for p in output.iterdir() if p.is_file()},
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report(Path(__file__).resolve().parents[1], a.output.resolve())
