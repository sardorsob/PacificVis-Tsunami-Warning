"""The events index pins verified bundles and lists only reviewed development events."""

import hashlib
import json
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from analysis.story.arrivals_export import export_arrivals
from analysis.story.events_index import build_events_index, validate_events_index

ROOT = Path(__file__).resolve().parents[2]
REAL_BUNDLES = ROOT / "app/demo-public/data"
CONFIG = ROOT / "config/story-events.toml"
EXAMPLE = ROOT / "docs/data/examples/story-events.example.json"
ARRIVALS_EXAMPLE = ROOT / "docs/data/examples/story-arrivals.example.json"
GOLDEN_SHA256 = "f824364ccb0528a913c3b8be9f8a8f9c21a8ed80104eb81269a4d509b987fa54"
ORIGIN = "2011-03-11T05:46:24.120Z"
EVENT: dict[str, Any] = {
    "event_id": "ev-1",
    "origin_time_utc": ORIGIN,
    "latitude": 38.297,
    "longitude": 142.373,
}


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _a(value: dict[str, Any]) -> Any:
    return value["events"][0]


def _b(value: dict[str, Any]) -> Any:
    return value["events"][1]


def _copy_tohoku_bundles(root: Path) -> None:
    names = ("tohoku-descriptive-demo-v2", "tohoku-story-layers-v1")
    if not all((REAL_BUNDLES / name / "manifest.json").is_file() for name in names):
        pytest.skip("local Tōhoku demo bundles unavailable")
    for name in names:
        shutil.copytree(REAL_BUNDLES / name, root / name)


def test_builds_the_pinned_tohoku_index_without_arrivals(tmp_path: Path) -> None:
    _copy_tohoku_bundles(tmp_path)
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    config = tmp_path / "events.toml"
    config.write_text(
        "\n".join(line for line in lines if not line.startswith("arrivals = ")) + "\n",
        encoding="utf-8",
    )
    out = build_events_index(bundles_root=tmp_path, config_path=config)
    data = out.read_bytes()
    assert out == tmp_path / "events.json"
    assert (len(data), hashlib.sha256(data).hexdigest()) == (652, GOLDEN_SHA256)


