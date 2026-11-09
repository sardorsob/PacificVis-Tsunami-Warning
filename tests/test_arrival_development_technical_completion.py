"""Synthetic contract tests; opaque NC/ledger bytes are never scientific input."""

# pyright: basic
from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from analysis.arrival import model_development_technical_completion as p

G, F = p.PHASES
GIT = "a" * 40
MIB = 1024**2
LEAVES = {
    "job.json",
    "inputs.json",
    "membership.json",
    "result.json",
    "prior-settings.json",
    "sampling-start.json",
    "diagnostics.json",
    "sampling-diagnostics.csv",
    "summary.json",
    "parameters.csv",
    "derived.csv",
    "curves.csv",
    "conditional-ppc.csv",
    "record-intervals.csv",
    "output-checksums.json",
    "numerical-oracles.json",
    "truth-quantiles.csv",
}
RESOURCES = dict(
    global_max_bytes=3072 * MIB,
    local_max_bytes=2048 * MIB,
    cache_max_bytes=256 * MIB,
    job_max_bytes=32 * MIB,
    file_max_bytes=64 * MIB,
    next_invocation_reserve_bytes=608 * MIB,
    timeout_seconds=600,
    watcher_seconds=0.1,
    chains=4,
    cores=2,
    draws=2000,
    tune=1000,
)


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else p.payload(value))
    return path


def read(path):
    return json.loads(path.read_text())


def hashes(root, names):
    return {str(n): p.sha(root / n) for n in names}


def worker_bytes(root, phase, job):
    folder, raw, *_ = p.paths(root, phase, job)
    names = LEAVES if phase == G else LEAVES - {"truth-quantiles.csv", "numerical-oracles.json"}
    for leaf in names - {"output-checksums.json"}:
        put(
            root,
            folder.relative_to(root) / leaf,
            job if leaf in {"job.json", "sampling-start.json"} else {"synthetic": True},
        )
    put(
        root,
        folder.relative_to(root) / "output-checksums.json",
        {n: p.sha(folder / n) for n in names - {"output-checksums.json"}},
    )
    put(root, raw.relative_to(root), b"opaque non-NetCDF fixture bytes")
    return hashes(
        root, [str(x.relative_to(root)) for x in folder.iterdir()] + [str(raw.relative_to(root))]
    )


def comparison():
    return dict(
        proof_contract=p.PROOF_CONTRACT,
        original_exact_oracle_equal=False,
        original_scientific_predicates_passed=True,
        fresh_original_componentwise_gradient_predicate=True,
        cross_run_numeric_tolerance_used=False,
        diagnostic_deltas=[
            dict(
                path="points[2].gradient_max_absolute_error",
                saved=1.6e-14,
                fresh=2.8e-14,
                absolute_delta=1.2e-14,
            )
        ],
    )


def close_job(case, phase, job, *, admission=None, legacy=False, failed=False):
    root = case.root
    a = p._admission(root, phase) if admission is None else admission
    plan = p.legacy_plan_path(root, phase) if legacy else p.plan_path(root, phase)
    if not plan.exists():
        put(root, plan.relative_to(root), p._plan(a))
    folder, raw, spec, log, process = p.paths(root, phase, job)
    wf = worker_bytes(root, phase, job)
    put(root, spec.relative_to(root), job)
    put(root, log.relative_to(root), b"worker exited")
    allocation = p.allocation_path(root, phase, job)
    put(
        root,
        allocation.relative_to(root),
        dict(
            job=job,
            job_id=job["id"],
            phase=phase,
            role=job["role"],
            cost=1,
            plan=str(plan.relative_to(root)),
            plan_sha256=p.sha(plan),
            authority_gate=a["authority_gate"],
            authority_gate_sha256=a["authority_gate_sha256"],
            worker_gate=p.KERNELS[phase],
            worker_gate_sha256=a["worker_gate_sha256"],
            spec=str(spec.relative_to(root)),
            spec_sha256=p.sha(spec),
            invocation_git_sha=GIT,
        ),
    )
    proof = p.legacy_proof_path(root, phase, job) if legacy else p.proof_path(root, phase, job)
    put(
        root,
        proof.with_name("proof.log").relative_to(root),
        b"original strict oracle diagnostic mismatch" if failed else b"zero sampler proof",
    )
    meta = dict(
        returncode=0,
        reason="worker_exit",
        monitor_failures=[],
        authority_gate_sha256=a["authority_gate_sha256"],
        worker_gate_sha256=a["worker_gate_sha256"],
        job_sha256=p.sha(spec),
        startup_environment=p.environment(root, phase),
    )
    put(
        root,
        proof.with_name("proof-process.json").relative_to(root),
        dict(meta, returncode=1 if failed else 0, sampler_calls=0),
    )
    put(
        root,
        process.relative_to(root),
        dict(
            meta,
            cost=1,
            start_markers=1,
            allocation=str(allocation.relative_to(root)),
            allocation_sha256=p.sha(allocation),
            authority_gate=a["authority_gate"],
            worker_gate=p.KERNELS[phase],
            plan_sha256=p.sha(plan),
            invocation_git_sha=GIT,
        ),
    )
    if failed:
        failure = root / p.CONTROL / "failures" / (job["id"] + ".json")
        put(
            root,
            failure.relative_to(root),
            dict(
                allocation=str(allocation.relative_to(root)),
                charged=1,
                error="ValueError('strict proof failure retained')",
            ),
        )
        return SimpleNamespace(
            worker_files=wf,
            failure=failure,
            allocation=allocation,
            process=process,
            proof=proof,
            plan=plan,
        )
    stable = phase == G and not legacy
    put(
        root,
        proof.relative_to(root),
        dict(
            status="scientific_artifact_replay_passed"
            if stable
            else "strict_original_worker_artifacts_passed",
            proof_contract=p.PROOF_CONTRACT
            if stable
            else ("strict_original_worker_artifacts_passed" if legacy else p.FULL_PROOF_CONTRACT),
            original_exact_oracle_equal=False,
            diagnostic_comparison=comparison() if stable else {},
            job=job,
            worker_files=wf,
            sampler_calls=0,
        ),
    )
    files = {
        **wf,
        **hashes(
            root,
            [
                str(x.relative_to(root))
                for x in [
                    spec,
                    log,
                    process,
                    allocation,
                    proof,
                    proof.with_name("proof.log"),
                    proof.with_name("proof-process.json"),
                ]
            ],
        ),
    }
    receipt = p.attempt_path(root, phase, job)
    put(
        root,
        receipt.relative_to(root),
        dict(
            producer="strict_startup_execution",
            job_id=job["id"],
            phase=phase,
            role=job["role"],
            cost=1,
            start_markers=1,
            outcome="accepted",
            worker_files=wf,
            files=files,
            allocation=str(allocation.relative_to(root)),
            allocation_sha256=p.sha(allocation),
            strict_proof=str(proof.relative_to(root)),
            strict_proof_sha256=p.sha(proof),
            strict_proof_process=str(proof.with_name("proof-process.json").relative_to(root)),
            strict_proof_process_sha256=p.sha(proof.with_name("proof-process.json")),
            receipt=str(receipt.relative_to(root)),
        ),
    )
    return receipt


