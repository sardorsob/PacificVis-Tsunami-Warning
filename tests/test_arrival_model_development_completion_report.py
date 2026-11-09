"""Synthetic saved-table adapter checks; native arrays and scoring are forbidden."""

# pyright: basic
import copy
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

from analysis.arrival import model_development_completion_report as r
from analysis.arrival.evidence import sha256, write_json
from tests import test_arrival_model_development_report as legacy_tests


def legacy_fixture(root, monkeypatch):
    """Include the real freeze's shape without parsing any legacy ledger body."""
    writer = legacy_tests.write_json

    def with_ledgers(path, value):
        if path == root / r.data.FREEZE:
            inherited = {}
            for i in range(12):
                name = f"context/immutable-ledgers/ledger-{i:02}.json"
                ledger = root / name
                ledger.parent.mkdir(parents=True, exist_ok=True)
                ledger.write_bytes(b"opaque immutable ledger; deliberately not JSON")
                inherited[name] = sha256(ledger)
            value["files"] = {**value.get("files", {}), **inherited}
        writer(path, value)

    with monkeypatch.context() as local:
        local.setattr(legacy_tests, "write_json", with_ledgers)
        return legacy_tests.fixture(root, monkeypatch)


class UpstreamAdmissionReached(Exception):
    pass


def ledger_admission_fixture(root, monkeypatch):
    needed = set(r.CONSUMED) | {
        r.data.FREEZE, r.data.MS5_REVIEW, r.data.CHECK_REVIEW, r.old.SMOKE_REVIEW,
        r.fit.GATE, r.fit.FULL_GATE, r.recovery.GATE, r.CASE0_REVIEW, r.CASE1_REVIEW,
        r.BASELINE, *r.AUTHORITY.values(), *r.SUMMARIES.values(),
    }
    for name in needed:
        write_json(root / name, {})
    inherited = {}
    for i in range(12):
        name = f"context/immutable-ledgers/ledger-{i:02}.json"
        ledger = root / name
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"opaque immutable ledger; deliberately not JSON")
        inherited[name] = sha256(ledger)
    freeze = {"files": inherited}
    write_json(root / r.data.FREEZE, freeze)
    pins = {name: sha256(root / name) for name in needed} | inherited
    gate = dict(
        status="accepted_frozen_full_development_fits", independent_checker=True,
        confirmation_outcomes_parsed=True, development_check_previously_inspected=True,
        reserved_outcomes="sealed", reserved_outcomes_parsed=False,
        specification_freeze=r.data.FREEZE, specification_freeze_sha256=pins[r.data.FREEZE],
        files=pins,
    )

    def save():
        write_json(root / r.GATE, gate)

    def admitted(*args):
        raise UpstreamAdmissionReached()

    save()
    monkeypatch.setattr(r.fit, "verify_gate", admitted)
    return gate, freeze, save


def test_exact12_inherited_opaque_ledgers_reach_admission_without_json_parsing(
    tmp_path, monkeypatch
):
    ledger_admission_fixture(tmp_path, monkeypatch)
    with pytest.raises(UpstreamAdmissionReached):
        r.verify_report_sources(tmp_path)


@pytest.mark.parametrize(
    "fault", ["omitted", "extra", "original_live_state", "continuation_live_state",
              "mismatched_hash", "non_json", "embedded_context", "freeze_hash",
              "inherited_live_state"],
)
def test_invalid_ledger_map_rejected_before_any_context_hash(tmp_path, monkeypatch, fault):
    gate, freeze, save = ledger_admission_fixture(tmp_path, monkeypatch)
    key = next(iter(freeze["files"]))
    pins = gate["files"]
    if fault == "omitted":
        pins.pop(key)
    elif fault == "extra":
        pins["context/unreviewed.json"] = "f" * 64
    elif fault == "original_live_state":
        pins[r.old.PRIVATE_STATE] = "f" * 64
    elif fault == "continuation_live_state":
        pins["context/runs/arrival-model-fitting-v1/development-completion-state.json"] = "f" * 64
    elif fault == "mismatched_hash":
        pins[key] = "f" * 64
    elif fault == "embedded_context":
        pins["artifacts/context/unreviewed.json"] = "f" * 64
    elif fault == "freeze_hash":
        pins[r.data.FREEZE] = "f" * 64
    else:
        destination = (
            key.removesuffix(".json") + ".txt" if fault == "non_json" else r.old.PRIVATE_STATE
        )
        freeze["files"][destination] = freeze["files"].pop(key)
        pins[destination] = pins.pop(key)
        write_json(tmp_path / r.data.FREEZE, freeze)
        pins[r.data.FREEZE] = sha256(tmp_path / r.data.FREEZE)
        gate["specification_freeze_sha256"] = pins[r.data.FREEZE]
    save()
    real = r.data._unchanged

    def before_hash(root, refs):
        if any("context/" in name for name in refs):
            pytest.fail("Invalid context map reached hashing")
        return real(root, refs)

    monkeypatch.setattr(r.data, "_unchanged", before_hash)
    with pytest.raises(ValueError):
        r.verify_report_sources(tmp_path)


def add_allocation(root, job, phase, record):
    worker = r.recovery if phase == "full_design_recovery" else r.fit
    folder, raw = worker.case_paths(root, job)
    spec = folder.with_name(folder.name + "-spec.json")
    process = folder.with_name(folder.name + ".supervisor.json")
    kernel = {
        "check": r.fit.GATE,
        "full_design_recovery": r.recovery.GATE,
        "full_development": r.fit.FULL_GATE,
    }[phase]
    plan = r.CONTROL + "/plans/" + phase + ".json"
    path = r.CONTROL + f"/allocations/{phase}/{job['id']}.json"
    allocation = dict(
        phase=phase,
        job_id=job["id"],
        job=job,
        role=job["role"],
        cost=int(raw is not None),
        plan=plan,
        plan_sha256=sha256(root / plan),
        authority_gate=r.AUTHORITY[phase],
        authority_gate_sha256=sha256(root / r.AUTHORITY[phase]),
        worker_gate=kernel,
        worker_gate_sha256=sha256(root / kernel),
        spec=str(spec.relative_to(root)),
        spec_sha256=sha256(spec),
        invocation_git_sha="a" * 40,
    )
    write_json(root / path, allocation)
    supervisor = json.loads(process.read_text())
    supervisor.update(
        allocation=path,
        allocation_sha256=sha256(root / path),
        invocation_git_sha=allocation["invocation_git_sha"],
    )
    write_json(process, supervisor)
    record.update(allocation=path, allocation_sha256=sha256(root / path))
    record["files"].update(
        {path: sha256(root / path), str(process.relative_to(root)): sha256(process)}
    )


