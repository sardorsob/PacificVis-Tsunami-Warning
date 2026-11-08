"""Report independently reviewed whole-sequence validation without opening later splits."""

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
from analysis.arrival.model_sequence_comparison import collect_models  # noqa: E402
from analysis.arrival.model_sequence_tables import comparison_tables  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402

LABELS = {
    "pooled": "Pooled reference",
    "distance": "Distance regression",
    "event": "Event hierarchy",
    "distance-scale": "Hierarchy + varying spread",
}
COLORS = {
    "pooled": "#777777",
    "distance": "#5B8FA8",
    "event": "#C17931",
    "distance-scale": "#286B55",
}
TARGETS = ["NCEI-native-duration", "T-OBS", "T-CAL"]


def figures(tables, output):
    plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(3, 1, figsize=(8, 15), layout="constrained")
    for ax, target in zip(axes, TARGETS, strict=True):
        pairs = [r for r in tables["paired-score-differences"] if r["target"] == target]
        labels = []
        for j, r in enumerate(pairs):
            mid = r["paired_mean_difference"]
            ax.errorbar(
                mid,
                j,
                xerr=[
                    [mid - r["sequence_cluster_ci95_lower"]],
                    [r["sequence_cluster_ci95_upper"] - mid],
                ],
                fmt="o",
                color=COLORS[r["first_model"]],
                capsize=3,
            )
            labels.append(f"{LABELS[r['first_model']]}\nminus {LABELS[r['second_model']]}")
        ax.axvline(0, color="#777777", linewidth=0.8, linestyle="--")
        ax.set(
            yticks=range(len(pairs)),
            yticklabels=labels,
            title=target,
            xlabel="Paired difference (nats per report)",
        )
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.2)
    fig.suptitle("Model gains depend on source and sequence", fontsize=18)
    fig.supxlabel(
        "Equal-event mean; descriptive 95% sequence-cluster intervals.\n"
        "Positive favors the first model.\n"
        "Sources: NCEI / NTWC exploration; whole sequences withheld.",
        fontsize=11,
    )
    for suffix in ["png", "svg"]:
        fig.savefig(output / f"paired-sequence-score-differences.{suffix}", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(8, 15), layout="constrained")
    styles = {"pooled": ":", "distance": "--", "event": "-.", "distance-scale": "-"}
    for ax, target in zip(axes, TARGETS, strict=True):
        rows = [
            r
            for r in tables["event-weighted-pit"]
            if r["target"] == target and r["stratum"] == "all"
        ]
        for kind in LABELS:
            group = [r for r in rows if r["model"] == kind]
            if not group:
                continue
            x = np.array([r["pit_probability"] for r in group])
            y = np.array([r["equal_event_cdf"] for r in group])
            ax.plot(
                x, y, label=LABELS[kind], color=COLORS[kind], linestyle=styles[kind], linewidth=1.8
            )
            # One band per panel avoids hiding the other model curves; it is not a test.
            bandkind = "distance-scale" if target == "NCEI-native-duration" else "event"
            if kind == bandkind:
                radius = float(group[0]["bootstrap_supnorm_radius95"])
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
            title=target,
            xlabel="Predictive probability",
            ylabel="Equal-event empirical CDF",
            aspect="equal",
        )
        ax.legend(loc="center left", bbox_to_anchor=(1.03, 0.5), fontsize=12, frameon=False)
    fig.suptitle("Held-sequence calibration remains a model check", fontsize=18)
    fig.supxlabel(
        "Marginal PIT; shaded 95% sequence-bootstrap sup-norm bands:\n"
        "varying spread (NCEI) or event hierarchy (NTWC).\n"
        "Heuristic groups and overlapping training limit interpretation.\n"
        "Descriptive bands, not uniformity tests. Sources: NCEI / NTWC.",
        fontsize=12,
    )
    for suffix in ["png", "svg"]:
        fig.savefig(output / f"held-sequence-predictive-calibration.{suffix}", dpi=160)
    plt.close(fig)


