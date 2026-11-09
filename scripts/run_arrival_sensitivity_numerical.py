"""Continue a reviewed numerical protocol while retaining every previous attempt."""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256  # noqa: E402
from scripts import run_arrival_sensitivity_completion as old  # noqa: E402
from scripts.run_arrival_model_batch import atomic_state, git_sha  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

c, p, r = old.c, old.p, old.r
require, read, canonical = old.require, old.read, old.canonical
SELF, TEST = (
    "scripts/run_arrival_sensitivity_numerical.py",
    "tests/test_run_arrival_sensitivity_numerical.py",
)
WORKER, CLI, WORKER_TEST = (
    "analysis/arrival/model_sensitivity_numerical_fit.py",
    "scripts/fit_arrival_sensitivity_numerical.py",
    "tests/test_arrival_model_sensitivity_numerical_fit.py",
)
RUN_ID = "numerical-protocol-v2"
GATE = r.DESIGN + "/" + RUN_ID + "/review-acceptance.json"
OUTPUT = r.OUTPUT + "/" + RUN_ID
STORE = "data/processed/models/arrival-sensitivity-" + RUN_ID
COMPLETION_SUMMARY = PUBLIC_COMPLETION_SUMMARY = OUTPUT + "/run-summary.json"


def resources():
    return old.resources()


def bindings(root, run_id):
    return dict(
        project_root=str(root.resolve()),
        state=str(root.resolve() / r.STATE),
        output=r.OUTPUT + "/" + run_id,
        store="data/processed/models/arrival-sensitivity-" + run_id,
    )


