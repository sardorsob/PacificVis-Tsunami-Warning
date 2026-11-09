"""One reviewed repair and the unchanged remaining MS5 jobs, without rewriting history."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivity_continuation as c  # noqa: E402
from scripts import run_arrival_sensitivity_verified_continuation as p  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

r = c.r
SELF, TEST = (
    "scripts/run_arrival_sensitivity_completion.py",
    "tests/test_run_arrival_sensitivity_completion.py",
)
GATE, OUTPUT = r.DESIGN + "/completion-v1/review-acceptance.json", r.OUTPUT + "/completion-v1"
BASELINE, PLAN = OUTPUT + "/baseline-state.json", OUTPUT + "/plan.json"
COMPLETION_SUMMARY = OUTPUT + "/run-summary.json"
COMPLETION_FAILURE = OUTPUT + "/completion-failure.json"
REPAIR_OUTPUT, REPAIR_STORE = (
    r.OUTPUT + "/numerical-repair-v1",
    "data/processed/models/arrival-sensitivity-repair-v1",
)
REPAIR_GATE = r.DESIGN + "/numerical-repair-v1/review-acceptance.json"
REPAIR_BASELINE, REPAIR_REVIEW = (
    REPAIR_OUTPUT + "/baseline-state.json",
    REPAIR_OUTPUT + "/review-acceptance.json",
)
FAILURE_REVIEW = REPAIR_OUTPUT + "/diagnostic-stop-review.json"
PREFIX_REVIEW = r.OUTPUT + "/batch-034-review-acceptance.json"
REPAIR_SOURCE, REPAIR_CLI = (
    "analysis/arrival/model_sensitivity_repair.py",
    "scripts/fit_arrival_sensitivity_repair.py",
)
REPAIR_TEST = "tests/test_arrival_model_sensitivity_repair.py"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(root, name):
    return json.loads(c._path(root, name).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def repair_api() -> Any:
    return importlib.import_module("analysis.arrival.model_sensitivity_repair")


def resources():
    # Tune and target_accept differ only in the separately frozen repair job.
    return {k: v for k, v in c.resources().items() if k not in {"initial_cases", "tune"}}


def bindings(root):
    return dict(
        project_root=str(root.resolve()),
        state=str(root.resolve() / r.STATE),
        original_output=r.OUTPUT,
        original_store=r.STORE,
        output=OUTPUT,
        repair_output=REPAIR_OUTPUT,
        repair_store=REPAIR_STORE,
    )


def case_paths(root, checked, kind, job):
    if kind == "original":
        return r.case_paths(root, job)
    require(kind == "repair" and job == checked["repair_job"], "one literal repair job required")
    folder, raw = checked["repair_api"].case_paths(root, job)
    require(
        folder == root / REPAIR_OUTPUT / "jobs" / job["id"]
        and raw == root / REPAIR_STORE / (job["id"] + ".nc"),
        "fixed separate repair paths required",
    )
    return (
        folder,
        raw,
        folder.with_name(folder.name + "-spec.json"),
        folder.with_name(folder.name + ".log"),
        folder.with_name(folder.name + ".supervisor.json"),
    )


def history(root, checked):
    """Verify frozen old receipts, including the explicit final failed invocation."""
    pins, baseline = checked["files"], checked["baseline"]
    expected = c._state_receipt(c._path(root, c.BASELINE).read_bytes())
    common = c._receipt_common(checked["resource_pins"])
    previous_sha, resource = None, []
    names = {c.BASELINE, p.BASELINE}
    for folder in sorted((root / c.CONTROL / "receipts").iterdir()):
        require(
            folder.resolve() == folder
            and folder.is_dir()
            and {q.name for q in folder.iterdir()} <= {"before.json", "after.json", "failure.json"},
            "literal frozen resource history required",
        )
        before_name, after_name = [
            str((folder / leaf).relative_to(root)) for leaf in ["before.json", "after.json"]
        ]
        before, after = read(root, before_name), read(root, after_name)
        require(
            all(before.get(k) == v and after.get(k) == v for k, v in common.items())
            and before.get("state") == after.get("before_state") == expected
            and folder.name == f"{expected['next_case']:03d}-{expected['sha256']}"
            and before.get("previous_after_receipt_sha256")
            == after.get("previous_after_receipt_sha256")
            == previous_sha
            and after.get("before_receipt_sha256") == sha256(root / before_name)
            and before.get("invocation_git_sha") == after.get("invocation_git_sha"),
            "old resource receipt chain identity changed",
        )
        require(
            after.get("postcondition_failure") is None,
            "old runtime postcondition failure needs separate review",
        )
        last = after.get("after_state") == c._state_receipt(c._path(root, BASELINE).read_bytes())
        result = after["after_state"]
        if last:
            require(
                expected["next_case"] == 34
                and result["next_case"] == 34
                and result["calls_charged"] == result["calls_started"] == 35,
                "one retained failed call after the34-case checkpoint required",
            )
        else:
            require(
                after.get("controller_exception") is None
                and after.get("postcondition_failure") is None
                and expected["next_case"] < result["next_case"] <= expected["next_case"] + 4
                and result["calls_charged"] == result["calls_started"] == result["next_case"]
                and result["current"] is None,
                "successful old resource prefix required",
            )
        resource.append(after)
        names.update(str(q.relative_to(root)) for q in folder.iterdir())
        expected, previous_sha = result, sha256(root / after_name)
    require(
        expected == c._state_receipt(c._path(root, BASELINE).read_bytes()),
        "old resource history must end at failed35 baseline",
    )
    expected = c._state_receipt(c._path(root, p.BASELINE).read_bytes())
    common = {
        "performance_gate_sha256": pins[p.PERFORMANCE_GATE],
        "source_closure_sha256": p.digest(checked["performance_pins"]),
    }
    for folder in sorted((root / p.CONTROL / "sessions").iterdir()):
        require(
            folder.resolve() == folder
            and folder.is_dir()
            and {q.name for q in folder.iterdir()} <= {"before.json", "after.json", "failure.json"},
            "literal frozen performance history required",
        )
        before, after = [
            read(root, str((folder / leaf).relative_to(root)))
            for leaf in ["before.json", "after.json"]
        ]
        matches = [v for v in resource if v["before_state"] == expected]
        require(
            len(matches) == 1
            and before.get("state") == after.get("before_state") == expected
            and folder.name == f"{expected['next_case']:03d}-{expected['sha256']}"
            and all(before.get(k) == v and after.get(k) == v for k, v in common.items())
            and before.get("invocation_git_sha")
            == after.get("invocation_git_sha")
            == matches[0]["invocation_git_sha"]
            and after.get("after_state") == matches[0]["after_state"],
            "old performance/source/ownership chain changed",
        )
        failed = after["after_state"] == c._state_receipt(c._path(root, BASELINE).read_bytes())
        require(
            (
                failed
                and after.get("exception") is not None
                and after.get("expected_owned_after_sha256") is None
            )
            or (
                not failed
                and after.get("exception") is None
                and after.get("expected_owned_after_sha256") == after["after_state"]["sha256"]
            ),
            "original successful prefix and terminal failure must remain explicit",
        )
        names.update(str(q.relative_to(root)) for q in folder.iterdir())
        expected = after["after_state"]
    require(
        expected == c._state_receipt(c._path(root, BASELINE).read_bytes()),
        "performance history must end at failed35 baseline",
    )
    require(
        set(checked["gate"]["history_files"]) == names,
        "exact complete frozen old history inventory required",
    )
    c._require(pins, checked["gate"]["history_files"])
    require(baseline["attempts"][-1]["outcome"] != "accepted", "failed attempt must remain failed")


def verify_gate(root):
    root = root.resolve()
    gate = read(root, GATE)
    needed = {
        SELF,
        TEST,
        REPAIR_SOURCE,
        REPAIR_CLI,
        REPAIR_TEST,
        BASELINE,
        REPAIR_BASELINE,
        r.GATE,
        c.GATE,
        p.PERFORMANCE_GATE,
        c.PLAN,
        r.PILOT_REVIEW,
        PREFIX_REVIEW,
        FAILURE_REVIEW,
        REPAIR_GATE,
    }
    require(
        gate.get("status") == "accepted_sensitivity_failed_case_completion_execution"
        and gate.get("independent_checker") is True
        and gate.get("confirmation_outcomes_parsed") is False
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("resources") == resources()
        and gate.get("path_bindings") == bindings(root)
        and gate.get("max_sampler_call_slots") == 110
        and type(gate["max_sampler_call_slots"]) is int
        and needed <= set(gate.get("files", {}))
        and r.STATE not in gate["files"],
        "independent complete bounded completion Gate required before loading",
    )
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    c._unchanged(root, pins)
    science, original_pins, jobs, parents = r._admit(root)  # Does not read private STATE.
    c._require(pins, original_pins)
    require(
        len(jobs) == 55
        and gate.get("remaining_jobs") == jobs[35:]
        and gate.get("parent_minimum_bytes") == science["parent_minimum_bytes"],
        "unchanged55-job plan and floors required",
    )
    plan = read(root, c.PLAN)
    require(
        plan
        == {
            "files": original_pins,
            "jobs": jobs,
            "resources": r.resources(),
            "path_bindings": r.path_bindings(root),
            "parent_minimum_bytes": science["parent_minimum_bytes"],
            "gate_sha256": original_pins[r.GATE],
        },
        "original plan must stay unchanged",
    )
    resource, performance = read(root, c.GATE), read(root, p.PERFORMANCE_GATE)
    for value, status in [
        (resource, "accepted_exploration_sensitivity_resource_continuation"),
        (performance, "accepted_sensitivity_in_memory_proof_reuse"),
    ]:
        require(
            value.get("status") == status
            and value.get("independent_checker") is True
            and value.get("confirmation_outcomes_parsed") is False
            and value.get("reserved_outcomes") == "sealed"
            and value.get("resources") == c.resources()
            and value.get("path_bindings") == r.path_bindings(root),
            "unchanged accepted old runtime Gates required",
        )
        c._require(pins, value.get("files"))
    resource_pins = {**resource["files"], c.GATE: pins[c.GATE]}
    performance_pins = {**performance["files"], p.PERFORMANCE_GATE: pins[p.PERFORMANCE_GATE]}
    require(
        {
            c.SELF,
            c.TEST,
            "analysis/arrival/model_sensitivity_references.py",
            r.GATE,
            c.PLAN,
            r.PILOT_REVIEW,
            c.BASELINE,
            c.PROJECTION,
            *r.RUNTIME,
        }
        <= set(resource["files"])
        and {p.SELF, p.TEST, p.BASELINE, c.GATE, r.GATE, c.PLAN} <= set(performance["files"]),
        "complete frozen old runtime source/metadata prerequisites required",
    )
    require(
        len(resource.get("old_ledger_snapshots", {})) == 12,
        "all twelve frozen older ledgers required",
    )
    c._require(pins, resource["old_ledger_snapshots"])
    require(
        performance.get("proof_contract") == p.CONTRACT, "unchanged old proof contract required"
    )
    for field, name in [
        ("original_science_gate_sha256", r.GATE),
        ("resource_gate_sha256", c.GATE),
        ("original_plan_sha256", c.PLAN),
    ]:
        require(performance.get(field) == pins[name], "old performance Gate binding changed")
    for field, name in [
        ("original_gate_sha256", r.GATE),
        ("original_plan_sha256", c.PLAN),
        ("pilot_review_sha256", r.PILOT_REVIEW),
    ]:
        require(resource.get(field) == pins[name], "old resource Gate binding changed")
    baseline = read(root, BASELINE)
    require(
        sha256(root / BASELINE)
        == sha256(root / REPAIR_BASELINE)
        == gate.get("original_baseline_sha256")
        and gate.get("baseline_state") == BASELINE
        and gate.get("repair_baseline_state") == REPAIR_BASELINE
        and baseline.get("status") == "sensitivity_needs_review"
        and baseline.get("current") is None
        and baseline.get("next_case") == len(baseline.get("accepted", [])) == 34
        and baseline.get("calls_charged")
        == baseline.get("calls_started")
        == len(baseline.get("attempts", []))
        == 35
        and baseline.get("plan_sha256") == pins[c.PLAN],
        "literal failed35 baseline copies required",
    )
    for j, (job, attempt) in enumerate(zip(jobs[:35], baseline["attempts"], strict=True)):
        require(
            attempt.get("case_id") == job["id"]
            and attempt.get("charged_slots") == attempt.get("start_markers") == 1
            and (attempt.get("outcome") == "accepted") == (j < 34),
            "original failed call accounting must remain explicit",
        )
        if j < 34:
            entry = baseline["accepted"][j]
            require(
                all(
                    attempt.get(k) == entry.get(k)
                    for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]
                ),
                "unchanged34 accepted entries required",
            )
            c._require(pins, {**entry["files"], entry["receipt"]: entry["receipt_sha256"]})
    require(
        r._pilot_review(root, baseline)
        == baseline.get("pilot_review_sha256")
        == pins[r.PILOT_REVIEW],
        "same closed original two-pilot review required",
    )
    prefix, failure = read(root, PREFIX_REVIEW), read(root, FAILURE_REVIEW)
    for value, status in [
        (prefix, "accepted_sensitivity_thirty_four_case_checkpoint"),
        (failure, "accepted_sensitivity_same_case_numerical_repair_plan"),
    ]:
        require(
            value.get("status") == status
            and value.get("independent_checker") is True
            and value.get("confirmation_outcomes_parsed") is False
            and value.get("reserved_outcomes") == "sealed",
            "independently reviewed34 prefix and diagnostic stop required",
        )
        c._require(pins, value.get("files"))
    require(
        prefix.get("accepted_total_cases") == 34
        and prefix.get("original_plan_sha256") == pins[c.PLAN]
        and failure.get("original_job") == jobs[34]
        and failure.get("baseline_state_sha256") == pins[BASELINE],
        "same34 prefix and exact failed original case required",
    )
    for field, name in [
        ("original_plan_sha256", c.PLAN),
        ("original_science_gate_sha256", r.GATE),
        ("resource_gate_sha256", c.GATE),
        ("performance_gate_sha256", p.PERFORMANCE_GATE),
    ]:
        require(
            gate.get(field) == pins[name] and prefix.get(field) == pins[name],
            "completion/prefix Gate bindings changed",
        )
    require(
        gate.get("prefix_review") == PREFIX_REVIEW
        and gate.get("failure_review") == FAILURE_REVIEW
        and gate.get("repair_gate") == REPAIR_GATE,
        "literal review and repair Gate paths required",
    )
    external = gate.get("external_reference_files", {})
    require(
        set(external) == set(c.external_reference_paths(root, parents)),
        "exact ten outside-only NC references required",
    )
    c._require(pins, external)
    c._require(pins, gate.get("failed_files"))
    api = repair_api()  # Only after all Gate/source pins passed.
    repair_admission = api.verify_gate(root)
    c._require(pins, repair_admission["files"])
    require(
        repair_admission["original_admission"]["files"] == original_pins
        and repair_admission["original_job"] == jobs[34]
        and repair_admission["job"] == gate.get("repair_job"),
        "exact separately reviewed repair job required",
    )
    checked = dict(
        root=root,
        gate=gate,
        files=pins,
        baseline=baseline,
        jobs=jobs,
        old_pins=original_pins,
        parents=parents,
        repair_api=api,
        repair_admission=repair_admission,
        repair_job=gate["repair_job"],
        resource_pins=resource_pins,
        performance_pins=performance_pins,
        initial_files=dict(pins),
    )
    history(root, checked)
    failed = baseline["attempts"][-1]
    c._require(pins, read(root, failed["receipt"]).get("files"))
    require(
        pins.get(failed["receipt"]) == failed["receipt_sha256"],
        "retained failed attempt receipt identity required",
    )
    c._unchanged(root, pins)
    return checked


def physical(root, paths, files, receipt=None):
    folder, raw, spec, log, process = paths
    actual = set()
    for path in [folder, *folder.rglob("*"), raw, spec, log, process]:
        require(path.resolve() == path and path.exists(), "literal retained case paths required")
        if path.is_file():
            actual.add(str(path.relative_to(root)))
        elif path.is_dir():
            require(
                path == folder or any(path in (root / name).parents for name in files),
                "unknown case directory",
            )
        else:
            raise ValueError("nonregular case artifact")
    require(
        actual == set(files) | ({receipt} if receipt else set()),
        "exact complete case inventory required",
    )
    c._unchanged(root, files)


def validate_state(state, checked):
    original = {
        k: v
        for k, v in state.items()
        if k not in {"completion_v1", "calls_charged", "calls_started"}
    }
    baseline = {
        k: v for k, v in checked["baseline"].items() if k not in {"calls_charged", "calls_started"}
    }
    require(original == baseline, "entire original35 history must remain unchanged")
    entry = state.get("completion_v1")
    if entry is None:
        require(
            state == checked["baseline"], "initial private STATE must equal frozen failed baseline"
        )
        return
    require(
        entry.get("schema_version") == 1
        and entry.get("current") is None
        and entry.get("status")
        in {"checkpoint", "awaiting_repair_review", "computed_pending_review"}
        and (entry.get("repair") is not None or not entry.get("accepted_remaining"))
        and entry.get("original_baseline_sha256") == checked["files"][BASELINE]
        and entry.get("completion_gate_sha256") == checked["files"][GATE]
        and entry.get("next_original_order") == 35 + len(entry.get("accepted_remaining", []))
        and [a["case_id"] for a in entry["accepted_remaining"]]
        == [j["id"] for j in checked["jobs"][35 : entry["next_original_order"]]],
        "conserved idle successful completion prefix required; no retry/reset",
    )
    accepted = ([entry["repair"]] if entry.get("repair") else []) + entry["accepted_remaining"]
    require(
        len(entry["attempts"]) == len(accepted)
        and len(accepted) <= 21
        and state["calls_charged"] == state["calls_started"] == 35 + len(accepted) <= 110
        and all(
            a.get("outcome") == "accepted"
            and a.get("start_markers") == a.get("charged_slots") == 1
            and all(a.get(k) == b.get(k) for k in ["case_id", "receipt", "receipt_sha256"])
            for a, b in zip(entry["attempts"], accepted, strict=True)
        ),
        "all extra charges and starts must be conserved",
    )


def repair_review(root, checked, entry):
    if entry["repair"] is None or not (root / REPAIR_REVIEW).exists():
        require(entry.get("repair_review_sha256") is None, "sealed repair QA is missing")
        return None
    review = read(root, REPAIR_REVIEW)
    require(
        review.get("status") == "accepted_sensitivity_same_model_numerical_repair"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is False
        and review.get("reserved_outcomes") == "sealed"
        and review.get("original_job") == checked["jobs"][34]
        and review.get("repair_job") == checked["repair_job"]
        and review.get("posterior")
        == str(case_paths(root, checked, "repair", checked["repair_job"])[1].relative_to(root))
        and review.get("posterior_sha256") == entry["repair"]["files"].get(review.get("posterior"))
        and review.get("original_baseline_sha256") == checked["files"][BASELINE]
        and review.get("original_plan_sha256") == checked["files"][c.PLAN]
        and review.get("repair_gate_sha256") == checked["files"][REPAIR_GATE]
        and review.get("completion_gate_sha256") == checked["files"][GATE],
        "independent exact same-model repair QA required",
    )
    needed = p.merge(
        checked["initial_files"],
        entry["repair"]["files"],
        {
            entry["repair"]["receipt"]: entry["repair"]["receipt_sha256"],
            PLAN: entry["plan_sha256"],
            entry["attempts"][0]["completion_receipt"]: entry["attempts"][0][
                "completion_receipt_sha256"
            ],
        },
    )
    require(r.STATE not in review.get("files", {}), "repair QA must not pin mutable private STATE")
    c._require(review.get("files", {}), needed)
    require(
        review.get("remaining_completion")
        == dict(
            status="accepted_sensitivity_original_remaining_completion",
            authorized=True,
            jobs=checked["jobs"][35:],
            inherited_calls=dict(charged=36, started=36),
            resources=resources(),
            path_bindings=bindings(root),
            max_sampler_call_slots=110,
        ),
        "explicit prospective remaining20 admission required",
    )
    pins = p.merge(checked["files"], review["files"], {REPAIR_REVIEW: sha256(root / REPAIR_REVIEW)})
    c._unchanged(root, pins)
    require(
        entry.get("repair_review_sha256") in {None, pins[REPAIR_REVIEW]},
        "sealed repair QA identity changed",
    )
    return pins


class Proofs:
    """One-process full proofs; every reuse checks complete fresh files and receipts."""

    def __init__(self, root, checked):
        self.root, self.checked, self.verified = root, checked, {}
        self.identity = self.source_identity(checked)

    @staticmethod
    def source_identity(checked):
        return canonical(
            {key: checked[key] for key in ["initial_files", "old_pins", "repair_job", "baseline"]}
        )

    def rebind(self, root, checked):
        require(
            root == self.root and self.source_identity(checked) == self.identity,
            "foreground proof memo requires identical initial Gate/model/baseline identities",
        )
        self.checked = (
            checked  # Freshly admitted repair-review closure, never an old-source shortcut.
        )

    def verify(self, kind, job, accepted):
        root, checked = self.root, self.checked
        paths = case_paths(root, checked, kind, job)
        physical(root, paths, accepted["files"], accepted["receipt"])
        require(
            sha256(root / accepted["receipt"]) == accepted["receipt_sha256"]
            and read(root, accepted["receipt"])
            == {"case_id": accepted["case_id"], "files": accepted["files"]},
            "immutable accepted attempt branch required",
        )
        key = canonical(dict(kind=kind, job=job, accepted=accepted))
        identity = kind + ":" + job["id"]
        if identity not in self.verified:
            if kind == "original":
                files, manifest = r.fit.case_artifacts(root, job, checked["old_pins"], accepted)
            else:
                result = checked["repair_api"].case_artifacts(
                    root, job, checked["repair_admission"]["files"], accepted
                )
                files, manifest = result["files"], result["manifest"]
            require(
                files == accepted["files"]
                and str(Path(manifest).relative_to(root)) == accepted["receipt"],
                "complete original worker proof required",
            )
            self.verified[identity] = key
        require(self.verified[identity] == key, "no proof-cache identity migration")
        physical(root, paths, accepted["files"], accepted["receipt"])

    def all(self, state, current=None):
        root, checked = self.root, self.checked
        c._unchanged(root, checked["files"])
        physical(root, r.case_paths(root, checked["jobs"][34]), checked["gate"]["failed_files"])
        for job, accepted in zip(
            checked["jobs"][:34], checked["baseline"]["accepted"], strict=True
        ):
            self.verify("original", job, accepted)
        entry = state.get("completion_v1") or {}
        if entry.get("repair"):
            self.verify("repair", checked["repair_job"], entry["repair"])
        for job, accepted in zip(
            checked["jobs"][35 : 35 + len(entry.get("accepted_remaining", []))],
            entry.get("accepted_remaining", []),
            strict=True,
        ):
            self.verify("original", job, accepted)
        for attempt in entry.get("attempts", []):
            require(
                sha256(root / attempt["completion_receipt"]) == attempt["completion_receipt_sha256"]
                and read(root, attempt["completion_receipt"])
                == {k: v for k, v in attempt.items() if k != "completion_receipt_sha256"},
                "immutable completion attempt evidence changed",
            )
        c._unchanged(root, checked["files"])
        inventory(root, checked, state, current)


def inventory(root, checked, state, current=None):
    entry = state.get("completion_v1") or {}
    original = (
        checked["jobs"][:35] + checked["jobs"][35 : 35 + len(entry.get("accepted_remaining", []))]
    )
    repair = [checked["repair_job"]] if entry.get("repair") else []
    if current:
        (repair if current[0] == "repair" else original).append(current[1])
    for store, jobs in [(r.STORE, original), (REPAIR_STORE, repair)]:
        wanted = {
            str((root / store / (job["id"] + ".nc")).relative_to(root))
            for job in jobs
            if (root / store / (job["id"] + ".nc")).exists()
        }
        actual = set()
        for path in (root / store).rglob("*"):
            require(path.resolve() == path, "raw/cache symlinks are not admitted")
            if path == root / store / "cache" or root / store / "cache" in path.parents:
                continue
            require(path.is_file(), "unknown raw directory retained")
            actual.add(str(path.relative_to(root)))
        require(actual == wanted, "unknown raw partial retained")
    for base, jobs in [(r.OUTPUT, original), (REPAIR_OUTPUT, repair)]:
        ids = {job["id"] for job in jobs}
        allowed = ids | {
            name + suffix for name in ids for suffix in ["-spec.json", ".log", ".supervisor.json"]
        }
        require(
            all(
                path.name in allowed and path.resolve() == path
                for path in (root / base / "jobs").glob("*")
            ),
            "unknown case artifact retained",
        )
    allowed = {BASELINE, PLAN, COMPLETION_SUMMARY, OUTPUT + "/.controller.lock", OUTPUT + "/STOP"}
    for attempt in entry.get("attempts", []):
        allowed.add(attempt["completion_receipt"])
        if attempt.get("failure_receipt"):
            allowed.add(attempt["failure_receipt"])
    if current:
        allowed.add(OUTPUT + "/attempts/" + current[1]["id"] + ".json")
    for path in (root / OUTPUT).rglob("*"):
        require(path.resolve() == path, "completion symlinks are not admitted")
        if path.is_file():
            require(str(path.relative_to(root)) in allowed, "unknown completion evidence retained")
        else:
            require(
                path.is_dir() and any(path in (root / name).parents for name in allowed),
                "unknown completion directory retained",
            )


def quota(root, checked, state, current=None, *, reserve=False):
    try:
        r.parent_floors(root, checked["gate"])
        bases = [root / r.DESIGN, root / r.OUTPUT, root / r.STORE, root / REPAIR_STORE]
        for base in bases:
            require(base.resolve() == base, "symlink storage")
            for path in base.rglob("*"):
                require(path.resolve() == path, "symlink storage")
                try:
                    if path.is_file() and path.stat().st_size > r.FILE_MAX:
                        return "per_file_storage"
                except FileNotFoundError:
                    continue  # Match the existing monitor's atomic-cache replacement handling.
        extra = r.RESERVE if reserve else 0
        outside = sum(
            c._path(root, name).stat().st_size
            for name in checked["gate"]["external_reference_files"]
        )
        if (
            r.working_bytes(root, checked["parents"])
            + r.byte_count(root / REPAIR_STORE)
            + outside
            + extra
            > resources()["global_max_bytes"]
        ):
            return "global_storage"
        if r.byte_count(*bases) + extra > resources()["local_max_bytes"]:
            return "local_storage"
        if r.byte_count(root / r.STORE / "cache", root / REPAIR_STORE / "cache") > r.MAX_CACHE:
            return "cache_storage"
        entry = state.get("completion_v1") or {}
        cases = [("original", j) for j in checked["jobs"][:35]]
        cases += [
            ("original", j)
            for j in checked["jobs"][35 : 35 + len(entry.get("accepted_remaining", []))]
        ]
        if entry.get("repair"):
            cases.append(("repair", checked["repair_job"]))
        if current and current not in cases:
            cases.append(current)
        for kind, job in cases:
            folder, *siblings = case_paths(root, checked, kind, job)
            evidence = root / OUTPUT / "attempts" / (job["id"] + ".json")
            total = r.byte_count(folder) + sum(
                path.stat().st_size
                for path in [*siblings, evidence, evidence.with_name(job["id"] + "-failure.json")]
                if path.is_file()
            )
            if total > r.MAX_JOB:
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


@contextmanager
def leases(root):
    with r._leases(root):
        path = root / OUTPUT / ".controller.lock"
        r.new_json(path, {"pid": os.getpid()})
        try:
            yield
        finally:
            path.unlink()


def controller_summary(root, checked, state):
    entry = state["completion_v1"]
    require(
        entry["repair_mapping"] is not None
        and entry["next_original_order"] == 55
        and state["calls_charged"] == state["calls_started"] == 56,
        "all55 logical cases/56 actual calls required",
    )
    accepted = []
    sources = [
        ("original", job, value)
        for job, value in zip(checked["jobs"][:34], checked["baseline"]["accepted"], strict=True)
    ]
    sources += [("repair", checked["repair_job"], entry["repair"])]
    sources += [
        ("original", job, value)
        for job, value in zip(checked["jobs"][35:], entry["accepted_remaining"], strict=True)
    ]
    files = dict(checked["files"])
    for order, (kind, job, value) in enumerate(sources):
        raw = case_paths(root, checked, kind, job)[1]
        accepted.append(
            dict(
                value,
                order=order,
                case_id=checked["jobs"][order]["id"],
                source_role="numerical_repair" if kind == "repair" else "original",
                original_job=checked["jobs"][order],
                execution_job=job,
                posterior=str(raw.relative_to(root)),
                posterior_sha256=value["files"][str(raw.relative_to(root))],
            )
        )
        files = p.merge(files, value["files"], {value["receipt"]: value["receipt_sha256"]})
    for attempt in entry["attempts"]:
        files[attempt["completion_receipt"]] = attempt["completion_receipt_sha256"]
    files[PLAN] = entry["plan_sha256"]
    require(r.STATE not in files, "public summary must not pin mutable private STATE")
    return dict(
        schema_version=1,
        status="sensitivity_computations_complete",
        logical_cases=55,
        actual_sampler_calls=56,
        calls_charged=56,
        calls_started=56,
        max_sampler_call_slots=110,
        original_plan=c.PLAN,
        original_plan_sha256=checked["files"][c.PLAN],
        original_baseline=BASELINE,
        original_baseline_sha256=checked["files"][BASELINE],
        completion_gate=GATE,
        completion_gate_sha256=checked["files"][GATE],
        repair_gate=REPAIR_GATE,
        repair_gate_sha256=checked["files"][REPAIR_GATE],
        repair_review=REPAIR_REVIEW,
        repair_review_sha256=entry["repair_review_sha256"],
        accepted=accepted,
        numerical_repair_mapping={checked["jobs"][34]["id"]: entry["repair_mapping"]},
        completion_attempts=entry["attempts"],
        monitor_failures=[],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scientific_acceptance="pending_independent_checker",
        files=files,
    )


def verify_completion_sources(root):
    """Public metadata-only final admission; does not read canonical private STATE."""
    checked = verify_gate(root)
    summary = read(root, COMPLETION_SUMMARY)
    require(
        summary.get("status") == "sensitivity_computations_complete"
        and summary.get("logical_cases") == 55
        and summary.get("calls_charged")
        == summary.get("calls_started")
        == summary.get("actual_sampler_calls")
        == 56
        and summary.get("max_sampler_call_slots") == 110
        and summary.get("monitor_failures") == []
        and summary.get("confirmation_outcomes_parsed") is False
        and summary.get("reserved_outcomes") == "sealed"
        and [v["case_id"] for v in summary.get("accepted", [])]
        == [j["id"] for j in checked["jobs"]]
        and summary.get("completion_gate_sha256") == checked["files"][GATE],
        "complete explicit55/56 public summary required",
    )
    require(
        not (root / COMPLETION_FAILURE).exists(), "retained completion failure blocks promotion"
    )
    require(
        summary.get("original_plan_sha256") == checked["files"][c.PLAN]
        and summary.get("original_baseline_sha256") == checked["files"][BASELINE]
        and summary.get("repair_gate_sha256") == checked["files"][REPAIR_GATE],
        "same final baseline/plan/repair Gate required",
    )
    for order, accepted in enumerate(summary["accepted"]):
        kind = "repair" if order == 34 else "original"
        job = checked["repair_job"] if order == 34 else checked["jobs"][order]
        paths = case_paths(root, checked, kind, job)
        require(
            accepted.get("order") == order
            and accepted.get("original_job") == checked["jobs"][order]
            and accepted.get("execution_job") == job
            and accepted.get("source_role") == ("numerical_repair" if order == 34 else "original")
            and accepted.get("posterior") == str(paths[1].relative_to(root))
            and accepted.get("posterior_sha256") == accepted["files"].get(accepted["posterior"])
            and accepted.get("receipt")
            == str((paths[0] / "attempt-evidence.json").relative_to(root))
            and accepted.get("receipt_sha256") == sha256(root / accepted["receipt"]),
            "literal ordered original/repair artifact descriptors required",
        )
        physical(root, paths, accepted["files"], accepted["receipt"])
        c._require(
            summary.get("files", {}),
            p.merge(accepted["files"], {accepted["receipt"]: accepted["receipt_sha256"]}),
        )
    physical(root, r.case_paths(root, checked["jobs"][34]), checked["gate"]["failed_files"])
    require(
        len(summary.get("completion_attempts", [])) == 21,
        "repair and20 original immutable completion attempts required",
    )
    for position, attempt in enumerate(summary["completion_attempts"]):
        job = checked["repair_job"] if position == 0 else checked["jobs"][34 + position]
        case_id = checked["jobs"][34]["id"] if position == 0 else job["id"]
        require(
            attempt.get("execution_job") == job
            and attempt.get("case_id") == case_id
            and attempt.get("kind") == ("repair" if position == 0 else "original")
            and attempt.get("outcome") == "accepted"
            and attempt.get("charged_slots") == attempt.get("start_markers") == 1
            and attempt.get("completion_receipt") == OUTPUT + "/attempts/" + job["id"] + ".json"
            and attempt.get("completion_receipt_sha256")
            == sha256(root / attempt["completion_receipt"])
            and read(root, attempt["completion_receipt"])
            == {k: v for k, v in attempt.items() if k != "completion_receipt_sha256"},
            "literal full-cost completion attempt proof required",
        )
        c._require(
            summary["files"], {attempt["completion_receipt"]: attempt["completion_receipt_sha256"]}
        )
    repair = summary["accepted"][34]
    review_pins = repair_review(
        root,
        checked,
        dict(
            repair=repair,
            plan_sha256=summary["files"][PLAN],
            attempts=summary["completion_attempts"],
            repair_review_sha256=summary.get("repair_review_sha256"),
        ),
    )
    if review_pins is None:
        raise ValueError("accepted repair and remaining20 admission required")
    c._require(summary["files"], review_pins)
    require(
        summary.get("numerical_repair_mapping")
        == {
            checked["jobs"][34]["id"]: dict(
                repair_job=checked["repair_job"],
                repair_gate_sha256=checked["files"][REPAIR_GATE],
                repair_review_sha256=review_pins[REPAIR_REVIEW],
                failed_attempt_receipt_sha256=checked["baseline"]["attempts"][-1]["receipt_sha256"],
                original_baseline_sha256=checked["files"][BASELINE],
                posterior=repair["posterior"],
                posterior_sha256=repair["posterior_sha256"],
            )
        },
        "explicit unchanged failed-to-repair mapping required",
    )
    c._require(summary.get("files", {}), checked["files"])
    pins = p.merge(summary["files"], {COMPLETION_SUMMARY: sha256(root / COMPLETION_SUMMARY)})
    require(r.STATE not in pins, "mutable STATE is not a final public source")
    c._unchanged(root, pins)
    return {**checked, "summary": summary, "files": pins}


def run(root, *, resume=False, max_cases=4, _session=None, _expected_state_sha256=None):
    require(
        type(max_cases) is int and 1 <= max_cases <= 4, "one to four remaining jobs per invocation"
    )
    root = root.resolve()
    checked = verify_gate(root)
    state_path = root / r.STATE
    owned = state_path.read_bytes()
    require(
        _expected_state_sha256 is None
        or hashlib.sha256(owned).hexdigest() == _expected_state_sha256,
        "foreign valid STATE advance during foreground admission",
    )
    state = json.loads(owned)
    validate_state(state, checked)
    require(
        resume == (state.get("completion_v1") is not None),
        "explicit first allocation/resume required",
    )
    plan = dict(
        files=checked["files"],
        original_baseline_sha256=checked["files"][BASELINE],
        repair_job=checked["repair_job"],
        remaining_jobs=checked["jobs"][35:],
    )
    if resume:
        require(
            sha256(root / PLAN) == state["completion_v1"]["plan_sha256"]
            and read(root, PLAN) == plan,
            "immutable completion plan required",
        )
    if state.get("completion_v1", {}).get("repair"):
        extra = repair_review(root, checked, state["completion_v1"])
        if extra is not None:
            checked["files"] = extra
    proofs = None if _session is None else _session.get("proofs")
    if proofs is None:
        proofs = Proofs(root, checked)
        if _session is not None:
            _session["proofs"] = proofs
    else:
        require(isinstance(proofs, Proofs), "one controlled foreground proof memo required")
        proofs.rebind(root, checked)
    proofs.all(state)
    stops = [root / name for name in [r.OLD_OUTPUT + "/STOP", r.OUTPUT + "/STOP", OUTPUT + "/STOP"]]
    require(not any(q.exists() or q.is_symlink() for q in stops), "STOP before allocation")

    def save():
        nonlocal owned
        require(state_path.read_bytes() == owned, "foreign canonical STATE; do not overwrite")
        expected = (json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        atomic_state(state_path, state)
        owned = expected
        require(state_path.read_bytes() == owned, "foreign canonical STATE after write")

    with leases(root):
        require(
            state_path.read_bytes() == owned, "canonical STATE changed before lease acquisition"
        )
        if not resume:
            r.new_json(root / PLAN, plan)
            state["completion_v1"] = dict(
                schema_version=1,
                original_baseline_sha256=checked["files"][BASELINE],
                completion_gate_sha256=checked["files"][GATE],
                plan_sha256=sha256(root / PLAN),
                status="checkpoint",
                current=None,
                repair=None,
                accepted_remaining=[],
                attempts=[],
                next_original_order=35,
                repair_mapping=None,
                repair_review_sha256=None,
            )
            save()
        entry = state["completion_v1"]
        if entry["status"] == "computed_pending_review":
            require(
                sha256(root / COMPLETION_SUMMARY) == entry["summary_sha256"]
                and not quota(root, checked, state),
                "immutable terminal summary/resources changed",
            )
            verify_completion_sources(root)
            return hashlib.sha256(owned).hexdigest()
        ended, failures = threading.Event(), []
        current: list[Any] = [None]

        def monitor():
            while not ended.wait(0.1):
                reason = quota(root, checked, state, current[0])
                if any(q.exists() for q in stops):
                    reason = reason or "STOP"
                if reason:
                    failures.append(reason)
                    try:
                        with stops[-1].open("x") as stream:
                            stream.write(reason)
                    except FileExistsError:
                        pass
                    return

        cache = root / r.STORE / "cache"
        os.environ.update(
            PYTENSOR_FLAGS=(
                f"floatX=float64,base_compiledir={cache / 'pytensor'},"
                f"compiledir={cache / 'pytensor/compiled'}"
            ),
            NUMBA_CACHE_DIR=str(cache / "numba"),
            MPLCONFIGDIR=str(cache / "matplotlib"),
        )
        limit_worker_file_size(r.FILE_MAX)
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            if entry["repair"] is None:
                work = [("repair", checked["repair_job"])]
            else:
                extra = repair_review(root, checked, state["completion_v1"])
                if extra is None:
                    entry["status"] = "awaiting_repair_review"
                    save()
                    return hashlib.sha256(owned).hexdigest()
                checked["files"] = extra
                entry["repair_review_sha256"] = extra[REPAIR_REVIEW]
                repair_raw = case_paths(root, checked, "repair", checked["repair_job"])[1]
                entry["repair_mapping"] = dict(
                    repair_job=checked["repair_job"],
                    repair_gate_sha256=extra[REPAIR_GATE],
                    repair_review_sha256=extra[REPAIR_REVIEW],
                    failed_attempt_receipt_sha256=checked["baseline"]["attempts"][-1][
                        "receipt_sha256"
                    ],
                    original_baseline_sha256=extra[BASELINE],
                    posterior=str(repair_raw.relative_to(root)),
                    posterior_sha256=entry["repair"]["files"][str(repair_raw.relative_to(root))],
                )
                save()
                work = [
                    ("original", j)
                    for j in checked["jobs"][
                        entry["next_original_order"] : entry["next_original_order"] + max_cases
                    ]
                ]
            for kind, job in work:
                proofs.all(state)
                require(state_path.read_bytes() == owned, "foreign STATE before dispatch")
                require(
                    not failures
                    and not any(q.exists() for q in stops)
                    and not quota(root, checked, state, reserve=True)
                    and state["calls_charged"] < 110,
                    "source/storage/STOP/call ceiling before dispatch",
                )
                paths = case_paths(root, checked, kind, job)
                folder, raw, spec, log, process = paths
                require(
                    all(not q.exists() and not q.is_symlink() and q.resolve() == q for q in paths),
                    "new paths only; preserve all partials/no retries",
                )
                r.new_json(spec, job)
                entry["current"] = dict(kind=kind, job_id=job["id"])
                state["calls_charged"] += 1
                save()
                current[0] = (kind, job)
                runtime = {}
                try:
                    c._unchanged(root, checked["files"])
                    cli = REPAIR_CLI if kind == "repair" else "scripts/fit_arrival_sensitivity.py"
                    runtime = supervise(
                        [
                            sys.executable,
                            str(root / cli),
                            "--job",
                            str(spec),
                            "--output",
                            str(folder),
                            "--store",
                            str(raw),
                            "--max-output-bytes",
                            str(r.FILE_MAX),
                        ],
                        log,
                        stops[-1],
                        600,
                    )
                except BaseException as error:
                    runtime = dict(
                        returncode=None, reason="supervisor_failure", error=type(error).__name__
                    )
                require(
                    state_path.read_bytes() == owned,
                    "foreign canonical STATE after child; retain evidence without overwrite",
                )
                markers = len(list(folder.rglob("sampling-start*.json")))
                state["calls_started"] += markers
                r.new_json(
                    process,
                    {
                        **runtime,
                        "charged_slots": 1,
                        "start_markers": markers,
                        "job_sha256": sha256(spec),
                        "plan_sha256": checked["files"][c.PLAN],
                        "repair_gate_sha256": checked["files"][REPAIR_GATE],
                        "completion_gate_sha256": checked["files"][GATE],
                        "invocation_git_sha": git_sha(root),
                        "monitor_failures": list(failures),
                    },
                )
                evidence = root / OUTPUT / "attempts" / (job["id"] + ".json")
                outcome, accepted = "needs_review", None
                try:
                    require(
                        markers == 1
                        and runtime.get("returncode") == 0
                        and runtime.get("reason") == "worker_exit",
                        "one complete successful sampler invocation required",
                    )
                    if kind == "repair":
                        result = checked["repair_api"].case_artifacts(
                            root, job, checked["repair_admission"]["files"]
                        )
                        files, manifest = result["files"], Path(result["manifest"])
                    else:
                        files, manifest = r.fit.case_artifacts(root, job, checked["old_pins"])
                    require(
                        manifest == folder / "attempt-evidence.json",
                        "literal case attempt manifest required",
                    )
                    case_id = checked["jobs"][34]["id"] if kind == "repair" else job["id"]
                    r.new_json(manifest, {"case_id": case_id, "files": files})
                    accepted = dict(
                        case_id=case_id,
                        charged_slots=1,
                        files=files,
                        receipt=str(manifest.relative_to(root)),
                        receipt_sha256=sha256(manifest),
                    )
                    proofs.verify(kind, job, accepted)
                    outcome = "accepted"
                except Exception as error:
                    r.new_json(
                        folder / "completion-failure.json", {"error": str(error), "retained": True}
                    )
                record = dict(
                    case_id=checked["jobs"][34]["id"] if kind == "repair" else job["id"],
                    execution_job=job,
                    kind=kind,
                    charged_slots=1,
                    start_markers=markers,
                    outcome=outcome,
                    completion_receipt=str(evidence.relative_to(root)),
                )
                if accepted:
                    record.update({k: accepted[k] for k in ["receipt", "receipt_sha256"]})
                r.new_json(evidence, record)
                record["completion_receipt_sha256"] = sha256(evidence)
                try:
                    require(
                        outcome == "accepted", "failed computation retained; no automatic retry"
                    )
                    proofs.all(state, (kind, job))
                    proofs.verify(kind, job, accepted)
                    inventory(root, checked, state, (kind, job))
                    require(
                        not failures
                        and not any(q.exists() for q in stops)
                        and not quota(root, checked, state, (kind, job)),
                        "post-evidence storage/STOP failure",
                    )
                    c._unchanged(
                        root, {record["completion_receipt"]: record["completion_receipt_sha256"]}
                    )
                except Exception as error:
                    failure = evidence.with_name(job["id"] + "-failure.json")
                    r.new_json(
                        failure,
                        {
                            "error": str(error),
                            "completion_receipt_sha256": record["completion_receipt_sha256"],
                        },
                    )
                    record.update(
                        outcome="needs_review",
                        failure_receipt=str(failure.relative_to(root)),
                        failure_receipt_sha256=sha256(failure),
                    )
                    entry["attempts"].append(record)
                    raise ValueError("failed computation retained; no retry/refund") from error
                entry["attempts"].append(record)
                if kind == "repair":
                    entry["repair"], entry["status"] = accepted, "awaiting_repair_review"
                else:
                    entry["accepted_remaining"].append(accepted)
                    entry["next_original_order"] += 1
                    entry["status"] = "checkpoint"
                entry["current"], current[0] = None, None
                save()
            ended.set()
            watcher.join(timeout=2)
            validate_state(state, checked)
            proofs.all(state)
            require(
                not failures
                and not any(q.exists() for q in stops)
                and not quota(root, checked, state),
                "final source/storage/STOP failure",
            )
            if entry["next_original_order"] == 55:
                summary = controller_summary(root, checked, state)
                r.new_json(root / COMPLETION_SUMMARY, summary)
                entry.update(
                    status="computed_pending_review",
                    summary_sha256=sha256(root / COMPLETION_SUMMARY),
                )
            proofs.all(state)
            require(not quota(root, checked, state), "late final write storage failure")
            save()
        except BaseException as error:
            if not (root / COMPLETION_FAILURE).exists():
                r.new_json(
                    root / COMPLETION_FAILURE,
                    {
                        "status": "needs_review",
                        "error": str(error),
                        "calls_charged": state["calls_charged"],
                        "calls_started": state["calls_started"],
                    },
                )
            if state_path.read_bytes() == owned:
                entry["status"] = "needs_review"
                save()
            else:
                path = root / OUTPUT / "foreign-state-failure.json"
                if not path.exists():
                    r.new_json(
                        path,
                        {
                            "error": str(error),
                            "expected_state_sha256": hashlib.sha256(owned).hexdigest(),
                            "actual_state_sha256": sha256(state_path),
                            "canonical_state_overwritten": False,
                        },
                    )
            raise
        finally:
            ended.set()
            watcher.join(timeout=2)

    return hashlib.sha256(owned).hexdigest()


def foreground(root, *, resume=False, max_cases=4, invocations=1, pause_between_batches=False):
    """At most six closed invocations; explicit ACK and exact ownership between them."""
    require(
        type(invocations) is int
        and 1 <= invocations <= 6
        and (invocations == 1 or pause_between_batches),
        "multiple foreground invocations require explicit checkpoint pauses",
    )
    root = root.resolve()
    session, owned = {}, None
    try:
        for number in range(invocations):
            owned = run(
                root,
                resume=resume or number > 0,
                max_cases=max_cases,
                _session=session,
                _expected_state_sha256=owned,
            )
            require(sha256(root / r.STATE) == owned, "foreign STATE after closed foreground batch")
            status = read(root, r.STATE)["completion_v1"]["status"]
            require(
                sha256(root / r.STATE) == owned, "foreign STATE during closed checkpoint readback"
            )
            if (
                status in {"awaiting_repair_review", "computed_pending_review"}
                or number + 1 == invocations
            ):
                break
            require(
                input("Closed batch; enter ACK after review to continue: ") in {"", "ACK"},
                "explicit newline/ACK checkpoint required",
            )
            require(sha256(root / r.STATE) == owned, "foreign valid STATE advance while paused")
        return owned
    finally:
        if "proofs" in session:
            session["proofs"].verified.clear()
        session.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--invocations", type=int, default=1)
    parser.add_argument("--pause-between-batches", action="store_true")
    args = parser.parse_args()
    foreground(
        Path(__file__).resolve().parents[1],
        resume=args.resume,
        max_cases=args.max_cases,
        invocations=args.invocations,
        pause_between_batches=args.pause_between_batches,
    )
