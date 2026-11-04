"""Run one frozen descriptive EDA question on one declared event split."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import (  # noqa: E402
    file_manifest,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)
from analysis.arrival.timing_artifact_names import (  # noqa: E402
    CODE_FILES,
    artifact_filename,
    question_directory,
    rename_bundle_files,
)
from analysis.arrival.timing_data_and_descriptive_statistics import (  # noqa: E402
    DISTANCE_BINS,
    Record,
    bootstrap_median,
    grouped,
    load_frames,
    number,
    summarize,
    support,
)
from analysis.arrival.timing_diagnostic_plots import draw  # noqa: E402


def clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "unknown"
    if isinstance(value, dict):
        return {k: clean(v) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [clean(v) for v in cast(list[Any], value)]
    return value


def csv(path: Path, rows: list[Record]) -> None:
    fields = sorted({k for r in rows for k in r})
    converted = [
        {
            k: json.dumps(r[k], sort_keys=True)
            if isinstance(r.get(k), (list, dict))
            else "unknown"
            if r.get(k) is None or isinstance(r.get(k), float) and not math.isfinite(r[k])
            else str(r.get(k, "unknown"))
            for k in fields
        }
        for r in rows
    ]
    write_rows(path, converted)


def core(
    frames: dict[str, list[Record]], availability: list[Record], module: str, out: Path, split: str
) -> Record:
    results: Record = {}
    targets = ["T-CAL"] if module == "C8" else ["T-OBS", "NCEI-native-duration"]
    for target in targets:
        rows = frames[target]
        prefix = out / target
        csv(prefix.with_suffix(".csv"), rows) if module == "C1" else None
        if module == "C1":
            findings = [
                r | {"finding": "nonpositive_or_subminute_duration"}
                for r in rows
                if r["target_minutes"] < 1
            ]
            findings.extend(
                r | {"finding": "source_definition_comparison_unapproved"}
                for r in rows
                if r.get("definition_conflict_candidate") == "True"
            )
            csv(out / f"{target}-data-findings.csv", findings)
            counts = [
                {"x": i, "label": e, "y": sum(r["event_id"] == e for r in rows)}
                for i, e in enumerate(sorted({r["event_id"] for r in rows}))
            ]
            figure(
                out,
                f"{target}-event-counts",
                counts,
                "bar",
                "x",
                "y",
                f"{target}: records per event",
                "Event (IDs in CSV)",
                "Retained records",
                split,
            )
            results[target] = support(rows) | {
                "findings": len(findings),
                "unknown_distance": sum(not math.isfinite(r["distance_km"]) for r in rows),
                "origin_difference_seconds": summarize(
                    [r["origin_difference_seconds"] for r in rows]
                ),
                "precision": grouped(rows, "precision_seconds", "target_minutes"),
            }
        elif module in {"C2", "C8"}:
            values = [r["target_minutes"] for r in rows]
            logs = [math.log(v) for v in values if v > 0] if module == "C2" else values
            edges = np.linspace(-5, 9, 29) if module == "C2" else np.linspace(-240, 60, 31)
            freq, _ = np.histogram(logs, bins=edges)
            hist = [
                {"x": float((a + b) / 2), "y": int(n), "bin_left": float(a), "bin_right": float(b)}
                for a, b, n in zip(edges[:-1], edges[1:], freq, strict=True)
            ]
            figure(
                out,
                f"{target}-distribution",
                hist,
                "bar",
                "x",
                "y",
                f"{target}: {'log duration' if module == 'C2' else 'signed E − O'}",
                "ln(duration / minute)" if module == "C2" else "Estimated − observed (minutes)",
                "Records in bin",
                split,
            )
            from statistics import NormalDist

            qq = [
                {"x": NormalDist().inv_cdf((i + 0.5) / len(logs)), "y": float(v)}
                for i, v in enumerate(sorted(logs))
            ]
            figure(
                out,
                f"{target}-qq",
                qq,
                "scatter",
                "x",
                "y",
                f"{target}: descriptive QQ",
                "Standard normal quantile (no fitted line)",
                "ln(duration / minute)" if module == "C2" else "E − O (minutes)",
                split,
            )
            results[target] = summarize(values) | {
                "nonpositive": sum(v <= 0 for v in values),
                "native_clock_second_summary": summarize(
                    [r["observed_clock_second"] for r in rows]
                ),
                "integer_minute_share": sum(abs(v - round(v)) < 1e-6 for v in values) / len(values)
                if values
                else math.nan,
                "outside_fixed_histogram": len(logs) - int(sum(freq)),
                "negative_share": sum(v < 0 for v in values) / len(values) if values else math.nan,
            }
            if module == "C8":
                for key in ["event_id", "era", "header_family"]:
                    stratified = grouped(rows, key, "target_minutes")
                    csv(out / f"T-CAL-by-{key}.csv", stratified)
                    results[target]["by-" + key] = stratified
                figure(
                    out,
                    f"{target}-distance",
                    rows,
                    "scatter",
                    "distance_km",
                    "target_minutes",
                    "T-CAL: signed timing difference versus distance",
                    "Geodesic distance (km)",
                    "Estimated − observed (minutes)",
                    split,
                )
        elif module == "C3":
            bins: list[Record] = []
            for lo, hi in zip(DISTANCE_BINS[:-1], DISTANCE_BINS[1:], strict=True):
                own = [r for r in rows if lo <= r["distance_km"] < hi]
                low, high = bootstrap_median(own, "r0", 500, 20261103)
                bins.append(
                    {
                        "x": (lo + hi) / 2,
                        "y": summarize([r["r0"] for r in own])["median"],
                        "low_km": lo,
                        "high_km": hi,
                        "rows": len(own),
                        "events": len({r["event_id"] for r in own}),
                        "ci_low": low,
                        "ci_high": high,
                        **summarize([r["r0"] for r in own]),
                    }
                )
            figure(
                out,
                f"{target}-physics-bins",
                bins,
                "line",
                "x",
                "y",
                f"{target}: departures from fixed depth reference",
                "Geodesic distance (km)",
                "r₀ = ln(observed / reference duration)",
                split,
            )
            figure(
                out,
                f"{target}-physics",
                rows,
                "physics",
                "distance_km",
                "target_minutes",
                f"{target}: duration and a fixed physics reference",
                "Geodesic distance (km; log scale)",
                "Duration (minutes; log scale)",
                split,
            )
            results[target] = {
                "r0": summarize([r["r0"] for r in rows]),
                "bins": bins,
                "near": summarize([r["r0"] for r in rows if r["distance_km"] < 500]),
                "far": summarize([r["r0"] for r in rows if r["distance_km"] >= 500]),
            }
        else:
            raise ValueError("module not implemented")
    return results


def figure(
    out: Path,
    name: str,
    rows: list[Record],
    kind: str,
    x: str,
    y: str,
    title: str,
    xlabel: str,
    ylabel: str,
    split: str,
) -> None:
    csv(out / f"{name}.csv", rows)
    draw(
        out / name,
        rows,
        kind=kind,
        x=x,
        y=y,
        title=title,
        xlabel=xlabel,
        ylabel=ylabel,
        split=split,
    )


def run(
    root: Path,
    split: str,
    module: str,
    output: Path,
    git_sha: str | None = None,
    replay: bool = False,
) -> None:
    if module not in {f"C{i}" for i in range(1, 10)} | {f"B{i}" for i in range(1, 12)}:
        raise ValueError("unknown EDA question")
    if output.exists():
        raise FileExistsError(output)
    input_path = root / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
    frozen = verify_inputs(input_path, expected_schema="paper_eda_inputs_v1")
    settings = tomllib.loads(
        (root / "config/arrival-timing-exploration-confirmation-split.toml").read_text()
    )
    pins = {p: sha256(root / p) for p in CODE_FILES}
    reference: Path | None = None
    lock: Record = {}
    core_root = output.parent.parent
    if split == "confirmation" or replay:
        lock = json.loads(
            (root / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json").read_text()
        )
        if lock.get("layout_replay_code", lock["code"]) != pins or lock["inputs_sha256"] != sha256(
            input_path
        ):
            raise ValueError("frozen analysis code or config drift")
        if split == "confirmation" and module not in lock["questions"]:
            raise ValueError("confirmation question not selected in the frozen lock")
        canonical = question_directory(Path(lock["artifact_root"]), split, module)
        if replay:
            if not canonical.is_dir():
                raise ValueError("replay requires an existing canonical EDA bundle")
            reference = canonical
            core_root = Path(lock["artifact_root"])
            if "layout_replay_code" in lock:
                for name, digest in lock["generation_metadata_sha256"][f"{split}:{module}"].items():
                    if sha256(canonical / name) != digest:
                        raise ValueError("original generation metadata changed")
            git_sha = json.loads((canonical / artifact_filename("meta.json")).read_text())[
                "git_sha"
            ]
        elif output.resolve() != canonical.resolve():
            raise ValueError("confirmation question must use its single canonical output path")
    frames, availability = load_frames(root, frozen, settings[split])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / "bundle"
        stage.mkdir()
        if module in {"C1", "C2", "C3", "C8"}:
            result = core(frames, availability, module, stage, split)
        else:
            from analysis.arrival.timing_group_reporting_and_support_diagnostics import diagnostics

            if module.startswith("B"):
                from analysis.arrival.timing_followup_diagnostics import branches

                core_results = {
                    m: json.loads(
                        (
                            question_directory(core_root, split, m)
                            / artifact_filename("summary.json")
                        ).read_text()
                    )
                    for m in ["C3", "C4", "C5", "C6", "C7", "C8"]
                }
                if split == "confirmation":
                    core_results["_routes"] = lock["routes"]
                result, tables = branches(frames, core_results, module)
            else:
                result, tables = diagnostics(frames, availability, module)
            for name, table in tables.items():
                csv(stage / f"{name}.csv", table)
            if module == "C4":
                for target in ["T-OBS", "NCEI-native-duration"]:
                    data = tables[target + "-physical_site_id-effects"]
                    for kind in ["event", "site"]:
                        values = [r for r in data if r["kind"] == kind and r["component"] == 0]
                        chart = [r | {"x": i, "y": r["effect"]} for i, r in enumerate(values)]
                        figure(
                            stage,
                            target + "-" + kind + "-effects",
                            chart,
                            "scatter",
                            "x",
                            "y",
                            target + ": component-relative " + kind + " effects",
                            "Group index (IDs in CSV)",
                            "Effect on ln(duration / reference)",
                            split,
                        )
            elif module == "C5":
                data = tables["linked-geographic-comparisons"]
                chart = [r | {"x": i, "y": r["difference_minutes"]} for i, r in enumerate(data)]
                figure(
                    stage,
                    "linked-differences",
                    chart,
                    "scatter",
                    "x",
                    "y",
                    "Shared geographic sites: separate-source comparisons",
                    "Comparison index",
                    "NTWC − native NCEI duration (minutes)",
                    split,
                )
                sensitivity = tables["posthoc-P1-colocation-comparisons"]
                chart2 = [
                    r | {"x": i, "y": r["difference_minutes"]} for i, r in enumerate(sensitivity)
                ]
                figure(
                    stage,
                    "posthoc-P1-differences",
                    chart2,
                    "scatter",
                    "x",
                    "y",
                    "Unapproved same-name, bounded 2 km comparisons",
                    "Comparison index",
                    "NTWC − native NCEI duration (minutes)",
                    split,
                )
            elif module == "C6":
                data = tables["availability-era"]
                chart = [r | {"x": i, "y": r["availability"]} for i, r in enumerate(data)]
                figure(
                    stage,
                    "availability-era",
                    chart,
                    "scatter",
                    "x",
                    "y",
                    "Exact observation availability by product era",
                    "Source era",
                    "Exact observations / accepted rows",
                    split,
                )
            elif module in {"C7", "C9"}:
                for target in (
                    ["T-OBS", "NCEI-native-duration", "T-CAL"]
                    if module == "C9"
                    else ["T-OBS", "NCEI-native-duration"]
                ):
                    if module == "C7":
                        data = tables[target + "-leave-one-event-out"]
                        chart = [r | {"x": i, "y": r["median_r0"]} for i, r in enumerate(data)]
                    else:
                        chart = [
                            {
                                "x": n,
                                "y": result[target][f"sites_at_least_{n}_events"],
                                "caption": str(result[target]["sites"])
                                + " sites; nested repeat thresholds",
                            }
                            for n in [2, 3, 5]
                        ]
                    figure(
                        stage,
                        target + "-" + module,
                        chart,
                        "scatter" if module == "C7" else "bar",
                        "x",
                        "y",
                        target
                        + (
                            ": leave-one-event-out median"
                            if module == "C7"
                            else ": repeated site support"
                        ),
                        "Held-out event index"
                        if module == "C7"
                        else "Minimum observed events per site",
                        "Median r₀" if module == "C7" else "Sites",
                        split,
                    )
            elif module.startswith("B"):
                chart = [
                    {
                        "x": i,
                        "y": number(result[t]["scalar"]),
                        "target": t,
                        "comparison_label": t
                        + (
                            "\ncoastal − DART"
                            if module == "B6"
                            and result[t]["detail"].get("selected_route")
                            == "measurement_family|deep_ocean_gauge|tide_gauge"
                            else ""
                        ),
                    }
                    for i, t in enumerate(result)
                ]
                figure(
                    stage,
                    module + "-screen",
                    chart,
                    "scatter",
                    "x",
                    "y",
                    module + ": pre-registered descriptive check",
                    "Target index (target name in CSV)",
                    {
                        "B1": "Distance-profile contrast on r₀ (dimensionless)",
                        "B2": "Flagged share of records",
                        "B3": "Site / residual MAD ratio",
                        "B4": "Event / residual MAD ratio",
                        "B5": "Selected largest / smallest MAD ratio",
                        "B6": "Selected within-event contrast (minutes)",
                        "B7": "Selected availability/peak screen (see CSV)",
                        "B8": "Maximum relative descriptive-summary change",
                        "B9": "Distance-profile contrast on r₀ (dimensionless)",
                        "B10": "Within-event rank correlation",
                        "B11": "Source/within-event duration contrast (minutes)",
                    }[module],
                    split,
                )
        if module == "C1":
            from analysis.arrival.evidence import read_rows

            metadata = {
                r["event_id"]: r
                for r in read_rows(
                    root
                    / "artifacts/eda/arrival-timing/frozen-inputs/development-event-metadata.csv"
                )
            }
            origins: dict[str, Record] = {}
            for row in read_rows(
                root / "data/processed/arrival-evidence/documentary-v1/forecast_instances.csv.gz"
            ):
                if row["event_id"] not in settings[split] or row["native_origin_utc"] == "unknown":
                    continue
                native = datetime.fromisoformat(row["native_origin_utc"].replace("Z", "+00:00"))
                reviewed = datetime.fromisoformat(
                    metadata[row["event_id"]]["origin_utc"].replace("Z", "+00:00")
                )
                origins[row["product_id"]] = {
                    "event_id": row["event_id"],
                    "product_id": row["product_id"],
                    "native_origin_utc": row["native_origin_utc"],
                    "reviewed_origin_utc": metadata[row["event_id"]]["origin_utc"],
                    "difference_seconds": (native - reviewed).total_seconds(),
                    "comparison": "separate documentary product; primary ancestry unapproved",
                }
            csv(stage / "documentary-origin-comparison.csv", list(origins.values()))
            result["documentary_origins"] = summarize(
                [r["difference_seconds"] for r in origins.values()]
            )
        write_json(stage / "summary.json", clean(result))
        write_json(stage / "metrics.json", {target: clean(result[target]) for target in result})
        (stage / "notes.md").write_text(
            "Descriptive preliminary evidence on a frozen archive-event split. "
            "Unknown arrival-pick provenance and source datum remain unknown. "
            "No filtering, repair, fitting or selection. Shared metadata sequence crossing "
            "halves and sparse confirmation support limit interpretation.\n"
        )
        write_json(
            stage / "inputs.json",
            {"frozen_input_manifest_sha256": sha256(input_path), "code": pins},
        )
        write_json(
            stage / "config.json",
            tomllib.loads((root / "config/arrival-timing-eda-settings.toml").read_text()),
        )
        write_json(stage / "seeds.json", {"bootstrap": 20261103})
        write_json(
            stage / "meta.json",
            {
                "split": split,
                "module": module,
                "purpose": "preliminary descriptive EDA; no fit",
                "git_sha": git_sha
                or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            },
        )
        (stage / "report.md").write_text(
            f"# {module} — {split}\n\nPreliminary descriptive "
            "results; no model fit or causal identification.\n\n"
            + "```json\n"
            + json.dumps(clean(result), indent=2)
            + "\n```\n"
        )
        rename_bundle_files(stage)
        if reference is not None:
            # Retain authentic generation provenance; the lock separately pins replay code.
            name = artifact_filename("inputs.json")
            (stage / name).write_bytes((reference / name).read_bytes())
        write_json(stage / artifact_filename("outputs.json"), file_manifest(stage))
        if reference is not None and file_manifest(stage) != file_manifest(reference):
            raise ValueError("EDA replay differs from canonical bundle")
        stage.rename(output)
    print(f"{module} {split}: {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", choices=["exploration", "confirmation"], required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--git-sha", default=None)
    p.add_argument(
        "--replay",
        action="store_true",
        help="Verify an existing exploration or confirmation bundle byte for byte",
    )
    args = p.parse_args()
    run(Path(".").resolve(), args.split, args.module, args.output, args.git_sha, args.replay)
