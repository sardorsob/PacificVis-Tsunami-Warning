"""Data and split boundaries must hold before any scientific likelihood."""

from __future__ import annotations

import builtins
import copy
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival.evidence import sha256, write_rows
from analysis.arrival.model_data import (
    CONTRACT,
    METADATA,
    SOURCE_MANIFEST,
    SPLIT,
    TARGET_FILES,
    lane_arrays,
    load_lanes,
    sequence_folds,
    write_data_bundle,
)


def records() -> list[dict[str, str]]:
    return [
        {
            "record_id": f"r{i}",
            "event_id": event,
            "physical_site_id": site,
            "distance_km": str(distance),
            "target_minutes": "20",
            "target": "T-OBS",
            "precision_seconds": "unknown",
        }
        for i, (event, site, distance) in enumerate(
            [("e1", "s1", 100), ("e2", "s1", 200), ("e3", "s2", 1000)]
        )
    ]


SEQUENCES = {"e1": "q1", "e2": "q2", "e3": "q1"}


def lane(rows: list[dict[str, str]] | None = None):
    return lane_arrays("T-OBS", records() if rows is None else rows, SEQUENCES, set(SEQUENCES))


def test_sequence_purge_seen_sites_and_fixed_reference() -> None:
    data = lane()
    folds = sequence_folds(data)
    held = next(f for f in folds if f.sequence_id == "q1")
    assert data.record_ids == ("r0", "r1", "r2")
    assert held.train.tolist() == [1]
    assert held.test.tolist() == [0, 2]
    assert held.seen_site.tolist() == [True, False]
    np.testing.assert_allclose(data.x, np.log([0.1, 0.2, 1]))
    np.testing.assert_allclose(data.response, np.log(data.y / data.reference_minutes))
    assert "interval_lower" not in data.rows[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_minutes", "inf"),
        ("target_minutes", "nan"),
        ("target_minutes", "0"),
        ("distance_km", "0"),
        ("distance_km", "inf"),
        ("physical_site_id", "unknown"),
        ("physical_site_id", ""),
        ("event_id", "unknown"),
        ("target", "T-CAL"),
    ],
)
def test_invalid_required_fields_fail_closed(field: str, value: str) -> None:
    rows = records()
    rows[0][field] = value
    with pytest.raises(ValueError):
        lane(rows)


def test_duplicate_ids_unknown_sequence_and_forbidden_roles() -> None:
    rows = records()
    rows[1]["record_id"] = rows[0]["record_id"]
    with pytest.raises(ValueError, match="unique"):
        lane(rows)
    with pytest.raises(ValueError, match="sequence"):
        lane_arrays("T-OBS", records(), {**SEQUENCES, "e1": "unknown"}, set(SEQUENCES))
    with pytest.raises(ValueError, match="exploration"):
        lane_arrays("T-OBS", records(), SEQUENCES, {"e1", "e2"})


def test_calibration_is_signed_and_finite() -> None:
    rows = records()
    for r in rows:
        r.update(target="T-CAL", target_minutes="-3")
    data = lane_arrays("T-CAL", rows, SEQUENCES, set(SEQUENCES))
    np.testing.assert_array_equal(data.response, [-3, -3, -3])
    rows[0]["target_minutes"] = "nan"
    with pytest.raises(ValueError):
        lane_arrays("T-CAL", rows, SEQUENCES, set(SEQUENCES))


def test_repeated_ncei_edges_are_preserved_and_excluded_as_a_group() -> None:
    rows = records()
    for row in rows:
        row["target"] = "NCEI-native-duration"
    other = copy.deepcopy(rows[0])
    other.update(record_id="r3", target_minutes="900")
    rows.append(other)
    data = lane_arrays("NCEI-native-duration", rows, SEQUENCES, set(SEQUENCES))
    assert len(data.rows) == 4
    assert data.included.tolist() == [False, True, True, False]
    changed = copy.deepcopy(rows)
    changed[3]["target_minutes"] = "1"
    alternate = lane_arrays("NCEI-native-duration", changed, SEQUENCES, set(SEQUENCES))
    np.testing.assert_array_equal(alternate.included, data.included)