def ordinary_fixture(root, monkeypatch, *, phase="full_development"):
    _, _, admissions = legacy_fixture(root, monkeypatch)
    role = "full_development" if phase == "full_development" else "check_evaluate"
    admission = admissions[role]
    job = admission["gate"]["jobs"][0]
    folder, raw = r.fit.case_paths(root, job)
    authority = dict(jobs=admission["gate"]["jobs"], files=admission["files"])
    write_json(root / r.AUTHORITY[phase], authority)
    plan = r.CONTROL + "/plans/" + phase + ".json"
    write_json(
        root / plan,
        dict(
            phase=phase,
            gate=r.AUTHORITY[phase],
            jobs=authority["jobs"],
            files={**authority["files"], r.AUTHORITY[phase]: sha256(root / r.AUTHORITY[phase])},
        ),
    )
    process = folder.with_name(folder.name + ".supervisor.json")
    supervisor = json.loads(process.read_text())
    supervisor.update(
        plan_sha256=sha256(root / plan),
        authority_gate_sha256=sha256(root / r.AUTHORITY[phase]),
        worker_gate_sha256=sha256(root / (r.fit.FULL_GATE if raw is not None else r.fit.GATE)),
    )
    write_json(process, supervisor)
    original_receipt = root / r.old.CONTROL / "attempts" / phase / (job["id"] + ".json")
    record = json.loads(original_receipt.read_text())
    receipt = r.CONTROL + f"/attempts/{phase}/{job['id']}.json"
    record["receipt"] = receipt
    record["gap_eligible"] = False
    add_allocation(root, job, phase, record)

    def seal():
        manifest = json.loads((folder / "output-checksums.json").read_text())
        manifest = {name: sha256(folder / name) for name in manifest}
        write_json(folder / "output-checksums.json", manifest)
        workers = {str((folder / n).relative_to(root)): h for n, h in manifest.items()}
        workers[str((folder / "output-checksums.json").relative_to(root))] = sha256(
            folder / "output-checksums.json"
        )
        if raw is not None:
            workers[str(raw.relative_to(root))] = sha256(raw)
        record["worker_files"] = workers
        record["files"].update(workers)
        for path in [
            process,
            folder.with_name(folder.name + "-spec.json"),
            folder.with_name(folder.name + ".log"),
        ]:
            record["files"][str(path.relative_to(root))] = sha256(path)
        write_json(root / receipt, record)
        return {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}

    return job, admission, folder, process, record, seal


@pytest.mark.parametrize("phase", ["check", "full_development"])
def test_ordinary_saved_metadata_has_exact_dual_authority_and_no_native_reads(
    tmp_path, monkeypatch, phase
):
    job, admission, _, _, _, seal = ordinary_fixture(tmp_path, monkeypatch, phase=phase)
    pins = seal()
    case = r._ordinary_case(tmp_path, pins, admission, job, phase, pins)
    assert case["job"] == job and case["public_record"]["outcome"] == "accepted"
    assert case["receipt"].startswith(r.CONTROL + "/attempts/")


@pytest.mark.parametrize(
    "fault",
    ["authority", "kernel", "cost", "markers", "returncode", "monitor", "raw", "prior", "plan"],
)
def test_resealed_wrong_success_metadata_cannot_reach_saved_tables(tmp_path, monkeypatch, fault):
    job, admission, folder, process, _, seal = ordinary_fixture(tmp_path, monkeypatch)
    value = json.loads(process.read_text())
    if fault in {"authority", "kernel"}:
        value["authority_gate_sha256" if fault == "authority" else "worker_gate_sha256"] = "f" * 64
    elif fault in {"cost", "returncode"}:
        value[fault] = 9
    elif fault == "markers":
        value["start_markers"] = 0
    elif fault == "monitor":
        value["monitor_failures"] = ["late source drift"]
    elif fault == "raw":
        result = json.loads((folder / "result.json").read_text())
        result["posterior_sha256"] = None
        write_json(folder / "result.json", result)
    elif fault == "prior":
        prior = json.loads((folder / "prior-settings.json").read_text())
        prior["base_prior"]["alpha_sd"] = 99
        write_json(folder / "prior-settings.json", prior)
    else:
        path = tmp_path / r.CONTROL / "plans/full_development.json"
        plan = json.loads(path.read_text())
        plan["files"] = {}
        write_json(path, plan)
        value["plan_sha256"] = sha256(path)
    write_json(process, value)
    pins = seal()
    with pytest.raises(ValueError):
        r._ordinary_case(tmp_path, pins, admission, job, "full_development", pins)


def test_mixed_mcse_view_is_a_labelled_copy_not_a_new_score():
    original = dict(
        status=r.fit.SUCCESS,
        precision_passed=True,
        equal_event_score=-5.2,
        mcse_triangle_bound=0.0013,
    )
    before = copy.deepcopy(original)
    value = r._aggregate_view(original)
    assert value is not None
    assert original == before
    assert value["equal_event_score"] == -5.2 and value["mcse_equal_event_score"] == 0.0013
    assert value["source_status"] == r.fit.SUCCESS
    assert value["mcse_kind"] == "conservative_sum_of_estimated_MCSEs"


@pytest.mark.parametrize("value", [None, {"precision_passed": False, "equal_event_score": 99}])
def test_unresolved_aggregate_never_publishes_partial_or_diagnostic_estimate(value):
    assert r._aggregate_view(value) is None


@pytest.mark.parametrize("fault", ["missing", "nan", "negative", "wrong_status", "nonfinite_score"])
def test_invalid_saved_numerical_uncertainty_is_not_invented(fault):
    value = dict(
        status=r.fit.SUCCESS,
        precision_passed=True,
        equal_event_score=-5.2,
        mcse_triangle_bound=0.001,
    )
    if fault == "missing":
        value.pop("mcse_triangle_bound")
    elif fault == "nan":
        value["mcse_triangle_bound"] = float("nan")
    elif fault == "negative":
        value["mcse_triangle_bound"] = -1
    elif fault == "wrong_status":
        value["status"] = "needs_numerical_review"
    else:
        value["equal_event_score"] = float("inf")
    with pytest.raises(ValueError):
        r._aggregate_view(value)


def test_reader_note_keeps_failure_and_labels_the_sum_of_mcse_estimates(monkeypatch):
    value = r._aggregate_view(
        dict(
            status=r.fit.SUCCESS,
            precision_passed=True,
            equal_event_score=-5.2,
            mcse_triangle_bound=0.001,
        )
    )
    text = "# Result\n\nReserved events sealed.\n\n## NCEI\n" + r.old._score(value)
    monkeypatch.setattr(r.old, "render_markdown", lambda summary: text)
    summary = {
        "lanes": [{"checks": [{"aggregate": value, "aggregate_without_crossing_event": None}]}]
    }
    saved = r.render_markdown(summary)
    assert saved.index("original numerical precision failure") < saved.index("## NCEI")
    assert "without assuming independence" in saved and "not a finite-bias bound" in saved
    assert "sum of MCSE estimates" in saved and "Reserved events sealed" in saved


@pytest.mark.parametrize(
    "fault", ["status", "independence", "exposure", "reserved", "missing_source"]
)
def test_incomplete_final_review_rejects_before_any_saved_table(tmp_path, monkeypatch, fault):
    gate = dict(
        status="accepted_frozen_full_development_fits",
        independent_checker=True,
        confirmation_outcomes_parsed=True,
        development_check_previously_inspected=True,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        files={},
    )
    if fault == "status":
        gate["status"] = "pending"
    elif fault == "independence":
        gate["independent_checker"] = False
    elif fault == "exposure":
        gate["development_check_previously_inspected"] = False
    elif fault == "reserved":
        gate["reserved_outcomes_parsed"] = True
    write_json(tmp_path / r.GATE, gate)
    monkeypatch.setattr(r, "read_rows", lambda *a: pytest.fail("table read before source closure"))
    with pytest.raises(ValueError):
        r.verify_report_sources(tmp_path)


