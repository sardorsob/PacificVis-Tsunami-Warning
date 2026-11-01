"""Package immutable acquisition evidence into private paper and safe viewer catalogs.

The viewer receives a strict allowlist of development metadata and waveform
samples. It never receives paper reports, reservation lists or model results.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import tomllib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import load_contracts

WAVE_COLUMNS = (
    "event_id",
    "source_id",
    "station_key",
    "sensor",
    "timestamp_utc",
    "numeric_value",
    "value_state",
    "timestamp_state",
    "duplicate_timestamp",
    "units",
    "vertical_datum",
    "qc_state",
    "qc_json",
)
VALID_TIMES = {
    "reported_utc",
    "epoch_calendar_agree",
    "epoch_calendar_minute_agree",
    "header_day_end_boundary",
}
MAX_VIEWER_ASSET_BYTES = 2_000_000
TABLE_GRAINS_KEYS = {
    "event_index": ("One archived event page/disposition", ["archive_key"]),
    "report_index": ("One original NTWC table row", ["report_id"]),
    "event_station_index": ("One report/code/sensor alternative", ["event_station_record_id"]),
    "unique_report_crosswalk": ("One identity assessment per source report", ["report_id"]),
    "source_index": ("One acquisition source, including failures and controls", ["source_id"]),
    "source_url_overlaps": (
        "One acquisition source in a repeated exact URL group; no deduplication",
        ["source_url", "source_id"],
    ),
    "series_coverage": (
        "One event-window observation series with compatible cadence, units and datum",
        [
            "event_id",
            "provider",
            "provider_station_id",
            "display_station_key",
            "station_key",
            "sensor",
            "declared_cadence_seconds",
            "units",
            "vertical_datum",
            "window_start_utc",
            "window_stop_utc",
        ],
    ),
    "contour_index": ("One published event travel-time layer", ["event_id", "layer_id"]),
    "reviewed_site_incidence": ("One reviewed event/site edge", ["event_id", "physical_site_id"]),
    "site_degrees": ("One reviewed geographic/provider site", ["physical_site_id"]),
    "fold_rank": ("One leave-event/site-out design audit", ["fold", "held_out"]),
    "stage_d_pass_rates": ("One metadata group support summary", ["grouping", "value"]),
    "cadence_by_era": (
        "One header year/provider/cadence/unit group",
        ["year", "provider", "cadence_value", "cadence_units", "units"],
    ),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"input path escapes project: {path}")
    return resolved


def _relative(root: Path, path: Path) -> str:
    return _inside(root, path).relative_to(root.resolve()).as_posix()


def _member(folder: Path, name: str) -> Path:
    return _inside(folder, Path(name))


def _verify(path: Path, expected: str) -> None:
    if _sha(path) != expected:
        raise ValueError(f"checksum mismatch: {path}")


def _records(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(
    path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None
) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or sorted({key for row in rows for key in row}) or ["status"]
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row.get(key, "unknown") for key in fields} for row in rows)
    payload = target.getvalue().encode()
    path.write_bytes(gzip.compress(payload, mtime=0) if path.suffix == ".gz" else payload)
    return fields


def _true(value: Any) -> bool:
    return value is True or value == "True" or value == "true"


def _utc(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value):
        raise ValueError("display window requires explicit UTC timestamps")
    return datetime.fromisoformat(value)


def _event_order(row: dict[str, Any]) -> tuple[bool, str, str, str]:
    origin = row.get("origin_utc", row.get("usgs_time", "unknown"))
    known = origin not in {None, "", "unknown"}
    return (
        not known,
        _utc(str(origin)).isoformat(timespec="microseconds") if known else "",
        str(row.get("event_id", "unknown")),
        str(row.get("archive_key", "")),
    )


def _assert_development(rows: list[dict[str, Any]], events: dict[str, dict[str, Any]]) -> None:
    for row in rows:
        event = events.get(str(row.get("event_id", "")))
        if (
            not event
            or event["role"] != "development"
            or row.get("role", "development") != "development"
        ):
            raise ValueError("reserved or absent event in value-bearing input")


def _source_url_overlaps(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        url = source.get("source_url")
        if isinstance(url, str) and url not in {"", "unknown"}:
            groups[url].append(source)
    return [
        {
            **{
                key: source.get(key, "unknown")
                for key in (
                    "source_url",
                    "source_id",
                    "event_id",
                    "purpose",
                    "source_sha256",
                    "output_sha256",
                    "processing_status",
                    "acquisition_status",
                    "raw_path",
                    "normalized_path",
                    "provider",
                    "sensor",
                    "units",
                    "vertical_datum",
                    "source_rows",
                )
            },
            "group_source_count": len(members),
        }
        for _, members in sorted(groups.items())
        if len(members) > 1
        for source in sorted(members, key=lambda row: row["source_id"])
    ]


def _wave_sources(
    root: Path, folder: Path, manifest: dict[str, Any], events: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    contracts: dict[str, Any] = {}
    for name, digest in manifest["input_sha256"].items():
        path = _inside(root, Path(name))
        _verify(path, digest)
        if path.suffix == ".toml":
            document = tomllib.loads(path.read_text())
            if "events" in document:
                configured = {row["event_id"]: row for row in document["events"].values()}
                if set(configured) != set(events) or any(
                    configured[eid][key] != events[eid][key]
                    for eid in events
                    for key in ("role", "usgs_time")
                ):
                    raise ValueError("waveform event config differs from frozen selection")
            for contract in load_contracts(path):
                contracts[contract.source_id] = contract
    sources: list[dict[str, Any]] = []
    if len({row["source_id"] for row in manifest["sources"]}) != len(manifest["sources"]):
        raise ValueError("duplicate waveform source identity")
    for item in manifest["sources"]:
        row = dict(item)
        if "event_id" in row:
            _assert_development([row], events)
        contract = contracts.get(row["source_id"])
        if contract:
            row.update(
                raw_path=str(contract.local_path),
                publisher=contract.publisher,
                crs=contract.crs,
                horizontal_datum=contract.horizontal_datum,
                coordinate_order=contract.coordinate_order,
            )
            if row.get("source_sha256") not in {None, "unknown"}:
                _verify(_inside(root, Path(contract.local_path)), row["source_sha256"])
        if row.get("processing_status") == "normalized_source_samples":
            _assert_development([row], events)
            path = _member(folder, row["output_path"])
            _verify(path, row["output_sha256"])
            row["normalized_path"] = _relative(root, path)
        sources.append(row)
    return sources


def _viewer(
    root: Path,
    output: Path,
    events: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    contours: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Use declared operational QC, keeping source samples distinct from onsets."""
    by_source = {row["source_id"]: row for row in sources}
    series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    _assert_development(coverage, events)
    for row in coverage:
        if _true(row.get("display_eligible")):
            origin = _utc(events[row["event_id"]]["usgs_time"])
            if _utc(row["window_start_utc"]) != origin - timedelta(hours=6) or _utc(
                row["window_stop_utc"]
            ) != origin + timedelta(hours=30):
                raise ValueError("display coverage window differs from frozen origin rule")
            if (
                not row.get("source_ids")
                or row.get("rule_id") != "viewer_36h_80pct_60min_v1"
                or row.get("purpose") != "event_window"
                or row.get("expected_bins", 0) <= 0
                or row.get("usable_bins", 0) / row["expected_bins"] < 0.8
                or row["usable_bins"] > row["expected_bins"]
                or abs(row["coverage_fraction"] - row["usable_bins"] / row["expected_bins"]) > 1e-9
                or row.get("longest_supported_minutes", 0) < 60
                or not re.fullmatch(r"coops:\d{7}", row.get("display_station_key", ""))
            ):
                raise ValueError("display coverage does not satisfy its declared rule")
            for sid in row["source_ids"]:
                source = by_source.get(sid, {})
                if (
                    source.get("event_id") != row["event_id"]
                    or source.get("processing_status") != "normalized_source_samples"
                    or source.get("purpose") != "event_window"
                    or source.get("provider") not in {"CO-OPS", "NOS", "NOAA"}
                    or source.get("display_station_key") != row["display_station_key"]
                    or f"coops:{source.get('provider_station_id', 'unknown')}"
                    != row["display_station_key"]
                ):
                    raise ValueError("coverage source is not a normalized event window")
            series[row["event_id"]].append(row)
    readiness: dict[str, dict[str, Any]] = {}
    exports: list[dict[str, Any]] = []
    for eid, event in sorted(
        events.items(), key=lambda item: _event_order({**item[1], "event_id": item[0]})
    ):
        if event["role"] != "development":
            continue
        stations = {row.get("display_station_key", row["station_key"]) for row in series[eid]}
        ready = len(stations) >= 3
        readiness[eid] = {
            "display_usable_station_count": len(stations),
            "viewer_ready": ready,
            "viewer_blocked_reason": "none"
            if ready
            else "lt3_display_usable_stations"
            if coverage
            else "display_coverage_qc_missing",
        }
        if not ready:
            continue
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for quality in sorted(series[eid], key=lambda row: (row["station_key"], row["sensor"])):
            start, stop = (
                datetime.fromisoformat(quality[key])
                for key in ("window_start_utc", "window_stop_utc")
            )
            for sid in sorted(quality["source_ids"]):
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", sid) or sid in {".", ".."}:
                    raise ValueError("unsafe source identity")
                if sid in seen:
                    continue
                seen.add(sid)
                source = by_source[sid]
                if (
                    source.get("event_id") != eid
                    or source.get("processing_status") != "normalized_source_samples"
                    or source.get("purpose") != "event_window"
                ):
                    raise ValueError(
                        "coverage source does not belong to the declared development event"
                    )
                rows = _records(_inside(root, Path(source["normalized_path"])))
                _assert_development(rows, events)
                if any(
                    row["source_id"] != sid
                    or row["event_id"] != eid
                    or row.get("purpose") != "event_window"
                    for row in rows
                ):
                    raise ValueError("waveform row identity differs from verified source")
                chosen = [
                    row
                    for row in rows
                    if row["timestamp_state"] in VALID_TIMES
                    and start <= datetime.fromisoformat(row["timestamp_utc"]) < stop
                ]
                relative = Path("waveforms") / eid / f"{sid}.csv.gz"
                _write_csv(output / "viewer" / relative, chosen, list(WAVE_COLUMNS))
                payload = (output / "viewer" / relative).read_bytes()
                metadata = source.get("source_metadata", {})
                files.append(
                    {
                        "source_id": sid,
                        "station_key": quality["station_key"],
                        "sensor": quality["sensor"],
                        "path": relative.as_posix(),
                        "sha256": _sha(output / "viewer" / relative),
                        "media_type": "text/csv",
                        "content_encoding": "gzip",
                        "compressed_bytes": len(payload),
                        "uncompressed_bytes": len(gzip.decompress(payload)),
                        "rows": len(chosen),
                        "rows_outside_display_slice_or_invalid_time": len(rows) - len(chosen),
                        "source_url": source["source_url"],
                        "source_sha256": source["source_sha256"],
                        "units": source["units"],
                        "vertical_datum": source["vertical_datum"],
                        "station_name": metadata.get(
                            "name", metadata.get("header_name", "unknown")
                        ),
                        "latitude": metadata.get("lat", metadata.get("latitude", "unknown")),
                        "longitude": metadata.get("lon", metadata.get("longitude", "unknown")),
                        "coordinate_crs": metadata.get("coordinate_crs", "unknown"),
                        "physical_site_id": "unknown",
                        "deployment_id": "unknown",
                        "coverage_rule_id": quality["rule_id"],
                        "display_station_key": quality["display_station_key"],
                        "coverage_fraction": quality["coverage_fraction"],
                        "longest_supported_minutes": quality["longest_supported_minutes"],
                    }
                )
        exports.append(
            {
                "event_id": eid,
                "name": event["usgs_place"],
                "origin_utc": event["usgs_time"],
                "latitude": float(event["usgs_latitude"]),
                "longitude": float(event["usgs_longitude"]),
                "magnitude": float(event["usgs_mag"]),
                "magnitude_type": event["usgs_magType"],
                "depth_km": float(event["usgs_depth"]),
                "usable_station_count": len(stations),
                "waveforms": files,
            }
        )
        published: list[dict[str, Any]] = []
        for contour in contours or []:
            if contour["event_id"] != eid:
                continue
            source_path = _inside(root, Path(contour["processed_path"]))
            geometry = _json(source_path)
            layer = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": feature["geometry"],
                        "properties": {
                            key: feature["properties"][key] for key in ("HOURS", "Name")
                        },
                    }
                    for feature in geometry["features"]
                ],
            }
            relative = Path("contours") / f"{eid}-{contour['layer_id']}.geojson"
            payload = (json.dumps(layer, indent=2, sort_keys=True) + "\n").encode()
            uncompressed_bytes = len(payload)
            encoding = "identity"
            if len(payload) > MAX_VIEWER_ASSET_BYTES:
                relative = relative.with_suffix(".geojson.gz")
                payload = gzip.compress(payload, mtime=0)
                encoding = "gzip"
            target = output / "viewer" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            published.append(
                {
                    "publisher": "NOAA NCEI",
                    "source_url": contour["source_url"],
                    "source_sha256": contour["raw_sha256"],
                    "path": relative.as_posix(),
                    "sha256": _sha(output / "viewer" / relative),
                    "media_type": "application/geo+json",
                    "content_encoding": encoding,
                    "compressed_bytes": len(payload),
                    "uncompressed_bytes": uncompressed_bytes,
                    "units": contour["units"],
                    "crs": contour["crs"],
                    "coordinate_order": contour["coordinate_order"],
                    "horizontal_datum": contour["horizontal_datum"],
                    "origin_reference": contour["origin_reference"],
                    "ntwc_prediction_equivalence_verified": False,
                }
            )
        exports[-1]["published_travel_time_contours"] = published
    _write_json(
        output / "viewer/catalog.json",
        {
            "schema_version": "development-waveform-catalog-v1",
            "events": exports,
            "description": (
                "Source water-level records; UTC and provider datum retained. "
                "No physical arrival picks are supplied."
            ),
            "asset_encoding_contract": (
                "Decode each asset according to its content_encoding metadata; "
                "do not assume the server transparently decodes gzip files. "
                "Hashes and compressed_bytes refer to stored bytes; identity means no compression."
            ),
        },
    )
    for path in (output / "viewer").rglob("*"):
        if path.is_file() and path.stat().st_size > MAX_VIEWER_ASSET_BYTES:
            raise ValueError(f"viewer asset exceeds {MAX_VIEWER_ASSET_BYTES} bytes: {path.name}")
    return exports, readiness