@pytest.fixture
def program(tmp_path, monkeypatch):
    import hashlib

    root = tmp_path
    jobs: list[dict[str, Any]] = [
        dict(
            id=f"full-smoke-{i // 2}-{'a' if i % 2 == 0 else 'b'}",
            order=i,
            role=G,
            model_key=f"lane-{i // 2}:selected",
            sampler_seed=100 + i,
            conditional_seed=200 + i,
            simulator_seed=300 + i,
            truth={"alpha": 0.1},
        )
        for i in range(6)
    ]
    full: list[dict[str, Any]] = [
        dict(
            id=f"dev-lane-{i}-selected-full",
            order=i,
            role=F,
            model_key=f"lane-{i}:selected",
            seed=400 + i,
        )
        for i in range(3)
    ]
    context = {}
    for i in range(12):
        name = f"context/frozen-ledgers/{i}.json"
        context[name] = p.sha(put(root, name, b"opaque ledger, not JSON"))
    live = {}
    for leaf in [
        "development-state.json",
        "development-completion-state.json",
        "sensitivity-state.json",
    ]:
        name = "context/runs/arrival-model-fitting-v1/" + leaf
        live[name] = p.sha(put(root, name, b"opaque retained private state"))
    old_code = {}
    for name in [p.SELF, p.CLI, p.TEST]:
        old_code[name] = p.sha(put(root, name, b"# old synthetic source\n"))
    put(root, p.FREEZE, {"files": context})
    put(
        root,
        p.CHECK_SUMMARY,
        {
            "logical_check_dispositions": [
                {"job_id": "baseline-0", "outcome": "accepted_resolution"},
                {"job_id": "baseline-1", "outcome": "accepted_unresolved_gap"},
            ]
        },
    )
    put(root, "config/frozen-science.toml", b"original scientific settings\n")
    common = hashes(root, [p.FREEZE, p.CHECK_SUMMARY, "config/frozen-science.toml", *context])
    put(
        root,
        p.CHECK,
        dict(
            status="accepted_frozen_arrival_development_check",
            independent_checker=True,
            completed_once=True,
            no_retuning=True,
            specification_freeze_sha256=common[p.FREEZE],
            files=common,
        ),
    )
    common[p.CHECK] = p.sha(root / p.CHECK)
    put(root, p.KERNELS[G], dict(jobs=jobs, resources=RESOURCES, files=common))
    legacy_journal = p.CONTROL.replace("technical-completion-v1", "completion-after-gap-v1")
    old_authority = (
        p.ART + "development-design-v1/completion-after-gap-v1/"
        "full_design_recovery/review-acceptance.json"
    )
    put(
        root,
        old_authority,
        dict(
            files=common,
            original_state_sha256=live[
                "context/runs/arrival-model-fitting-v1/development-state.json"
            ],
            failed_continuation_state_sha256=live[
                "context/runs/arrival-model-fitting-v1/development-completion-state.json"
            ],
        ),
    )
    old_alloc = legacy_journal + "/allocations/full_design_recovery/" + jobs[0]["id"] + ".json"
    old_receipt = legacy_journal + "/attempts/full_design_recovery/" + jobs[0]["id"] + ".json"
    old_plan = legacy_journal + "/plans/full_design_recovery.json"
    wf = worker_bytes(root, G, jobs[0])
    folder, raw, spec, log, process = p.paths(root, G, jobs[0])
    put(root, spec.relative_to(root), jobs[0])
    put(root, log.relative_to(root), b"retained log")
    put(
        root,
        process.relative_to(root),
        dict(returncode=0, reason="worker_exit", monitor_failures=[], invocation_git_sha=GIT),
    )
    put(root, old_alloc, {"job": jobs[0], "cost": 1})
    put(root, old_plan, {"jobs": jobs})
    old_files = {
        **wf,
        **hashes(
            root,
            [
                old_alloc,
                str(spec.relative_to(root)),
                str(log.relative_to(root)),
                str(process.relative_to(root)),
            ],
        ),
    }
    put(
        root,
        old_receipt,
        dict(
            job_id=jobs[0]["id"],
            outcome="needs_review",
            cost=1,
            start_markers=1,
            gap_eligible=False,
            worker_files={},
            files=old_files,
        ),
    )
    strict = p.CONTROL + "/review-evidence-v1/strict-proof.json"
    put(
        root,
        strict,
        dict(
            status="unmodified_G0_strict_artifact_proof_passed_exact_worker_startup",
            new_sampler_calls=0,
            proof={
                "files": wf,
                "posterior": str(raw.relative_to(root)),
                "posterior_sha256": p.sha(raw),
                "role": G,
            },
            exact_environment_before_scientific_imports=p.environment(root, G),
        ),
    )
    b = dict(
        status="accepted_frozen_development_G0_strict_revalidation",
        independent_checker=True,
        cost=1,
        start_markers=1,
        calls_charged=1,
        calls_started=1,
        new_sampler_calls=0,
        original_controller_outcome="needs_review",
        confirmation_outcomes_parsed=True,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        specification_freeze_sha256=common[p.FREEZE],
        original_invocation_git_sha=GIT,
        job=jobs[0],
        worker_files=wf,
        original_receipt=old_receipt,
        original_allocation=old_alloc,
        original_supervisor=str(process.relative_to(root)),
        original_plan=old_plan,
        original_worker_gate=p.KERNELS[G],
        original_authority_gate=old_authority,
        posterior=str(raw.relative_to(root)),
        strict_proof=strict,
        exact_worker_startup_environment=p.environment(root, G),
        private_state_hashes_history_only=live,
        execution_authority=False,
        unmodified_case_artifacts_complete_pass=True,
        strict_source_thresholds_and_exact_oracle_equality_unchanged=True,
        original_statuses_and_all_original_bytes_preserved=True,
    )
    base_names = (
        {str(x.relative_to(root)) for x in root.rglob("*") if x.is_file()}
        - set(live)
        - set(old_code)
    )

    def seal_baseline():
        b["files"] = hashes(root, base_names)
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
            b[key + "_sha256"] = p.sha(root / b[key])
        put(root, p.BASELINE, b)
        return {**b["files"], p.BASELINE: p.sha(root / p.BASELINE)}

    initial = seal_baseline()
    old_review = p.LEGACY_DESIGN + "/source-review.json"
    put(root, old_review, {"files": old_code})
    old_gate: dict[str, Any] = dict(
        status="accepted_frozen_arrival_development_technical_continuation",
        independent_checker=True,
        phase=G,
        path_bindings={**p.bindings(root), "design": p.LEGACY_DESIGN},
        jobs=jobs,
        dispatch_jobs=jobs[1:],
        resources=RESOURCES,
        worker_gate=p.KERNELS[G],
        worker_gate_sha256=p.sha(root / p.KERNELS[G]),
        baseline_review=p.BASELINE,
        baseline_review_sha256=p.sha(root / p.BASELINE),
        max_sampler_call_slots=9,
        inherited_calls={"charged": 1, "started": 1},
        confirmation_outcomes_parsed=True,
        reserved_outcomes="sealed",
        no_retuning=True,
        files={**initial, **old_code, old_review: p.sha(root / old_review)},
    )
    put(root, p.LEGACY_AUTHORITY, old_gate)
    old_gate_sha = p.sha(root / p.LEGACY_AUTHORITY)
    monkeypatch.setattr(p, "LEGACY_AUTHORITY_SHA256", old_gate_sha)
    old_a: dict[str, Any] = dict(
        old_gate,
        authority_gate=p.LEGACY_AUTHORITY,
        authority_gate_sha256=old_gate_sha,
        files={**old_gate["files"], p.LEGACY_AUTHORITY: old_gate_sha},
    )
    case = SimpleNamespace(
        root=root, baseline=b, jobs=jobs, full=full, context=context, live=live, seal=seal_baseline
    )
    old_g1 = close_job(case, G, jobs[1], admission=old_a, legacy=True)
    old_record = read(old_g1)
    pilot_files = {
        **old_a["files"],
        **old_record["files"],
        str(old_g1.relative_to(root)): p.sha(old_g1),
        str(p.legacy_plan_path(root, G).relative_to(root)): p.sha(p.legacy_plan_path(root, G)),
    }
    put(
        root,
        p.PILOT,
        dict(
            status="accepted_development_two_sampler_runtime_pilots",
            independent_checker=True,
            sampler_pilot_job_ids=[jobs[0]["id"], jobs[1]["id"]],
            authority_gate=p.LEGACY_AUTHORITY,
            authority_gate_sha256=old_gate_sha,
            baseline_review_sha256=p.sha(root / p.BASELINE),
            calls_charged=2,
            calls_started=2,
            files=pilot_files,
        ),
    )
    partial = close_job(case, G, jobs[2], admission=old_a, legacy=True, failed=True)
    archived = {}
    bindings = {}
    for i, (name, h) in enumerate(old_code.items()):
        archive = p.DESIGN + f"/source-history/v1/source-{i}.py.txt"
        content = (root / name).read_bytes()
        put(root, archive, content)
        archived[archive] = h
        bindings[name] = dict(
            archived_path=archive,
            expected_sha256=h,
            git_blob_oid=hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest(),
            producer_git_commit="c446079dcff1b1e04a734a74f77d551afd1aafb6",
            recognized_source_epoch="technical-completion-v1",
        )
        put(root, name, b"# current epoch-two synthetic source\n")
    manifest = dict(
        status="preserved_original_technical_continuation_source_epoch",
        source_epoch="technical-completion-v1",
        historical_authority=p.LEGACY_AUTHORITY,
        historical_authority_sha256=old_gate_sha,
        data_config_kernel_context_rebinding_allowed=False,
        allowed_bindings=bindings,
        files=archived,
    )
    put(root, p.HISTORY_MANIFEST, manifest)
    monkeypatch.setattr(p, "V1_SOURCE_HASHES", old_code)
    monkeypatch.setattr(p, "HISTORY_MANIFEST_SHA256", p.sha(root / p.HISTORY_MANIFEST))
    for name in [p.REPLAY_SOURCE, p.REPLAY_TEST]:
        put(root, name, b"# synthetic stable proof source\n")
    stable = p.proof_path(root, G, jobs[2])
    put(
        root,
        stable.relative_to(root),
        dict(
            status="scientific_artifact_replay_passed",
            proof_contract=p.PROOF_CONTRACT,
            original_exact_oracle_equal=False,
            diagnostic_comparison=comparison(),
            job=jobs[2],
            worker_files=partial.worker_files,
            sampler_calls=0,
        ),
    )
    pointers = dict(
        original_allocation=str(partial.allocation.relative_to(root)),
        original_failure=str(partial.failure.relative_to(root)),
        original_supervisor=str(partial.process.relative_to(root)),
        original_failed_proof_process=str(
            partial.proof.with_name("proof-process.json").relative_to(root)
        ),
        original_failed_proof_log=str(partial.proof.with_name("proof.log").relative_to(root)),
        original_plan=str(partial.plan.relative_to(root)),
        original_authority_gate=p.LEGACY_AUTHORITY,
        original_worker_gate=p.KERNELS[G],
        posterior=str(p.paths(root, G, jobs[2])[1].relative_to(root)),
        stable_proof=str(stable.relative_to(root)),
    )
    g2: dict[str, Any] = dict(
        status="accepted_frozen_development_G2_stable_revalidation",
        independent_checker=True,
        job=jobs[2],
        cost=1,
        start_markers=1,
        calls_charged=3,
        calls_started=3,
        new_sampler_calls=0,
        original_controller_outcome="failed_before_attempt",
        original_exact_oracle_guard_passed=False,
        original_proof_output_absent=True,
        original_accepted_attempt_absent=True,
        confirmation_outcomes_parsed=True,
        reserved_outcomes="sealed",
        original_invocation_git_sha=GIT,
        worker_files=partial.worker_files,
        **pointers,
    )
    partial_paths = {
        str(x.relative_to(root))
        for x in [
            *p.paths(root, G, jobs[2])[1:],
            partial.allocation,
            partial.proof.with_name("proof.log"),
            partial.proof.with_name("proof-process.json"),
            partial.failure,
            stable,
            partial.plan,
        ]
    }
    g2["files"] = {**partial.worker_files, **hashes(root, partial_paths)}
    for key, path in pointers.items():
        g2[key + "_sha256"] = p.sha(root / path)
    put(root, p.G2_REVIEW, g2)
    history = p.historical_source_verify(root, {**old_a["files"], **pilot_files})

    def authority(phase=G):
        pins = {
            **seal_baseline(),
            **history,
            **g2["files"],
            p.G2_REVIEW: p.sha(root / p.G2_REVIEW),
            p.PILOT: p.sha(root / p.PILOT),
            **hashes(root, [p.SELF, p.CLI, p.TEST, p.REPLAY_SOURCE, p.REPLAY_TEST]),
        }
        phase_jobs = jobs
        if phase == F:
            prior = p.read_program_metadata(root, G)
            put(
                root,
                p.G_REVIEW,
                dict(
                    status="accepted_frozen_full_development_design_checks",
                    independent_checker=True,
                    specification_freeze_sha256=pins[p.FREEZE],
                    files=prior["files"],
                ),
            )
            kernel_files = {**prior["files"], p.G_REVIEW: p.sha(root / p.G_REVIEW)}
            put(root, p.KERNELS[F], dict(jobs=full, resources=RESOURCES, files=kernel_files))
            pins.update(kernel_files)
            pins[p.KERNELS[F]] = p.sha(root / p.KERNELS[F])
            phase_jobs = full
        gate = dict(
            status="accepted_frozen_arrival_development_technical_continuation",
            independent_checker=True,
            source_epoch="technical-completion-v2",
            proof_contract=(
                p.PROOF_CONTRACT if phase == G else "original_full_development_case_artifacts"
            ),
            phase=phase,
            path_bindings=p.bindings(root),
            max_sampler_call_slots=9,
            confirmation_outcomes_parsed=True,
            reserved_outcomes="sealed",
            inherited_context_files=context,
            files=pins,
            baseline_review=p.BASELINE,
            baseline_review_sha256=pins[p.BASELINE],
            worker_gate=p.KERNELS[phase],
            worker_gate_sha256=pins[p.KERNELS[phase]],
            jobs=phase_jobs,
            dispatch_jobs=phase_jobs[1:] if phase == G else phase_jobs,
            resources=RESOURCES,
            inherited_calls={"charged": 3 if phase == G else 6, "started": 3 if phase == G else 6},
            no_retuning=True,
        )
        put(root, p.gate_path(phase), gate)
        return gate

    case.authority = authority
    case.history = manifest
    case.old_code = old_code
    case.g2 = g2
    case.partial = partial
    return case