def expand_check_fixture(root, admissions):
    """Keep all six logical frozen checks, including each lane's alternative."""
    check, full = admissions["check_evaluate"], admissions["full_development"]
    jobs = []
    for index, selected in enumerate(list(check["gate"]["jobs"])):
        target, model = check["specs"][selected["model_key"]]
        selected["order"] = 2 * index
        folder, _ = r.fit.case_paths(root, selected)
        job_path = folder / "job.json"
        write_json(job_path, selected)
        result = json.loads((folder / "result.json").read_text())
        result["job"] = selected
        write_json(folder / "result.json", result)
        alternative = {
            **model,
            "role": "runner_up",
            "kind": {
                "NCEI-native-duration": "distance-scale",
                "T-OBS": "distance",
                "T-CAL": "event",
            }[target],
        }
        key = f"{target}:{alternative['kind']}:runner_up"
        check["specs"][key] = (target, alternative)
        check["freeze"]["models"][target].append(alternative)
        slug = {"NCEI-native-duration": "ncei", "T-OBS": "tobs", "T-CAL": "tcal"}[target]
        other = dict(
            id=f"dev-{slug}-{alternative['kind']}-runner-up-check",
            order=2 * index + 1,
            role="check_evaluate",
            model_key=key,
            seed=2976110900 + 200 * index,
            training_reference={"kind": "historical"},
        )
        other_folder, _ = r.fit.case_paths(root, other)
        shutil.copytree(folder, other_folder)
        write_json(other_folder / "job.json", other)
        result["job"] = other
        write_json(other_folder / "result.json", result)
        inputs = json.loads((other_folder / "inputs.json").read_text())
        inputs["model_spec"] = alternative
        write_json(other_folder / "inputs.json", inputs)
        jobs.extend([selected, other])
    check["gate"]["jobs"][:] = jobs
    write_json(root / r.data.FREEZE, check["freeze"])
    check["files"][r.data.FREEZE] = sha256(root / r.data.FREEZE)
    full["files"][r.data.FREEZE] = check["files"][r.data.FREEZE]
    for job in jobs + full["gate"]["jobs"]:
        folder, _ = r.fit.case_paths(root, job)
        inputs = json.loads((folder / "inputs.json").read_text())
        inputs["files"] = check["files"]
        inputs["specification_freeze_sha256"] = check["files"][r.data.FREEZE]
        write_json(folder / "inputs.json", inputs)
        manifest = json.loads((folder / "output-checksums.json").read_text())
        write_json(folder / "output-checksums.json", {n: sha256(folder / n) for n in manifest})

    ms5_inputs = (root / r.data.MS5_REVIEW).parent / "inputs.json"
    value = json.loads(ms5_inputs.read_text())
    value["files"] = {n: sha256(root / n) for n in value["files"]}
    write_json(ms5_inputs, value)
    ms5_review = json.loads((root / r.data.MS5_REVIEW).read_text())
    ms5_review["files"] = {n: sha256(root / n) for n in ms5_review["files"]}
    write_json(root / r.data.MS5_REVIEW, ms5_review)


def resolved_fixture(root, monkeypatch, *, unresolved=False):
    """Production-shaped compact receipts; no integration or native arrays.

    Only upstream native admission is stubbed. The real resolver byte inventory,
    complete512-block prefix validation and both strict independent anchors run.
    """
    _, _, admissions = legacy_fixture(root, monkeypatch)
    expand_check_fixture(root, admissions)
    admission = admissions["check_evaluate"]
    job = admission["gate"]["jobs"][0]
    before, _ = r.fit.case_paths(root, job)
    job["id"] = "dev-ncei-mean-curvature-selected-check"
    folder, _ = r.fit.case_paths(root, job)
    before.rename(folder)
    for suffix in ["-spec.json", ".log", ".supervisor.json"]:
        before.with_name(before.name + suffix).rename(folder.with_name(folder.name + suffix))
    original = json.loads((folder / "result.json").read_text())
    original.update(job=job, status="needs_numerical_review", sampler_call_started=False)
    write_json(folder / "result.json", original)
    prediction = str((folder / "held-out-record-predictions.csv").relative_to(root))
    m = r.numerical
    for name in m.CONSUMED:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic closed source")
    numerical: dict[str, Any] = dict(
        status="accepted_frozen_arrival_development_numerical_resolution_execution",
        independent_checker=True,
        reserved_outcomes="sealed",
        source_role="frozen_check_numerical_resolution",
        protocol=m.protocol(),
        resources=m.resources(),
        job=m.job_descriptor(),
        sampler_calls=0,
    )
    write_json(root / m.GATE, numerical)
    source_names = [
        "source.txt",
        r.data.FREEZE,
        m.SELF,
        m.CLI,
        m.TEST,
        prediction,
        str((folder / "event-results.json").relative_to(root)),
        str((folder / "direct-score-arrays.npz").relative_to(root)),
    ]

    def source_pins():
        return {n: sha256(root / n) for n in source_names + [m.GATE]}

    def native_admission(root):
        gate = json.loads((root / m.GATE).read_text())
        r.require(
            gate["status"] == numerical["status"]
            and gate["independent_checker"] is True
            and gate["protocol"] == m.protocol()
            and gate["resources"] == m.resources()
            and gate["job"] == m.job_descriptor()
            and gate["sampler_calls"] == 0,
            "unchanged fixture metadata admission required",
        )
        pins = source_pins()
        return dict(files=pins, original_files={prediction: pins[prediction]}, original_job=job)

    monkeypatch.setattr(m, "verify_gate", native_admission)
    for name in ["integrate", "replay_resolution", "load_case"]:
        monkeypatch.setattr(
            m, name, lambda *a, **k: pytest.fail("reader attempted numerical/native work")
        )
    output = root / m.CASE_OUTPUT
    output.mkdir(parents=True)
    prefixes = []
    cfg = m.protocol()
    for df in cfg["proposal_df"]:
        for rep, seed in enumerate(cfg["scrambles"]):
            digest = hashlib.sha256()
            for first in range(0, max(cfg["levels"]), cfg["stream_block_size"]):
                count = first + cfg["stream_block_size"]
                block_hash = hashlib.sha256(f"analytic-toy-{df}-{rep}-{first}".encode()).hexdigest()
                digest.update(bytes.fromhex(block_hash))
                offset = -40.0 + (2.0 if unresolved and df == 9 else 0.0)
                den = dict(
                    count=count,
                    log_sum=math.log(count),
                    log_sum_squares=math.log(count),
                    maximum=0.0,
                )
                num = dict(
                    count=count,
                    log_sum=math.log(count) + offset,
                    log_sum_squares=math.log(count) + 2 * offset,
                    maximum=offset,
                )
                write_json(
                    output / f"blocks/df{df}-rep{rep}-{first:06d}.json",
                    dict(
                        df=df,
                        replicate=rep,
                        seed=seed,
                        first=first,
                        count=cfg["stream_block_size"],
                        last_exclusive=count,
                        block_sha256=block_hash,
                        cumulative_stream_sha256=digest.hexdigest(),
                        training=den,
                        numerator=num,
                        probes=[],
                    ),
                )
                if count in cfg["levels"]:
                    ds, ns = m.sum_summary(den), m.sum_summary(num)
                    joint = ns["log_integral"] - ds["log_integral"]
                    prefixes.append(
                        dict(
                            df=df,
                            replicate=rep,
                            seed=seed,
                            n=count,
                            training=ds,
                            numerator=ns,
                            joint_log_predictive=joint,
                            normalized_score=joint / cfg["event_records"],
                            cumulative_stream_sha256=digest.hexdigest(),
                        )
                    )
    stream = dict(prefixes=prefixes, blocks=512, unique_nodes=2097152)
    resolution = m.summarize_integration(stream)
    primary = dict(
        status=r.fit.SUCCESS,
        precision_passed=True,
        equal_event_score=-0.25,
        mcse_triangle_bound=0.001,
    )
    aggregates = dict(
        available=not unresolved,
        primary=None if unresolved else primary,
        without_crossing_event=None,
        supplement_available=False,
    )
    proof_admission = native_admission(root)
    result = m._result(proof_admission, resolution, aggregates)
    values = {
        "job.json": m.job_descriptor(),
        "inputs.json": dict(
            files=proof_admission["files"],
            protocol=m.protocol(),
            resources=m.resources(),
            original_job=job,
        ),
        "proposal.json": {},
        "runtime.json": dict(
            libraries=m.library_versions(),
            protocol=m.protocol(),
            source_gate_sha256=proof_admission["files"][m.GATE],
            training_posterior_sha256=m.RAW_SHA,
            quadrature_is_not_mcmc=True,
            store_full_nodes=False,
        ),
        "integration-start.json": dict(
            job=m.job_descriptor(), sampler_calls=0, protocol_sha256=m.fingerprint(m.protocol())
        ),
        "stream-summary.json": stream,
        "precision.json": resolution,
        "aggregate-diagnostics.json": aggregates,
        "result.json": result,
    }
    for name, value in values.items():
        write_json(output / name, value)
    cold: dict[str, Any] = dict(
        status=m.COLD_REVIEW_STATUS,
        independent_checker=True,
        sampler_calls=0,
        reserved_outcomes="sealed",
        source_role="frozen_check_numerical_resolution",
        job=m.job_descriptor(),
        original_job=job,
        execution_gate=m.GATE,
        execution_gate_sha256=sha256(root / m.GATE),
        protocol_sha256=m.fingerprint(m.protocol()),
        worker_sources={n: sha256(root / n) for n in [m.SELF, m.CLI, m.TEST]},
        full_stream_replay=dict(passed=True, blocks=512, unique_nodes=2097152, sampler_calls=0),
    )
    disposition: dict[str, Any] = dict(
        status=m.REVIEW_STATUS,
        independent_checker=True,
        reserved_outcomes="sealed",
        original_job=job,
        original_state_sha256=m.ORIGINAL_STATE_SHA,
        specification_freeze_sha256=sha256(root / r.data.FREEZE),
        case0_outcome="accepted_unresolved_gap" if unresolved else "accepted_resolution",
        primary_aggregate_available=not unresolved,
        prediction_file=prediction,
        prediction_sha256=sha256(root / prediction),
        resolved_result=None if unresolved else m.CASE_OUTPUT + "/result.json",
        resolved_result_sha256=None,
    )

    def seal():
        write_json(output / "result.json", result)
        manifest = {
            str(p.relative_to(output)): sha256(p)
            for p in output.rglob("*")
            if p.is_file() and p.name != "output-checksums.json"
        }
        write_json(output / "output-checksums.json", manifest)
        candidate = {m.CASE_OUTPUT + "/" + n: h for n, h in manifest.items()}
        candidate[m.CASE_OUTPUT + "/output-checksums.json"] = sha256(
            output / "output-checksums.json"
        )
        # Preserve intentionally corrupted test values rather than silently repairing them.
        cold.setdefault("candidate_files", candidate)
        cold.setdefault("computed_status", result["status"])
        base = {**source_pins(), **candidate}
        cold.setdefault("files", base)
        # Re-seal candidate bytes while keeping omissions introduced by adversarial tests.
        cold["candidate_files"] = {n: sha256(root / n) for n in cold["candidate_files"]}
        cold["files"] = {n: sha256(root / n) for n in cold["files"]}
        write_json(root / r.COLD_REVIEW, cold)
        if not unresolved:
            disposition["resolved_result_sha256"] = sha256(output / "result.json")
        disposition["files"] = {**base, r.COLD_REVIEW: sha256(root / r.COLD_REVIEW)}
        write_json(root / r.CASE0_REVIEW, disposition)
        return {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}

    seal()
    return admission, disposition, result, cold, seal