def _recovery_bundle(
    root: Path,
    folder: Path,
    corpus: Path,
    crosswalk: Path,
    corpus_summary: dict[str, Any],
    events: dict[str, dict[str, Any]],
    report_events: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Path], dict[Path, str]]:
    """Verify an optional private recovery package without changing legacy support."""
    versions = {
        "T-OBS": "reported_duration_from_reviewed_reference_v1",
        "T-CAL": "reported_absolute_difference_v1",
    }
    folder = _inside(root, folder)
    manifest_path = folder / "manifest.json"
    manifest, summary = _json(manifest_path), _json(folder / "summary.json")
    if summary.get("schema_version") != "arrival-recovery-qa-v1" or summary.get(
        "input_sha256"
    ) != manifest.get("input_sha256"):
        raise ValueError("recovery summary/manifest lineage mismatch")
    stems = {
        "recovery_delta",
        "fold_support",
        "site_degrees",
        "balance",
        "evidence_gap_queue",
        "t-obs",
        "t-cal",
    }
    allowed = {f"{stem}.{suffix}" for stem in stems for suffix in ("json", "csv")}
    allowed.add("summary.json")
    required = {f"{stem}.json" for stem in stems} | {"summary.json"}
    outputs = manifest["output_sha256"]
    if not required <= set(outputs) <= allowed:
        raise ValueError("recovery manifest has missing or unsupported output paths")
    files = {"manifest.json": manifest_path}
    pins = {manifest_path: _sha(manifest_path)}
    for name, digest in outputs.items():
        path = _member(folder, name)
        if path.parent != folder or path.name != name:
            raise ValueError("recovery output path must be an exact local filename")
        _verify(path, digest)
        files[name], pins[path] = path, digest
    for name, digest in manifest["input_sha256"].items():
        path = _inside(root, Path(name))
        if _relative(root, path) != name:
            raise ValueError("recovery input path must be exact and project-relative")
        _verify(path, digest)
        pins[path] = digest
    for path in (corpus / "summary.json", crosswalk / "unique_report_crosswalk.csv"):
        if manifest["input_sha256"].get(_relative(root, path)) != _sha(path):
            raise ValueError("recovery does not pin the current corpus/crosswalk")
    if corpus_summary["input_sha256"].get("crosswalk") != _sha(
        crosswalk / "unique_report_crosswalk.csv"
    ):
        raise ValueError("corpus/recovery crosswalk checksum mismatch")
    configs = [
        path
        for path, digest in pins.items()
        if path.suffix == ".toml" and digest == corpus_summary["input_sha256"].get("config")
    ]
    if not configs:
        raise ValueError("recovery lacks the current corpus event-config pin")
    for config in configs:
        configured = tomllib.loads(config.read_text(encoding="utf-8"))["events"]
        roles = {row["event_id"]: row["role"] for row in configured.values()}
        if roles != {eid: row["role"] for eid, row in events.items()}:
            raise ValueError("recovery event-config roles differ from frozen selection")

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            value = cast(dict[str, Any], value)
            if "event_id" in value:
                _assert_development([value], events)
            if "report_id" in value and report_events.get(value["report_id"]) != value.get(
                "event_id"
            ):
                raise ValueError("recovery report/event identity mismatch")
            if "target_id" in value:
                target = value["target_id"]
                if (
                    target not in versions
                    or value.get("target_version", versions[target]) != versions[target]
                ):
                    raise ValueError("recovery target version mismatch")
            if (
                value.get("fold") == "LOEO"
                and events.get(str(value.get("held_out", "")), {}).get("role") != "development"
            ):
                raise ValueError("recovery fold contains reserved event")
            for key, item in value.items():
                if key in {"model_eligible", "physical_onset_validated", "acquisition_eligible"}:
                    if item not in (False, "False", "false"):
                        raise ValueError(
                            "recovery must retain false scientific/acquisition approvals"
                        )
                if key in {"events", "unseen_events"}:
                    members = (
                        json.loads(item) if isinstance(item, str) and item.startswith("[") else item
                    )
                    if isinstance(members, list):
                        for member in cast(list[Any], members):
                            if (
                                not isinstance(member, str)
                                or events.get(member, {}).get("role") != "development"
                            ):
                                raise ValueError("recovery graph contains reserved event")
                inspect(item)
        elif isinstance(value, list):
            for item in cast(list[Any], value):
                inspect(item)

    for name, path in files.items():
        inspect(_json(path) if name.endswith(".json") else _records(path))
    if (
        summary["counts"].get("reserved_rows") != 0
        or summary["counts"].get("reports") != corpus_summary["source_rows"]
        or summary["counts"].get("new_pairs") != corpus_summary["exact_pairs"]
        or summary["counts"].get("exact_observed_values") != corpus_summary["exact_observed_values"]
    ):
        raise ValueError("recovery counts differ from current corpus")
    delta = _json(files["recovery_delta.json"])
    if len(delta) != len(report_events) or {row["report_id"] for row in delta} != set(
        report_events
    ):
        raise ValueError("recovery delta does not conserve all reports")
    for stem in stems:
        if f"{stem}.csv" not in files:
            continue
        expected_rows = [
            {
                key: json.dumps(value, sort_keys=True)
                if isinstance(value, (list, dict))
                else str(value)
                for key, value in row.items()
            }
            for row in _json(files[f"{stem}.json"])
        ]
        if _records(files[f"{stem}.csv"]) != expected_rows:
            raise ValueError("recovery CSV/JSON content mismatch")
    corpus_targets: list[dict[str, str]] = []
    for relative in corpus_summary["output_sha256"]:
        if Path(relative).name == "target_eligibility.csv.gz":
            corpus_targets.extend(_records(_member(corpus, relative)))
    target_counts: dict[str, int] = {}
    for target, version in versions.items():
        rows = _json(files[target.lower() + ".json"])
        count = len(rows)
        if (
            len({row["report_id"] for row in rows}) != count
            or any(row["target_id"] != target or row["target_version"] != version for row in rows)
            or summary["targets"][target]["target_version"] != version
            or summary["targets"][target]["eligible_reports"] != count
            or corpus_summary["target_eligible"][target] != count
        ):
            raise ValueError("recovery target view/count/version mismatch")
        eligible_ids = {
            row["report_id"]
            for row in corpus_targets
            if row["target_id"] == target
            and row["target_version"] == version
            and _true(row["eligible"])
        }
        if eligible_ids != {row["report_id"] for row in rows}:
            raise ValueError("recovery target view differs from corpus eligibility")
        csv_name = target.lower() + ".csv"
        if csv_name in files and len(_records(files[csv_name])) != count:
            raise ValueError("recovery target CSV/JSON count mismatch")
        target_counts[target] = count
    metadata = dict(
        path="paper/recovery",
        source_directory=_relative(root, folder),
        target_versions=versions,
        target_eligible_reports=target_counts,
        interpretation="Candidate reported targets and descriptive support; no model approval",
        model_eligible=False,
        physical_onset_validated=False,
    )
    return metadata, files, pins