def test_builds_the_tohoku_index_with_arrivals(tmp_path: Path) -> None:
    if not (ROOT / "data/processed/arrival-evidence/foundation-v1/manifest.json").is_file():
        pytest.skip("local released arrival-evidence tables unavailable")
    _copy_tohoku_bundles(tmp_path)
    arrivals = export_arrivals(
        source_root=ROOT, output_root=tmp_path, config_path=ROOT / "config/story-arrivals.toml"
    )
    index = json.loads(build_events_index(bundles_root=tmp_path, config_path=CONFIG).read_bytes())
    validate_events_index(index)
    data = (arrivals / "official20110311054624120_30.json").read_bytes()
    assert [event["arrivals"] for event in index["events"]] == [
        {
            "path": "story-arrivals-v1/official20110311054624120_30.json",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
    ]


def test_accepts_the_shared_example() -> None:
    validate_events_index(_example())


def test_orders_by_instant_not_string() -> None:
    value = _example()
    _a(value)["origin_time_utc"] = "2002-02-02T12:00:00Z"
    _b(value)["origin_time_utc"] = "2002-02-02T12:00:00.500Z"  # sorts first as a string
    validate_events_index(value)


MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], object]]] = [
    ("unknown default", lambda v: v.update(default_event_id="example-event-c")),
    ("duplicate event id", lambda v: _b(v).update(event_id="example-event-a", arrivals=None)),
    ("events reversed", lambda v: v["events"].reverse()),
    (
        "string order is not instant order",
        lambda v: (
            _a(v).update(origin_time_utc="2002-02-02T12:00:00.500Z"),
            _b(v).update(origin_time_utc="2002-02-02T12:00:00Z"),
        ),
    ),
    (
        "same instant, ids out of order",
        lambda v: (_a(v).update(origin_time_utc=_b(v)["origin_time_utc"]), v["events"].reverse()),
    ),
    (
        "arrivals path leaves root",
        lambda v: _a(v)["arrivals"].update(path="../story-arrivals-v1/example-event-a.json"),
    ),
    (
        "absolute arrivals path",
        lambda v: _a(v)["arrivals"].update(path="/story-arrivals-v1/example-event-a.json"),
    ),
    ("nested arrivals path", lambda v: _a(v)["arrivals"].update(path="a/b/example-event-a.json")),
    ("arrivals path without dir", lambda v: _a(v)["arrivals"].update(path="example-event-a.json")),
    (
        "arrivals file named for another event",
        lambda v: _a(v)["arrivals"].update(path="story-arrivals-v1/example-event-b.json"),
    ),
    ("arrivals file too large", lambda v: _a(v)["arrivals"].update(bytes=2_097_153)),
    ("uppercase hash", lambda v: _a(v)["records"].update(manifest_sha256="A" * 64)),
    ("short hash", lambda v: _a(v)["arrivals"].update(sha256="c" * 63)),
    ("zero bytes", lambda v: _a(v)["layers"].update(manifest_bytes=0)),
    ("negative bytes", lambda v: _a(v)["arrivals"].update(bytes=-1)),
    ("boolean bytes", lambda v: _a(v)["records"].update(manifest_bytes=True)),
    ("bundle shared by two events", lambda v: _b(v).update(records=dict(_a(v)["records"]))),
    ("unsafe bundle id", lambda v: _a(v)["layers"].update(bundle_id="../layers")),
    ("latitude out of range", lambda v: _a(v).update(latitude=90.5)),
    ("longitude out of range", lambda v: _b(v).update(longitude=-180.5)),
    ("nonfinite magnitude", lambda v: _a(v).update(magnitude=float("nan"))),
    ("boolean latitude", lambda v: _a(v).update(latitude=True)),
    ("empty label", lambda v: _a(v).update(label="")),
    ("empty magnitude type", lambda v: _b(v).update(magnitude_type="")),
    ("offset origin", lambda v: _a(v).update(origin_time_utc="2001-01-01T00:00:00+00:00")),
    ("7-digit fraction", lambda v: _b(v).update(origin_time_utc="2002-02-02T12:00:00.5000000Z")),
    ("impossible date", lambda v: _a(v).update(origin_time_utc="2001-02-30T00:00:00Z")),
    ("wrong schema version", lambda v: v.update(schema_version="2")),
    ("wrong evidence state", lambda v: v.update(evidence_state="public")),
    ("extra top-level key", lambda v: v.update(generated_at="2026-11-13")),
    ("extra event key", lambda v: _a(v).update(role="development")),
    ("extra bundle key", lambda v: _a(v)["records"].update(path="manifest.json")),
    ("missing top-level key", lambda v: v.pop("evidence_state")),
    ("missing event key", lambda v: _b(v).pop("arrivals")),
    ("missing asset key", lambda v: _a(v)["arrivals"].pop("bytes")),
]


@pytest.mark.parametrize("mutate", [m for _, m in MUTATIONS], ids=[name for name, _ in MUTATIONS])
def test_rejects_mutated_index(mutate: Callable[[dict[str, Any]], object]) -> None:
    value = _example()
    mutate(value)
    with pytest.raises(ValueError):
        validate_events_index(value)


