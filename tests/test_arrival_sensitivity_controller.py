"""Synthetic S5 accounting, admission boundaries and bounded real process groups."""

# pyright: basic
import json
import time
from pathlib import Path

import pytest

from analysis.arrival.evidence import sha256, write_json
from scripts import run_arrival_sensitivities as runner


def fixture(root, monkeypatch, *, failure=None):
    jobs = [
        {
            "id": f"ms5-case-{i:02d}",
            "order": i,
            "target": "T-OBS",
            "kind": "event",
            "prior_variant": "joint_wider",
            "pilot": i < 2,
            "draws": 2000,
            "tune": 1000,
            "cores": 2,
            "seed": 2886110800 + 1000 * i,
        }
        for i in range(55)
    ]
    jobs[0].update(
        id="ms5-case-power-0.5-prior",
        target="NCEI-native-duration",
        kind="mean-curvature",
        prior_variant="t4_matched",
    )
    jobs[1].update(
        id="ms5-case-power-1.5-prior", target="T-CAL", kind="event", prior_variant="t4_matched"
    )
    source = root / "frozen.py"
    source.write_text("frozen")
    floors = {}
    for parent in runner.parent_roots(root):
        parent.mkdir(parents=True, exist_ok=True)
        (parent / "floor.bin").write_bytes(b"original")
        floors[str(parent.relative_to(root))] = runner.byte_count(parent)
    (root / runner.OLD_OUTPUT).mkdir(parents=True, exist_ok=True)
    for name in runner.RUNTIME:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen runtime")
    gate = {
        "jobs": jobs,
        "resources": runner.resources(),
        "path_bindings": runner.path_bindings(root),
        "parent_minimum_bytes": floors,
    }
    write_json(root / runner.GATE, gate)
    pins = {name: sha256(root / name) for name in ["frozen.py", *runner.RUNTIME, runner.GATE]}
    monkeypatch.setattr(
        runner, "verify_gate", lambda root: {"gate": gate, "files": pins, "contract": {}}
    )
    monkeypatch.setattr(runner, "limit_worker_file_size", lambda *args: None)
    calls = []

    def proof(_root, job, source_pins, accepted=None):
        folder, raw, spec, log, supervisor = runner.case_paths(root, job)
        manifest = folder / "attempt-evidence.json"
        assert (
            json.loads((folder / "result.json").read_text())["status"]
            == "computed_pending_scientific_review"
        )
        process = json.loads(supervisor.read_text())
        assert process["returncode"] == 0 and process["reason"] == "worker_exit"
        assert process["start_markers"] == process["charged_slots"] == 1
        assert not process["monitor_failures"]
        paths = {path for path in folder.rglob("*") if path.is_file() and path != manifest}
        paths.update([raw, spec, log, supervisor])
        files = {str(path.relative_to(root)): sha256(path) for path in paths}
        if accepted is not None:
            assert accepted["files"] == files and accepted["receipt_sha256"] == sha256(manifest)
            assert json.loads(manifest.read_text()) == {"case_id": job["id"], "files": files}
        return files, manifest

    monkeypatch.setattr(runner, "case_artifacts", proof)

    def supervise(command, log, stop, timeout):
        calls.append(command)
        spec = Path(command[command.index("--job") + 1])
        job = json.loads(spec.read_text())
        folder = Path(command[command.index("--output") + 1])
        raw = Path(command[command.index("--store") + 1])
        state = json.loads((root / runner.STATE).read_text())
        assert state["current"] == job["id"] and state["calls_charged"] == len(calls)
        folder.mkdir(parents=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"posterior")
        write_json(folder / "sampling-start.json", job)
        write_json(folder / "job.json", job)
        write_json(
            folder / "result.json",
            {
                "job": job,
                "status": "failed" if failure == "result" else "computed_pending_scientific_review",
            },
        )
        log.write_text("worker")
        if failure == "source":
            source.write_text("changed")
        if failure == "floor":
            (runner.parent_roots(root)[0] / "floor.bin").unlink()
        if failure == "interrupt":
            raise KeyboardInterrupt
        return {"returncode": 0, "reason": "worker_exit", "elapsed_seconds": 0.01}

    monkeypatch.setattr(runner, "supervise", supervise)
    return jobs, gate, pins, calls


