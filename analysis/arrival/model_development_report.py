"""Saved-table MS6 report; no fitting, posterior reading, or new predictive scores."""

# pyright: basic
from __future__ import annotations

import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as fit
from analysis.arrival import model_development_recovery as recovery
from analysis.arrival.evidence import read_rows, sha256, write_json
from analysis.arrival.model_data import LANE_SEMANTICS
from analysis.arrival.model_fit_report import matched_predictive_checks
from analysis.arrival.model_validation_report import csv_rows

GATE = fit.FULL_OUTPUT + "/review-acceptance.json"
SMOKE_REVIEW = recovery.OUTPUT + "/review-acceptance.json"
MS5_SUMMARY = str(Path(data.MS5_REVIEW).parent / "summary.json")
MS5_INPUTS = str(Path(data.MS5_REVIEW).parent / "inputs.json")
MS5_PROBES = str(Path(data.MS5_REVIEW).parent / "probe-dispositions.json")
MS5_CONTROLLER = data.ART + "exploration-sensitivity-v1/remaining-sensitivities-v1/run-summary.json"
MS5_FINISH_CONTROLLER = (
    data.ART + "exploration-sensitivity-v1/finish-sensitivities-v1/run-summary.json"
)
MS5_FINISH_DISPOSITION = (
    data.ART + "exploration-sensitivity-v1/finish-sensitivities-v1/case47-review-acceptance.json"
)
MS5_FINISH_GATE = data.ART + "sensitivity-design-v1/finish-sensitivities-v1/review-acceptance.json"
MS5_NUMERICAL_GATE = data.ART + "sensitivity-design-v1/numerical-protocol-v2/review-acceptance.json"
MS5_OLD_EXECUTION_GATE = (
    data.ART + "sensitivity-design-v1/remaining-sensitivities-v1/review-acceptance.json"
)
MS5_COUNTS = dict(
    planned_cases=55,
    completed_probes=55,
    accepted_logical_fits=54,
    unresolved_case_count=1,
    actual_sampler_calls=57,
    calls_charged=57,
    calls_started=57,
    retained_failed_calls=3,
    max_sampler_call_slots=110,
)
CONTROL = fit.CHECK_OUTPUT + "/controller"
PRIVATE_STATE = "context/runs/arrival-model-fitting-v1/development-state.json"
TABLES = ("parameters", "derived", "curves", "conditional_ppc", "record_intervals")
CONSUMED = tuple(
    sorted(
        set(fit.CONSUMED)
        | set(recovery.CONSUMED)
        | {
            "analysis/arrival/model_development_report.py",
            "scripts/summarize_arrival_development.py",
            "tests/test_arrival_model_development_report.py",
            "analysis/arrival/model_fit_report.py",
        }
    )
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _case(root, pins, admission, job, reviewed) -> dict[str, Any]:
    folder, raw = fit.case_paths(root, job)

    def name(leaf):
        return str((folder / leaf).relative_to(root))

    phase = "check" if raw is None else "full_development"
    receipt = CONTROL + f"/attempts/{phase}/{job['id']}.json"
    require(receipt in reviewed, "accepted literal controller receipt missing")
    record = data._json(root, pins, receipt)
    data._require(reviewed, record.get("files"))
    data._require(pins, record["files"])
    spec_path, log, process = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    plan = CONTROL + "/" + phase + "-plan.json"
    body = (
        {"event-results.json", "direct-score-arrays.npz", "held-out-record-predictions.csv"}
        if raw is None
        else {
            "summary.json",
            "prior-settings.json",
            "sampling-start.json",
            "diagnostics.json",
            "sampling-diagnostics.csv",
            *(key.replace("_", "-") + ".csv" for key in TABLES),
        }
    )
    needed = {
        name(leaf)
        for leaf in {
            "job.json",
            "inputs.json",
            "membership.json",
            "result.json",
            "output-checksums.json",
            *body,
        }
    }
    needed |= {str(path.relative_to(root)) for path in [spec_path, log, process]}
    if raw is not None:
        needed.add(str(raw.relative_to(root)))
    require(
        needed <= set(record["files"])
        and plan in reviewed
        and plan in pins
        and record.get("job_id") == job["id"]
        and record.get("role") == job["role"]
        and record.get("phase") == phase
        and record.get("cost") == record.get("start_markers") == int(raw is not None)
        and record.get("outcome") == "accepted",
        "complete same-role accepted result inventory required",
    )
    manifest = data._json(root, pins, name("output-checksums.json"))
    require(
        {"job.json", "inputs.json", "membership.json", "result.json", *body} <= set(manifest),
        "complete accepted worker output manifest required",
    )
    worker_files = {name(leaf): digest for leaf, digest in manifest.items()}
    worker_files[name("output-checksums.json")] = pins[name("output-checksums.json")]
    if raw is not None:
        worker_files[str(raw.relative_to(root))] = pins[str(raw.relative_to(root))]
    require(
        record.get("worker_files") == worker_files, "complete literal worker inventory required"
    )
    data._require(record["files"], worker_files)
    supervisor = data._json(root, pins, str(process.relative_to(root)))
    require(
        data._json(root, pins, str(spec_path.relative_to(root))) == job
        and supervisor.get("returncode") == 0
        and supervisor.get("reason") == "worker_exit"
        and supervisor.get("cost") == supervisor.get("start_markers") == int(raw is not None)
        and supervisor.get("job_sha256") == pins[str(spec_path.relative_to(root))]
        and supervisor.get("plan_sha256") == pins[plan]
        and supervisor.get("monitor_failures") == [],
        "complete accepted exact-cost process proof required",
    )
    result, inputs, membership = [
        data._json(root, pins, name(leaf))
        for leaf in ["result.json", "inputs.json", "membership.json"]
    ]
    target, spec = admission["specs"][job["model_key"]]
    require(
        result.get("job") == data._json(root, pins, name("job.json")) == job
        and result.get("status") == fit.SUCCESS
        and result.get("confirmation_outcomes_parsed") is True
        and result.get("reserved_outcomes") == "sealed"
        and inputs.get("files") == admission["files"]
        and inputs.get("model_spec") == spec
        and inputs.get("specification_freeze_sha256") == pins[data.FREEZE],
        "same frozen model/job/input/exposure required",
    )
    settings = None
    if raw is not None:
        require(
            result.get("posterior") == str(raw.relative_to(root))
            and isinstance(result.get("posterior_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", result["posterior_sha256"]) is not None
            and result["posterior_sha256"]
            == record["files"][str(raw.relative_to(root))]
            == pins[str(raw.relative_to(root))]
            and data._json(root, pins, name("sampling-start.json")) == job
            and result.get("diagnostics", {}).get("screen_passed") is True,
            "accepted literal posterior SHA and diagnostics required",
        )
        settings = data._json(root, pins, name("prior-settings.json"))
        base, wider, effective = fit._priors(root, target, spec)
        require(
            settings == dict(base_prior=base, wider_prior=wider, **effective),
            "same frozen effective prior settings required",
        )
    return dict(
        job=job,
        target=target,
        spec=spec,
        folder=folder,
        result=result,
        membership=membership,
        settings=settings,
        files=record["files"],
        receipt=receipt,
        receipt_sha256=pins[receipt],
    )


def _schema3_sensitivity_history(root, pins, review, saved, inputs):
    """Read admitted metadata only; the unresolved case contributes no posterior body."""
    require(
        {MS5_CONTROLLER, MS5_PROBES} <= set(review["files"]) and MS5_CONTROLLER in inputs["files"],
        "schema3 controller and all55 probe dispositions must be source-bound",
    )
    controller = data._json(root, pins, MS5_CONTROLLER)
    dispositions = data._json(root, pins, MS5_PROBES)
    require(
        controller.get("schema_version") == 3
        and controller.get("status") == "sensitivity_program_complete_with_unresolved_case"
        and all(
            type(value.get(k)) is int and value[k] == v
            for value in [saved, controller]
            for k, v in MS5_COUNTS.items()
        )
        and saved.get("views") == 68
        and saved.get("new_fits") == 54
        and saved.get("selection") == "none"
        and all(
            value.get("confirmation_outcomes_parsed") is False
            and value.get("reserved_outcomes") == "sealed"
            for value in [saved, inputs, controller]
        ),
        "schema3 exact55 planned/54 usable/one unresolved/57 calls/three failures required",
    )
    accepted, failed, unresolved = [
        controller.get(k) for k in ["accepted", "retained_failures", "unresolved_cases"]
    ]
    require(
        isinstance(accepted, list)
        and [e.get("order") for e in accepted] == [i for i in range(55) if i != 36]
        and isinstance(failed, list)
        and [(e.get("order"), e.get("attempt")) for e in failed] == [(34, 1), (36, 1), (36, 2)]
        and isinstance(unresolved, list)
        and len(unresolved) == 1
        and saved.get("unresolved_cases") == dispositions.get("unresolved_cases") == unresolved,
        "schema3 exact usable and unresolved history must agree across accepted sources",
    )
    assert isinstance(accepted, list) and isinstance(failed, list) and isinstance(unresolved, list)
    missing = unresolved[0]
    original = missing.get("original_job", {})
    require(
        missing.get("order") == original.get("order") == 36
        and missing.get("case_id") == original.get("id")
        and original.get("target") == "NCEI-native-duration"
        and original.get("kind") == "distance-scale"
        and original.get("scenario") == "era-2014plus"
        and missing.get("status") == "computationally_unresolved"
        and missing.get("no_third_attempt") is True
        and missing.get("posterior") is None
        and missing.get("failed_attempts") == failed[1:]
        and all(entry.get("original_job") == original for entry in failed[1:])
        and failed[1].get("execution_job") == original
        and failed[2].get("execution_job", {}).get("original_job") == original
        and failed[2]["execution_job"].get("sampler", {}).get("seed") == original.get("seed"),
        "same linear2014 stress, two failures, no third attempt or usable posterior required",
    )
    probes = saved.get("probe_dispositions")
    require(
        isinstance(probes, list)
        and [e.get("order") for e in probes] == list(range(55))
        and len({e.get("case_id") for e in probes}) == 55
        and dispositions.get("probes") == probes
        and all(
            probes[e["order"]].get("case_id") == e.get("case_id")
            and probes[e["order"]].get("original_job") == e.get("original_job")
            and probes[e["order"]].get("posterior") == e.get("posterior")
            and probes[e["order"]].get("status") == "accepted_scientific_computation"
            for e in accepted
        )
        and probes[36].get("case_id") == original["id"]
        and probes[36].get("original_job") == original
        and probes[36].get("status") == "computationally_unresolved"
        and probes[36].get("posterior") is None,
        "all55 source-bound dispositions and no successful case36 view required",
    )
    mapping = saved.get("successful_numerical_repair_mapping")
    amendment = saved.get("protocol_amendment")
    require(
        isinstance(mapping, dict)
        and set(mapping) == {accepted[34]["case_id"]}
        and mapping[accepted[34]["case_id"]].get("posterior") == accepted[34].get("posterior")
        and mapping
        == inputs.get("successful_numerical_repair_mapping")
        == controller.get("successful_numerical_repair_mapping")
        and isinstance(amendment, dict)
        and amendment == inputs.get("protocol_amendment") == controller.get("protocol_amendment")
        and not any("numerical_repair_mapping" in value for value in [saved, inputs, controller]),
        "schema3 successful repair34 only and identical accepted numerical amendment required",
    )
    assert isinstance(amendment, dict)
    protocol = amendment.get("protocol")
    executions = amendment.get("execution_jobs")
    first = amendment.get("first_attempt_original_case_ids")
    expected_protocol = dict(
        draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
    )
    require(
        protocol == expected_protocol
        and first == [e["case_id"] for e in accepted[36:]]
        and isinstance(executions, list)
        and len(executions) == 18
        and all(
            e == a.get("execution_job")
            and e
            == dict(
                id=f"ms5-numerical-protocol-v2-{a['order']:03d}-attempt-1",
                original_job=a["original_job"],
                attempt=1,
                sampler={**expected_protocol, "seed": a["original_job"]["seed"]},
                order=a["order"],
            )
            for e, a in zip(executions, accepted[36:], strict=True)
        ),
        "exact18 first-attempt numerical protocol and original seeds required",
    )
    qualification = saved.get("unresolved_comparison")
    require(
        isinstance(qualification, str) and bool(qualification.strip()),
        "accepted unresolved comparison qualification required",
    )
    return dict(
        status="available",
        source_schema_version=3,
        **MS5_COUNTS,
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        numerical_repair_method=saved.get("numerical_repair_method"),
        unresolved_cases=unresolved,
        unresolved_comparison=qualification,
        probe_dispositions=probes,
    )


def _schema4_sensitivity_history(root, pins, review, saved, inputs):
    """Read only admitted schema4 metadata, retaining both possible era-comparison gaps."""
    require(
        {MS5_FINISH_CONTROLLER, MS5_PROBES, MS5_FINISH_DISPOSITION} <= set(review["files"])
        and {MS5_FINISH_CONTROLLER, MS5_FINISH_DISPOSITION} <= set(inputs["files"]),
        "schema4 final controller, typed disposition and55 probes must be source-bound",
    )
    controller = data._json(root, pins, MS5_FINISH_CONTROLLER)
    dispositions = data._json(root, pins, MS5_PROBES)
    decision = data._json(root, pins, MS5_FINISH_DISPOSITION)
    data._require(pins, decision.get("files"))
    unresolved = controller.get("unresolved_cases")
    require(isinstance(unresolved, list), "schema4 typed unresolved list required")
    assert isinstance(unresolved, list)
    orders = [e.get("order") for e in unresolved]
    require(
        all(type(n) is int for n in orders) and orders in [[36], [36, 47]],
        "schema4 only unresolved36 and optional exhausted47 permitted",
    )
    count = len(orders)
    counts = dict(
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=55 - count,
        unresolved_case_count=count,
        actual_sampler_calls=58,
        calls_charged=58,
        calls_started=58,
        retained_failed_calls=3 + count,
        max_sampler_call_slots=110,
    )
    outcome = "exhausted_unresolved" if 47 in orders else "accepted_repair"
    require(
        all(v.get("schema_version") == 4 for v in [saved, inputs, controller])
        and controller.get("status") == "sensitivity_program_complete_with_unresolved_cases"
        and all(
            type(v.get(k)) is int and v[k] == expected
            for v in [saved, controller]
            for k, expected in counts.items()
        )
        and saved.get("views") == 69 - count
        and saved.get("new_fits") == 55 - count
        and saved.get("selection") == "none"
        and all(
            v.get("confirmation_outcomes_parsed") is False
            and v.get("reserved_outcomes") == "sealed"
            for v in [saved, inputs, controller, decision]
        )
        and all(v.get("case47_outcome") == outcome for v in [saved, inputs, controller, decision]),
        "schema4 exact55 probes/53-or54 usable/58 calls/four-or-five failures required",
    )
    accepted, failed, probes = (
        controller.get("accepted"),
        controller.get("retained_failures"),
        saved.get("probe_dispositions"),
    )
    require(
        isinstance(accepted, list) and isinstance(failed, list) and isinstance(probes, list),
        "schema4 exact accepted/failed/probe lists required",
    )
    assert isinstance(accepted, list) and isinstance(failed, list) and isinstance(probes, list)
    require(
        [e.get("order") for e in accepted] == [i for i in range(55) if i not in orders]
        and [(e.get("order"), e.get("attempt")) for e in failed]
        == [(34, 1), (36, 1), (36, 2), (47, 1)] + ([(47, 2)] if count == 2 else [])
        and [e.get("order") for e in probes] == list(range(55))
        and len({e.get("case_id") for e in probes}) == 55
        and dispositions.get("probes") == probes
        and saved.get("unresolved_cases") == dispositions.get("unresolved_cases") == unresolved,
        "schema4 all55 dispositions and exact failed history required",
    )
    jobs = [e.get("original_job") for e in probes]
    require(
        all(
            isinstance(j, dict) and j.get("order") == i and j.get("id") == probes[i].get("case_id")
            for i, j in enumerate(jobs)
        ),
        "schema4 original ordered probe identities required",
    )
    by_order = {e["order"]: e for e in accepted}
    for e in accepted:
        probe = probes[e["order"]]
        require(
            probe.get("original_job") == e.get("original_job") == jobs[e["order"]]
            and probe.get("case_id") == e.get("case_id")
            and probe.get("posterior") == e.get("posterior")
            and probe.get("status") == "accepted_scientific_computation",
            "schema4 accepted probes must bind actual controller fits",
        )
    for e in unresolved:
        order = e["order"]
        job = jobs[order]
        attempts = [f for f in failed if f["order"] == order]
        require(
            job.get("target") == "NCEI-native-duration"
            and job.get("kind") == ("distance-scale" if order == 36 else "mean-curvature")
            and job.get("scenario") == "era-2014plus"
            and e.get("original_job") == job
            and e.get("case_id") == job["id"]
            and e.get("status") == "computationally_unresolved"
            and e.get("no_third_attempt") is True
            and e.get("posterior") is None
            and e.get("posterior_sha256") is None
            and not any(k in e for k in ["summary", "parameters", "curves", "conditional_ppc"])
            and e.get("failed_attempts") == attempts
            and len(attempts) == 2
            and all(f.get("original_job") == job for f in attempts)
            and probes[order].get("posterior") is None
            and probes[order].get("status") == "computationally_unresolved",
            "schema4 unresolved36/47 require exact two failures, no third attempt or posterior",
        )
    protocol = dict(
        draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
    )
    repair_protocol = {**protocol, "tune": 4000, "target_accept": 0.999}

    def execution(n, attempt=1):
        return dict(
            id=f"ms5-numerical-protocol-v2-{n:03d}-attempt-{attempt}",
            original_job=jobs[n],
            attempt=attempt,
            sampler={
                **(repair_protocol if n == 47 and attempt == 2 else protocol),
                "seed": jobs[n]["seed"],
            },
            order=n,
        )

    repair_job = execution(47, 2)
    tail = [execution(n) for n in range(48, 55)]
    expected_failures = [jobs[34], jobs[36], execution(36, 2), execution(47)] + (
        [repair_job] if count == 2 else []
    )
    require(
        [f.get("execution_job") for f in failed] == expected_failures,
        "schema4 failed executions must retain original seeds and literal protocols",
    )
    require(
        all(
            v.get("repair_job") == repair_job and v.get("remaining_jobs") == tail
            for v in [saved, inputs, controller]
        ),
        "schema4 full finalrepair and seven-tail execution identities required",
    )
    for n in [*range(37, 47), *range(48, 55)]:
        require(
            by_order[n].get("execution_job") == execution(n)
            and by_order[n].get("producer") == "numerical_protocol"
            and by_order[n].get("source_role") == "numerical_protocol"
            and by_order[n].get("execution_gate")
            == (MS5_FINISH_GATE if n >= 48 else MS5_OLD_EXECUTION_GATE)
            and by_order[n].get("worker_spec_gate") == MS5_NUMERICAL_GATE,
            "schema4 actual first-attempt executions and dual authority must remain exact",
        )
    if count == 1:
        e = by_order[47]
        require(
            e.get("execution_job") == repair_job
            and e.get("producer") == "repair47"
            and e.get("source_role") == "numerical_repair"
            and e.get("execution_gate") == e.get("worker_spec_gate") == MS5_FINISH_GATE,
            "schema4 repaired47 is a distinct literal second attempt under final authority",
        )
    require(
        MS5_FINISH_GATE in pins
        and all(
            v.get("case47_disposition_review") == MS5_FINISH_DISPOSITION
            and v.get("case47_disposition_review_sha256") == pins[MS5_FINISH_DISPOSITION]
            for v in [saved, inputs, controller]
        )
        and decision.get("status") == "accepted_sensitivity_case47_disposition"
        and decision.get("independent_checker") is True
        and decision.get("repair_job") == repair_job
        and decision.get("calls_charged") == decision.get("calls_started") == 51
        and decision.get("execution_authority_gate_sha256")
        == decision.get("repair_spec_gate_sha256")
        == pins[MS5_FINISH_GATE],
        "schema4 typed independent case47 disposition must bind the51-call repair and authority",
    )
    amendment = dict(
        protocol=protocol,
        first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
        execution_jobs=[execution(n) for n in range(37, 55)],
        case47_final_repair=dict(
            execution_job=repair_job,
            protocol=repair_protocol,
            worker_spec_gate=MS5_FINISH_GATE,
            worker_spec_gate_sha256=pins[MS5_FINISH_GATE],
        ),
        remaining_execution_jobs=tail,
    )
    require(
        all(v.get("protocol_amendment") == amendment for v in [saved, inputs, controller])
        and [a.get("execution_job") for a in controller.get("completion_attempts", [])]
        == [repair_job, *tail],
        "schema4 original18 plus distinct finalrepair and seven-tail protocols must agree",
    )
    mapping = saved.get("successful_numerical_repair_mapping")
    repair_orders = [34] + ([47] if count == 1 else [])
    require(
        isinstance(mapping, dict)
        and set(mapping) == {jobs[n]["id"] for n in repair_orders}
        and mapping
        == inputs.get("successful_numerical_repair_mapping")
        == controller.get("successful_numerical_repair_mapping")
        and all(
            mapping[jobs[n]["id"]].get(k) == by_order[n].get(k)
            for n in repair_orders
            for k in ["posterior", "posterior_sha256"]
        )
        and not any("numerical_repair_mapping" in v for v in [saved, inputs, controller]),
        "schema4 mapping requires original-order34 and optional47 successful fits",
    )
    qualification = saved.get("unresolved_comparison")
    require(
        isinstance(qualification, str) and bool(qualification.strip()),
        "schema4 accepted unresolved qualification required",
    )
    return dict(
        status="available",
        source_schema_version=4,
        **counts,
        case47_outcome=outcome,
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        numerical_repair_method=saved.get("numerical_repair_method"),
        unresolved_cases=unresolved,
        unresolved_comparison=qualification,
        probe_dispositions=probes,
    )


def _sensitivity_history(root, pins):
    review = data._json(root, pins, data.MS5_REVIEW)
    data._require(pins, review.get("files"))
    require(
        {MS5_SUMMARY, MS5_INPUTS} <= set(review["files"]),
        "accepted MS5 summary/input provenance required",
    )
    saved, inputs = [data._json(root, pins, path) for path in [MS5_SUMMARY, MS5_INPUTS]]
    data._require(pins, inputs.get("files"))
    schema4_keys = {
        "case47_outcome",
        "repair_job",
        "remaining_jobs",
        "case47_disposition_review",
        "case47_disposition_review_sha256",
    }
    if any(
        schema4_keys.intersection(value) or value.get("schema_version") == 4
        for value in [saved, inputs]
    ) or any(
        {MS5_FINISH_CONTROLLER, MS5_FINISH_DISPOSITION}.intersection(value)
        for value in [review["files"], inputs["files"]]
    ):
        return _schema4_sensitivity_history(root, pins, review, saved, inputs)
    schema3_keys = {
        "successful_numerical_repair_mapping",
        "unresolved_cases",
        "planned_cases",
        "completed_probes",
        "unresolved_case_count",
        "unresolved_comparison",
        "probe_dispositions",
    }
    # A damaged summary cannot hide schema3 evidence bound elsewhere in the accepted source.
    if any(
        schema3_keys.intersection(value) or value.get("schema_version") == 3
        for value in [saved, inputs]
    ) or any(
        {MS5_CONTROLLER, MS5_PROBES}.intersection(value)
        for value in [review["files"], inputs["files"]]
    ):
        return _schema3_sensitivity_history(root, pins, review, saved, inputs)
    # Compatibility is confined to a separately accepted complete69-view legacy report.
    require(
        saved.get("views") == 69, "legacy MS5 history requires an admitted complete69-view source"
    )
    keys = ["accepted_logical_fits", "actual_sampler_calls", "retained_failed_calls"]
    if not all(key in saved for key in keys):
        return {"status": "unavailable_in_accepted_source"}
    logical, calls, failed = [saved[key] for key in keys]
    require(
        all(type(value) is int and value >= 0 for value in [logical, calls, failed])
        and (logical, calls, failed) == (55, 57, 2)
        and calls == saved.get("calls_charged") == logical + failed,
        "MS5 logical fits, charged calls and retained failures must reconcile",
    )
    mapping, amendment = [
        saved.get(key) for key in ["numerical_repair_mapping", "protocol_amendment"]
    ]
    require(
        isinstance(mapping, dict)
        and isinstance(amendment, dict)
        and inputs.get("numerical_repair_mapping") == mapping
        and inputs.get("protocol_amendment") == amendment,
        "same accepted MS5 numerical method/input identities required",
    )
    assert isinstance(amendment, dict)
    protocol, first = amendment.get("protocol"), amendment.get("first_attempt_original_case_ids")
    require(
        isinstance(protocol, dict)
        and isinstance(first, list)
        and all(isinstance(value, str) for value in first)
        and len(first) == len(set(first)),
        "explicit accepted MS5 first-attempt numerical amendment required",
    )
    return dict(
        status="available",
        accepted_logical_fits=logical,
        actual_sampler_calls=calls,
        retained_failed_calls=failed,
        numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        numerical_repair_method=saved.get("numerical_repair_method"),
    )


def verify_report_sources(root: Path) -> dict[str, Any]:
    """Hash the entire accepted closure before reading any saved result table body."""
    root = root.resolve()
    gate = json.loads(data._path(root, GATE).read_text())
    required = {
        *CONSUMED,
        data.FREEZE,
        data.MS5_REVIEW,
        MS5_SUMMARY,
        MS5_INPUTS,
        data.CHECK_REVIEW,
        SMOKE_REVIEW,
        fit.GATE,
        fit.FULL_GATE,
        recovery.GATE,
    }
    require(
        gate.get("status") == "accepted_frozen_full_development_fits"
        and gate.get("independent_checker") is True
        and gate.get("confirmation_outcomes_parsed") is True
        and gate.get("development_check_previously_inspected") is True
        and gate.get("reserved_outcomes") == "sealed"
        and gate.get("reserved_outcomes_parsed") is False
        and required <= set(gate.get("files", {}))
        and PRIVATE_STATE not in gate["files"],
        "complete independent full-fit review and truthful development exposure required",
    )
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    data._unchanged(root, pins)
    admissions = {
        role: fit.verify_gate(root, role) for role in ["full_development", "check_evaluate"]
    }
    for admission in admissions.values():
        data._require(pins, admission["files"])
    smoke = recovery.verify_gate(root)
    data._require(pins, smoke["files"])
    freeze = admissions["full_development"]["freeze"]
    require(
        admissions["check_evaluate"]["freeze"] == smoke["freeze"] == freeze
        and gate.get("specification_freeze") == data.FREEZE
        and gate.get("specification_freeze_sha256") == pins[data.FREEZE],
        "same scientific freeze required",
    )
    # The existing admissions already verify the final MS5 and completed-check contracts.
    check_review = data._json(root, pins, data.CHECK_REVIEW)
    smoke_review = data._json(root, pins, SMOKE_REVIEW)
    require(
        smoke_review.get("status") == "accepted_frozen_full_development_design_checks"
        and smoke_review.get("independent_checker") is True
        and smoke_review.get("reserved_outcomes") == "sealed"
        and smoke_review.get("confirmation_outcomes_parsed") is True
        and smoke_review.get("specification_freeze_sha256") == pins[data.FREEZE],
        "accepted same-freeze computational smoke review required",
    )
    data._require(pins, smoke_review.get("files"))
    require(len(smoke["gate"]["jobs"]) == 6, "six fixed synthetic smoke cases required")
    for job in smoke["gate"]["jobs"]:
        folder, raw = recovery.case_paths(root, job)
        require(
            {str(raw.relative_to(root)), str((folder / "result.json").relative_to(root))}
            <= set(smoke_review["files"]),
            "all six reviewed smoke results required",
        )
    full = admissions["full_development"]
    jobs = full["gate"]["jobs"]
    selected = {
        f"{target}:{specs[0]['kind']}:selected" for target, specs in freeze["models"].items()
    }
    descriptors = gate.get("accepted", [])
    require(
        len(jobs) == len(descriptors) == 3
        and {job["model_key"] for job in jobs} == selected
        and [entry.get("job") for entry in descriptors] == jobs,
        "exact three selected full-fit descriptors required",
    )
    cases = []
    for job, descriptor in zip(jobs, descriptors, strict=True):
        case = _case(root, pins, full, job, gate["files"])
        require(
            descriptor.get("files") == case["files"]
            and descriptor.get("receipt") == case["receipt"]
            and descriptor.get("receipt_sha256") == case["receipt_sha256"]
            and descriptor.get("result") == str((case["folder"] / "result.json").relative_to(root))
            and descriptor.get("summary")
            == str((case["folder"] / "summary.json").relative_to(root)),
            "literal full-fit descriptor/source/receipt binding required",
        )
        cases.append(case)
    check = admissions["check_evaluate"]
    evaluations = [job for job in check["gate"]["jobs"] if job["role"] == "check_evaluate"]
    require(
        len(evaluations) == len(check["specs"])
        and {j["model_key"] for j in evaluations} == set(check["specs"]),
        "one saved development evaluation per frozen selected/runner-up required",
    )
    checks = [_case(root, pins, check, job, check_review["files"]) for job in evaluations]
    sensitivity = _sensitivity_history(root, pins)
    data._unchanged(root, pins)
    return dict(
        root=root, files=pins, freeze=freeze, full=cases, checks=checks, sensitivity=sensitivity
    )


def report_tables(bundle) -> dict[str, Any]:
    """Pure arrangement of accepted saved quantities; no density or MCSE calculations."""
    lanes = []
    for case in bundle["full"]:
        saved = case["summary"]
        require(
            saved.get("target") == case["target"]
            and saved.get("kind") == case["spec"]["kind"]
            and saved.get("membership") == case["membership"]["training_record_ids"]
            and saved.get("conditional_predictive_draws") == 800
            and fit._summary_valid(saved),
            "complete finite existing90-percent summaries required",
        )
        checks = []
        for check in [entry for entry in bundle["checks"] if entry["target"] == case["target"]]:
            events, rows = check["events"], check["predictions"]
            ids = [r for event in events["events"] for r in event["record_ids"]]
            require(
                events["aggregate"] == check["result"]["aggregate"]
                and len(rows) == len(ids) == len(set(ids))
                and {row["record_id"] for row in rows} == set(ids)
                and [event["event_id"] for event in events["events"]]
                == events["expected_event_ids"]
                and all(
                    row["prediction_precision_passed"] in {"True", "False"}
                    and row["coverage90_numerically_ambiguous"] in {"True", "False"}
                    for row in rows
                ),
                "complete unchanged event results/prediction rows required",
            )
            checks.append(
                dict(
                    model_key=check["job"]["model_key"],
                    aggregate=events["aggregate"],
                    aggregate_without_crossing_event=events.get(
                        "aggregate_without_crossing_event",
                        {"status": "unavailable_in_accepted_source"},
                    ),
                    events=len(events["events"]),
                    records=len(rows),
                    distance_support=dict(Counter(row["distance_support"] for row in rows)),
                    prediction_precision_failures=sum(
                        row["prediction_precision_passed"] == "False" for row in rows
                    ),
                    ambiguous_coverage90=sum(
                        row["coverage90_numerically_ambiguous"] == "True" for row in rows
                    ),
                )
            )
        lanes.append(
            dict(
                target=case["target"],
                model=case["spec"],
                response=LANE_SEMANTICS[case["target"]],
                prior=case["settings"],
                diagnostics=case["result"]["diagnostics"],
                membership=case["membership"].get("counts", {}),
                support=saved["support"],
                parameters=saved["parameters"],
                derived=saved["derived"],
                curves=saved["curves"],
                conditional_ppc=matched_predictive_checks(
                    {case["spec"]["kind"]: csv_rows(saved["conditional_ppc"])}
                ),
                checks=checks,
                positive_native_moments=saved.get("positive_native_moments"),
            )
        )
    return dict(
        status="computed_pending_independent_final_report_review",
        interval_probability=0.90,
        lanes=lanes,
        sensitivity_history=bundle["sensitivity"],
        confirmation_outcomes_parsed=True,
        development_check_previously_inspected=True,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
    )


def _interval(row):
    values = [row[key] for key in ["q05", "q50", "q95"]]
    require(
        all(type(value) in {int, float} and math.isfinite(value) for value in values)
        and values[0] <= values[1] <= values[2],
        "finite ordered90-percent quantiles required",
    )
    return f"{values[1]:.4g} [{values[0]:.4g}, {values[2]:.4g}]"


def _score(value):
    if value is None:
        return "source-null; score/MCSE unavailable"
    if (
        value.get("status") != "computed_pending_review"
        or value.get("precision_passed") is not True
    ):
        return value.get("status", "unavailable") + "; score/MCSE unavailable"
    return f"{value['equal_event_score']:.5g} ± {value['mcse_equal_event_score']:.3g} MCSE"


def render_markdown(summary):
    text = [
        "# Frozen development model summary",
        "",
        "The 19-event check was previously inspected during EDA. It is a development check, "
        "not an independent test. The specification was frozen before evaluation. "
        "The 18 reserved outcomes remain sealed.",
        "",
        "Targets retain separate likelihoods and units. Reported timing is conditional on "
        "archive inclusion. The models do not establish physical onset, causal delay, "
        "operational warning time, or transfer to new station geography.",
        "",
        "All intervals below are central 90%. Parameter intervals describe posterior uncertainty; "
        "New-event intervals are pointwise reported-value predictions. "
        "Positive-target summaries use "
        "quantiles, with no predictive mean or moment claim.",
    ]
    history = summary["sensitivity_history"]
    if history.get("source_schema_version") in {3, 4}:
        text += [
            "",
            history["unresolved_comparison"],
            "",
            "The unresolved linear 2014-onward stress provides no robustness claim and no basis "
            "to prefer curvature. The frozen decision must acknowledge that gap; this report "
            "does not reopen model selection.",
            "",
        ]
    meanings = {
        "NCEI-native-duration": "NCEI positive reported travel duration",
        "T-OBS": (
            "NTWC reported observed UTC minus the reviewed USGS origin, "
            "a positive reported travel duration"
        ),
        "T-CAL": (
            "NTWC reported estimated UTC minus reported observed UTC, "
            "a signed archive discrepancy in minutes"
        ),
    }
    for lane in summary["lanes"]:
        spec, support = lane["model"], lane["support"]
        text += [
            "",
            f"## {lane['target']}",
            "",
            f"{meanings[lane['target']]}. Response: `{lane['response']['transform']}`. "
            f"Frozen form: **{spec['kind']}**; prior: **{spec['prior_variant']}** "
            f"({lane['prior']['family']}).",
            "",
            f"Full fit: {support['records']} reports across {len(support['event_counts'])} "
            f"eligible events. Distance range: {support['distance_km_min']:g}–"
            f"{support['distance_km_max']:g} km. Support flags describe distance only.",
            "",
            "| Parameter | Median [90% interval] |",
            "| --- | --- |",
        ]
        for row in lane["parameters"]:
            anchor = f" at {row['anchor_km']:g} km" if row.get("anchor_km") is not None else ""
            text.append(f"| {row['parameter']}{anchor} | {_interval(row)} |")
        text += [
            "",
            "| Distance km | Curve | Native minutes: median [90% interval] | Support |",
            "| ---: | --- | --- | --- |",
        ]
        for row in lane["curves"]:
            flag = "; SD endpoint clamped" if row.get("residual_scale_endpoint_clamped") else ""
            text.append(
                f"| {row['distance_km']:g} | {row['curve']} | {_interval(row)} | "
                f"{row['support']}{flag} |"
            )
        text += [
            "",
            "| Frozen check model | Native nats/report ± MCSE | Excluding crossing event |",
            "| --- | --- | --- |",
        ]
        for row in lane["checks"]:
            text.append(
                f"| {row['model_key']} | {_score(row['aggregate'])} | "
                f"{_score(row['aggregate_without_crossing_event'])} |"
            )
        for row in lane["checks"]:
            text += [
                "",
                f"Check `{row['model_key']}`: {row['events']} eligible events / "
                f"{row['records']} reports; {row['prediction_precision_failures']} prediction "
                f"precision flags; {row['ambiguous_coverage90']} ambiguous "
                "interval classifications. "
                f"Distance support: `{row['distance_support']}`.",
            ]
        misses = sum(
            row["observed_outside_replicated_central90"] for row in lane["conditional_ppc"]
        )
        text += [
            "",
            f"Conditional PPC: {misses}/{len(lane['conditional_ppc'])} observed quantile "
            "cells outside replicated central 90% intervals. These correlated, fitted-event "
            "checks are descriptive; they are not held-out validation.",
        ]
    text += [
        "",
        "For signed T-CAL, native and modeled PPC scales repeat the same evidence. "
        "The crossing sequence was purged uniformly from check training and restored for the "
        "unchanged full refit. Target eligibility counts differ; 57 is the catalogue size, "
        "not each target's event count.",
        "",
        "The initial 34 sensitivity fits were an interim checkpoint. "
        "The accepted complete analysis "
        "and frozen decision govern the specification. Posterior sensitivity is not a new "
        "predictive ranking or proof of equivalence. Two fixed synthetic cases per selected target "
        "provide a computational smoke check, not calibration or coverage evidence.",
        "",
        "Scores are saved equal-event joint native-minute densities; no additional Jacobian is "
        "applied. MCSE retains shared-training covariance. Numerical screens do not certify "
        "tail accuracy or global exploration; unresolved supplemental results remain unavailable. "
        "No re-selection follows the check.",
        "",
        "[Saved summaries](summary.json) include prior distribution scales, residual-scale and "
        "elasticity intervals, diagnostics, precision flags and support counts. "
        "[Input identities](inputs.json) bind the accepted artifacts and reproduction code. "
        "Predictive summaries retain the existing 800-draw budget; small shifts need Monte Carlo "
        "caution.",
        "",
    ]
    history = summary["sensitivity_history"]
    if history["status"] == "available":
        amendment = history["protocol_amendment"]
        protocol = amendment["protocol"]
        count_label = (
            f"{history['accepted_logical_fits']} usable fits across "
            f"{history['planned_cases']} planned probes "
            f"({history['unresolved_case_count']} computationally unresolved)"
            if history.get("source_schema_version") in {3, 4}
            else f"{history['accepted_logical_fits']} logical fits"
        )
        text += [
            f"The accepted MS5 analysis has {count_label} and "
            f"{history['actual_sampler_calls']} sampler calls, including "
            f"{history['retained_failed_calls']} retained failed calls. Failed draws contribute "
            "no posterior summaries. "
            f"The accepted numerical amendment also covered the first attempts of "
            f"{len(amendment['first_attempt_original_case_ids'])} prespecified cases. "
            f"Recorded amended sampling settings: `{protocol}`.",
            "",
        ]
        if history.get("numerical_repair_method"):
            text += [
                "The accepted MS5 method record retains the statistical models, priors, "
                "masks, cohorts and seeds; same-model repairs amend numerical sampling settings.",
                "",
            ]
    else:
        text += [
            "MS5 numerical-attempt counts are unavailable in the accepted source; "
            "no repair count or sampling amendment is inferred.",
            "",
        ]
    return "\n".join(text)


def _match_table(path, rows):
    expected = csv_rows(rows)
    columns = {key for row in expected for key in row}
    normalized = [{key: row.get(key, "") for key in columns} for row in expected]

    def encode(row):
        return json.dumps(row, sort_keys=True, allow_nan=False)

    require(
        Counter(map(encode, read_rows(path))) == Counter(map(encode, normalized)),
        f"saved summary CSV cells differ: {path.name}",
    )


def report(root: Path, output: Path):
    root, output = root.resolve(), Path(output).absolute()
    require(
        output.resolve() == output and output.is_relative_to(root) and not output.exists(),
        "new literal project-local output required",
    )
    bundle = verify_report_sources(root)
    for case in bundle["full"]:
        case["summary"] = data._json(
            root, bundle["files"], str((case["folder"] / "summary.json").relative_to(root))
        )
        for key in TABLES:
            _match_table(case["folder"] / (key.replace("_", "-") + ".csv"), case["summary"][key])
    for case in bundle["checks"]:
        case["events"] = data._json(
            root, bundle["files"], str((case["folder"] / "event-results.json").relative_to(root))
        )
        case["predictions"] = read_rows(case["folder"] / "held-out-record-predictions.csv")
    summary = report_tables(bundle)
    text = render_markdown(summary)
    json.dumps(summary, allow_nan=False)
    data._unchanged(root, bundle["files"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".development-report-") as temporary:
        stage = Path(temporary)
        (stage / "findings.md").write_text(text)
        write_json(stage / "summary.json", summary)
        write_json(
            stage / "inputs.json",
            dict(
                files=bundle["files"],
                review=GATE,
                specification_freeze_sha256=bundle["files"][data.FREEZE],
                method="accepted_saved_tables_only_no_new_scores_or_simulation",
            ),
        )
        write_json(
            stage / "output-checksums.json",
            {leaf: sha256(stage / leaf) for leaf in ["findings.md", "summary.json", "inputs.json"]},
        )
        data._unchanged(root, bundle["files"])
        require(not output.exists(), "output appeared before publication")
        stage.rename(output)
