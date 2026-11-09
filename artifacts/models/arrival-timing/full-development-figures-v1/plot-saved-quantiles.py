#!/usr/bin/env python3
"""Display accepted, saved native-minute quantiles; never fit or predict.

Actual execution requires Root's all-three-accepted notice plus the literal
FullSCI SHA. Admission refreshes the consumed saved tables, their source metadata,
and the accepted reviews; FullSCI owns the underlying scientific acceptance.
"""

# pyright: basic
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

ART = "artifacts/models/arrival-timing/"
REVIEW = ART + "full-development-v1/review-acceptance.json"
OUTPUT = ART + "full-development-figures-v1"
FIGURE = "selected-model-distance-curves-and-predictive-intervals.png"
GRID = [20.0, 50.0, 100.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0]
SPECS = [
    ("dev-ncei-mean-curvature-selected-full", "NCEI-native-duration", "mean-curvature", 1215, 47),
    ("dev-tobs-pooled-selected-full", "T-OBS", "pooled", 258, 20),
    ("dev-tcal-distance-selected-full", "T-CAL", "distance", 169, 18),
]
FIELDS = [
    "distance_km",
    "curve",
    "q05",
    "q50",
    "q95",
    "support",
    "within_training_distance_range",
    "residual_scale_endpoint_clamped",
]
CAPTION = (
    "Selected source-specific full-development models, using saved native-minute quantiles only. "
    "Dark bands show central 90% pointwise posterior intervals for the population median; "
    "light bands show central 90% pointwise predictive intervals for a new report. "
    "Dots mark saved population-median q50 values at nine distances; connectors and filled "
    "bands join those points and do not add evaluated predictions. "
    "These are not simultaneous bands. "
    "NCEI prediction includes a new event offset plus report variation; the selected T-OBS and "
    "T-CAL forms have no event term. NCEI and T-OBS use logarithmic duration axes; T-CAL uses "
    "signed minutes, where positive means the estimate is later than the observed report. "
    "All distance axes are logarithmic. Hatched regions lie outside the training distance range. "
    "NCEI residual spread is held at its endpoint value below 500 km and above 5,000 km, "
    "which is separate from distance extrapolation. These archive-conditional curves do not "
    "establish calibration, physical-onset accuracy, or operational warning performance."
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scoped(root, name):
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts, "relative input required")
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()), "input escapes root")
    return path


def unchanged(root, pins):
    for name, digest in pins.items():
        require(sha(scoped(root, name)) == digest, f"changed pinned input: {name}")


def normalized(row):
    values = {k: float(row[k]) for k in ["distance_km", "q05", "q50", "q95"]}
    require(all(math.isfinite(x) for x in values.values()), "finite saved quantiles required")
    require(values["q05"] <= values["q50"] <= values["q95"], "ordered quantiles required")
    values.update({k: row[k] for k in ["curve", "support"]})
    for key in ["within_training_distance_range", "residual_scale_endpoint_clamped"]:
        require(type(row[key]) is bool or row[key] in ["True", "False"], "literal flag required")
        values[key] = row[key] is True or row[key] == "True"
    return values


def validate_panel(rows, summary, spec):
    _, target, kind, n, events = spec
    support = summary["support"]
    require(
        summary["target"] == target
        and summary["kind"] == kind
        and summary["native_units"] == "minutes",
        "exact selected target/form/units required",
    )
    require(
        support["records"] == n
        and len(support["event_counts"]) == events
        and sum(support["event_counts"].values()) == n,
        "exact source-specific support required",
    )
    low, high = support["distance_km_min"], support["distance_km_max"]
    require(
        math.isfinite(low) and math.isfinite(high) and 0 < low < high, "distance support required"
    )
    for row in [*rows, *summary["curves"]]:
        require(row.get("quantile_valid") in [True, "True"], "valid saved quantiles required")
        require(
            int(row.get("nonfinite_values", -1)) == 0
            and int(row.get("nonfinite_quantile_values", -1)) == 0,
            "saved nonfinite values must be absent",
        )
        if target != "T-CAL":
            require(
                row.get("native_representable") in [True, "True"],
                "native duration quantiles must be representable",
            )
    clean = [normalized(row) for row in rows]
    keys = [(r["curve"], r["distance_km"]) for r in clean]
    require(
        len(keys) == 18
        and len(set(keys)) == 18
        and set(keys) == {(c, d) for c in ["new_event", "population_median"] for d in GRID},
        "exact two curves at nine saved distances required",
    )
    for row in clean:
        d = row["distance_km"]
        expected = "below" if d < low else "above" if d > high else "within"
        require(
            row["support"] == expected
            and row["within_training_distance_range"] == (expected == "within"),
            "preserve literal distance support flags",
        )
        require(
            row["residual_scale_endpoint_clamped"]
            == (kind == "mean-curvature" and (d < 500 or d > 5000)),
            "preserve residual-scale endpoint flag",
        )
        require(
            target == "T-CAL" or row["q05"] > 0, "positive duration quantiles required for log axes"
        )

    def sortkey(row):
        return row["curve"], row["distance_km"]

    clean.sort(key=sortkey)
    require(
        clean == sorted([normalized(r) for r in summary["curves"]], key=sortkey),
        "saved CSV must equal accepted summary quantiles",
    )
    return dict(rows=clean, support=support, target=target, kind=kind)