@pytest.mark.parametrize("unresolved", [False, True])
def test_typed_resolution_preserves_original_failure_and_prediction_source(
    tmp_path, monkeypatch, unresolved
):
    admission, disposition, _, _, seal = resolved_fixture(
        tmp_path, monkeypatch, unresolved=unresolved
    )
    case = r._resolved_case(tmp_path, seal(), admission, disposition)
    assert case["result"]["status"] == "needs_numerical_review"
    assert case["prediction_path"] == disposition["prediction_file"]
    assert (case["resolution"] is None) is unresolved


@pytest.mark.parametrize(
    "fault",
    [
        "prediction",
        "missing_cold",
        "partial_stream",
        "protocol",
        "worker_source",
        "candidate",
        "new_calls",
        "derived_role",
        "unknown_outcome",
    ],
)
def test_resealed_resolution_cannot_bypass_typed_cold_or_original_source_contract(
    tmp_path, monkeypatch, fault
):
    admission, disposition, result, cold, seal = resolved_fixture(tmp_path, monkeypatch)
    assert result is not None and cold is not None
    if fault == "prediction":
        disposition["prediction_sha256"] = "f" * 64
    elif fault == "missing_cold":
        cold["status"] = "pending"
    elif fault == "partial_stream":
        cold["full_stream_replay"]["blocks"] = 511
    elif fault == "protocol":
        cold["protocol_sha256"] = "f" * 64
    elif fault == "worker_source":
        cold["worker_sources"] = {}
    elif fault == "candidate":
        cold["candidate_files"] = {}
    elif fault == "new_calls":
        result["sampler_calls"] = 1
    elif fault == "derived_role":
        result["source_role"] = "ordinary_success"
    else:
        disposition["case0_outcome"] = "unknown"
    pins = seal()
    with pytest.raises(ValueError):
        r._resolved_case(tmp_path, pins, admission, disposition)