def _write_bundle(root: Path, bundle_id: str, identity: dict[str, Any]) -> None:
    asset = root / bundle_id / "data/part.json"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b'{"x":1}\n')
    manifest = {
        "bundle_id": bundle_id,
        "assets": [
            {
                "path": "data/part.json",
                "bytes": asset.stat().st_size,
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            }
        ],
        **identity,
    }
    (root / bundle_id / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def bundles(tmp_path: Path) -> Path:
    root = tmp_path / "bundles"
    _write_bundle(root, "rec", {"event": EVENT})
    _write_bundle(root, "lay", {"origin_time_utc": ORIGIN})
    return root


def _config(tmp_path: Path, **overrides: object) -> Path:
    entry: dict[str, object] = {
        **EVENT,
        "label": "Event one",
        "magnitude": 9.1,
        "magnitude_type": "mww",
        "records_bundle": "rec",
        "layers_bundle": "lay",
        **overrides,
    }
    lines = [f"default_event_id = {json.dumps(entry['event_id'])}", "[[events]]"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in entry.items() if value is not None]
    path = tmp_path / "events.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build(bundles: Path, config: Path, *, replace: bool = False) -> Path:
    return build_events_index(bundles_root=bundles, config_path=config, replace=replace)


def _names(root: Path) -> list[str]:
    return sorted(path.name for path in root.iterdir())


def test_pins_manifests_in_compact_sorted_json(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path))
    data = out.read_bytes()
    index = json.loads(data)
    manifest = (bundles / "rec/manifest.json").read_bytes()
    assert index["events"][0]["records"] == {
        "bundle_id": "rec",
        "manifest_bytes": len(manifest),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
    assert index["events"][0]["arrivals"] is None
    assert (
        data
        == (
            json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    )
    assert _names(bundles) == ["events.json", "lay", "rec"]


def test_absent_bundles_become_null(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path, records_bundle=None, layers_bundle=None))
    event = json.loads(out.read_bytes())["events"][0]
    assert (event["records"], event["layers"]) == (None, None)


@pytest.mark.parametrize("content", [b'{"x":1}\n\n', b'{"x":2}\n'], ids=["bytes", "sha256"])
def test_refuses_an_asset_that_differs_from_its_manifest(
    bundles: Path, tmp_path: Path, content: bytes
) -> None:
    (bundles / "lay/data/part.json").write_bytes(content)
    with pytest.raises(ValueError, match="differs from its manifest"):
        _build(bundles, _config(tmp_path))
    assert not (bundles / "events.json").exists()


def test_refuses_a_records_event_that_differs_from_the_entry(bundles: Path, tmp_path: Path) -> None:
    _write_bundle(bundles, "rec", {"event": {**EVENT, "latitude": 38.3}})
    with pytest.raises(ValueError, match="records manifest event"):
        _build(bundles, _config(tmp_path))


def test_refuses_a_layers_origin_that_differs_from_the_entry(bundles: Path, tmp_path: Path) -> None:
    _write_bundle(bundles, "lay", {"origin_time_utc": "2011-03-11T05:46:24.12Z"})
    with pytest.raises(ValueError, match="layers manifest origin"):
        _build(bundles, _config(tmp_path))


def test_refuses_a_manifest_named_for_another_bundle(bundles: Path, tmp_path: Path) -> None:
    _write_bundle(bundles, "rec", {"event": EVENT, "bundle_id": "other"})
    with pytest.raises(ValueError, match="bundle_id differs"):
        _build(bundles, _config(tmp_path))


def test_refuses_an_asset_path_outside_its_bundle(bundles: Path, tmp_path: Path) -> None:
    manifest_path = bundles / "lay/manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"][0]["path"] = "../rec/data/part.json"  # same bytes and hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        _build(bundles, _config(tmp_path))


def test_refuses_a_bundle_directory_outside_the_root(bundles: Path, tmp_path: Path) -> None:
    shutil.move(bundles / "lay", tmp_path / "lay")
    (bundles / "lay").symlink_to(tmp_path / "lay")
    with pytest.raises(ValueError, match="escapes"):
        _build(bundles, _config(tmp_path))


