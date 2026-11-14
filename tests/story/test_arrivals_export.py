"""Reported-times files: validator, real export, row conservation and lane fences."""

import ast
import builtins
import csv
import gzip
import hashlib
import io
import json
import math
import os
import pathlib
import shutil
import tomllib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from analysis.story.arrivals_export import export_arrivals, validate_arrivals
from analysis.story.events_index import build_events_index

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs/data/examples/story-arrivals.example.json"
CONFIG = ROOT / "config/story-arrivals.toml"
EVENTS_CONFIG = ROOT / "config/story-events.toml"
EVIDENCE = ROOT / "data/processed/arrival-evidence/foundation-v1"
BUNDLES = ROOT / "app/demo-public/data"
TOHOKU = "official20110311054624120_30"
RECORDS = "tohoku-descriptive-demo-v2"
TABLES = (
    "source_records",
    "observations",
    "forecast_instances",
    "pair_members",
    "sites",
    "site_links",
)
MAX_BYTES = 2_097_152
BUNDLE_ID = "story-arrivals-v2"


def _settings() -> dict[str, Any]:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def _need_real_data() -> None:
    if not (EVIDENCE / "manifest.json").is_file() or not (BUNDLES / RECORDS).is_dir():
        pytest.skip("local released arrival-evidence tables or Tōhoku records bundle unavailable")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _need_real_data()
    out = tmp_path_factory.mktemp("arrivals")
    return export_arrivals(source_root=ROOT, output_root=out, config_path=CONFIG)


@pytest.fixture(scope="module")
def files(bundle: Path) -> dict[str, dict[str, Any]]:
    return {path.stem: json.loads(path.read_bytes()) for path in sorted(bundle.glob("*.json"))}


@pytest.fixture(scope="module")
def tables() -> dict[str, list[dict[str, str]]]:
    _need_real_data()
    out: dict[str, list[dict[str, str]]] = {}
    for name in TABLES:
        with gzip.open(EVIDENCE / f"{name}.csv.gz", "rt", encoding="utf-8", newline="") as stream:
            out[name] = list(csv.DictReader(stream))
    return out


# 1. The shared example and its mutations.


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _p(value: dict[str, Any], index: int) -> Any:
    return value["places"][index]


def _r(value: dict[str, Any], index: int) -> Any:
    return value["reports"][index]


def _add_unused_place(value: dict[str, Any]) -> None:
    value["places"].append({**_p(value, 3), "site_id": "zz-unused", "record": None})
    value["accounting"]["places"] += 1


def _records_input(value: dict[str, Any], path: str) -> None:
    """Replace the records-manifest fingerprint (the only free path) and keep the order."""
    inputs: list[dict[str, str]] = value["input_fingerprints"]
    inputs[0]["path"] = path
    inputs.sort(key=lambda item: item["path"])


def _add_input(value: dict[str, Any], path: str) -> None:
    inputs: list[dict[str, str]] = value["input_fingerprints"]
    inputs.append({"path": path, "sha256": "0" * 64})
    inputs.sort(key=lambda item: item["path"])


def _drop_reported_time(value: dict[str, Any]) -> None:
    _r(value, 2).update(
        reported_minutes=None,
        reported_origin=None,
        reported_utc=None,
        reported_minus_ruler_minutes=None,
    )


def _negative_reported(value: dict[str, Any]) -> None:
    """Report 3 (placed, no estimate) at a source time 10 minutes before the origin."""
    _r(value, 2).update(
        reported_utc="2000-12-31T23:50:00Z",
        reported_minutes=-10.0,
        reported_text="2350 (366)",
        reported_minus_ruler_minutes=None,
    )


def _negative_estimate(value: dict[str, Any]) -> None:
    """Pair 1 with an estimate 5 minutes before the origin; still a pair-table row."""
    _r(value, 0).update(
        estimate_utc="2000-12-31T23:55:00Z",
        estimate_minutes=-5.0,
        estimate_text="2355 (366)",
        reported_minus_estimate_minutes=None,
    )


def _negative_fixture() -> dict[str, Any]:
    value = _example()
    _negative_reported(value)
    _negative_estimate(value)
    return value


MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], object]]] = [
    ("release literal", lambda v: v["release"].update(arrival_comparison_allowed=True)),
    ("release false written as 0", lambda v: v["release"].update(arrival_comparison_allowed=0)),
    ("release uses reordered", lambda v: v["release"]["allowed_uses"].reverse()),
    ("release extra field", lambda v: v["release"].update(note="ok")),
    ("ruler literal", lambda v: v["ruler"].update(speed_km_per_h=700)),
    ("ruler speed as float", lambda v: v["ruler"].update(speed_km_per_h=713.0)),
    ("ruler statement", lambda v: v["ruler"].update(statement="A prediction.")),
    ("display crs", lambda v: v.update(display_crs="EPSG:3857")),
    ("schema version as integer", lambda v: v.update(schema_version=1)),
    ("evidence state", lambda v: v.update(evidence_state="public")),
    ("extra top-level key", lambda v: v.update(role="development")),
    ("missing top-level key", lambda v: v.pop("accounting")),
    ("offset origin", lambda v: v.update(origin_time_utc="2001-01-01T00:00:00+00:00")),
    ("uppercase config hash", lambda v: v.update(config_sha256="A" * 64)),
    ("null rule: NTWC origin offset", lambda v: _r(v, 0).update(origin_offset_seconds=0.0)),
    ("null rule: estimate utc without minutes", lambda v: _r(v, 0).update(estimate_minutes=None)),
    ("null rule: origin without minutes", lambda v: _r(v, 3).update(reported_origin=None)),
    ("null rule: empty raw text", lambda v: _r(v, 0).update(estimate_text="")),
    ("raw text not collapsed", lambda v: _r(v, 0).update(reported_text=" 0215")),
    ("place text not collapsed", lambda v: _r(v, 3).update(place_text="Example  Bay")),
    (
        "NCEI row with an estimate",
        lambda v: _r(v, 3).update(
            estimate_minutes=1.0, estimate_utc="2001-01-01T00:01:00Z", estimate_text="0001"
        ),
    ),
    ("NCEI reported utc", lambda v: _r(v, 3).update(reported_utc="2001-01-01T03:10:00Z")),
    ("NCEI reported text", lambda v: _r(v, 3).update(reported_text="0310")),
    ("NCEI origin label", lambda v: _r(v, 3).update(reported_origin="usgs_reviewed")),
    (
        "NCEI nonpositive duration",
        lambda v: _r(v, 4).update(reported_minutes=0.0, reported_minus_ruler_minutes=-66.0),
    ),
    ("cross-source difference", lambda v: _r(v, 3).update(reported_minus_estimate_minutes=55.0)),
    (
        "difference not from its row",
        lambda v: _r(v, 0).update(reported_minus_estimate_minutes=16.0),
    ),
    (
        "difference without both times",
        lambda v: _r(v, 2).update(reported_minus_estimate_minutes=1.0),
    ),
    ("reported minutes not from utc", lambda v: _r(v, 1).update(reported_minutes=171.0)),
    ("estimate minutes not from utc", lambda v: _r(v, 0).update(estimate_minutes=121.0)),
    ("ruler difference arithmetic", lambda v: _r(v, 0).update(reported_minus_ruler_minutes=41.2)),
    ("ruler difference without place", lambda v: _r(v, 1).update(reported_minus_ruler_minutes=1.0)),
    ("ruler minutes arithmetic", lambda v: _p(v, 2).update(ruler_minutes=66.1)),
    ("distance not rounded", lambda v: _p(v, 2).update(distance_km=784.04)),
    ("negative distance", lambda v: _p(v, 2).update(distance_km=-784.0)),
    ("NTWC row with neither time", _drop_reported_time),
    ("NTWC gauge kind", lambda v: _r(v, 0).update(gauge_kind="tide_gauge")),
    ("NCEI gauge kind", lambda v: _r(v, 3).update(gauge_kind="unknown")),
    ("doubtful on NTWC", lambda v: _r(v, 0).update(source_flags=["doubtful"])),
    ("unknown flag", lambda v: _r(v, 3).update(source_flags=["suspect"])),
    ("unknown source", lambda v: _r(v, 0).update(source="usgs")),
    ("NCEI before NTWC", lambda v: v["reports"].insert(0, v["reports"].pop(3))),
    ("duplicate report id", lambda v: _r(v, 1).update(report_id="example-event-a:1:1")),
    ("short source hash", lambda v: _r(v, 0).update(source_sha256="e" * 63)),
    ("nonfinite offset", lambda v: _r(v, 3).update(origin_offset_seconds=float("nan"))),
    ("report at an unlisted site", lambda v: _r(v, 1).update(site_id="coops:9999999")),
    ("extra report key", lambda v: _r(v, 0).update(cohort="core")),
    ("places unsorted", lambda v: v["places"].reverse()),
    ("unused place", _add_unused_place),
    ("label not first place text", lambda v: _p(v, 0).update(label="Elsewhere")),
    ("NCEI place marked reviewed", lambda v: _p(v, 1).update(position_status="reviewed")),
    (
        "NTWC place marked source position",
        lambda v: _p(v, 3).update(position_status="source_position"),
    ),
    ("fractional x", lambda v: _p(v, 0).update(x=957998.5)),
    ("integer latitude", lambda v: _p(v, 1).update(latitude=10)),
    ("latitude out of range", lambda v: _p(v, 1).update(latitude=90.5)),
    ("record link kind", lambda v: _p(v, 0)["record"].update(link="nearest")),
    ("provider link to another ID", lambda v: _p(v, 0)["record"].update(station_id="0000002")),
    ("extra place key", lambda v: _p(v, 0).update(model_eligible=False)),
    ("accounting off by one", lambda v: v["accounting"].update(ntwc_rows_with_estimate=3)),
    ("accounting reports off by one", lambda v: v["accounting"].update(reports=6)),
    (
        "accounting pairs with position",
        lambda v: v["accounting"].update(ntwc_pairs_with_position=2),
    ),
    ("table rows below listed rows", lambda v: v["accounting"].update(ntwc_table_rows=2)),
    ("negative count", lambda v: v["accounting"].update(ncei_records=-1)),
    ("accounting extra key", lambda v: v["accounting"].update(cohort_rows=0)),
    ("record link without records manifest", lambda v: v["input_fingerprints"].pop(0)),
    ("missing table fingerprint", lambda v: v["input_fingerprints"].pop(5)),
    ("fingerprints unsorted", lambda v: v["input_fingerprints"].reverse()),
    (
        "paper target view as input",
        lambda v: _records_input(v, "data/processed/arrival-evidence/foundation-v1/T-OBS.csv.gz"),
    ),
    ("model output as input", lambda v: _records_input(v, "artifacts/models/run/manifest.json")),
    ("parent path as input", lambda v: _records_input(v, "app/../demo/manifest.json")),
    (
        "absolute path as input",
        lambda v: _records_input(v, "/app/demo-public/data/b/manifest.json"),
    ),
    ("second records manifest", lambda v: _add_input(v, "app/demo-public/data/b/manifest.json")),
    ("release list missing a bar", lambda v: v["release"]["prohibited_uses"].pop()),
    (
        "ruler difference on a negative time",
        lambda v: (_negative_reported(v), _r(v, 2).update(reported_minus_ruler_minutes=-202.8)),
    ),
    (
        "estimate difference on a negative time",
        lambda v: (_negative_estimate(v), _r(v, 0).update(reported_minus_estimate_minutes=140.0)),
    ),
    (
        "withheld pair beyond the pair count",
        lambda v: (_negative_estimate(v), v["accounting"].update(ntwc_rows_with_both_times=3)),
    ),
    (
        "pair count below the listed differences",
        lambda v: (_negative_estimate(v), v["accounting"].update(ntwc_rows_with_both_times=0)),
    ),
]