def accept_pilots(root):
    state = json.loads((root / runner.STATE).read_text())
    files = {runner.OUTPUT + "/plan.json": state["plan_sha256"]}
    for accepted in state["accepted"][:2]:
        files.update(accepted["files"])
        files[accepted["receipt"]] = accepted["receipt_sha256"]
    write_json(
        root / runner.PILOT_REVIEW,
        {
            "status": "accepted_sensitivity_two_case_runtime_and_prior_pilots",
            "independent_checker": True,
            "files": files,
        },
    )


def test_initial_launch_requires_explicit_two_or_fewer_and_review_blocks_third(
    tmp_path, monkeypatch
):
    jobs, _, _, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="pilots"):
        runner.run(tmp_path)
    runner.run(tmp_path, max_cases=2)
    assert len(calls) == 2
    for job in jobs[:2]:
        folder, raw, spec, log, supervisor = runner.case_paths(tmp_path, job)
        assert log.name == job["id"] + ".log"
        assert supervisor.name == job["id"] + ".supervisor.json"
        assert spec.name == job["id"] + "-spec.json" and raw.name == job["id"] + ".nc"
    with pytest.raises(ValueError, match="pilot"):
        runner.run(tmp_path, resume=True)
    assert len(calls) == 2
    accept_pilots(tmp_path)
    runner.run(tmp_path, resume=True, max_cases=4)
    assert len(calls) == 6


def test_all55_calls_conserve_counters_and_terminal_readback_does_not_rewrite(
    tmp_path, monkeypatch
):
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_cases=2)
    accept_pilots(tmp_path)
    while len(calls) < 55:
        runner.run(tmp_path, resume=True, max_cases=4)
    state_path = tmp_path / runner.STATE
    state = json.loads(state_path.read_text())
    assert state["calls_charged"] == state["calls_started"] == state["next_case"] == 55
    assert len(state["attempts"]) == len(state["accepted"]) == 55
    assert state["status"] == "sensitivity_computations_complete"
    assert state["final_summary_sha256"] == sha256(tmp_path / runner.OUTPUT / "run-summary.json")
    before = state_path.read_bytes(), (tmp_path / runner.OUTPUT / "run-summary.json").read_bytes()
    runner.run(tmp_path, resume=True)
    assert before == (
        state_path.read_bytes(),
        (tmp_path / runner.OUTPUT / "run-summary.json").read_bytes(),
    )
    assert len(calls) == 55


@pytest.mark.parametrize("failure", ["result", "source", "floor", "interrupt"])
def test_failed_call_remains_charged_and_cannot_auto_resume(tmp_path, monkeypatch, failure):
    _, _, _, calls = fixture(tmp_path, monkeypatch, failure=failure)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert state["calls_charged"] == state["calls_started"] == 1
    assert state["next_case"] == 0 and state["current"] is None
    assert state["status"] == "sensitivity_needs_review" and len(state["attempts"]) == 1
    with pytest.raises((ValueError, SystemExit)):
        runner.run(tmp_path, resume=True, max_cases=1)
    assert len(calls) == 1


def test_stop_before_allocation_and_old_lease_prevent_new_dispatch(tmp_path, monkeypatch):
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    stop = tmp_path / runner.OLD_OUTPUT / "STOP"
    stop.write_text("owner stop")
    with pytest.raises(ValueError, match="STOP"):
        runner.run(tmp_path, max_cases=1)
    assert not (tmp_path / runner.STATE).exists() and not calls
    stop.unlink()
    lease = tmp_path / runner.OLD_OUTPUT / ".controller.lock"
    lease.write_text("another controller")
    with pytest.raises((ValueError, FileExistsError)):
        runner.run(tmp_path, max_cases=1)
    assert lease.read_text() == "another controller" and not calls