def add_case1_gap(root, monkeypatch, admission) -> dict[str, Any]:
    job = admission["gate"]["jobs"][1]
    folder, _ = r.fit.case_paths(root, job)
    result = json.loads((folder / "result.json").read_text())
    result.update(status="needs_numerical_review", sampler_call_started=False, prediction_rows=1)
    for key in ["aggregate", "aggregate_without_crossing_event"]:
        result[key] = dict(
            status="needs_numerical_review",
            precision_passed=False,
            equal_event_score=999,
            diagnostic_estimate_only=True,
        )
    write_json(folder / "result.json", result)
    manifest = json.loads((folder / "output-checksums.json").read_text())
    write_json(folder / "output-checksums.json", {n: sha256(folder / n) for n in manifest})
    plan_name = r.LEGACY_CONTROL + "/check-plan.json"
    authority = str(Path(r.fit.GATE).parent / "completion-v1/check/review-acceptance.json")
    gate = dict(jobs=admission["gate"]["jobs"][1:], files=admission["files"])
    write_json(root / authority, gate)
    write_json(
        root / plan_name,
        dict(
            phase="check",
            gate=authority,
            jobs=gate["jobs"],
            files={**gate["files"], authority: sha256(root / authority)},
        ),
    )
    spec, log, process = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    write_json(spec, job)
    log.write_text("synthetic retained numerical failure")
    write_json(
        process,
        dict(
            returncode=2,
            reason="worker_exit",
            monitor_failures=[],
            cost=0,
            start_markers=0,
            job_sha256=sha256(spec),
            plan_sha256=sha256(root / plan_name),
            authority_gate_sha256=sha256(root / authority),
            worker_gate_sha256=sha256(root / r.fit.GATE),
        ),
    )
    persistent = {
        str(p.relative_to(root)): sha256(p) for p in [*folder.iterdir(), spec, log, process]
    }
    receipt = r.LEGACY_CONTROL + f"/attempts/check/{job['id']}.json"
    record = dict(
        job_id=job["id"],
        phase="check",
        role="check_evaluate",
        cost=0,
        start_markers=0,
        outcome="needs_review",
        receipt=receipt,
        files=persistent,
        worker_files={},
    )
    write_json(root / receipt, record)
    baseline = dict(
        schema_version=1,
        status="frozen_failed_development_continuation_history",
        original_state_sha256=r.numerical.ORIGINAL_STATE_SHA,
        failed_continuation_state_sha256=r.FAILED_STATE_SHA,
        calls_charged=0,
        calls_started=0,
        reserved_outcomes="sealed",
        private_state_bodies_copied=False,
        failed_attempt={**record, "receipt_sha256": sha256(root / receipt)},
        unattempted_job_ids=[j["id"] for j in admission["gate"]["jobs"][2:]],
        source_references={
            p: sha256(root / p) for p in [plan_name, authority, receipt, r.CASE0_REVIEW]
        },
    )
    write_json(root / r.BASELINE, baseline)
    monkeypatch.setattr(r, "BASELINE_SHA", sha256(root / r.BASELINE))
    prediction = str((folder / "held-out-record-predictions.csv").relative_to(root))
    review = dict(
        status="accepted_frozen_development_runner_up_numerical_gap",
        independent_checker=True,
        original_job=job,
        case1_outcome="accepted_unresolved_gap",
        original_result_status="needs_numerical_review",
        original_worker_result_status="needs_numerical_review",
        controller_attempt_outcome="needs_review",
        primary_aggregate_available=False,
        without_crossing_aggregate_available=False,
        resolved_result=None,
        resolved_result_sha256=None,
        original_state_sha256=r.numerical.ORIGINAL_STATE_SHA,
        failed_continuation_state_sha256=r.FAILED_STATE_SHA,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        no_retuning=True,
        no_model_or_prior_change=True,
        no_observation_change=True,
        no_retry_or_additional_integration=True,
        completed_six_check_protocol_accepted=False,
        curvature_winner_claimed=False,
        equivalence_claimed=False,
        model_rejected=False,
        sampler_calls_charged=0,
        sampler_calls_started=0,
        new_sampler_calls=0,
        prediction_file=prediction,
        prediction_sha256=sha256(root / prediction),
        prediction_rows=1,
        prediction_rows_precision_passed=1,
        original_attempt_persistent_files=persistent,
    )
    for key, path in [
        ("baseline_history", r.BASELINE),
        ("original_attempt_receipt", receipt),
        ("plan", plan_name),
        ("execution_authority_gate", authority),
        ("worker_gate", r.fit.GATE),
        ("original_result", str((folder / "result.json").relative_to(root))),
        ("specification_freeze", r.data.FREEZE),
        ("case0_review", r.CASE0_REVIEW),
    ]:
        review[key], review[key + "_sha256"] = path, sha256(root / path)
    review["files"] = {
        **admission["files"],
        **persistent,
        **{
            p: sha256(root / p)
            for p in [
                r.BASELINE,
                receipt,
                plan_name,
                authority,
                r.fit.GATE,
                r.data.FREEZE,
                r.CASE0_REVIEW,
            ]
        },
    }
    write_json(root / r.CASE1_REVIEW, review)
    return review


