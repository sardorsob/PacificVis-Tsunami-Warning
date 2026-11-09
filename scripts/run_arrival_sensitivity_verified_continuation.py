"""Process-only reuse of fully verified MS-5 proofs, with fresh bytes every pass."""

# pyright: basic
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_arrival_sensitivity_continuation as c  # noqa: E402

r = c.r
SELF = "scripts/run_arrival_sensitivity_verified_continuation.py"
TEST = "tests/test_run_arrival_sensitivity_verified_continuation.py"
PERFORMANCE_GATE = r.DESIGN + "/proof-continuation-v1/review-acceptance.json"
CONTROL = c.CONTROL + "/proof-continuation-v1"
BASELINE = CONTROL + "/baseline-state.json"
CONTRACT = {
    "scope": "one_foreground_process_only",
    "proof_cache": "successful_full_verification_metadata_only",
    "scientific_arrays_cached": False,
    "persistent_cache": False,
    "mtime_or_size_identity": False,
    "source_hash_cache": False,
    "every_dispatch_original_verifier": True,
    "every_prefix_fresh_sources_inventory_files_receipt_start_and_end": True,
    "pending_requires_complete_accepted_branch": True,
}
_LOCK = threading.Lock()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def merge(*maps):
    result = {}
    for values in maps:
        if any(p in result and result[p] != h for p, h in values.items()):
            raise ValueError("proof source identity conflict")
        result.update(values)
    return result


def verify_gate(root):
    gate = json.loads(c._path(root, PERFORMANCE_GATE).read_text())
    if (
        gate.get("status") != "accepted_sensitivity_in_memory_proof_reuse"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("resources") != c.resources()
        or gate.get("path_bindings") != r.path_bindings(root)
        or gate.get("proof_contract") != CONTRACT
        or not {SELF, TEST, BASELINE, c.GATE, r.GATE, c.PLAN} <= set(gate.get("files", {}))
        or {r.STATE, r.OUTPUT + "/run-summary.json"} & set(gate.get("files", {}))
    ):
        raise ValueError("complete independent process-only proof-reuse Gate required")
    pins = {**gate["files"], PERFORMANCE_GATE: c.sha256(root / PERFORMANCE_GATE)}
    c._unchanged(root, pins)
    resource = c.verify_continuation(root)
    c._require(pins, resource["files"])
    for key, path in [
        ("original_science_gate_sha256", r.GATE),
        ("resource_gate_sha256", c.GATE),
        ("original_plan_sha256", c.PLAN),
    ]:
        if gate.get(key) != pins[path]:
            raise ValueError("unchanged science/resource Gate and original plan required")
    baseline = json.loads((root / BASELINE).read_text())
    r._validate_state(baseline, resource["jobs"])
    state = resource["state"]
    n = baseline["next_case"]
    if (
        n < 6
        or state["next_case"] < n
        or state["accepted"][:n] != baseline["accepted"]
        or state["attempts"][:n] != baseline["attempts"]
        or baseline["plan_sha256"] != pins[c.PLAN]
    ):
        raise ValueError("immutable accepted baseline and conserved subsequent prefix required")
    for entry in baseline["accepted"]:
        c._require(pins, {**entry["files"], entry["receipt"]: entry["receipt_sha256"]})
    c._unchanged(root, pins)
    return {"gate": gate, "files": pins, "resource": resource}


