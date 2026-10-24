"""Export published contours and coastline as an immutable browser layer bundle.

Projection matches the demo geometry; lines split at the 20°E display seam;
coordinates rounded to whole metres. No simplification, smoothing or clamping.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analysis.story.atlas import DISPLAY_CRS, project_line_parts, split_at_display_seam
from analysis.story.plots import _load_coastline_parts  # pyright: ignore[reportPrivateUsage]

STATEMENT = (
    "NOAA/NCEI published tsunami travel-time contours: hours after the earthquake, "
    "computed from a point at the epicentre (not the full rupture), first arrival only, "
    "no wave height. Not a station arrival, not the NCTR field and not warning time."
)
HOURS_SEMANTICS = (
    "First-arrival travel time after tsunami generation at the epicentre, per the NCEI "
    "travel-time maps page; hour 0 is equated with the USGS origin time."
)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _input(root: Path, relative: str, sha256: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError("source path escapes explicit source root")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or _hash(path) != sha256:
        raise ValueError(f"checksum mismatch: {relative}")
    return path


def _round(parts: Sequence[Sequence[tuple[float, float]]]) -> list[list[list[int]]]:
    return [[[round(x), round(y)] for x, y in part] for part in parts]


def _contours(path: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["features"]
    out: list[dict[str, Any]] = []
    for feature in sorted(
        features, key=lambda f: (f["properties"]["HOURS"], f["properties"]["OBJECTID"])
    ):
        geometry = feature["geometry"]
        if geometry["type"] == "LineString":
            lines = [geometry["coordinates"]]
        elif geometry["type"] == "MultiLineString":
            lines = geometry["coordinates"]
        else:
            raise ValueError("contours must be LineString or MultiLineString")
        seam = tuple(
            part
            for line in lines
            for part in split_at_display_seam(tuple((float(x), float(y)) for x, y in line))
        )
        out.append(
            {
                "hours": int(feature["properties"]["HOURS"]),
                "index": feature["properties"]["Index"] == "Y",
                "parts": _round(project_line_parts(seam, DISPLAY_CRS)),
            }
        )
    return out


def export_map_layers(*, source_root: Path, output_root: Path, config_path: Path) -> Path:
    """Verify inputs and atomically write a new layers bundle; never overwrite one.

    Raises ValueError for unsafe or changed inputs and FileExistsError for an
    existing bundle. Work is linear in the number of vertices.
    """
    if not source_root.is_absolute() or not source_root.is_dir():
        raise ValueError("explicit absolute source root is required")
    source_root = source_root.resolve()
    config_bytes = config_path.read_bytes()
    settings = tomllib.loads(config_bytes.decode("utf-8"))
    if settings["schema_version"] != "1" or not re.fullmatch(
        r"[a-zA-Z0-9_-]+", settings["bundle_id"]
    ):
        raise ValueError("unsupported schema or unsafe bundle ID")
    contour_path = _input(source_root, settings["contours"], settings["contours_sha256"])
    coast_path = _input(source_root, settings["coastline"], settings["coastline_sha256"])
    output_root = output_root.resolve()
    destination = output_root / settings["bundle_id"]
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    features = _contours(contour_path)
    coast_parts = _round(
        project_line_parts(
            tuple(
                part
                for line in _load_coastline_parts(coast_path)
                for part in split_at_display_seam(line)
            ),
            DISPLAY_CRS,
        )
    )
    contours = {
        "schema_version": "1",
        "source_id": settings["contour_source_id"],
        "features": features,
    }
    coastline = {
        "schema_version": "1",
        "source_id": settings["coastline_source_id"],
        "parts": coast_parts,
        "closed": [len(part) > 3 and part[0] == part[-1] for part in coast_parts],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{settings['bundle_id']}-", dir=output_root
    ) as temporary:
        staging = Path(temporary)
        _write_json(staging / "contours.json", contours)
        _write_json(staging / "coastline.json", coastline)
        assets = [
            {"path": path.name, "sha256": _hash(path), "bytes": path.stat().st_size}
            for path in sorted(staging.glob("*.json"))
        ]
        _write_json(
            staging / "manifest.json",
            {
                "schema_version": "1",
                "exporter_version": "1",
                "bundle_id": settings["bundle_id"],
                "evidence_state": "internal_descriptive_only",
                "display_crs": DISPLAY_CRS,
                "central_meridian": -160,
                "coordinate_order": "x,y",
                "units": "metres (rounded to whole metres)",
                "statement": STATEMENT,
                "contour_source_id": settings["contour_source_id"],
                "coastline_source_id": settings["coastline_source_id"],
                "origin_time_utc": settings["origin_time_utc"],
                "hours_semantics": HOURS_SEMANTICS,
                "assets": assets,
                "input_fingerprints": [
                    {"path": settings["contours"], "sha256": settings["contours_sha256"]},
                    {"path": settings["coastline"], "sha256": settings["coastline_sha256"]},
                ],
                "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
                "accounting": {
                    "contour_features": len(features),
                    "contour_parts": sum(len(f["parts"]) for f in features),
                    "contour_vertices": sum(len(part) for f in features for part in f["parts"]),
                    "hours": sorted({f["hours"] for f in features}),
                    "coastline_parts": len(coast_parts),
                },
            },
        )
        # Recheck immutable inputs before publication; no partial bundle becomes visible.
        _input(source_root, settings["contours"], settings["contours_sha256"])
        _input(source_root, settings["coastline"], settings["coastline_sha256"])
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        staging.rename(destination)
    return destination


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )
