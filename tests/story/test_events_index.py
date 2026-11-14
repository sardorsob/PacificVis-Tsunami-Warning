"""The events index (schema 2) pins verified bundles and lists only reviewed development events."""

import csv
import gzip
import hashlib
import json
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from analysis.story import events_index
from analysis.story.events_index import build_events_index, validate_events_index

ROOT = Path(__file__).resolve().parents[2]
REAL_BUNDLES = ROOT / "app/demo-public/data"
CONFIG = ROOT / "config/story-events.toml"
NAMES = ROOT / "config/story-event-names.csv"
EXAMPLE = ROOT / "docs/data/examples/story-events.example.json"
ARRIVALS_EXAMPLE = ROOT / "docs/data/examples/story-arrivals.example.json"
GOLDEN_SHA256 = "6518cc592c1bf865fef552d3daed623848f67d3ab63aa73fd51b7ecae63c11cc"
TOHOKU = "official20110311054624120_30"
ORIGIN = "2011-03-11T05:46:24.120Z"
REASON = "no_records_and_no_drawable_reported_time"
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


def _settings() -> dict[str, Any]:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def _labels(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["event_id"]: row["label"] for row in csv.DictReader(stream)}


# The real index, re-pinned by SHA-256.


def _copy_real_bundles(root: Path) -> None:
    settings = _settings()
    names = {settings["basemap"].split("/")[0]}
    for entry in settings["events"]:
        names |= {entry[key] for key in ("records_bundle", "layers_bundle") if key in entry}
        if "arrivals" in entry:
            names.add(entry["arrivals"].split("/")[0])
    if not all((REAL_BUNDLES / name).is_dir() for name in names):
        pytest.skip("local story bundles unavailable")
    for name in sorted(names):
        shutil.copytree(REAL_BUNDLES / name, root / name)


def test_builds_the_pinned_real_index_and_report(tmp_path: Path) -> None:
    root = tmp_path / "bundles"
    _copy_real_bundles(root)
    out = build_events_index(
        bundles_root=root, config_path=CONFIG, report_path=tmp_path / "report.json"
    )
    data = out.read_bytes()
    assert hashlib.sha256(data).hexdigest() == GOLDEN_SHA256
    if (REAL_BUNDLES / "events.json").is_file():
        assert (REAL_BUNDLES / "events.json").read_bytes() == data
    index = json.loads(data)
    validate_events_index(index)
    report = json.loads((tmp_path / "report.json").read_bytes())
    listed = {event["event_id"]: event for event in index["events"]}
    labels = _labels(NAMES)
    assert {event_id: event["label"] for event_id, event in listed.items()} == labels
    excluded = [item["event_id"] for item in report["excluded"]]
    assert sorted([*listed, *excluded]) == sorted(e["event_id"] for e in _settings()["events"])
    assert excluded == sorted(excluded)
    assert {item["reason"] for item in report["excluded"]} == {REASON}
    sizes = {item["path"]: item["bytes"] for item in report["files"]}
    assert sizes["events.json"] == len(data)
    assert report["totals"] == {
        "listed_events": len(listed),
        "excluded_events": len(excluded),
        "bytes": sum(sizes.values()),
    }
    tohoku = listed[TOHOKU]
    assert index["default_event_id"] == TOHOKU
    assert (tohoku["origin_time_utc"], tohoku["latitude"], tohoku["longitude"]) == (
        ORIGIN,
        38.297,
        142.373,
    )


# The shared example and its mutations.


def test_accepts_the_shared_example() -> None:
    validate_events_index(_example())


def test_orders_by_instant_not_string() -> None:
    value = _example()
    _a(value)["origin_time_utc"] = "2002-02-02T12:00:00Z"
    _b(value)["origin_time_utc"] = "2002-02-02T12:00:00.500Z"  # sorts first as a string
    validate_events_index(value)


