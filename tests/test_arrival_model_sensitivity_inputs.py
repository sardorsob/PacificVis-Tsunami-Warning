"""Synthetic provenance closure and exact native-item joins; no project outcomes."""

# pyright: basic
import json
import tomllib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival import model_sensitivity_inputs as adapter
from analysis.arrival.evidence import sha256, write_json, write_rows
from analysis.arrival.model_data import CONVENTIONS, lane_arrays
from analysis.arrival.model_source_components import COMPONENTS, assess_components


def fixture(root):
    """1070 synthetic rows, 35 official-shaped pages and the accepted census schema."""
    events = [
        adapter.TOHOKU_EVENT,
        adapter.CHILE_EVENT,
        *[f"event-{i:02d}" for i in range(29)],
        adapter.INFLUENTIAL_2014_EVENT,
        adapter.LATA_EVENT,
    ]
    exploration = [*events, *[f"unused-{i}" for i in range(5)]]
    confirmation = [f"confirmation-{i}" for i in range(19)]
    years = {event: 2001 + i % 19 for i, event in enumerate(exploration)}
    years[adapter.INFLUENTIAL_2014_EVENT] = years[adapter.LATA_EVENT] = 2014
    sequences = {event: f"seq-{event}" for event in exploration}
    sequences[adapter.LATA_EVENT] = sequences[adapter.INFLUENTIAL_2014_EVENT]
    normal = events[:-2]
    specs = [(event, 1) for event in normal] + [(normal[2], 2), (normal[2], 3)]
    specs += [(adapter.INFLUENTIAL_2014_EVENT, 1), (adapter.LATA_EVENT, 1)]
    rows, raw, source_info = [], {}, []
    for j, (event, page) in enumerate(specs):
        identity = (
            "recovery-ncei-6fa5e2d2459724b6"
            if event == adapter.LATA_EVENT
            else "recovery-ncei-66bfa3cd99cb7161"
            if j == 2
            else f"recovery-ncei-fixture{j:03d}"
        )
        number = 5560 if event == adapter.LATA_EVENT else 6000 + events.index(event)
        directory = "ncei-development-runups-v1" if page > 1 or j == 2 else "ncei-development-v1"
        relative = f"data/raw/arrival-recovery/{directory}/{identity}.json"
        count = (
            1
            if event == adapter.LATA_EVENT
            else 3
            if event == adapter.INFLUENTIAL_2014_EVENT
            else 33
            if j < 10
            else 32
        )
        positions = [3] if event == adapter.LATA_EVENT else list(range(1, count + 1))
        items = []
        for position in range(1, max(positions) + 1):
            item = {
                "id": 29865
                if event == adapter.LATA_EVENT and position == 3
                else j * 200 + position,
                "tsunamiEventId": number,
                "typeMeasurementId": 2 if position % 2 else 3,
                "locationName": f"Station-{j}-{position}",
                "distFromSource": 1000 + j * 20 + position,
                "year": years[event],
                "month": 1,
                "day": 1,
                "hour": 0,
                "minute": 0,
                "second": 0,
                "arrDay": 1,
                "arrHour": 0,
                "arrMin": 24,
                "travHours": 0,
                "travMins": 24,
            }
            items.append(item)
            if position not in positions:
                continue
            record = f"{identity}:{position}"
            site = f"site-{j}-{position}"
            if j == 0 and position <= 6:
                site = f"ambiguous-{(position - 1) // 2}"
            rows.append(
                {
                    "record_id": record,
                    "event_id": event,
                    "physical_site_id": site,
                    "source_label": item["locationName"],
                    "target": "NCEI-native-duration",
                    "target_minutes": "24",
                    "distance_km": str(item["distFromSource"] * 0.9),
                    "measurement_family": "tide_gauge"
                    if item["typeMeasurementId"] == 2
                    else "deep_ocean_gauge",
                    "native_distance_km": str(item["distFromSource"]),
                    "definition_conflict_candidate": str(record in adapter.DEFINITION_RECORD_IDS),
                    **{f"site_{radius}km": f"{radius}-{site}" for radius in [1, 2, 5]},
                }
            )
        raw[identity] = {"items": items, "page": page}
        source_info.append((identity, relative, event, number, page))
    ncei = lane_arrays("NCEI-native-duration", rows, sequences, set(exploration))
    primary = [record for record, keep in zip(ncei.record_ids, ncei.included, strict=True) if keep]
    unassessed = set(primary[-14:])
    triage = []
    seen_events = set()
    for row in ncei.rows:
        if (
            row["record_id"] in primary
            and row["record_id"] not in unassessed
            and row["event_id"] not in seen_events
        ):
            triage.append(row["record_id"])
            seen_events.add(row["event_id"])
            if len(triage) == 4:
                break
    for record in unassessed | set(triage):
        identity, position = record.rsplit(":", 1)
        raw[identity]["items"][int(position) - 1][
            "arrMin" if record in unassessed else "arrHour"
        ] = None if record in unassessed else 12
    for identity, relative, *_ in source_info:
        write_json(root / relative, raw[identity])
    proof = "artifacts/generated/ntwc-batch/recovery-execution-v1/fixture-check.json"
    write_json(root / proof, {"scope": "synthetic explicit pagination evidence"})
    manifest = []
    for identity, relative, event, number, page in source_info:
        station = {
            "development_event_id": event,
            "event_id": event,
            "ncei_event_id": number,
            "ncei_origin_utc": f"{years[event]}-01-01T00:00:00+00:00",
        }
        if page > 1:
            parent = source_info[2]
            station["pagination_evidence"] = {
                "page_requested": page,
                "total_pages": 3,
                "page1_source_id": parent[0],
                "page1_sha256": sha256(root / parent[1]),
                "qa_receipt": proof,
                "qa_sha256": sha256(root / proof),
            }
        manifest.append(
            {
                "source_id": identity,
                "publisher": "NOAA NCEI",
                "local_path": relative,
                "sha256": sha256(root / relative),
                "url": "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/runups?"
                f"tsunamiEventId={number}&typeMeasurementId=2&typeMeasurementId=3&itemsPerPage=200&page={page}",
                "notes": json.dumps({"station_metadata": json.dumps(station)}),
            }
        )
    write_rows(root / adapter.SOURCE_LEDGER, manifest)
    lanes = {ncei.target: ncei}
    for target in ["T-OBS", "T-CAL"]:
        table = [
            {
                "record_id": f"{target}-{i}",
                "event_id": events[i],
                "physical_site_id": f"ntwc-{i}",
                "target": target,
                "target_minutes": str(20 + i),
                "distance_km": str(100 + 600 * i),
                "definition_conflict_candidate": "False",
            }
            for i in range(3)
        ]
        lanes[target] = lane_arrays(target, table, sequences, set(exploration))
    for target, lane in lanes.items():
        write_rows(root / adapter.TARGET_FILES[target], list(lane.rows))
    write_rows(
        root / adapter.METADATA,
        [
            {
                "event_id": event,
                "origin_utc": f"{years.get(event, 2010)}-01-01T00:00:00+00:00",
                "sequence_group": sequences.get(event, f"seq-{event}"),
            }
            for event in [*exploration, *confirmation]
        ],
    )
    split = root / adapter.SPLIT
    split.parent.mkdir(parents=True, exist_ok=True)
    split.write_text(
        f"metadata_only = true\nexploration = {json.dumps(exploration)}\n"
        f"confirmation = {json.dumps(confirmation)}\n"
    )
    write_json(root / adapter.SOURCE_MANIFEST, {"schema_version": "paper_eda_inputs_v1"})
    contract = dict(CONVENTIONS)
    inputs = {
        path: sha256(root / path)
        for path in [
            *adapter.TARGET_FILES.values(),
            adapter.METADATA,
            adapter.SPLIT,
            adapter.SOURCE_MANIFEST,
        ]
    }
    text = (
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        + "\n[inputs]\n"
    )
    text += (
        "\n".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in inputs.items())
        + "\n"
    )
    (root / adapter.CONTRACT).write_text(text)
    config = root / adapter.CENSUS_CONFIG
    config.write_text(
        'schema_version = "arrival_native_component_census_v1"\n'
        "large_disagreement_minutes = 60\n"
        f'source_manifest = "{adapter.SOURCE_LEDGER}"\n'
        f'source_manifest_sha256 = "{sha256(root / adapter.SOURCE_LEDGER)}"\n'
    )
    census = []
    for row, included in zip(ncei.rows, ncei.included, strict=True):
        identity, position = row["record_id"].rsplit(":", 1)
        item = raw[identity]["items"][int(position) - 1]
        values = {
            **{
                key: row[key]
                for key in ["record_id", "event_id", "physical_site_id", "source_label"]
            },
            "included_primary": bool(included),
            "native_item_id": item["id"],
            "native_tsunami_event_id": item["tsunamiEventId"],
            "reported_minutes": 24,
            **{key: item.get(key) for key in COMPONENTS},
            **assess_components(item, 60),
        }
        census.append(
            {key: "not_applicable" if value is None else value for key, value in values.items()}
        )
    write_rows(
        root / adapter.CENSUS_RECORDS,
        [{key: str(value) for key, value in row.items()} for row in census],
    )
    historical = [
        path
        for path in adapter.required_sensitivity_paths()
        if path
        not in {
            adapter.CENSUS_REVIEW,
            *adapter.CENSUS_OUTPUTS,
            "analysis/arrival/model_sensitivity_inputs.py",
            "analysis/arrival/model_sensitivity_design.py",
            "analysis/arrival/model_curvature.py",
            "analysis/arrival/model_scale.py",
            "pyproject.toml",
            "uv.lock",
        }
    ]
    historical += [
        "analysis/arrival/model_validation_report.py",
        "scripts/audit_arrival_source_components.py",
    ]
    for path in historical:
        if not (root / path).is_file():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("synthetic source closure")
    census_files = set(historical) | {relative for _, relative, *_ in source_info} | {proof}
    assert len(census_files) == 50
    census_pins = {path: sha256(root / path) for path in census_files}
    write_json(
        root / adapter.CENSUS_INPUTS,
        {
            "files": census_pins,
            "design": tomllib.loads(config.read_text()),
            "raw_pages": 35,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    for path in adapter.CENSUS_OUTPUTS:
        if not (root / path).is_file():
            write_json(root / path, {"scope": "synthetic accepted output"})
    checks = {
        "all_records": 1070,
        "primary_records": 1064,
        "assessed_all": 1056,
        "assessed_primary": 1050,
        "unassessed": 14,
        "flagged": 4,
        "flagged_events": 4,
        "authorized_exploration_pages": 35,
        "input_pins": 50,
    }
    write_json(
        root / adapter.CENSUS_REVIEW,
        {
            "schema_version": "arrival_native_components_acceptance_v1",
            "status": "accepted_exploration_source_component_census",
            "checks": checks,
            "files": {path: sha256(root / path) for path in adapter.CENSUS_OUTPUTS},
        },
    )
    for path in adapter.required_sensitivity_paths():
        if not (root / path).is_file():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("synthetic adapter source")
    pins = {
        path: sha256(root / path) for path in {*adapter.required_sensitivity_paths(), *census_pins}
    }
    return lanes, pins, census, raw, manifest


def test_full_synthetic_adapter_preserves_order_native_values_and_exact_cohorts(tmp_path):
    lanes, pins, _, _, _ = fixture(tmp_path)
    lane = lanes["NCEI-native-duration"]
    original = lane.y.copy()
    metadata = adapter.load_sensitivity_inputs(tmp_path, lanes, pins)
    assert metadata.lata_record_id == adapter.LATA_RECORD
    assert (
        len(metadata.triage_record_ids) == 4 and len(metadata.component_assessed_record_ids) == 1050
    )
    assert metadata.definition_record_ids == adapter.DEFINITION_RECORD_IDS
    assert (
        metadata.influence_sequences["influential2014"] == f"seq-{adapter.INFLUENTIAL_2014_EVENT}"
    )
    assert metadata.event_years[adapter.LATA_EVENT] == 2014
    np.testing.assert_array_equal(
        metadata.coastal, [row["measurement_family"] == "tide_gauge" for row in lane.rows]
    )
    np.testing.assert_array_equal(
        metadata.publisher_distance_km, [float(row["native_distance_km"]) for row in lane.rows]
    )
    assert metadata.site_keys_by_km[2] == tuple(row["site_2km"] for row in lane.rows)
    np.testing.assert_array_equal(lane.y, original)


@pytest.mark.parametrize("missing", ["receipt", "input_closure", "pagination", "source"])
def test_incomplete_pins_fail_before_census_or_raw_parse(tmp_path, monkeypatch, missing):
    lanes, pins, _, _, manifest = fixture(tmp_path)
    if missing == "receipt":
        pins.pop(adapter.CENSUS_REVIEW)
    elif missing == "input_closure":
        pins.pop("analysis/arrival/model_validation_report.py")
    elif missing == "pagination":
        pins.pop("artifacts/generated/ntwc-batch/recovery-execution-v1/fixture-check.json")
    else:
        pins.pop(manifest[0]["local_path"])
    original = adapter.read_rows

    def guarded(path):
        assert str(path.relative_to(tmp_path)) != adapter.CENSUS_RECORDS, (
            "census parsed before closure"
        )
        return original(path)

    monkeypatch.setattr(adapter, "read_rows", guarded)
    original_text = Path.read_text

    def text_guard(path, *args, **kwargs):
        assert "data/raw/" not in str(path), "raw parsed before closure"
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", text_guard)
    with pytest.raises(ValueError):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)


def test_source_hash_drift_fails_before_census(tmp_path, monkeypatch):
    lanes, pins, _, _, manifest = fixture(tmp_path)
    (tmp_path / manifest[0]["local_path"]).write_text("changed source")
    original = adapter.read_rows

    def guard(path):
        assert str(path.relative_to(tmp_path)) != adapter.CENSUS_RECORDS
        return original(path)

    monkeypatch.setattr(adapter, "read_rows", guard)
    with pytest.raises(ValueError, match="hash"):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)


