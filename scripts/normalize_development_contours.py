"""Validate published contours without interpolating fields or changing geometry."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.acquisition import load_contracts  # noqa: E402
from scripts.prepare_ntwc_batch import write_identical_or_new  # noqa: E402


def validated_features(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Check the complete response and retain documented boundary precision."""
    if payload.get("type") != "FeatureCollection" or payload.get("exceededTransferLimit"):
        raise ValueError("not a complete FeatureCollection")
    features = payload["features"]
    ids: set[int] = set()
    counts = {
        "features": len(features),
        "vertices": 0,
        "boundary_precision_vertices": 0,
        "antimeridian_segments": 0,
    }
    for feature in features:
        props = feature["properties"]
        oid, hours = props["OBJECTID"], props["HOURS"]
        if (
            oid in ids
            or not isinstance(hours, (int, float))
            or not math.isfinite(hours)
            or hours <= 0
        ):
            raise ValueError("duplicate feature ID or invalid travel hours")
        ids.add(oid)
        geometry = feature["geometry"]
        if geometry["type"] not in {"LineString", "MultiLineString"}:
            raise ValueError("unexpected geometry type")
        lines = (
            geometry["coordinates"]
            if geometry["type"] == "MultiLineString"
            else [geometry["coordinates"]]
        )
        for line in lines:
            if len(line) < 2:
                raise ValueError("line has fewer than two vertices")
            previous = None
            for lon, lat in line:
                if (
                    not math.isfinite(lon)
                    or not math.isfinite(lat)
                    or abs(lon) > 180 + 1e-8
                    or abs(lat) > 90
                ):
                    raise ValueError("invalid longitude/latitude")
                counts["vertices"] += 1
                counts["boundary_precision_vertices"] += int(abs(lon) > 180)
                if previous is not None:
                    counts["antimeridian_segments"] += int(abs(lon - previous) > 180)
                previous = lon
    return sorted(features, key=lambda item: item["properties"]["OBJECTID"]), counts


def main() -> None:
    """Write immutable per-event GeoJSON and a source-backed catalog."""
    root = Path(__file__).resolve().parents[1]
    mapping = json.loads(
        (root / "artifacts/generated/ntwc-batch/contour-source-map.json").read_text()
    )
    contracts = {
        item.source_id: item
        for item in load_contracts(root / "config/ncei-development-contours.toml")
    }
    selection = json.loads(
        (root / "artifacts/generated/ntwc-batch/screen-v1/selection-v2.json").read_text(
            encoding="utf-8"
        )
    )
    material = {key: value for key, value in selection.items() if key != "selection_sha256"}
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != selection["selection_sha256"]:
        raise ValueError("frozen selection digest mismatch")
    development = {row["event_id"] for row in selection["events"] if row["role"] == "development"}
    output = root / "data/processed/arrival-contours/foundation-v2"
    output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for source in mapping:
        if not source["source_id"].endswith("geojson"):
            continue
        if source["event_id"] not in development or source["local_path"] != str(
            contracts[source["source_id"]].local_path
        ):
            raise ValueError("contour outside frozen development/source contract")
        path = root / source["local_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.with_name(path.name + ".sha256").read_text().split()[0] != digest:
            raise ValueError("raw checksum mismatch")
        payload = json.loads(path.read_text())
        features, counts = validated_features(payload)
        metadata_source = next(
            row
            for row in mapping
            if row["event_id"] == source["event_id"] and row["source_id"].endswith("metadata")
        )
        metadata_path = root / metadata_source["local_path"]
        if metadata_source["local_path"] != str(contracts[metadata_source["source_id"]].local_path):
            raise ValueError("metadata differs from source contract")
        if (
            hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            != metadata_path.with_name(metadata_path.name + ".sha256")
            .read_text(encoding="utf-8")
            .strip()
        ):
            raise ValueError("metadata checksum mismatch")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["name"] != source["layer_name"] or len(features) >= metadata["maxRecordCount"]:
            raise ValueError("layer identity mismatch or possible record truncation")
        target = output / f"{source['event_id']}.geojson"
        text = (
            json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
            + "\n"
        )
        write_identical_or_new(target, text)
        manifest.append(
            {
                **source,
                "source_url": contracts[source["source_id"]].url,
                **counts,
                "raw_sha256": digest,
                "processed_path": str(target.relative_to(root)),
                "processed_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "units": "hours",
                "coordinate_order": "longitude, latitude",
                "crs": "EPSG:4326 requested from service",
                "horizontal_datum": "unknown",
                "origin_reference": (
                    "source-specific, not independently reconciled with NTWC estimates"
                ),
                "processing": (
                    "feature ordering only; no coordinate repair, resampling or interpolation"
                ),
                "ntwc_prediction_equivalence_verified": False,
            }
        )
    write_identical_or_new(
        output / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps({"events": len(manifest), "features": sum(row["features"] for row in manifest)})
    )


if __name__ == "__main__":
    main()