def _hour(value: dict[str, Any], source: str, hour: int, count: int) -> None:
    _a(value)["counts"]["reported_per_hour"][source][hour] = count


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
    ("schema 1", lambda v: v.update(schema_version="1")),
    ("wrong evidence state", lambda v: v.update(evidence_state="public")),
    ("extra top-level key", lambda v: v.update(generated_at="2026-11-13")),
    ("extra event key", lambda v: _a(v).update(role="development")),
    ("extra bundle key", lambda v: _a(v)["records"].update(path="manifest.json")),
    ("missing top-level key", lambda v: v.pop("evidence_state")),
    ("missing event key", lambda v: _b(v).pop("arrivals")),
    ("missing asset key", lambda v: _a(v)["arrivals"].pop("bytes")),
    # Schema 2: basemap, projected epicentre and counts.
    ("missing basemap", lambda v: v.pop("basemap")),
    ("basemap named otherwise", lambda v: v["basemap"].update(path="basemap-v1/coast.json")),
    (
        "basemap path leaves root",
        lambda v: v["basemap"].update(path="../basemap-v1/coastline.json"),
    ),
    ("basemap too large", lambda v: v["basemap"].update(bytes=2_097_153)),
    ("non-integer x", lambda v: _a(v).update(x=0.5)),
    ("float-valued y", lambda v: _b(v).update(y=-2605574.0)),
    ("boolean x", lambda v: _a(v).update(x=False)),
    ("missing counts", lambda v: _a(v).pop("counts")),
    ("extra count", lambda v: _a(v)["counts"].update(places=1)),
    ("negative count", lambda v: _a(v)["counts"].update(ncei_reported=-1)),
    ("float count", lambda v: _a(v)["counts"].update(ntwc_reported=3.0)),
    ("counts mismatch: hours exceed reported", lambda v: _hour(v, "ntwc", 29, 5)),
    ("counts mismatch: placed pairs exceed pairs", lambda v: _a(v)["counts"].update(ntwc_pairs=0)),
    ("counts mismatch: stations without records", lambda v: _b(v)["counts"].update(stations=1)),
    (
        "counts mismatch: reported without a file",
        lambda v: _b(v).update(arrivals=None),
    ),
    ("bad hour array length", lambda v: _a(v)["counts"]["reported_per_hour"]["ncei"].append(0)),
    ("short hour array", lambda v: _a(v)["counts"]["reported_per_hour"]["ntwc"].pop()),
    ("negative hour count", lambda v: _hour(v, "ncei", 0, -1)),
    ("hour sources", lambda v: _a(v)["counts"]["reported_per_hour"].pop("ncei")),
]


@pytest.mark.parametrize("mutate", [m for _, m in MUTATIONS], ids=[name for name, _ in MUTATIONS])
def test_rejects_mutated_index(mutate: Callable[[dict[str, Any]], object]) -> None:
    value = _example()
    mutate(value)
    with pytest.raises(ValueError):
        validate_events_index(value)


# The builder on synthetic bundles.


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
    (root / "base").mkdir()
    (root / "base/coastline.json").write_bytes(b"{}\n")
    return root


