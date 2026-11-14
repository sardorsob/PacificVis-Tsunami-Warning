"""Map layers export published contours and coastline without repair."""

import hashlib
import json
import tomllib
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


def _basemap_config(tmp_path: Path, root: Path) -> Path:
    sha = hashlib.sha256((root / "data/raw/natural-earth/coast.geojson").read_bytes()).hexdigest()
    config = tmp_path / "basemap.toml"
    config.write_text(
        'bundle_id = "test-basemap"\ncoastline = "data/raw/natural-earth/coast.geojson"\n'
        f'coastline_sha256 = "{sha}"\ncoastline_source_id = "test-coastline"\n',
        encoding="utf-8",
    )
    return config


def test_basemap_is_the_layers_coastline_format(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    root, _ = inputs
    layers = _export(inputs, tmp_path)
    out = map_layers.export_basemap(
        source_root=root, output_root=tmp_path / "base", config_path=_basemap_config(tmp_path, root)
    )
    assert out == tmp_path / "base/test-basemap/coastline.json"
    assert [p.name for p in out.parent.iterdir()] == ["coastline.json"]
    assert out.read_bytes() == (layers / "coastline.json").read_bytes()  # same input and format


def test_basemap_refuses_a_changed_input_or_an_existing_bundle(
    inputs: tuple[Path, Path], tmp_path: Path
) -> None:
    root, _ = inputs
    config = _basemap_config(tmp_path, root)
    map_layers.export_basemap(source_root=root, output_root=tmp_path / "base", config_path=config)
    with pytest.raises(FileExistsError):
        map_layers.export_basemap(
            source_root=root, output_root=tmp_path / "base", config_path=config
        )
    (root / "data/raw/natural-earth/coast.geojson").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        map_layers.export_basemap(
            source_root=root, output_root=tmp_path / "other", config_path=config
        )


ROOT = Path(__file__).resolve().parents[2]
BUNDLES = ROOT / "app/demo-public/data"
CONTOURS = ROOT / "data/processed/arrival-contours/foundation-v2/manifest.json"


def _same_tree(built: Path, published: Path) -> None:
    names = sorted(p.relative_to(built) for p in built.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(published) for p in published.rglob("*") if p.is_file())
    assert all((built / n).read_bytes() == (published / n).read_bytes() for n in names)


def test_real_basemap_is_natural_earth_110m(tmp_path: Path) -> None:
    config = ROOT / "config/story-basemap.toml"
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if not (ROOT / settings["coastline"]).is_file():
        pytest.skip("local Natural Earth 1:110m coastline unavailable")
    out = map_layers.export_basemap(source_root=ROOT, output_root=tmp_path, config_path=config)
    assert out.relative_to(tmp_path).as_posix() == "basemap-v1/coastline.json"
    value = json.loads(out.read_bytes())
    assert (value["schema_version"], value["source_id"]) == ("1", "natural-earth-110m-coastline")
    assert len(value["closed"]) == len(value["parts"]) > 0
    if (BUNDLES / "basemap-v1").is_dir():
        _same_tree(out.parent, BUNDLES / "basemap-v1")


LAYER_CONFIGS = sorted((ROOT / "config").glob("story-map-layers*.toml"))


@pytest.mark.parametrize("config", LAYER_CONFIGS, ids=[p.stem for p in LAYER_CONFIGS])
def test_real_layers_use_the_published_contour_manifest(config: Path, tmp_path: Path) -> None:
    if not CONTOURS.is_file():
        pytest.skip("local published-contour manifest unavailable")
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    entries = {entry["local_path"]: entry for entry in json.loads(CONTOURS.read_bytes())}
    entry = entries[settings["contours"]]
    assert settings["contours_sha256"] == entry["raw_sha256"]
    assert settings["contour_source_id"] == entry["source_id"]
    if entry["event_id"] != "official20110311054624120_30":  # Tōhoku keeps its v1 bundle
        assert settings["bundle_id"] == f"layers-{entry['event_id']}-v1"
    assert settings["coastline_source_id"] == "natural-earth-50m-coastline"
    if not (ROOT / settings["contours"]).is_file():
        pytest.skip("local raw contour layer unavailable")
    out = map_layers.export_map_layers(source_root=ROOT, output_root=tmp_path, config_path=config)
    if (BUNDLES / out.name).is_dir():
        _same_tree(out, BUNDLES / out.name)


def test_every_non_tohoku_published_layer_has_a_config() -> None:
    if not CONTOURS.is_file():
        pytest.skip("local published-contour manifest unavailable")
    configured = {tomllib.loads(p.read_text(encoding="utf-8"))["contours"] for p in LAYER_CONFIGS}
    assert configured == {entry["local_path"] for entry in json.loads(CONTOURS.read_bytes())}
