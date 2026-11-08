"""Finite controller tests use synthetic receipts and no sampler or real outcomes."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival import model_curvature_calibration as checks_module
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_curvature_validation import CONSUMED
from scripts import run_arrival_curvature_calibration as runner


def test_all150_cases_have_disjoint_effective_seed_roles():
    cases = runner.make_cases()
    assert len(cases) == 150
    seeds = [c["seed"] + j for c in cases for j in [0, 1, 2, 3, *range(10, 22), *range(30, 39)]]
    assert len(set(seeds)) == len(seeds)
    assert cases[0]["truth"]["gamma"] == 0 and cases[10]["truth"]["gamma"] == 0.5
    assert cases[20]["truth"]["gamma"] == -0.5
    assert all(c["first_event_id"] == runner.FIRST_EVENT for c in cases)


def test_budget_counts_partial_files_and_retained_caches(tmp_path, monkeypatch):
    output = tmp_path / "output"
    store = tmp_path / "store"
    output.mkdir()
    (store / "cache").mkdir(parents=True)
    (output / "evidence").write_bytes(b"123")
    (store / "partial-augmented.nc").write_bytes(b"12345")
    (store / "cache" / "compiled").write_bytes(b"1234")
    assert runner.byte_count(output, store) == 12
    monkeypatch.setattr(runner, "MAX_BYTES", 11)
    assert runner.quota_failure(tmp_path, output, store) == "aggregate_storage"
    monkeypatch.setattr(runner, "MAX_BYTES", 100)
    monkeypatch.setattr(runner, "MAX_CACHE", 3)
    assert runner.quota_failure(tmp_path, output, store) == "cache_storage"


def fixture(root, monkeypatch, *, fail=False):
    for name in {
        *CONSUMED,
        *runner.EXTRA,
        *runner.PARENT_GATES,
        runner.SELF,
        runner.CHECKPOINT_HELPER,
    }:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture-only source identity")
    pins = {
        name: sha256(root / name)
        for name in {
            *CONSUMED,
            *runner.EXTRA,
            *runner.PARENT_GATES,
            runner.SELF,
            runner.CHECKPOINT_HELPER,
        }
    }
    for name in runner.PARENT_ROOTS:
        (root / name).mkdir(parents=True, exist_ok=True)
    inventory = runner.parent_inventory(root)
    pins.update(inventory)
    write_json(
        root / runner.GATE,
        {
            "status": "accepted_finite_curvature_calibration",
            "independent_checker": True,
            "max_sampler_call_slots": 150,
            "max_bytes": runner.MAX_BYTES,
            "files": pins,
            "parent_inventory": inventory,
            "parent_minimum_bytes": {
                name: runner.byte_count(root / name) for name in runner.PARENT_ROOTS[:-1]
            },
        },
    )
    for name in runner.PARENT_ROOTS:
        (root / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner, "parent_datasets", lambda root: ["pilot-dataset"])
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda n: None)
    monkeypatch.setattr(runner, "os", SimpleNamespace(environ={}, getpid=lambda: 123))
    monkeypatch.setattr(runner, "git_sha", lambda root: "synthetic-fixture")
    calls = []

    def fake_checks(root, path, result):
        return {
            "case_id": result["job"]["id"],
            "rank_ready": True,
            "synthetic_observed_data_sha256": result["job"]["id"],
            "estimates": [{}] * 12,
            "functional": {"estimates": [{}] * 9},
        }

    monkeypatch.setattr(checks_module, "retained_checks", fake_checks)

    def simulated(command, log, stop, timeout):
        assert timeout == 600
        case = json.loads(Path(command[command.index("--job") + 1]).read_text())
        out = Path(command[command.index("--output") + 1])
        store = Path(command[command.index("--store") + 1])
        out.mkdir(parents=True)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_bytes(b"partial" if fail else b"posterior fixture")
        log.write_text("synthetic supervisor fixture\n")
        calls.append(case["id"])
        if not fail:
            write_json(out / "job.json", case)
            write_json(out / "inputs.json", {"fixture": True})
            (out / "sampled-hyperparameter-diagnostics.csv").write_text("fixture\n")
            (out / "sampling-diagnostics.csv").write_text("fixture\n")
            write_json(
                out / "result.json",
                {
                    "job": case,
                    "synthetic_only": True,
                    "posterior": str(store.relative_to(root)),
                    "code_and_config": {p: pins[p] for p in CONSUMED},
                    "posterior_sha256": sha256(store),
                    "diagnostics": {"screen_passed": True},
                },
            )
        return {"returncode": 1 if fail else 0, "reason": "worker_exit"}

    monkeypatch.setattr(runner, "supervise", simulated)
    return (
        calls,
        root / runner.OUTPUT,
        root / runner.STORE,
        root / runner.STATE,
    )


def test_one_counter_across50_recovery_and100_sbc(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=5)
    for _ in range(9):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 50
    assert json.loads(state.read_text())["status"] == "recovery_complete"
    with pytest.raises(ValueError, match="independently accepted"):
        runner.run(tmp_path, out, store, state, phase="sbc", resume=True)
    value = json.loads(state.read_text())
    pins = {str(out.relative_to(tmp_path) / "plan.json"): sha256(out / "plan.json")}
    for entry in value["accepted"]:
        pins.update(entry["files"])
        pins[entry["receipt"]] = entry["receipt_sha256"]
    write_json(
        tmp_path / runner.RECOVERY_GATE,
        {
            "status": "accepted_fifty_recovery_for_sbc",
            "independent_checker": True,
            "recovery_cases": 50,
            "files": pins,
        },
    )
    for _ in range(20):
        runner.run(tmp_path, out, store, state, phase="sbc", resume=True, max_cases=5)
    runner.run(tmp_path, out, store, state, phase="sbc", resume=True)
    value = json.loads(state.read_text())
    assert len(calls) == value["calls_used"] == value["next_case"] == 150
    assert value["status"] == "complete"


def test_first_failed_dispatch_stops_and_cannot_automatically_resume(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch, fail=True)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, out, store, state, max_cases=5)
    assert len(calls) == 1 and (store / "recovery-000.nc").read_bytes() == b"partial"
    with pytest.raises(ValueError, match="reconciliation"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 1


def test_changed_retained_prefix_rejects_before_another_dispatch(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=1)
    (store / "recovery-000.nc").write_bytes(b"changed")
    with pytest.raises(ValueError, match="prefix.*changed"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 1


def test_copied_output_plan_cannot_reset_evidence_accounting(tmp_path, monkeypatch):
    import shutil

    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=1)
    alternative = tmp_path / "artifacts/copied-pilot"
    shutil.copytree(out, alternative)
    with pytest.raises(ValueError, match="bounded invocation"):
        runner.run(tmp_path, alternative, store, state, resume=True, max_cases=1)
    assert len(calls) == 1


@pytest.mark.parametrize("omission", ["empty", "posterior", "result"])
def test_omitted_retained_proof_cannot_pass_resume(tmp_path, monkeypatch, omission):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=1)
    value = json.loads(state.read_text())
    files = value["accepted"][0]["files"]
    if omission == "empty":
        files.clear()
    else:
        key = (
            next(k for k in files if k.endswith(".nc") if omission == "posterior")
            if omission == "posterior"
            else next(k for k in files if k.endswith("result.json"))
        )
        del files[key]
    state.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="proof changed or omitted"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=1)
    assert len(calls) == 1


def test_checkpoint_helper_is_mandatory_gate_coverage(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    path = tmp_path / runner.GATE
    gate = json.loads(path.read_text())
    del gate["files"][runner.CHECKPOINT_HELPER]
    path.write_text(json.dumps(gate))
    with pytest.raises(ValueError, match="complete independently accepted"):
        runner.run(tmp_path, out, store, state, max_cases=1)
    assert not calls


def test_interrupt_is_recorded_without_automatic_retry(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)

    def interrupted(*args):
        calls.append("interrupted")
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "supervise", interrupted)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, out, store, state, max_cases=5)
    assert json.loads(state.read_text())["status"] == "interrupted"
    receipt = json.loads((out / "jobs/recovery-000.supervisor.json").read_text())
    assert receipt["reason"] == "interrupt"
    with pytest.raises(ValueError, match="reconciliation"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=1)
    assert len(calls) == 1


def test_missing_or_corrupt_curve_checks_block_resume(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state)
    (out / "jobs/recovery-000/calibration-checks.json").unlink()
    with pytest.raises(ValueError, match="mandatory calibration"):
        runner.run(tmp_path, out, store, state, resume=True)
    assert len(calls) == 1


def test_duplicate_generated_dataset_fails_without_retry(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state)
    old = checks_module.retained_checks

    def duplicate(root, path, result):
        value = old(root, path, result)
        value["synthetic_observed_data_sha256"] = "recovery-000"
        return value

    monkeypatch.setattr(checks_module, "retained_checks", duplicate)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    value = json.loads(state.read_text())
    assert len(calls) == value["calls_used"] == 2 and value["next_case"] == 1
    assert value["status"] == "rank_or_distinct_dataset_failure"


def test_parent_storage_is_in_shared_budget(tmp_path):
    out, store = tmp_path / runner.OUTPUT, tmp_path / runner.STORE
    parent = tmp_path / runner.PARENT_ROOTS[0]
    parent.mkdir(parents=True)
    (parent / "retained.nc").write_bytes(b"12345")
    assert runner.byte_count(*runner.working_roots(tmp_path, out, store)) == 5


def test_no_unbounded_batch_invocation(tmp_path):
    with pytest.raises(ValueError, match="bounded invocation"):
        runner.run(
            tmp_path,
            tmp_path / runner.OUTPUT,
            tmp_path / runner.STORE,
            tmp_path / runner.STATE,
            max_cases=150,
        )


def test_removed_parent_evidence_blocks_dispatch(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state)
    (tmp_path / runner.PARENT_GATES[2]).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.run(tmp_path, out, store, state, resume=True)
    assert len(calls) == 1


def test_parent_cache_is_counted_without_file_pins(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    cache = tmp_path / runner.PARENT_ROOTS[0] / "cache"
    cache.mkdir()
    retained = cache / "retained"
    retained.write_bytes(b"12345")
    gatepath = tmp_path / runner.GATE
    gate = json.loads(gatepath.read_text())
    gate["parent_minimum_bytes"][runner.PARENT_ROOTS[0]] += 5
    write_json(gatepath, gate)
    assert not any("/cache/" in p for p in gate["files"])
    runner.run(tmp_path, out, store, state)
    retained.unlink()
    with pytest.raises(ValueError, match="parent evidence inventory/accounting"):
        runner.run(tmp_path, out, store, state, resume=True)
    assert len(calls) == 1