def test_baseline_keeps_original_failure_and_one_real_call(program):
    c = program
    pins = c.seal()
    b = p._baseline(c.root, pins)
    assert len(b["worker_files"]) == 18 and b["original_controller_outcome"] == "needs_review"
    assert p.program_counters(c.root) == dict(charged=3, started=3)
    assert not read(c.root / b["original_receipt"])["worker_files"]


@pytest.mark.parametrize(
    "fault",
    [
        "status",
        "strict_status",
        "strict_calls",
        "strict_environment",
        "strict_worker_files",
        "original_outcome",
        "baseline_calls",
        "authority_claim",
        "waived_strict_proof",
        "boolean_cost",
        "missing_raw_both_maps",
        "strict_posterior_mismatch",
    ],
)
def test_resealed_baseline_cannot_launder_original_failure(program, fault):
    c = program
    b = c.baseline
    if fault == "status":
        b["status"] = "pending"
    elif fault == "original_outcome":
        v = read(c.root / b["original_receipt"])
        v["outcome"] = "accepted"
        put(c.root, b["original_receipt"], v)
    elif fault == "baseline_calls":
        b["calls_charged"] = 2
    elif fault == "authority_claim":
        b["execution_authority"] = True
    elif fault == "waived_strict_proof":
        b["unmodified_case_artifacts_complete_pass"] = False
    elif fault == "boolean_cost":
        b["cost"] = True
    else:
        v = read(c.root / b["strict_proof"])
        if fault == "strict_status":
            v["status"] = "numerically_close"
        elif fault == "strict_calls":
            v["new_sampler_calls"] = 1
        elif fault == "strict_environment":
            v["exact_environment_before_scientific_imports"]["OPENBLAS_NUM_THREADS"] = "1"
        elif fault == "missing_raw_both_maps":
            b["worker_files"].pop(b["posterior"])
            v["proof"]["files"].pop(b["posterior"])
        elif fault == "strict_posterior_mismatch":
            v["proof"]["posterior"] = "data/other.nc"
        else:
            v["proof"]["files"].pop(next(iter(v["proof"]["files"])))
        put(c.root, b["strict_proof"], v)
    with pytest.raises(ValueError):
        p._baseline(c.root, c.seal())