class ProofCache:
    """Metadata from full verifications; every reused proof rechecks all byte identities."""

    def __init__(self, root, checked, original, source_checker):
        self.root, self.checked, self.original = root, checked, original
        self.source_checker = source_checker
        self.old_pins = copy.deepcopy(checked["resource"]["old_pins"])
        self.jobs = {j["id"]: canonical(j) for j in checked["resource"]["jobs"]}
        self.pending, self.accepted = {}, {}
        self.lock = threading.RLock()
        self.counts = {
            "full_proofs": 0,
            "pending_captures": 0,
            "pending_promotions": 0,
            "warm_checks": 0,
        }
        self.working = r.working_bytes
        self.expected_state_sha256 = hashlib.sha256(checked["resource"]["snapshot"]).hexdigest()

    def clear(self):
        with self.lock:
            self.pending.clear()
            self.accepted.clear()

    def sources(self):
        self.source_checker(self.root, self.checked["files"])

    def runtime(self):
        if any(
            (self.root / p).exists() or (self.root / p).is_symlink()
            for p in [r.OUTPUT + "/STOP", r.OLD_OUTPUT + "/STOP"]
        ):
            raise ValueError("STOP prevents proof promotion or reuse")
        checked = self.checked["resource"]

        def working(root, parents):
            return self.working(root, parents) + sum(
                c._path(root, p).stat().st_size for p in checked["gate"]["external_reference_files"]
            )

        if c.quota_failure(self.root, checked["parents"], checked["old_gate"], working=working):
            raise ValueError("resource failure prevents proof promotion or reuse")

    def guard(self, job, pins):
        if canonical(pins) != canonical(self.old_pins) or self.jobs.get(job["id"]) != canonical(
            job
        ):
            raise ValueError("job or original source pin identity changed; no cache migration")

    def inventory(self, job):
        folder, raw, spec, log, process = r.case_paths(self.root, job)
        manifest = folder / "attempt-evidence.json"
        mandatory = [
            folder / p
            for p in [
                "job.json",
                "inputs.json",
                "membership.json",
                "sampling-start.json",
                "result.json",
                "diagnostics.json",
                "sampling-diagnostics.csv",
                "summary.json",
                "parameters.csv",
                "derived.csv",
                "curves.csv",
                "conditional-ppc.csv",
                "record-intervals.csv",
            ]
        ] + [raw, spec, log, process]
        directories, files = [], set(mandatory)
        if folder.resolve() != folder or not folder.is_dir():
            raise ValueError("literal complete case directory required")
        for path in folder.rglob("*"):
            if path.resolve() != path or path.is_symlink():
                raise ValueError("case symlink is not admitted")
            if path.is_dir():
                directories.append(str(path.relative_to(self.root)))
            elif path.is_file() and path != manifest:
                files.add(path)
        values = {
            str(path.relative_to(self.root)): c.sha256(
                c._path(self.root, str(path.relative_to(self.root)))
            )
            for path in files
        }
        return values, sorted(directories), manifest

    def branch(self, job, accepted, snapshot):
        files, directories, manifest = self.inventory(job)
        if files != snapshot["files"] or directories != snapshot["directories"]:
            raise ValueError("complete case inventory or file SHA changed")
        if (
            accepted.get("case_id") != job["id"]
            or accepted.get("charged_slots") != 1
            or accepted.get("files") != files
            or accepted.get("receipt") != str(manifest.relative_to(self.root))
            or accepted.get("receipt_sha256") != c.sha256(c._path(self.root, accepted["receipt"]))
            or json.loads(manifest.read_text()) != {"case_id": job["id"], "files": files}
        ):
            raise ValueError("complete original accepted receipt branch required")
        return canonical(
            {"job": job, "accepted": accepted, "receipt": str(manifest), "old_pins": self.old_pins}
        )

    def capture(self, *args, **kwargs):
        # Unconditional identical delegation, including dispatch calls with accepted=None.
        result = self.original(*args, **kwargs)
        root = args[0] if args else kwargs["root"]
        job = args[1] if len(args) > 1 else kwargs["job"]
        pins = args[2] if len(args) > 2 else kwargs["pins"]
        accepted = args[3] if len(args) > 3 else kwargs.get("accepted")
        if root.resolve() != self.root:
            raise ValueError("one canonical proof-cache project required")
        self.guard(job, pins)
        files, directories, manifest = self.inventory(job)
        if result[0] != files or result[1] != manifest:
            raise ValueError("original verifier result and fresh complete inventory differ")
        snapshot = {
            "files": copy.deepcopy(files),
            "directories": directories,
            "job": canonical(job),
            "old_pins": canonical(pins),
        }
        with self.lock:
            self.counts["full_proofs"] += 1
            if accepted is None:
                self.pending[job["id"]] = snapshot
                self.counts["pending_captures"] += 1
            else:
                key = self.branch(job, accepted, snapshot)
                snapshot["key"] = key
                previous = self.accepted.get(job["id"])
                if previous is not None and previous["key"] != key:
                    raise ValueError("accepted cache identity changed")
                if previous is not None and "attempt" in previous:
                    snapshot["attempt"] = previous["attempt"]
                self.accepted[job["id"]] = snapshot
        return result  # EXACT original tuple object, not a reconstructed return value.

    def one(self, job, accepted, attempt, pins):
        self.guard(job, pins)
        if any(
            attempt.get(k) != accepted.get(k)
            for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]
        ):
            raise ValueError("attempt and accepted identity changed")
        name = job["id"]
        with self.lock:
            cached = copy.deepcopy(self.accepted.get(name))
            pending = copy.deepcopy(self.pending.get(name))
        if cached is None and pending is None:
            self.capture(self.root, job, pins, accepted)
            with self.lock:
                cached = copy.deepcopy(self.accepted[name])
        candidate = cached if cached is not None else pending
        if candidate is None:
            raise ValueError("successful full proof capture required")
        key = self.branch(job, accepted, candidate)
        if candidate.get("attempt") not in {None, canonical(attempt)}:
            raise ValueError("attempt identity changed")
        candidate["attempt"] = canonical(attempt)
        if cached is not None and cached["key"] != key:
            raise ValueError("accepted proof identity changed; no cache migration")
        # Second complete fresh scan closes mutations during the first readback.
        if self.branch(job, accepted, candidate) != key:
            raise ValueError("case receipt changed during proof readback")
        return name, candidate, key, cached is None

    def proofs(self, root, state, jobs, pins):
        if root.resolve() != self.root or canonical(jobs) != canonical(
            self.checked["resource"]["jobs"]
        ):
            raise ValueError("exact full ordered jobs required")
        self.sources()
        self.runtime()
        r._validate_state(state, jobs)
        r._inventory(root, state)
        entries = list(
            zip(jobs[: state["next_case"]], state["accepted"], state["attempts"], strict=True)
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.one, job, accepted, attempt, pins)
                for job, accepted, attempt in entries
            ]
            results = [future.result() for future in futures]
        self.sources()
        self.runtime()
        r._inventory(root, state)
        with self.lock:
            for name, candidate, key, promoted in results:
                candidate["key"] = key
                self.accepted[name] = candidate
                if promoted:
                    self.pending.pop(name, None)
                    self.counts["pending_promotions"] += 1
                else:
                    self.counts["warm_checks"] += 1