@pytest.mark.parametrize("change", ["refund", "current", "proof", "unknown_file", "unknown_dir"])
def test_changed_interrupted_or_unknown_resume_state_is_refused(tmp_path, monkeypatch, change):
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_cases=1)
    path = tmp_path / runner.STATE
    state = json.loads(path.read_text())
    if change == "refund":
        state["calls_charged"] = 0
        write_json(path, state)
    elif change == "current":
        state.update(current="interrupted", calls_charged=2, status="sensitivity_running")
        write_json(path, state)
    elif change == "proof":
        (tmp_path / state["accepted"][0]["receipt"]).write_text("changed")
    elif change == "unknown_file":
        (tmp_path / runner.STORE / "unknown.nc.partial").write_bytes(b"partial")
    else:
        (tmp_path / runner.STORE / "unknown").mkdir()
    before = path.read_bytes()
    with pytest.raises((ValueError, AssertionError)):
        runner.run(tmp_path, resume=True, max_cases=1)
    assert path.read_bytes() == before and len(calls) == 1


def test_late_case_cap_after_receipt_retains_both_inventories_without_accepting(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "MAX_JOB", 128 * 1024)
    jobs, _, _, calls = fixture(tmp_path, monkeypatch)
    original = runner.new_json

    def injected(path, value):
        original(path, value)
        if path.name == "attempt-evidence.json":
            (path.parent / "late.bin").write_bytes(b"x" * runner.MAX_JOB)

    monkeypatch.setattr(runner, "new_json", injected)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert state["calls_charged"] == 1 and state["next_case"] == 0 and len(calls) == 1
    folder = runner.case_paths(tmp_path, jobs[0])[0]
    assert (folder / "attempt-evidence.json").exists()
    failure = json.loads((folder / "failure-evidence.json").read_text())
    assert str((folder / "late.bin").relative_to(tmp_path)) in failure["files"]
    assert state["attempts"][0]["receipt"].endswith("failure-evidence.json")


def test_late_summary_cap_cannot_mark_complete_or_success(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_LOCAL", 700 * runner.MIB)
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    original = runner.write_json

    def injected(path, value):
        original(path, value)
        if path.name == "run-summary.json":
            # Small synthetic cap rather than a large allocation.
            monkeypatch.setattr(runner, "MAX_LOCAL", 1)

    monkeypatch.setattr(runner, "write_json", injected)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert state["status"] == "sensitivity_needs_review" and "final_summary_sha256" not in state
    assert state["calls_charged"] == 1 and len(calls) == 1


def test_pilot_review_identity_is_frozen_on_later_resume(tmp_path, monkeypatch):
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_cases=2)
    accept_pilots(tmp_path)
    runner.run(tmp_path, resume=True, max_cases=1)
    path = tmp_path / runner.PILOT_REVIEW
    review = json.loads(path.read_text())
    review["changed"] = True
    write_json(path, review)
    with pytest.raises(ValueError, match="review identity"):
        runner.run(tmp_path, resume=True, max_cases=1)
    assert len(calls) == 3