def test_public_metadata_is_pure_and_starts_with_only_revalidated_G0(program, monkeypatch):
    c = program
    c.authority()
    monkeypatch.setattr(
        p, "_runtime", lambda: pytest.fail("pure reader imported runtime/native workers")
    )
    result = p.read_program_metadata(c.root, G)
    assert result["calls_charged"] == result["calls_started"] == 3
    assert len(result["attempt_records"]) == 1 and not result["complete"]
    baseline = result["accepted_records"][0]
    assert baseline["producer"] == "legacy_G0_strict_revalidation"
    assert baseline["original_controller_outcome"] == "needs_review"
    assert baseline["technical_review"] == p.BASELINE


@pytest.mark.parametrize("fault", ["missing", "extra", "live", "mismatch"])
def test_invalid_context_map_rejected_before_context_hash(program, monkeypatch, fault):
    c = program
    g = c.authority()
    first = next(iter(c.context))
    if fault == "missing":
        g["files"].pop(first)
    elif fault == "extra":
        g["files"]["context/unapproved.json"] = "0" * 64
    elif fault == "live":
        g["files"][next(iter(c.live))] = "0" * 64
    else:
        g["files"][first] = "0" * 64
    put(c.root, p.gate_path(G), g)
    real = p.fresh

    def before_context(root, pins):
        if any(x.startswith("context/") for x in pins):
            pytest.fail("bad context map reached hashing")
        return real(root, pins)

    monkeypatch.setattr(p, "fresh", before_context)
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