def test_real_loader_only_reads_five_pinned_exploration_or_metadata_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    opened: set[Path] = set()
    original = Path.open

    def watch(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "r" in str(args[0] if args else kwargs.get("mode", "r")):
            opened.add(path.resolve())
        return original(path, *args, **kwargs)  # type: ignore[arg-type]

    native_open = builtins.open

    def watch_native(file: object, mode: str = "r", *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if isinstance(file, (str, Path)) and "r" in mode:
            opened.add(Path(file).resolve())
        return native_open(file, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", watch)
    monkeypatch.setattr(builtins, "open", watch_native)
    lanes, _ = load_lanes(root)
    assert len(opened) == 7  # plus upstream source-manifest metadata, never raw outcomes
    assert not any("/confirmation/" in str(p) or "/data/" in str(p) for p in opened)
    assert {key: len(value.rows) for key, value in lanes.items()} == {
        "NCEI-native-duration": 1070,
        "T-OBS": 236,
        "T-CAL": 156,
    }
    assert int(lanes["NCEI-native-duration"].included.sum()) == 1064


def test_direct_cli_help_without_pytest_pythonpath() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/arrival_model.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "data" in result.stdout


def synthetic_root(root: Path) -> Path:
    """Use no real outcomes to exercise allowlists, corruption and relocation."""
    repository = Path(__file__).resolve().parents[1]
    config = tomllib.loads((repository / CONTRACT).read_text(encoding="utf-8"))
    exploration = ["e1", "e2", "e3", *[f"extra{i}" for i in range(35)]]
    confirmation = [f"confirm{i}" for i in range(19)]
    (root / SPLIT).parent.mkdir(parents=True)
    (root / SPLIT).write_text(
        f"exploration = {json.dumps(exploration)}\nconfirmation = {json.dumps(confirmation)}\n",
        encoding="utf-8",
    )
    write_rows(
        root / METADATA,
        [
            {"event_id": event, "sequence_group": SEQUENCES.get(event, "q-" + event)}
            for event in exploration + confirmation
        ],
    )
    (root / SOURCE_MANIFEST).write_text(
        '{"schema_version": "synthetic_source_manifest", "files": []}', encoding="utf-8"
    )
    for target, path in TARGET_FILES.items():
        rows = records()
        for row in rows:
            row["target"] = target
        write_rows(root / path, rows)
    lines = [
        f"{key} = {json.dumps(value)}"
        for key, value in config.items()
        if key not in {"inputs", "lanes"}
    ]
    lines += [
        "[inputs]",
        *[
            f"{json.dumps(path)} = {json.dumps(sha256(root / path))}"
            for path in [*TARGET_FILES.values(), SPLIT, METADATA, SOURCE_MANIFEST]
        ],
    ]
    for target in TARGET_FILES:
        lines += [
            f"[lanes.{json.dumps(target)}]",
            "rows = 3",
            "primary_rows = 3",
            "events = 3",
            "sites = 2",
            "sequences = 2",
            "excluded_ids = []",
            *[
                f"{key} = {json.dumps(config['lanes'][target][key])}"
                for key in ["response", "transform", "prediction"]
            ],
        ]
    (root / CONTRACT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in [
        "analysis/arrival/model_data.py",
        "analysis/arrival/evidence.py",
        "scripts/arrival_model.py",
        "pyproject.toml",
        "uv.lock",
    ]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((repository / name).read_bytes())
    return root


def test_relocation_full_replay_and_forbidden_outcome_mutation(tmp_path: Path) -> None:
    first = synthetic_root(tmp_path / "first")
    second = synthetic_root(tmp_path / "relocated")
    forbidden = second / "data/protected-confirmation.csv"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("THIS MUST NEVER BE PARSED", encoding="utf-8")
    write_data_bundle(first, tmp_path / "a")
    write_data_bundle(second, tmp_path / "b")
    assert {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "b").iterdir()
    }
    with pytest.raises(ValueError, match="new"):
        write_data_bundle(first, tmp_path / "a")


@pytest.mark.parametrize("change", ["hash", "convention", "lanes", "excluded_ids", "semantics"])
def test_input_and_contract_corruption_rejected(tmp_path: Path, change: str) -> None:
    root = synthetic_root(tmp_path)
    contract_path = root / CONTRACT
    text = contract_path.read_text(encoding="utf-8")
    if change == "hash":
        (root / TARGET_FILES["T-OBS"]).write_text("corrupted", encoding="utf-8")
    elif change == "convention":
        contract_path.write_text(text.replace("near_field_km = 500", "near_field_km = 501"))
    elif change == "lanes":
        contract_path.write_text(text.replace('[lanes."T-CAL"]', '[lanes."extra"]'))
    elif change == "semantics":
        contract_path.write_text(text.replace("identity_minutes", "log_minutes"))
    else:
        contract_path.write_text(text.replace("excluded_ids = []", 'excluded_ids = ["r0"]'))
    with pytest.raises(ValueError):
        load_lanes(root)


def test_public_cli_synthetic_data_build(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path / "source-export")
    output = tmp_path / "result"
    result = subprocess.run(
        [sys.executable, str(root / "scripts/arrival_model.py"), "data", "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "metrics.json").read_text())["T-OBS"]["rows"] == 3
    pins = json.loads((output / "output-checksums.json").read_text())
    assert pins["run-metadata.json"] == sha256(output / "run-metadata.json")
