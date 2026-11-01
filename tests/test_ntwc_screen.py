"""The metadata gate must not learn from arrival cells or silently move holdouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.prepare_ntwc_batch import SEED, build_batch, reserve_events
from scripts.screen_ntwc_index import (
    CATALOG,
    SOURCE_MAP,
    assign_roles,
    distance_km,
    extract_origins,
    intro_text,
    load_overrides,
    match_origins,
    screen,
    sequence_groups,
    sequence_windows,
    stage_m_reason,
)


def test_intro_stops_before_table_and_ignores_script() -> None:
    assert (
        intro_text("<p>Earthquake metadata</p><script>secret</script><TABLE><td>arrival</td>")
        == "Earthquake metadata"
    )


@pytest.mark.parametrize("clock", ["at 12:34:56 UTC", "at 123456Z", "at 1234 UTC"])
def test_origin_formats(clock: str) -> None:
    origins = extract_origins(
        f"An earthquake magnitude 7.2 occurred {clock} at 31.2N, 141.3E.",
        "Tsunami of January 2, 2002",
    )
    assert len(origins) == 1
    assert origins[0]["latitude"] == "31.2"
    assert origins[0]["longitude"] == "141.3"


def test_labeled_origin_coordinates_before_time() -> None:
    origins = extract_origins(
        "Earthquake magnitude 7.2 Latitude: 3.3N Longitude: 95.8E Origin Time: 00:58:53UTC",
        "December 26, 2004",
    )
    assert origins[0]["origin_time"] == "2004-12-26T00:58:53+00:00"


def test_false_same_date_match_and_hemisphere_typo_are_not_guessed() -> None:
    origin = [
        {"origin_time": "2014-04-12T20:14:39+00:00", "latitude": "-11.315", "longitude": "-162.211"}
    ]
    catalog = [
        {
            "id": "correct",
            "time": "2014-04-12T20:14:39.300Z",
            "latitude": "-11.2701",
            "longitude": "162.1481",
        },
        {
            "id": "other",
            "time": "2014-04-12T22:14:39Z",
            "latitude": "-11.315",
            "longitude": "-162.211",
        },
    ]
    assert match_origins(origin, catalog) == []
    origin[0]["longitude"] = "162.211"
    assert match_origins(origin, catalog) == ["correct"]


def test_multiple_candidates_stay_ambiguous() -> None:
    origin = [
        {"origin_time": "2004-09-05T14:57:00+00:00", "latitude": "33.184", "longitude": "137.071"}
    ]
    rows = [
        {"id": name, "time": "2004-09-05T14:57:18Z", "latitude": "33.184", "longitude": "137.071"}
        for name in ("native", "duplicate")
    ]
    assert match_origins(origin, rows) == ["duplicate", "native"]


def test_unstated_timezone_is_not_automatically_utc() -> None:
    origins = extract_origins(
        "Earthquake magnitude 7.1 occurred at 12:00:00 on January2 at 31N, 141E.",
        "January 2, 2002",
    )
    assert origins[0]["time_basis"] == "unknown"
    assert origins[0]["origin_time"] == "2002-01-02T12:00:00"
    assert (
        match_origins(
            origins,
            [{"id": "match", "time": "2002-01-02T12:00:00Z", "latitude": "31", "longitude": "141"}],
        )
        == []
    )


def test_antimeridian_distance_is_short() -> None:
    assert 20 < distance_km(0, 179.9, 0, -179.9) < 23


@pytest.mark.parametrize(
    ("magtype", "mag", "depth", "region", "reason"),
    [
        ("mwc", "7", "70", "western_pacific", "metadata_eligible"),
        ("mb", "7", "10", "western_pacific", "no_mw_family_magnitude"),
        ("mww", "6.99", "10", "western_pacific", "mw_lt_7"),
        ("mww", "7.8", "70.01", "western_pacific", "depth_gt_70"),
        ("mww", "9.1", "10", "non_pacific", "non_pacific"),
        ("mww", "7.5", "10", "boundary_review", "ambiguous_basin"),
    ],
)
def test_stage_m_rules(magtype: str, mag: str, depth: str, region: str, reason: str) -> None:
    assert (
        stage_m_reason(
            {"type": "earthquake", "magType": magtype, "mag": mag, "depth": depth}, region
        )
        == reason
    )


def test_override_needs_actual_distinct_reviews(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    for second in ("", "same", "pending"):
        path.write_text(
            f"archive_key,reason,citation,reviewer_1,reviewer_2\na,evidence,https://example.org,same,{second}\n"
        )
        with pytest.raises(ValueError):
            load_overrides(path)


def test_sequence_units_and_component_edges() -> None:
    days, km = sequence_windows(8)
    assert 900 < days < 1100  # days, not years or seconds
    assert 90 < km < 100  # half of ~190km WC subsurface length dominates
    events = [
        {"event_id": "a", "component_event_ids": "a;b"},
        {"event_id": "c", "component_event_ids": ""},
    ]
    catalog = {
        name: {"mag": "7", "time": f"2000-01-0{day}T00:00:00Z", "latitude": "0", "longitude": lon}
        for name, day, lon in (("a", 1, "100"), ("b", 1, "150"), ("c", 2, "150.01"))
    }
    groups, edges = sequence_groups(events, catalog)
    assert groups["a"] == groups["c"]
    assert edges[0]["source_component_a"] == "b"


def test_preserves_legacy_mixed_roles_and_seals_new_related_member() -> None:
    events = [
        {"event_id": name, "prior_role": role, "cohort": "contrast", "usgs_mag": "7.5"}
        for name, role in (
            ("olddev", "development"),
            ("oldsealed", "sealed_evaluation"),
            ("new", "unassigned"),
        )
    ]
    assign_roles(events, {row["event_id"]: "shared" for row in events})
    assert [row["role"] for row in events] == [
        "development",
        "sealed_evaluation",
        "sealed_evaluation",
    ]
    assert all(row["legacy_role_conflict"] == "true" for row in events)
    assert all(row["sequence_validation_status"] == "within_sequence" for row in events)


def test_stratified_draw_deterministic_and_preserves_v1_defaults() -> None:
    rows = [{"event_id": str(i), "region": str(i % 3), "cohort": str(i % 2)} for i in range(15)]
    assert reserve_events(rows, 3) == reserve_events(rows, 3, stratum_key="region", seed=SEED)
    assert reserve_events(rows, 3, stratum_key="cohort", seed="v2") == reserve_events(
        list(reversed(rows)), 3, stratum_key="cohort", seed="v2"
    )


def test_compound_magnitude_and_exposure_affect_draw_before_outcomes() -> None:
    events = [
        {
            "event_id": name,
            "prior_role": "unassigned",
            "cohort": "thrust_core",
            "usgs_mag": "7.7",
            "grouping_magnitude": magnitude,
        }
        for name, magnitude in (("a", "7.8"), ("b", "8.0"), ("usp000db93", "8.1"))
    ]
    result = assign_roles(events, {row["event_id"]: row["event_id"] for row in events})
    assert result["strata"] == {"thrust_core:ge7.8": 2}
    assert events[2]["role"] == "development"
    assert events[2]["role_basis"] == "prefreeze_outcome_exposure"


def test_complete_screen_never_calls_arrival_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pipeline.ntwc_archive as archive

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("arrival parser called before reservation")

    monkeypatch.setattr(archive, "parse_archive", forbidden)
    sources: list[dict[str, str]] = []
    payload = (
        b"<p>Earthquake magnitude 7.1 occurred at 12:00:00 UTC at 31N, 141E.</p>"
        b"<table>arrival sentinel</table>"
    )
    for i in range(118):
        path = tmp_path / f"raw/{i}.html"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(payload)
        path.with_suffix(".html.sha256").write_text(hashlib.sha256(payload).hexdigest())
        sources.append(
            {
                "archive_key": str(i),
                "label": "January 2, 2002",
                "local_path": str(path.relative_to(tmp_path)),
                "source_id": str(i),
                "url": "https://www.tsunami.gov/",
                "prior_event_id": "unknown",
                "prior_role": "unassigned",
            }
        )
    source_map = tmp_path / SOURCE_MAP
    source_map.parent.mkdir(parents=True)
    source_map.write_text(json.dumps(sources))
    catalog = tmp_path / CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        "id,time,latitude,longitude,mag,magType,depth,type\ne,2002-01-02T12:00:00Z,31,141,7.1,mwc,10,earthquake\n"
    )
    catalog.with_suffix(".csv.sha256").write_text(hashlib.sha256(catalog.read_bytes()).hexdigest())
    result = screen(tmp_path)
    assert len(result["dispositions"]) == 118  # type: ignore[arg-type]
    assert result["arrival_tables_read"] is False
    assert "arrival sentinel" not in json.dumps(result)
    # Replacing table cells cannot change an origin-only decision; digest still detects bytes.
    (tmp_path / "raw/0.html").write_text("changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        screen(tmp_path)


def test_real_v1_reproduction_when_raw_snapshot_present() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / "data/raw/ntwc/batch-2026-10-30/index.html").exists():
        pytest.skip("local raw snapshot is not shipped in Git")
    config, _ = build_batch(root)
    assert config == (root / "config/ntwc-archive-batch.toml").read_text()
