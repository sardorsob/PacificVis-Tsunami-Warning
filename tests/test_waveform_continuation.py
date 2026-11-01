"""Continuation never resets frozen identity, elapsed runtime or provider stops."""

from __future__ import annotations

import copy
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import continue_waveform_acquisition as continuation
from tests.test_audit_waveforms import fixture


def source(index: int, **changes: Any) -> dict[str, Any]:
    return dict(
        source_id=f"ia-{index}", expected_no_data=False, structurally_usable=True,
        source_bytes=10, reason="not applicable", provider="ia", acquisition_status="downloaded",
    ) | changes


def test_yield_counts_expected_no_data_separately_but_not_unsupported_sources() -> None:
    preflight = dict(batches=[dict(contracts=100)], estimated_transfer_bytes=1000)
    sources = [source(i, structurally_usable=i < 9, expected_no_data=i >= 18) for i in range(20)]
    result = continuation.decision(preflight, [dict(response_bytes=100)], sources)
    assert result["gate_passed"]
    assert result["usable_fraction_excluding_expected_no_data"] == 0.5
    assert result["usable_fraction_all_attempts"] == 0.45
    assert result["completed_fraction"] == 0.2
    sources[0]["structurally_usable"] = False
    assert not continuation.decision(preflight, [], sources)["gate_passed"]


@pytest.mark.parametrize("reason", ["provider_error_limit: web.archive.org", "max_total_bytes"])
def test_provider_and_byte_stops_cannot_be_hidden_by_good_yield(reason: str) -> None:
    preflight = dict(batches=[dict(contracts=100)], estimated_transfer_bytes=1000)
    sources = [source(i) for i in range(20)]
    sources[-1]["reason"] = reason
    assert not continuation.decision(preflight, [], sources)["gate_passed"]


def test_first_twenty_percent_and_aggregate_budget_are_hard_bounds() -> None:
    preflight = dict(batches=[dict(contracts=100)], estimated_transfer_bytes=1000)
    assert not continuation.decision(preflight, [], [source(i) for i in range(19)])["gate_passed"]
    assert not continuation.decision(
        preflight, [dict(response_bytes=1200)], [source(i) for i in range(20)]
    )["gate_passed"]
    with pytest.raises(ValueError, match="duplicate"):
        continuation.decision(preflight, [], [source(1), source(1)])


def portable_run(tmp_path: Path) -> tuple[Path, str, str]:
    config, receipts, _, _ = fixture(tmp_path)
    contracts = continuation.load_contracts(config)
    run = tmp_path / "artifacts/logs/runs/fixture"
    run.mkdir(parents=True)
    digest = continuation.sha(config)
    (run / "config.json").write_text(json.dumps(dict(sha256=digest, toml=config.read_text())))
    (run / "inputs.json").write_text(json.dumps([
        dict(source_id=c.source_id, url=c.url, local_path=str(c.local_path),
             expected_prefix=c.expected_prefix) for c in contracts
    ]))
    (run / "outputs.json").write_bytes(receipts.read_bytes())
    (run / "metrics.json").write_text(json.dumps(dict(
        total_contracts=1, status_counts=dict(downloaded=1),
        transfer_budget=dict(received_response_bytes=123),
    )))
    preflight = tmp_path / "preflight.json"
    preflight.write_text(json.dumps(dict(
        batches=[dict(path=config.name, contracts=1, sha256=digest)]
    )))
    return preflight.relative_to(tmp_path), config.name, str(run.relative_to(tmp_path))


@pytest.mark.parametrize("violation", ["inputs", "config", "outcomes", "metrics", "run_path"])
def test_adopted_run_requires_original_identity_and_complete_accounting(
    tmp_path: Path, violation: str
) -> None:
    preflight, config, run = portable_run(tmp_path)
    assert continuation.batch_record(tmp_path, preflight, config, run)["response_bytes"] == 123
    if violation == "inputs":
        path = tmp_path / run / "inputs.json"
        rows = json.loads(path.read_text())
        rows[0]["url"] = "https://example.test/wrong-source"
        path.write_text(json.dumps(rows))
    elif violation == "config":
        (tmp_path / config).write_text((tmp_path / config).read_text() + "\n# changed\n")
    elif violation == "outcomes":
        (tmp_path / run / "outputs.json").write_text("[]")
    elif violation == "metrics":
        path = tmp_path / run / "metrics.json"
        rows = json.loads(path.read_text())
        rows["total_contracts"] = 2
        path.write_text(json.dumps(rows))
    else:
        run = "artifacts/logs/runs/../../outside"
    with pytest.raises(ValueError):
        continuation.batch_record(tmp_path, preflight, config, run)


