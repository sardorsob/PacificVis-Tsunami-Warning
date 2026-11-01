"""Inspect a completed first tranche, then explicitly continue bounded IA batches.

The default gate command is read-only. Only --run dispatches network acquisition;
it requires an accepted gate and an absolute deadline from the original run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import load_contracts  # noqa: E402
from scripts.generate_waveform_contracts import parse_utc  # noqa: E402
from scripts.normalize_audit_waveforms import build  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def batch_record(root: Path, preflight_path: Path, config: str, run: str) -> dict[str, Any]:
    """Bind a portable run to exactly one preflight batch, including transfer accounting."""
    preflight = json.loads((root / preflight_path).read_text())
    expected = {str(preflight_path.parent / b["path"]): b for b in preflight["batches"]}
    if config not in expected or expected[config]["contracts"] > 200:
        raise ValueError("run is not an approved bounded batch")
    run_path = Path(run)
    if (
        not run_path.is_relative_to(Path("artifacts/logs/runs"))
        or ".." in run_path.parts
        or not (root / run_path).resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("run path escapes portable evidence")
    config_hash = sha(root / config)
    captured = json.loads((root / run_path / "config.json").read_text())
    if (
        config_hash != expected[config]["sha256"]
        or captured["sha256"] != config_hash
        or hashlib.sha256(captured["toml"].encode()).hexdigest() != config_hash
    ):
        raise ValueError("run configuration differs from pinned preflight")
    outputs = json.loads((root / run_path / "outputs.json").read_text())
    contracts = load_contracts(root / config)
    captured_inputs = json.loads((root / run_path / "inputs.json").read_text())
    captured_by_id = {c["source_id"]: c for c in captured_inputs}
    if len(captured_by_id) != len(captured_inputs) or set(captured_by_id) != {
        c.source_id for c in contracts
    }:
        raise ValueError("run captured inputs differ from approved contract")
    for contract in contracts:
        identity = dict(
            url=contract.url,
            local_path=str(contract.local_path),
            expected_prefix=contract.expected_prefix,
        )
        if contract.expected_cdx_sha1:
            identity.update(
                expected_cdx_sha1=contract.expected_cdx_sha1,
                cdx_evidence_path=contract.cdx_evidence_path,
                cdx_evidence_sha256=contract.cdx_evidence_sha256,
            )
        if any(captured_by_id[contract.source_id].get(k) != v for k, v in identity.items()):
            raise ValueError("run captured source identity differs from contract")
    if len(outputs) != len(contracts) or {o["source_id"] for o in outputs} != {
        c.source_id for c in contracts
    }:
        raise ValueError("run lacks complete source outcomes")
    metrics = json.loads((root / run_path / "metrics.json").read_text())
    counts = dict(Counter(o["status"] for o in outputs))
    if (
        counts != metrics["status_counts"]
        or metrics["total_contracts"] != len(contracts)
        or len(contracts) != expected[config]["contracts"]
        or not set(counts) <= {"cached", "downloaded", "quarantined", "skipped", "blocked"}
    ):
        raise ValueError("run outcome accounting differs")
    return dict(
        config=config,
        run=run,
        status_counts=counts,
        response_bytes=metrics["transfer_budget"]["received_response_bytes"],
        input_sha256={
            str(Path(config)): config_hash,
            **{
                str(run_path / name): sha(root / run_path / name)
                for name in ("config.json", "inputs.json", "outputs.json", "metrics.json")
            },
        },
    )


def inspect_batches(
    root: Path, records: list[dict[str, Any]], events: Path, selection: Path, catalog: Path
) -> list[dict[str, Any]]:
    """Operational structural usability, with no clean-arrival or onset claim."""
    with tempfile.TemporaryDirectory(prefix="ntwc-yield-") as temporary:
        out = Path(temporary) / "normalized"
        summary = build(
            [root / r["config"] for r in records],
            [root / r["run"] / "outputs.json" for r in records],
            root / events,
            root,
            out,
            selection=root / selection,
            known_catalog=root / catalog,
            retain_unparsed=True,
        )
        result: list[dict[str, Any]] = []
        for source in summary["sources"]:
            error = source.get("provider_error", {}).get("error", {})
            expected_no_data = (
                source["processing_status"] == "unavailable_provider_response"
                and "no data was found" in str(error.get("message", "")).casefold()
            )
            valid = 0
            if source["processing_status"] == "normalized_source_samples":
                with gzip.open(out / source["output_path"], "rt", newline="") as stream:
                    for row in csv.DictReader(stream):
                        valid += int(
                            row["value_state"] == "finite_numeric"
                            and row["timestamp_utc"] != "unknown"
                            and row["duplicate_timestamp"] == "False"
                        )
            documented_units = source.get("units", "").casefold() in {
                "m",
                "cm",
                "meters",
                "metres",
                "centimeters",
                "centimetres",
            }
            provider = "ia" if source["source_id"].startswith("ia-") else "coops"
            limit = 290000 if provider == "ia" else 2180000
            row: dict[str, Any] = dict(
                source_id=source["source_id"],
                processing_status=source["processing_status"],
                acquisition_status=source["acquisition_status"],
                reason=source["reason"],
                source_bytes=source.get("source_bytes", 0),
                source_sha256=source.get("source_sha256"),
                source_rows=source["source_rows"],
                finite_valid_unique_rows=valid,
                structurally_usable=valid > 0 and documented_units,
                expected_no_data=expected_no_data,
                provider=provider,
                units=source.get("units", "unresolved"),
                cadence_seconds=source.get("declared_cadence_seconds", "unresolved"),
                timestamp_states=source.get("timestamp_states", {}),
                value_states=source.get("value_states", {}),
            )
            if row["source_bytes"] > limit:
                raw = (root / source["raw_path"]).read_bytes()
                row["oversize_inspection"] = dict(
                    ten_times_unit_bytes=limit,
                    line_count=len(raw.splitlines()),
                    header_lines=[
                        line.decode("utf-8", errors="replace")[:500]
                        for line in raw.splitlines()[:4]
                    ],
                    header_metadata=source.get("source_metadata", {}),
                    parse_reason=source.get("parse_reason", "documented header parsed"),
                    disposition="retained_with_explicit_source_semantics; no onset inference",
                )
            result.append(row)
    return result


def decision(
    preflight: dict[str, Any], records: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    total = sum(b["contracts"] for b in preflight["batches"])
    attempts = len(sources)
    if len({s["source_id"] for s in sources}) != attempts:
        raise ValueError("duplicate source in cumulative gate")
    expected = sum(s["expected_no_data"] for s in sources)
    usable = sum(s["structurally_usable"] for s in sources)
    denominator = attempts - expected
    spent = sum(r["response_bytes"] for r in records)
    cap = math.floor(preflight["estimated_transfer_bytes"] * 1.2)
    provider_stopped = any("provider_error_limit:" in s["reason"] for s in sources)
    byte_limit_stopped = any("max_total_bytes" in s["reason"] for s in sources)
    due = attempts >= math.ceil(total * 0.2)
    passed = due and denominator > 0 and usable / denominator >= 0.5
    return dict(
        gate_passed=passed and spent < cap and not provider_stopped and not byte_limit_stopped,
        gate_due=due,
        completed_contracts=attempts,
        planned_contracts=total,
        completed_fraction=attempts / total,
        structurally_usable=usable,
        expected_no_data=expected,
        evaluated_denominator=denominator,
        usable_fraction_excluding_expected_no_data=usable / denominator if denominator else 0,
        usable_fraction_all_attempts=usable / attempts if attempts else 0,
        response_bytes_total=spent,
        aggregate_response_byte_cap=cap,
        remaining_response_bytes=max(0, cap - spent),
        provider_stopped=provider_stopped,
        byte_limit_stopped=byte_limit_stopped,
        max_source_bytes={
            p: max((s["source_bytes"] for s in sources if s["provider"] == p), default=0)
            for p in ("ia", "coops")
        },
        oversized_sources=[s for s in sources if "oversize_inspection" in s],
        rule="S3 operational structural gate: supported UTC parser, documented units and at least "
        "one finite/time-valid/nonduplicate sample; not waveform cleanliness or onset validation. "
        "Expected CO-OPS no-data is separate. Gaps, QC, sentinels and timestamps remain explicit.",
    )


def write_new(path: Path, document: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def trailing_ia_errors(root: Path, records: list[dict[str, Any]]) -> int:
    """Use original ordered outcomes, not normalized-source ordering, for carryover."""
    streak = 0
    for record in records:
        if not Path(record["config"]).name.startswith("ia-"):
            continue
        outcomes = json.loads((root / record["run"] / "outputs.json").read_text())
        if [s["source_id"] for s in outcomes] != sorted(s["source_id"] for s in outcomes):
            raise ValueError("acquisition outcome order differs from source-ID request order")
        for source in outcomes:
            if re.search(r"HTTP(?: Error)? (?:403|429|5\d\d)", source["reason"]):
                streak += 1
            elif source["status"] == "downloaded":
                streak = 0
    return streak


def run_remaining(gate: dict[str, Any], root: Path, state_path: Path, deadline: datetime) -> None:
    """Explicit root-invoked continuation; no overwriting or implicit restart."""
    if not gate["decision"]["gate_passed"]:
        raise ValueError("continuation requires a passed first-tranche gate")
    if state_path.exists() or deadline <= datetime.now(UTC):
        raise ValueError("continuation state exists or original deadline has expired")
    preflight_path = Path(gate["preflight"])
    if sha(root / preflight_path) != gate["preflight_sha256"]:
        raise ValueError("preflight changed after gate")
    preflight = json.loads((root / preflight_path).read_text())
    for record in gate["batches"]:
        for value, digest in record["input_sha256"].items():
            if sha(root / value) != digest:
                raise ValueError("completed-run evidence changed after gate")
    for value, digest in gate["input_sha256"].items():
        if sha(root / value) != digest:
            raise ValueError("gate input changed after inspection")
    if deadline != parse_utc(gate["deadline_utc"]):
        raise ValueError("continuation cannot reset the original deadline")
    state: dict[str, Any] = {**gate, "provider": "all", "status": "running"}
    write_new(state_path, state)

    def save() -> None:
        completed_configs = {r["config"] for r in state["batches"]}
        state["unattempted_batches"] = [
            str(preflight_path.parent / b["path"])
            for b in preflight["batches"]
            if str(preflight_path.parent / b["path"]) not in completed_configs
        ]
        temporary = state_path.with_suffix(state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        temporary.replace(state_path)

    completed = {r["config"] for r in state["batches"]}
    for batch in preflight["batches"]:
        config = str(preflight_path.parent / batch["path"])
        if config in completed:
            continue
        if not batch["path"].startswith("ia-"):
            raise ValueError("NOAA must be complete before IA continuation")
        remaining_seconds = (deadline - datetime.now(UTC)).total_seconds()
        if remaining_seconds <= 0 or not state["decision"]["gate_passed"]:
            state["status"] = "stopped_deadline_or_gate"
            save()
            return
        if sha(root / config) != batch["sha256"] or batch["contracts"] > 200:
            state["status"] = "stopped_pending_contract_changed"
            save()
            return
        # A trailing access-error streak cannot be reset by starting a new process.
        streak = trailing_ia_errors(root, state["batches"])
        if streak >= 3:
            state["status"] = "stopped_provider_error_streak"
            save()
            return
        error_limit = 3 - streak
        byte_cap = min(
            state["decision"]["remaining_response_bytes"],
            math.floor(batch["estimated_bytes"] * 1.2),
        )
        command = [
            str(root / ".venv/bin/python"),
            str(root / "scripts/acquire_tohoku.py"),
            "--root",
            str(root),
            "--config",
            config,
            "--run-tag",
            "continue-" + batch["path"][:-5],
            "--lane",
            "paper",
            "--min-interval",
            "4",
            "--max-contracts",
            "200",
            "--max-total-bytes",
            str(byte_cap),
            "--max-object-bytes",
            "20000000",
            "--max-consecutive-provider-errors",
            str(error_limit),
        ]
        state["active_command"] = command
        save()
        try:
            completed_run = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=remaining_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            state["status"] = "stopped_deadline_with_unreceipted_batch"
            save()
            return
        match = re.search(r"to (.+)\s*$", completed_run.stdout.strip())
        if completed_run.returncode or not match:
            state.update(
                status="stopped_command_error",
                stdout=completed_run.stdout,
                stderr=completed_run.stderr,
            )
            save()
            return
        run = Path(match[1])
        if run.is_absolute():
            run = run.relative_to(root)
        record = batch_record(root, preflight_path, config, str(run))
        state["batches"].append(record)
        state["sources"].extend(
            inspect_batches(
                root,
                [record],
                Path(gate["events"]),
                Path(gate["selection"]),
                Path(gate["catalog"]),
            )
        )
        state["decision"] = decision(preflight, state["batches"], state["sources"])
        state.pop("active_command", None)
        save()
        time.sleep(4)
    state["status"] = (
        "completed" if state["decision"]["gate_passed"] else "completed_with_gate_stop"
    )
    save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--checkpoint", type=Path, action="append", default=[])
    parser.add_argument("--adopt-ia-run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--gate-sha256")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--deadline-utc")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.run:
        if args.gate is None or args.gate_sha256 is None:
            parser.error("--run requires --gate and its independently reviewed --gate-sha256")
        if sha(args.gate) != args.gate_sha256:
            raise ValueError("gate changed after independent review")
        gate = json.loads(args.gate.read_text())
        deadline = args.deadline_utc or gate["deadline_utc"]
        run_remaining(gate, root, args.output, parse_utc(deadline))
        return 0
    if any(
        p is None
        for p in (args.preflight, args.events, args.selection, args.catalog, args.deadline_utc)
    ):
        parser.error(
            "gate requires --preflight, --events, --selection, --catalog and original deadline"
        )
    preflight = json.loads((root / args.preflight).read_text())
    records: list[dict[str, Any]] = []
    for path in args.checkpoint:
        checkpoint = json.loads(path.read_text())
        if checkpoint["preflight_sha256"] != sha(root / args.preflight):
            raise ValueError("checkpoint is for a different preflight")
        records.extend(
            batch_record(root, args.preflight, b["config"], b["run"]) for b in checkpoint["batches"]
        )
    if args.adopt_ia_run:
        first = next(b for b in preflight["batches"] if b["path"].startswith("ia-"))
        config = str(args.preflight.parent / first["path"])
        if config not in {r["config"] for r in records}:
            records.append(batch_record(root, args.preflight, config, str(args.adopt_ia_run)))
    sources = inspect_batches(root, records, args.events, args.selection, args.catalog)
    document: dict[str, Any] = dict(
        preflight=str(args.preflight),
        preflight_sha256=sha(root / args.preflight),
        events=str(args.events),
        selection=str(args.selection),
        catalog=str(args.catalog),
        deadline_utc=parse_utc(args.deadline_utc).isoformat(),
        input_sha256={str(p): sha(root / p) for p in (args.events, args.selection, args.catalog)},
        batches=records,
        sources=sources,
        decision=decision(preflight, records, sources),
    )
    write_new(args.output, document)
    print(json.dumps(document["decision"], sort_keys=True))
    return 0 if document["decision"]["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