def test_protected_lane_event_fails_before_census_or_raw_parse(tmp_path, monkeypatch):
    lanes, pins, _, _, _ = fixture(tmp_path)
    lane = lanes["NCEI-native-duration"]
    lanes[lane.target] = replace(lane, event_ids=("confirmation-0", *lane.event_ids[1:]))
    original = adapter.read_rows

    def guard(path):
        assert str(path.relative_to(tmp_path)) != adapter.CENSUS_RECORDS
        return original(path)

    monkeypatch.setattr(adapter, "read_rows", guard)
    with pytest.raises(ValueError, match="exploration"):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)


def test_symlink_escape_is_rejected_before_any_table_parse(tmp_path, monkeypatch):
    lanes, pins, _, _, _ = fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_text("untrusted")
    link = tmp_path / "escape.json"
    link.symlink_to(outside)
    pins["escape.json"] = sha256(outside)
    monkeypatch.setattr(
        adapter, "read_rows", lambda *args: pytest.fail("parsed before boundary validation")
    )
    with pytest.raises(ValueError, match="outside"):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)


def repin(root, pins):
    """Refresh only the fake accepted closure after an intentional fixture mutation."""
    manifest = adapter.read_rows(root / adapter.SOURCE_LEDGER)
    for source in manifest:
        source["sha256"] = sha256(root / source["local_path"])
    by_id = {source["source_id"]: source for source in manifest}
    for source in manifest:
        notes = json.loads(source["notes"])
        station = json.loads(notes["station_metadata"])
        if "pagination_evidence" in station:
            pagination = station["pagination_evidence"]
            pagination["page1_sha256"] = by_id[pagination["page1_source_id"]]["sha256"]
            notes["station_metadata"] = json.dumps(station)
            source["notes"] = json.dumps(notes)
    write_rows(root / adapter.SOURCE_LEDGER, manifest)
    config = tomllib.loads((root / adapter.CENSUS_CONFIG).read_text())
    config["source_manifest_sha256"] = sha256(root / adapter.SOURCE_LEDGER)
    (root / adapter.CENSUS_CONFIG).write_text(
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in config.items()) + "\n"
    )
    inputs = json.loads((root / adapter.CENSUS_INPUTS).read_text())
    inputs["files"] = {path: sha256(root / path) for path in inputs["files"]}
    inputs["design"] = config
    write_json(root / adapter.CENSUS_INPUTS, inputs)
    review = json.loads((root / adapter.CENSUS_REVIEW).read_text())
    review["files"] = {path: sha256(root / path) for path in review["files"]}
    write_json(root / adapter.CENSUS_REVIEW, review)
    return {path: sha256(root / path) for path in pins}


