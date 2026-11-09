"""Finite append-only G/full completion with explicitly versioned scientific proofs.

The public metadata reader imports no scientific modules and never parses arrays
or private STATE. Worker and proof children share the original startup settings.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import sys
import threading
from pathlib import Path
from typing import Any

ART = "artifacts/models/arrival-timing/"
CONTROL = ART + "development-check-v1/controller/technical-completion-v1"
LEGACY_DESIGN = ART + "development-design-v1/technical-completion-v1"
DESIGN = ART + "development-design-v1/technical-completion-v2"
HISTORY_MANIFEST = DESIGN + "/source-history/v1/historical-source-bindings.json"
HISTORY_MANIFEST_SHA256 = "585e40cffbcbcea780d111f85158776d28ed597fa8f5f93f55588229869e76ed"
LEGACY_AUTHORITY = LEGACY_DESIGN + "/full_design_recovery/review-acceptance.json"
LEGACY_AUTHORITY_SHA256 = "da7c13dcaaa43e7b7a8be73837794c6c6051e8ebd16c068063165b90b9a5b5a2"
G2_REVIEW = CONTROL + "/G2-stable-review.json"
PROOF_CONTRACT = "original_scientific_checks_diagnostic_recomputation_v2"
FULL_PROOF_CONTRACT = "original_full_development_case_artifacts"
REPLAY_SOURCE = "analysis/arrival/model_development_replay.py"
REPLAY_TEST = "tests/test_arrival_model_development_replay.py"
V1_SOURCE_HASHES = {
    "analysis/arrival/model_development_technical_completion.py": (
        "66cec4fdddde344ec60bce51f4681cd0faa5f5ca0db89b60f5cd8156e7621247"
    ),
    "scripts/run_arrival_development_technical_completion.py": (
        "d8184af399ac762709e8493cbde497c3d6ddcbb382ba58b7a250a1b7025c0e76"
    ),
    "tests/test_arrival_development_technical_completion.py": (
        "2296279e35001607c01af9acfdc3878b01c41735d7f1176cefb33464cf1dc25c"
    ),
}
BASELINE = CONTROL + "/baseline-review.json"
PILOT = CONTROL + "/sampler-pilot-review-acceptance.json"
FREEZE = ART + "specification-freeze-v1/review-acceptance.json"
CHECK = ART + "development-check-v1/review-acceptance.json"
CHECK_SUMMARY = ART + "development-check-v1/controller/completion-after-gap-v1/check-summary.json"
G_REVIEW = ART + "full-development-recovery-v1/review-acceptance.json"
PHASES = ("full_design_recovery", "full_development")
SELF = "analysis/arrival/model_development_technical_completion.py"
CLI = "scripts/run_arrival_development_technical_completion.py"
TEST = "tests/test_arrival_development_technical_completion.py"
THREADS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
STORES = {
    "full_design_recovery": "data/processed/models/arrival-development-recovery-v1",
    "full_development": "data/processed/models/arrival-development-v1",
}
OUTPUTS = {
    "full_design_recovery": ART + "full-development-recovery-v1",
    "full_development": ART + "full-development-v1",
}
KERNELS = {
    "full_design_recovery": ART + "full-development-recovery-design-v1/review-acceptance.json",
    "full_development": ART + "full-development-design-v1/review-acceptance.json",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def payload(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def file(root, name):
    p = root / name
    require(
        isinstance(name, str)
        and not Path(name).is_absolute()
        and ".." not in Path(name).parts
        and p.resolve() == p
        and p.is_file(),
        "literal regular metadata file required: " + str(name),
    )
    return p


def load(root, name):
    return json.loads(file(root, name).read_text())


def merge(*maps):
    result = {}
    for values in maps:
        for p, h in values.items():
            require(
                re.fullmatch("[0-9a-f]{64}", h) and (p not in result or result[p] == h),
                "conflicting SHA closure",
            )
            result[p] = h
    return result


def fresh(root, pins):
    for p, h in pins.items():
        require(sha(file(root, p)) == h, "changed accepted bytes: " + p)


def historical_source_verify(root, pins, source_epoch="technical-completion-v1"):
    """Explicit V1-only source migration; ordinary fresh() never falls back."""
    require(source_epoch == "technical-completion-v1", "recognized historical source epoch only")
    manifest = load(root, HISTORY_MANIFEST)
    require(
        sha(file(root, HISTORY_MANIFEST)) == HISTORY_MANIFEST_SHA256
        and manifest.get("status") == "preserved_original_technical_continuation_source_epoch"
        and manifest.get("source_epoch") == source_epoch
        and manifest.get("data_config_kernel_context_rebinding_allowed") is False
        and manifest.get("historical_authority") == LEGACY_AUTHORITY
        and manifest.get("historical_authority_sha256") == LEGACY_AUTHORITY_SHA256
        and set(manifest["allowed_bindings"]) == set(V1_SOURCE_HASHES),
        "exact independently preserved V1 source manifest",
    )
    archived = {}
    for name, expected in V1_SOURCE_HASHES.items():
        binding = manifest["allowed_bindings"][name]
        archive = binding["archived_path"]
        require(
            binding["expected_sha256"] == expected
            and binding["recognized_source_epoch"] == source_epoch
            and binding["producer_git_commit"] == "c446079dcff1b1e04a734a74f77d551afd1aafb6"
            and archive.startswith(DESIGN + "/source-history/v1/")
            and manifest["files"].get(archive) == expected,
            "only exact three archived V1 code bindings",
        )
        # Git blob identity is content-derived, requiring no mutable Git checkout.
        content = file(root, archive).read_bytes()
        require(
            hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            == binding["git_blob_oid"],
            "preserved original Git blob",
        )
        archived[archive] = expected
    require(manifest["files"] == archived, "exact archived-source inventory")
    result = {}
    for name, digest in pins.items():
        if name in V1_SOURCE_HASHES:
            require(digest == V1_SOURCE_HASHES[name], "no alternate historical code hash")
            name = manifest["allowed_bindings"][name]["archived_path"]
        require(name not in result or result[name] == digest, "conflicting SHA closure")
        result[name] = digest
    result = merge(result, archived, {HISTORY_MANIFEST: HISTORY_MANIFEST_SHA256})
    fresh(root, result)
    return result


def _covered(pins, required):
    require(
        all(pins.get(p) == h for p, h in required.items()), "complete materialized proof closure"
    )


def _legacy_authority(root, pins):
    require(pins.get(LEGACY_AUTHORITY) == LEGACY_AUTHORITY_SHA256, "exact original V1 authority")
    old = load(root, LEGACY_AUTHORITY)
    materialized = historical_source_verify(root, old["files"])
    _covered(pins, materialized)
    return old


def gate_path(phase):
    require(phase in PHASES, "fixed phase")
    return DESIGN + "/" + phase + "/review-acceptance.json"


def authority_path(phase):
    return gate_path(phase)


def plan_path(root, phase):
    return root / CONTROL / "epochs" / "epoch-2" / (phase + "-plan.json")


def legacy_plan_path(root, phase):
    return root / CONTROL / "plans" / (phase + ".json")


def allocation_path(root, phase, job):
    return root / CONTROL / "allocations" / phase / (job["id"] + ".json")


def attempt_path(root, phase, job):
    return root / CONTROL / "attempts" / phase / (job["id"] + ".json")


def summary_path(root, phase):
    return root / CONTROL / "epochs" / "epoch-2" / (phase + "-summary.json")


def proof_path(root, phase, job):
    leaf = "diagnostic-replay-v2" if phase == PHASES[0] else "strict-proofs"
    return root / OUTPUTS[phase] / leaf / job["id"] / "proof.json"


def legacy_proof_path(root, phase, job):
    return root / OUTPUTS[phase] / "strict-proofs" / job["id"] / "proof.json"


def paths(root, phase, job):
    folder = root / OUTPUTS[phase] / "jobs" / job["id"]
    return (
        folder,
        root / STORES[phase] / (job["id"] + ".nc"),
        folder.with_name(folder.name + "-spec.json"),
        folder.with_name(folder.name + ".log"),
        folder.with_name(folder.name + ".supervisor.json"),
    )


def producer_names(phase):
    names = {
        "job.json",
        "inputs.json",
        "membership.json",
        "result.json",
        "prior-settings.json",
        "sampling-start.json",
        "diagnostics.json",
        "sampling-diagnostics.csv",
        "summary.json",
        "output-checksums.json",
        "parameters.csv",
        "derived.csv",
        "curves.csv",
        "conditional-ppc.csv",
        "record-intervals.csv",
    }
    return names | (
        {"numerical-oracles.json", "truth-quantiles.csv"} if phase == PHASES[0] else set()
    )


def environment(root, phase):
    store = root / STORES[phase]
    return {
        **{p: "2" for p in THREADS},
        "PYTENSOR_FLAGS": f"floatX=float64,base_compiledir={store / 'cache/pytensor'}",
        "NUMBA_CACHE_DIR": str(store / "cache/numba"),
        "MPLCONFIGDIR": str(store / "cache/matplotlib"),
    }


def bootstrap(root, phase):
    require(
        not {"numpy", "pymc", "pytensor", "scripts.run_arrival_development"} & set(sys.modules),
        "startup environment must precede scientific imports",
    )
    os.environ.update(environment(root, phase))
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = 64 * 1024**2
    bound = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (bound if soft == resource.RLIM_INFINITY else min(bound, soft), hard)
    )


def bindings(root):
    return dict(
        project_root=str(root),
        control=CONTROL,
        design=DESIGN,
        state=None,
        stores=STORES,
        outputs=OUTPUTS,
    )


def _baseline(root, pins):
    b = load(root, BASELINE)
    require(
        b.get("status") == "accepted_frozen_development_G0_strict_revalidation"
        and b.get("independent_checker") is True
        and type(b.get("cost")) is int
        and type(b.get("start_markers")) is int
        and b.get("cost") == b.get("start_markers") == 1
        and b.get("calls_charged") == b.get("calls_started") == 1
        and b.get("new_sampler_calls") == 0
        and b.get("execution_authority") is False
        and b.get("unmodified_case_artifacts_complete_pass") is True
        and b.get("strict_source_thresholds_and_exact_oracle_equality_unchanged") is True
        and b.get("original_statuses_and_all_original_bytes_preserved") is True
        and b.get("reserved_outcomes_parsed") is False
        and b.get("original_controller_outcome") == "needs_review"
        and b.get("confirmation_outcomes_parsed") is True
        and b.get("reserved_outcomes") == "sealed"
        and b.get("specification_freeze_sha256") == pins[FREEZE],
        "independent strict legacy G0 baseline required",
    )
    require(all(pins.get(p) == h for p, h in b["files"].items()), "baseline full closure required")
    for key in [
        "original_receipt",
        "original_allocation",
        "original_supervisor",
        "original_plan",
        "original_worker_gate",
        "original_authority_gate",
        "posterior",
        "strict_proof",
    ]:
        require(pins.get(b[key]) == b[key + "_sha256"], "literal baseline proof binding: " + key)
    old = load(root, b["original_receipt"])
    process = load(root, b["original_supervisor"])
    proof = load(root, b["strict_proof"])
    require(
        old["outcome"] == "needs_review"
        and old.get("gap_eligible") is False
        and old.get("worker_files") == {}
        and old["cost"] == old["start_markers"] == 1
        and old["job_id"] == b["job"]["id"]
        and process["returncode"] == 0
        and process["reason"] == "worker_exit"
        and process["monitor_failures"] == []
        and process["invocation_git_sha"] == b["original_invocation_git_sha"]
        and proof["status"] == "unmodified_G0_strict_artifact_proof_passed_exact_worker_startup"
        and proof["new_sampler_calls"] == 0
        and proof["proof"]["files"] == b["worker_files"]
        and proof["exact_environment_before_scientific_imports"] == environment(root, PHASES[0]),
        "original failure and exact strict proof required",
    )
    folder, raw, _, _, _ = paths(root, PHASES[0], b["job"])
    expected = {str((folder / n).relative_to(root)) for n in producer_names(PHASES[0])} | {
        str(raw.relative_to(root))
    }
    require(
        set(b["worker_files"]) == expected
        and b["posterior"] == str(raw.relative_to(root))
        and b["worker_files"][b["posterior"]] == b["posterior_sha256"]
        and proof["proof"]["posterior"] == b["posterior"]
        and proof["proof"]["posterior_sha256"] == b["posterior_sha256"]
        and proof["proof"]["role"] == PHASES[0],
        "complete exact eighteen-file original posterior proof",
    )
    return b


def _plan(a):
    value = {
        k: a[k]
        for k in [
            "phase",
            "jobs",
            "dispatch_jobs",
            "files",
            "worker_gate",
            "worker_gate_sha256",
            "authority_gate",
            "authority_gate_sha256",
        ]
    }

    if a.get("source_epoch") == "technical-completion-v2":
        value.update(source_epoch=a["source_epoch"], proof_contract=a["proof_contract"])
    return value


def _admission(root, phase) -> dict[str, Any]:
    """Fresh complete public bytes/receipts only; no runtime imports or cold proof."""
    root = Path(root).resolve()
    name = gate_path(phase)
    g = load(root, name)
    pins = merge(g["files"], {name: sha(root / name)})
    require(
        g.get("status") == "accepted_frozen_arrival_development_technical_continuation"
        and g.get("independent_checker") is True
        and g.get("phase") == phase
        and g.get("source_epoch") == "technical-completion-v2"
        and g.get("proof_contract")
        == (PROOF_CONTRACT if phase == PHASES[0] else FULL_PROOF_CONTRACT)
        and g.get("path_bindings") == bindings(root)
        and g.get("max_sampler_call_slots") == 9
        and g.get("confirmation_outcomes_parsed") is True
        and g.get("reserved_outcomes") == "sealed"
        and {
            SELF,
            CLI,
            TEST,
            REPLAY_SOURCE,
            REPLAY_TEST,
            HISTORY_MANIFEST,
            LEGACY_AUTHORITY,
            G2_REVIEW,
            PILOT,
            FREEZE,
            CHECK,
            CHECK_SUMMARY,
            BASELINE,
            KERNELS[phase],
        }
        <= set(pins),
        "exact complete technical authority required",
    )
    inherited = g["inherited_context_files"]
    require(
        len(inherited) == 12
        and {p: h for p, h in pins.items() if p.startswith("context/")} == inherited,
        "only exact inherited ledgers; no live STATE",
    )
    fresh(root, pins)
    b = _baseline(root, pins)
    _legacy_authority(root, pins)
    worker = load(root, KERNELS[phase])
    require(
        g["baseline_review"] == BASELINE
        and g["baseline_review_sha256"] == pins[BASELINE]
        and g["worker_gate"] == KERNELS[phase]
        and g["worker_gate_sha256"] == pins[KERNELS[phase]]
        and g["jobs"] == worker["jobs"]
        and g["resources"] == worker["resources"]
        and all(pins.get(p) == h for p, h in worker["files"].items()),
        "unchanged frozen worker kernel required",
    )
    expected = g["jobs"][1:] if phase == PHASES[0] else g["jobs"]
    require(
        g["dispatch_jobs"] == expected
        and len(expected) == (5 if phase == PHASES[0] else 3)
        and (phase != PHASES[0] or g["jobs"][0] == b["job"]),
        "fixed remaining five G / three full jobs",
    )
    require(
        g.get("inherited_calls")
        == {"charged": 3 if phase == PHASES[0] else 6, "started": 3 if phase == PHASES[0] else 6}
        and g.get("no_retuning") is True
        and g["resources"] == load(root, b["original_worker_gate"])["resources"],
        "fixed inherited budget/resources",
    )
    check = load(root, CHECK)
    require(
        check.get("status") == "accepted_frozen_arrival_development_check"
        and check.get("independent_checker") is True
        and check.get("completed_once") is True
        and check.get("no_retuning") is True
        and check.get("specification_freeze_sha256") == pins[FREEZE],
        "accepted frozen check required",
    )
    require(
        all(pins.get(p) == h for p, h in check["files"].items()), "full check SCI source closure"
    )
    if phase == PHASES[1]:
        require(G_REVIEW in pins, "previous G SCI before full")
        review = load(root, G_REVIEW)
        require(
            review.get("status") == "accepted_frozen_full_development_design_checks"
            and review.get("independent_checker") is True
            and review.get("specification_freeze_sha256") == pins[FREEZE]
            and all(pins.get(p) == h for p, h in review["files"].items()),
            "accepted G6 before full",
        )
    a = dict(g, authority_gate=name, authority_gate_sha256=pins[name], files=pins)
    return dict(a, baseline=b)


def _stable_comparison(value):
    """Validate the declared proof semantics without recomputing scientific arrays."""
    comparison = value.get("diagnostic_comparison")
    exact = value.get("original_exact_oracle_equal")
    return (
        value.get("proof_contract") == PROOF_CONTRACT
        and type(exact) is bool
        and isinstance(comparison, dict)
        and comparison.get("proof_contract") == PROOF_CONTRACT
        and comparison.get("original_scientific_predicates_passed") is True
        and comparison.get("fresh_original_componentwise_gradient_predicate") is True
        and comparison.get("cross_run_numeric_tolerance_used") is False
        and type(comparison.get("original_exact_oracle_equal")) is bool
        and comparison["original_exact_oracle_equal"] is exact
    )


def _g2_revalidation(root, a):
    """A separately reviewed logical completion, never an invented attempt."""
    pins = a["files"]
    b = load(root, G2_REVIEW)
    job = a["jobs"][2]
    require(
        b.get("status") == "accepted_frozen_development_G2_stable_revalidation"
        and b.get("independent_checker") is True
        and b.get("job") == job
        and type(b.get("cost")) is int
        and type(b.get("start_markers")) is int
        and b["cost"] == b["start_markers"] == 1
        and b.get("calls_charged") == b.get("calls_started") == 3
        and b.get("new_sampler_calls") == 0
        and b.get("original_controller_outcome") == "failed_before_attempt"
        and b.get("original_exact_oracle_guard_passed") is False
        and b.get("original_proof_output_absent") is True
        and b.get("original_accepted_attempt_absent") is True
        and b.get("confirmation_outcomes_parsed") is True
        and b.get("reserved_outcomes") == "sealed",
        "typed same-call G2 stable review",
    )
    _covered(pins, b["files"])
    for key in [
        "original_allocation",
        "original_failure",
        "original_supervisor",
        "original_failed_proof_process",
        "original_failed_proof_log",
        "original_plan",
        "original_authority_gate",
        "original_worker_gate",
        "posterior",
        "stable_proof",
    ]:
        require(pins.get(b[key]) == b[key + "_sha256"], "literal G2 review pointer: " + key)
    folder, raw, spec, log, process = paths(root, PHASES[0], job)
    allocation = allocation_path(root, PHASES[0], job)
    failure = root / CONTROL / "failures" / (job["id"] + ".json")
    legacy_proof = legacy_proof_path(root, PHASES[0], job)
    old = load(root, str(allocation.relative_to(root)))
    failed = load(root, str(failure.relative_to(root)))
    worker = load(root, str(process.relative_to(root)))
    q = load(root, str(legacy_proof.with_name("proof-process.json").relative_to(root)))
    proof = load(root, b["stable_proof"])
    require(
        b["original_allocation"] == str(allocation.relative_to(root))
        and b["original_failure"] == str(failure.relative_to(root))
        and b["original_supervisor"] == str(process.relative_to(root))
        and b["original_failed_proof_process"]
        == str(legacy_proof.with_name("proof-process.json").relative_to(root))
        and b["original_failed_proof_log"]
        == str(legacy_proof.with_name("proof.log").relative_to(root))
        and b["original_plan"] == str(legacy_plan_path(root, PHASES[0]).relative_to(root))
        and b["original_authority_gate"] == LEGACY_AUTHORITY
        and b["original_authority_gate_sha256"] == LEGACY_AUTHORITY_SHA256
        and b["original_worker_gate"] == KERNELS[PHASES[0]]
        and b["posterior"] == str(raw.relative_to(root))
        and b["stable_proof"] == str(proof_path(root, PHASES[0], job).relative_to(root))
        and not legacy_proof.exists()
        and not legacy_proof.is_symlink()
        and not attempt_path(root, PHASES[0], job).exists()
        and not attempt_path(root, PHASES[0], job).is_symlink(),
        "no G2 original history healing",
    )
    require(
        old["job"] == job
        and load(root, str(spec.relative_to(root))) == job
        and old["invocation_git_sha"] == b["original_invocation_git_sha"]
        and re.fullmatch("[0-9a-f]{40}", b["original_invocation_git_sha"]) is not None
        and load(root, str((folder / "sampling-start.json").relative_to(root))) == job
        and old["cost"] == worker["cost"] == worker["start_markers"] == failed["charged"] == 1
        and worker["returncode"] == 0
        and worker["reason"] == "worker_exit"
        and worker["monitor_failures"] == []
        and worker["authority_gate_sha256"] == LEGACY_AUTHORITY_SHA256
        and worker["allocation_sha256"] == sha(allocation)
        and worker["invocation_git_sha"] == b["original_invocation_git_sha"]
        and worker["worker_gate_sha256"] == pins[KERNELS[PHASES[0]]]
        and worker["job_sha256"] == sha(spec)
        and worker["plan_sha256"] == sha(legacy_plan_path(root, PHASES[0]))
        and worker["startup_environment"] == environment(root, PHASES[0])
        and failed["allocation"] == str(allocation.relative_to(root))
        and q["returncode"] != 0
        and q["reason"] == "worker_exit"
        and q["monitor_failures"] == []
        and q["sampler_calls"] == 0
        and q["authority_gate_sha256"] == LEGACY_AUTHORITY_SHA256
        and q["worker_gate_sha256"] == pins[KERNELS[PHASES[0]]]
        and q["job_sha256"] == sha(spec)
        and q["startup_environment"] == environment(root, PHASES[0]),
        "retained exact paid G2 worker/proof failure",
    )
    expected_worker = {str((folder / n).relative_to(root)) for n in producer_names(PHASES[0])} | {
        str(raw.relative_to(root))
    }
    require(
        set(b["worker_files"]) == expected_worker
        and {p.name for p in folder.iterdir()} == producer_names(PHASES[0])
        and proof.get("status") == "scientific_artifact_replay_passed"
        and proof.get("proof_contract") == PROOF_CONTRACT
        and proof.get("job") == job
        and proof.get("sampler_calls") == 0
        and proof.get("worker_files") == b["worker_files"]
        and _stable_comparison(proof),
        "complete stable scientific proof",
    )
    _covered(pins, b["worker_files"])
    require(
        {p.name for p in legacy_proof.parent.iterdir()} == {"proof.log", "proof-process.json"},
        "retained G2 failed proof inventory remains exact",
    )
    for proof_folder in [legacy_proof.parent, (root / b["stable_proof"]).parent]:
        for entry in proof_folder.rglob("*"):
            relative = str(entry.relative_to(root))
            require(
                entry.resolve() == entry and (entry.is_file() or entry.is_dir()),
                "literal closed G2 proof evidence",
            )
            require(
                (entry.is_file() and relative in b["files"])
                or (entry.is_dir() and any(entry in (root / n).parents for n in b["files"])),
                "unknown G2 proof evidence",
            )
    return dict(
        producer="G2_stable_scientific_revalidation",
        producer_epoch="technical-completion-v2",
        proof_contract=PROOF_CONTRACT,
        job=job,
        logical_outcome="accepted_under_stable_revalidation",
        original_controller_outcome="failed_before_attempt",
        original_allocation=b["original_allocation"],
        original_allocation_sha256=b["original_allocation_sha256"],
        original_failure=b["original_failure"],
        original_failure_sha256=b["original_failure_sha256"],
        technical_review=G2_REVIEW,
        technical_review_sha256=pins[G2_REVIEW],
        strict_proof=b["stable_proof"],
        strict_proof_sha256=b["stable_proof_sha256"],
        worker_files=b["worker_files"],
        files=b["files"],
        cost=1,
        start_markers=1,
    )


def _historical_pilot(root, a, first):
    pilot = load(root, PILOT)
    materialized = historical_source_verify(root, pilot["files"])
    _covered(a["files"], materialized)
    require(
        pilot.get("status") == "accepted_development_two_sampler_runtime_pilots"
        and pilot.get("independent_checker") is True
        and pilot.get("sampler_pilot_job_ids")
        == [r["job"]["id"] if "job" in r else r["job_id"] for r in first]
        and pilot.get("authority_gate") == LEGACY_AUTHORITY
        and pilot.get("authority_gate_sha256") == LEGACY_AUTHORITY_SHA256
        and pilot.get("baseline_review_sha256") == a["files"][BASELINE]
        and pilot.get("calls_charged") == pilot.get("calls_started") == 2
        and all(
            pilot["files"].get(r["receipt"]) == r["receipt_sha256"] for r in first if "receipt" in r
        ),
        "historical first two actual starts independently reviewed",
    )
    return merge(materialized, {PILOT: sha(file(root, PILOT))})


def read_program_metadata(root, phase) -> dict[str, Any]:
    root = Path(root).resolve()
    a = _admission(root, phase)
    b = a["baseline"]
    pins = a["files"]
    name = a["authority_gate"]
    expected = a["dispatch_jobs"]
    records = []
    logical = []
    extra = {}
    charged = started = 1
    base = dict(
        producer="legacy_G0_strict_revalidation",
        producer_epoch="legacy_before_technical_v1",
        proof_contract="strict_original_worker_artifacts_passed",
        job=b["job"],
        logical_outcome="accepted_under_strict_revalidation",
        original_controller_outcome="needs_review",
        original_receipt=b["original_receipt"],
        original_receipt_sha256=b["original_receipt_sha256"],
        technical_review=BASELINE,
        technical_review_sha256=pins[BASELINE],
        strict_proof=b["strict_proof"],
        strict_proof_sha256=b["strict_proof_sha256"],
        worker_files=b["worker_files"],
        files=b["files"],
        cost=1,
        start_markers=1,
    )
    if phase == PHASES[1]:
        prior = read_program_metadata(root, PHASES[0])
        require(
            prior["complete"] and prior["calls_charged"] == prior["calls_started"] == 6,
            "G6 complete before full",
        )
        review = load(root, G_REVIEW)
        require(
            review.get("status") == "accepted_frozen_full_development_design_checks"
            and review.get("independent_checker") is True
            and review.get("specification_freeze_sha256") == pins[FREEZE]
            and all(pins.get(p) == h for p, h in prior["files"].items()),
            "same-freeze reviewed G6 required",
        )
        charged = started = 6
        extra = merge(extra, prior["files"])
    plan = plan_path(root, phase)
    if plan.exists():
        require(load(root, str(plan.relative_to(root))) == _plan(a), "immutable plan mismatch")
        extra[str(plan.relative_to(root))] = sha(plan)
    old_authority = _legacy_authority(root, pins)
    old_name = LEGACY_AUTHORITY
    old_pins = merge(old_authority["files"], {old_name: LEGACY_AUTHORITY_SHA256})
    old_plan = legacy_plan_path(root, PHASES[0])
    require(
        load(root, str(old_plan.relative_to(root)))
        == _plan(
            dict(
                old_authority,
                authority_gate=old_name,
                authority_gate_sha256=LEGACY_AUTHORITY_SHA256,
                files=old_pins,
            )
        ),
        "immutable original V1 plan",
    )
    _covered(pins, historical_source_verify(root, old_pins))
    extra[str(old_plan.relative_to(root))] = sha(old_plan)
    for i, job in enumerate(expected):
        alloc = allocation_path(root, phase, job)
        receipt = attempt_path(root, phase, job)
        if not alloc.exists():
            require(
                not receipt.exists()
                and not any(allocation_path(root, phase, j).exists() for j in expected[i + 1 :]),
                "allocation gap",
            )
            break
        allocation = load(root, str(alloc.relative_to(root)))
        legacy = allocation.get("authority_gate") == LEGACY_AUTHORITY
        record_name = LEGACY_AUTHORITY if legacy else name
        record_plan = old_plan if legacy else plan
        record_gate_sha = LEGACY_AUTHORITY_SHA256 if legacy else pins[name]
        record_proof = (
            legacy_proof_path(root, phase, job) if legacy else proof_path(root, phase, job)
        )
        require(
            legacy == (phase == PHASES[0] and job in a["jobs"][1:3]),
            "exact two V1 paid jobs cannot be relabeled as new executions",
        )
        charged += 1
        folder, raw, spec, log, process = paths(root, phase, job)
        marker = folder / "sampling-start.json"
        if marker.exists():
            require(load(root, str(marker.relative_to(root))) == job, "literal marker required")
            started += 1
        require(
            record_plan.exists()
            and allocation["job"] == job
            and type(allocation["cost"]) is int
            and allocation["cost"] == 1
            and allocation.get("job_id") == job["id"]
            and allocation.get("phase") == phase
            and allocation.get("role") == job["role"]
            and allocation.get("plan") == str(record_plan.relative_to(root))
            and allocation.get("authority_gate") == record_name
            and allocation.get("worker_gate") == KERNELS[phase]
            and allocation.get("spec") == str(spec.relative_to(root))
            and load(root, str(spec.relative_to(root))) == job
            and allocation["plan_sha256"] == sha(record_plan)
            and allocation["authority_gate_sha256"] == record_gate_sha
            and allocation["worker_gate_sha256"] == pins[KERNELS[phase]]
            and allocation["spec_sha256"] == sha(file(root, str(spec.relative_to(root))))
            and re.fullmatch("[0-9a-f]{40}", allocation["invocation_git_sha"]) is not None,
            "allocation source/job/cost identity",
        )
        if legacy and job == a["jobs"][2]:
            require(marker.exists(), "paid G2 actual start retained")
            special = _g2_revalidation(root, a)
            logical.append(special)
            extra = merge(extra, special["files"], {G2_REVIEW: pins[G2_REVIEW]})
            continue
        require(receipt.exists(), "incomplete allocation retained; never retry/refund")
        r = load(root, str(receipt.relative_to(root)))
        r = {**r, "receipt_sha256": sha(receipt)}
        require(
            marker.exists()
            and r["job_id"] == job["id"]
            and r["phase"] == phase
            and r["role"] == job["role"]
            and type(r["cost"]) is int
            and type(r["start_markers"]) is int
            and r["cost"] == r["start_markers"] == 1
            and r["outcome"] == "accepted"
            and r.get("allocation") == str(alloc.relative_to(root))
            and r["allocation_sha256"] == sha(alloc)
            and r["receipt"] == str(receipt.relative_to(root)),
            "failed/incomplete attempt hardstop",
        )
        fresh(root, r["files"])
        p = load(root, str(process.relative_to(root)))
        proof = load(root, r["strict_proof"])
        q = load(root, r["strict_proof_process"])
        require(
            p["returncode"] == 0
            and p["reason"] == "worker_exit"
            and p["monitor_failures"] == []
            and p["cost"] == p["start_markers"] == 1
            and p["allocation"] == str(alloc.relative_to(root))
            and p["authority_gate"] == record_name
            and p["worker_gate"] == KERNELS[phase]
            and p["startup_environment"] == environment(root, phase)
            and p["authority_gate_sha256"] == record_gate_sha
            and p["worker_gate_sha256"] == pins[KERNELS[phase]]
            and p["plan_sha256"] == sha(record_plan)
            and p["allocation_sha256"] == sha(alloc)
            and p["invocation_git_sha"] == allocation["invocation_git_sha"]
            and p["job_sha256"] == sha(spec)
            and proof["status"]
            == (
                "strict_original_worker_artifacts_passed"
                if legacy or phase == PHASES[1]
                else "scientific_artifact_replay_passed"
            )
            and (
                legacy
                or (phase == PHASES[1] and proof.get("proof_contract") == FULL_PROOF_CONTRACT)
                or (phase == PHASES[0] and (_stable_comparison(proof)))
            )
            and proof["job"] == job
            and proof["worker_files"] == r["worker_files"]
            and proof["sampler_calls"] == 0
            and r["strict_proof"] == str(record_proof.relative_to(root))
            and r["strict_proof_sha256"] == r["files"][r["strict_proof"]]
            and r["strict_proof_process"]
            == str(record_proof.with_name("proof-process.json").relative_to(root))
            and r["strict_proof_process_sha256"] == r["files"][r["strict_proof_process"]]
            and q["returncode"] == 0
            and q["reason"] == "worker_exit"
            and q["monitor_failures"] == []
            and q["sampler_calls"] == 0
            and q["authority_gate_sha256"] == record_gate_sha
            and q["worker_gate_sha256"] == pins[KERNELS[phase]]
            and q["job_sha256"] == sha(spec)
            and q["startup_environment"] == environment(root, phase),
            "full process and strict proof metadata",
        )
        expected_worker = {str((folder / n).relative_to(root)) for n in producer_names(phase)} | {
            str(raw.relative_to(root))
        }
        require(
            set(r["worker_files"]) == expected_worker
            and proof["worker_files"] == r["worker_files"],
            "fixed complete worker file set",
        )
        require(
            {p.name for p in folder.iterdir()} == producer_names(phase), "fixed producer leaf set"
        )
        physical = [
            raw,
            spec,
            log,
            process,
            alloc,
            record_proof,
            record_proof.with_name("proof.log"),
            record_proof.with_name("proof-process.json"),
        ]
        physical.extend(folder.rglob("*"))
        actual = set()
        for p in physical:
            require(
                p.resolve() == p and (p.is_file() or p.is_dir()),
                "literal complete producer/proof inventory",
            )
            if p.is_file():
                actual.add(str(p.relative_to(root)))
            else:
                require(
                    any(p in (root / n).parents for n in r["files"]), "unknown producer directory"
                )
        require(actual == set(r["files"]), "exact closed per-case inventory")
        extra = merge(extra, r["files"], {r["receipt"]: r["receipt_sha256"]})
        r["producer_epoch"] = "technical-completion-v1" if legacy else "technical-completion-v2"
        r["proof_contract"] = (
            "strict_original_worker_artifacts_passed"
            if legacy
            else (PROOF_CONTRACT if phase == PHASES[0] else FULL_PROOF_CONTRACT)
        )
        records.append(r)
        logical.append(r)
    require(charged <= 9 and started <= charged, "inclusive nine calls; no refunds")
    require(
        phase != PHASES[0] or (len(logical) >= 2 and charged >= 3 and started >= 3),
        "Epoch2 requires the exact retained three-call logical baseline",
    )
    g2 = load(root, G2_REVIEW)
    failure_root = root / CONTROL / "failures"
    if failure_root.exists():
        require(
            {str(p.relative_to(root)) for p in failure_root.rglob("*")} == {g2["original_failure"]},
            "only independently bound G2 failure marker may remain",
        )
        require(
            sha(file(root, g2["original_failure"])) == g2["original_failure_sha256"],
            "unchanged G2 stop marker",
        )
    accepted = ([base] if phase == PHASES[0] else []) + logical
    complete = len(logical) == len(expected)
    result = dict(
        a,
        baseline=b,
        accepted_records=accepted,
        attempt_records=records,
        calls_charged=charged,
        calls_started=started,
        complete=complete,
        remaining_jobs=expected[len(logical) :],
        producer_epoch="technical-completion-v2",
        files=merge(pins, extra),
        logical_check_dispositions=load(root, CHECK_SUMMARY)["logical_check_dispositions"],
    )
    summary = summary_path(root, phase)
    if summary.exists():
        require(
            complete and load(root, str(summary.relative_to(root))) == summary_value(result),
            "immutable phase summary",
        )
        result["files"][str(summary.relative_to(root))] = sha(summary)
    require(
        program_counters(root, through_phase=phase) == dict(charged=charged, started=started),
        "every paid allocation/marker must belong to the exact phase prefix",
    )
    if phase == PHASES[0]:
        result["files"] = merge(result["files"], _historical_pilot(root, a, accepted[:2]))
    fresh(root, result["files"])
    return result


def summary_value(a):
    return {
        **{
            k: a[k]
            for k in [
                "phase",
                "jobs",
                "dispatch_jobs",
                "accepted_records",
                "attempt_records",
                "calls_charged",
                "calls_started",
                "authority_gate",
                "authority_gate_sha256",
                "worker_gate",
                "worker_gate_sha256",
                "logical_check_dispositions",
            ]
        },
        "status": "computed_pending_independent_review",
        "source_epoch": a["source_epoch"],
        "proof_contract": a["proof_contract"],
        "baseline_review": BASELINE,
        "baseline_review_sha256": a["files"][BASELINE],
    }


def _runtime():
    from scripts import run_arrival_development_journal as j

    return j


def write(path, value):
    require(path.resolve() == path, "literal exclusive output")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(payload(value))


def proof_only(root, phase, job_path, output):
    root = Path(root).resolve()
    bootstrap(root, phase)
    a = _admission(root, phase)
    job = json.loads(Path(job_path).read_text())
    require(
        job in a["dispatch_jobs"]
        and Path(job_path) == paths(root, phase, job)[2]
        and Path(output) == proof_path(root, phase, job)
        and not Path(output).exists(),
        "fixed fresh zero-sampler proof only",
    )
    alloc = load(root, str(allocation_path(root, phase, job).relative_to(root)))
    require(
        alloc["job"] == job
        and alloc["authority_gate_sha256"] == a["authority_gate_sha256"]
        and alloc["worker_gate_sha256"] == a["worker_gate_sha256"]
        and alloc["spec_sha256"] == sha(Path(job_path)),
        "paid execution allocation proof binding",
    )
    j = _runtime()
    worker = j.old.consumer(phase)
    admission = (
        worker.verify_gate(root)
        if phase == PHASES[0]
        else worker.verify_gate(root, "full_development")
    )
    if phase == PHASES[0]:
        from analysis.arrival import model_development_replay

        value = model_development_replay.case_artifacts(root, job, a["files"])
        require(
            _stable_comparison(value),
            "honest stable G verifier contract",
        )
    else:
        value = worker.case_artifacts(root, job, admission["files"])
    fresh(root, a["files"])
    write(
        Path(output),
        dict(
            status="scientific_artifact_replay_passed"
            if phase == PHASES[0]
            else "strict_original_worker_artifacts_passed",
            proof_contract=PROOF_CONTRACT if phase == PHASES[0] else FULL_PROOF_CONTRACT,
            original_exact_oracle_equal=value.get("original_exact_oracle_equal", True),
            diagnostic_comparison=value.get("diagnostic_comparison", {}),
            job=job,
            worker_files=value["files"],
            sampler_calls=0,
        ),
    )


def _run_one(root, phase):
    bootstrap(root, phase)
    root = Path(root).resolve()
    a = read_program_metadata(root, phase)
    if a["complete"]:
        return a
    j = _runtime()
    job = a["remaining_jobs"][0]
    ps = paths(root, phase, job)
    folder, raw, spec, log, process = ps
    proof = proof_path(root, phase, job)
    allocation = allocation_path(root, phase, job)
    attempt = attempt_path(root, phase, job)
    require(
        a["calls_charged"] < 9
        and all(not p.exists() and not p.is_symlink() for p in [*ps, proof, allocation, attempt]),
        "new next job only",
    )
    if a["calls_started"] >= 2:
        first = read_program_metadata(root, PHASES[0])["accepted_records"][:2]
        a["files"] = merge(a["files"], _historical_pilot(root, a, first))
    known = dict(a["files"])
    lock = root / CONTROL / ".lock"
    ended = threading.Event()
    failures = []

    def guard(active=False):
        require(
            not j.allocation_path(root, phase, job).exists()
            and not (root / j.CONTROL / ".journal.lock").exists(),
            "foreign legacy allocation/lease; preserve original namespace",
        )
        fresh(root, known)
        j.history(root, load(root, a["baseline"]["original_authority_gate"]))
        for name, value in a["baseline"]["private_state_hashes_history_only"].items():
            require(
                sha(file(root, name)) == value,
                "retained private history SHA changed; never parse/heal",
            )
        require(not any(p.exists() for p in [root / CONTROL / "STOP", *j.stops(root)]), "STOP")
        require(
            j.c2.quota(
                root, {"gate": a, "files": known, "phase": phase}, reserve=True, known_files=known
            )
            is None,
            "quota/floor/reserve",
        )
        b = a["baseline"]
        basefiles = set(b["worker_files"]) | {
            BASELINE,
            b["original_receipt"],
            b["original_allocation"],
            b["original_supervisor"],
        }
        reviewdir = (root / b["strict_proof"]).parent
        basefiles.update(str(p.relative_to(root)) for p in reviewdir.rglob("*") if p.is_file())
        require(
            sum(file(root, p).stat().st_size for p in basefiles) <= j.old.r.MAX_JOB,
            "baseline raw/job/review job cap",
        )
        scope = dict(known)
        for p in [
            lock,
            allocation,
            attempt,
            proof,
            proof.with_name("proof.log"),
            proof.with_name("proof-process.json"),
            plan_path(root, phase),
            summary_path(root, phase),
        ]:
            if p.exists():
                scope[str(p.relative_to(root))] = sha(p)
        if active:
            scope.update(
                {
                    str(p.relative_to(root)): "0" * 64
                    for p in [
                        proof,
                        proof.with_name("proof.log"),
                        proof.with_name("proof-process.json"),
                    ]
                }
            )
        j.inventory(root, {"files": scope, "phase": phase}, {}, (job, ps) if active else None)
        require(
            j.old.r.byte_count(folder)
            + sum(
                p.stat().st_size
                for p in [
                    raw,
                    spec,
                    log,
                    process,
                    allocation,
                    attempt,
                    proof,
                    proof.with_name("proof.log"),
                    proof.with_name("proof-process.json"),
                ]
                if p.is_file()
            )
            <= j.old.r.MAX_JOB,
            "combined job/evidence cap",
        )

    guard()
    with j.old.r._leases(root):
        write(lock, {"pid": os.getpid(), "owner": os.urandom(16).hex()})
        st = lock.stat()
        identity = (st.st_dev, st.st_ino, st.st_size, lock.read_bytes())

        def owned():
            require(lock.resolve() == lock and lock.is_file(), "owned lease missing or aliased")
            st = lock.stat()
            require(
                (st.st_dev, st.st_ino, st.st_size) == identity[:3]
                and lock.read_bytes() == identity[3],
                "foreign lease preserved",
            )

        try:
            inside = read_program_metadata(root, phase)
            require(
                all(a["files"].get(p) == h for p, h in inside["files"].items())
                and inside["calls_charged"] == a["calls_charged"]
                and inside["attempt_records"] == a["attempt_records"],
                "foreign prefix before lease",
            )
            guard()
            owned()
            plan = plan_path(root, phase)
            if not plan.exists():
                write(plan, _plan(a))
            write(spec, job)
            write(
                allocation,
                dict(
                    job=job,
                    job_id=job["id"],
                    phase=phase,
                    role=job["role"],
                    cost=1,
                    plan=str(plan.relative_to(root)),
                    plan_sha256=sha(plan),
                    authority_gate=a["authority_gate"],
                    authority_gate_sha256=a["authority_gate_sha256"],
                    worker_gate=a["worker_gate"],
                    worker_gate_sha256=a["worker_gate_sha256"],
                    spec=str(spec.relative_to(root)),
                    spec_sha256=sha(spec),
                    invocation_git_sha=j.old.git_sha(root),
                ),
            )
            known.update({str(p.relative_to(root)): sha(p) for p in [plan, spec, allocation]})

            def watch():
                while not ended.wait(0.1):
                    try:
                        owned()
                        guard(True)
                    except Exception as exc:
                        failures.append(str(exc))
                        try:
                            write(root / CONTROL / "STOP", {"error": str(exc)})
                        except FileExistsError:
                            pass
                        return

            thread = threading.Thread(target=watch, daemon=True)
            thread.start()
            try:
                owned()
                guard(True)
                cmd = [
                    sys.executable,
                    str(
                        root
                        / (
                            j.old.RECOVERY_CLI
                            if phase == PHASES[0]
                            else "scripts/fit_arrival_development.py"
                        )
                    ),
                    "--job",
                    str(spec),
                    "--output",
                    str(folder),
                    "--store",
                    str(raw),
                    "--max-output-bytes",
                    str(j.old.r.FILE_MAX),
                ]
                p = j.old.supervise(cmd, log, root / CONTROL / "STOP", 600)
                write(
                    process,
                    {
                        **p,
                        "cost": 1,
                        "start_markers": int((folder / "sampling-start.json").is_file()),
                        "allocation": str(allocation.relative_to(root)),
                        "plan": str(plan.relative_to(root)),
                        "authority_gate": a["authority_gate"],
                        "worker_gate": a["worker_gate"],
                        "startup_environment": environment(root, phase),
                        "monitor_failures": list(failures),
                        "job_sha256": sha(spec),
                        "plan_sha256": sha(plan),
                        "allocation_sha256": sha(allocation),
                        "authority_gate_sha256": a["authority_gate_sha256"],
                        "worker_gate_sha256": a["worker_gate_sha256"],
                        "invocation_git_sha": load(root, str(allocation.relative_to(root)))[
                            "invocation_git_sha"
                        ],
                    },
                )
                require(
                    p["returncode"] == 0 and p["reason"] == "worker_exit" and not failures,
                    "worker failure retained",
                )
                proof.parent.mkdir(parents=True, exist_ok=True)
                q = j.old.supervise(
                    [
                        sys.executable,
                        str(root / CLI),
                        "--root",
                        str(root),
                        "--phase",
                        phase,
                        "--proof-only",
                        "--job",
                        str(spec),
                        "--proof-output",
                        str(proof),
                    ],
                    proof.with_name("proof.log"),
                    root / CONTROL / "STOP",
                    600,
                )
                write(
                    proof.with_name("proof-process.json"),
                    {
                        **q,
                        "monitor_failures": list(failures),
                        "sampler_calls": 0,
                        "authority_gate_sha256": a["authority_gate_sha256"],
                        "worker_gate_sha256": a["worker_gate_sha256"],
                        "job_sha256": sha(spec),
                        "startup_environment": environment(root, phase),
                    },
                )
                require(
                    q["returncode"] == 0 and q["reason"] == "worker_exit" and not failures,
                    "strict proof failure retained",
                )
            finally:
                ended.set()
                thread.join()
            owned()
            guard(True)
            wf = load(root, str(proof.relative_to(root)))["worker_files"]
            files = merge(
                wf,
                {
                    str(p.relative_to(root)): sha(p)
                    for p in [
                        spec,
                        log,
                        process,
                        allocation,
                        proof,
                        proof.with_name("proof.log"),
                        proof.with_name("proof-process.json"),
                    ]
                },
            )
            write(
                attempt,
                dict(
                    producer="stable_scientific_startup_execution"
                    if phase == PHASES[0]
                    else "strict_startup_execution",
                    job_id=job["id"],
                    phase=phase,
                    role=job["role"],
                    cost=1,
                    start_markers=1,
                    outcome="accepted",
                    worker_files=wf,
                    files=files,
                    allocation=str(allocation.relative_to(root)),
                    allocation_sha256=sha(allocation),
                    strict_proof=str(proof.relative_to(root)),
                    strict_proof_sha256=sha(proof),
                    strict_proof_process=str(
                        proof.with_name("proof-process.json").relative_to(root)
                    ),
                    strict_proof_process_sha256=sha(proof.with_name("proof-process.json")),
                    receipt=str(attempt.relative_to(root)),
                ),
            )
            result = read_program_metadata(root, phase)
            known.update(result["files"])
            owned()
            guard()
            if result["complete"]:
                write(summary_path(root, phase), summary_value(result))
                known[str(summary_path(root, phase).relative_to(root))] = sha(
                    summary_path(root, phase)
                )
            owned()
            guard()
        except BaseException as exc:
            failure = root / CONTROL / "failures" / (job["id"] + ".json")
            if allocation.exists() and not failure.exists():
                write(
                    failure,
                    {
                        "error": repr(exc),
                        "allocation": str(allocation.relative_to(root)),
                        "charged": 1,
                    },
                )
            raise
        finally:
            owned()
            lock.unlink()
    guard()
    return read_program_metadata(root, phase)


def program_counters(root, *, through_phase=None):
    """Conservative diagnostic counts include incomplete paid allocations."""
    root = Path(root).resolve()
    charged = started = 1
    phases = PHASES if through_phase is None else PHASES[: PHASES.index(through_phase) + 1]
    for phase in phases:
        for p in (root / CONTROL / "allocations" / phase).glob("*.json"):
            value = load(root, str(p.relative_to(root)))
            job = value["job"]
            require(
                p == allocation_path(root, phase, job)
                and type(value["cost"]) is int
                and value["cost"] == 1,
                "literal allocated cost",
            )
            charged += 1
            folder = paths(root, phase, job)[0]
            markers = list(folder.glob("sampling-start*.json"))
            require(
                len(markers) <= 1
                and all(load(root, str(m.relative_to(root))) == job for m in markers),
                "literal actual marker count",
            )
            started += len(markers)
    require(started <= charged <= 9, "inclusive program counters")
    return dict(charged=charged, started=started)


def run_one(root, phase):
    root = Path(root).resolve()
    before = {str(p) for p in (root / CONTROL / "allocations" / phase).glob("*.json")}
    try:
        return _run_one(root, phase)
    except BaseException as exc:
        for p in (root / CONTROL / "allocations" / phase).glob("*.json"):
            if str(p) in before:
                continue
            failure = root / CONTROL / "failures" / (p.stem + ".json")
            if not failure.exists():
                write(
                    failure,
                    {"error": repr(exc), "allocation": str(p.relative_to(root)), "charged": 1},
                )
        raise
