"""Synthetic future admission and membership checks; no historical response reads."""

# pyright: basic
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival import model_development_data as data
from analysis.arrival.evidence import sha256, write_json, write_rows
from analysis.arrival.model_data import VREF_KM_MIN


def fixture(
    root,
    monkeypatch,
    *,
    ambiguous=False,
    ambiguous_target="NCEI-native-duration",
    legacy_ntwc=False,
    corrupt=None,
):
    for name in data.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic consumed source")
    exp = [data.CROSS_EXPLORATION, *[f"exp-{i:02d}" for i in range(1, 38)]]
    check = [data.CROSS_CHECK, *[f"check-{i:02d}" for i in range(1, 19)]]
    seq = {exp[0]: data.CROSS_SEQUENCE, check[0]: data.CROSS_SEQUENCE}
    seq.update({event: f"seq-{event}" for event in exp[1:33] + check[1:]})
    seq.update({exp[i]: seq[exp[i - 32]] for i in range(33, 38)})
    if corrupt == "sequence":
        seq[data.CROSS_CHECK] = "unapproved-crossing-change"
    write_rows(
        root / data.METADATA,
        [{"event_id": event, "sequence_group": seq[event]} for event in exp + check],
    )
    (root / data.SPLIT).write_text(
        "exploration = " + json.dumps(exp) + "\nconfirmation = " + json.dumps(check) + "\n"
    )
    prior = {"alpha_sd": 0.5, "beta_sd": 0.25, "tau_sd": 0.4, "sigma_sd": 0.4}
    monkeypatch.setattr(
        data,
        "read_prior",
        lambda *args: {k: v * (2 if args[-1] == "wider" else 1) for k, v in prior.items()},
    )
    monkeypatch.setattr(
        data,
        "read_curvature_prior",
        lambda *args: {**prior, "gamma_sd": 0.5 if args[-1] == "base" else 1.0},
    )
    original_tables = {}
    for target, (ne, nc, ee, ec) in data.COUNTS.items():
        for role, count, event_count, names, files in [
            ("exploration", ne, ee, exp, data.TARGET_FILES),
            ("confirmation", nc, ec, check, data.CHECK_FILES),
        ]:
            rows = []
            if target == "NCEI-native-duration" and role == "exploration":
                events = [exp[0]] * 24 + [exp[1 + i % 32] for i in range(1040)] + [exp[1]] * 6
            else:
                eligible = (
                    names[:event_count]
                    if target == "NCEI-native-duration"
                    else names[1 : event_count + 1]
                )
                events = [eligible[i % event_count] for i in range(count)]
            exclusions = sorted(data.OLD_EXCLUSIONS)
            for i, event in enumerate(events):
                record = f"{target}-{role}-{i:04d}"
                site = f"{role}-site-{i}"
                if target == "NCEI-native-duration" and role == "exploration" and i >= 1064:
                    record, site = exclusions[i - 1064], f"old-ambiguous-{(i - 1064) // 2}"
                if ambiguous and target == ambiguous_target and role == "confirmation" and i < 2:
                    event, site = events[0], "new-ambiguous"
                if (
                    legacy_ntwc
                    and target != "NCEI-native-duration"
                    and role == "exploration"
                    and i < 2
                ):
                    event, site = events[0], "legacy-ambiguous"
                distance = 500 + i * 10
                y = (-20 if i % 2 else 15) if target == "T-CAL" else 20 + i
                rows.append(
                    dict(
                        record_id=record,
                        event_id=event,
                        target=target,
                        physical_site_id=site,
                        distance_km=str(distance),
                        reference_minutes=str(distance / VREF_KM_MIN),
                        target_minutes=str(y),
                        provider="literal synthetic provider",
                    )
                )
            if target == "NCEI-native-duration" and role == "confirmation":
                if corrupt == "role":
                    rows[0]["event_id"] = exp[1]
                elif corrupt == "distance":
                    rows[0]["distance_km"] = "0"
                elif corrupt == "reference":
                    rows[0]["reference_minutes"] = "1"
                elif corrupt == "native":
                    rows[0]["target_minutes"] = "-1"
                elif corrupt == "record":
                    rows[1]["record_id"] = rows[0]["record_id"]
            write_rows(root / files[target], rows)
            original_tables[target, role] = rows
    # Pinned synthetic substitutes for the exact historical accepted table SHAs.
    monkeypatch.setattr(
        data, "CHECK_SHA", {name: sha256(root / name) for name in data.CHECK_FILES.values()}
    )
    old_input, old_lock = "1" * 64, "2" * 64
    source = root / "synthetic-native-source.txt"
    source.write_text("synthetic native producer source")
    write_json(
        root / data.SOURCE_MANIFEST,
        {
            "pre_rename_manifest_sha256": old_input,
            "files": [{"path": source.name, "sha256": sha256(source)}],
        },
    )
    producer = root / "synthetic-producer.py"
    producer.write_text("historical producer source")
    code = {"old-producer.py": "3" * 64}
    entries = [
        {
            "old_path": "old-producer.py",
            "new_path": producer.name,
            "before_sha256": "3" * 64,
            "after_sha256": sha256(producer),
        }
    ]
    generation_metadata = {}
    for folder in sorted(
        {
            str(Path(name).parent)
            for name in [*data.TARGET_FILES.values(), *data.CHECK_FILES.values()]
        }
    ):
        module = "C8" if folder.endswith("estimated-minus-observed-timing-distributions") else "C1"
        split = "confirmation" if "/confirmation/" in folder else "exploration"
        path = root / folder
        write_json(
            path / "generation-input-and-code-checksums.json",
            {"code": code, "frozen_input_manifest_sha256": old_input},
        )
        write_json(path / "original-run-metadata.json", {"split": split, "module": module})
        members = sorted(p for p in path.iterdir() if p.is_file())
        write_json(
            path / "output-file-checksums.json",
            [{"path": p.name, "sha256": sha256(p)} for p in members],
        )
        members.append(path / "output-file-checksums.json")
        for p in members:
            name = str(p.relative_to(root))
            entries.append(
                {
                    "old_path": "old/" + name,
                    "new_path": name,
                    "before_sha256": sha256(p),
                    "after_sha256": sha256(p),
                }
            )
        generation_metadata[split + ":" + module] = {
            name: sha256(path / name)
            for name in ["generation-input-and-code-checksums.json", "original-run-metadata.json"]
        }
    write_json(
        root / data.LEDGER,
        {
            "files": entries,
            "original_confirmation_lock_sha256": old_lock,
            "original_input_manifest_sha256": old_input,
            "original_generation_metadata_preserved": True,
        },
    )
    write_json(
        root / data.LOCK,
        {
            "inputs_sha256": sha256(root / data.SOURCE_MANIFEST),
            "generation_inputs_sha256": old_input,
            "pre_rename_lock_sha256": old_lock,
            "path_migration_manifest": data.LEDGER,
            "code": code,
            "layout_replay_code": {producer.name: sha256(producer)},
            "generation_metadata_sha256": generation_metadata,
        },
    )
    write_json(
        root / data.CONFIRMATION_QA,
        {
            "status": "ACCEPTED locked confirmation artifacts with scientific limitations",
            "lock_sha256": old_lock,
        },
    )
    write_json(
        root / data.RENAME_VERIFICATION,
        {"status": "ACCEPTED descriptive artifact/source migration at verified worktree version"},
    )
    write_json(
        root / data.RENAME_QA,
        {
            "status": "ACCEPTED exact main HEAD landing of descriptive EDA migration",
            "bindings": {
                "ledger_sha256": sha256(root / data.LEDGER),
                "lock_sha256": sha256(root / data.LOCK),
                "file_renaming_verification_sha256": sha256(root / data.RENAME_VERIFICATION),
            },
        },
    )
    inputs = {
        name: sha256(root / name)
        for name in [*data.TARGET_FILES.values(), data.SPLIT, data.METADATA, data.SOURCE_MANIFEST]
    }
    contract = [key + " = " + json.dumps(value) for key, value in data.CONVENTIONS.items()]
    contract += ["[inputs]"] + [
        json.dumps(key) + " = " + json.dumps(value) for key, value in inputs.items()
    ]
    for target in data.TARGET_FILES:
        contract += [
            f'[lanes."{target}"]',
            "excluded_ids = "
            + json.dumps(sorted(data.OLD_EXCLUSIONS) if target == "NCEI-native-duration" else []),
        ]
    (root / data.CONTRACT).write_text("\n".join(contract) + "\n")
    (root / data.SCORING).write_text(
        'schema_version = "arrival_model_scoring_v1"\n'
        'primary = "equal_event_mean_normalized_joint_native_minute_log_predictive_density"\n'
        'validation_unit = "leave_whole_sequence_out_refits"\n'
    )
    models = {}
    for target, kind in [
        ("NCEI-native-duration", "mean-curvature"),
        ("T-OBS", "pooled"),
        ("T-CAL", "event"),
    ]:
        active = {name for name, _ in data._population_spec(target, kind).values()}
        values = {**prior, "gamma_sd": 0.5}
        models[target] = [
            {
                "role": "selected",
                "kind": kind,
                "prior_variant": "base",
                "base_prior_sd": {name: values[name] for name in active},
                "wider_prior_sd": None,
            }
        ]
    decision_name = "scientific-decision.json"
    decision = {
        "models": models,
        "distance_mode": "geodesic_km",
        "observation_contract": data.CONTRACT,
        "scoring_contract": data.SCORING,
        "seeds": {"check": 2926110800, "full_development": 2936110800},
    }
    write_json(root / decision_name, decision)
    write_json(
        root / data.MS5_REVIEW,
        {
            "status": "accepted_exploration_sensitivity_analysis",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {source.name: sha256(source)},
        },
    )
    files = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    freeze = {
        **decision,
        "status": "accepted_arrival_model_specification_freeze",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "no_retuning_after_development_check": True,
        "ms5_report_review": data.MS5_REVIEW,
        "ms5_decision": decision_name,
        "crossing_policy": "uniform_purge_all_check_sequences",
        "files": files,
    }
    write_json(root / data.FREEZE, freeze)
    pins = {**files, data.FREEZE: sha256(root / data.FREEZE)}
    return pins, original_tables