def test_mixed_six_G_and_three_full_metadata_without_native_imports(program, monkeypatch):
    c = program
    c.authority()
    monkeypatch.setattr(p, "_runtime", lambda: pytest.fail("metadata opened native workers"))
    for job in c.jobs[3:]:
        close_job(c, G, job)
    g = p.read_program_metadata(c.root, G)
    assert g["complete"] and len(g["accepted_records"]) == 6 and len(g["attempt_records"]) == 4
    assert g["calls_charged"] == g["calls_started"] == 6
    put(c.root, p.summary_path(c.root, G).relative_to(c.root), p.summary_value(g))
    c.authority(F)
    for job in c.full:
        close_job(c, F, job)
    f = p.read_program_metadata(c.root, F)
    assert f["complete"] and len(f["accepted_records"]) == 3
    assert f["calls_charged"] == f["calls_started"] == 9
    assert f["logical_check_dispositions"] == g["logical_check_dispositions"]


def test_partial_paid_allocation_is_charged_retained_and_not_resumable(program):
    c = program
    c.authority()
    receipt = close_job(c, G, c.jobs[3])
    receipt.unlink()
    assert p.program_counters(c.root) == dict(charged=4, started=4)
    with pytest.raises(ValueError, match="incomplete"):
        p.read_program_metadata(c.root, G)
    assert p.allocation_path(c.root, G, c.jobs[3]).exists()


def test_unknown_paid_allocation_cannot_disappear_from_metadata(program):
    c = program
    c.authority()
    # This would retry the already charged baseline slot in the new namespace.
    put(
        c.root,
        p.allocation_path(c.root, G, c.jobs[0]).relative_to(c.root),
        dict(job=c.jobs[0], cost=1, phase=G),
    )
    assert p.program_counters(c.root) == dict(charged=4, started=4)
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


def test_inclusive_counter_ceiling_counts_every_paid_partial(program):
    c = program
    for phase, jobs in [(G, c.jobs[3:]), (F, c.full)]:
        for job in jobs:
            put(
                c.root,
                p.allocation_path(c.root, phase, job).relative_to(c.root),
                dict(job=job, cost=1),
            )
            folder = p.paths(c.root, phase, job)[0]
            put(c.root, (folder / "sampling-start.json").relative_to(c.root), job)
    assert p.program_counters(c.root) == dict(charged=9, started=9)
    ghost = dict(id="extra-unapproved", role=F)
    put(c.root, p.allocation_path(c.root, F, ghost).relative_to(c.root), dict(job=ghost, cost=1))
    with pytest.raises(ValueError):
        p.program_counters(c.root)


def test_boolean_allocation_does_not_masquerade_as_integer_call(program):
    c = program
    c.authority()
    receipt = close_job(c, G, c.jobs[3])
    allocation = p.allocation_path(c.root, G, c.jobs[3])
    a = read(allocation)
    a["cost"] = True
    put(c.root, allocation.relative_to(c.root), a)
    process = p.paths(c.root, G, c.jobs[3])[-1]
    proc = read(process)
    proc["allocation_sha256"] = p.sha(allocation)
    put(c.root, process.relative_to(c.root), proc)
    r = read(receipt)
    r["allocation_sha256"] = p.sha(allocation)
    r["files"][str(allocation.relative_to(c.root))] = p.sha(allocation)
    r["files"][str(process.relative_to(c.root))] = p.sha(process)
    put(c.root, receipt.relative_to(c.root), r)
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


@pytest.mark.parametrize("fault", ["unknown_file", "empty_directory", "symlink"])
def test_closed_case_unknown_objects_are_retained_and_rejected(program, fault):
    c = program
    c.authority()
    close_job(c, G, c.jobs[3])
    folder = p.paths(c.root, G, c.jobs[3])[0]
    unknown = folder / "unlisted"
    if fault == "unknown_file":
        unknown.write_bytes(b"partial retained")
    elif fault == "empty_directory":
        unknown.mkdir()
    else:
        unknown.symlink_to(folder / "job.json")
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)
    assert unknown.exists()


def test_source_drift_rejects_before_metadata_results(program):
    c = program
    c.authority()
    (c.root / p.SELF).write_bytes(b"changed source")
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


def test_bootstrap_in_genuinely_fresh_process_sets_environment_before_imports(tmp_path):
    code = (
        "import json,sys;from pathlib import Path;from analysis.arrival import "
        "model_development_technical_completion as p;"
        f"p.bootstrap(Path({str(tmp_path)!r}),p.PHASES[0]);"
        "assert not {'numpy','pymc','pytensor'} & set(sys.modules);"
        "import os;env=p.environment(Path(sys.argv[1]),p.PHASES[0]);"
        "assert all(os.environ[k]==v for k,v in env.items())"
    )
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True)
    assert not list(tmp_path.iterdir())