@contextmanager
def session(root, checked):
    if not _LOCK.acquire(blocking=False):
        raise ValueError("one foreground proof-reuse session required")
    saved = {
        "case_artifacts": r.case_artifacts,
        "source": r._unchanged,
        "supervise": r.supervise,
        "proofs": c.parallel_proofs,
        "checker": c._unchanged,
        "leases": r._leases,
    }
    extra = {p: h for p, h in checked["files"].items() if p not in checked["resource"]["files"]}
    cache = ProofCache(root, checked, saved["case_artifacts"], saved["checker"])

    def checker(root, pins):
        saved["checker"](root, merge(pins, extra))

    def supervisor(*args, **kwargs):
        return {
            **saved["supervise"](*args, **kwargs),
            "performance_gate_sha256": checked["files"][PERFORMANCE_GATE],
        }

    @contextmanager
    def leases(root):
        with saved["leases"](root):
            if c.sha256(root / r.STATE) != cache.expected_state_sha256:
                raise ValueError("foreign STATE change before performance lease admission")
            yield

    try:
        r.case_artifacts, r._unchanged, r.supervise = cache.capture, saved["checker"], supervisor
        c.parallel_proofs, c._unchanged = cache.proofs, checker
        r._leases = leases
        yield cache
    finally:
        r.case_artifacts, r._unchanged, r.supervise = (
            saved["case_artifacts"],
            saved["source"],
            saved["supervise"],
        )
        c.parallel_proofs, c._unchanged = saved["proofs"], saved["checker"]
        r._leases = saved["leases"]
        cache.clear()
        _LOCK.release()


def own_closed_state(root, before, resource):
    """Advance ownership only from this invocation's closed old resource receipt."""
    after = (root / r.STATE).read_bytes()
    state = json.loads(after)
    r._validate_state(state, resource["jobs"])
    if state["status"] not in {"sensitivity_checkpoint", "sensitivity_computations_complete"}:
        raise ValueError("inner controller did not return a successful closed checkpoint")
    start = c._state_receipt(before)
    if start["next_case"] == 55:
        if after != before:
            raise ValueError("foreign STATE change during completed readback")
        return after
    folder = root / c.CONTROL / "receipts" / f"{start['next_case']:03d}-{start['sha256']}"
    path = c._path(root, str((folder / "after.json").relative_to(root)))
    receipt = json.loads(path.read_text())
    if (
        receipt.get("before_state") != start
        or receipt.get("after_state") != c._state_receipt(after)
        or receipt.get("controller_exception") is not None
        or receipt.get("postcondition_failure") is not None
        or not start["next_case"] < state["next_case"] <= min(55, start["next_case"] + 4)
        or c.receipt_chain(root, {**resource, "snapshot": after, "state": state}) != c.sha256(path)
    ):
        raise ValueError("foreign STATE or missing OWN closed resource receipt")
    return after