@pytest.mark.parametrize(
    "override",
    [{"records_bundle": "../bundles/rec"}, {"layer_bundle": "lay"}],
    ids=["unsafe bundle name", "unknown key"],
)
def test_refuses_a_bad_config_entry(
    bundles: Path, tmp_path: Path, override: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        _build(bundles, _config(tmp_path, **override))


EXAMPLE_ARRIVALS = "story-arrivals-v1/example-event-a.json"


def _arrivals_config(bundles: Path, tmp_path: Path, **overrides: object) -> Path:
    """The shared arrivals example, its records bundle and a config entry naming both."""
    value = json.loads(ARRIVALS_EXAMPLE.read_text(encoding="utf-8"))
    identity = {
        "event_id": value["event_id"],
        "origin_time_utc": value["origin_time_utc"],
        "latitude": 0.0,
        "longitude": -160.0,
    }
    stations = [{"station_id": "0000001"}, {"station_id": "0000002"}]
    _write_bundle(bundles, "rec-a", {"event": identity, "stations": stations})
    _write_arrivals(bundles, value)
    settings: dict[str, object] = {
        **identity,
        "records_bundle": "rec-a",
        "layers_bundle": None,
        "arrivals": EXAMPLE_ARRIVALS,
    }
    return _config(tmp_path, **(settings | overrides))


def _write_arrivals(bundles: Path, value: dict[str, Any]) -> None:
    path = bundles / EXAMPLE_ARRIVALS
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def test_pins_and_accepts_a_valid_arrivals_file(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _arrivals_config(bundles, tmp_path))
    data = (bundles / EXAMPLE_ARRIVALS).read_bytes()
    assert json.loads(out.read_bytes())["events"][0]["arrivals"] == {
        "path": EXAMPLE_ARRIVALS,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _mutated_arrivals(bundles: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    value = json.loads((bundles / EXAMPLE_ARRIVALS).read_bytes())
    mutate(value)
    _write_arrivals(bundles, value)


BAD_ARRIVALS: list[tuple[str, Callable[[dict[str, Any]], object], str]] = [
    (
        "record names an unknown station",
        lambda v: v["places"][1]["record"].update(station_id="0000009"),  # a within_1km link
        "record",
    ),
    ("another event", lambda v: v.update(event_id="example-event-b"), "arrivals event differs"),
    ("invalid file", lambda v: v["release"].update(arrival_comparison_allowed=True), "release"),
]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [(mutate, match) for _, mutate, match in BAD_ARRIVALS],
    ids=[name for name, _, _ in BAD_ARRIVALS],
)
def test_refuses_a_bad_arrivals_file(
    bundles: Path, tmp_path: Path, mutate: Callable[[dict[str, Any]], object], match: str
) -> None:
    config = _arrivals_config(bundles, tmp_path)
    _mutated_arrivals(bundles, mutate)
    with pytest.raises(ValueError, match=match):
        _build(bundles, config)
    assert not (bundles / "events.json").exists()


def test_refuses_record_links_without_a_records_bundle(bundles: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="record"):
        _build(bundles, _arrivals_config(bundles, tmp_path, records_bundle=None))
    assert not (bundles / "events.json").exists()


def test_refuses_an_arrivals_name_outside_the_root(bundles: Path, tmp_path: Path) -> None:
    config = _arrivals_config(
        bundles, tmp_path, arrivals="../story-arrivals-v1/example-event-a.json"
    )
    with pytest.raises(ValueError):
        _build(bundles, config)


def test_leaves_an_identical_index_untouched(bundles: Path, tmp_path: Path) -> None:
    config = _config(tmp_path)
    out = _build(bundles, config)
    before = out.stat()
    assert _build(bundles, config) == out
    after = out.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert _names(bundles) == ["events.json", "lay", "rec"]


def test_replaces_a_different_index_only_when_asked(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path))
    old, inode = out.read_bytes(), out.stat().st_ino
    changed = _config(tmp_path, label="Event one, relabelled")
    with pytest.raises(FileExistsError):
        _build(bundles, changed)
    assert out.read_bytes() == old
    assert _build(bundles, changed, replace=True) == out
    assert json.loads(out.read_bytes())["events"][0]["label"] == "Event one, relabelled"
    assert out.stat().st_ino != inode  # renamed into place, not rewritten in place
    assert _names(bundles) == ["events.json", "lay", "rec"]


@pytest.mark.parametrize("replace", [False, True])
def test_refuses_a_symlinked_index(bundles: Path, tmp_path: Path, replace: bool) -> None:
    config = _config(tmp_path)
    target = tmp_path / "elsewhere.json"
    out = _build(bundles, config)
    target.write_bytes(out.read_bytes())  # identical bytes behind the link
    out.unlink()
    out.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        _build(bundles, config, replace=replace)
    assert out.is_symlink()


def _story_event_ids() -> list[str]:
    events: list[dict[str, Any]] = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["events"]
    return [event["event_id"] for event in events]


def _batch_entries() -> dict[str, dict[str, Any]]:
    path = ROOT / "config/ntwc-archive-batch-v2.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))["events"]


def _require_development(event_ids: list[str]) -> None:
    # The guard reports no IDs, so no reserved or excluded entry is ever printed.
    entries = _batch_entries()
    if not all(entries.get(event_id, {}).get("role") == "development" for event_id in event_ids):
        raise ValueError("a story event is not a development entry of the frozen selection")


def _another_role_id() -> str:
    return next(i for i, entry in _batch_entries().items() if entry["role"] != "development")


def test_story_events_are_development_entries() -> None:
    _require_development(_story_event_ids())


def test_development_guard_rejects_another_role() -> None:
    event_ids = _story_event_ids()
    event_ids[0] = _another_role_id()
    with pytest.raises(ValueError):
        _require_development(event_ids)
