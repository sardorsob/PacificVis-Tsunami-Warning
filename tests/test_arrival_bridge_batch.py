"""Finite fold accounting, retained repairs and corruption-safe resume."""

# pyright: basic
import json
from dataclasses import replace
from pathlib import Path

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_bridge_batch as batch
from tests.test_arrival_models import tiny_lane


def fixture(root, monkeypatch, outcomes):
    for p in ["controller.py", "stub.py", "gate.json", "bridge.json"]:
        (root / p).write_text("fixture")
    for p in ["scripts/run_arrival_model_batch.py", "scripts/run_arrival_model_validation.py"]:
        target = root / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture framework")
    cases = [
        {
            "id": f"case-{i}",
            "ensemble_count": 2,
            "job": {
                "seed": 100 + i * 100,
                "draws": 2000,
                "tune": 1000,
                "gate": "gate.json",
                "bridge_gate": "bridge.json",
            },
        }
        for i in range(2)
    ]
    monkeypatch.setattr(batch, "make_bridge_cases", lambda *_: cases)
    monkeypatch.setattr(batch, "CONTROLLER", "controller.py")
    monkeypatch.setattr(batch, "FOLD_CONSUMED", ["stub.py"])
    monkeypatch.setattr(batch, "git_sha", lambda *_: "fixture-sha")
    seen = []

    def supervise(command, log, stop, timeout):
        job = json.loads(Path(command[command.index("--job") + 1]).read_text())
        seen.append(job)
        output = Path(command[command.index("--output") + 1])
        store = Path(command[command.index("--store") + 1])
        output.mkdir(parents=True)
        store.mkdir(parents=True)
        (store / "posterior.nc").write_text("mock")
        for i in range(2):
            write_json(output / "sampling-starts" / f"{i:02d}.json", {"seed": job["seed"] + i})
        expected = {p: sha256(root / p) for p in ["stub.py", "gate.json", "bridge.json"]}
        write_json(output / "inputs.json", {"files": expected})
        mode = outcomes[len(seen) - 1] if len(seen) <= len(outcomes) else "pass"
        result = {
            "job": job,
            "status": "computed_pending_review" if mode == "pass" else "precision_failure",
            "score_precision_passed": mode == "pass",
            "prediction_precision_passed": mode == "pass",
            "repairable": mode == "mild",
            "sampler_calls": 2,
        }
        write_json(output / "result.json", result)
        return {"reason": "worker_exit", "returncode": 0 if mode == "pass" else 2}

    monkeypatch.setattr(batch, "supervise", supervise)
    return seen


def test_one_same_seed_repair_is_retained_and_counted(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, ["mild", "pass", "pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    batch.run_bridge_batch(tmp_path, out, store, state)
    d = json.loads(state.read_text())
    assert d["status"] == "computations_complete" and d["next_case"] == 2
    assert d["calls_used"] == 3 and d["sampler_call_slots_used"] == 6
    assert [j["draws"] for j in seen] == [2000, 4000, 2000]
    assert seen[0]["seed"] == seen[1]["seed"]
    assert [a["outcome"] for a in d["attempts"]] == ["precision_failure", "accepted", "accepted"]


def test_unsafe_result_stops_without_resampling_or_auto_resume(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, ["unsafe"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    batch.run_bridge_batch(tmp_path, out, store, state)
    assert json.loads(state.read_text())["status"] == "needs_review" and len(seen) == 1
    with pytest.raises(ValueError):
        batch.run_bridge_batch(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_corrupted_retained_posterior_blocks_resume_before_next_fit(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, ["pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    batch.run_bridge_batch(tmp_path, out, store, state, max_cases=1)
    next(store.rglob("posterior.nc")).write_text("corrupt")
    with pytest.raises(ValueError, match="retained"):
        batch.run_bridge_batch(tmp_path, out, store, state, resume=True)
    assert len(seen) == 1


def test_storage_reservation_stops_before_a_fit(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, [])
    monkeypatch.setattr(batch, "MAX_POSTERIOR_BYTES", 1)
    batch.run_bridge_batch(tmp_path, tmp_path / "out", tmp_path / "store", tmp_path / "state.json")
    assert not seen
    assert json.loads((tmp_path / "state.json").read_text())["status"] == "budget_limit"


def test_resume_cannot_switch_to_an_empty_store_and_reset_byte_accounting(tmp_path, monkeypatch):
    seen = fixture(tmp_path, monkeypatch, ["pass"])
    out, store, state = tmp_path / "out", tmp_path / "store", tmp_path / "state.json"
    batch.run_bridge_batch(tmp_path, out, store, state, max_cases=1)
    with pytest.raises(ValueError, match="store"):
        batch.run_bridge_batch(tmp_path, out, tmp_path / "other-store", state, resume=True)
    assert len(seen) == 1


def test_case_construction_conserves_folds_and_disjoint_seed_channels(tmp_path, monkeypatch):
    lane = tiny_lane()
    lanes = {
        target: replace(lane, target=target)
        for target in ["NCEI-native-duration", "T-OBS", "T-CAL"]
    }
    monkeypatch.setattr(batch, "load_lanes", lambda *_: (lanes, {}))
    monkeypatch.setattr(batch, "verify_bridge_gate", lambda *_: None)
    monkeypatch.setattr(batch, "verify_prediction_gate", lambda *_: None)
    cases = batch.make_bridge_cases(tmp_path)
    assert len(cases) == 8
    assert sum(c["ensemble_count"] for c in cases) == 20
    seeds = [c["job"]["seed"] + k for c in cases for k in range(c["ensemble_count"])]
    assert len(seeds) == len(set(seeds)) == 20
    assert [c["job"]["kind"] for c in cases[:2]] == ["event", "distance-scale"]