def _config(
    tmp_path: Path,
    *,
    labels: dict[str, str] | None = None,
    extra: tuple[dict[str, object], ...] = (),
    values: dict[str, object] | None = None,
    **overrides: object,
) -> Path:
    entry: dict[str, object] = {
        **EVENT,
        "magnitude": 9.1,
        "magnitude_type": "mww",
        "records_bundle": "rec",
        "layers_bundle": "lay",
        **(values or {}),
        **overrides,
    }
    with (tmp_path / "names.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["event_id", "label"])
        names = {str(entry["event_id"]): "Event one"} if labels is None else labels
        writer.writerows(names.items())
    lines = [
        f"default_event_id = {json.dumps(entry['event_id'])}",
        'names = "names.csv"',
        'basemap = "base/coastline.json"',
    ]
    for item in (entry, *extra):
        lines += ["[[events]]"]
        lines += [
            f"{key} = {json.dumps(value)}" for key, value in item.items() if value is not None
        ]
    path = tmp_path / "events.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build(bundles: Path, config: Path, *, replace: bool = False) -> Path:
    report = bundles.parent / "report.json"
    return build_events_index(
        bundles_root=bundles, config_path=config, report_path=report, replace=replace
    )


def _names(root: Path) -> list[str]:
    return sorted(path.name for path in root.iterdir())


def test_pins_manifests_and_basemap_in_compact_sorted_json(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path))
    data = out.read_bytes()
    index = json.loads(data)
    manifest = (bundles / "rec/manifest.json").read_bytes()
    event = index["events"][0]
    assert event["records"] == {
        "bundle_id": "rec",
        "manifest_bytes": len(manifest),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
    assert index["basemap"] == {
        "path": "base/coastline.json",
        "bytes": 3,
        "sha256": hashlib.sha256(b"{}\n").hexdigest(),
    }
    assert (event["arrivals"], event["label"]) == (None, "Event one")
    assert event["counts"] == {
        "ntwc_pairs": 0,
        "ntwc_pairs_with_position": 0,
        "ntwc_reported": 0,
        "ncei_reported": 0,
        "stations": 0,
        "reported_per_hour": {"ntwc": [0] * 30, "ncei": [0] * 30},
    }
    assert isinstance(event["x"], int) and isinstance(event["y"], int)
    assert (
        data
        == (
            json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    )
    assert _names(bundles) == ["base", "events.json", "lay", "rec"]


def test_projects_the_epicentre_like_the_example(bundles: Path, tmp_path: Path) -> None:
    b = _b(_example())
    place = {"latitude": b["latitude"], "longitude": b["longitude"]}
    _write_bundle(bundles, "rec", {"event": {**EVENT, **place}})
    event = json.loads(_build(bundles, _config(tmp_path, **place)).read_bytes())["events"][0]
    assert (event["x"], event["y"]) == (b["x"], b["y"])  # computed once with pyproj


def test_absent_layers_become_null(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path, layers_bundle=None))
    assert json.loads(out.read_bytes())["events"][0]["layers"] is None


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
    [{"records_bundle": "../bundles/rec"}, {"layer_bundle": "lay"}, {"label": "Event one"}],
    ids=["unsafe bundle name", "unknown key", "label outside the names table"],
)
def test_refuses_a_bad_config_entry(
    bundles: Path, tmp_path: Path, override: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        _build(bundles, _config(tmp_path, values=override))


def test_refuses_a_basemap_outside_the_root(bundles: Path, tmp_path: Path) -> None:
    shutil.move(bundles / "base", tmp_path / "base")
    (bundles / "base").symlink_to(tmp_path / "base")
    with pytest.raises(ValueError, match="escapes"):
        _build(bundles, _config(tmp_path))


EXAMPLE_ARRIVALS = "story-arrivals-v1/example-event-a.json"


def _arrivals_entry(bundles: Path, records: bool = True) -> dict[str, object]:
    """The shared arrivals example as a config entry, with or without its records bundle."""
    value = json.loads(ARRIVALS_EXAMPLE.read_text(encoding="utf-8"))
    identity = {
        "event_id": value["event_id"],
        "origin_time_utc": value["origin_time_utc"],
        "latitude": 0.0,
        "longitude": -160.0,
    }
    stations = [{"station_id": "0000001"}, {"station_id": "0000002"}]
    _write_bundle(bundles, "rec-a", {"event": identity, "stations": stations})
    if not records:
        for place in value["places"]:
            place["record"] = None
    _write_arrivals(bundles, value)
    return {
        **identity,
        "magnitude": 8.0,
        "magnitude_type": "mww",
        "records_bundle": "rec-a" if records else None,
        "arrivals": EXAMPLE_ARRIVALS,
    }


def _arrivals_config(bundles: Path, tmp_path: Path, **overrides: object) -> Path:
    entry = _arrivals_entry(bundles)
    labels = {str(entry["event_id"]): "Example A"}
    return _config(tmp_path, labels=labels, values=entry | {"layers_bundle": None} | overrides)


def _write_arrivals(bundles: Path, value: dict[str, Any]) -> None:
    path = bundles / EXAMPLE_ARRIVALS
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def test_pins_a_valid_arrivals_file_and_copies_its_counts(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _arrivals_config(bundles, tmp_path))
    data = (bundles / EXAMPLE_ARRIVALS).read_bytes()
    event = json.loads(out.read_bytes())["events"][0]
    assert event["arrivals"] == {
        "path": EXAMPLE_ARRIVALS,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    expected = _a(_example())  # the two shared examples describe the same event
    assert event["counts"] == expected["counts"]
    assert (event["x"], event["y"]) == (expected["x"], expected["y"])


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


# Listing rule, names table and report.


def _unplaced(value: dict[str, Any]) -> None:
    """Every report loses its place, so no reported time can be drawn."""
    value["places"] = []
    for report in value["reports"]:
        report.update(site_id=None, reported_minus_ruler_minutes=None)
    value["accounting"].update(
        places=0,
        ntwc_pairs_with_position=0,
        ntwc_reported_with_position=0,
        ncei_durations_with_position=0,
    )


NOTHING: dict[str, object] = {
    "event_id": "ev-0",
    "origin_time_utc": "1999-01-01T00:00:00Z",
    "latitude": 1.0,
    "longitude": 2.0,
    "magnitude": 7.0,
    "magnitude_type": "mwc",
}


def test_lists_records_or_drawable_reported_times_and_reports_the_rest(
    bundles: Path, tmp_path: Path
) -> None:
    entry = _arrivals_entry(bundles, records=False)
    labels = {"ev-1": "Event one", "example-event-a": "Example A"}
    config = _config(tmp_path, labels=labels, extra=(entry, NOTHING))
    index = json.loads(_build(bundles, config).read_bytes())
    listed = {event["event_id"]: event for event in index["events"]}
    assert list(listed) == ["example-event-a", "ev-1"]  # origin order
    assert (listed["example-event-a"]["records"], listed["example-event-a"]["layers"]) == (
        None,
        None,
    )
    assert listed["example-event-a"]["counts"]["stations"] == 0
    report = json.loads((tmp_path / "report.json").read_bytes())
    assert report["excluded"] == [{"event_id": "ev-0", "reason": REASON}]
    paths = [item["path"] for item in report["files"]]
    assert paths == sorted(paths)
    assert set(paths) == {
        "base/coastline.json",
        "events.json",
        "lay/data/part.json",
        "lay/manifest.json",
        "rec/data/part.json",
        "rec/manifest.json",
        EXAMPLE_ARRIVALS,
    }
    assert report["totals"] == {
        "listed_events": 2,
        "excluded_events": 1,
        "bytes": sum(item["bytes"] for item in report["files"]),
    }
    assert report["schema_version"] == "1"


def test_excludes_reported_times_that_cannot_be_drawn(bundles: Path, tmp_path: Path) -> None:
    entry = _arrivals_entry(bundles, records=False)
    _mutated_arrivals(bundles, _unplaced)
    config = _config(tmp_path, extra=(entry,))
    assert [e["event_id"] for e in json.loads(_build(bundles, config).read_bytes())["events"]] == [
        "ev-1"
    ]
    report = json.loads((tmp_path / "report.json").read_bytes())
    assert report["excluded"] == [{"event_id": "example-event-a", "reason": REASON}]
    assert EXAMPLE_ARRIVALS not in {item["path"] for item in report["files"]}


@pytest.mark.parametrize(
    "labels",
    [{}, {"ev-1": "Event one", "ev-0": "Excluded"}, {"ev-1": "Event one", "other": "Other"}],
    ids=["missing label", "label for an excluded event", "label for another ID"],
)
def test_names_table_labels_exactly_the_listed_events(
    bundles: Path, tmp_path: Path, labels: dict[str, str]
) -> None:
    with pytest.raises(ValueError, match="names table"):
        _build(bundles, _config(tmp_path, labels=labels, extra=(NOTHING,)))
    assert not (bundles / "events.json").exists()


def test_refuses_a_report_inside_the_bundles_root(bundles: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the bundles root"):
        build_events_index(
            bundles_root=bundles, config_path=_config(tmp_path), report_path=bundles / "r.json"
        )
    assert _names(bundles) == ["base", "lay", "rec"]


@pytest.mark.parametrize(
    ("budget", "limit", "match"),
    [
        ("MAX_EVENT_BYTES", 100, "opening ev-1"),
        ("MAX_ASSET_BYTES", 7, "over 7"),
        ("MAX_FIRST_SCREEN_BYTES", 100, "index and basemap"),
    ],
)
def test_refuses_an_index_over_a_size_budget(
    bundles: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: str,
    limit: int,
    match: str,
) -> None:
    monkeypatch.setattr(events_index, budget, limit)
    with pytest.raises(ValueError, match=match):
        _build(bundles, _config(tmp_path))
    assert not (bundles / "events.json").exists()


def test_station_records_and_the_schema_1_records_bundle_are_outside_the_budgets(
    bundles: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    station = bundles / "rec/stations/s.csv.gz"
    station.parent.mkdir()
    station.write_bytes(bytes(range(256)) * 4)  # 1,024 bytes, over the event budget below
    big = bundles / "rec/data/part.json"
    manifest = {
        "schema_version": "1",
        "bundle_id": "rec",
        "event": EVENT,
        "assets": [
            {
                "path": p,
                "bytes": f.stat().st_size,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }
            for p, f in (("data/part.json", big), ("stations/s.csv.gz", station))
        ],
    }
    (bundles / "rec/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(events_index, "MAX_ASSET_BYTES", 7)
    monkeypatch.setattr(events_index, "MAX_EVENT_BYTES", 600)  # manifests and part, no station
    _build(bundles, _config(tmp_path, layers_bundle=None))
    manifest["schema_version"] = "2"
    (bundles / "rec/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="over 7"):
        _build(bundles, _config(tmp_path, layers_bundle=None), replace=True)


# Publication.


def test_leaves_an_identical_index_untouched(bundles: Path, tmp_path: Path) -> None:
    config = _config(tmp_path)
    out = _build(bundles, config)
    before = out.stat()
    assert _build(bundles, config) == out
    after = out.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert _names(bundles) == ["base", "events.json", "lay", "rec"]


def test_replaces_a_different_index_only_when_asked(bundles: Path, tmp_path: Path) -> None:
    out = _build(bundles, _config(tmp_path))
    old, inode = out.read_bytes(), out.stat().st_ino
    changed = _config(tmp_path, labels={"ev-1": "Event one, relabelled"})
    with pytest.raises(FileExistsError):
        _build(bundles, changed)
    assert out.read_bytes() == old
    assert _build(bundles, changed, replace=True) == out
    assert json.loads(out.read_bytes())["events"][0]["label"] == "Event one, relabelled"
    assert out.stat().st_ino != inode  # renamed into place, not rewritten in place
    assert _names(bundles) == ["base", "events.json", "lay", "rec"]


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


# Configured events: development entries, released, and copied from the reviewed sources.


def _story_event_ids() -> list[str]:
    return [event["event_id"] for event in _settings()["events"]]


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


def test_story_events_and_names_are_development_entries() -> None:
    _require_development(_story_event_ids())
    _require_development(list(_labels(NAMES)))


def test_development_guard_rejects_another_role() -> None:
    for event_ids in (_story_event_ids(), list(_labels(NAMES))):
        event_ids[0] = _another_role_id()
        with pytest.raises(ValueError):
            _require_development(event_ids)


def test_names_are_short_reviewed_labels_of_configured_events() -> None:
    labels = _labels(NAMES)
    assert set(labels) <= set(_story_event_ids())
    assert all(label and label == label.strip() for label in labels.values())
    assert labels[TOHOKU] == "Tōhoku, Japan"


def test_configured_events_are_the_released_development_events() -> None:
    path = ROOT / "data/processed/arrival-evidence/foundation-v1/source_records.csv.gz"
    if not path.is_file():
        pytest.skip("local released arrival-evidence tables unavailable")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        released = {row["event_id"] for row in csv.DictReader(stream)}
    assert sorted(_story_event_ids()) == sorted(released)


def test_config_copies_the_reviewed_usgs_identity() -> None:
    batch = _batch_entries()
    text = (ROOT / "config/ntwc-event-annotations-v2.csv").read_text(encoding="utf-8")
    details = {row["event_id"]: row for row in csv.DictReader(text.splitlines())}
    for event in _settings()["events"]:
        entry = batch[event["event_id"]]
        assert event["origin_time_utc"] == entry["usgs_time"]
        assert event["magnitude"] == float(entry["usgs_mag"])
        assert event["magnitude_type"] == entry["usgs_magType"]
        detail = ROOT / details[event["event_id"]]["detail_path"]
        if detail.is_file():  # pinned USGS event detail; local-only raw data
            data = detail.read_bytes()
            assert hashlib.sha256(data).hexdigest() == details[event["event_id"]]["detail_sha256"]
            longitude, latitude = json.loads(data)["geometry"]["coordinates"][:2]
            assert (event["latitude"], event["longitude"]) == (latitude, longitude)