def test_bootstrap_refuses_in_process_scientific_import(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pymc", SimpleNamespace())
    with pytest.raises(ValueError, match="precede"):
        p.bootstrap(tmp_path, G)


@pytest.fixture
def runtime(program, monkeypatch):
    """Fake only the already frozen supervisor/worker/resource services."""
    c = program
    c.authority()
    state = dict(worker_calls=0, proof_calls=0, quota_calls=0)
    controls = {}
    events = []
    original_source = (c.root / p.SELF).read_bytes()

    @contextmanager
    def leases(root):
        paths = [root / "shared-global.lock", root / "shared-s5.lock"]
        for x in paths:
            x.write_bytes(b"owned shared lease")
        try:
            if controls.get("inside_lease_drift"):
                (root / p.SELF).write_bytes(b"foreign source drift")
            yield
        finally:
            for x in paths:
                x.unlink()
            if controls.get("late_drift"):
                (root / p.SELF).write_bytes(b"late foreign drift")

    def bootstrap(root, phase):
        events.append("bootstrap")

    def history(root, gate):
        # Frozen J.history checks these two old failure states. The new program
        # must separately conserve the third (S5) literal baseline hash.
        for name, field in [
            ("development-state.json", "original_state_sha256"),
            ("development-completion-state.json", "failed_continuation_state_sha256"),
        ]:
            assert p.sha(root / "context/runs/arrival-model-fitting-v1" / name) == gate[field]

    def quota(root, a, *, reserve, known_files):
        assert reserve and known_files and a["files"] == known_files
        state["quota_calls"] += 1
        if controls.get("quota") or (controls.get("quota_after_worker") and state["worker_calls"]):
            return "numerical_inventory_or_storage_failure"
        return None

    def inventory(*args):
        events.append("inventory")

    def byte_count(*paths):
        return sum(
            x.stat().st_size
            for path in paths
            for x in ([path] if path.is_file() else path.rglob("*"))
            if x.is_file()
        )

    def artifacts(root, job, pins):
        state["proof_calls"] += 1
        folder, raw, *_ = p.paths(root, job["role"], job)
        return {
            "files": hashes(
                root,
                [str(x.relative_to(root)) for x in folder.iterdir()] + [str(raw.relative_to(root))],
            )
        }

    worker = SimpleNamespace(
        verify_gate=lambda *args: {"files": read(c.root / p.KERNELS[G])["files"]},
        case_artifacts=artifacts,
    )

    def supervise(command, log, stop, timeout):
        assert timeout == 600 and stop == c.root / p.CONTROL / "STOP"
        events.append("supervise")
        assert events.index("bootstrap") < events.index("supervise")
        job_path = Path(command[command.index("--job") + 1])
        job = read(job_path)
        if "--proof-only" in command:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_bytes(b"proof log")
            if controls.get("proof_failure"):
                return dict(returncode=2, reason="worker_exit")
            output = Path(command[command.index("--proof-output") + 1])
            p.proof_only(c.root, job["role"], job_path, output)
        else:
            state["worker_calls"] += 1
            worker_bytes(c.root, job["role"], job)
            log.write_bytes(b"worker log")
            if controls.get("foreign_lease"):
                (c.root / p.CONTROL / ".lock").write_bytes(b"foreign lease replacement")
            if controls.get("timeout"):
                return dict(returncode=124, reason="timeout")
        return dict(returncode=0, reason="worker_exit", elapsed_seconds=0.01)

    legacy = p.CONTROL.replace("technical-completion-v1", "completion-after-gap-v1")
    fake = SimpleNamespace(
        CONTROL=legacy,
        allocation_path=lambda root, phase, job: (
            root / legacy / "allocations" / phase / (job["id"] + ".json")
        ),
        history=history,
        stops=lambda root: [],
        inventory=inventory,
        c2=SimpleNamespace(quota=quota),
        old=SimpleNamespace(
            consumer=lambda phase: worker,
            supervise=supervise,
            git_sha=lambda root: GIT,
            RECOVERY_CLI="scripts/check_arrival_development_recovery.py",
            r=SimpleNamespace(
                _leases=leases, byte_count=byte_count, MAX_JOB=32 * MIB, FILE_MAX=64 * MIB
            ),
        ),
    )

    def backend():
        assert "bootstrap" in events
        return fake

    import analysis.arrival as arrival_package

    stable_backend = SimpleNamespace(
        case_artifacts=lambda root, job, pins: {
            **artifacts(root, job, pins),
            "proof_contract": p.PROOF_CONTRACT,
            "original_exact_oracle_equal": False,
            "diagnostic_comparison": comparison(),
        }
    )
    monkeypatch.setitem(sys.modules, "analysis.arrival.model_development_replay", stable_backend)
    monkeypatch.setattr(arrival_package, "model_development_replay", stable_backend, raising=False)
    monkeypatch.setattr(p, "bootstrap", bootstrap)
    monkeypatch.setattr(p, "_runtime", backend)
    return SimpleNamespace(
        case=c, state=state, controls=controls, events=events, source=original_source
    )


def test_one_dispatch_and_fresh_proof_child_charge_only_one_new_sampler(runtime):
    r = runtime
    c = r.case
    result = p.run_one(c.root, G)
    assert r.state["worker_calls"] == r.state["proof_calls"] == 1
    assert result["calls_charged"] == result["calls_started"] == 4
    assert len(result["attempt_records"]) == 2 and len(result["accepted_records"]) == 4
    assert not (c.root / p.CONTROL / ".lock").exists()
    proof = read(p.proof_path(c.root, G, c.jobs[3]))
    assert proof["sampler_calls"] == 0 and proof["status"] == "scientific_artifact_replay_passed"


def test_third_actual_start_requires_legacy_plus_new_pilot(runtime):
    r = runtime
    c = r.case
    (c.root / p.PILOT).unlink()
    with pytest.raises(ValueError):
        p.run_one(c.root, G)
    assert r.state["worker_calls"] == 0
    assert p.program_counters(c.root) == dict(charged=3, started=3)
    assert not p.allocation_path(c.root, G, c.jobs[3]).exists()


def test_independent_pilot_allows_only_the_next_original_job(runtime):
    r = runtime
    c = r.case
    before = (c.root / p.PILOT).read_bytes()
    result = p.run_one(c.root, G)
    assert r.state["worker_calls"] == 1 and result["calls_started"] == 4
    assert result["attempt_records"][-1]["job_id"] == c.jobs[3]["id"]
    assert (c.root / p.PILOT).read_bytes() == before


@pytest.mark.parametrize(
    "fault", ["timeout", "proof_failure", "quota_after_worker", "foreign_lease"]
)
def test_paid_failure_retains_partial_bytes_and_never_retries(runtime, fault):
    r = runtime
    c = r.case
    r.controls[fault] = True
    with pytest.raises((ValueError, AssertionError)):
        p.run_one(c.root, G)
    assert r.state["worker_calls"] == 1
    assert p.program_counters(c.root) == dict(charged=4, started=4)
    assert p.paths(c.root, G, c.jobs[3])[1].read_bytes() == b"opaque non-NetCDF fixture bytes"
    failure = c.root / p.CONTROL / "failures" / (c.jobs[3]["id"] + ".json")
    assert failure.exists()
    if fault == "foreign_lease":
        assert (c.root / p.CONTROL / ".lock").read_bytes() == b"foreign lease replacement"
    r.controls.clear()
    with pytest.raises((ValueError, AssertionError)):
        p.run_one(c.root, G)
    assert r.state["worker_calls"] == 1


@pytest.mark.parametrize("fault", ["quota", "STOP", "inside_lease_drift"])
def test_prelaunch_failure_never_allocates(runtime, fault):
    r = runtime
    c = r.case
    if fault == "STOP":
        put(c.root, p.CONTROL + "/STOP", {"reason": "stop before launch"})
    else:
        r.controls[fault] = True
    with pytest.raises((ValueError, AssertionError)):
        p.run_one(c.root, G)
    assert r.state["worker_calls"] == 0
    assert p.program_counters(c.root) == dict(charged=3, started=3)
    assert not p.allocation_path(c.root, G, c.jobs[3]).exists()


def test_source_drift_after_lease_cleanup_cannot_disappear_into_success(runtime):
    r = runtime
    c = r.case
    r.controls["late_drift"] = True
    with pytest.raises(ValueError):
        p.run_one(c.root, G)
    assert p.program_counters(c.root) == dict(charged=4, started=4)
    (c.root / p.SELF).write_bytes(r.source)
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)
    assert (c.root / p.CONTROL / "failures" / (c.jobs[3]["id"] + ".json")).exists()