def test_public_preflight_parses_no_csv_or_raw_source(tmp_path, monkeypatch):
    _, pins, _, _, _ = fixture(tmp_path)
    monkeypatch.setattr(adapter, "read_rows", lambda *args: pytest.fail("CSV parsed by preflight"))
    monkeypatch.setattr(
        adapter, "prepare_sources", lambda *args: pytest.fail("native source lookup by preflight")
    )
    monkeypatch.setattr(
        adapter, "_native_page", lambda *args: pytest.fail("raw parsed by preflight")
    )
    assert adapter.verify_sensitivity_inputs(tmp_path, pins) is None


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_census",
        "missing_census",
        "wrong_item_id",
        "wrong_duration",
        "wrong_role",
        "missing_distance",
        "wrong_distance",
        "duplicate_native",
        "wrong_family",
    ],
)
def test_exact_census_and_native_join_rejects_inconsistent_supplied_evidence(tmp_path, change):
    lanes, pins, census, raw, manifest = fixture(tmp_path)
    lane = lanes["NCEI-native-duration"]
    record = lane.record_ids[0]
    saved = next(row for row in census if row["record_id"] == record)
    identity, ordinal = record.rsplit(":", 1)
    item = raw[identity]["items"][int(ordinal) - 1]
    if change == "duplicate_census":
        census.append(dict(saved))
    elif change == "missing_census":
        census.remove(saved)
    elif change == "wrong_item_id":
        saved["native_item_id"] = 999999
    elif change == "wrong_duration":
        saved["reported_minutes"] = 25
    elif change == "wrong_role":
        saved["included_primary"] = not saved["included_primary"]
    elif change == "missing_distance":
        item["distFromSource"] = None
    elif change == "wrong_distance":
        item["distFromSource"] += 1
    elif change == "duplicate_native":
        raw[identity]["items"][1]["id"] = raw[identity]["items"][0]["id"]
    else:
        item["typeMeasurementId"] = 3 if item["typeMeasurementId"] == 2 else 2
    relative = next(source["local_path"] for source in manifest if source["source_id"] == identity)
    write_json(tmp_path / relative, raw[identity])
    write_rows(
        tmp_path / adapter.CENSUS_RECORDS,
        [{key: str(value) for key, value in row.items()} for row in census],
    )
    pins = repin(tmp_path, pins)
    expected = {
        "duplicate_census": "complete unique exact census",
        "missing_census": "complete unique exact census",
        "wrong_item_id": "identity or primary-role mismatch",
        "wrong_duration": "duration changed",
        "wrong_role": "identity or primary-role mismatch",
        "missing_distance": "publisher distance; no imputation",
        "wrong_distance": "publisher distance disagrees",
        "duplicate_native": "duplicate native item",
        "wrong_family": "canonical EDA family",
    }
    with pytest.raises(ValueError, match=expected[change]):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)


def test_post_preflight_native_drift_is_refused_before_json_parse(tmp_path, monkeypatch):
    lanes, pins, _, _, manifest = fixture(tmp_path)
    original = adapter.read_rows
    source = tmp_path / manifest[0]["local_path"]

    def injected(path):
        values = original(path)
        if str(path.relative_to(tmp_path)) == adapter.CENSUS_RECORDS:
            source.write_text('{"forbidden_unpinned_payload":true}')
        return values

    original_json = json.loads

    def guarded(payload, *args, **kwargs):
        assert "forbidden_unpinned_payload" not in str(payload), "unpinned raw JSON parsed"
        return original_json(payload, *args, **kwargs)

    monkeypatch.setattr(adapter, "read_rows", injected)
    monkeypatch.setattr(adapter.json, "loads", guarded)
    with pytest.raises(ValueError, match="hash changed before raw parse"):
        adapter.load_sensitivity_inputs(tmp_path, lanes, pins)