def complete_fixture(root, monkeypatch, unresolved=False):
    """Full saved-table path with all6real-shaped G process/attempt receipts."""
    check, disposition, _, _, seal_case = resolved_fixture(root, monkeypatch, unresolved=unresolved)
    add_case1_gap(root, monkeypatch, check)
    full = r.fit.verify_gate(root, "full_development")
    freeze = full["freeze"]
    for name in r.CONSUMED:
        if not (root / name).exists():
            write_json(root / name, {"synthetic": "closed source"})
    smoke_jobs = r.recovery.jobs(freeze)
    smoke = dict(
        gate={"jobs": smoke_jobs}, files=check["files"], freeze=freeze, specs=full["specs"]
    )
    monkeypatch.setattr(r.recovery, "verify_gate", lambda root: smoke)

    def smoke_paths(root, job):
        return root / r.recovery.OUTPUT / "jobs" / job["id"], root / r.recovery.STORE / (
            job["id"] + ".nc"
        )

    monkeypatch.setattr(r.recovery, "case_paths", smoke_paths)
    for job in smoke_jobs:
        folder, raw = smoke_paths(root, job)
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"synthetic opaque NC hash only")
        target, model = smoke["specs"][job["model_key"]]
        base, wider, effective = r.fit._priors(root, target, model)
        objects = {
            "job.json": job,
            "inputs.json": dict(
                files=smoke["files"], model_spec=model, protocol=r.recovery.protocol()
            ),
            "membership.json": dict(truth=job["truth"]),
            "sampling-start.json": job,
            "prior-settings.json": dict(base_prior=base, wider_prior=wider, **effective),
            "diagnostics.json": {"screen_passed": True},
            "numerical-oracles.json": {"passed": True},
            "summary.json": {key: [] for key in r.old.TABLES},
            "result.json": dict(
                job=job,
                status=r.fit.SUCCESS,
                confirmation_outcomes_parsed=True,
                reserved_outcomes="sealed",
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
                diagnostics={"screen_passed": True},
                sampler_call_started=True,
                numerical_oracles_passed=True,
                scope=r.recovery.protocol()["scope"],
                calibration_or_coverage_claim=False,
            ),
        }
        for name, value in objects.items():
            write_json(folder / name, value)
        for name in [
            "sampling-diagnostics.csv",
            "truth-quantiles.csv",
            *[k.replace("_", "-") + ".csv" for k in r.old.TABLES],
        ]:
            (folder / name).write_text("synthetic_saved_header\n")
        write_json(folder / "output-checksums.json", {p.name: sha256(p) for p in folder.iterdir()})
    jobs = {
        "check": check["gate"]["jobs"][2:],
        "full_design_recovery": smoke_jobs,
        "full_development": full["gate"]["jobs"],
    }
    admissions = {"check": check, "full_design_recovery": smoke, "full_development": full}
    records = {}
    for phase in r.PHASES:
        kernel = {
            "check": r.fit.GATE,
            "full_design_recovery": r.recovery.GATE,
            "full_development": r.fit.FULL_GATE,
        }[phase]
        authority: dict[str, Any] = dict(
            status="accepted_frozen_arrival_development_journal_execution",
            independent_checker=True,
            phase=phase,
            no_retuning=True,
            reserved_outcomes="sealed",
            max_sampler_call_slots=9,
            worker_gate=kernel,
            worker_gate_sha256=sha256(root / kernel),
            jobs=jobs[phase],
            files=admissions[phase]["files"],
        )
        write_json(root / r.AUTHORITY[phase], authority)
        plan = r.CONTROL + "/plans/" + phase + ".json"
        write_json(
            root / plan,
            dict(
                phase=phase,
                gate=r.AUTHORITY[phase],
                jobs=jobs[phase],
                files={**authority["files"], r.AUTHORITY[phase]: sha256(root / r.AUTHORITY[phase])},
            ),
        )
        records[phase] = []
        for job in jobs[phase]:
            folder, raw = (r.recovery if phase == "full_design_recovery" else r.fit).case_paths(
                root, job
            )
            manifest = json.loads((folder / "output-checksums.json").read_text())
            worker = {str((folder / n).relative_to(root)): sha256(folder / n) for n in manifest}
            worker[str((folder / "output-checksums.json").relative_to(root))] = sha256(
                folder / "output-checksums.json"
            )
            if raw is not None:
                worker[str(raw.relative_to(root))] = sha256(raw)
            spec, log, process = [
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ]
            write_json(spec, job)
            log.write_text("synthetic successful process")
            cost = int(raw is not None)
            write_json(
                process,
                dict(
                    returncode=0,
                    reason="worker_exit",
                    monitor_failures=[],
                    cost=cost,
                    start_markers=cost,
                    job_sha256=sha256(spec),
                    plan_sha256=sha256(root / plan),
                    authority_gate_sha256=sha256(root / r.AUTHORITY[phase]),
                    worker_gate_sha256=sha256(root / kernel),
                ),
            )
            receipt = r.CONTROL + f"/attempts/{phase}/{job['id']}.json"
            record = dict(
                job_id=job["id"],
                phase=phase,
                role=job["role"],
                cost=cost,
                start_markers=cost,
                outcome="accepted",
                gap_eligible=False,
                receipt=receipt,
                worker_files=worker,
                files={
                    **worker,
                    **{str(p.relative_to(root)): sha256(p) for p in [spec, log, process]},
                },
            )
            add_allocation(root, job, phase, record)
            write_json(root / receipt, record)
            records[phase].append({**record, "receipt_sha256": sha256(root / receipt)})
        summary = dict(
            status="computed_pending_independent_review",
            specification_freeze_sha256=sha256(root / r.data.FREEZE),
            case0_outcome=disposition["case0_outcome"],
            case1_outcome="accepted_unresolved_gap",
            logical_check_dispositions=[
                dict(
                    job_id=j["id"],
                    job=j,
                    outcome=outcome,
                    review=path,
                    review_sha256=sha256(root / path),
                    primary_aggregate_available=available,
                )
                for j, path, outcome, available in [
                    (
                        check["gate"]["jobs"][0],
                        r.CASE0_REVIEW,
                        disposition["case0_outcome"],
                        not unresolved,
                    ),
                    (check["gate"]["jobs"][1], r.CASE1_REVIEW, "accepted_unresolved_gap", False),
                ]
            ],
            attempt_records=records[phase],
            plan_sha256=sha256(root / plan),
            jobs=jobs[phase],
            authority_gate=r.AUTHORITY[phase],
            authority_gate_sha256=sha256(root / r.AUTHORITY[phase]),
            worker_gate=kernel,
            worker_gate_sha256=sha256(root / kernel),
            accepted_records=records[phase],
            calls_charged={"check": 0, "full_design_recovery": 6, "full_development": 9}[phase],
            calls_started={"check": 0, "full_design_recovery": 6, "full_development": 9}[phase],
        )
        write_json(root / r.SUMMARIES[phase], summary)
    final = json.loads((root / r.GATE).read_text())
    final["specification_freeze_sha256"] = sha256(root / r.data.FREEZE)

    def seal_all():
        seal_case()
        for phase in r.PHASES:
            summary = json.loads((root / r.SUMMARIES[phase]).read_text())
            updated = []
            for oldrecord in summary["attempt_records"]:
                record = json.loads((root / oldrecord["receipt"]).read_text())
                job = next(j for j in jobs[phase] if j["id"] == record["job_id"])
                folder, raw = (r.recovery if phase == "full_design_recovery" else r.fit).case_paths(
                    root, job
                )
                manifest_path = folder / "output-checksums.json"
                manifest = json.loads(manifest_path.read_text())
                write_json(manifest_path, {n: sha256(folder / n) for n in manifest})
                record["files"] = {n: sha256(root / n) for n in record["files"]}
                record["worker_files"] = {n: sha256(root / n) for n in record["worker_files"]}
                write_json(root / record["receipt"], record)
                updated.append({**record, "receipt_sha256": sha256(root / record["receipt"])})
            summary["accepted_records"] = [v for v in updated if v["outcome"] == "accepted"]
            summary["attempt_records"] = updated
            write_json(root / r.SUMMARIES[phase], summary)
        for name in [r.data.CHECK_REVIEW, r.old.SMOKE_REVIEW]:
            review = json.loads((root / name).read_text())
            review["specification_freeze_sha256"] = sha256(root / r.data.FREEZE)
            review["files"] = {
                str(p.relative_to(root)): sha256(p)
                for p in root.rglob("*")
                if p.is_file()
                and p not in {root / r.GATE, root / r.data.CHECK_REVIEW, root / r.old.SMOKE_REVIEW}
            }
            if name == r.data.CHECK_REVIEW:
                review.update(
                    completed_once=True,
                    no_retuning=True,
                    case0_review=r.CASE0_REVIEW,
                    case0_review_sha256=sha256(root / r.CASE0_REVIEW),
                )
            write_json(root / name, review)
        fullrecords = json.loads((root / r.SUMMARIES["full_development"]).read_text())[
            "accepted_records"
        ]
        final["accepted"] = [
            dict(
                job=job,
                files=rec["files"],
                receipt=rec["receipt"],
                receipt_sha256=rec["receipt_sha256"],
            )
            for job, rec in zip(jobs["full_development"], fullrecords, strict=True)
        ]
        final["files"] = {
            str(p.relative_to(root)): sha256(p)
            for p in root.rglob("*")
            if p.is_file() and p != root / r.GATE
        }
        write_json(root / r.GATE, final)

    seal_all()
    return seal_all


@pytest.mark.parametrize("unresolved", [False, True])
def test_complete_reader_validates_all_six_smoke_receipts_without_arrays(
    tmp_path, monkeypatch, unresolved
):
    complete_fixture(tmp_path, monkeypatch, unresolved)
    if unresolved:
        with pytest.raises(ValueError, match="original reviewed resolution retained"):
            r.report(tmp_path, tmp_path / "report")
        return
    r.report(tmp_path, tmp_path / "report")
    summary = json.loads((tmp_path / "report/summary.json").read_text())
    assert summary["lanes"][0]["checks"][0]["aggregate"] is not None
    assert summary["lanes"][0]["checks"][1]["aggregate"] is None
    assert summary["lanes"][0]["checks"][1]["aggregate_without_crossing_event"] is None
    assert sum(len(lane["checks"]) for lane in summary["lanes"]) == 6


@pytest.mark.parametrize(
    "fault",
    ["missing_receipt", "outcome", "cost", "plan", "oracle", "start", "raw", "summary_outcome"],
)
def test_resealed_g6_metadata_must_be_complete_before_tables(tmp_path, monkeypatch, fault):
    seal = complete_fixture(tmp_path, monkeypatch)
    summary = json.loads((tmp_path / r.SUMMARIES["full_design_recovery"]).read_text())
    record = summary["accepted_records"][0]
    receipt = tmp_path / record["receipt"]
    if fault in {"outcome", "cost"}:
        body = json.loads(receipt.read_text())
        body["outcome" if fault == "outcome" else "cost"] = "failed" if fault == "outcome" else 0
        write_json(receipt, body)
    elif fault in {"missing_receipt", "summary_outcome", "plan"}:
        if fault == "missing_receipt":
            summary["accepted_records"][0] = {"job_id": record["job_id"]}
        elif fault == "summary_outcome":
            summary["case0_outcome"] = "accepted_unresolved_gap"
        else:
            summary["plan_sha256"] = "f" * 64
        write_json(tmp_path / r.SUMMARIES["full_design_recovery"], summary)
    else:
        target = {"oracle": "numerical-oracles.json", "start": "sampling-start.json", "raw": None}[
            fault
        ]
        name = (
            next(n for n in record["files"] if n.endswith(".nc") if target is None)
            if target is None
            else next(n for n in record["files"] if n.endswith("/" + target))
        )
        write_json(
            tmp_path / name, {"passed": False} if fault == "oracle" else {"wrong": "identity"}
        )
    if fault != "missing_receipt":
        seal()
    else:
        gate = json.loads((tmp_path / r.GATE).read_text())
        gate["files"] = {n: sha256(tmp_path / n) for n in gate["files"]}
        write_json(tmp_path / r.GATE, gate)
    monkeypatch.setattr(
        r, "read_rows", lambda *a: pytest.fail("metadata must reject before tables")
    )
    with pytest.raises((ValueError, KeyError)):
        r.verify_report_sources(tmp_path)