def failure_evidence(root, folder, cache, reason, owned_after_sha):
    """Never overwrite a foreign precharge/checkpoint while handling an outer failure."""
    marked, ownership_error = False, None
    try:
        if owned_after_sha is None:
            raise ValueError("no successful OWN closed checkpoint to mutate")
        with r._leases(root):
            if c.sha256(root / r.STATE) != owned_after_sha:
                raise ValueError("foreign STATE before failure handling")
            c._failed(root, reason)
            marked = True
    except Exception as exc:
        ownership_error = str(exc)
    try:
        with (root / r.OUTPUT / "STOP").open("x") as stream:
            stream.write(reason + "\n")
    except FileExistsError:
        pass
    r.new_json(
        folder / "failure.json",
        {
            "reason": reason,
            "canonical_state_marked": marked,
            "ownership_error": ownership_error,
            "expected_owned_after_sha256": owned_after_sha,
        },
    )


def run(root, *, invocations=1, pause_between_batches=False):
    if (
        type(invocations) is not int
        or not 1 <= invocations <= 14
        or invocations > 1
        and not pause_between_batches
    ):
        raise ValueError("1..14 invocations; multiple batches require explicit pause flag")
    root = root.resolve()
    checked = verify_gate(root)
    with session(root, checked) as cache:
        for number in range(invocations):
            resource = c.verify_continuation(root)
            cache.sources()
            before = (root / r.STATE).read_bytes()
            if (
                hashlib.sha256(resource["snapshot"]).hexdigest() != cache.expected_state_sha256
                or hashlib.sha256(before).hexdigest() != cache.expected_state_sha256
            ):
                raise ValueError("foreign STATE checkpoint before outer invocation")
            folder = (
                root
                / CONTROL
                / "sessions"
                / f"{resource['state']['next_case']:03d}-{hashlib.sha256(before).hexdigest()}"
            )
            if folder.exists() or folder.resolve() != folder:
                raise ValueError("existing/ambiguous outer performance invocation needs review")
            common = {
                "performance_gate_sha256": checked["files"][PERFORMANCE_GATE],
                "source_closure_sha256": digest(checked["files"]),
                "invocation_git_sha": c.git_sha(root),
            }
            r.new_json(
                folder / "before.json",
                {**common, "state": c._state_receipt(before), "cache_counts": dict(cache.counts)},
            )
            error, owned_after_sha = None, None
            try:
                c.run(root, max_cases=4)
                after = own_closed_state(root, before, resource)
                owned_after_sha = hashlib.sha256(after).hexdigest()
                cache.expected_state_sha256 = owned_after_sha
                cache.sources()
                cache.runtime()
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                try:
                    observed = (root / r.STATE).read_bytes()
                    r.new_json(
                        folder / "after.json",
                        {
                            **common,
                            "before_state": c._state_receipt(before),
                            "after_state": c._state_receipt(observed),
                            "exception": error,
                            "expected_owned_after_sha256": owned_after_sha,
                            "cache_counts": dict(cache.counts),
                        },
                    )
                    cache.sources()
                    cache.runtime()
                except Exception as exc:
                    failure_evidence(root, folder, cache, str(exc), owned_after_sha)
                    if error is None:
                        raise
            if json.loads(after)["next_case"] == 55 or number + 1 == invocations:
                break
            if input("Closed batch; enter ACK after review to continue: ") not in {"", "ACK"}:
                raise ValueError("explicit newline/ACK checkpoint required")
            if c.sha256(root / r.STATE) != cache.expected_state_sha256:
                raise ValueError("foreign STATE change while paused; stop without automatic resume")
            cache.sources()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invocations", type=int, default=1)
    parser.add_argument("--pause-between-batches", action="store_true")
    args = parser.parse_args()
    run(
        Path(__file__).resolve().parents[1],
        invocations=args.invocations,
        pause_between_batches=args.pause_between_batches,
    )