def prepare(root, *, all_three_accepted, review_sha256):
    require(all_three_accepted is True, "explicit Root all-three-accepted notice required")
    require(
        re.fullmatch("[0-9a-f]{64}", review_sha256 or "") is not None,
        "literal FullSCI SHA required",
    )
    root = Path(root).resolve()
    review_path = scoped(root, REVIEW)
    require(sha(review_path) == review_sha256, "FullSCI SHA mismatch")
    review = json.loads(review_path.read_text())
    require(
        review.get("status") == "accepted_frozen_full_development_fits"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is True
        and review.get("development_check_previously_inspected") is True
        and review.get("reserved_outcomes") == "sealed"
        and review.get("reserved_outcomes_parsed") is False,
        "accepted FullSCI required",
    )
    jobs = review.get("jobs", [])
    records = review.get("accepted_records", [])
    dispositions = review.get("ordinary_scientific_dispositions", [])
    require(
        len(jobs) == len(records) == len(dispositions) == 3
        and review.get("attempt_records") == records
        and all(
            type(review.get(key)) is int and review[key] == 9
            for key in ["calls_charged", "calls_started", "max_sampler_call_slots"]
        )
        and review.get("source_epoch") == "technical-completion-v2"
        and review.get("proof_contract") == "original_full_development_case_artifacts",
        "exact three current full fits and nine cumulative sampler calls required",
    )
    by_id = {record.get("job_id"): record for record in records}
    science_by_id = {item["job"]["id"]: item for item in dispositions}
    require(
        len(by_id) == len(science_by_id) == 3
        and set(by_id) == set(science_by_id) == {spec[0] for spec in SPECS},
        "unique three actual computation and scientific dispositions required",
    )
    pins = {REVIEW: review_sha256}
    paths = []

    def pinned(name, expected=None):
        digest = review.get("files", {}).get(name)
        require(
            isinstance(digest, str)
            and re.fullmatch("[0-9a-f]{64}", digest) is not None
            and (expected is None or digest == expected),
            "matching FullSCI source SHA required",
        )
        pins[name] = digest
        return digest

    for order, (job, spec) in enumerate(zip(jobs, SPECS, strict=True)):
        jobid, target, kind, _, _ = spec
        require(
            job
            == dict(
                id=jobid,
                model_key=f"{target}:{kind}:selected",
                role="full_development",
                order=order,
                seed=2986110800 + 100 * order,
                training_reference=None,
            ),
            "exact ordered selected full jobs required",
        )
        record, disposition = by_id[jobid], science_by_id[jobid]
        require(
            disposition["job"] == job
            and record.get("producer") == "strict_startup_execution"
            and record.get("producer_epoch") == "technical-completion-v2"
            and record.get("proof_contract") == "original_full_development_case_artifacts"
            and record.get("phase") == record.get("role") == "full_development"
            and record.get("outcome") == "accepted"
            and type(record.get("cost")) is int
            and type(record.get("start_markers")) is int
            and record["cost"] == record["start_markers"] == 1,
            "same accepted strict full computation and scientific job required",
        )
        require(
            isinstance(record.get("files"), dict)
            and record["files"]
            and all(
                review["files"].get(name) == digest for name, digest in record["files"].items()
            ),
            "FullSCI must cover the complete descriptor source map",
        )
        folder = ART + f"full-development-v1/jobs/{jobid}/"
        pair = [folder + name for name in ["curves.csv", "summary.json", "result.json", "job.json"]]
        for name in pair:
            digest = pinned(name)
            require(
                record["files"].get(name) == record.get("worker_files", {}).get(name) == digest,
                "review, actual descriptor and worker proof must pin every saved input",
            )
        receipt = (
            ART
            + "development-check-v1/controller/technical-completion-v1/attempts/"
            + f"full_development/{jobid}.json"
        )
        require(record.get("receipt") == receipt, "literal actual attempt receipt required")
        require(record.get("receipt_sha256") == pinned(receipt), "literal attempt SHA required")
        require(
            disposition.get("review_sha256") == pinned(disposition["review"]),
            "literal scientific disposition SHA required",
        )
        paths.append((pair, receipt, disposition["review"], record, job))
    unchanged(root, pins)  # All saved inputs and receipts before any result-table body read.
    # Metadata lineage first; no native posterior or scientific replay is used.
    for pair, receipt, science_name, record, job in paths:
        raw = json.loads(scoped(root, receipt).read_text())
        require(
            raw
            == {
                k: v
                for k, v in record.items()
                if k not in {"receipt_sha256", "producer_epoch", "proof_contract"}
            },
            "exact actual receipt body with only three derived descriptor fields removed",
        )
        require(
            json.loads(scoped(root, pair[3]).read_text()) == job,
            "saved worker job must equal the accepted selected job",
        )
        result = json.loads(scoped(root, pair[2]).read_text())
        require(
            result.get("job") == job
            and result.get("status") == "computed_pending_scientific_review"
            and result.get("sampler_call_started") is True
            and result.get("confirmation_outcomes_parsed") is True
            and result.get("reserved_outcomes") == "sealed"
            and result.get("diagnostics", {}).get("screen_passed") is True,
            "successful same-job source result required",
        )
        science = json.loads(scoped(root, science_name).read_text())
        require(
            science.get("status") == "accepted_closed_full_development_scientific_checks"
            and science.get("phase") == "full_development"
            and science.get("job") == job
            and science.get("independent_checker") is True
            and science.get("new_sampler_calls_in_QA") == 0
            and science.get("summary", {}).get("passed") is True
            and science.get("numerics", {}).get("passed") is True
            and science.get("visual", {}).get("P0_P1_issues") == 0,
            "same-job independent full-fit numerical/summary/visual acceptance required",
        )
    panels = []
    for (pair, *_), spec in zip(paths, SPECS, strict=True):
        rows = list(csv.DictReader(io.StringIO(scoped(root, pair[0]).read_text())))
        summary = json.loads(scoped(root, pair[1]).read_text())
        panels.append(validate_panel(rows, summary, spec))
    unchanged(root, pins)
    return root, pins, panels


