"""Freeze a reproducible development waveform audit without arrival labels or picks.

Private mappings never enter blind/. Source samples remain unchanged, with only
identifiers removed from blind copies. Charts use raw native water levels.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.ntwc_archive import link_identity  # noqa: E402
from scripts.build_multi_event_catalog import (  # noqa: E402
    VALID_TIMES,
    _inside,
    _json,
    _records,
    _sha,
    _utc,
    _verify,
    _write_csv,
    _write_json,
)

SEED = "ntwc-blind-waveforms-v1"
BLIND_COLUMNS = (
    "source_row_number",
    "timestamp_utc",
    "timestamp_state",
    "raw_timestamp",
    "raw_epoch",
    "raw_value",
    "numeric_value",
    "value_state",
    "units",
    "vertical_datum",
    "qc_state",
    "qc_json",
    "duplicate_timestamp",
)
KNOWN_UNITS = {"m", "meters", "metres", "cm", "mm", "ft", "feet"}


def case_key(source: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Do not merge identities supplied by different providers or sensors."""
    url = urlsplit(str(source["source_url"]))
    if url.hostname == "api.tidesandcurrents.noaa.gov":
        station = parse_qs(url.query).get("station", ["unknown"])[0]
        provider, sensor = "CO-OPS", "provider_product"
    else:
        tokens = link_identity(source["source_url"])
        station = source.get("station_key", "ntwc-" + tokens["link_code"])
        provider, sensor = (
            source.get("provider", "unverified"),
            source.get("sensor", tokens["link_sensor"]),
        )
    if station in {"unknown", "ntwc-unknown"}:
        station = "unresolved-source-" + source["source_id"]
    if source["purpose"] == "quiet_control":
        station += "|" + source["window_start_utc"] + "|" + source["window_stop_utc"]
    return source["event_id"], provider, station, sensor, source["purpose"]