@pytest.mark.parametrize("mode", ["timeout", "old_stop"])
def test_real_stub_process_group_and_descendant_are_terminated(tmp_path, monkeypatch, mode):
    from scripts.run_arrival_model_validation import supervise as real_supervise

    monkeypatch.setattr(runner, "TIMEOUT", 1 if mode == "timeout" else 5)
    jobs, _, _, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "supervise", real_supervise)
    script = tmp_path / "scripts/fit_arrival_sensitivity.py"
    child_code = (
        "import signal,sys,time\nfrom pathlib import Path\n"
        "def terminated(signum,frame):\n"
        " Path(sys.argv[1]).write_text('terminated');sys.exit(0)\n"
        "signal.signal(signal.SIGTERM,terminated)\n"
        "Path(sys.argv[2]).write_text('ready');time.sleep(30)\n"
    )
    old_stop = str(tmp_path / runner.OLD_OUTPUT / "STOP")
    stop_code = f"Path({old_stop!r}).write_text('owner stop')\n" if mode == "old_stop" else ""
    script.write_text(
        "import argparse,json,subprocess,sys,time\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser()\n"
        "for k in ['job','output','store','max-output-bytes']:p.add_argument('--'+k)\n"
        "a=p.parse_args();folder=Path(a.output);folder.mkdir(parents=True)\n"
        "Path(a.store).parent.mkdir(parents=True,exist_ok=True)\n"
        "Path(a.store).write_bytes(b'retained partial')\n"
        "(folder/'sampling-start.json').write_text(Path(a.job).read_text())\n"
        f"child_code={child_code!r}\n"
        "subprocess.Popen([sys.executable,'-c',child_code,\n"
        " str(folder/'child-terminated'),str(folder/'child-ready')])\n"
        "while not (folder/'child-ready').exists():time.sleep(.01)\n"
        + stop_code
        + "time.sleep(30)\n"
    )
    # The real stub is the frozen worker source in this synthetic prospective gate.
    admission = runner.verify_gate(tmp_path)
    admission["files"][str(script.relative_to(tmp_path))] = sha256(script)
    started = time.monotonic()
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    assert time.monotonic() - started < 6
    folder, raw, _, _, process = runner.case_paths(tmp_path, jobs[0])
    assert (folder / "child-terminated").read_text() == "terminated"
    assert raw.read_bytes() == b"retained partial"
    receipt = json.loads(process.read_text())
    assert receipt["reason"] == ("timeout" if mode == "timeout" else "stop_signal")
    assert receipt["charged_slots"] == receipt["start_markers"] == 1
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert state["calls_charged"] == state["calls_started"] == 1
    assert state["status"] == "sensitivity_needs_review" and not state["accepted"]
    assert not (tmp_path / runner.OUTPUT / ".controller.lock").exists()
    assert not (tmp_path / runner.OLD_OUTPUT / ".controller.lock").exists()


def test_next_call_reserve_failure_does_not_charge_or_dispatch(tmp_path, monkeypatch):
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    original = runner.quota_failure

    def exhausted(root, parents, gate, current=None, *, reserve=False):
        return "next_call_reserve" if reserve else original(root, parents, gate, current)

    monkeypatch.setattr(runner, "quota_failure", exhausted)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert not calls and state["calls_charged"] == state["calls_started"] == 0


def test_cache_cap_counts_bytes_outside_case_raw_file(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "MAX_CACHE", 8192)
    _, _, _, calls = fixture(tmp_path, monkeypatch)
    original = runner.supervise

    def overflowing(*args):
        receipt = original(*args)
        cache = tmp_path / runner.STORE / "cache"
        cache.mkdir()
        (cache / "compiler.partial").write_bytes(b"x" * (runner.MAX_CACHE + 1))
        return receipt

    monkeypatch.setattr(runner, "supervise", overflowing)
    with pytest.raises(SystemExit):
        runner.run(tmp_path, max_cases=1)
    state = json.loads((tmp_path / runner.STATE).read_text())
    assert len(calls) == state["calls_charged"] == 1 and state["next_case"] == 0
    assert (tmp_path / runner.STORE / "cache/compiler.partial").exists()


def test_private_state_race_is_refused_after_both_leases_without_overwriting(tmp_path, monkeypatch):
    from contextlib import contextmanager

    _, _, _, calls = fixture(tmp_path, monkeypatch)
    runner.run(tmp_path, max_cases=1)
    original = runner._leases

    @contextmanager
    def raced(root):
        with original(root):
            state = json.loads((root / runner.STATE).read_text())
            state["other_owner_update"] = True
            write_json(root / runner.STATE, state)
            yield

    monkeypatch.setattr(runner, "_leases", raced)
    with pytest.raises(ValueError, match="changed before exclusive"):
        runner.run(tmp_path, resume=True, max_cases=1)
    assert json.loads((tmp_path / runner.STATE).read_text())["other_owner_update"] is True
    assert len(calls) == 1