def gate_fixture(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "ia-002.toml").write_text("approved")
    preflight = dict(batches=[
        dict(path="ia-001.toml", contracts=200, estimated_bytes=1000),
        dict(path="ia-002.toml", contracts=200, estimated_bytes=1000,
             sha256=continuation.sha(tmp_path / "ia-002.toml")),
    ], estimated_transfer_bytes=2000)
    (tmp_path / "preflight.json").write_text(json.dumps(preflight))
    sources = [source(i) for i in range(200)]
    run = tmp_path / "artifacts/logs/runs/fixture"
    run.mkdir(parents=True)
    (run / "outputs.json").write_text("[]")
    records = [dict(config="ia-001.toml", response_bytes=100, input_sha256={},
                    run=str(run.relative_to(tmp_path)))]
    return dict(
        preflight="preflight.json", preflight_sha256=continuation.sha(tmp_path / "preflight.json"),
        input_sha256={}, batches=records, sources=sources,
        events="events", selection="selection", catalog="catalog",
        deadline_utc=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        decision=continuation.decision(preflight, records, sources),
    )


@pytest.mark.parametrize(
    "violation", ["expired", "deadline_reset", "preflight_changed", "existing"]
)
def test_continuation_rejects_restart_or_stale_inputs_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    gate = gate_fixture(tmp_path)
    deadline = continuation.parse_utc(gate["deadline_utc"])
    output = tmp_path / "state.json"
    if violation == "expired":
        deadline = datetime.now(UTC) - timedelta(seconds=1)
    elif violation == "deadline_reset":
        deadline += timedelta(hours=1)
    elif violation == "preflight_changed":
        (tmp_path / "preflight.json").write_text("{}")
    else:
        output.write_text("existing")
    calls: list[Any] = []
    def invoke(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
    monkeypatch.setattr(continuation.subprocess, "run", invoke)
    with pytest.raises(ValueError):
        continuation.run_remaining(gate, tmp_path, output, deadline)
    assert calls == []


def test_continuation_keeps_error_streak_caps_deadline_and_unattempted_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = gate_fixture(tmp_path)
    receipt = tmp_path / gate["batches"][0]["run"] / "outputs.json"
    receipt.write_text(json.dumps([
        dict(source_id=f"ia-{i}", reason="HTTP Error 503: unavailable", status="quarantined")
        for i in range(2)
    ]))
    commands: list[list[str]] = []

    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert 0 < kwargs["timeout"] <= 3600
        return subprocess.CompletedProcess(command, 2, "", "fixture refusal")

    monkeypatch.setattr(continuation.subprocess, "run", invoke)
    output = tmp_path / "state.json"
    continuation.run_remaining(gate, tmp_path, output, continuation.parse_utc(gate["deadline_utc"]))
    command = commands[0]
    for flag, expected in [
        ("--max-consecutive-provider-errors", "1"), ("--min-interval", "4"),
        ("--max-contracts", "200"), ("--max-total-bytes", "1200"),
    ]:
        assert command[command.index(flag) + 1] == expected
    state = json.loads(output.read_text())
    assert state["status"] == "stopped_command_error"
    assert state["unattempted_batches"] == ["ia-002.toml"]
    assert state["batches"] == gate["batches"]


@pytest.mark.parametrize("violation", ["pending_config", "three_final_errors"])
def test_pending_mutation_or_exhausted_error_streak_blocks_all_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    gate = gate_fixture(tmp_path)
    if violation == "pending_config":
        (tmp_path / "ia-002.toml").write_text("unreviewed")
    else:
        receipt = tmp_path / gate["batches"][0]["run"] / "outputs.json"
        receipt.write_text(json.dumps([
            dict(source_id=f"ia-{i}", reason="HTTP Error 503: unavailable", status="quarantined")
            for i in range(3)
        ]))
    calls: list[Any] = []
    def invoke(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
    monkeypatch.setattr(continuation.subprocess, "run", invoke)
    output = tmp_path / "state.json"
    continuation.run_remaining(gate, tmp_path, output, continuation.parse_utc(gate["deadline_utc"]))
    assert not calls
    expected = (
        "pending_contract_changed" if violation == "pending_config" else "provider_error_streak"
    )
    assert json.loads(output.read_text())["status"] == "stopped_" + expected


def test_changed_completed_evidence_blocks_continuation(tmp_path: Path) -> None:
    gate = gate_fixture(tmp_path)
    evidence = tmp_path / "receipt"
    evidence.write_text("original")
    gate["batches"][0]["input_sha256"] = {"receipt": continuation.sha(evidence)}
    evidence.write_text("changed")
    with pytest.raises(ValueError, match="evidence changed"):
        continuation.run_remaining(
            copy.deepcopy(gate), tmp_path, tmp_path / "state.json",
            continuation.parse_utc(gate["deadline_utc"]),
        )