def report(root, output):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local comparison report required")
    models, pins = collect_models(root)
    tables = comparison_tables(models)
    code = [
        "scripts/summarize_arrival_sequence_validation.py",
        "analysis/arrival/model_sequence_comparison.py",
        "analysis/arrival/model_sequence_tables.py",
        "analysis/arrival/model_sequence_report.py",
        "analysis/arrival/model_comparison.py",
    ]
    pins.update({p: sha256(root / p) for p in code})
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "selection": "none; completed exploration comparisons and predictive criticism only",
            "reserved_outcomes": "sealed",
            "confirmation_outcomes_parsed": False,
            "pit_bootstrap_replicates": 2000,
            "pit_bootstrap_seed": 25261108,
        },
    )
    for name, rows in tables.items():
        write_table(
            output / f"{name}.csv",
            [{k: ("not_applicable" if v is None else v) for k, v in r.items()} for r in rows],
        )
    figures(tables, output)
    lines = [
        "# Whole-sequence predictive comparison",
        "",
        "These exploration comparisons predict reported timings for sequences "
        "excluded from training. "
        "Each event contributes its joint native-minute log predictive density "
        "divided by its number "
        "of reports; events then receive equal weight. Higher scores indicate better prediction "
        "within the same source and evidence cohort.",
        "",
        "For both duration targets, every comparator already contains the fixed "
        "distance-based reference t0(d). Distance regression adds a learned log-distance "
        "adjustment; the event hierarchy adds partially pooled event offsets. The pooled "
        "T-CAL comparator has a constant signed-minute mean.",
        "",
        "| Source | Model | Reports | Events | Equal-event score | Monte Carlo SE |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in sorted(
        tables["model-scores"],
        key=lambda r: (TARGETS.index(r["target"]), list(LABELS).index(r["model"])),
    ):
        se = (
            "not applicable"
            if r["monte_carlo_standard_error"] is None
            else f"{r['monte_carlo_standard_error']:.6f}"
        )
        lines.append(
            f"| {r['target']} | {LABELS[r['model']]} | {r['records']} | {r['events']} | "
            f"{r['equal_event_score']:.6f} | {se} |"
        )

    def contrast(target, first, second):
        return next(
            r
            for r in tables["paired-score-differences"]
            if (r["target"], r["first_model"], r["second_model"]) == (target, first, second)
        )

    primary = contrast("NCEI-native-duration", "distance-scale", "event")
    influence = [
        r
        for r in tables["sequence-score-influence"]
        if (r["target"], r["first_model"], r["second_model"])
        == ("NCEI-native-duration", "distance-scale", "event")
    ]
    leading = max(
        influence,
        key=lambda r: abs(r["mean_difference_without_cluster"] - primary["paired_mean_difference"]),
    )
    contribution = leading["difference_sum"] / primary["events"]
    observed = contrast("T-OBS", "event", "pooled")
    calibration = contrast("T-CAL", "event", "distance")
    near = next(
        r
        for r in tables["predictive-calibration-by-stratum"]
        if (r["target"], r["model"], r["stratum"])
        == ("NCEI-native-duration", "distance-scale", "under-500km")
    )
    lines += [
        "",
        f"For NCEI durations, varying spread has the highest score among these four models. "
        f"Its paired gain over constant-spread hierarchy is "
        f"{primary['paired_mean_difference']:.3f} "
        f"nats/report, with a descriptive 95% sequence interval "
        f"[{primary['sequence_cluster_ci95_lower']:.3f}, "
        f"{primary['sequence_cluster_ci95_upper']:.3f}]. "
        "This interval does not establish a clear advantage over that hierarchy.",
        "",
        f"Sequence `{leading['sequence']}` contains {leading['events']} events and contributes "
        f"{contribution:.3f} nats/report to that "
        f"{primary['paired_mean_difference']:.3f} mean gain. "
        f"Re-averaging the other {primary['events'] - leading['events']} event scores gives "
        f"{leading['mean_difference_without_cluster']:.3f}. This deletes score contributions only: "
        "the other models were not refitted without this sequence. Source-field and whole-sequence "
        "sensitivity checks remain necessary before selection.",
        "",
        f"For reports under 500 km, the varying-spread model's equal-event 90% coverage estimate "
        f"is {near['equal_event_coverage90']:.1%} across {near['events']} events. "
        f"Together with the "
        "earlier conditional predictive discrepancies, this motivates the bounded mean-form "
        "revisit; broad overall coverage alone would hide this stratum.",
        "",
        f"For NTWC observed durations, hierarchy minus pooled reference is "
        f"{observed['paired_mean_difference']:.3f} "
        f"[{observed['sequence_cluster_ci95_lower']:.3f}, "
        f"{observed['sequence_cluster_ci95_upper']:.3f}]. "
        f"For signed timing differences, hierarchy minus distance regression is "
        f"{calibration['paired_mean_difference']:.3f} "
        f"[{calibration['sequence_cluster_ci95_lower']:.3f}, "
        f"{calibration['sequence_cluster_ci95_upper']:.3f}]. "
        "Neither establishes a clear predictive gain. No specification is selected here.",
    ]
    lines += [
        "",
        "![Paired score differences and descriptive sequence-cluster "
        "intervals](paired-sequence-score-differences.png)",
        "",
        "Scores from different sources have different response definitions and cannot be ranked "
        "against one another. T-OBS is observed UTC minus reviewed earthquake origin in minutes. "
        "T-CAL is estimated UTC minus observed UTC in signed minutes. The two share the "
        "observed clock and remain separate analyses. "
        "NCEI durations retain their native reported definition; no common "
        "physical onset is assumed.",
        "",
        "The paired table reports each model difference with a descriptive sequence-cluster "
        "sandwich standard error and a 95% t interval. The small, metadata-defined sequence groups "
        "and overlapping training sets limit their interpretation. Numerical Monte Carlo errors "
        "and deterministic integration error estimates are recorded separately. The latter are "
        "refinement diagnostics, not rigorous error bounds. A 0.01-nat reporting yardstick does "
        "not define a model-promotion rule or a Bayes factor.",
        "",
        "![Event-weighted held-sequence PIT calibration "
        "curves](held-sequence-predictive-calibration.png)",
        "",
        "Calibration tables give both record-weighted summaries and equal-event averages. "
        "Distances use fixed 500, 2,000 and 5,000 km cut points. Seen geographic sites need not "
        "be continuous instrument deployments; unseen-site performance does not establish "
        "transfer to new regions. Interval widths and absolute errors are in native minutes. "
        "The PIT sequence bootstrap resamples sequence totals and event counts together. Its "
        "bands are descriptive and conditional on the retained predictions, not uniformity tests.",
        "",
        "Sequence influence rows remove score contributions without refitting models. They "
        "complement the later explicit influential-event refits. Full-exploration posterior "
        "predictive checks and sensitivity analysis remain necessary before "
        "any specification freeze.",
        "",
        "The 19 previously inspected EDA confirmation events have not been reopened here; the "
        "18 reserved outcomes remain sealed. These comparisons do not establish operational "
        "warning accuracy, missing timestamp recovery or independent transport to new eras.",
        "",
        "Reproduce with `uv run --locked --offline python "
        "scripts/summarize_arrival_sequence_validation.py --output <new-project-path>`. "
        "The command requires all 83 logical sequence calculations and their independent "
        "acceptance receipt. Exact inputs and output hashes accompany this report.",
        "",
        "Tables: [model scores](model-scores.csv), [paired "
        "differences](paired-score-differences.csv), "
        "[event joint scores](event-joint-scores.csv), [sequence "
        "influence](sequence-score-influence.csv), "
        "[predictive strata](predictive-calibration-by-stratum.csv), "
        "[event-weighted PIT](event-weighted-pit.csv).",
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report(Path(__file__).resolve().parents[1], args.output.resolve())
