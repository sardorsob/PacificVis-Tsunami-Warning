"""Prospective single-call resource guards use dummy workers, never real outcomes."""

# pyright: basic
import json
from types import SimpleNamespace

import pytest

from analysis.arrival import model_curvature_fit as fitting
from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_curvature_fit as runner


def fixture(root, monkeypatch, *, fail=False, interrupt=False, mutate_job=False):
    source = root / "source.txt"
    source.write_text("retained-source")
    pins = {"source.txt": sha256(source)}
    parents = runner.working_roots(
        root, root / runner.CALIBRATION_OUTPUT, root / runner.CALIBRATION_STORE
    )
    for parent in parents:
        parent.mkdir(parents=True, exist_ok=True)
        (parent / "retained").write_bytes(b"123")
    raw = root / runner.STORE
    cache_env = {
        "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={raw / 'cache/pytensor'}",
        "NUMBA_CACHE_DIR": str(raw / "cache/numba"),
        "MPLCONFIGDIR": str(raw / "cache/matplotlib"),
    }
    gate = {
        "controller": runner.SELF,
        "cache_environment": cache_env,
        "global_max_bytes": runner.MAX_GLOBAL,
        "local_max_bytes": runner.MAX_LOCAL,
        "cache_max_bytes": runner.MAX_CACHE,
        "small_output_max_bytes": runner.MAX_SMALL,
        "next_job_reserve_bytes": runner.RESERVE,
        "timeout_seconds": 600,
        "concurrency": 1,
        "automatic_retries": 0,
        "parent_minimum_bytes": {str(p.relative_to(root)): runner.byte_count(p) for p in parents},
    }
    job = {"fixture": "one-call"}
    write_json(root / runner.DESIGN / "job.json", job)
    write_json(root / fitting.FIT_GATE, gate)
    monkeypatch.setattr(fitting, "verify_fit_gate", lambda *a: pins)
    monkeypatch.setattr(runner, "os", SimpleNamespace(environ={}))
    calls = []

    def worker(command, log, stop, timeout):
        assert timeout == 600
        assert command[-2:] == ["--max-output-bytes", str(64 * runner.MIB)]
        calls.append(command)
        if interrupt:
            raise KeyboardInterrupt
        output = root / runner.OUTPUT
        output.mkdir()
        posterior = raw / "primary.nc"
        posterior.write_bytes(b"partial" if fail else b"closed posterior")
        log.write_text("dummy worker\n")
        if mutate_job:
            write_json(root / runner.DESIGN / "job.json", {"changed": True})
        if not fail:
            write_json(
                output / "result.json",
                {
                    "job": job,
                    "code_and_config": pins,
                    "posterior_sha256": sha256(posterior),
                    "diagnostics": {"screen_passed": True},
                    "status": "computed_pending_scientific_review",
                },
            )
        return {"returncode": 1 if fail else 0, "reason": "worker_exit"}

    monkeypatch.setattr(runner, "supervise", worker)
    return calls, root / runner.CONTROL


def test_one_successful_call_is_conserved_and_not_restarted(tmp_path, monkeypatch):
    calls, control = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path)
    assert len(calls) == 1
    assert json.loads((control / "allocation.json").read_text())["sampler_call_slots_used"] == 1
    assert (
        json.loads((control / "result.json").read_text())["status"]
        == "computed_pending_independent_review"
    )
    with pytest.raises(ValueError, match="no automatic retry"):
        runner.run(tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("reason", ["runtime", "interrupt", "changed-job"])
def test_failure_or_interrupt_preserves_receipt_and_sole_attempt(tmp_path, monkeypatch, reason):
    calls, control = fixture(
        tmp_path,
        monkeypatch,
        fail=reason == "runtime",
        interrupt=reason == "interrupt",
        mutate_job=reason == "changed-job",
    )
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    assert len(calls) == 1
    result = json.loads((control / "result.json").read_text())
    assert (
        result["status"]
        == {
            "runtime": "runtime_failure",
            "interrupt": "interrupted",
            "changed-job": "identity_failure",
        }[reason]
    )
    assert result["sampler_call_slots_used"] == 1
    assert (control / "supervisor.json").is_file()
    with pytest.raises(ValueError, match="no automatic retry"):
        runner.run(tmp_path)


def test_missing_parent_cache_bytes_fail_before_dispatch(tmp_path, monkeypatch):
    calls, control = fixture(tmp_path, monkeypatch)
    gate_path = tmp_path / fitting.FIT_GATE
    gate = json.loads(gate_path.read_text())
    parent = next(iter(gate["parent_minimum_bytes"]))
    gate["parent_minimum_bytes"][parent] += 1
    write_json(gate_path, gate)
    with pytest.raises(ValueError, match="preserved parent"):
        runner.run(tmp_path)
    assert not calls and not control.exists()


def test_trip_threshold_retains_overshoot_and_fails_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_LOCAL", 5)
    calls, control = fixture(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        runner.run(tmp_path)
    assert len(calls) == 1
    assert json.loads((control / "result.json").read_text())["status"] == "storage_failure"
    assert (tmp_path / runner.STORE / "primary.nc").is_file()