def accept_check(root, pins):
    write_json(
        root / data.CHECK_REVIEW,
        {
            "status": "accepted_frozen_arrival_development_check",
            "independent_checker": True,
            "completed_once": True,
            "no_retuning": True,
            "confirmation_outcomes_parsed": True,
            "reserved_outcomes": "sealed",
            "specification_freeze": data.FREEZE,
            "specification_freeze_sha256": pins[data.FREEZE],
            "files": dict(pins),
        },
    )
    return {**pins, data.CHECK_REVIEW: sha256(root / data.CHECK_REVIEW)}


def test_exact_protected_views_transforms_purge_and_restored_union(tmp_path, monkeypatch):
    pins, originals = fixture(tmp_path, monkeypatch)
    result = data.load_check_lanes(tmp_path, pins)
    assert "combined" not in result
    assert result["provenance"]["evaluation_performed"] is False
    for target in data.TARGET_FILES:
        train, held = result["training_purged"][target], result["check"][target]
        assert data.CROSS_SEQUENCE not in set(np.asarray(train.sequences)[train.included])
        assert held.y.tolist() == [
            float(row["target_minutes"])
            for row in sorted(originals[target, "confirmation"], key=lambda row: row["record_id"])
        ]
        assert held.rows[0]["provider"] == "literal synthetic provider"
        if target == "T-CAL":
            assert (held.y < 0).any()
            np.testing.assert_array_equal(held.response, held.y)
        else:
            np.testing.assert_allclose(
                held.response, np.log(held.y) - np.log(held.reference_minutes)
            )
            np.testing.assert_allclose(held.x, np.log(held.distance_km / 1000))
    ncei = result["membership"]["NCEI-native-duration"]
    assert len(ncei["purged_primary_ids"]) == 24 and len(ncei["training_purged_ids"]) == 1040
    assert set(ncei["excluded_ids"]) == data.OLD_EXCLUSIONS
    assert data.CROSS_CHECK in result["check"]["NCEI-native-duration"].event_ids
    full = data.load_full_development_lanes(tmp_path, accept_check(tmp_path, pins))
    for target, lane in full["combined"].items():
        assert len(lane.rows) == sum(data.COUNTS[target][:2])
        assert set(lane.record_ids) == set(full["membership"][target]["exploration_pre_ids"]) | set(
            full["membership"][target]["check_pre_ids"]
        )
    assert full["combined"]["NCEI-native-duration"].included.sum() == 1215
    assert data.CROSS_EXPLORATION in set(
        np.asarray(full["combined"]["NCEI-native-duration"].event_ids)[
            full["combined"]["NCEI-native-duration"].included
        ]
    )