def test_accepts_the_shared_example() -> None:
    validate_arrivals(_example())


def test_accepts_negative_minutes_listed_without_differences() -> None:
    # Listed but not drawn: the times stay as given; no difference is written for them,
    # and the withheld pair still counts in ntwc_rows_with_both_times.
    value = _negative_fixture()
    assert value["accounting"]["ntwc_rows_with_both_times"] == 2
    validate_arrivals(value)


@pytest.mark.parametrize("mutate", [m for _, m in MUTATIONS], ids=[name for name, _ in MUTATIONS])
def test_rejects_mutated_file(mutate: Callable[[dict[str, Any]], object]) -> None:
    value = _example()
    mutate(value)
    with pytest.raises(ValueError):
        validate_arrivals(value)


# 2-4. Real export: accounting, sign rule and hand-checked values.


def _expected_accounting(event_id: str, tables: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    def rows(name: str) -> list[dict[str, str]]:
        return [row for row in tables[name] if row["event_id"] == event_id]

    families = Counter(row["source_family"] for row in rows("source_records"))
    links = {row["source_record_id"]: row for row in rows("site_links")}
    observations = rows("observations")
    reported = {
        row["source_record_id"]
        for row in observations
        if row["arrival_definition"] == "NTWC_reported_observed_arrival"
        and row["duration_state"] == "exact_reported_timestamp"
    }
    durations = {
        row["source_record_id"]
        for row in observations
        if row["arrival_definition"] == "source_reported_initial_wave"
        and row["duration_state"] == "complete_positive"
    }
    estimates = {
        row["source_record_id"]
        for row in rows("forecast_instances")
        if row["estimate_state"] == "exact_reported_timestamp"
    }
    pairs = {row["source_record_id"] for row in rows("pair_members")}
    listed = reported | estimates | durations
    resolved = {
        i for i, link in links.items() if link["decision"] in ("accepted", "source_native_position")
    }
    return {
        "ntwc_table_rows": families["NTWC"],
        "ntwc_rows_with_reported_time": len(reported),
        "ntwc_rows_with_estimate": len(estimates),
        "ntwc_rows_with_both_times": len(pairs),
        "ntwc_pairs_with_position": len(pairs & resolved),
        "ntwc_reported_with_position": len(reported & resolved),
        "ncei_records": families["NCEI"],
        "ncei_reported_durations": len(durations),
        "ncei_durations_with_position": len(durations & resolved),
        "reports": len(listed),
        "places": len({links[i]["physical_site_id"] for i in listed & resolved}),
    }


def test_files_are_valid_canonical_and_cover_every_configured_event(
    bundle: Path, files: dict[str, dict[str, Any]]
) -> None:
    events = _settings()["events"]
    assert bundle.name == BUNDLE_ID
    assert sorted(files) == sorted(event["event_id"] for event in events)
    config_sha256 = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    for event in events:
        value = files[event["event_id"]]
        validate_arrivals(value)
        assert (value["event_id"], value["origin_time_utc"]) == (
            event["event_id"],
            event["origin_time_utc"],
        )
        assert value["config_sha256"] == config_sha256
        for item in value["input_fingerprints"]:
            assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
        text = json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
        assert (bundle / f"{event['event_id']}.json").read_bytes() == (text + "\n").encode()


def test_accounting_equals_counts_taken_from_the_released_tables(
    files: dict[str, dict[str, Any]], tables: dict[str, list[dict[str, str]]]
) -> None:
    for event_id, value in files.items():
        assert value["accounting"] == _expected_accounting(event_id, tables)
        order = [row for row in tables["source_records"] if row["event_id"] == event_id]
        ntwc = {r["report_id"] for r in value["reports"] if r["source"] == "ntwc"}
        ncei = {r["report_id"] for r in value["reports"] if r["source"] == "ncei"}
        expected = [row["source_record_id"] for row in order if row["source_record_id"] in ntwc]
        expected += [row["source_record_id"] for row in order if row["source_record_id"] in ncei]
        assert [r["report_id"] for r in value["reports"]] == expected


def test_difference_reverses_the_pair_table_sign(
    files: dict[str, dict[str, Any]], tables: dict[str, list[dict[str, str]]]
) -> None:
    pairs = {
        row["source_record_id"]: float(row["estimated_minus_observed_seconds"])
        for row in tables["pair_members"]
    }
    checked = withheld = 0
    for value in files.values():
        for report in value["reports"]:
            times = (report["reported_minutes"], report["estimate_minutes"])
            if report["report_id"] not in pairs:
                assert report["reported_minus_estimate_minutes"] is None
            elif min(times) < 0:  # listed but not drawn: no difference
                assert report["reported_minus_estimate_minutes"] is None
                withheld += 1
            else:
                expected = round(-pairs[report["report_id"]] / 60, 3)
                assert report["reported_minus_estimate_minutes"] == expected
                checked += 1
    both = sum(v["accounting"]["ntwc_rows_with_both_times"] for v in files.values())
    assert checked + withheld == both
    assert checked > 0


def test_illapel_time_before_the_origin_is_kept_without_differences(
    files: dict[str, dict[str, Any]],
) -> None:
    reports = {report["report_id"]: report for report in files["us20003k7a"]["reports"]}
    report = reports["us20003k7a:1:20"]
    assert (report["reported_minutes"], report["reported_text"]) == (-1325.548, "0049 (259)")
    assert report["reported_utc"] == "2015-09-16T00:49:00Z"
    assert report["site_id"] is not None
    assert report["reported_minus_ruler_minutes"] is None
    assert report["reported_minus_estimate_minutes"] is None


def _floats(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for item in cast(dict[str, object], value).values() for f in _floats(item)]
    if isinstance(value, list):
        return [f for item in cast(list[object], value) for f in _floats(item)]
    return []


def test_no_negative_zero_is_written(files: dict[str, dict[str, Any]]) -> None:
    # A zero difference written as -0.0 would read as "earlier than the estimate".
    for value in files.values():
        assert [f for f in _floats(value) if f == 0 and math.copysign(1.0, f) < 0] == []


HAND_CHECKED = {  # suffix: (reported minus estimate, has a reviewed position)
    ":1:11": (17.0, False),
    ":1:46": (3.0, True),
    ":1:47": (11.0, True),
    ":1:54": (7.0, True),
    ":1:122": (8.0, True),
    ":1:148": (17.0, False),
}


def test_six_hand_checked_tohoku_values(files: dict[str, dict[str, Any]]) -> None:
    reports = {report["report_id"]: report for report in files[TOHOKU]["reports"]}
    for suffix, (minutes, placed) in HAND_CHECKED.items():
        report = reports[TOHOKU + suffix]
        assert report["reported_minus_estimate_minutes"] == minutes
        assert (report["site_id"] is not None) == placed


# 5. Lane fence.


def _forbidden_imports(source: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names += [module, *(f"{module}.{alias.name}" for alias in node.names)]
    return [
        name
        for name in names
        if "models" in name or name == "analysis.arrival" or name.startswith("analysis.arrival.")
    ]


def test_story_modules_import_nothing_from_the_model_lane() -> None:
    paths = sorted(
        [*(ROOT / "analysis/story").rglob("*.py"), *(ROOT / "scripts/story").rglob("*.py")]
    )
    assert len(paths) > 10
    found = {path.name: _forbidden_imports(path.read_text(encoding="utf-8")) for path in paths}
    assert {name: imports for name, imports in found.items() if imports} == {}


@pytest.mark.parametrize(
    "source",
    [
        "from analysis.arrival import evidence",
        "import analysis.arrival.model_bridge",
        "from analysis import arrival",
        "import pipeline.models",
        "from . import models",
    ],
)
def test_import_fence_catches_model_lane_imports(source: str) -> None:
    assert _forbidden_imports(source)


def _allowed_reads() -> set[Path]:
    settings = _settings()
    paths = {EVIDENCE / "manifest.json", *(EVIDENCE / f"{name}.csv.gz" for name in TABLES)}
    paths |= {ROOT / settings["release_manifest"], CONFIG}
    paths |= {
        ROOT / settings["bundles_root"] / event["records_bundle"] / "manifest.json"
        for event in settings["events"]
        if "records_bundle" in event
    }
    return {path.resolve() for path in paths}


def test_export_reads_only_the_allowlisted_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need_real_data()
    out = (tmp_path / "out").resolve()
    reads: list[Path] = []
    writes: list[Path] = []

    def recorder(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(file: Any, *args: Any, **kwargs: Any) -> Any:
            mode = str(args[0] if args else kwargs.get("mode", "r"))
            if isinstance(file, str | os.PathLike):
                path = Path(os.fspath(file)).resolve()  # pyright: ignore[reportUnknownArgumentType]
                (writes if any(flag in mode for flag in "wax+") else reads).append(path)
            return original(file, *args, **kwargs)

        return wrapper

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", recorder(builtins.open))
        patch.setattr(io, "open", recorder(io.open))
        patch.setattr(gzip, "open", recorder(gzip.open))
        patch.setattr(pathlib.Path, "open", recorder(pathlib.Path.open))
        export_arrivals(source_root=ROOT, output_root=out, config_path=CONFIG)
    assert set(reads) == _allowed_reads()
    assert not [path for path in reads if "models" in path.parts]
    assert writes and all(path.is_relative_to(out) for path in writes)


# 6. Events: released, development and correctly copied.


def test_refuses_an_event_absent_from_source_records(tmp_path: Path) -> None:
    _need_real_data()
    config = tmp_path / "arrivals.toml"
    text = CONFIG.read_text(encoding="utf-8")
    assert '"us20003k7a"' in text
    config.write_text(text.replace('"us20003k7a"', '"not-a-released-event"'), encoding="utf-8")
    with pytest.raises(ValueError, match="source_records"):
        export_arrivals(source_root=ROOT, output_root=tmp_path / "out", config_path=config)
    assert not (tmp_path / "out" / BUNDLE_ID).exists()


def _batch_entries() -> dict[str, dict[str, Any]]:
    path = ROOT / "config/ntwc-archive-batch-v2.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))["events"]


def _require_development(event_ids: list[str]) -> None:
    # The guard reports no IDs, so no reserved or excluded entry is ever printed.
    entries = _batch_entries()
    if not all(entries.get(event_id, {}).get("role") == "development" for event_id in event_ids):
        raise ValueError("an arrivals event is not a development entry of the frozen selection")


def _configured_ids() -> list[str]:
    return [event["event_id"] for event in _settings()["events"]]


def test_configured_events_are_development_entries() -> None:
    _require_development(_configured_ids())


def test_development_guard_rejects_another_role() -> None:
    event_ids = _configured_ids()
    event_ids[-1] = next(
        i for i, entry in _batch_entries().items() if entry["role"] != "development"
    )
    with pytest.raises(ValueError):
        _require_development(event_ids)


def test_config_copies_the_reviewed_usgs_identity() -> None:
    batch = _batch_entries()
    text = (ROOT / "config/ntwc-event-annotations-v2.csv").read_text(encoding="utf-8")
    details = {row["event_id"]: row for row in csv.DictReader(text.splitlines())}
    for event in _settings()["events"]:
        event_id = event["event_id"]
        assert event["origin_time_utc"] == batch[event_id]["usgs_time"]
        detail = ROOT / details[event_id]["detail_path"]
        if detail.is_file():  # pinned USGS event detail; local-only raw data
            data = detail.read_bytes()
            assert hashlib.sha256(data).hexdigest() == details[event_id]["detail_sha256"]
            longitude, latitude = json.loads(data)["geometry"]["coordinates"][:2]
            assert (event["latitude"], event["longitude"]) == (latitude, longitude)
        if "records_bundle" in event:
            manifest = BUNDLES / event["records_bundle"] / "manifest.json"
            if manifest.is_file():
                identity = {
                    k: event[k] for k in ("event_id", "origin_time_utc", "latitude", "longitude")
                }
                assert json.loads(manifest.read_bytes())["event"] == identity


# 7. Sources are never mixed.


def test_no_difference_mixes_ntwc_and_ncei(files: dict[str, dict[str, Any]]) -> None:
    for value in files.values():
        ruler = {place["site_id"]: place["ruler_minutes"] for place in value["places"]}
        for report in value["reports"]:
            if report["source"] == "ncei":
                assert report["reported_minus_estimate_minutes"] is None
                assert report["estimate_minutes"] is None
            elif report["reported_minus_estimate_minutes"] is not None:
                own = round(report["reported_minutes"] - report["estimate_minutes"], 3)
                assert abs(report["reported_minus_estimate_minutes"] - own) <= 0.0011
            if report["reported_minus_ruler_minutes"] is not None:
                own = round(report["reported_minutes"] - ruler[report["site_id"]], 1)
                assert report["reported_minus_ruler_minutes"] == own


# 8. Publication.


def test_rerun_is_byte_identical_bounded_and_never_overwrites(bundle: Path, tmp_path: Path) -> None:
    again = export_arrivals(source_root=ROOT, output_root=tmp_path, config_path=CONFIG)
    names = sorted(path.name for path in bundle.iterdir())
    assert names == sorted(path.name for path in again.iterdir())
    for name in names:
        assert (again / name).read_bytes() == (bundle / name).read_bytes()
        assert (again / name).stat().st_size <= MAX_BYTES
    with pytest.raises(FileExistsError):
        export_arrivals(source_root=ROOT, output_root=tmp_path, config_path=CONFIG)
    assert [path.name for path in tmp_path.iterdir()] == [BUNDLE_ID]


# 9. The events index accepts the real file and refuses a broken record link.


def _bundles_with_arrivals(root: Path, arrivals: Path) -> Path:
    for name in (RECORDS, "tohoku-story-layers-v1", "basemap-v1"):
        shutil.copytree(BUNDLES / name, root / name)
    shutil.copytree(arrivals, root / arrivals.name)
    return root / arrivals.name / f"{TOHOKU}.json"


def _tohoku_index_config(tmp_path: Path) -> Path:
    """The real index config cut down to its Tōhoku entry, labelled as in the names table."""
    settings = tomllib.loads(EVENTS_CONFIG.read_text(encoding="utf-8"))
    entry = next(event for event in settings["events"] if event["event_id"] == TOHOKU)
    (tmp_path / "names.csv").write_text(
        f'event_id,label\n{TOHOKU},"Tōhoku, Japan"\n', encoding="utf-8"
    )
    lines = [f'default_event_id = "{TOHOKU}"', 'names = "names.csv"']
    lines += [f"basemap = {json.dumps(settings['basemap'])}", "[[events]]"]
    lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in entry.items()]
    config = tmp_path / "events.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def test_index_accepts_tohoku_arrivals_and_refuses_a_broken_record_link(
    bundle: Path, tmp_path: Path
) -> None:
    if not all((BUNDLES / name).is_dir() for name in ("tohoku-story-layers-v1", "basemap-v1")):
        pytest.skip("local Tōhoku layers bundle or basemap unavailable")
    config = _tohoku_index_config(tmp_path)
    report = tmp_path / "report.json"
    good = _bundles_with_arrivals(tmp_path / "good", bundle)
    index = json.loads(
        build_events_index(
            bundles_root=good.parents[1], config_path=config, report_path=report
        ).read_bytes()
    )
    data = good.read_bytes()
    assert index["events"][0]["arrivals"] == {
        "path": f"{BUNDLE_ID}/{TOHOKU}.json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    broken = _bundles_with_arrivals(tmp_path / "broken", bundle)
    value = json.loads(broken.read_bytes())
    places: list[dict[str, Any]] = value["places"]
    place = next(p for p in places if p["record"] and p["record"]["link"] == "within_1km")
    place["record"]["station_id"] = "not-a-station"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    broken.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="record"):
        build_events_index(bundles_root=broken.parents[1], config_path=config, report_path=report)
    assert not (broken.parents[1] / "events.json").exists()


# 10. Record links read both records schemas.


def test_record_links_read_a_schema_2_station() -> None:
    from pyproj import Geod

    from analysis.story.arrivals_export import _record  # pyright: ignore[reportPrivateUsage]

    station = {  # schema 2: provider key, no top-level source_id
        "station_id": "1612340",
        "display_station_key": "coops:1612340",
        "latitude": 21.3033,
        "longitude": -157.8645,
        "source": {"source_id": "ia-window-aa2758f15ce24d78c9ce", "sha256": "0" * 64, "url": None},
    }
    geod = Geod(ellps="WGS84")
    link = _record("coops:1612340", 21.0, -157.0, [station], geod)
    assert link == {"station_id": "1612340", "link": "same_provider_id"}
    assert _record("ncei-native:x", 21.3033, -157.8645, [station], geod) == {
        "station_id": "1612340",
        "link": "within_1km",
    }


def test_export_matches_the_published_bundle(bundle: Path) -> None:
    published = BUNDLES / bundle.name
    if not published.is_dir():
        pytest.skip("published arrivals bundle unavailable")
    names = sorted(path.name for path in bundle.iterdir())
    assert names == sorted(path.name for path in published.iterdir())
    assert all((bundle / name).read_bytes() == (published / name).read_bytes() for name in names)