def build(
    root: Path,
    screen: Path,
    selection: Path,
    census: Path,
    design: Path,
    crosswalk: Path,
    corpus: Path,
    waveforms: Path,
    output: Path,
    contours: Path | None = None,
    recovery_design: Path | None = None,
) -> dict[str, Any]:
    """Verify lineage, preserve every report, and publish a new immutable bundle."""
    if output.exists():
        raise FileExistsError(output)
    root = root.resolve()
    screen, selection, census, design, crosswalk, corpus, waveforms = (
        _inside(root, path)
        for path in (screen, selection, census, design, crosswalk, corpus, waveforms)
    )
    frozen, screened = _json(selection), _json(screen)
    material = {key: value for key, value in frozen.items() if key != "selection_sha256"}
    if (
        hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != frozen["selection_sha256"]
    ):
        raise ValueError("frozen selection digest mismatch")
    if (
        hashlib.sha256(json.dumps(screened, sort_keys=True).encode()).hexdigest()
        != frozen["screen_sha256"]
    ):
        raise ValueError("screen does not match frozen selection")
    events = {row["event_id"]: row for row in frozen["events"]}
    if len(events) != len(frozen["events"]) or any(
        row["role"] not in {"development", "sealed_evaluation"} for row in events.values()
    ):
        raise ValueError("invalid event identities or roles")
    development = {eid for eid, row in events.items() if row["role"] == "development"}
    dispositions = screened["dispositions"]
    if len({row["archive_key"] for row in dispositions}) != len(dispositions):
        raise ValueError("duplicate archive disposition")
    if {row["event_id"] for row in dispositions if row["reason"] == "metadata_eligible"} != set(
        events
    ):
        raise ValueError("selection differs from eligible screen identities")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", eid) for eid in events):
        raise ValueError("unsafe event identity")
    for row in dispositions:
        _verify(_inside(root, Path(row["local_path"])), row["source_sha256"])
    summary = _json(corpus / "summary.json")
    if set(summary["events"]) != development:
        raise ValueError("corpus does not account for every development event")
    reports: list[dict[str, Any]] = []
    for relative, digest in summary["output_sha256"].items():
        path = _member(corpus, relative)
        _verify(path, digest)
        if path.name == "arrival_report.csv.gz":
            rows: list[dict[str, Any]] = list(_records(path))
            _assert_development(rows, events)
            reports.extend({**row, "corpus_path": _relative(root, path)} for row in rows)
    if len(reports) != summary["source_rows"] or len({row["report_id"] for row in reports}) != len(
        reports
    ):
        raise ValueError("corpus report accounting mismatch")
    census_rows = _json(census / "rows.json")
    _assert_development(census_rows, events)
    census_ids = {
        f"{row['event_id']}:{row['table_index']}:{row['row_index']}" for row in census_rows
    }
    if census_ids != {row["report_id"] for row in reports}:
        raise ValueError("census and corpus report identities disagree")
    report_events = {row["report_id"]: row["event_id"] for row in reports}
    stations: list[dict[str, Any]] = list(_records(crosswalk / "event_site.csv"))
    _assert_development(stations, events)
    if {row["report_id"] for row in stations} != census_ids:
        raise ValueError("crosswalk must retain every source report")
    for row in stations:
        if report_events[row["report_id"]] != row["event_id"]:
            raise ValueError("crosswalk report event mismatch")
        row["event_station_record_id"] = (
            f"{row['report_id']}:{row['link_code']}:{row['link_sensor']}"
        )
    if len({row["event_station_record_id"] for row in stations}) != len(stations):
        raise ValueError("duplicate event-station index key")
    support = {row["event_id"]: row for row in _records(design / "event_support.csv")}
    _assert_development(list(support.values()), events)
    if set(support) != development:
        raise ValueError("design must account for every development event")
    connectivity = _json(crosswalk / "connectivity.json")
    design_summary = _json(design / "summary.json")
    if "crosswalk" in design_summary["input_sha256"]:
        _verify(
            crosswalk / "unique_report_crosswalk.csv", design_summary["input_sha256"]["crosswalk"]
        )
    for upstream in (connectivity, design_summary, summary):
        for name in ("rows", "census", "links"):
            if name in upstream["input_sha256"]:
                _verify(census / f"{name}.json", upstream["input_sha256"][name])
    unique_path = crosswalk / "unique_report_crosswalk.csv"
    unique: list[dict[str, Any]] = list(_records(unique_path)) if unique_path.exists() else []
    if unique:
        _assert_development(unique, events)
        if len(unique) != len(reports) or {row["report_id"] for row in unique} != census_ids:
            raise ValueError("unique crosswalk report accounting mismatch")
    contour_rows: list[dict[str, Any]] = _json(_inside(root, contours)) if contours else []
    _assert_development(contour_rows, events)
    for row in contour_rows:
        _verify(_inside(root, Path(row["local_path"])), row["raw_sha256"])
        _verify(_inside(root, Path(row["processed_path"])), row["processed_sha256"])
    waveform_manifest = _json(waveforms / "manifest.json")
    sources = _wave_sources(root, waveforms, waveform_manifest, events)
    recovery_metadata: dict[str, Any] = {}
    recovery_files: dict[str, Path] = {}
    recovery_pins: dict[Path, str] = {}
    if recovery_design is not None:
        recovery_metadata, recovery_files, recovery_pins = _recovery_bundle(
            root, recovery_design, corpus, crosswalk, summary, events, report_events
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".multi-event-catalog-", dir=output.parent))
    try:
        viewer, readiness = _viewer(
            root,
            temporary,
            events,
            sources,
            waveform_manifest.get("series_coverage", []),
            contour_rows,
        )
        event_rows: list[dict[str, Any]] = []
        stations_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        unique_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        sources_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in stations:
            stations_by_event[row["event_id"]].append(row)
        for row in unique:
            unique_by_event[row["event_id"]].append(row)
        for row in sources:
            sources_by_event[row.get("event_id", "unknown")].append(row)
        private: list[dict[str, Any]] = []
        for disposition in sorted(dispositions, key=lambda row: row["archive_key"]):
            eid = disposition["event_id"]
            event = events.get(eid, {})
            role = event.get("role", "outside_selected_cohort")
            dev = role == "development"
            row_support = support.get(eid, {}) if dev else {}
            rows = stations_by_event[eid] if dev else []
            fit_sites = {
                row["physical_site_id"]
                for row in rows
                if _true(row.get("fit_eligible"))
                and row["physical_site_id"] != "unknown"
                and (_true(row["explicit_both_values"]) or _true(row["legacy_both_values"]))
            }
            reviewed_pair_sites = {
                row["physical_site_id"]
                for row in unique_by_event[eid]
                if _true(row["site_identity_fit_tier"])
                and _true(row["explicit_both_values"])
                and row["physical_site_id"] != "unknown"
            }
            paired_identity_reports = {
                row["report_id"]
                for row in rows
                if row["identity_tier"] in {"header_exact", "registry_exact"}
                and (_true(row["explicit_both_values"]) or _true(row["legacy_both_values"]))
            }
            status = (
                "metadata_excluded_or_uncertain"
                if not event
                else "sealed_metadata_only"
                if not dev
                else "blocked_pending_independent_identity_and_onset_review"
            )
            entry = {
                "archive_key": disposition["archive_key"],
                "event_id": eid,
                "origin_utc": event.get("usgs_time", disposition.get("usgs_time", "unknown")),
                "role": role,
                "metadata_reason": disposition["reason"],
                "identity_status": disposition["identity_status"],
                "archive_path": disposition["local_path"],
                "archive_sha256": disposition["source_sha256"],
                "archive_url": disposition["url"],
                "data_status": status,
                "corpus_directory": _relative(root, corpus / eid) if dev else "unknown",
                "source_reports": summary["events"][eid]["source_rows"] if dev else "unknown",
                "exact_reported_clock_pairs": summary["events"][eid]["exact_pairs"]
                if dev
                else "unknown",
                "source_pair_values": row_support.get("source_pair_values", "unknown"),
                "paired_header_or_registry_reports": len(paired_identity_reports)
                if dev
                else "unknown",
                "fit_tier_site_count": len(fit_sites) if dev else "unknown",
                "reviewed_explicit_pair_site_count": len(reviewed_pair_sites) if dev else "unknown",
                "stage_d_status": "unassessed_sealed"
                if role == "sealed_evaluation"
                else "not_applicable"
                if not dev
                else "support_met_pending_onset_audit"
                if len(reviewed_pair_sites) >= 5
                else "lt5_independently_accepted_fit_tier_sites",
                "model_eligible": False,
                "waveform_sources": len(sources_by_event[eid]) if dev else "unknown",
                **(
                    readiness.get(eid, {})
                    if dev
                    else {
                        "viewer_ready": False,
                        "viewer_blocked_reason": "outside_development_export",
                    }
                ),
            }
            event_rows.append(entry)
            private.append(
                {
                    **entry,
                    "source_metadata": disposition,
                    "selection_metadata": event or "unknown",
                    "waveform_source_ids": [row["source_id"] for row in sources_by_event[eid]]
                    if dev
                    else [],
                    "contours": [row for row in contour_rows if row["event_id"] == eid],
                }
            )
        event_rows.sort(key=_event_order)
        private.sort(key=_event_order)
        source_rows = [
            {
                **{
                    key: row.get(key, "unknown")
                    for key in (
                        "source_id",
                        "event_id",
                        "purpose",
                        "provider",
                        "sensor",
                        "source_url",
                        "raw_path",
                        "source_sha256",
                        "processing_status",
                        "acquisition_status",
                        "reason",
                        "normalized_path",
                        "output_sha256",
                        "source_rows",
                        "source_bytes",
                        "source_line_count",
                        "station_key",
                        "provider_station_id",
                        "display_station_key",
                        "window_start_utc",
                        "window_stop_utc",
                        "first_timestamp_utc",
                        "last_timestamp_utc",
                        "declared_cadence_seconds",
                        "timing_and_units",
                        "value_states",
                        "timestamp_states",
                        "qc_states",
                        "duplicate_timestamp_rows",
                        "duplicate_timestamp_excess",
                        "gaps_over_declared_cadence",
                        "missing_grid_timestamps",
                        "observed_delta_seconds",
                        "parse_reason",
                        "provider_error",
                        "units",
                        "vertical_datum",
                        "publisher",
                        "crs",
                        "horizontal_datum",
                        "coordinate_order",
                    )
                }
            }
            for row in sources
        ]
        tables = {
            "paper/event_index.csv": event_rows,
            "paper/report_index.csv": sorted(
                reports,
                key=lambda row: (row["event_id"], int(row["table_index"]), int(row["row_index"])),
            ),
            "paper/event_station_index.csv": stations,
            "paper/source_index.csv": source_rows,
            "paper/series_coverage.csv": waveform_manifest.get("series_coverage", []),
        }
        overlaps = _source_url_overlaps(source_rows)
        if overlaps:
            tables["paper/source_url_overlaps.csv"] = overlaps
        if unique:
            tables["paper/unique_report_crosswalk.csv"] = unique
        if contour_rows:
            tables["paper/contour_index.csv"] = contour_rows
        for name in (
            "reviewed_site_incidence",
            "site_degrees",
            "fold_rank",
            "stage_d_pass_rates",
            "cadence_by_era",
        ):
            path = design / f"{name}.csv"
            if path.exists():
                rows = list(_records(path))
                if rows and "event_id" in rows[0]:
                    _assert_development(rows, events)
                tables[f"paper/{name}.csv"] = rows
        dictionary: dict[str, Any] = {
            "schema_version": "multi-event-data-dictionary-v2",
            "conventions": {
                "event_order": (
                    "Private catalog, event_index and viewer events: reviewed canonical UTC "
                    "origin ascending, unknown last, then event_id and archive_key. "
                    "A compound event's canonical origin is a metadata key, "
                    "not arrival attribution."
                ),
                "waveform_order": (
                    "Native source row order is retained, including duplicate timestamps; "
                    "viewer slices filter by supported UTC time without sorting or deduplication."
                ),
                "observation_grain": (
                    "Normalized counts are retained source rows, not unique measurements. "
                    "source_id distinguishes acquisition source/snapshot records. Repeated "
                    "request/capture URLs and hashes can refer to overlapping observations. "
                    "Do not merge on timestamps alone across providers, stations, sensors, "
                    "units or vertical datums. No automatic winner or deduplication is applied."
                ),
                "source_url_overlaps": (
                    "When present, the private overlap table lists every member of repeated "
                    "exact source_url groups, including headers, controls and unavailable "
                    "requests. Unknown URLs are excluded. Equal URLs do not prove equal bytes; "
                    "different URLs can still overlap. This inventory changes no eligibility."
                ),
                "missing_values": (
                    "Derived unknowns use unknown; original source blanks and missing/invalid "
                    "states remain distinct. Zero is a recorded value, never inferred NoData."
                ),
                "units": (
                    "Water levels retain each row/source units and vertical_datum; no common "
                    "datum is inferred. UTC timestamp strings are timezone-qualified. "
                    "Cadence/precision fields ending seconds use seconds; "
                    "longest_supported_minutes uses minutes; counts are dimensionless."
                ),
                "joins": [
                    "archive_key uniquely identifies archive entries; "
                    "unknown event IDs are not join keys.",
                    "Known event_id connects development reports, waveform sources "
                    "and coverage to event_index.",
                    "report_id joins report_index, event_station_index "
                    "and unique_report_crosswalk.",
                    "report_index.source_id identifies the NTWC page in "
                    "catalog.source_metadata, not a waveform.",
                    "series_coverage.source_ids is a JSON array joining source_index.source_id.",
                    "source_url_overlaps.source_id joins source_index.source_id; "
                    "its source_url groups are descriptive, not independent measurements.",
                    "Crosswalk source_ids identify header/registry evidence; "
                    "inspect its bound evidence JSON.",
                    "physical_site_id joins reviewed incidence and site degrees "
                    "only within its declared identity_scope.",
                    "Unknown physical_site_id/deployment_id values "
                    "must not be joined as one shared station.",
                ],
                "gzip": (
                    "CSV.gz assets require gzip decoding. Viewer assets declare media_type and "
                    "content_encoding; decode gzip explicitly rather than relying on server "
                    "headers. SHA256 and compressed_bytes refer to stored bytes; "
                    "uncompressed_bytes is the decoded byte count. identity means no compression."
                ),
            },
            "tables": {},
        }
        for name, rows in tables.items():
            rows = [
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
                for row in rows
            ]
            fields = _write_csv(temporary / name, rows)
            grain, keys = TABLE_GRAINS_KEYS[Path(name).stem]
            dictionary["tables"][name] = {
                "grain": grain,
                "primary_key": keys,
                "ordering": (
                    dictionary["conventions"]["event_order"]
                    if Path(name).stem == "event_index"
                    else "event_id, numeric table_index, numeric row_index; source IDs retained"
                    if Path(name).stem == "report_index"
                    else "Exact source_url lexicographic, then source_id lexicographic"
                    if Path(name).stem == "source_url_overlaps"
                    else "Preserved upstream manifest/design/crosswalk row order"
                ),
                "columns": {
                    field: {
                        "missing_value": "Derived unknowns and original blanks stay distinct",
                        "definition": {
                            "event_id": "Canonical ID; compound key does not attribute arrivals",
                            "origin_utc": "Reviewed canonical USGS origin, or unknown",
                            "report_id": "Event:table:row key; sensor variants remain one report",
                            "event_station_record_id": "Report:code:sensor, not physical site ID",
                            "model_eligible": "Always false; this package is descriptive",
                            "viewer_ready": "Three distinct stations pass display coverage QC",
                            "fit_tier_site_count": "Known physical sites explicitly fit-accepted",
                            "reviewed_explicit_pair_site_count": "Reviewed IDs with source pairs",
                            "stage_d_status": "Identity support only; onset review still pending",
                            "archive_path": "Project-relative private raw NTWC page",
                            "normalized_path": "Project-relative waveform file with digest",
                            "source_id": (
                                "Provenance key: NTWC page for reports; "
                                "acquisition source/snapshot for waveform tables"
                            ),
                            "source_rows": "Retained source rows, not unique measurements",
                            "group_source_count": "Acquisition entries sharing the exact URL",
                            "purpose": (
                                "Declared source use: event_window, quiet_control, "
                                "header_evidence, diagnostic or outside_observation_scope"
                            ),
                            "waveform_sources": (
                                "All associated acquisition entries, including controls, failures "
                                "and metadata-only headers; inspect purpose/processing_status"
                            ),
                            "provider_station_id": (
                                "Provider-qualified identifier; never compare across providers"
                            ),
                            "source_ids": "JSON source-ID array; same-site products stay distinct",
                            "window_start_utc": "Inclusive declared UTC window start",
                            "window_stop_utc": "Exclusive declared UTC window stop",
                            "display_eligible": (
                                "Operational display coverage, not physical-onset validation"
                            ),
                            "qc_states": "JSON object of preserved provider/source QC-state counts",
                            "value_states": "JSON finite, missing or invalid source-value counts",
                            "timestamp_states": "JSON object of source timestamp validation counts",
                        }.get(field, f"Preserved upstream {field}; no reinterpretation"),
                    }
                    for field in fields
                },
            }
        _write_json(
            temporary / "catalog.json",
            {"schema_version": "multi-event-private-catalog-v1", "entries": private},
        )
        if recovery_metadata:
            dictionary["paper_recovery"] = recovery_metadata
            destination = temporary / "paper/recovery"
            destination.mkdir(parents=True)
            for name, path in sorted(recovery_files.items()):
                shutil.copyfile(path, destination / name)
                _verify(destination / name, recovery_pins[path])
        _write_json(temporary / "data_dictionary.json", dictionary)
        inputs = [
            screen,
            selection,
            census / "rows.json",
            census / "links.json",
            design / "summary.json",
            design / "event_support.csv",
            crosswalk / "connectivity.json",
            crosswalk / "event_site.csv",
            corpus / "summary.json",
            waveforms / "manifest.json",
        ]
        if unique:
            inputs.append(unique_path)
        if contours:
            inputs.append(_inside(root, contours))
        inputs.extend(
            design / Path(name).name
            for name in tables
            if name.startswith("paper/") and (design / Path(name).name).exists()
        )
        if recovery_metadata:
            for path, digest in recovery_pins.items():
                _verify(path, digest)
            inputs.extend(recovery_pins)
        result: dict[str, Any] = {
            "schema_version": "multi-event-package-v1",
            "archive_entries": len(dispositions),
            "selected_entries": len(events),
            "development_entries": len(development),
            "sealed_entries": len(events) - len(development),
            "source_reports": len(reports),
            "event_station_rows": len(stations),
            "viewer_events": len(viewer),
            "repeated_source_url_groups": len({row["source_url"] for row in overlaps}),
            "overlap_source_entries": len(overlaps),
            "model_eligible_events": 0,
            "selection_sha256": frozen["selection_sha256"],
            "input_sha256": {_relative(root, path): _sha(path) for path in inputs},
            "output_sha256": {
                str(path.relative_to(temporary)): _sha(path)
                for path in sorted(temporary.rglob("*"))
                if path.is_file()
            },
            "viewer_boundary": (
                "Only viewer/ is exportable to the story; "
                "all sibling files are private paper evidence"
            ),
        }
        if recovery_metadata:
            result["paper_recovery"] = recovery_metadata
        _write_json(temporary / "manifest.json", result)
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--contours", type=Path)
    parser.add_argument(
        "--recovery-design",
        type=Path,
        help="Copy verified candidate target/support tables into paper/recovery only.",
    )
    for name in (
        "screen",
        "selection",
        "census",
        "design",
        "crosswalk",
        "corpus",
        "waveforms",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(
        args.root,
        args.screen,
        args.selection,
        args.census,
        args.design,
        args.crosswalk,
        args.corpus,
        args.waveforms,
        args.output,
        args.contours,
        args.recovery_design,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "archive_entries",
                    "source_reports",
                    "event_station_rows",
                    "viewer_events",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
