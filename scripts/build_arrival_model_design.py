"""Exploration-only design checks and hypothetical scale translations; no model fit."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tomllib
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path
from statistics import NormalDist
from typing import Any, cast

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import Row, read_rows, sha256, write_json, write_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE = "artifacts/eda/arrival-timing/results/exploration/"
INPUTS = {
    BASE + "data-integrity-and-response-records/ntwc-reported-travel-duration-analysis-records.csv":
        "106d6bacbd73497373ef7019f7397b50e41cc6cf67a9dca6573b75ff241f37c6",
    BASE + "data-integrity-and-response-records/ncei-native-travel-duration-analysis-records.csv":
        "8aa7ed2227b68b4a7c9dbf0cfe13439770415d1906ecd234c6e2abab20caf72e",
    BASE + "estimated-minus-observed-timing-distributions/"
    "estimated-minus-observed-time-difference-versus-source-station-distance.csv":
        "1bbd3af184b9dc1ca37027000121e6d404d579f85269a3568325ecfdba00b4e2",
    "config/arrival-timing-exploration-confirmation-split.toml":
        "4f3d3ae8ba5f96d5a701508e5c65c5979f8938f1959d17cfb14be4dbab800328",
}
LABELS = {"T-OBS": "NTWC duration", "NCEI-native-duration": "NCEI duration",
          "T-CAL": "Estimate − observation"}


def design_checks(rows: list[Row]) -> tuple[dict[str, Any], list[Row], list[Row]]:
    """Count structural contrasts and decompose log distance without fitting outcomes."""
    if not rows or len({r["record_id"] for r in rows}) != len(rows):
        raise ValueError("require nonempty rows with unique source-record IDs")
    for row in rows:
        if row["event_id"] in {"", "unknown"} or row["physical_site_id"] in {"", "unknown"}:
            raise ValueError("unknown event/site identity must not become a pooled group")
        if not math.isfinite(float(row["distance_km"])) or float(row["distance_km"]) <= 0:
            raise ValueError("log-distance requires finite positive distance")
    events = sorted({r["event_id"] for r in rows})
    sites = sorted({r["physical_site_id"] for r in rows})
    edges = {(r["event_id"], r["physical_site_id"]) for r in rows}
    adjacent: dict[str, set[str]] = defaultdict(set)
    for event, site in edges:
        a, b = "event:" + event, "site:" + site
        adjacent[a].add(b)
        adjacent[b].add(a)
    remaining = set(adjacent)
    components = 0
    while remaining:
        pending = [remaining.pop()]
        components += 1
        while pending:
            unseen = adjacent[pending.pop()] & remaining
            remaining -= unseen
            pending.extend(unseen)
    rank = len(events) + len(sites) - components
    x = np.log(np.array([float(r["distance_km"]) / 1000 for r in rows]))
    grand = float(x.mean())
    total_ss = float(np.sum((x - grand) ** 2))
    within_ss = 0.0
    folds: list[Row] = []
    for event in events:
        indices = [i for i, r in enumerate(rows) if r["event_id"] == event]
        subset = x[indices]
        within_ss += float(np.sum((subset - subset.mean()) ** 2))
        other_sites = {s for e, s in edges if e != event}
        seen = sum(rows[i]["physical_site_id"] in other_sites for i in indices)
        folds.append({"event_id": event, "rows": str(len(indices)),
                      "seen_site_rows": str(seen), "unseen_site_rows": str(len(indices)-seen),
                      "seen_site_fraction": str(seen / len(indices)),
                      "mean_log_distance_over_1000km": str(float(subset.mean())),
                      "log_distance_range": str(float(np.ptp(subset)))})
    aliases: list[Row] = []
    for field in ["magnitude", "depth_km", "era", "region", "mechanism", "header_family"]:
        varying = sum(len({r[field] for r in rows if r["event_id"] == e}) > 1 for e in events)
        unknown = sum(r[field] in {"unknown", ""} for r in rows)
        aliases.append({"field": field, "events_with_within_event_variation": str(varying),
                        "unknown_rows": str(unknown),
                        "aliased_with_unrestricted_event_intercepts": str(varying == 0),
                        "interpretation": "structural design only; missing is not a numeric value"})
    summary = {
        "rows": len(rows), "events": len(events), "sites": len(sites),
        "unique_event_site_edges": len(edges), "repeated_edge_rows": len(rows)-len(edges),
        "components": components, "additive_indicator_rank": rank,
        "unique_edge_cycle_surplus": len(edges)-rank, "row_surplus_over_rank": len(rows)-rank,
        "log_distance_total_ss": total_ss, "log_distance_within_event_ss": within_ss,
        "log_distance_between_event_ss": total_ss-within_ss,
        "within_event_log_distance_fraction": within_ss/total_ss if total_ss else None,
        "row_weighted_seen_site_fraction": sum(int(f["seen_site_rows"]) for f in folds)/len(rows),
        "event_weighted_seen_site_fraction": sum(float(f["seen_site_fraction"]) for f in folds)
            / len(events),
        "events_with_zero_seen_sites": sum(int(f["seen_site_rows"]) == 0 for f in folds),
    }
    return summary, folds, aliases


def scale_scenarios() -> list[Row]:
    """Translate specified normal log-spreads; these numbers are not elicited priors."""
    z = NormalDist().inv_cdf(0.95)
    return [{"assumed_log_sd": str(s), "median_ratio": "1.0",
             "central_90_lower_ratio": str(math.exp(-z*s)),
             "central_90_upper_ratio": str(math.exp(z*s)),
             "conditional_mean_over_median": str(math.exp(s*s/2)),
             "status": "illustrative fixed conditional spread; not a prior or estimate"}
            for s in [0.1, 0.25, 0.5, 1.0]]


def draw_support(summary: dict[str, Any], output: Path) -> None:
    """Plot seen-site support under event deletion, with explicit row/event weighting."""
    plt.rcParams.update({"font.size": 12, "svg.hashsalt": "arrival-model-design"})
    figure, axes = plt.subplots(figsize=(8, 6.5))
    fig, ax = cast(Any, figure), cast(Any, axes)
    y = np.arange(len(summary))
    ax.barh(y+0.16, [summary[t]["row_weighted_seen_site_fraction"]*100 for t in summary],
            height=0.27, color="#286989", label="Each row weighted equally")
    ax.barh(y-0.16, [summary[t]["event_weighted_seen_site_fraction"]*100 for t in summary],
            height=0.27, color="#777777", label="Each held-out event weighted equally")
    ax.set_yticks(y, [f"{LABELS[t]}\n{summary[t]['events']} events; {summary[t]['rows']} rows"
                     for t in summary])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Held-out rows at sites seen in other exploration events (%)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), fontsize=12)
    fig.suptitle("New events require predictions\nat both seen and unseen sites", fontsize=15)
    fig.text(0.02, 0.025, "Source: frozen NTWC/NCEI exploration tables. Geographic sites;\n"
             "deployment and physical-sequence validity remain unverified.", fontsize=12)
    fig.tight_layout(rect=(0, 0.14, 1, 0.84))
    fig.savefig(output / "event-holdout-seen-site-support.png", dpi=160)
    fig.savefig(output / "event-holdout-seen-site-support.svg", metadata={"Date": None})
    plt.close(fig)


def build(output: Path) -> None:
    """Verify frozen exploration bytes before reading; refuse output replacement."""
    if output.exists():
        raise ValueError("output already exists; use a fresh directory for replay")
    for relative, digest in INPUTS.items():
        if sha256(ROOT / relative) != digest:
            raise ValueError(f"frozen exploration input changed: {relative}")
    split = tomllib.loads((ROOT / list(INPUTS)[-1]).read_text(encoding="utf-8"))
    frames = [read_rows(ROOT / p) for p in INPUTS if p.endswith(".csv")]
    if any(r["event_id"] not in split["exploration"] for rows in frames for r in rows):
        raise ValueError("non-exploration event found; do not read further outcomes")
    summaries: dict[str, Any] = {}
    all_folds: list[Row] = []
    all_aliases: list[Row] = []
    for rows in frames:
        target = rows[0]["target"]
        summary, folds, aliases = design_checks(rows)
        summaries[target] = summary
        all_folds.extend({"target": target, **f} for f in folds)
        all_aliases.extend({"target": target, **a} for a in aliases)
    output.mkdir(parents=True)
    write_rows(output / "event-station-contrast-support.csv",
               [{"target": t, **{k: str(v) for k, v in s.items()}} for t, s in summaries.items()])
    write_rows(output / "event-holdout-seen-site-support.csv", all_folds)
    write_rows(output / "event-intercept-covariate-aliases.csv", all_aliases)
    write_rows(output / "hypothetical-log-scale-translation.csv", scale_scenarios())
    clock_rows: list[Row] = []
    for rows in frames[:2]:
        durations = [float(r["target_minutes"]) for r in rows]
        for half_width in [0.5, 1.0, 5.0]:
            clock_rows.append({"target": rows[0]["target"], "assumed_half_width_minutes":
                               str(half_width), "rows": str(len(rows)),
                               "rows_at_or_below_half_width":
                               str(sum(t <= half_width for t in durations)),
                               "rows_with_half_width_at_least_10pct_of_duration":
                               str(sum(half_width/t >= 0.1 for t in durations)),
                               "status": "hypothetical observation window; no accuracy inferred"})
    write_rows(output / "hypothetical-clock-width-sensitivity.csv", clock_rows)
    draw_support(summaries, output)
    write_json(output / "analysis-metrics.json", summaries)
    write_json(output / "analysis-settings.json", {
        "scope": "posthoc exploration-only structural design; no outcome regression or fits",
        "site_key": "physical_site_id", "distance_transform": "ln(distance_km / 1000)",
        "scenarios_are_priors": False, "confirmation_read": False, "reserved_outcomes_read": False,
        "clock_half_width_minutes": [0.5, 1, 5], "log_sd_scenarios": [0.1, 0.25, 0.5, 1],
    })
    write_json(output / "random-seeds.json", {"randomness": "none; deterministic calculations"})
    code = ["scripts/build_arrival_model_design.py", "analysis/arrival/evidence.py"]
    write_json(output / "input-and-code-checksums.json", {
        "inputs": INPUTS, "code": {p: sha256(ROOT / p) for p in code},
    })
    write_json(output / "run-metadata.json", {
        "base_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                 text=True).strip(),
        "code_identity": "input-and-code-checksums.json; code may be uncommitted at execution",
        "python": sys.version.split()[0],
        "packages": {p: version(p) for p in ["numpy", "matplotlib", "mlflow-skinny"]},
        "disposition": "pre-model design evidence; no candidate selected or fitted",
    })
    lines = ["# Exploration design: what the model can learn", "",
             "These posthoc checks describe the accepted exploration design. They do not",
             "estimate Bayesian parameters or repeat the frozen confirmation analysis.", "",
             "| Response | Rows | Events | Sites | Components | Unique edges | Cycle surplus |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for t, s in summaries.items():
        lines.append(f"| {LABELS[t]} | {s['rows']} | {s['events']} | {s['sites']} | "
                     f"{s['components']} | {s['unique_event_site_edges']} | "
                     f"{s['unique_edge_cycle_surplus']} |")
    lines += ["", "Cycle surplus = unique edges − events − sites + connected components.",
              "It counts redundant contrasts for an unrestricted additive event/site design;",
              "it is neither posterior effective sample size nor a variance-identification test.",
              "Repeated rows on an edge do not establish independent replicate measurements.", "",
              "| Response | Within-event fraction of log-distance variation | Seen-site fraction,"
              " row weighted | Seen-site fraction, event weighted |",
              "| --- | ---: | ---: | ---: |"]
    for t, s in summaries.items():
        lines.append(f"| {LABELS[t]} | {s['within_event_log_distance_fraction']:.1%} | "
                     f"{s['row_weighted_seen_site_fraction']:.1%} | "
                     f"{s['event_weighted_seen_site_fraction']:.1%} |")
    lines += ["", "Log-distance variation decomposes exactly into within-event and row-weighted",
              "between-event sums of squares. This measures predictor support,",
              "not a response slope.",
              "Event deletion here is a design check, not cross-validation",
              "or a physical-sequence split.",
              "", "![Seen-site support](event-holdout-seen-site-support.png)", "",
              "[Model meanings, assumptions and next checks](../../../../docs/research/"
              "bayesian-model-readiness.md) explain inference limits and candidate progression.",
              "Scenario CSVs contain deliberately assumed scales, not selected priors or known",
              "clock accuracy. All rows stay in their original analysis views.", ""]
    (output / "design-findings.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(output / "output-file-checksums.json", [
        {"path": p.name, "sha256": sha256(p)} for p in sorted(output.iterdir()) if p.is_file()
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output.resolve())