@pytest.mark.parametrize(
    "state_name",
    ["development-state.json", "development-completion-state.json", "sensitivity-state.json"],
)
def test_all_three_retained_private_histories_fail_closed_without_body_parse(runtime, state_name):
    r = runtime
    c = r.case
    private = c.root / "context/runs/arrival-model-fitting-v1" / state_name
    private.write_bytes(b"foreign private state mutation")
    with pytest.raises((ValueError, AssertionError)):
        p.run_one(c.root, G)
    assert r.state["worker_calls"] == 0
    assert private.read_bytes() == b"foreign private state mutation"


def test_proof_only_reuses_closed_worker_without_any_sampler(runtime):
    r = runtime
    c = r.case
    close_job(c, G, c.jobs[3])
    proof = p.proof_path(c.root, G, c.jobs[3])
    proof.unlink()
    before = p.program_counters(c.root)
    p.proof_only(c.root, G, p.paths(c.root, G, c.jobs[3])[2], proof)
    assert r.state["worker_calls"] == 0 and r.state["proof_calls"] == 1
    assert p.program_counters(c.root) == before == dict(charged=4, started=4)
    assert read(proof)["sampler_calls"] == 0


def test_proof_only_cannot_overwrite_existing_proof_or_reuse_legacy_G0(runtime):
    r = runtime
    c = r.case
    close_job(c, G, c.jobs[3])
    with pytest.raises(ValueError):
        p.proof_only(
            c.root, G, p.paths(c.root, G, c.jobs[3])[2], p.proof_path(c.root, G, c.jobs[3])
        )
    with pytest.raises(ValueError):
        p.proof_only(
            c.root, G, p.paths(c.root, G, c.jobs[0])[2], p.proof_path(c.root, G, c.jobs[0])
        )
    assert r.state["proof_calls"] == r.state["worker_calls"] == 0


def test_frozen_old_journal_entrypoints_are_not_used_by_new_launcher():
    import ast

    tree = ast.parse(Path(p.__file__).read_text())
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not any(
        isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "j"
        and n.attr in {"admit", "run", "all_records", "journal_records"}
        for n in calls
    )


def reseal_g2(case):
    """Reclose synthetic metadata so negatives exercise semantics, not stale hashes."""
    b = case.g2
    b["files"] = hashes(case.root, b["files"])
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
        b[key + "_sha256"] = p.sha(case.root / b[key])
    put(case.root, p.G2_REVIEW, b)
    case.authority()


def test_history_resolver_materializes_only_three_old_code_files(program):
    c = program
    resolved = p.historical_source_verify(c.root, c.old_code)
    assert not set(c.old_code) & set(resolved)
    assert set(resolved) == set(c.history["files"]) | {p.HISTORY_MANIFEST}
    p.fresh(c.root, resolved)
    with pytest.raises(ValueError):
        p.fresh(c.root, c.old_code)
    with pytest.raises(ValueError):
        p.historical_source_verify(c.root, c.old_code, "technical-completion-v2")