def choose_cases(
    keys: list[tuple[str, str, str, str, str]], events: dict[str, dict[str, Any]], count: int
) -> list[tuple[str, str, str, str, str]]:
    """Balance events, eras and regions without consulting waveform values or picks."""
    remaining = set(keys)
    chosen: list[tuple[str, str, str, str, str]] = []
    event_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    era_counts: Counter[int] = Counter()
    while remaining and len(chosen) < count:

        def score(key: tuple[str, str, str, str, str]) -> tuple[Any, ...]:
            event = events[key[0]]
            era = int(event["usgs_time"][:4]) // 5 * 5
            return (
                event_counts[key[0]],
                region_counts[event.get("region", "unknown")],
                era_counts[era],
                hashlib.sha256((SEED + repr(key)).encode()).hexdigest(),
            )

        selected = min(remaining, key=score)
        remaining.remove(selected)
        chosen.append(selected)
        event_counts[selected[0]] += 1
        region_counts[events[selected[0]].get("region", "unknown")] += 1
        era_counts[int(events[selected[0]]["usgs_time"][:4]) // 5 * 5] += 1
    return chosen


def chart_sources(sources: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    normalized = [s for s in sources if s["processing_status"] == "normalized_source_samples"]
    if provider == "CO-OPS" and normalized:
        # Prefer the finest available product; lexical source ID breaks exact ties.
        return [min(normalized, key=lambda s: (s["declared_cadence_seconds"], s["source_id"]))]
    return sorted(normalized, key=lambda s: s["source_id"])


def chart_points(
    rows: list[dict[str, str]], reference: str, cadence: float
) -> tuple[list[float], list[float], dict[str, int]]:
    """Collapse equal timestamp/value duplicates for charts only; conflicts leave gaps."""
    origin = _utc(reference)
    grouped: dict[str, list[float]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    for row in rows:
        if row["timestamp_state"] not in VALID_TIMES:
            excluded["invalid_timestamp_rows"] += 1
            continue
        stamp = _utc(row["timestamp_utc"])
        hour = (stamp - origin).total_seconds() / 3600
        if not -6 <= hour < 30:
            excluded["outside_plot_window_rows"] += 1
            continue
        if row["value_state"] != "finite_numeric":
            excluded["non_numeric_rows"] += 1
            continue
        value = float(row["numeric_value"])
        if not math.isfinite(value):
            raise ValueError("finite numeric flag conflicts with source value")
        grouped[stamp.isoformat()].append(value)
    x: list[float] = []
    y: list[float] = []
    previous = None
    for stamp, values in sorted(grouped.items()):
        time = _utc(stamp)
        if len(set(values)) > 1:
            excluded["conflicting_duplicate_rows"] += len(values)
            continue
        excluded["identical_duplicate_rows_removed"] += len(values) - 1
        hour = (time - origin).total_seconds() / 3600
        if previous is not None and (time - previous).total_seconds() > cadence * 1.5:
            x.append(hour)
            y.append(float("nan"))
        x.append(hour)
        y.append(values[0])
        previous = time
    return x, y, dict(excluded)


def plot_case(
    case_id: str,
    x: list[float],
    y: list[float],
    units: str,
    datum: str,
    provider: str,
    reference: str,
) -> Figure:
    """Raw source values only: no tide subtraction, smoothing or predicted arrivals."""
    fig, ax = plt.subplots(figsize=(10, 5.5), layout=None)
    fig.subplots_adjust(left=0.11, right=0.97, bottom=0.23, top=0.76)
    fig.text(
        0.11, 0.93, f"Raw water levels • {case_id}", fontsize=17, weight="bold", color="#333333"
    )
    fig.text(
        0.11,
        0.865,
        f"Native units: {units}  |  Provider datum: {datum}",
        fontsize=12,
        color="#595959",
    )
    ax.plot(x, y, color="#0072B2", linewidth=1)
    ax.set(
        xlim=(-6, 30), xlabel="Hours from supplied reference time", ylabel=f"Water level ({units})"
    )
    ax.set_xlabel("Hours from supplied reference time", fontsize=12)
    ax.set_ylabel(f"Water level ({units})", fontsize=12)
    ax.tick_params(labelsize=11)
    ax.grid(axis="y", color="#E5E5E5", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(
        0.11,
        0.115,
        f"Source: {provider} water-level records. Reference: {reference}",
        fontsize=11,
        color="#595959",
    )
    fig.text(
        0.11,
        0.055,
        "Raw levels; gaps retained. No tide removal, arrival labels or predictions.",
        fontsize=11,
        color="#595959",
    )
    return fig


def build(
    root: Path,
    selection: Path,
    waveform_manifest: Path,
    output: Path,
    sample_size: int = 60,
    controls: int = 9,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if not 1 <= sample_size <= 60 or not 0 <= controls <= 9:
        raise ValueError("audit sample bounds are 1..60 and 0..9 controls")
    root = root.resolve()
    selection = _inside(root, selection)
    waveform_manifest = _inside(root, waveform_manifest)
    frozen, manifest = _json(selection), _json(waveform_manifest)
    material = {k: v for k, v in frozen.items() if k != "selection_sha256"}
    if (
        hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != frozen["selection_sha256"]
    ):
        raise ValueError("frozen selection digest mismatch")
    for name, digest in manifest["input_sha256"].items():
        _verify(_inside(root, Path(name)), digest)
    events = {r["event_id"]: r for r in frozen["events"]}
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in manifest["sources"]:
        if source["purpose"] not in {"event_window", "quiet_control"}:
            continue
        if source["event_id"] not in events or events[source["event_id"]]["role"] != "development":
            raise ValueError("reserved or absent event in audit input")
        groups[case_key(source)].append(source)
    chosen = choose_cases([k for k in groups if k[-1] == "event_window"], events, sample_size)
    chosen_controls = choose_cases(
        [k for k in groups if k[-1] == "quiet_control"], events, controls
    )
    mapping: list[dict[str, Any]] = [
        {
            "case_id": "case-" + hashlib.sha256((SEED + repr(k)).encode()).hexdigest()[:12],
            "key": k,
            "source_ids": sorted(s["source_id"] for s in groups[k]),
        }
        for k in chosen + chosen_controls
    ]
    freeze = {
        "seed": SEED,
        "requested_event_cases": sample_size,
        "requested_controls": controls,
        "event_cases": len(chosen),
        "control_cases": len(chosen_controls),
        "cases": mapping,
        "selection_sha256": frozen["selection_sha256"],
        "waveform_manifest_sha256": _sha(waveform_manifest),
        "sampling_basis": "event/station/provider/sensor metadata; no source values or picks",
        "plot_product_rule": "Finest CO-OPS cadence; lexical tie; providers/sensors separate",
    }
    freeze["sample_sha256"] = hashlib.sha256(
        json.dumps(freeze, sort_keys=True).encode()
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".blind-waveform-audit-", dir=output.parent))
    try:
        # Freeze metadata selection before opening normalized waveform rows.
        _write_json(temporary / "private/sample.json", freeze)
        blind: list[dict[str, Any]] = []
        private: list[dict[str, Any]] = []
        for item, key in zip(mapping, chosen + chosen_controls, strict=True):
            eid, provider, _, sensor, purpose = key
            sources = sorted(groups[key], key=lambda s: s["source_id"])
            selected = chart_sources(sources, provider)
            origin = _utc(events[eid]["usgs_time"])
            event_start = origin.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
                days=1
            )
            reference = (
                origin
                if purpose == "event_window"
                else origin + (_utc(sources[0]["window_start_utc"]) - event_start)
            ).isoformat()
            case: dict[str, Any] = {
                "case_id": item["case_id"],
                "reference_utc": reference,
                "reference_basis": "Blinded reference time; case assignment withheld",
                "provider": provider,
                "provider_station_id": sources[0].get("provider_station_id", "unknown"),
                "sensor": sensor,
                "plot_window_hours": [-6, 30],
                "sources": [],
                "physical_onset_validated": False,
                "physical_site_id": "unknown",
                "deployment_id": "unknown",
                "expert_ground_truth": False,
                "pick_status": "unreviewed",
            }
            combined: list[dict[str, str]] = []
            selected_ids = {s["source_id"] for s in selected}
            aliases: list[dict[str, Any]] = []
            for n, source in enumerate(sources, 1):
                alias = f"trace-{n:02d}"
                entry = {
                    "trace_id": alias,
                    "status": source["processing_status"],
                    "units": source.get("units", "unknown"),
                    "vertical_datum": source.get("vertical_datum", "unknown"),
                    "declared_cadence_seconds": source.get("declared_cadence_seconds", "unknown"),
                    "selected_for_chart": source["source_id"] in selected_ids,
                    "source_metadata": {
                        k: source.get("source_metadata", {}).get(k, "unknown")
                        for k in (
                            "name",
                            "header_name",
                            "lat",
                            "lon",
                            "latitude",
                            "longitude",
                            "coordinate_crs",
                        )
                    },
                }
                aliases.append({"trace_id": alias, "source": source})
                if source["processing_status"] == "normalized_source_samples":
                    path = _inside(waveform_manifest.parent, Path(source["output_path"]))
                    _verify(path, source["output_sha256"])
                    rows = _records(path)
                    if any(
                        r["event_id"] != eid
                        or r["source_id"] != source["source_id"]
                        or r["purpose"] != purpose
                        for r in rows
                    ):
                        raise ValueError("source row identity or purpose differs from audit case")
                    relative = Path("cases") / item["case_id"] / f"{alias}.csv.gz"
                    _write_csv(temporary / "blind" / relative, rows, list(BLIND_COLUMNS))
                    entry.update(
                        path=relative.as_posix(),
                        rows=len(rows),
                        sha256=_sha(temporary / "blind" / relative),
                    )
                    if source["source_id"] in selected_ids:
                        combined.extend(rows)
                case["sources"].append(entry)
            reasons: list[str] = []
            if not selected:
                reasons.append("no_normalized_source")
            units = {s["units"] for s in selected}
            datums = {s["vertical_datum"] for s in selected}
            cadences = {s["declared_cadence_seconds"] for s in selected}
            if not units <= KNOWN_UNITS or len(units) != 1:
                reasons.append("unsupported_or_mixed_units")
            if len(datums) != 1 or len(cadences) != 1:
                reasons.append("mixed_or_missing_datum_or_cadence")
            elif not all(
                isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                for value in cadences
            ):
                reasons.append("unsupported_cadence")
            if not reasons:
                x, y, counts = chart_points(combined, reference, float(next(iter(cadences))))
                case["chart_exclusions"] = counts
                if sum(math.isfinite(v) for v in y) < 2:
                    reasons.append("insufficient_time_valid_numeric_samples")
                else:
                    figure = plot_case(
                        item["case_id"],
                        x,
                        y,
                        next(iter(units)),
                        next(iter(datums)),
                        provider,
                        reference,
                    )
                    relative = Path("cases") / item["case_id"] / "raw-water-level.png"
                    figure.savefig(
                        temporary / "blind" / relative, dpi=150, metadata={"Software": "matplotlib"}
                    )
                    plt.close(figure)
                    case.update(
                        chart_path=relative.as_posix(),
                        chart_sha256=_sha(temporary / "blind" / relative),
                        chart_alt_text="Raw water levels versus hours; gaps retained.",
                    )
            case.update(
                reviewable=not reasons,
                blocked_reasons=reasons,
            )
            _write_json(temporary / "blind/cases" / item["case_id"] / "metadata.json", case)
            blind.append(case)
            private.append({**item, "aliases": aliases})
        _write_json(temporary / "private/mapping.json", private)
        # Do not expose the event-then-control sampling order to reviewers.
        blind.sort(key=lambda case: case["case_id"])
        _write_json(
            temporary / "blind/catalog.json",
            {
                "schema_version": "blinded-waveform-audit-v1",
                "cases": blind,
                "instructions": (
                    "Inspect raw records. Record uncertain intervals or unusable reasons; "
                    "do not force a pick. Identify AI-assisted reviews as such. "
                    "Plot availability is not onset identifiability. "
                    "Agreement is not expert ground truth; no physical onsets are validated."
                ),
                "blinding_limit": (
                    "Timing and station metadata remain visible; known events may be recognizable. "
                    "Source assignments and comparison labels are withheld."
                ),
                "sampling_limit": (
                    "The sample balances events, regions and five-year eras among available "
                    "source groups. Cadence, provider and amplitude were not sampling strata. "
                    "Do not interpret audit proportions as archive-wide error rates."
                ),
            },
        )
        _write_csv(
            temporary / "blind/review-template.csv",
            [
                {
                    "case_id": r["case_id"],
                    "reviewer": "",
                    "reviewer_type": "",
                    "status": "unreviewed",
                    "onset_lower_utc": "",
                    "onset_upper_utc": "",
                    "reason": "",
                    "physical_onset_validated": False,
                }
                for r in blind
            ],
        )
        (temporary / "blind/README.md").write_text(
            "# Blinded waveform audit\n\n"
            "Use [catalog.json](catalog.json) to find each case, its metadata, raw traces "
            "and chart. Record one review per case in a copy of "
            "[review-template.csv](review-template.csv); preserve these input files.\n\n"
            "The plots show raw water levels in the reported native units, from six hours "
            "before to thirty hours after a blinded reference time. No tide removal, "
            "smoothing or onset annotation has been applied. Original trace rows are "
            "retained. Duplicate timestamps and gaps are handled only for chart display; "
            "the case metadata records exclusions.\n\n"
            "Inspect time support, units, cadence, gaps and source metadata before "
            "interpreting a trace. Unknown fields remain unknown. A plotted case is not "
            "necessarily suitable for identifying a physical onset. Missing, unsupported "
            "and ambiguous cases are valid review outcomes.\n\n"
            "Use status `provisional_interval` only when a defensible interval can be "
            "identified; otherwise use `ambiguous` or `unreviewable` and explain why. "
            "Keep interval bounds in UTC. Identify AI-assisted reviews in reviewer_type. "
            "Leave physical_onset_validated false: reviewer agreement does not establish "
            "expert-validated ground truth.\n\n"
            "Timing and station metadata remain visible, so known events may be "
            "recognizable. Assignments and comparison labels are withheld. The selection "
            "balances events, regions and five-year eras among available source groups; "
            "it does not stratify by provider, cadence or amplitude. Audit proportions "
            "must not be treated as archive-wide error rates.\n",
            encoding="utf-8",
        )
        summary = {
            "schema_version": "blinded-waveform-audit-package-v1",
            "sample_sha256": freeze["sample_sha256"],
            "event_cases": len(chosen),
            "control_cases": len(chosen_controls),
            "reviewable_cases": sum(r["reviewable"] for r in blind),
            "picks": 0,
            "input_sha256": {
                str(selection.relative_to(root)): _sha(selection),
                str(waveform_manifest.relative_to(root)): _sha(waveform_manifest),
            },
            "output_sha256": {
                str(p.relative_to(temporary)): _sha(p)
                for p in sorted(temporary.rglob("*"))
                if p.is_file()
            },
            "boundary": "Supply only blind/ to auditors; private/ identifies the sources",
        }
        _write_json(temporary / "manifest.json", summary)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument(
        "--waveforms", type=Path, required=True, help="Normalized waveform manifest JSON"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--controls", type=int, default=9)
    args = parser.parse_args()
    result = build(
        args.root, args.selection, args.waveforms, args.output, args.sample_size, args.controls
    )
    print(
        json.dumps(
            {k: result[k] for k in ("event_cases", "control_cases", "reviewable_cases", "picks")}
        )
    )


if __name__ == "__main__":
    main()
