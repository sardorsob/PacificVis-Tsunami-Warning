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
from analysis.arrival.eda import (  # noqa: E402
    DISTANCE_BINS,
    Record,
    bootstrap_median,
    grouped,
    load_frames,
    summarize,
    support,
)
from analysis.arrival.eda_plots import draw  # noqa: E402
from analysis.arrival.evidence import (  # noqa: E402
    file_manifest,
    sha256,
    verify_inputs,
    write_json,
    write_rows,
)


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
                "integer_minute_share": sum(abs(v - round(v)) < 1e-6 for v in values) / len(values)
                if values
                else math.nan,
                "outside_fixed_histogram": len(logs) - int(sum(freq)),
                "negative_share": sum(v < 0 for v in values) / len(values) if values else math.nan,
            }
            if module == "C8":
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
                "Geodesic distance (km)",
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


def run(root: Path, split: str, module: str, output: Path, git_sha: str | None = None) -> None:
    if output.exists():
        raise FileExistsError(output)
    input_path = root / "artifacts/eda/paper/freeze-v1/inputs.json"
    frozen = verify_inputs(input_path, expected_schema="paper_eda_inputs_v1")
    settings = tomllib.loads((root / "config/paper-eda-split-v1.toml").read_text())
    frames, availability = load_frames(root, frozen, settings[split])
    code = ["analysis/arrival/eda.py", "analysis/arrival/eda_plots.py", "scripts/run_paper_eda.py"]
    pins = {p: sha256(root / p) for p in code}
    if split == "confirmation":
        lock = json.loads((root / "artifacts/eda/paper/confirmation-lock.json").read_text())
        if lock["code"] != pins:
            raise ValueError("confirmation code drift")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / "bundle"
        stage.mkdir()
        result = core(frames, availability, module, stage, split)
        if module == "C1":
            from analysis.arrival.evidence import read_rows

            metadata = {
                r["event_id"]: r
                for r in read_rows(root / "artifacts/eda/paper/freeze-v1/development-metadata.csv")
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
            stage / "config.json", tomllib.loads((root / "config/paper-eda-v1.toml").read_text())
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
        write_json(stage / "outputs.json", file_manifest(stage))
        stage.rename(output)
    print(f"{module} {split}: {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", choices=["exploration", "confirmation"], required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--git-sha", default=None)
    args = p.parse_args()
    run(Path(".").resolve(), args.split, args.module, args.output, args.git_sha)