def proof_contract():
    return dict(
        baseline_prefix="independent_scientific_review_plus_fresh_complete_bytes",
        new_cases="unconditional_full_worker_verification_before_acceptance",
        memo_scope="one_foreground_process",
        scientific_arrays_cached=False,
        mtime_or_size_identity=False,
        fresh_sources_files_receipts_inventory_each_reuse=True,
        automatic_retry=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def worker_api() -> Any:
    return importlib.import_module("analysis.arrival.model_sensitivity_numerical_fit")


def layout(root, gate_path):
    run_id = Path(gate_path).parent.name
    require(
        re.fullmatch(r"numerical-protocol-v[1-9][0-9]*", run_id) is not None
        and gate_path == r.DESIGN + "/" + run_id + "/review-acceptance.json",
        "canonical separately reviewed numerical Gate required",
    )
    return bindings(root, run_id)


def verify_gate(root, gate_path=GATE):
    """Hash all admission sources before importing the native-data worker."""
    root = root.resolve()
    paths = layout(root, gate_path)
    gate = read(root, gate_path)
    require(
        gate.get("status") == "accepted_sensitivity_remaining_numerical_protocol"
        and gate.get("independent_checker") is True
        and gate.get("resources") == resources()
        and gate.get("path_bindings") == paths
        and gate.get("proof_contract") == proof_contract()
        and gate.get("confirmation_outcomes_parsed") is False
        and gate.get("reserved_outcomes") == "sealed"
        and {SELF, TEST, WORKER, CLI, WORKER_TEST} <= set(gate.get("files", {}))
        and r.STATE not in gate["files"],
        "complete reviewed numerical runtime required",
    )
    pins = {**gate["files"], gate_path: sha256(root / gate_path)}
    c._unchanged(root, pins)
    api = worker_api()
    checked = api.verify_gate(root, gate_path=gate_path)
    require(
        checked["gate"] == gate and checked["files"] == pins,
        "worker and controller must admit identical complete source closure",
    )
    parents = checked["parents"]
    external = c.external_reference_paths(root, parents)
    require(
        gate.get("parent_minimum_bytes")
        == checked["original_admission"]["gate"]["parent_minimum_bytes"]
        and gate.get("external_reference_files") == external
        and set(external) <= set(pins)
        and gate.get("max_sampler_call_slots") == 110,
        "all historical floors and exact outside references required",
    )
    return {
        **checked,
        "api": api,
        "gate_path": gate_path,
        "paths": paths,
        "initial_files": dict(pins),
    }


def paths_for(root, checked, descriptor):
    producer, job = descriptor["producer"], descriptor["execution_job"]
    if producer == "original":
        return r.case_paths(root, job)
    if producer == "repair_v1":
        folder, raw = (
            root / old.REPAIR_OUTPUT / "jobs" / job["id"],
            root / old.REPAIR_STORE / (job["id"] + ".nc"),
        )
    else:
        require(producer == "numerical_protocol", "known literal numerical producer required")
        folder, raw = checked["api"].case_paths(root, job, admission=checked)
    return (
        folder,
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    )


def execution_descriptor(root, checked, job, files, receipt):
    folder, raw = checked["api"].case_paths(root, job, admission=checked)
    require(receipt == folder / "attempt-evidence.json", "literal worker receipt required")
    return dict(
        case_id=job["original_job"]["id"],
        order=job["order"],
        original_job=job["original_job"],
        execution_job=job,
        producer="numerical_protocol",
        run_id=checked["gate"]["run_id"],
        execution_gate=checked["gate_path"],
        charged_slots=1,
        source_role="numerical_repair" if job["attempt"] == 2 else "numerical_protocol",
        posterior=str(raw.relative_to(root)),
        posterior_sha256=files[str(raw.relative_to(root))],
        files=files,
        receipt=str(receipt.relative_to(root)),
        receipt_sha256=sha256(receipt),
    )


def entry_of(state, checked):
    return state.get("numerical_protocol_runs", {}).get(checked["gate"]["run_id"])


def validate_state(state, checked):
    baseline, run_id = checked["baseline"], checked["gate"]["run_id"]
    projected = {
        k: v
        for k, v in state.items()
        if k not in {"calls_charged", "calls_started", "numerical_protocol_runs"}
    }
    projected_base = {
        k: v
        for k, v in baseline.items()
        if k not in {"calls_charged", "calls_started", "numerical_protocol_runs"}
    }
    other = dict(state.get("numerical_protocol_runs", {}))
    other.pop(run_id, None)
    require(
        projected == projected_base and other == baseline.get("numerical_protocol_runs", {}),
        "entire frozen history and every older namespace must remain unchanged",
    )
    entry = entry_of(state, checked)
    if entry is None:
        require(state == baseline, "initial canonical STATE must equal exact frozen38 baseline")
        return
    accepted, attempts = entry.get("accepted", []), entry.get("attempts", [])
    require(
        entry.get("schema_version") == 2
        and entry.get("gate_path") == checked["gate_path"]
        and entry.get("gate_sha256") == checked["initial_files"][checked["gate_path"]]
        and entry.get("baseline_sha256")
        == checked["initial_files"][checked["gate"]["baseline_state"]]
        and entry.get("registry_sha256")
        == checked["initial_files"][checked["gate"]["baseline_registry"]]
        and entry.get("current") is None
        and entry.get("status")
        in {"checkpoint", "awaiting_pilot_review", "computed_pending_review"}
        and entry.get("next_job") == len(accepted) <= len(checked["jobs"])
        and [a["execution_job"] for a in accepted] == checked["jobs"][: len(accepted)]
        and len(attempts) == len(accepted)
        and state["calls_charged"] == checked["gate"]["calls_before"] + len(accepted) <= 110
        and state["calls_started"] == checked["gate"]["started_before"] + len(accepted),
        "idle reviewed successful prefix required; failed/partial runs cannot resume",
    )
    for job, accepted_case, attempt in zip(
        checked["jobs"][: len(accepted)], accepted, attempts, strict=True
    ):
        require(
            accepted_case["case_id"] == job["original_job"]["id"]
            and attempt.get("outcome") == "accepted"
            and attempt.get("execution_job") == job
            and attempt.get("charged_slots") == attempt.get("start_markers") == 1
            and all(
                attempt.get(k) == accepted_case[k] for k in ["case_id", "receipt", "receipt_sha256"]
            ),
            "every retained charge/start/accepted receipt must reconcile",
        )


def pilot_review(root, checked, entry):
    name = checked["paths"]["output"] + "/pilot-review-acceptance.json"
    if not (root / name).exists():
        require(entry.get("pilot_review_sha256") is None, "sealed pilot review missing")
        return None
    require(bool(entry["accepted"]), "pilot review cannot predate completed first job")
    review = read(root, name)
    needed = p.merge(
        checked["initial_files"],
        entry["accepted"][0]["files"],
        {
            entry["accepted"][0]["receipt"]: entry["accepted"][0]["receipt_sha256"],
            checked["paths"]["output"] + "/plan.json": entry["plan_sha256"],
            entry["attempts"][0]["controller_receipt"]: entry["attempts"][0][
                "controller_receipt_sha256"
            ],
        },
    )
    require(
        review.get("status") == "accepted_sensitivity_numerical_protocol_pilot"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is False
        and review.get("reserved_outcomes") == "sealed"
        and review.get("run_id") == checked["gate"]["run_id"]
        and review.get("gate_sha256") == checked["initial_files"][checked["gate_path"]]
        and review.get("baseline_registry_sha256")
        == checked["initial_files"][checked["gate"]["baseline_registry"]]
        and review.get("accepted") == entry["accepted"][0]
        and review.get("calls_charged")
        == review.get("calls_started")
        == checked["gate"]["calls_before"] + 1
        and r.STATE not in review.get("files", {}),
        "exact independently accepted numerical pilot required",
    )
    require(
        review.get("remaining_authorization")
        == dict(
            status="accepted_sensitivity_numerical_protocol_remaining",
            authorized=True,
            jobs=checked["jobs"][1:],
            calls_before=checked["gate"]["calls_before"] + 1,
            started_before=checked["gate"]["started_before"] + 1,
            protocol=checked["gate"]["protocol"],
            resources=resources(),
            path_bindings=checked["paths"],
            max_sampler_call_slots=110,
        ),
        "explicit remaining18 authorization required",
    )
    c._require(review.get("files", {}), needed)
    pins = p.merge(checked["files"], review["files"], {name: sha256(root / name)})
    c._unchanged(root, pins)
    require(
        entry.get("pilot_review_sha256") in {None, pins[name]},
        "sealed numerical pilot review drift",
    )
    return pins


class Proofs:
    """Reviewed baseline plus fresh bytes; new numeric checks are process-local."""

    def __init__(self, root, checked):
        self.root, self.checked, self.identity = root, checked, self.source_identity(checked)
        self.verified = {}

    @staticmethod
    def source_identity(checked):
        return canonical(
            {
                k: checked[k]
                for k in ["initial_files", "baseline", "jobs", "accepted_prefix", "failed_attempts"]
            }
        )

    def rebind(self, root, checked):
        require(
            root == self.root and self.identity == self.source_identity(checked),
            "foreground source identity migration",
        )
        self.checked = checked

    def case(self, descriptor, *, new=False):
        root, checked = self.root, self.checked
        paths = paths_for(root, checked, descriptor)
        old.physical(root, paths, descriptor["files"], descriptor["receipt"])
        require(
            sha256(c._path(root, descriptor["receipt"])) == descriptor["receipt_sha256"]
            and read(root, descriptor["receipt"])
            == {"case_id": descriptor["case_id"], "files": descriptor["files"]}
            and descriptor["posterior"] == str(paths[1].relative_to(root))
            and descriptor["posterior_sha256"] == descriptor["files"].get(descriptor["posterior"]),
            "exact producer/receipt/raw identity required",
        )
        if descriptor["producer"] == "numerical_protocol":
            key = canonical(descriptor)
            identity = descriptor["execution_job"]["id"]
            if new or identity not in self.verified:
                proof = checked["api"].case_artifacts(
                    root,
                    descriptor["execution_job"],
                    checked["initial_files"],
                    accepted=descriptor,
                    gate_path=checked["gate_path"],
                )
                require(
                    proof["files"] == descriptor["files"]
                    and Path(proof["manifest"]) == paths[0] / "attempt-evidence.json",
                    "unconditional complete new worker proof required",
                )
                self.verified[identity] = key
            require(self.verified[identity] == key, "numerical proof memo identity migration")
        old.physical(root, paths, descriptor["files"], descriptor["receipt"])

    def all(self, state, current=None):
        root, checked = self.root, self.checked
        c._unchanged(root, checked["files"])
        for descriptor in checked["accepted_prefix"]:
            self.case(descriptor)
        for failed in checked["failed_attempts"]:
            old.physical(root, r.case_paths(root, failed["original_job"]), failed["physical_files"])
            c._unchanged(root, failed["files"])
            require(
                sha256(c._path(root, failed["receipt"])) == failed["receipt_sha256"],
                "failed history receipt drift",
            )
        entry = entry_of(state, checked) or {}
        for descriptor in entry.get("accepted", []):
            self.case(descriptor)
        for attempt in entry.get("attempts", []):
            require(
                sha256(c._path(root, attempt["controller_receipt"]))
                == attempt["controller_receipt_sha256"]
                and read(root, attempt["controller_receipt"])
                == {k: v for k, v in attempt.items() if k != "controller_receipt_sha256"},
                "immutable numerical attempt receipt changed",
            )
        inventory(root, checked, state, current)
        c._unchanged(root, checked["files"])


def all_descriptors(checked, state, current=None):
    descriptors = [
        *checked["accepted_prefix"],
        *checked["failed_attempts"],
        *((entry_of(state, checked) or {}).get("accepted", [])),
    ]
    if current and not any(d["execution_job"] == current for d in descriptors):
        descriptors.append(dict(producer="numerical_protocol", execution_job=current))
    return descriptors


def stores(root, checked):
    return [root / r.STORE, root / old.REPAIR_STORE, root / checked["paths"]["store"]]


def inventory(root, checked, state, current=None):
    descriptors = all_descriptors(checked, state, current)
    paths = [
        r.case_paths(root, d["original_job"])
        if "producer" not in d
        else paths_for(root, checked, d)
        for d in descriptors
    ]
    for store in stores(root, checked):
        wanted = {
            str(q[1].relative_to(root)) for q in paths if q[1].parent == store and q[1].exists()
        }
        actual = set()
        require(store.resolve() == store, "symlink raw root")
        for q in store.rglob("*"):
            require(q.resolve() == q, "raw/cache symlink")
            if q == store / "cache" or store / "cache" in q.parents:
                continue
            require(q.is_file(), "unknown raw directory retained")
            actual.add(str(q.relative_to(root)))
        require(actual == wanted, "unknown retained raw partial")
    job_bases = [
        root / r.OUTPUT / "jobs",
        root / old.REPAIR_OUTPUT / "jobs",
        root / checked["paths"]["output"] / "jobs",
    ]
    for base in job_bases:
        ids = {q[0].name for q in paths if q[0].parent == base}
        allowed = ids | {
            name + suffix for name in ids for suffix in ["-spec.json", ".log", ".supervisor.json"]
        }
        require(
            base.resolve() == base
            and all(q.resolve() == q and q.name in allowed for q in base.glob("*")),
            "unknown retained case/process inventory",
        )
    output = checked["paths"]["output"]
    allowed = {name for name in checked["files"] if name.startswith(output + "/")}
    allowed |= {
        output + "/" + n
        for n in [
            "plan.json",
            "run-summary.json",
            ".controller.lock",
            "STOP",
            "failure.json",
            "foreign-state-failure.json",
        ]
    }
    entry = entry_of(state, checked) or {}
    if entry.get("status") == "computed_pending_review":
        # A later independent publication review is not a worker-produced artifact.
        allowed.add(output + "/scientific-review.json")
    for attempt in entry.get("attempts", []):
        allowed.add(attempt["controller_receipt"])
        if attempt.get("failure_receipt"):
            allowed.add(attempt["failure_receipt"])
    if current:
        allowed.add(output + "/attempts/" + current["id"] + ".json")
    job_root = root / output / "jobs"
    for q in (root / output).rglob("*"):
        require(q.resolve() == q, "numerical output symlink")
        if q == job_root or job_root in q.parents:
            continue
        if q.is_file():
            require(str(q.relative_to(root)) in allowed, "unknown numerical evidence retained")
        else:
            require(
                q.is_dir() and any(q in (root / name).parents for name in allowed),
                "unknown numerical evidence directory",
            )


def quota(root, checked, state, current=None, *, reserve=False):
    try:
        r.parent_floors(root, checked["gate"])
        bases = [root / r.DESIGN, root / r.OUTPUT, *stores(root, checked)]
        for base in bases:
            require(base.resolve() == base, "symlink storage root")
            for q in base.rglob("*"):
                require(q.resolve() == q, "symlink storage")
                try:
                    if q.is_file() and q.stat().st_size > r.FILE_MAX:
                        return "per_file_storage"
                except FileNotFoundError:
                    continue
        extra = r.RESERVE if reserve else 0
        outside = sum(
            c._path(root, name).stat().st_size
            for name in checked["gate"]["external_reference_files"]
        )
        additional = sum(r.byte_count(q) for q in stores(root, checked)[1:])
        if (
            r.working_bytes(root, checked["parents"]) + additional + outside + extra
            > resources()["global_max_bytes"]
        ):
            return "global_storage"
        if r.byte_count(*bases) + extra > resources()["local_max_bytes"]:
            return "local_storage"
        if r.byte_count(*(q / "cache" for q in stores(root, checked))) > r.MAX_CACHE:
            return "cache_storage"
        for d in all_descriptors(checked, state, current):
            paths = (
                r.case_paths(root, d["original_job"])
                if "producer" not in d
                else paths_for(root, checked, d)
            )
            folder, *siblings = paths
            job_id = d["execution_job"]["id"]
            evidence = root / checked["paths"]["output"] / "attempts" / (job_id + ".json")
            extras = [evidence, evidence.with_name(job_id + "-failure.json")]
            if d.get("receipt"):
                receipt = root / d["receipt"]
                if folder not in receipt.parents:
                    extras.append(receipt)
            if (
                r.byte_count(folder)
                + sum(q.stat().st_size for q in [*siblings, *extras] if q.is_file())
                > r.MAX_JOB
            ):
                return "combined_job_storage"
    except (ValueError, OSError):
        return "parent_floor_or_storage_scan_failure"
    return None


@contextmanager
def leases(root, checked):
    with r._leases(root):
        path = root / checked["paths"]["output"] / ".controller.lock"
        r.new_json(path, {"pid": os.getpid()})
        try:
            yield
        finally:
            path.unlink()


def plan_value(checked):
    return dict(
        gate_path=checked["gate_path"],
        files=checked["initial_files"],
        jobs=checked["jobs"],
        baseline_sha256=checked["gate"]["baseline_state_sha256"],
        registry_sha256=checked["gate"]["baseline_registry_sha256"],
        proof_contract=proof_contract(),
    )


def controller_summary(root, checked, state):
    entry = entry_of(state, checked)
    accepted = [*checked["accepted_prefix"], *entry["accepted"]]
    require(
        len(accepted) == 55
        and entry["next_job"] == len(checked["jobs"])
        and state["calls_charged"] == state["calls_started"] == 57,
        "all55 logical/57 actual calls required",
    )
    files = dict(checked["files"])
    for d in accepted:
        files = p.merge(files, d["files"], {d["receipt"]: d["receipt_sha256"]})
    for attempt in entry["attempts"]:
        files[attempt["controller_receipt"]] = attempt["controller_receipt_sha256"]
    files[checked["paths"]["output"] + "/plan.json"] = entry["plan_sha256"]
    mapping = {}
    for failed in checked["failed_attempts"]:
        d = accepted[failed["order"]]
        mapping[d["case_id"]] = dict(
            original_job=d["original_job"],
            execution_job=d["execution_job"],
            producer=d["producer"],
            failed_attempt_receipt=failed["receipt"],
            failed_attempt_receipt_sha256=failed["receipt_sha256"],
            failed_posterior=failed["posterior"],
            failed_posterior_sha256=failed["posterior_sha256"],
            posterior=d["posterior"],
            posterior_sha256=d["posterior_sha256"],
            receipt=d["receipt"],
            receipt_sha256=d["receipt_sha256"],
        )
    require(r.STATE not in files, "public summary cannot pin private STATE")
    refs = {
        k: checked["gate"][k]
        for k in [
            "baseline_state",
            "baseline_state_sha256",
            "baseline_registry",
            "baseline_registry_sha256",
            "baseline_review",
            "baseline_review_sha256",
        ]
    }
    pilot = checked["paths"]["output"] + "/pilot-review-acceptance.json"
    return dict(
        schema_version=2,
        status="sensitivity_computations_complete",
        run_id=checked["gate"]["run_id"],
        gate_path=checked["gate_path"],
        gate_path_sha256=checked["initial_files"][checked["gate_path"]],
        **refs,
        original_plan=c.PLAN,
        original_plan_sha256=checked["initial_files"][c.PLAN],
        pilot_review=pilot,
        pilot_review_sha256=entry["pilot_review_sha256"],
        logical_cases=55,
        actual_sampler_calls=57,
        calls_charged=57,
        calls_started=57,
        max_sampler_call_slots=110,
        accepted=accepted,
        numerical_repair_mapping=mapping,
        retained_failures=checked["failed_attempts"],
        protocol_amendment=dict(
            protocol=checked["gate"]["protocol"],
            first_attempt_original_case_ids=[
                j["original_job"]["id"] for j in checked["jobs"] if j["attempt"] == 1
            ],
            execution_jobs=checked["jobs"],
        ),
        completion_attempts=entry["attempts"],
        proof_contract=proof_contract(),
        monitor_failures=[],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
    )


def verify_completion_sources(root, summary_path=COMPLETION_SUMMARY):
    """Verify the public final history, without consulting canonical private STATE."""
    root = root.resolve()
    summary_sha = sha256(c._path(root, summary_path))
    summary = read(root, summary_path)
    gate_path = summary.get("gate_path", "")
    checked = verify_gate(root, gate_path)
    require(
        summary_path == checked["paths"]["output"] + "/run-summary.json"
        and r.STATE not in summary.get("files", {})
        and summary_path not in summary.get("files", {}),
        "literal public summary independent of private STATE required",
    )
    c._require(summary.get("files", {}), checked["initial_files"])
    c._unchanged(root, summary["files"])
    accepted = summary.get("accepted", [])
    entry: dict[str, Any] = dict(
        schema_version=2,
        gate_path=gate_path,
        gate_sha256=checked["initial_files"][gate_path],
        baseline_sha256=checked["gate"]["baseline_state_sha256"],
        registry_sha256=checked["gate"]["baseline_registry_sha256"],
        status="computed_pending_review",
        current=None,
        next_job=len(checked["jobs"]),
        accepted=accepted[len(checked["accepted_prefix"]) :],
        attempts=summary.get("completion_attempts", []),
        plan_sha256=summary["files"].get(checked["paths"]["output"] + "/plan.json"),
        pilot_review_sha256=summary.get("pilot_review_sha256"),
    )
    state = {
        **checked["baseline"],
        "calls_charged": summary.get("calls_charged"),
        "calls_started": summary.get("calls_started"),
        "numerical_protocol_runs": {
            **checked["baseline"].get("numerical_protocol_runs", {}),
            checked["gate"]["run_id"]: entry,
        },
    }
    validate_state(state, checked)
    require(
        read(root, checked["paths"]["output"] + "/plan.json") == plan_value(checked),
        "immutable public numerical plan changed",
    )
    pins = pilot_review(root, checked, entry)
    require(pins is not None, "accepted pilot and remaining authorization required")
    checked["files"] = pins
    # Public verification reuses the explicitly reviewed source/byte contract; no NC parse.
    proof = Proofs(root, checked)
    proof.verified = {d["execution_job"]["id"]: canonical(d) for d in entry["accepted"]}
    proof.all(state)
    require(
        summary == controller_summary(root, checked, state),
        "exact complete final numerical summary required",
    )
    c._unchanged(root, {summary_path: summary_sha, **summary["files"]})
    return {
        **checked,
        "admission": checked,
        "summary": summary,
        "files": {**summary["files"], summary_path: sha256(root / summary_path)},
    }


def run(
    root, *, gate_path=GATE, resume=False, max_cases=4, _session=None, _expected_state_sha256=None
):
    require(
        type(max_cases) is int and 1 <= max_cases <= 4, "one to four jobs per closed invocation"
    )
    root = root.resolve()
    checked = verify_gate(root, gate_path)
    state_path = c._path(root, r.STATE)
    owned = state_path.read_bytes()
    require(
        _expected_state_sha256 is None
        or hashlib.sha256(owned).hexdigest() == _expected_state_sha256,
        "foreign valid STATE advance during admission",
    )
    state = json.loads(owned)
    validate_state(state, checked)
    require(resume == (entry_of(state, checked) is not None), "explicit allocation/resume required")
    output, plan = checked["paths"]["output"], plan_value(checked)
    if resume:
        entry = entry_of(state, checked)
        require(
            sha256(root / output / "plan.json") == entry["plan_sha256"]
            and read(root, output + "/plan.json") == plan,
            "immutable numerical plan required",
        )
        if entry["accepted"]:
            extra = pilot_review(root, checked, entry)
            if extra:
                checked["files"] = extra
    proofs = None if _session is None else _session.get("proofs")
    if proofs is None:
        proofs = Proofs(root, checked)
        if _session is not None:
            _session["proofs"] = proofs
    else:
        require(isinstance(proofs, Proofs), "one controlled foreground memo required")
        proofs.rebind(root, checked)
    proofs.all(state)
    stops = [root / name for name in [r.OLD_OUTPUT + "/STOP", r.OUTPUT + "/STOP", output + "/STOP"]]
    require(not any(q.exists() or q.is_symlink() for q in stops), "STOP before allocation")

    def save():
        nonlocal owned
        require(state_path.read_bytes() == owned, "foreign canonical STATE; do not overwrite")
        expected = (json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        atomic_state(state_path, state)
        owned = expected
        require(state_path.read_bytes() == owned, "foreign STATE after write")

    with leases(root, checked):
        require(state_path.read_bytes() == owned, "canonical STATE changed before leases")
        if not resume:
            r.new_json(root / output / "plan.json", plan)
            entry = dict(
                schema_version=2,
                gate_path=gate_path,
                gate_sha256=checked["initial_files"][gate_path],
                baseline_sha256=checked["gate"]["baseline_state_sha256"],
                registry_sha256=checked["gate"]["baseline_registry_sha256"],
                plan_sha256=sha256(root / output / "plan.json"),
                status="checkpoint",
                current=None,
                next_job=0,
                accepted=[],
                attempts=[],
                pilot_review_sha256=None,
            )
            state.setdefault("numerical_protocol_runs", {})[checked["gate"]["run_id"]] = entry
            save()
        entry = entry_of(state, checked)
        if entry["status"] == "computed_pending_review":
            require(
                sha256(root / output / "run-summary.json") == entry["summary_sha256"]
                and not quota(root, checked, state),
                "terminal summary/resources changed",
            )
            verify_completion_sources(root, output + "/run-summary.json")
            return hashlib.sha256(owned).hexdigest()
        if entry["accepted"]:
            extra = pilot_review(root, checked, entry)
            if extra is None:
                entry["status"] = "awaiting_pilot_review"
                save()
                return hashlib.sha256(owned).hexdigest()
            checked["files"] = extra
            entry["pilot_review_sha256"] = extra[output + "/pilot-review-acceptance.json"]
            save()
        ended, failures = threading.Event(), []
        current: list[Any] = [None]

        def monitor():
            while not ended.wait(0.1):
                reason = quota(root, checked, state, current[0])
                if any(q.exists() or q.is_symlink() for q in stops):
                    reason = reason or "STOP"
                if reason:
                    failures.append(reason)
                    try:
                        with stops[-1].open("x") as stream:
                            stream.write(reason)
                    except FileExistsError:
                        pass
                    return

        cache = root / checked["paths"]["store"] / "cache"
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
            count = max_cases if entry["accepted"] else 1
            for job in checked["jobs"][entry["next_job"] : entry["next_job"] + count]:
                proofs.all(state)
                require(state_path.read_bytes() == owned, "foreign STATE before dispatch")
                require(
                    not failures
                    and not any(q.exists() or q.is_symlink() for q in stops)
                    and not quota(root, checked, state, reserve=True)
                    and state["calls_charged"] < 110,
                    "source/storage/STOP/call ceiling before dispatch",
                )
                descriptor = dict(producer="numerical_protocol", execution_job=job)
                folder, raw, spec, log, process = paths_for(root, checked, descriptor)
                require(
                    all(
                        not q.exists() and not q.is_symlink() and q.resolve() == q
                        for q in [folder, raw, spec, log, process]
                    ),
                    "new paths only; preserve every partial/no retries",
                )
                r.new_json(spec, job)
                entry["current"], current[0] = job, job
                state["calls_charged"] += 1
                save()
                runtime = {}
                invocation_git = git_sha(root)
                try:
                    c._unchanged(root, checked["files"])
                    runtime = supervise(
                        [
                            sys.executable,
                            str(root / CLI),
                            "--gate",
                            gate_path,
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
                    "foreign STATE after child; retain without overwrite",
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
                        "plan_sha256": checked["initial_files"][c.PLAN],
                        "numerical_gate_sha256": checked["initial_files"][gate_path],
                        "invocation_git_sha": invocation_git,
                        "monitor_failures": list(failures),
                    },
                )
                evidence = root / output / "attempts" / (job["id"] + ".json")
                accepted, outcome, error_text = None, "needs_review", None
                try:
                    require(
                        markers == 1
                        and runtime.get("returncode") == 0
                        and runtime.get("reason") == "worker_exit",
                        "one complete successful sampler invocation required",
                    )
                    proof = checked["api"].case_artifacts(
                        root, job, checked["initial_files"], gate_path=gate_path
                    )
                    files, manifest = proof["files"], Path(proof["manifest"])
                    require(
                        manifest == folder / "attempt-evidence.json",
                        "literal worker manifest required",
                    )
                    r.new_json(manifest, {"case_id": job["original_job"]["id"], "files": files})
                    accepted = execution_descriptor(root, checked, job, files, manifest)
                    # Full worker proof above is unconditional, even in a warm foreground session.
                    proofs.verified[job["id"]] = canonical(accepted)
                    proofs.case(accepted)
                    outcome = "accepted"
                except Exception as error:
                    error_text = str(error)
                record = dict(
                    case_id=job["original_job"]["id"],
                    execution_job=job,
                    charged_slots=1,
                    start_markers=markers,
                    outcome=outcome,
                    controller_receipt=str(evidence.relative_to(root)),
                )
                if accepted:
                    record.update({k: accepted[k] for k in ["receipt", "receipt_sha256"]})
                if error_text:
                    record["error"] = error_text
                r.new_json(evidence, record)
                record["controller_receipt_sha256"] = sha256(evidence)
                try:
                    require(
                        outcome == "accepted", "failed computation retained; no automatic retry"
                    )
                    proofs.all(state, job)
                    proofs.case(accepted)
                    require(
                        not failures
                        and not any(q.exists() or q.is_symlink() for q in stops)
                        and not quota(root, checked, state, job),
                        "post-evidence quota/STOP failure",
                    )
                    c._unchanged(
                        root, {record["controller_receipt"]: record["controller_receipt_sha256"]}
                    )
                except Exception as error:
                    failure = evidence.with_name(job["id"] + "-failure.json")
                    r.new_json(
                        failure,
                        {
                            "error": str(error),
                            "controller_receipt_sha256": record["controller_receipt_sha256"],
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
                entry["accepted"].append(accepted)
                entry["next_job"] += 1
                entry["status"] = (
                    "awaiting_pilot_review" if entry["next_job"] == 1 else "checkpoint"
                )
                entry["current"], current[0] = None, None
                save()
            ended.set()
            watcher.join(timeout=2)
            validate_state(state, checked)
            proofs.all(state)
            require(
                not failures
                and not any(q.exists() or q.is_symlink() for q in stops)
                and not quota(root, checked, state),
                "final source/storage/STOP failure",
            )
            if entry["next_job"] == len(checked["jobs"]):
                summary = controller_summary(root, checked, state)
                r.new_json(root / output / "run-summary.json", summary)
                entry.update(
                    status="computed_pending_review",
                    summary_sha256=sha256(root / output / "run-summary.json"),
                )
            proofs.all(state)
            require(not quota(root, checked, state), "late final write storage failure")
            save()
        except BaseException as error:
            failure = root / output / "failure.json"
            if not failure.exists():
                r.new_json(
                    failure,
                    dict(
                        status="needs_review",
                        error=str(error),
                        calls_charged=state["calls_charged"],
                        calls_started=state["calls_started"],
                    ),
                )
            if state_path.read_bytes() == owned:
                entry["status"] = "needs_review"
                save()
            else:
                failure = root / output / "foreign-state-failure.json"
                if not failure.exists():
                    r.new_json(
                        failure,
                        dict(
                            error=str(error),
                            expected_state_sha256=hashlib.sha256(owned).hexdigest(),
                            actual_state_sha256=sha256(state_path),
                            canonical_state_overwritten=False,
                        ),
                    )
            raise
        finally:
            ended.set()
            watcher.join(timeout=2)
    return hashlib.sha256(owned).hexdigest()


def foreground(
    root, *, gate_path=GATE, resume=False, max_cases=4, invocations=1, pause_between_batches=False
):
    require(type(invocations) is int and 1 <= invocations <= 6, "one to six foreground invocations")
    require(
        invocations == 1 or pause_between_batches,
        "explicit acknowledgement between closed batches required",
    )
    session, expected = {}, None
    try:
        for i in range(invocations):
            if i:
                actual = sha256(c._path(root.resolve(), r.STATE))
                require(actual == expected, "foreign STATE before acknowledgement")
                answer = input(f"Closed batch STATE {expected}; enter ACK {expected} to continue: ")
                require(answer == f"ACK {expected}", "exact owned STATE acknowledgement required")
                require(
                    sha256(c._path(root.resolve(), r.STATE)) == expected,
                    "foreign STATE after acknowledgement",
                )
            expected = run(
                root,
                gate_path=gate_path,
                resume=resume or i > 0,
                max_cases=max_cases,
                _session=session,
                _expected_state_sha256=expected,
            )
            state = read(root.resolve(), r.STATE)
            run_id = Path(gate_path).parent.name
            entry = state["numerical_protocol_runs"][run_id]
            if entry["status"] in {"awaiting_pilot_review", "computed_pending_review"}:
                break
        return expected
    finally:
        session.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--gate", default=GATE)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--foreground-invocations", type=int, default=1)
    parser.add_argument("--pause-between-batches", action="store_true")
    args = parser.parse_args()
    foreground(
        args.root,
        gate_path=args.gate,
        resume=args.resume,
        max_cases=args.max_cases,
        invocations=args.foreground_invocations,
        pause_between_batches=args.pause_between_batches,
    )


if __name__ == "__main__":
    main()
