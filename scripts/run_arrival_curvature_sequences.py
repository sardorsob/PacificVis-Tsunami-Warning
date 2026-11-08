"""Conserved finite sequence-CV ledger; first metadata-defined fold requires review."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json  # noqa: E402
from scripts.run_arrival_curvature_calibration import working_roots  # noqa: E402
from scripts.run_arrival_curvature_fit import CONTROL as ACTUAL_CONTROL  # noqa: E402
from scripts.run_arrival_curvature_fit import DESIGN as ACTUAL_DESIGN  # noqa: E402
from scripts.run_arrival_curvature_fit import OUTPUT as ACTUAL_OUTPUT  # noqa: E402
from scripts.run_arrival_curvature_fit import STORE as ACTUAL_STORE  # noqa: E402
from scripts.run_arrival_curvature_pilot import bindings, byte_count  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

SELF = "scripts/run_arrival_curvature_sequences.py"
OUTPUT = "artifacts/models/arrival-timing/mean-curvature-sequence-v1"
STORE = "data/processed/models/mean-curvature-sequence-v1"
DESIGN = "artifacts/models/arrival-timing/mean-curvature-sequence-design-v1"
STATE = "context/runs/arrival-model-fitting-v1/curvature-sequence-state.json"
REHEARSAL = OUTPUT + "/rehearsal-review-acceptance.json"
MIB = 1024**2
MAX_GLOBAL = 2048 * MIB
MAX_LOCAL = 1024 * MIB
MAX_CACHE = 256 * MIB
MAX_JOB = 32 * MIB
RESERVE = 608 * MIB
MAX_CALLS = 248
TIMEOUT = 1200


def parent_roots(root):
    parents = working_roots(
        root,
        root / "artifacts/models/arrival-timing/mean-curvature-calibration-v1",
        root / "data/processed/models/mean-curvature-calibration-v1",
    )
    return [
        *parents,
        *(root / p for p in [ACTUAL_OUTPUT, ACTUAL_STORE, ACTUAL_CONTROL, ACTUAL_DESIGN]),
    ]


def make_design(root):
    from analysis.arrival.model_data import load_lanes, sequence_folds

    lane = load_lanes(root)[0]["NCEI-native-duration"]
    cases = []
    memberships = {}
    for j, fold in enumerate(sequence_folds(lane)):
        identity = f"fold-{j:03d}"
        cases.append(
            {
                "id": identity,
                "target": lane.target,
                "kind": "mean-curvature",
                "prior": "base",
                "sequence": fold.sequence_id,
                "draws": 2000,
                "tune": 1000,
                "cores": 2,
                "seed": 2856110800 + 1000 * j,
            }
        )
        events = sorted({lane.event_ids[int(i)] for i in fold.test})
        memberships[identity] = {
            "train": [lane.record_ids[int(i)] for i in fold.train],
            "test": [lane.record_ids[int(i)] for i in fold.test],
            "sequence": fold.sequence_id,
            "held_events": events,
            "event_records": {
                event: [
                    lane.record_ids[int(i)] for i in fold.test if lane.event_ids[int(i)] == event
                ]
                for event in events
            },
            "charged_call_slots": 1 + len(events),
        }
    if len(cases) != 29 or sum(len(v["held_events"]) for v in memberships.values()) != 33:
        raise ValueError("frozen29sequence33event design required")
    return cases, memberships


def quota_failure(root, parents, current=None):
    output, store = root / OUTPUT, root / STORE
    if byte_count(*parents, output, store, root / DESIGN) > MAX_GLOBAL:
        return "global_storage"
    if byte_count(output, store) > MAX_LOCAL:
        return "local_storage"
    if byte_count(store / "cache") > MAX_CACHE:
        return "cache_storage"
    if current is not None and byte_count(current) > MAX_JOB:
        return "job_output_storage"
    return None


def parent_floors(root, gate):
    parents = parent_roots(root)
    floors = gate.get("parent_minimum_bytes", {})
    if (
        set(floors) != {str(p.relative_to(root)) for p in parents}
        or any(type(v) is not int or v < 0 for v in floors.values())
        or any(not (root / p).is_dir() or byte_count(root / p) < v for p, v in floors.items())
    ):
        raise ValueError("preserved cumulative parent accounting required")
    return parents


def case_artifacts(root, case, membership, pins, accepted=None):
    attempt = root / OUTPUT / "jobs" / case["id"]
    raw = root / STORE / case["id"]
    manifest = attempt / "attempt-evidence.json"
    mandatory = [
        attempt / n
        for n in [
            "job.json",
            "inputs.json",
            "membership.json",
            "result.json",
            "held-out-record-predictions.csv",
            "event-joint-scores.csv",
        ]
    ]
    mandatory += [
        attempt.with_name(case["id"] + "-spec.json"),
        attempt.with_suffix(".log"),
        attempt.with_suffix(".supervisor.json"),
        raw / "bridge-arrays.npz",
    ]
    raw_expected = {raw / "bridge-arrays.npz"}
    for k, event in enumerate([None, *membership["held_events"]]):
        phase = "training" if event is None else "augmented"
        folder = attempt / "ensembles" / f"{k:02d}-{phase}"
        mandatory += [attempt / "sampling-starts" / f"{k:02d}.json"]
        mandatory += [
            folder / n
            for n in [
                "job.json",
                "inputs.json",
                "membership.json",
                "result.json",
                "sampling-diagnostics.csv",
            ]
        ]
        posterior = raw / f"{k:02d}-{phase}.nc"
        mandatory.append(posterior)
        raw_expected.add(posterior)
    if not all(p.is_file() for p in mandatory):
        raise ValueError("complete mandatory fold evidence required")
    if {p for p in raw.rglob("*") if p.is_file()} != raw_expected:
        raise ValueError("unexpected raw posterior or partial in accepted fold")
    paths = {p for p in attempt.rglob("*") if p.is_file() and p != manifest} | set(mandatory)
    files = {str(p.relative_to(root)): sha256(p) for p in paths}
    if accepted is not None:
        if (
            accepted.get("charged_slots") != membership["charged_call_slots"]
            or accepted.get("receipt") != str(manifest.relative_to(root))
            or not manifest.exists()
            or sha256(manifest) != accepted.get("receipt_sha256")
            or accepted.get("files") != files
            or json.loads(manifest.read_text()) != {"case_id": case["id"], "files": files}
        ):
            raise ValueError("accepted prefix closure changed or omitted")
    result = json.loads((attempt / "result.json").read_text())
    expected_members = {k: membership[k] for k in ["train", "test", "sequence"]}
    if (
        result.get("job") != case
        or result.get("status") != "computed_pending_review"
        or result.get("sampler_calls_started") != membership["charged_call_slots"]
        or not result.get("score_precision_passed")
        or not result.get("prediction_precision_passed")
        or result.get("confirmation_outcomes_parsed") is not False
        or result.get("reserved_outcomes") != "sealed"
        or result.get("observation_measure") != "native_minutes_Jacobian_already_applied_once"
        or json.loads((attempt / "job.json").read_text()) != case
        or json.loads((attempt / "membership.json").read_text()) != expected_members
        or json.loads((attempt / "inputs.json").read_text()).get("files") != pins
        or result.get("bridge_arrays_sha256") != sha256(raw / "bridge-arrays.npz")
    ):
        raise ValueError("fold result identity, native measure or precision changed")
    if sorted(e["event_id"] for e in result["events"]) != membership["held_events"]:
        raise ValueError("held-event score membership changed")
    predictions = read_rows(attempt / "held-out-record-predictions.csv")
    if (
        len(predictions) != len(membership["test"])
        or {r["record_id"] for r in predictions} != set(membership["test"])
        or any(
            r["record_id"] not in membership["event_records"].get(r["event_id"], [])
            for r in predictions
        )
        or any(r.get("prediction_precision_passed") != "True" for r in predictions)
        or any(
            e["records"] != len(membership["event_records"][e["event_id"]])
            for e in result["events"]
        )
    ):
        raise ValueError("complete held-event prediction membership and precision required")
    supervisor = json.loads(attempt.with_suffix(".supervisor.json").read_text())
    if (
        supervisor.get("returncode") != 0
        or supervisor.get("reason") != "worker_exit"
        or supervisor.get("charged_slots") != membership["charged_call_slots"]
        or supervisor.get("start_markers") != membership["charged_call_slots"]
        or supervisor.get("job_sha256") != sha256(attempt.with_name(case["id"] + "-spec.json"))
        or supervisor.get("plan_sha256") != sha256(root / OUTPUT / "plan.json")
        or supervisor.get("monitor_failures")
    ):
        raise ValueError("complete successful process/call receipt required")
    from analysis.arrival.model_curvature_sequence import CONSUMED, GATE

    expected_sources = {p: pins[p] for p in [*CONSUMED, GATE]}
    source_files = json.loads((attempt / "inputs.json").read_text()).get("source_files")
    if not isinstance(source_files, dict) or not source_files:
        raise ValueError("complete frozen data source identities required")
    for k, event in enumerate([None, *membership["held_events"]]):
        phase = "training" if event is None else "augmented"
        spec = {**case, "phase": phase, "event": event, "seed": case["seed"] + k}
        folder = attempt / "ensembles" / f"{k:02d}-{phase}"
        result = json.loads((folder / "result.json").read_text())
        inputs = json.loads((folder / "inputs.json").read_text())
        included = json.loads((folder / "membership.json").read_text()).get("included", [])
        expected_ids = set(membership["train"]) | (
            set() if event is None else set(membership["event_records"][event])
        )
        if (
            inputs.get("files") != expected_sources
            or inputs.get("source_files") != source_files
            or len(included) != len(expected_ids)
            or set(included) != expected_ids
        ):
            raise ValueError("one-event ensemble membership or frozen source identity changed")
        if (
            json.loads((attempt / "sampling-starts" / f"{k:02d}.json").read_text()) != spec
            or json.loads((folder / "job.json").read_text()) != spec
            or result.get("job") != spec
            or result.get("posterior") != str((raw / f"{k:02d}-{phase}.nc").relative_to(root))
            or result.get("posterior_sha256") != sha256(raw / f"{k:02d}-{phase}.nc")
            or not result.get("diagnostics", {}).get("screen_passed")
        ):
            raise ValueError("closed ensemble identity or diagnostics changed")
    return files, manifest


def verify_rehearsal(root, state):
    path = root / REHEARSAL
    if state["next_fold"] < 1 or not path.is_file():
        raise ValueError("independent first-fold rehearsal required")
    gate = json.loads(path.read_text())
    first = state["accepted"][0]
    required = {
        **first["files"],
        first["receipt"]: first["receipt_sha256"],
        OUTPUT + "/plan.json": sha256(root / OUTPUT / "plan.json"),
    }
    if (
        gate.get("status") != "accepted_first_curvature_sequence"
        or gate.get("independent_checker") is not True
        or any(gate.get("files", {}).get(p) != h for p, h in required.items())
    ):
        raise ValueError("complete independently accepted rehearsal proof required")
    for p, h in gate["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("rehearsal proof changed")
    identity = sha256(path)
    if state.get("rehearsal_sha256") not in {None, identity}:
        raise ValueError("rehearsal gate identity changed")
    return identity


def run(root, *, resume=False, max_folds=1):
    root = root.resolve()
    output, store, state_path = root / OUTPUT, root / STORE, root / STATE
    if not resume and max_folds != 1:
        raise ValueError("initial invocation is the single first-fold rehearsal")
    if not 1 <= max_folds <= 3:
        raise ValueError("one through three finite folds per invocation")
    if resume:
        if not all(p.exists() for p in [output, store, state_path]):
            raise ValueError("original state and stores required")
    elif any(p.exists() for p in [output, store, state_path]):
        raise ValueError("new conserved CV allocation required")
    cache_env = {
        "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
        "NUMBA_CACHE_DIR": str(store / "cache/numba"),
        "MPLCONFIGDIR": str(store / "cache/matplotlib"),
    }
    os.environ.update(cache_env)
    from analysis.arrival.model_curvature_sequence import CONSUMED, GATE, verify_gate

    gate = json.loads((root / GATE).read_text())
    if not isinstance(gate.get("cases"), list) or not gate["cases"]:
        raise ValueError("accepted case manifest required before outcome loading")
    pins = verify_gate(root, gate["cases"][0])
    cases, memberships = make_design(root)
    expected = {
        "cases": cases,
        "memberships": memberships,
        "max_sampler_call_slots": MAX_CALLS,
        "nominal_sampler_call_slots": 62,
        "global_max_bytes": MAX_GLOBAL,
        "local_max_bytes": MAX_LOCAL,
        "cache_max_bytes": MAX_CACHE,
        "job_max_bytes": MAX_JOB,
        "next_invocation_reserve_bytes": RESERVE,
        "timeout_seconds": TIMEOUT,
        "timeout_scope": "whole_fold_all_ensembles_and_scoring",
        "cache_environment": cache_env,
        "concurrency": 1,
        "automatic_retries": 0,
    }
    if any(gate.get(k) != v for k, v in expected.items()) or not {SELF, *CONSUMED}.issubset(pins):
        raise ValueError("complete independently frozen CV runtime/resource design required")
    parents = parent_floors(root, gate)
    bound = bindings(root, output, store, state_path)
    if not resume:
        output.mkdir(parents=True)
        store.mkdir(parents=True)
    elif json.loads((output / "plan.json").read_text()).get("path_bindings") != bound:
        raise ValueError("frozen path accounting cannot be copied or reset")
    lease = output / ".controller.lock"
    with lease.open("x") as stream:
        stream.write(str(os.getpid()))
    ended = threading.Event()
    failures = []
    current = [None]
    stop = output / "STOP"

    def monitor():
        while not ended.wait(0.1):
            reason = quota_failure(root, parents, current[0])
            if reason:
                failures.append(reason)
                if not stop.exists():
                    stop.write_text(reason + "\n")
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        limit_worker_file_size(64 * MIB)
        if resume:
            plan = json.loads((output / "plan.json").read_text())
            state = json.loads(state_path.read_text())
            if (
                plan["files"] != pins
                or plan["cases"] != cases
                or plan["memberships"] != memberships
                or plan["resource_design"] != expected
                or state["plan_sha256"] != sha256(output / "plan.json")
                or state["status"] not in {"checkpoint", "complete"}
                or state["current"] is not None
                or state["next_fold"] != len(state["accepted"])
                or state["calls_charged"] != sum(a["charged_slots"] for a in state["accepted"])
                or state["calls_started"] != state["calls_charged"]
                or not 0 <= state["calls_charged"] <= MAX_CALLS
            ):
                raise ValueError(
                    "failed, changed or incomplete ledger requires reviewed reconciliation"
                )
            if [a["case_id"] for a in state["accepted"]] != [
                c["id"] for c in cases[: state["next_fold"]]
            ]:
                raise ValueError("accepted prefix membership changed")
            for case, a in zip(cases, state["accepted"], strict=False):
                case_artifacts(root, case, memberships[case["id"]], pins, a)
        else:
            plan = {
                "files": pins,
                "cases": cases,
                "memberships": memberships,
                "resource_design": expected,
                "path_bindings": bound,
                "source_git_sha": git_sha(root),
                "scope": "248inclusive_conservatively_charged_slots; no automatic repair; "
                "all parent/cache/partial bytes counted; "
                "monitored thresholds not filesystem quotas",
            }
            write_json(output / "plan.json", plan)
            state = {
                "next_fold": 0,
                "calls_charged": 0,
                "calls_started": 0,
                "accepted": [],
                "current": None,
                "status": "checkpoint",
                "plan_sha256": sha256(output / "plan.json"),
            }
            atomic_state(state_path, state)
        was_complete = resume and state["status"] == "complete"
        for _ in range(max_folds):
            if state["next_fold"] >= 1:
                state["rehearsal_sha256"] = verify_rehearsal(root, state)
                atomic_state(state_path, state)
            parent_floors(root, gate)
            expected_dirs = {a["case_id"] for a in state["accepted"]}
            if any(p.is_file() for p in store.iterdir()):
                raise ValueError("unexpected raw file or partial outside a closed fold")
            if {
                p.name for p in store.iterdir() if p.is_dir() and p.name != "cache"
            } != expected_dirs:
                raise ValueError("unexpected raw fold directory/partial")
            if state["next_fold"] == len(cases):
                if quota_failure(root, parents):
                    raise ValueError("completed collection exceeds retained storage budget")
                if was_complete:
                    return  # completed validation is read-only; do not rewrite a frozen summary
                break
            case = cases[state["next_fold"]]
            membership = memberships[case["id"]]
            cost = membership["charged_call_slots"]
            if (
                stop.exists()
                or failures
                or quota_failure(root, parents)
                or state["calls_charged"] + cost > MAX_CALLS
                or byte_count(output, store) + RESERVE > MAX_LOCAL
                or byte_count(*parents, output, store, root / DESIGN) + RESERVE > MAX_GLOBAL
            ):
                state["status"] = "stop_or_budget_failure"
                break
            if any(sha256(root / p) != h for p, h in pins.items()):
                raise ValueError("CV source drift")
            attempt = output / "jobs" / case["id"]
            raw = store / case["id"]
            spec = attempt.with_name(case["id"] + "-spec.json")
            if any(
                p.exists()
                for p in [
                    attempt,
                    raw,
                    spec,
                    attempt.with_suffix(".log"),
                    attempt.with_suffix(".supervisor.json"),
                ]
            ):
                raise ValueError("prior attempt/receipt retained; no overwrite")
            write_json(spec, case)
            state.update(
                current=case["id"], calls_charged=state["calls_charged"] + cost, status="running"
            )
            atomic_state(state_path, state)
            current[0] = attempt
            try:
                receipt = supervise(
                    [
                        sys.executable,
                        str(root / "scripts/fit_arrival_curvature_sequence.py"),
                        "--job",
                        str(spec),
                        "--output",
                        str(attempt),
                        "--store",
                        str(raw),
                    ],
                    attempt.with_suffix(".log"),
                    stop,
                    TIMEOUT,
                )
            except KeyboardInterrupt:
                receipt = {"returncode": 130, "reason": "interrupt"}
            starts = list((attempt / "sampling-starts").glob("*.json"))
            state["calls_started"] += len(starts)
            write_json(
                attempt.with_suffix(".supervisor.json"),
                {
                    **receipt,
                    "monitor_failures": failures,
                    "charged_slots": cost,
                    "start_markers": len(starts),
                    "job_sha256": sha256(spec),
                    "plan_sha256": state["plan_sha256"],
                },
            )
            current[0] = None
            state["current"] = None
            status = "interrupted" if receipt["reason"] == "interrupt" else "runtime_failure"
            result_path = attempt / "result.json"
            if (
                receipt["returncode"] == 0
                and receipt["reason"] == "worker_exit"
                and result_path.exists()
            ):
                result = json.loads(result_path.read_text())
                status = "precision_or_diagnostic_failure"
                if (
                    result.get("job") == case
                    and result.get("status") == "computed_pending_review"
                    and len(starts) == cost
                ):
                    files, manifest = case_artifacts(root, case, membership, pins)
                    write_json(manifest, {"case_id": case["id"], "files": files})
                    state["accepted"].append(
                        {
                            "case_id": case["id"],
                            "charged_slots": cost,
                            "files": files,
                            "receipt": str(manifest.relative_to(root)),
                            "receipt_sha256": sha256(manifest),
                        }
                    )
                    state["next_fold"] += 1
                    status = "complete" if state["next_fold"] == len(cases) else "checkpoint"
            if failures or quota_failure(root, parents, attempt):
                status = "storage_failure"
            state["status"] = status
            atomic_state(state_path, state)
            if status not in {"checkpoint", "complete"}:
                break
        atomic_state(state_path, state)
        write_json(
            output / "run-summary.json",
            {
                "status": state["status"],
                "computed_folds": state["next_fold"],
                "calls_charged": state["calls_charged"],
                "calls_started": state["calls_started"],
                "max_sampler_call_slots": MAX_CALLS,
                "nominal_sampler_call_slots": 62,
                "working_bytes": byte_count(*parents, output, store, root / DESIGN),
                "confirmation_outcomes_parsed": False,
                "reserved_outcomes": "sealed",
            },
        )
        if quota_failure(root, parents):
            state["status"] = "storage_failure"
            atomic_state(state_path, state)
            summary = json.loads((output / "run-summary.json").read_text())
            summary["status"] = "storage_failure"
            summary["working_bytes"] = byte_count(*parents, output, store, root / DESIGN)
            write_json(output / "run-summary.json", summary)
        if state["status"] not in {"checkpoint", "complete"}:
            raise SystemExit(2)
    finally:
        ended.set()
        watcher.join(timeout=2)
        lease.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-folds", type=int, default=1)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], resume=args.resume, max_folds=args.max_folds)