@pytest.mark.parametrize(
    "name",
    [
        "config/frozen-science.toml",
        p.FREEZE,
        p.KERNELS[G],
        "analysis/arrival/model_development_fit.py",
        "analysis/arrival/model_development_recovery.py",
        "scripts/run_arrival_development_journal.py",
        "context/runs/arrival-model-fitting-v1/sensitivity-state.json",
        "data/processed/models/frozen-reference.nc",
    ],
)
def test_scientific_data_config_kernels_and_context_never_use_archive_fallback(program, name):
    c = program
    if not (c.root / name).exists():
        put(c.root, name, b"original protected bytes")
    expected = p.sha(c.root / name)
    put(c.root, name, b"changed protected bytes")
    with pytest.raises(ValueError):
        p.historical_source_verify(c.root, {**c.old_code, name: expected})
    assert (c.root / name).read_bytes() == b"changed protected bytes"


@pytest.mark.parametrize(
    "fault", ["extra_binding", "producer", "git_blob", "alternate_hash", "epoch", "archive_bytes"]
)
def test_resealed_history_binding_cannot_expand_or_impersonate_source_epoch(
    program, monkeypatch, fault
):
    c = program
    m = read(c.root / p.HISTORY_MANIFEST)
    name = next(iter(c.old_code))
    entry = m["allowed_bindings"][name]
    if fault == "extra_binding":
        m["allowed_bindings"]["config/frozen-science.toml"] = dict(entry)
    elif fault == "producer":
        entry["producer_git_commit"] = "b" * 40
    elif fault == "git_blob":
        entry["git_blob_oid"] = "b" * 40
    elif fault == "alternate_hash":
        entry["expected_sha256"] = "b" * 64
    elif fault == "epoch":
        entry["recognized_source_epoch"] = "unreviewed-epoch"
    else:
        put(c.root, entry["archived_path"], b"changed archived source")
    put(c.root, p.HISTORY_MANIFEST, m)
    monkeypatch.setattr(p, "HISTORY_MANIFEST_SHA256", p.sha(c.root / p.HISTORY_MANIFEST))
    with pytest.raises(ValueError):
        p.historical_source_verify(c.root, c.old_code)


def test_epoch2_counts_paid_G2_once_without_inventing_receipt(program):
    c = program
    c.authority()
    a = p.read_program_metadata(c.root, G)
    assert a["calls_charged"] == a["calls_started"] == 3
    assert [x["job"]["id"] if "job" in x else x["job_id"] for x in a["accepted_records"]] == [
        j["id"] for j in c.jobs[:3]
    ]
    assert [x["job_id"] for x in a["attempt_records"]] == [c.jobs[1]["id"]]
    assert a["accepted_records"][2]["producer"] == "G2_stable_scientific_revalidation"
    assert a["accepted_records"][2]["original_controller_outcome"] == "failed_before_attempt"
    assert a["remaining_jobs"] == c.jobs[3:]
    assert not p.attempt_path(c.root, G, c.jobs[2]).exists()
    assert not p.legacy_proof_path(c.root, G, c.jobs[2]).exists()


@pytest.mark.parametrize(
    "fault",
    [
        "double_charge",
        "new_sampler",
        "claim_original_exact",
        "healed_attempt",
        "healed_old_proof",
        "worker_monitor",
        "failed_verifier_claims_success",
        "stable_contract",
        "stable_job",
        "stable_predicate_false",
        "stable_cross_run_tolerance",
    ],
)
def test_G2_review_cannot_heal_history_or_waive_scientific_predicates(program, fault):
    c = program
    b = c.g2
    if fault == "double_charge":
        b["calls_charged"] = 4
    elif fault == "new_sampler":
        b["new_sampler_calls"] = 1
    elif fault == "claim_original_exact":
        b["original_exact_oracle_guard_passed"] = True
    elif fault == "healed_attempt":
        put(
            c.root,
            p.attempt_path(c.root, G, c.jobs[2]).relative_to(c.root),
            {"outcome": "accepted"},
        )
    elif fault == "healed_old_proof":
        put(
            c.root,
            p.legacy_proof_path(c.root, G, c.jobs[2]).relative_to(c.root),
            {"status": "passed"},
        )
    elif fault in {"worker_monitor", "failed_verifier_claims_success"}:
        key = (
            "original_supervisor" if fault == "worker_monitor" else "original_failed_proof_process"
        )
        v = read(c.root / b[key])
        if fault == "worker_monitor":
            v["monitor_failures"] = ["actual resource failure"]
        else:
            v["returncode"] = 0
        put(c.root, b[key], v)
    else:
        v = read(c.root / b["stable_proof"])
        if fault == "stable_contract":
            v["proof_contract"] = "bitwise_original_G_pass_claim"
        elif fault == "stable_job":
            v["job"] = {**v["job"], "sampler_seed": 999}
        elif fault == "stable_predicate_false":
            v["diagnostic_comparison"]["original_scientific_predicates_passed"] = False
        else:
            v["diagnostic_comparison"]["cross_run_numeric_tolerance_used"] = True
        put(c.root, b["stable_proof"], v)
    reseal_g2(c)
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


def test_unknown_failure_is_never_covered_by_G2_technical_review(program):
    c = program
    c.authority()
    path = put(
        c.root, p.CONTROL + "/failures/unreviewed.json", {"charged": 1, "error": "new failure"}
    )
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)
    assert read(path)["error"] == "new failure"


def test_epoch2_plan_is_distinct_and_cannot_rewrite_historical_plan(program):
    c = program
    c.authority()
    old = p.legacy_plan_path(c.root, G)
    old_bytes = old.read_bytes()
    close_job(c, G, c.jobs[3])
    assert p.plan_path(c.root, G) != old and old.read_bytes() == old_bytes
    assert read(p.plan_path(c.root, G))["source_epoch"] == "technical-completion-v2"
    put(c.root, old.relative_to(c.root), {"rewritten_old_plan": True})
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)


def test_current_execution_source_cannot_borrow_its_old_archive_hash(program):
    c = program
    c.authority()
    archive = c.history["allowed_bindings"][p.SELF]["archived_path"]
    (c.root / p.SELF).write_bytes((c.root / archive).read_bytes())
    with pytest.raises(ValueError):
        p.read_program_metadata(c.root, G)