@pytest.mark.parametrize(
    "failure",
    [
        "no_freeze",
        "pending",
        "no_ms5",
        "missing_producer",
        "drift",
        "publisher_distance",
        "bool_seed",
        "wrong_prior",
    ],
)
def test_admission_failures_precede_every_response_parse(tmp_path, monkeypatch, failure):
    pins, _ = fixture(tmp_path, monkeypatch)
    freeze = json.loads((tmp_path / data.FREEZE).read_text())
    if failure == "no_freeze":
        pins.pop(data.FREEZE)
    elif failure == "no_ms5":
        pins.pop(data.MS5_REVIEW)
    elif failure == "missing_producer":
        pins.pop(next(name for name in pins if name.endswith("output-file-checksums.json")))
    elif failure == "drift":
        (tmp_path / next(iter(data.CHECK_FILES.values()))).write_text("changed source")
    else:
        if failure == "pending":
            freeze["status"] = "pending"
        elif failure == "publisher_distance":
            freeze["distance_mode"] = "publisher_native_km"
        elif failure == "bool_seed":
            freeze["seeds"]["check"] = True
        elif failure == "wrong_prior":
            freeze["models"]["T-OBS"][0]["base_prior_sd"]["beta_sd"] = 0.25
        write_json(tmp_path / data.FREEZE, freeze)
        pins[data.FREEZE] = sha256(tmp_path / data.FREEZE)
    monkeypatch.setattr(data, "read_rows", lambda *args: pytest.fail("CSV parsed before admission"))
    with pytest.raises(ValueError):
        data.load_check_lanes(tmp_path, pins)


