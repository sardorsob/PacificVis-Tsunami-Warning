"""Finite controller tests use synthetic receipts and no sampler or real outcomes."""

# pyright: basic
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_curvature_validation import CONSUMED
from scripts import run_arrival_curvature_pilot as runner


def test_five_cases_have_disjoint_effective_seed_roles():
    cases = runner.make_cases()
    assert len(cases) == 5
    seeds = [c["seed"] + j for c in cases for j in [0, 1, 2, 3, *range(10, 22)]]
    assert len(set(seeds)) == len(seeds)
    assert cases[0]["truth"]["gamma"] == 0 and cases[1]["truth"]["gamma"] == 0.5
    assert cases[2]["truth"]["gamma"] == -0.5
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
    assert runner.quota_failure(output, store) == "aggregate_storage"
    monkeypatch.setattr(runner, "MAX_BYTES", 100)
    monkeypatch.setattr(runner, "MAX_CACHE", 3)
    assert runner.quota_failure(output, store) == "cache_storage"


def fixture(root, monkeypatch, *, fail=False):
    for name in {*CONSUMED, runner.SELF, runner.CHECKPOINT_HELPER}:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture-only source identity")
    pins = {
        name: sha256(root / name) for name in {*CONSUMED, runner.SELF, runner.CHECKPOINT_HELPER}
    }
    write_json(
        root / runner.GATE,
        {
            "status": "accepted_five_case_synthetic_pilot",
            "independent_checker": True,
            "max_sampler_call_slots": 5,
            "max_bytes": runner.MAX_BYTES,
            "files": pins,
        },
    )
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda n: None)
    monkeypatch.setattr(runner, "os", SimpleNamespace(environ={}, getpid=lambda: 123))
    monkeypatch.setattr(runner, "git_sha", lambda root: "synthetic-fixture")
    calls = []

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
        root / "artifacts/pilot",
        root / "data/pilot",
        root / "context/runs/arrival-model-fitting-v1/pilot-state.json",
    )


def test_success_prefix_resume_cannot_exceed_five_call_slots(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=2)
    assert len(calls) == 2
    runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 5
    runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 5
    snapshot = json.loads(state.read_text())
    assert snapshot["calls_used"] == snapshot["next_case"] == 5 and snapshot["status"] == "complete"


def test_first_failed_dispatch_stops_and_cannot_automatically_resume(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch, fail=True)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, out, store, state, max_cases=5)
    assert len(calls) == 1 and (store / "null-weak.nc").read_bytes() == b"partial"
    with pytest.raises(ValueError, match="reconciliation"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 1


def test_changed_retained_prefix_rejects_before_another_dispatch(tmp_path, monkeypatch):
    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=1)
    (store / "null-weak.nc").write_bytes(b"changed")
    with pytest.raises(ValueError, match="prefix.*changed"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=5)
    assert len(calls) == 1


def test_copied_output_plan_cannot_reset_evidence_accounting(tmp_path, monkeypatch):
    import shutil

    calls, out, store, state = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, out, store, state, max_cases=1)
    alternative = tmp_path / "artifacts/copied-pilot"
    shutil.copytree(out, alternative)
    with pytest.raises(ValueError, match="paths differ"):
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
    receipt = json.loads((out / "jobs/null-weak.supervisor.json").read_text())
    assert receipt["reason"] == "interrupt"
    with pytest.raises(ValueError, match="reconciliation"):
        runner.run(tmp_path, out, store, state, resume=True, max_cases=1)
    assert len(calls) == 1
