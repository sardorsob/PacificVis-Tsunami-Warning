"""Synthetic simulation and diagnostic failure fixtures; never a real-data fit."""

# pyright: basic
import importlib.util
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr

from analysis.arrival.model_validation import (
    conditional_event_effects,
    fit_synthetic_job,
    rank_summary,
    sampling_diagnostics,
    simulate_response,
)
from tests.test_arrival_models import tiny_lane


def test_worker_storage_allocation_is_kernel_enforced(tmp_path: Path) -> None:
    output = tmp_path / "capped.bin"
    code = (
        "from scripts.run_arrival_model_validation import limit_worker_file_size;"
        "limit_worker_file_size(1024);"
        f"f=open({str(output)!r},'wb');f.write(b'x'*2048);f.flush();f.close()"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode != 0
    assert output.stat().st_size <= 1024


def test_simulator_uses_design_and_truth_not_actual_outcomes() -> None:
    truth = {"alpha": 0.2, "beta": -0.1, "tau_event": 0.3, "sigma": 0.2}
    first, effects = simulate_response(tiny_lane("100"), truth, seed=17)
    changed, _ = simulate_response(tiny_lane("9000"), truth, seed=17)
    np.testing.assert_array_equal(first, changed)
    assert len(effects) == 3
    exact, _ = simulate_response(tiny_lane(), {**truth, "tau_event": 0, "sigma": 0}, seed=17)
    np.testing.assert_allclose(exact, 0.2 - 0.1 * tiny_lane().x)


def fixture(shift: bool = False, divergence: bool = False) -> xr.DataTree:
    rng = np.random.default_rng(17)
    alpha = rng.normal(size=(4, 2000))
    if shift:
        alpha[0] += 3
    diverging = np.zeros((4, 2000), dtype=bool)
    diverging[0, 0] = divergence
    return xr.DataTree.from_dict(
        {
            "posterior": xr.Dataset({"alpha": (("chain", "draw"), alpha)}),
            "sample_stats": xr.Dataset(
                {
                    "diverging": (("chain", "draw"), diverging),
                    "maxdepth_reached": (("chain", "draw"), np.zeros_like(diverging)),
                    "energy": (("chain", "draw"), rng.normal(size=alpha.shape)),
                }
            ),
        }
    )


def test_diagnostics_detect_shift_and_divergence() -> None:
    good, _ = sampling_diagnostics(fixture())
    shifted, _ = sampling_diagnostics(fixture(shift=True))
    divergent, _ = sampling_diagnostics(fixture(divergence=True))
    assert good["screen_passed"]
    assert not shifted["screen_passed"] and shifted["max_rhat"] > 1.01
    assert not divergent["screen_passed"] and divergent["divergences"] == 1


def test_supervisor_timeout_and_preexisting_stop(tmp_path: Path) -> None:
    scope = runpy.run_path("scripts/run_arrival_model_validation.py")
    command = [sys.executable, "-c", "import time; time.sleep(20)"]
    timed = scope["supervise"](command, tmp_path / "timeout.log", tmp_path / "STOP", 1)
    assert timed["reason"] == "timeout" and timed["returncode"] != 0
    (tmp_path / "STOP").touch()
    stopped = scope["supervise"](command, tmp_path / "never.log", tmp_path / "STOP", 1)
    assert stopped["reason"] == "stop_signal" and not (tmp_path / "never.log").exists()


def test_conditional_event_draws_match_normal_oracle_and_ignore_heldout_values() -> None:
    lane = replace(tiny_lane(), response=np.ones(3))
    hyper = {
        "alpha": np.zeros((4, 10000)),
        "beta": np.zeros((4, 10000)),
        "tau_event": np.full((4, 10000), 0.3),
        "sigma": np.full((4, 10000), 0.4),
    }
    effects, labels = conditional_event_effects(lane, hyper, seed=18, indices=np.arange(3))
    assert labels == ["e1", "e2", "e3"]
    np.testing.assert_allclose(effects.mean(), 0.36, atol=0.003)
    np.testing.assert_allclose(effects.var(), 0.0576, atol=0.001)
    changed = replace(lane, response=np.array([90000.0, 1.0, 90000.0]))
    first, _ = conditional_event_effects(lane, hyper, seed=18, indices=np.array([1]))
    second, _ = conditional_event_effects(changed, hyper, seed=18, indices=np.array([1]))
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize(
    "field,value", [("draws", 999999), ("tune", True), ("seed", -1), ("cores", 8)]
)
def test_fit_allocation_rejected_before_sampling(tmp_path: Path, field: str, value: object) -> None:
    job = {"phase": "pilot", "draws": 1000, "tune": 1000, "seed": 1, field: value}
    with pytest.raises(ValueError):
        fit_synthetic_job(Path.cwd(), job, tmp_path / "out", tmp_path / "draws.nc")
    assert not (tmp_path / "out").exists()


def test_rank_diagnostics_distinguish_ess_from_subsample_and_reject_stuck_chain() -> None:
    values = np.random.default_rng(11).normal(size=(4, 2000))
    good = rank_summary(values, 0, 88)
    assert good["rank_ready"] and good["rank_draws"] == 100
    assert good["quantity_ess_bulk"] > 1000
    values[0] += 3
    bad = rank_summary(values, 0, 88)
    assert not bad["rank_ready"]


def test_timeout_cleans_sigterm_resistant_descendant(tmp_path: Path) -> None:
    scope = runpy.run_path("scripts/run_arrival_model_validation.py")
    pid_file, heartbeat = tmp_path / "child.json", tmp_path / "heartbeat"
    child = (
        "import signal,os,time,json; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(pid_file)!r}).write_text(json.dumps({{'pgid':os.getpgrp()}})); "
        f'exec("while True:\\n Path({str(heartbeat)!r}).write_text(str(time.monotonic()))'
        '\\n time.sleep(.03)")'
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(20)"
    )
    try:
        scope["supervise"](
            [sys.executable, "-c", parent], tmp_path / "group.log", tmp_path / "STOP", 1
        )
        assert heartbeat.exists()
        value = heartbeat.read_text()
        time.sleep(0.15)
        assert heartbeat.read_text() == value, "descendant still running after timeout"
    finally:
        if pid_file.exists():
            try:
                os.killpg(json.loads(pid_file.read_text())["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_supervisor_interrupt_cleans_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    scope = runpy.run_path("scripts/run_arrival_model_validation.py")
    original_popen, original_sleep = subprocess.Popen, time.sleep
    processes: list[Any] = []
    interrupted = False

    def track(command: list[str], **kwargs: Any) -> Any:
        process = original_popen(command, **kwargs)
        processes.append(process)
        return process

    def interrupt_once(seconds: float) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        original_sleep(seconds)

    monkeypatch.setattr(subprocess, "Popen", track)
    monkeypatch.setattr(time, "sleep", interrupt_once)
    try:
        with pytest.raises(KeyboardInterrupt):
            scope["supervise"](
                [sys.executable, "-c", "import time;time.sleep(20)"],
                tmp_path / "interrupt.log",
                tmp_path / "STOP",
                30,
            )
        assert processes and all(p.poll() is not None for p in processes)
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def test_cli_persists_interruption_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "validation_cli", "scripts/run_arrival_model_validation.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = tmp_path / "job.json"
    job.write_text('{"phase":"pilot"}')
    output = tmp_path / "attempt"

    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "supervise", interrupt)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validation",
            "--job",
            str(job),
            "--output",
            str(output),
            "--store",
            str(tmp_path / "draws.nc"),
        ],
    )
    with pytest.raises((SystemExit, KeyboardInterrupt)) as error:
        module.main()
    assert isinstance(error.value, SystemExit) and error.value.code == 130
    assert json.loads(output.with_suffix(".supervisor.json").read_text())["reason"] == "interrupt"