@pytest.mark.parametrize(
    "fault",
    [
        "original_state",
        "numerical_status",
        "protocol",
        "cold_source",
        "typed_source",
        "missing_primary",
        "candidate_result",
        "unresolved_sha",
    ],
)
def test_strict_resolver_metadata_and_anchor_reuse_rejects_resealed_gaps(
    tmp_path, monkeypatch, fault
):
    admission, review, result, cold, seal = resolved_fixture(
        tmp_path, monkeypatch, unresolved=fault == "unresolved_sha"
    )
    assert result is not None and cold is not None
    if fault == "original_state":
        review["original_state_sha256"] = "f" * 64
    elif fault in {"numerical_status", "protocol"}:
        gate = json.loads((tmp_path / r.NUMERICAL_GATE).read_text())
        gate["status" if fault == "numerical_status" else "protocol"] = (
            "pending" if fault == "numerical_status" else {"retuned": True}
        )
        write_json(tmp_path / r.NUMERICAL_GATE, gate)
    elif fault == "cold_source":
        cold["files"].pop(r.numerical.SELF)
    elif fault == "missing_primary":
        result["aggregates"]["primary"] = None
        path = tmp_path / r.numerical.CASE_OUTPUT / "aggregate-diagnostics.json"
        value = json.loads(path.read_text())
        value["primary"] = None
        write_json(path, value)
    elif fault == "candidate_result":
        cold["candidate_files"].pop(r.numerical.CASE_OUTPUT + "/result.json")
    elif fault == "unresolved_sha":
        review["resolved_result_sha256"] = "f" * 64
    pins = seal()
    if fault == "typed_source":
        review["files"] = {"source.txt": pins["source.txt"]}
        write_json(tmp_path / r.CASE0_REVIEW, review)
        pins[r.CASE0_REVIEW] = sha256(tmp_path / r.CASE0_REVIEW)
    with pytest.raises(ValueError):
        r._resolved_case(tmp_path, pins, admission, review)


@pytest.mark.parametrize("phase", r.PHASES)
def test_every_phase_summary_must_match_exact_case0_disposition(tmp_path, monkeypatch, phase):
    seal = complete_fixture(tmp_path, monkeypatch)
    name = r.SUMMARIES[phase]
    summary = json.loads((tmp_path / name).read_text())
    summary["case0_outcome"] = "accepted_unresolved_gap"
    write_json(tmp_path / name, summary)
    seal()
    monkeypatch.setattr(
        r, "read_rows", lambda *a: pytest.fail("table body parsed before chronology")
    )
    with pytest.raises(ValueError):
        r.verify_report_sources(tmp_path)


def test_after_gap_reader_uses_separate_immutable_journal_paths():
    assert r.CONTROL == r.old.CONTROL + "/completion-after-gap-v1"
    for phase in r.PHASES:
        assert "/completion-after-gap-v1/" in r.AUTHORITY[phase]


def test_new_execution_receipt_cannot_omit_its_prelaunch_allocation(tmp_path, monkeypatch):
    job, admission, _, _, record, seal = ordinary_fixture(tmp_path, monkeypatch)
    record.pop("allocation", None)
    record.pop("allocation_sha256", None)
    pins = seal()
    with pytest.raises(ValueError):
        r._ordinary_case(tmp_path, pins, admission, job, "full_development", pins)


def test_reader_names_second_ncei_gap_without_model_ranking(monkeypatch):
    monkeypatch.setattr(r.old, "render_markdown", lambda summary: "# Findings\n\n## NCEI\n")
    text = r.render_markdown({"lanes": []})
    assert "linear NCEI" in text
    assert "both aggregate" in text
    assert "superiority" in text


def test_case1_gap_keeps_diagnostics_out_of_both_score_views(tmp_path, monkeypatch):
    admission, _, _, _, _ = resolved_fixture(tmp_path, monkeypatch)
    add_case1_gap(tmp_path, monkeypatch, admission)
    pins = {str(p.relative_to(tmp_path)): sha256(p) for p in tmp_path.rglob("*") if p.is_file()}
    case = r._case1_gap(tmp_path, pins, admission)
    assert case["resolution"] is None and case["disposition"] == "accepted_unresolved_gap"
    assert case["result"]["aggregate"]["equal_event_score"] == 999