def test_full_mode_requires_same_freeze_completed_check_before_response_parse(
    tmp_path, monkeypatch
):
    pins, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        data, "read_rows", lambda *args: pytest.fail("CSV parsed before full admission")
    )
    with pytest.raises(ValueError, match="metadata pin missing"):
        data.load_full_development_lanes(tmp_path, pins)
    pins = accept_check(tmp_path, pins)
    doc = json.loads((tmp_path / data.CHECK_REVIEW).read_text())
    doc["specification_freeze_sha256"] = "0" * 64
    write_json(tmp_path / data.CHECK_REVIEW, doc)
    pins[data.CHECK_REVIEW] = sha256(tmp_path / data.CHECK_REVIEW)
    with pytest.raises(ValueError, match="completed frozen one-check"):
        data.load_full_development_lanes(tmp_path, pins)


@pytest.mark.parametrize("target", list(data.TARGET_FILES))
def test_new_ambiguous_native_edges_stop_with_explicit_ids(tmp_path, monkeypatch, target):
    pins, _ = fixture(tmp_path, monkeypatch, ambiguous=True, ambiguous_target=target)
    with pytest.raises(
        ValueError, match="unapproved ambiguous check.*requires_review_before_fit"
    ) as caught:
        data.load_check_lanes(tmp_path, pins)
    assert f"{target}-confirmation-0000" in str(caught.value)
    assert f"{target}-confirmation-0001" in str(caught.value)
    with pytest.raises(ValueError, match="unapproved ambiguous check"):
        data.load_full_development_lanes(tmp_path, accept_check(tmp_path, pins))


def test_legacy_ntwc_exploration_edges_preserved_flagged_and_old_ncei_six_intact(
    tmp_path, monkeypatch
):
    pins, _ = fixture(tmp_path, monkeypatch, legacy_ntwc=True)
    checked = data.load_check_lanes(tmp_path, pins)
    full = data.load_full_development_lanes(tmp_path, accept_check(tmp_path, pins))
    for target in ["T-OBS", "T-CAL"]:
        expected = [f"{target}-exploration-0000", f"{target}-exploration-0001"]
        for result in [checked, full]:
            member = result["membership"][target]
            assert member["legacy_exploration_repeated_edge_ids"] == expected
            assert member["legacy_repeated_edge_disposition"].endswith("no_independence_claim")
            assert set(expected) <= set(member["exploration_primary_ids"])
            assert member["excluded_ids"] == []
        assert full["combined"][target].included.all()
    for result in [checked, full]:
        member = result["membership"]["NCEI-native-duration"]
        assert set(member["excluded_ids"]) == data.OLD_EXCLUSIONS
        assert set(member["legacy_exploration_repeated_edge_ids"]) == data.OLD_EXCLUSIONS
        assert member["counts"]["training_purged"] == 1040
        assert member["counts"]["combined_primary"] == 1215


def test_source_recheck_after_parsing_rejects_drift(tmp_path, monkeypatch):
    pins, _ = fixture(tmp_path, monkeypatch)
    reader = data.read_rows

    def read_and_change(path):
        rows = reader(path)
        if str(path).endswith(next(iter(data.CHECK_FILES.values()))):
            (tmp_path / "synthetic-native-source.txt").write_text("changed while reading")
        return rows

    monkeypatch.setattr(data, "read_rows", read_and_change)
    with pytest.raises(ValueError, match="SHA changed"):
        data.load_check_lanes(tmp_path, pins)


@pytest.mark.parametrize("corrupt", ["role", "distance", "reference", "native", "record"])
def test_native_roles_ids_positive_units_and_reference_remain_literal(
    tmp_path, monkeypatch, corrupt
):
    pins, _ = fixture(tmp_path, monkeypatch, corrupt=corrupt)
    with pytest.raises(ValueError):
        data.load_check_lanes(tmp_path, pins)


def test_new_metadata_crossing_stops_before_response_body(tmp_path, monkeypatch):
    pins, _ = fixture(tmp_path, monkeypatch, corrupt="sequence")
    reader = data.read_rows

    def only_metadata(path):
        assert str(path).endswith(data.METADATA), "response body opened after unapproved metadata"
        return reader(path)

    monkeypatch.setattr(data, "read_rows", only_metadata)
    with pytest.raises(ValueError, match="single approved crossing"):
        data.load_check_lanes(tmp_path, pins)
