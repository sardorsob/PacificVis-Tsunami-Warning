"""Map layers export published contours and coastline without repair."""

import hashlib
import json
from pathlib import Path

import pytest

from analysis.story import map_layers


def _write(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contour(
    object_id: int, hours: int, index: str | None, geometry: dict[str, object]
) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, "HOURS": hours, "Name": "2011 Japan", "Index": index},
        "geometry": geometry,
    }


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "source"
    contours = {
        "type": "FeatureCollection",
        "features": [
            _contour(
                20,
                5,
                "Y",
                {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[180.2, 10.0], [-179.0, 11.0]],
                        [[10.0, 0.0], [30.0, 0.0]],
                    ],
                },
            ),
            _contour(
                4, 1, None, {"type": "LineString", "coordinates": [[142.0, 38.0], [143.0, 39.0]]}
            ),
        ],
    }
    coastline = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-155.0, 19.0], [-154.0, 20.0], [-155.0, 21.0], [-155.0, 19.0]],
                },
            }
        ],
    }
    contour_sha = _write(root / "data/raw/ncei/contours.geojson", contours)
    coast_sha = _write(root / "data/raw/natural-earth/coast.geojson", coastline)
    config = tmp_path / "layers.toml"
    config.write_text(
        'schema_version = "1"\nbundle_id = "test-layers"\n'
        'origin_time_utc = "2011-03-11T05:46:24.120Z"\n'
        f'contours = "data/raw/ncei/contours.geojson"\ncontours_sha256 = "{contour_sha}"\n'
        'contour_source_id = "test-contours"\n'
        f'coastline = "data/raw/natural-earth/coast.geojson"\ncoastline_sha256 = "{coast_sha}"\n'
        'coastline_source_id = "test-coastline"\n',
        encoding="utf-8",
    )
    return root, config


def _export(inputs: tuple[Path, Path], tmp_path: Path) -> Path:
    root, config = inputs
    return map_layers.export_map_layers(
        source_root=root, output_root=tmp_path / "out", config_path=config
    )


def test_exports_projected_layers_with_accounting(
    inputs: tuple[Path, Path], tmp_path: Path
) -> None:
    out = _export(inputs, tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    contours = json.loads((out / "contours.json").read_text(encoding="utf-8"))
    assert manifest["accounting"]["contour_features"] == 2
    assert manifest["accounting"]["hours"] == [1, 5]
    assert [f["hours"] for f in contours["features"]] == [1, 5]
    assert [f["index"] for f in contours["features"]] == [False, True]
    assert manifest["accounting"]["contour_parts"] == 4
    assert all(
        isinstance(v, int) for part in contours["features"][0]["parts"] for p in part for v in p
    )
    assert {a["path"] for a in manifest["assets"]} == {"contours.json", "coastline.json"}
    assert "not a station arrival" in manifest["statement"].lower()
    coast = json.loads((out / "coastline.json").read_text(encoding="utf-8"))
    assert coast["closed"] == [True]


def test_keeps_vertices_past_180_and_splits_only_at_the_display_seam(
    inputs: tuple[Path, Path], tmp_path: Path
) -> None:
    out = _export(inputs, tmp_path)
    five = json.loads((out / "contours.json").read_text(encoding="utf-8"))["features"][1]
    assert len(five["parts"]) == 3  # 180.2°E→179°W stays whole; 10°E→30°E splits at 20°E
    assert len(five["parts"][0]) == 2  # the 180.2° vertex is kept, not clamped or dropped
    xs = [p[0] for part in five["parts"] for p in part]
    assert min(xs) < 0 < max(xs)


def test_refuses_checksum_mismatch(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    root, _ = inputs
    (root / "data/raw/ncei/contours.geojson").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        _export(inputs, tmp_path)


def test_refuses_an_existing_bundle(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    _export(inputs, tmp_path)
    with pytest.raises(FileExistsError):
        _export(inputs, tmp_path)