@pytest.mark.parametrize(
    "fault",
    [
        "status",
        "state",
        "baseline",
        "prediction",
        "source",
        "partial_artifacts",
        "aggregate_upgrade",
        "attempt_upgrade",
        "new_call",
        "process",
    ],
)
def test_case1_gap_rejects_resealed_metadata_tampering(tmp_path, monkeypatch, fault):
    admission, _, _, _, _ = resolved_fixture(tmp_path, monkeypatch)
    review = add_case1_gap(tmp_path, monkeypatch, admission)
    if fault == "status":
        review["status"] = "accepted_model_fit"
    elif fault == "state":
        review["failed_continuation_state_sha256"] = "f" * 64
    elif fault == "baseline":
        review["baseline_history_sha256"] = "f" * 64
    elif fault == "prediction":
        review["prediction_sha256"] = "f" * 64
    elif fault == "source":
        review["files"].pop(r.CASE0_REVIEW)
    elif fault == "partial_artifacts":
        review["original_attempt_persistent_files"].pop(review["prediction_file"])
    elif fault == "aggregate_upgrade":
        review["primary_aggregate_available"] = True
    elif fault == "attempt_upgrade":
        review["controller_attempt_outcome"] = "accepted"
    elif fault == "new_call":
        review["new_sampler_calls"] = 1
    else:
        path = next(
            p for p in review["original_attempt_persistent_files"] if p.endswith(".supervisor.json")
        )
        value = json.loads((tmp_path / path).read_text())
        value["returncode"] = 0
        write_json(tmp_path / path, value)
        review["original_attempt_persistent_files"][path] = sha256(tmp_path / path)
        review["files"][path] = sha256(tmp_path / path)
    write_json(tmp_path / r.CASE1_REVIEW, review)
    pins = {str(p.relative_to(tmp_path)): sha256(p) for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        r._case1_gap(tmp_path, pins, admission)


@pytest.mark.parametrize("fault", ["job", "plan", "authority", "spec", "git", "path", "hash"])
def test_prelaunch_allocation_identity_is_not_reconstructed_from_current_state(
    tmp_path, monkeypatch, fault
):
    job, admission, _, process, record, seal = ordinary_fixture(tmp_path, monkeypatch)
    allocation_path = record["allocation"]
    value = json.loads((tmp_path / allocation_path).read_text())
    if fault == "job":
        value["job"] = {**job, "seed": 999}
    elif fault == "git":
        value["invocation_git_sha"] = "b" * 40
    elif fault in {"plan", "authority", "spec"}:
        key = {"plan": "plan_sha256", "authority": "authority_gate_sha256", "spec": "spec_sha256"}[
            fault
        ]
        value[key] = "f" * 64
    elif fault == "path":
        record["allocation"] = "unknown.json"
    else:
        record["allocation_sha256"] = "f" * 64
    write_json(tmp_path / allocation_path, value)
    if fault not in {"path", "hash"}:
        record["allocation_sha256"] = sha256(tmp_path / allocation_path)
        record["files"][allocation_path] = sha256(tmp_path / allocation_path)
        supervisor = json.loads(process.read_text())
        supervisor["allocation_sha256"] = sha256(tmp_path / allocation_path)
        write_json(process, supervisor)
    pins = seal()
    with pytest.raises(ValueError):
        r._ordinary_case(tmp_path, pins, admission, job, "full_development", pins)


def future_gap_fixture(root, monkeypatch):
    seal = complete_fixture(root, monkeypatch)
    phase = "check"
    summary = json.loads((root / r.SUMMARIES[phase]).read_text())
    job = summary["jobs"][0]
    record = summary["attempt_records"][0]
    folder, _ = r.fit.case_paths(root, job)
    result = json.loads((folder / "result.json").read_text())
    result.update(status="needs_numerical_review", sampler_call_started=False, prediction_rows=1)
    for key in ["aggregate", "aggregate_without_crossing_event"]:
        result[key] = dict(
            status="needs_numerical_review",
            precision_passed=False,
            equal_event_score=888,
            diagnostic_estimate_only=True,
        )
    write_json(folder / "result.json", result)
    process = folder.with_name(folder.name + ".supervisor.json")
    supervisor = json.loads(process.read_text())
    supervisor["returncode"] = 2
    write_json(process, supervisor)
    record = {k: v for k, v in record.items() if k != "receipt_sha256"}
    record.update(outcome="needs_review", gap_eligible=True, worker_files={})
    write_json(root / record["receipt"], record)
    seal()
    record = json.loads((root / r.SUMMARIES[phase]).read_text())["attempt_records"][0]
    review_path = r.CONTROL + f"/reviews/check/{job['id']}/review-acceptance.json"
    disposition_path = r.CONTROL + f"/dispositions/check/{job['id']}.json"
    authority = json.loads((root / r.AUTHORITY[phase]).read_text())
    prediction = str((folder / "held-out-record-predictions.csv").relative_to(root))
    review = dict(
        status="accepted_frozen_development_check_numerical_gap",
        independent_checker=True,
        original_job=job,
        failure_kind="numerical_precision_only",
        fully_computed_same_source=True,
        primary_aggregate_available=False,
        without_crossing_aggregate_available=False,
        resolved_result=None,
        resolved_result_sha256=None,
        specification_freeze_sha256=sha256(root / r.data.FREEZE),
        attempt=record["receipt"],
        attempt_sha256=record["receipt_sha256"],
        prediction_file=prediction,
        prediction_sha256=sha256(root / prediction),
        prediction_rows_precision_passed=1,
        files={
            **authority["files"],
            r.AUTHORITY[phase]: sha256(root / r.AUTHORITY[phase]),
            **record["files"],
            record["receipt"]: record["receipt_sha256"],
        },
    )
    write_json(root / review_path, review)
    disposition = dict(
        job=job,
        outcome="accepted_unresolved_gap",
        attempt=record["receipt"],
        attempt_sha256=record["receipt_sha256"],
        review=review_path,
        review_sha256=sha256(root / review_path),
    )
    write_json(root / disposition_path, disposition)
    logical = dict(
        job_id=job["id"],
        job=job,
        outcome="accepted_unresolved_gap",
        review=review_path,
        review_sha256=sha256(root / review_path),
        primary_aggregate_available=False,
        disposition=disposition_path,
        disposition_sha256=sha256(root / disposition_path),
    )
    for name in r.SUMMARIES.values():
        value = json.loads((root / name).read_text())
        value["logical_check_dispositions"].append(logical)
        write_json(root / name, value)
    seal()
    return seal, job, review_path, disposition_path


def test_future_individually_reviewed_check_gap_keeps_all_six_slots(tmp_path, monkeypatch):
    future_gap_fixture(tmp_path, monkeypatch)
    r.report(tmp_path, tmp_path / "report")
    summary = json.loads((tmp_path / "report/summary.json").read_text())
    assert len(summary["numerical_check_gaps"]) == 2
    assert sum(len(v["checks"]) for v in summary["lanes"]) == 6
    assert summary["lanes"][1]["checks"][0]["aggregate"] is None
    assert summary["lanes"][1]["checks"][0]["aggregate_without_crossing_event"] is None
    assert "888" not in (tmp_path / "report/findings.md").read_text()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_review",
        "prediction",
        "prediction_precision",
        "wrong_attempt",
        "not_precision",
        "lost_gap",
        "duplicate_slot",
        "waived_fit",
    ],
)
def test_future_gap_needs_its_own_complete_scientific_disposition(tmp_path, monkeypatch, fault):
    seal, job, review_path, disposition_path = future_gap_fixture(tmp_path, monkeypatch)
    review = json.loads((tmp_path / review_path).read_text())
    if fault in {
        "missing_review",
        "prediction",
        "prediction_precision",
        "wrong_attempt",
        "not_precision",
    }:
        key = {
            "missing_review": "status",
            "prediction": "prediction_sha256",
            "prediction_precision": "prediction_rows_precision_passed",
            "wrong_attempt": "attempt_sha256",
            "not_precision": "failure_kind",
        }[fault]
        review[key] = "wrong"
        write_json(tmp_path / review_path, review)
        disposition = json.loads((tmp_path / disposition_path).read_text())
        disposition["review_sha256"] = sha256(tmp_path / review_path)
        write_json(tmp_path / disposition_path, disposition)
        for name in r.SUMMARIES.values():
            value = json.loads((tmp_path / name).read_text())
            logical = value["logical_check_dispositions"][-1]
            logical.update(
                review_sha256=sha256(tmp_path / review_path),
                disposition_sha256=sha256(tmp_path / disposition_path),
            )
            write_json(tmp_path / name, value)
    else:
        name = r.SUMMARIES["full_development"]
        value = json.loads((tmp_path / name).read_text())
        if fault == "lost_gap":
            value["logical_check_dispositions"].pop()
        elif fault == "duplicate_slot":
            value["logical_check_dispositions"].append(value["logical_check_dispositions"][-1])
        else:
            attempt = value["attempt_records"][0]
            record = json.loads((tmp_path / attempt["receipt"]).read_text())
            record.update(outcome="needs_review", gap_eligible=True)
            write_json(tmp_path / attempt["receipt"], record)
        write_json(tmp_path / name, value)
    if fault != "waived_fit":
        seal()
    else:
        for name in [r.data.CHECK_REVIEW, r.old.SMOKE_REVIEW, r.GATE]:
            value = json.loads((tmp_path / name).read_text())
            value["files"] = {p: sha256(tmp_path / p) for p in value["files"]}
            if name == r.GATE:
                value["accepted"][0]["receipt_sha256"] = sha256(tmp_path / record["receipt"])
            write_json(tmp_path / name, value)
    monkeypatch.setattr(
        r, "read_rows", lambda *a: pytest.fail("metadata must close before predictions")
    )
    with pytest.raises(ValueError):
        r.verify_report_sources(tmp_path)


def test_late_source_drift_is_rejected_before_prediction_rows(tmp_path, monkeypatch):
    complete_fixture(tmp_path, monkeypatch)
    (tmp_path / r.SELF).write_text("changed after accepted closure")
    monkeypatch.setattr(r, "read_rows", lambda *a: pytest.fail("table read before hash closure"))
    with pytest.raises(ValueError, match="source SHA changed"):
        r.report(tmp_path, tmp_path / "not-published")
    assert not (tmp_path / "not-published").exists()


def test_late_source_drift_during_table_read_never_publishes(tmp_path, monkeypatch):
    complete_fixture(tmp_path, monkeypatch)
    actual = r.read_rows

    def changed(path):
        rows = actual(path)
        (tmp_path / r.SELF).write_text("source changed during saved-table read")
        return rows

    monkeypatch.setattr(r, "read_rows", changed)
    with pytest.raises(ValueError, match="source SHA changed"):
        r.report(tmp_path, tmp_path / "not-published")
    assert not (tmp_path / "not-published").exists()