def render(panels, *, synthetic=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator

    require(len(panels) == 3, "three panels required")
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        fig, axes = plt.subplots(3, 1, figsize=(6.25, 11.5), sharex=True)
        fig.subplots_adjust(left=0.16, right=0.97, top=0.805, bottom=0.205, hspace=0.45)
        fig.text(
            0.04,
            0.98,
            "Uncertainty in typical timing and new reports",
            fontsize=13.5,
            weight="bold",
            va="top",
        )
        subtitle = "Central 90% pointwise intervals • log-distance axes"
        if synthetic:
            subtitle = "SYNTHETIC layout • log-distance axes • no fitted results"
        fig.text(0.04, 0.952, subtitle, fontsize=10, va="top")
        handles = [
            Patch(
                facecolor="#d4d4d4",
                edgecolor="#676767",
                linestyle="--",
                label="New-report prediction: 90% interval",
            ),
            Patch(
                facecolor="#5b929a",
                edgecolor="#174e5b",
                label="Population median: 90% posterior interval",
            ),
            Line2D(
                [],
                [],
                color="#174e5b",
                marker="o",
                markersize=3,
                label="Population median: posterior q50",
            ),
        ]
        fig.legend(
            handles=handles,
            loc="upper left",
            bbox_to_anchor=(0.045, 0.925),
            frameon=False,
            fontsize=9.5,
            handlelength=2.5,
            labelspacing=0.7,
        )
        titles = [
            "A  NCEI reported duration",
            "B  T-OBS observed duration",
            "C  T-CAL estimate minus observation",
        ]
        for index, (ax, panel) in enumerate(zip(axes, panels, strict=True)):
            support = panel["support"]
            n, count = support["records"], len(support["event_counts"])
            note = "event offsets" if index == 0 else "no event term"
            ax.set_title(
                f"{titles[index]}\n{n:,} reports • {count} events • {note}",
                loc="left",
                fontsize=10.3,
                pad=10,
            )
            for lo, hi in [(20, support["distance_km_min"]), (support["distance_km_max"], 20000)]:
                lo, hi = max(20, lo), min(20000, hi)
                if lo < hi:
                    ax.axvspan(
                        lo,
                        hi,
                        facecolor="#f6f6f6",
                        edgecolor="#a0a0a0",
                        hatch="///",
                        lw=0,
                        zorder=0,
                    )
            for curve, face, edge, style in [
                ("new_event", "#d4d4d4", "#676767", "--"),
                ("population_median", "#5b929a", "#174e5b", "-"),
            ]:
                r = [v for v in panel["rows"] if v["curve"] == curve]
                x = [v["distance_km"] for v in r]
                ax.fill_between(
                    x,
                    [v["q05"] for v in r],
                    [v["q95"] for v in r],
                    facecolor=face,
                    edgecolor=edge,
                    linewidth=0.8,
                    linestyle=style,
                    zorder=2,
                )
                if curve == "population_median":
                    ax.plot(
                        x,
                        [v["q50"] for v in r],
                        color=edge,
                        linewidth=1.2,
                        marker="o",
                        markersize=3,
                        zorder=3,
                    )
            ax.set_xscale("log")
            ax.set_xlim(20, 20000)
            ax.xaxis.set_minor_locator(NullLocator())
            if index < 2:
                ax.set_yscale("log")
                ax.yaxis.set_major_locator(LogLocator(base=10, numticks=6))
                ax.yaxis.set_minor_locator(NullLocator())
                ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
                ax.set_ylabel("Duration (minutes; log scale)")
            else:
                ax.axhline(0, color="#555555", linewidth=0.8, zorder=1)
                ax.set_ylabel("Signed difference (minutes)")
            ax.grid(axis="y", color="#eeeeee", lw=0.6)
            ax.set_axisbelow(True)
        axes[-1].set_xticks([20, 100, 1000, 10000], ["20", "100", "1,000", "10,000"])
        axes[-1].set_xlabel("Source–station distance (km; log scale)", labelpad=8)
        notes = [
            "Dots are saved distances; connectors add no evaluated predictions.",
            "Hatching: outside the observed distance range for that source.",
            "NCEI spread is held at endpoint values below 500 / above 5,000 km.",
            "NCEI prediction includes new-event and report variation.",
            "T-CAL positive values mean estimated later than observed.",
            "Log-axis decade ticks are tenfold changes; bands are not simultaneous.",
            "Source: accepted NCEI / NTWC models, saved full-development quantiles.",
        ]
        if synthetic:
            notes[-1] = "Source: synthetic layout fixture only; no scientific result claimed."
        for i, line in enumerate(notes):
            fig.text(0.04, 0.137 - i * 0.016, line, fontsize=9.2, color="#444444", va="top")
        return fig


def publish(root, pins, panels, output):
    output = Path(output).resolve()
    require(not output.exists(), "new output folder required; never overwrite evidence")
    require(
        output == root / OUTPUT or output.is_relative_to(Path("/private/tmp")),
        "dedicated public or temporary output only",
    )
    script = Path(__file__).resolve()
    code_hash = sha(script)
    figure = render(panels)
    unchanged(root, pins)
    require(sha(script) == code_hash, "plotter changed before publication")
    output.mkdir(parents=True, exist_ok=False)
    figure.savefig(output / FIGURE, dpi=300, facecolor="white")
    with (output / "plotted-quantiles.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["target", *FIELDS])
        writer.writeheader()
        for panel in panels:
            writer.writerows(dict(target=panel["target"], **row) for row in panel["rows"])
    (output / "plot-saved-quantiles.py").write_bytes(script.read_bytes())
    (output / "caption.md").write_text(CAPTION + "\n")
    metadata = dict(
        status="rendered_pending_independent_visual_review",
        full_review=REVIEW,
        full_review_sha256=pins[REVIEW],
        input_files=pins,
        plotter_sha256=code_hash,
        inputs="accepted saved quantiles only",
        new_predictions_or_scores=False,
        raw_posterior_replayed=False,
        support=[
            dict(
                target=p["target"],
                records=p["support"]["records"],
                events=len(p["support"]["event_counts"]),
            )
            for p in panels
        ],
    )
    (output / "inputs.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    unchanged(root, pins)
    require(sha(script) == code_hash, "plotter changed during publication")
    manifest = {p.name: sha(p) for p in sorted(output.iterdir())}
    (output / "output-checksums.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--all-three-accepted", action="store_true")
    parser.add_argument("--full-review-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root, pins, panels = prepare(
        args.root, all_three_accepted=args.all_three_accepted, review_sha256=args.full_review_sha256
    )
    print(publish(root, pins, panels, args.output or root / OUTPUT))


if __name__ == "__main__":
    main()
