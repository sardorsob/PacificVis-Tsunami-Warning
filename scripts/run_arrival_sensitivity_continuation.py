"""Reviewed resource-only continuation of the immutable55-case MS-5 controller."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival import model_sensitivity_references as references  # noqa: E402
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivities as r  # noqa: E402
from scripts.run_arrival_model_batch import git_sha  # noqa: E402

SELF = "scripts/run_arrival_sensitivity_continuation.py"
TEST = "tests/test_run_arrival_sensitivity_continuation.py"
DESIGN = r.DESIGN + "/resource-continuation-v1"
GATE = DESIGN + "/review-acceptance.json"
CONTROL = r.OUTPUT + "/resource-continuation-v1"
BASELINE = CONTROL + "/baseline-state.json"
PLAN = r.OUTPUT + "/plan.json"
PROJECTION = CONTROL + "/resource-projection.json"
EXTERNAL_BYTES = 18_895_366
GLOBAL_MAX, LOCAL_MAX = 3072 * r.MIB, 2048 * r.MIB
_OVERRIDE_LOCK = threading.Lock()


def resources():
    return {**r.resources(), "global_max_bytes": GLOBAL_MAX, "local_max_bytes": LOCAL_MAX}


def _path(root, name):
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or Path(name).as_posix() != name
        or any(p in {".", ".."} for p in name.split("/"))
    ):
        raise ValueError("literal project-relative continuation file required")
    path = root / name
    if path.resolve() != path or not path.is_file():
        raise ValueError("literal nonsymlink continuation file required")
    return path


def _unchanged(root, pins):
    if not isinstance(pins, dict) or not pins:
        raise ValueError("complete continuation source pins required")
    for name, digest in pins.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or sha256(_path(root, name)) != digest
        ):
            raise ValueError("continuation source identity changed")


def _require(pins, subset):
    if (
        not isinstance(subset, dict)
        or not subset
        or any(pins.get(p) != h for p, h in subset.items())
    ):
        raise ValueError("complete source-bound continuation closure required")


def counted_roots(root, parents):
    """Exactly the roots traversed by frozen r.working_bytes, without rescanning data."""
    final = r.final_continuation
    sumatra, completion = final.sumatra, final.sumatra.completion
    previous = completion.previous
    names = [
        previous.OUTPUT,
        previous.STORE,
        previous.ORIGINAL_DESIGN,
        str(Path(previous.PATH_GATE).parent),
        previous.DESIGN,
        str(Path(completion.PRECISION_GATE).parent),
        completion.DESIGN,
        str(Path(sumatra.GATE).parent),
        final.DESIGN,
        r.DESIGN,
        r.OUTPUT,
        r.STORE,
    ]
    roots = set(parents) | {root / name for name in names}
    return sorted(p for p in roots if not any(a in p.parents for a in roots))


def external_reference_paths(root, parents):
    roots = counted_roots(root, parents)
    return sorted(
        {
            ref["raw"]
            for ref in references.descriptors()
            if not any(root / ref["raw"] == p or p in (root / ref["raw"]).parents for p in roots)
        }
    )


def verify_continuation(root):
    root = root.resolve()
    gate = json.loads(_path(root, GATE).read_text())
    required = {
        SELF,
        TEST,
        "analysis/arrival/model_sensitivity_references.py",
        r.GATE,
        PLAN,
        r.PILOT_REVIEW,
        BASELINE,
        PROJECTION,
        *r.RUNTIME,
    }
    if (
        gate.get("status") != "accepted_exploration_sensitivity_resource_continuation"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("resources") != resources()
        or gate.get("path_bindings") != r.path_bindings(root)
        or gate.get("planning_projection") != PROJECTION
        or not required <= set(gate.get("files", {}))
        or {r.STATE, r.OUTPUT + "/run-summary.json"} & set(gate.get("files", {}))
    ):
        raise ValueError("complete independent resource-only continuation approval required")
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    _unchanged(root, pins)  # Hash the new closure before old science admission/proof loaders.
    _require(pins, json.loads((root / r.PILOT_REVIEW).read_text()).get("files"))
    old_gate, old_pins, jobs, parents = r._admit(root)
    _require(pins, old_pins)
    for key, path in [
        ("original_gate_sha256", r.GATE),
        ("original_plan_sha256", PLAN),
        ("pilot_review_sha256", r.PILOT_REVIEW),
    ]:
        if gate.get(key) != pins[path]:
            raise ValueError("literal original science/plan/pilot review binding required")
    snapshots = gate.get("old_ledger_snapshots")
    if not isinstance(snapshots, dict) or len(snapshots) != 12:
        raise ValueError("exact twelve Root-frozen old ledger snapshots required")
    _require(pins, snapshots)
    external = gate.get("external_reference_files")
    if (
        not isinstance(external, dict)
        or len(external) != 10
        or set(external) != set(external_reference_paths(root, parents))
    ):
        raise ValueError("exact ten outside-only historical NC reference files required")
    _require(pins, external)
    if sum(_path(root, p).stat().st_size for p in external) != EXTERNAL_BYTES:
        raise ValueError("immutable external reference byte total changed")
    baseline = json.loads((root / BASELINE).read_text())
    snapshot = _path(root, r.STATE).read_bytes()
    state = json.loads(snapshot)
    r._validate_state(baseline, jobs)
    r._validate_state(state, jobs)
    if (
        baseline["next_case"] != 2
        or state["next_case"] < 2
        or state["accepted"][:2] != baseline["accepted"]
        or state["attempts"][:2] != baseline["attempts"]
        or state.get("plan_sha256") != pins[PLAN]
        or baseline.get("plan_sha256") != pins[PLAN]
        or r._pilot_review(root, state) != pins[r.PILOT_REVIEW]
    ):
        raise ValueError("unchanged two-pilot baseline and successful no-reset prefix required")
    expected = {
        "files": old_pins,
        "jobs": jobs,
        "resources": r.resources(),
        "path_bindings": r.path_bindings(root),
        "parent_minimum_bytes": old_gate["parent_minimum_bytes"],
        "gate_sha256": old_pins[r.GATE],
    }
    if json.loads((root / PLAN).read_text()) != expected:
        raise ValueError("original immutable controller plan must remain byte-bound")
    r._inventory(root, state)
    _unchanged(root, pins)
    checked = {
        "gate": gate,
        "files": pins,
        "old_gate": old_gate,
        "old_pins": old_pins,
        "jobs": jobs,
        "parents": parents,
        "state": state,
        "snapshot": snapshot,
    }
    receipt_chain(root, checked)
    return checked


def quota_failure(root, parents, gate, current=None, *, reserve=False, working):
    """Original per-file/job/cache/floor checks; new caps and outside bytes only."""
    try:
        r.parent_floors(root, gate)
        roots = [root / r.DESIGN, root / r.OUTPUT, root / r.STORE]
        for base in counted_roots(root, parents):
            if base.is_symlink():
                return "symlink_storage"
        for base in roots:
            for path in base.rglob("*"):
                if path.is_symlink():
                    return "symlink_storage"
                try:
                    if path.is_file() and path.stat().st_size > r.FILE_MAX:
                        return "per_file_storage"
                except FileNotFoundError:
                    continue
        extra = r.RESERVE if reserve else 0
        if working(root, parents) + extra > GLOBAL_MAX:
            return "global_storage"
        if r.byte_count(*roots) + extra > LOCAL_MAX:
            return "local_storage"
        if r.byte_count(root / r.STORE / "cache") > r.MAX_CACHE:
            return "cache_storage"
        if current is not None:
            folder, raw, spec, log, process = r.case_paths(root, current)
            total = r.byte_count(folder) + sum(
                p.stat().st_size for p in [raw, spec, log, process] if p.is_file()
            )
            if total > r.MAX_JOB:
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


def parallel_proofs(root, state, jobs, pins):
    """Two readonly verifiers; every original proof and identity check is retained."""
    entries = list(
        zip(jobs[: state["next_case"]], state["accepted"], state["attempts"], strict=True)
    )

    def verify(entry):
        job, accepted, attempt = entry
        r.case_artifacts(root, job, pins, accepted)
        if any(
            attempt.get(k) != accepted.get(k)
            for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]
        ):
            raise ValueError("attempt and accepted case receipt identities changed")

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(verify, entry) for entry in entries]:
            future.result()


def _state_receipt(payload):
    state = json.loads(payload)
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        **{
            k: state[k]
            for k in ["status", "next_case", "calls_charged", "calls_started", "current"]
        },
    }


def _receipt_common(pins):
    return {
        "resource_gate": GATE,
        "resource_amendment_gate_sha256": pins[GATE],
        "original_plan_sha256": pins[PLAN],
        "original_gate_sha256": pins[r.GATE],
        "source_closure_sha256": hashlib.sha256(
            json.dumps(pins, sort_keys=True).encode()
        ).hexdigest(),
    }


def receipt_chain(root, checked):
    """Every earlier invocation must close and link the baseline to current state."""
    receipts = root / CONTROL / "receipts"
    if receipts.resolve() != receipts:
        raise ValueError("nonsymlink continuation receipt chain required")
    expected = _state_receipt(_path(root, BASELINE).read_bytes())
    previous_sha = None
    common = _receipt_common(checked["files"])
    for folder in sorted(receipts.iterdir()) if receipts.exists() else []:
        if (
            not folder.is_dir()
            or folder.is_symlink()
            or {p.name for p in folder.iterdir()} != {"before.json", "after.json"}
        ):
            raise ValueError("unclosed or failed continuation receipt chain needs review")
        paths = [
            _path(root, str((folder / name).relative_to(root)))
            for name in ["before.json", "after.json"]
        ]
        before, after = [json.loads(path.read_text()) for path in paths]
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or any(before.get(k) != v or after.get(k) != v for k, v in common.items())
            or before.get("state") != expected
            or after.get("before_state") != expected
            or folder.name != f"{expected['next_case']:03d}-{expected['sha256']}"
            or before.get("previous_after_receipt_sha256") != previous_sha
            or after.get("previous_after_receipt_sha256") != previous_sha
            or after.get("before_receipt_sha256") != sha256(paths[0])
            or before.get("invocation_git_sha") != after.get("invocation_git_sha")
            or after.get("controller_exception") is not None
            or after.get("postcondition_failure") is not None
            or not isinstance(after.get("after_state"), dict)
        ):
            raise ValueError("mismatched continuation receipt chain needs review")
        result = after["after_state"]
        count = result.get("next_case")
        if (
            type(count) is not int
            or not expected["next_case"] <= count <= min(55, expected["next_case"] + 4)
            or result.get("calls_charged") != count
            or result.get("calls_started") != count
            or result.get("current") is not None
            or result.get("status")
            != ("sensitivity_computations_complete" if count == 55 else "sensitivity_checkpoint")
            or not isinstance(result.get("sha256"), str)
            or len(result["sha256"]) != 64
        ):
            raise ValueError("unconserved continuation receipt chain needs review")
        expected, previous_sha = result, sha256(paths[1])
    if expected != _state_receipt(checked["snapshot"]):
        raise ValueError("unclosed or mismatched continuation receipt chain before current prefix")
    return previous_sha


def _failed(root, reason):
    state = json.loads((root / r.STATE).read_text())
    state["status"] = "sensitivity_needs_review"
    state.pop("final_summary_sha256", None)
    r.atomic_state(root / r.STATE, state)
    stop = root / r.OUTPUT / "STOP"
    try:
        with stop.open("x") as stream:
            stream.write(reason + "\n")
    except FileExistsError:
        pass


@contextmanager
def overrides(root, checked):
    """Process-local bindings restored even on errors; original exclusive PG run remains."""
    if not _OVERRIDE_LOCK.acquire(blocking=False):
        raise ValueError("one process-local continuation override context required")
    names = ["working_bytes", "quota_failure", "supervise", "_proofs", "_unchanged", "_leases"]
    saved = {name: getattr(r, name) for name in names}
    pins = checked["files"]
    extra_pins = {p: h for p, h in pins.items() if p not in checked["old_pins"]}
    identity = pins[GATE]

    def working(root, parents):
        actual = sum(
            _path(root, p).stat().st_size for p in checked["gate"]["external_reference_files"]
        )
        if actual != EXTERNAL_BYTES:
            raise ValueError("immutable external reference byte total changed")
        return saved["working_bytes"](root, parents) + actual

    def quota(root, parents, gate, current=None, *, reserve=False):
        return quota_failure(root, parents, gate, current, reserve=reserve, working=working)

    def unchanged(root, old):
        saved["_unchanged"](root, old)
        _unchanged(root, extra_pins)

    def supervise(*args, **kwargs):
        _unchanged(root, pins)  # Immediate pre-child check; old precharge is never refunded.
        return {**saved["supervise"](*args, **kwargs), "resource_amendment_gate_sha256": identity}

    @contextmanager
    def leases(root):
        with saved["_leases"](root):
            _unchanged(root, pins)  # No receipt/write under a source identity that became stale.
            before = (root / r.STATE).read_bytes()
            if before != checked["snapshot"]:
                raise ValueError("private state changed before continuation lease admission")
            previous_sha = receipt_chain(root, checked)
            name = f"{checked['state']['next_case']:03d}-{hashlib.sha256(before).hexdigest()}"
            folder = root / CONTROL / "receipts" / name
            if folder.resolve() != folder or folder.exists() or folder.is_symlink():
                raise ValueError(
                    "existing continuation receipt; ambiguous/repeated invocation needs review"
                )
            common = {
                **_receipt_common(pins),
                "invocation_git_sha": git_sha(root),
                "previous_after_receipt_sha256": previous_sha,
            }
            r.new_json(folder / "before.json", {**common, "state": _state_receipt(before)})
            error = None
            try:
                yield
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                post_error = None
                try:
                    _unchanged(root, pins)
                    post_error = quota(root, checked["parents"], checked["old_gate"])
                except Exception as exc:
                    post_error = str(exc)
                if post_error:
                    _failed(root, post_error)
                after = (root / r.STATE).read_bytes()
                r.new_json(
                    folder / "after.json",
                    {
                        **common,
                        "before_state": _state_receipt(before),
                        "before_receipt_sha256": sha256(folder / "before.json"),
                        "after_state": _state_receipt(after),
                        "controller_exception": error,
                        "postcondition_failure": post_error,
                    },
                )
                late = quota(root, checked["parents"], checked["old_gate"])
                if late:
                    _failed(root, late)
                    r.new_json(
                        folder / "failure.json",
                        {"reason": late, "state": _state_receipt((root / r.STATE).read_bytes())},
                    )
                if error is None and (post_error or late):
                    raise ValueError("continuation source/storage postcondition failed")

    try:
        r.working_bytes, r.quota_failure, r.supervise = working, quota, supervise
        r._proofs, r._unchanged, r._leases = parallel_proofs, unchanged, leases
        yield
    finally:
        for name, value in saved.items():
            setattr(r, name, value)
        _OVERRIDE_LOCK.release()


def storage_projection(root, checked):
    """Planning estimate only: larger pilot×1.5, all remaining cache growth and reserve."""
    footprints = []
    for job in checked["jobs"][:2]:
        folder, *files = r.case_paths(root, job)
        footprints.append(
            r.byte_count(folder) + sum(p.stat().st_size for p in files if p.is_file())
        )
    cache_growth = max(0, r.MAX_CACHE - r.byte_count(root / r.STORE / "cache"))
    remaining = 55 - checked["state"]["next_case"]
    projected = math.ceil(1.5 * max(footprints)) * remaining + cache_growth + r.RESERVE
    local = r.byte_count(root / r.DESIGN, root / r.OUTPUT, root / r.STORE)
    working = r.working_bytes(root, checked["parents"]) + EXTERNAL_BYTES
    return {
        "planning_not_completion_guarantee": True,
        "pilot_job_bytes": footprints,
        "remaining_cases": remaining,
        "outside_reference_bytes": EXTERNAL_BYTES,
        "future_job_cache_reserve_bytes": projected,
        "projected_global_bytes": working + projected,
        "projected_local_bytes": local + projected,
        "hard_job_envelope_plus_reserve_bytes": remaining * r.MAX_JOB + r.RESERVE,
    }


def run(root, *, max_cases=4):
    if type(max_cases) is not int or not 1 <= max_cases <= 4:
        raise ValueError("continuation batches require1to4cases")
    root = root.resolve()
    checked = verify_continuation(root)
    with overrides(root, checked):
        r.run(root, resume=True, max_cases=max_cases)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-cases", type=int, default=4)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], max_cases=args.max_cases)
