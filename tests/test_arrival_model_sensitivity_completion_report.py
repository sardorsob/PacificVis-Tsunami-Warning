"""Synthetic schema4 report admission; no native data, NetCDF, sampling or Gates."""

# pyright: basic
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from analysis.arrival import model_sensitivity_completion_report as report
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_sensitivity_report import views


def fixture(
    root, monkeypatch, *, exhausted47=False
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    old, repair, numerical = report.old, report.repair, report.numerical_api()
    for name in report.CONSUMED:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic consumed source")
    for name in [
        old.fit.GATE,
        report.NUMERICAL_GATE,
        report.OLD_EXECUTION_GATE,
        report.EXECUTION_GATE,
    ]:
        write_json(root / name, {"status": "synthetic authority"})
    original_pins = {name: sha256(root / name) for name in [old.fit.GATE, *old.CONSUMED]}
    new = [v for v in views() if v["role"] == "sensitivity"]
    jobs = []
    for order, view in enumerate(new):
        jobs.append(
            {
                **{
                    k: v
                    for k, v in view.items()
                    if k not in {"summary", "provenance", "view_id", "role", "prior_specification"}
                },
                "id": repair.ORIGINAL_ID if order == 34 else f"case-{order}",
                "order": order,
                "seed": 2886110800 + 1000 * order,
            }
        )
    execution_jobs = numerical.execution_jobs(
        jobs[36:],
        "numerical-protocol-v2",
        {j["id"]: 2 if j["order"] == 36 else 1 for j in jobs[36:]},
        dict(numerical.PROTOCOL),
    )
    repair47 = numerical.execution_jobs(
        [jobs[47]], "numerical-protocol-v2", {jobs[47]["id"]: 2}, report.REPAIR47_PROTOCOL
    )[0]
    tail = execution_jobs[12:]
    new_jobs = [repair47, *tail]
    write_json(
        root / old.PLAN,
        {"jobs": jobs, "files": original_pins, "gate_sha256": original_pins[old.fit.GATE]},
    )

    def produce(original, execution, producer, failed=False):
        if producer == "repair_v1":
            folder, raw = root / repair.OUTPUT, root / repair.STORE
        elif producer in {"numerical_protocol", "repair47"}:
            folder, raw = numerical.case_paths(root, execution)
        else:
            folder, raw = (
                root / old.fit.OUTPUT / "jobs" / original["id"],
                root / old.fit.STORE / (original["id"] + ".nc"),
            )
        leaves = report.CASE_FILES if not failed else report.CASE_FILES[:7]
        paths = (
            [folder / n for n in leaves]
            + [raw]
            + [
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ]
        )
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synthetic bytes; never native")
        if not failed:
            write_json(folder / "summary.json", new[original["order"]]["summary"])
            prior = dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
            if original["kind"] == "mean-curvature":
                prior["gamma_sd"] = 0.4
            write_json(
                folder / "inputs.json",
                {
                    "base_prior": prior,
                    "wider_prior": {k: 2 * v for k, v in prior.items()}
                    if original["prior_variant"] == "joint_wider"
                    else None,
                },
            )
        else:
            write_json(
                folder / "result.json",
                dict(
                    job=execution,
                    status="diagnostic_failure",
                    posterior=str(raw.relative_to(root)),
                    posterior_sha256=sha256(raw),
                ),
            )
        files = {str(p.relative_to(root)): sha256(p) for p in paths}
        physical = dict(files)
        if not failed or original["order"] == 34:
            receipt = folder / "attempt-evidence.json"
            write_json(receipt, {"case_id": original["id"], "files": files})
            physical[str(receipt.relative_to(root))] = sha256(receipt)
        else:
            control = (
                report.CONTROL
                if producer == "repair47"
                else report.OLD_CONTROL
                if original["order"] == 47
                else report.NUMERICAL_OUTPUT
                if producer == "numerical_protocol"
                else report.first_completion.OUTPUT
            )
            receipt = root / control / "attempts" / (execution["id"] + ".json")
            write_json(
                receipt,
                dict(
                    case_id=original["id"],
                    execution_job=execution,
                    outcome="needs_review",
                    charged_slots=1,
                    start_markers=1,
                ),
            )
            files[str(receipt.relative_to(root))] = sha256(receipt)
        return dict(
            order=original["order"],
            case_id=original["id"],
            producer=producer,
            original_job=original,
            execution_job=execution,
            posterior=str(raw.relative_to(root)),
            posterior_sha256=sha256(raw),
            charged_slots=1,
            files=files,
            receipt=str(receipt.relative_to(root)),
            receipt_sha256=sha256(receipt),
        ), physical

    accepted = []
    for job in jobs:
        n = job["order"]
        if n == 36 or n == 47 and exhausted47:
            continue
        producer = (
            "repair_v1"
            if n == 34
            else "repair47"
            if n == 47
            else "numerical_protocol"
            if n >= 37
            else "original"
        )
        execution = (
            repair.repair_job(job)
            if n == 34
            else repair47
            if n == 47
            else execution_jobs[n - 36]
            if n >= 37
            else job
        )
        e, _ = produce(job, execution, producer)
        e["source_role"] = (
            "numerical_repair" if n in {34, 47} else "numerical_protocol" if n >= 37 else "original"
        )
        if n >= 37:
            e.update(
                run_id="numerical-protocol-v2",
                execution_gate=report.EXECUTION_GATE if n >= 47 else report.OLD_EXECUTION_GATE,
                worker_spec_gate=report.EXECUTION_GATE if n == 47 else report.NUMERICAL_GATE,
                execution_authority_run_id="finish-sensitivities-v1"
                if n >= 47
                else "remaining-sensitivities-v1",
            )
        accepted.append(e)
    failures = []
    for order, attempt in [(34, 1), (36, 1), (36, 2), (47, 1)] + ([(47, 2)] if exhausted47 else []):
        execution = (
            repair47
            if order == 47 and attempt == 2
            else execution_jobs[order - 36]
            if order == 47 or attempt == 2
            else jobs[order]
        )
        producer = (
            "repair47"
            if order == 47 and attempt == 2
            else "numerical_protocol"
            if order == 47 or attempt == 2
            else "original"
        )
        e, physical = produce(jobs[order], execution, producer, True)
        e.update(attempt=attempt, start_markers=1, outcome="needs_review", physical_files=physical)
        failures.append(e)
    unresolved = [
        dict(
            case_id=jobs[n]["id"],
            order=n,
            original_job=jobs[n],
            status="computationally_unresolved",
            failed_attempts=[f for f in failures if f["order"] == n],
            no_third_attempt=True,
            posterior=None,
        )
        for n in ([36, 47] if exhausted47 else [36])
    ]
    outcome = "exhausted_unresolved" if exhausted47 else "accepted_repair"
    counts = report.report_counts(dict(schema_version=4, unresolved_cases=unresolved))
    prerequisites = {
        "original_plan": old.PLAN,
        "worker_spec_gate": report.NUMERICAL_GATE,
        "repair_spec_gate": report.EXECUTION_GATE,
        "execution_authority_gate": report.EXECUTION_GATE,
        "baseline_state": report.CONTROL + "/baseline-state.json",
        "baseline_registry": report.CONTROL + "/baseline-registry.json",
        "baseline_review": report.SCIENTIFIC_REVIEWS["baseline50"],
        "case47_disposition_review": report.SCIENTIFIC_REVIEWS["case47_disposition"],
    }
    for name in prerequisites.values():
        if not (root / name).exists():
            write_json(root / name, {"synthetic": "prerequisite"})

    def allpins():
        return {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}

    for label, path in report.SCIENTIFIC_REVIEWS.items():
        if label in {"remaining", "baseline50", "case47_disposition"}:
            continue
        write_json(
            root / path,
            dict(
                status=report.SCIENCE_STATUSES[label],
                independent_checker=True,
                confirmation_outcomes_parsed=False,
                reserved_outcomes="sealed",
                no_third_case36_attempt=True,
                files={
                    k: v
                    for k, v in allpins().items()
                    if k != path
                    and k
                    not in [
                        report.SCIENTIFIC_REVIEWS["baseline50"],
                        report.SCIENTIFIC_REVIEWS["case47_disposition"],
                    ]
                },
            ),
        )
    baseline = report.SCIENTIFIC_REVIEWS["baseline50"]
    write_json(
        root / baseline,
        dict(
            status=report.SCIENCE_STATUSES["baseline50"],
            independent_checker=True,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            files={
                k: v
                for k, v in allpins().items()
                if k not in [baseline, report.SCIENTIFIC_REVIEWS["case47_disposition"]]
            },
        ),
    )
    path = report.SCIENTIFIC_REVIEWS["case47_disposition"]
    write_json(
        root / path,
        dict(
            status=report.SCIENCE_STATUSES["case47_disposition"],
            independent_checker=True,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
            files={k: v for k, v in allpins().items() if k != path},
            case47_outcome=outcome,
            repair_job=repair47,
            calls_charged=51,
            calls_started=51,
            execution_authority_gate_sha256=sha256(root / report.EXECUTION_GATE),
            repair_spec_gate_sha256=sha256(root / report.EXECUTION_GATE),
        ),
    )
    pins = allpins()
    original_admission = dict(
        files=original_pins, gate={"jobs": jobs}, contract={"source": "fixed"}
    )
    worker = dict(
        files=dict(pins),
        original_admission=original_admission,
        original_jobs=jobs,
        accepted_prefix=accepted[:36],
        failed_attempts=failures[:2],
        jobs=execution_jobs,
        gate={"protocol": dict(numerical.PROTOCOL), "run_id": "numerical-protocol-v2"},
    )
    admission = dict(
        files=dict(pins),
        original_admission=original_admission,
        worker_admission=worker,
        repair_admission={"files": dict(pins)},
        original_jobs=jobs,
        accepted_prefix=accepted[:46],
        failed_attempts=failures[:4],
        unresolved_cases=unresolved[:1],
        repair_job=repair47,
        remaining_jobs=tail,
        jobs=new_jobs,
        gate={"protocol": dict(numerical.PROTOCOL), "run_id": "finish-sensitivities-v1"},
    )
    by_order = {e["order"]: e for e in accepted}
    mapping = {
        jobs[n]["id"]: {k: by_order[n][k] for k in ["posterior", "posterior_sha256"]}
        for n in ([34] if exhausted47 else [34, 47])
    }
    protocol = dict(
        protocol=dict(numerical.PROTOCOL),
        first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
        execution_jobs=execution_jobs[1:],
        case47_final_repair=dict(
            execution_job=repair47,
            protocol=report.REPAIR47_PROTOCOL,
            worker_spec_gate=report.EXECUTION_GATE,
            worker_spec_gate_sha256=pins[report.EXECUTION_GATE],
        ),
        remaining_execution_jobs=tail,
    )
    summary = dict(
        schema_version=4,
        run_id="finish-sensitivities-v1",
        status="sensitivity_program_complete_with_unresolved_cases",
        **counts,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        accepted=accepted,
        retained_failures=failures,
        unresolved_cases=unresolved,
        case47_outcome=outcome,
        repair_job=repair47,
        remaining_jobs=tail,
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=protocol,
        completion_attempts=[
            dict(execution_job=j, charged_slots=1, start_markers=1) for j in new_jobs
        ],
        **prerequisites,
        **{k + "_sha256": pins[v] for k, v in prerequisites.items()},
    )
    write_json(root / report.COMPLETION_SUMMARY, summary)
    completed = dict(
        files={**pins, report.COMPLETION_SUMMARY: sha256(root / report.COMPLETION_SUMMARY)},
        summary=summary,
        admission=admission,
    )
    monkeypatch.setattr(
        report,
        "completion_api",
        lambda: SimpleNamespace(verify_completion_sources=lambda root, summary_path: completed),
    )
    monkeypatch.setattr(old.refs, "verify_reference_sources", lambda *a: None)
    science = dict(
        status=report.SCIENCE_STATUSES["remaining"],
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=dict(completed["files"]),
        execution_jobs=new_jobs,
        case47_outcome=outcome,
        **counts,
    )
    path = report.SCIENTIFIC_REVIEWS["remaining"]
    write_json(root / path, science)
    pins = {**completed["files"], path: sha256(root / path)}
    gate = dict(
        status="accepted_completed_sensitivity_program_with_unresolved_cases",
        **counts,
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        reference_summary=old.REFERENCE_SUMMARY,
        report_proof_contract=report.REPORT_PROOF_CONTRACT,
        scientific_reviews=report.SCIENTIFIC_REVIEWS,
        accepted=accepted,
        retained_failures=failures,
        successful_numerical_repair_mapping=mapping,
        unresolved_cases=unresolved,
        case47_outcome=outcome,
        protocol_amendment=protocol,
        files=pins,
    )
    write_json(root / report.GATE, gate)
    return gate, completed, new


def forbid_case_replays(monkeypatch):
    for producer in [report.old.fit, report.repair, report.numerical_api()]:
        monkeypatch.setattr(
            producer,
            "case_artifacts",
            lambda *a, **k: pytest.fail("redundant accepted-case native replay"),
        )


def forbid_reads(monkeypatch):
    monkeypatch.setattr(
        report.old, "load_lanes", lambda *a: pytest.fail("native read before admission")
    )
    forbid_case_replays(monkeypatch)


def test_metadata_admission_preserves55_probes54_valid57_calls_three_failed_raw(
    tmp_path, monkeypatch
):
    gate, _, _ = fixture(tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    checked = report.verify_report_sources(tmp_path)
    assert checked["gate"] == gate and len(checked["accepted"]) == 54
    assert checked["run_summary"]["actual_sampler_calls"] == 58


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-failed-raw",
        "counter",
        "order",
        "role",
        "repair-path",
        "repair-job",
        "missing-original-raw",
        "missing-repair-summary",
        "reference",
        "source",
        "gate-consumer",
        "private-state",
        "unknown-producer",
        "first-attempt-as-repair",
        "unknown-file",
        "missing-science",
        "proof-contract",
        "failed-map",
        "protocol",
    ],
)
def test_all_provenance_failures_precede_body_reads(tmp_path, monkeypatch, mutation):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    if mutation == "missing-failed-raw":
        gate["files"].pop(checked["summary"]["retained_failures"][1]["posterior"])
    elif mutation == "counter":
        checked["summary"]["actual_sampler_calls"] = 56
    elif mutation in {
        "order",
        "role",
        "repair-path",
        "repair-job",
        "unknown-producer",
        "first-attempt-as-repair",
    }:
        entry = checked["summary"]["accepted"][36]
        field, value = {
            "order": ("order", 35),
            "role": ("source_role", "original"),
            "first-attempt-as-repair": ("source_role", "numerical_repair"),
            "repair-path": ("posterior", "wrong.nc"),
            "repair-job": ("execution_job", entry["original_job"]),
            "unknown-producer": ("producer", "unknown"),
        }[mutation]
        entry[field] = value
    elif mutation == "missing-original-raw":
        gate["files"].pop(checked["summary"]["accepted"][0]["posterior"])
    elif mutation == "missing-repair-summary":
        gate["files"].pop(report.repair.OUTPUT + "/summary.json")
    elif mutation == "reference":
        monkeypatch.setattr(
            report.old.refs,
            "verify_reference_sources",
            lambda *a: (_ for _ in ()).throw(ValueError("reference missing")),
        )
    elif mutation == "source":
        (tmp_path / report.CONSUMED[0]).write_text("source drift")
    elif mutation == "gate-consumer":
        gate["files"].pop("analysis/arrival/model_sensitivity_completion_report.py")
    elif mutation == "private-state":
        gate["files"][report.first_completion.r.STATE] = "0" * 64
    elif mutation == "unknown-file":
        (
            tmp_path / Path(checked["summary"]["accepted"][36]["receipt"]).parent / "extra.txt"
        ).write_text("unexpected")
    elif mutation == "missing-science":
        gate["files"].pop(report.SCIENTIFIC_REVIEWS["remaining"])
    elif mutation == "proof-contract":
        gate["report_proof_contract"] = {}
    elif mutation == "failed-map":
        checked["summary"]["retained_failures"].pop()
    else:
        checked["summary"]["protocol_amendment"]["first_attempt_original_case_ids"].pop()
    write_json(tmp_path / report.GATE, gate)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.collect_views(tmp_path)


def test_gate_failure_allocates_no_output(tmp_path):
    output = tmp_path / "report"
    with pytest.raises(ValueError):
        report.report(tmp_path, output)
    assert not output.exists()


def collection_fixture(root, monkeypatch, *, exhausted47=False):
    gate, checked, new = fixture(root, monkeypatch, exhausted47=exhausted47)
    original_calls, repair_calls, historical, simulated = [], [], [], []
    forbid_case_replays(monkeypatch)
    from analysis.arrival.model_data import lane_arrays
    from tests.test_arrival_model_sensitivity_report import summary

    lanes = {}
    for target in ["NCEI-native-duration", "T-OBS", "T-CAL"]:
        rows = [
            dict(
                record_id=rid,
                event_id="event",
                physical_site_id=f"site-{i}",
                target=target,
                target_minutes=str(10 + i),
                distance_km=str(100 + 100 * i),
            )
            for i, rid in enumerate(["record-a", "record-b", "record-c"])
        ]
        lanes[target] = lane_arrays(target, rows, {"event": "sequence"}, {"event"})
    monkeypatch.setattr(report.old, "load_lanes", lambda root: (lanes, {"source": "fixed"}))
    registry = report.old.refs.descriptors()

    def reference(root, key, actual_lanes, pins):
        assert actual_lanes is lanes
        d = next(d for d in registry if d["key"] == key)
        historical.append(key)
        return lanes[d["target"]], d["kind"], np.arange(3), object(), {"key": key}

    def predictive(lane, kind, posterior, *, indices, seed, draws):
        simulated.append((seed, draws))
        return summary(lane.target, kind)

    monkeypatch.setattr(report.old.refs, "load_reference", reference)
    monkeypatch.setattr(report.old, "summarize_posterior", predictive)
    monkeypatch.setattr(report.old, "_priors", lambda *a, **k: {"variant": "synthetic"})
    return gate, checked, new, original_calls, repair_calls, historical, simulated


def test_exact35_original_one_repair18_numerical_without_cold_replay_and68_views(
    tmp_path, monkeypatch
):
    _, checked, new, originals, repairs, historical, simulated = collection_fixture(
        tmp_path, monkeypatch
    )
    result, provenance, pins, run = report.collect_views(tmp_path)
    assert originals == repairs == []
    assert len(result) == 68 and len(provenance) == 14
    assert [
        sum(v["provenance"].get("source_role") == role for v in result[:54])
        for role in ["original", "numerical_repair", "numerical_protocol"]
    ] == [35, 2, 17]
    assert historical == [d["key"] for d in report.old.refs.descriptors()]
    assert simulated == [(2916110800 + 1000 * i, 800) for i in range(14)]
    assert [v["view_id"] for v in result[:54]] == [
        j["id"] for j in checked["admission"]["original_jobs"] if j["order"] != 36
    ]
    assert [v["summary"] for v in result[:54]] == [
        v["summary"] for i, v in enumerate(new) if i != 36
    ]
    repaired = result[34]
    assert repaired["scenario"] == "era-pre2007" and repaired["prior_variant"] == "base"
    assert repaired["provenance"]["prediction_seed"] == 2886144801
    assert repaired["provenance"]["execution_job"]["sampler"]["tune"] == 2000
    assert repaired["provenance"]["execution_job"]["sampler"]["target_accept"] == 0.99
    assert repaired["provenance"]["posterior"] == report.repair.STORE
    assert sum(v["provenance"].get("new_sampler_calls", 0) for v in result) == 54
    assert run["actual_sampler_calls"] == 58 and pins[report.GATE] == sha256(tmp_path / report.GATE)


@pytest.mark.parametrize("mutation", ["mapping", "counter", "role", "repair-summary-fallback"])
def test_resealed_corruptions_are_not_accepted_by_matching_hashes(tmp_path, monkeypatch, mutation):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    if mutation == "mapping":
        checked["summary"]["successful_numerical_repair_mapping"][report.repair.ORIGINAL_ID][
            "posterior"
        ] = checked["summary"]["accepted"][0]["posterior"]
    elif mutation == "counter":
        checked["summary"]["calls_charged"] = checked["summary"]["calls_started"] = checked[
            "summary"
        ]["actual_sampler_calls"] = 55
    elif mutation == "role":
        checked["summary"]["accepted"][34]["source_role"] = "original"
    else:
        folder = report.old.fit.OUTPUT + "/jobs/" + report.repair.ORIGINAL_ID
        write_json(tmp_path / folder / "summary.json", {"failed_original_summary": True})
        (tmp_path / report.repair.OUTPUT / "summary.json").unlink()
    write_json(tmp_path / report.COMPLETION_SUMMARY, checked["summary"])
    gate["files"][report.COMPLETION_SUMMARY] = sha256(tmp_path / report.COMPLETION_SUMMARY)
    checked["files"][report.COMPLETION_SUMMARY] = gate["files"][report.COMPLETION_SUMMARY]
    write_json(tmp_path / report.GATE, gate)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.collect_views(tmp_path)


def test_reference_preflight_runs_before_both_producers(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    monkeypatch.setattr(
        report.old.refs,
        "verify_reference_sources",
        lambda *a: (_ for _ in ()).throw(ValueError("reference preflight")),
    )
    with pytest.raises(ValueError, match="reference preflight"):
        report.collect_views(tmp_path)


def test_end_source_drift_prevents_collection(tmp_path, monkeypatch):
    _, _, _, _, _, _, _ = collection_fixture(tmp_path, monkeypatch)
    original = report.old.refs.load_reference

    def drift(*args):
        result = original(*args)
        (tmp_path / report.CONSUMED[0]).write_text("end drift")
        return result

    monkeypatch.setattr(report.old.refs, "load_reference", drift)
    with pytest.raises(ValueError, match="SHA changed"):
        report.collect_views(tmp_path)


def test_report_reuses_pure_tables_figures_findings_and_reconciles_counts(tmp_path, monkeypatch):
    collection_fixture(tmp_path, monkeypatch)
    figure_calls = []

    def figures(tables, output, unresolved_orders):
        figure_calls.append(tables)
        for name in ["prior-population-median-curves", "ncei-data-stress-log-changes"]:
            for ext in ["png", "svg"]:
                (output / f"{name}.{ext}").write_text("synthetic plotting artifact")

    monkeypatch.setattr(report, "figures", figures)
    output = tmp_path / "report"
    report.report(tmp_path, output)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["views"] == 68 and summary["accepted_logical_fits"] == 54
    assert summary["actual_sampler_calls"] == summary["calls_charged"] == 58
    assert summary["retained_failed_calls"] == 4 and summary["selection"] == "none"
    assert tuple(summary["qualifications"]) == report.old.QUALIFICATIONS
    assert len(figure_calls) == 1 and set(figure_calls[0]) == set(report.TABLES)
    text = (output / "findings.md").read_text()
    assert "scripts/summarize_arrival_completed_sensitivities.py" in text
    assert "scripts/summarize_arrival_sensitivities.py" not in text
    assert "2,000 tuning steps" in text and "target_accept=0.99" in text
    assert "failed diagnostics" in text and "computationally unresolved" in text
    assert text.index("computationally unresolved") < text.index("54 usable fits")
    assert "favor curvature" in text and "150 original observations" in text
    assert len(summary["probe_dispositions"]) == 55
    assert summary["probe_dispositions"][36]["posterior"] is None
    manifest = json.loads((output / "output-checksums.json").read_text())
    assert len(manifest) == 14 and all(sha256(output / n) == h for n, h in manifest.items())
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError, match="new nonsymlink"):
        report.report(tmp_path, output)
    assert json.loads((output / "output-checksums.json").read_text()) == before


def test_end_drift_leaves_no_output_acceptance_manifest(tmp_path, monkeypatch):
    _, _, _, _, _, _, _ = collection_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        report,
        "figures",
        lambda *a: (tmp_path / report.CONSUMED[0]).write_text("drift after rendering"),
    )
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="SHA changed"):
        report.report(tmp_path, output)
    assert output.exists() and not (output / "output-checksums.json").exists()


def test_old_failed_run_summary_is_hash_only_not_final_accounting(tmp_path, monkeypatch):
    gate, _, _ = fixture(tmp_path, monkeypatch)
    old_summary = tmp_path / report.old.RUN_SUMMARY
    old_summary.write_text("Retained failed35 evidence; never parsed as the completed summary")
    gate["files"][report.old.RUN_SUMMARY] = sha256(old_summary)
    write_json(tmp_path / report.GATE, gate)
    forbid_reads(monkeypatch)
    checked = report.verify_report_sources(tmp_path)
    assert checked["run_summary"]["actual_sampler_calls"] == 58


@pytest.mark.parametrize("mutation", ["counter", "missing-new-raw"])
def test_underlying_numerical_science_is_required_even_with_resealed_final_gate(
    tmp_path, monkeypatch, mutation
):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    name = report.SCIENTIFIC_REVIEWS["remaining"]
    review = json.loads((tmp_path / name).read_text())
    if mutation == "counter":
        review["actual_sampler_calls"] = 56
    else:
        review["files"].pop(checked["summary"]["accepted"][40]["posterior"])
    write_json(tmp_path / name, review)
    gate["files"][name] = sha256(tmp_path / name)
    write_json(tmp_path / report.GATE, gate)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.collect_views(tmp_path)


def test_end_unknown_producer_file_blocks_publication_manifest(tmp_path, monkeypatch):
    _, checked, _, _, _, _, _ = collection_fixture(tmp_path, monkeypatch)
    folder = tmp_path / Path(checked["summary"]["accepted"][50]["receipt"]).parent
    monkeypatch.setattr(
        report, "figures", lambda *a: (folder / "unexpected.txt").write_text("late file")
    )
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="physical inventory changed"):
        report.report(tmp_path, output)
    assert output.exists() and not (output / "output-checksums.json").exists()


def test_tables_match_frozen_math_for_every_surviving_synthetic_view():
    full = views()
    sensitivities = [view for view in full if view["role"] == "sensitivity"]
    unresolved_id = sensitivities[36]["view_id"]
    subset = [view for view in full if view["view_id"] != unresolved_id]
    expected = report.old.sensitivity_tables(full)
    actual = report.sensitivity_tables(subset)
    assert set(actual) == set(expected)
    for name in expected:
        assert actual[name] == [row for row in expected[name] if row["view_id"] != unresolved_id]
        assert all(row["view_id"] != unresolved_id for row in actual[name])


@pytest.mark.parametrize(
    "mutation",
    ["third-attempt", "posterior", "wrong-original", "lost-failure", "repair-mapping", "valid36"],
)
def test_resealed_unresolved_case_cannot_become_a_fit(tmp_path, monkeypatch, mutation):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    run = checked["summary"]
    missing = run["unresolved_cases"][0]
    if mutation == "third-attempt":
        missing["no_third_attempt"] = False
    elif mutation == "posterior":
        missing["posterior"] = run["retained_failures"][-1]["posterior"]
    elif mutation == "wrong-original":
        missing["original_job"] = {**missing["original_job"], "seed": 1}
    elif mutation == "lost-failure":
        missing["failed_attempts"] = missing["failed_attempts"][:1]
    elif mutation == "repair-mapping":
        run["successful_numerical_repair_mapping"][missing["case_id"]] = {
            "posterior": run["retained_failures"][-1]["posterior"]
        }
    else:
        run["accepted"].insert(36, dict(run["retained_failures"][-1]))
    write_json(tmp_path / report.COMPLETION_SUMMARY, run)
    digest = sha256(tmp_path / report.COMPLETION_SUMMARY)
    gate["files"][report.COMPLETION_SUMMARY] = checked["files"][report.COMPLETION_SUMMARY] = digest
    write_json(tmp_path / report.GATE, gate)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.collect_views(tmp_path)


def test_no_failed_summary_is_read_when_collecting54_views(tmp_path, monkeypatch):
    _, checked, _, _, _, _, _ = collection_fixture(tmp_path, monkeypatch)
    original = report.old._read
    bad_folders = [str(Path(f["posterior"]).stem) for f in checked["summary"]["retained_failures"]]

    def checked_read(root, pins, name):
        if name.endswith(("summary.json", "inputs.json")) and "/jobs/" in name:
            assert not any("/jobs/" + folder + "/" in name for folder in bad_folders)
        return original(root, pins, name)

    monkeypatch.setattr(report.old, "_read", checked_read)
    result, *_ = report.collect_views(tmp_path)
    assert len(result) == 68


def test_unexpected_missing_heatmap_cell_raises(tmp_path):
    full = views()
    missing = [v for v in full if v["role"] == "sensitivity"][36]["view_id"]
    tables = report.sensitivity_tables([v for v in full if v["view_id"] != missing])
    name = report.TABLES[2]
    rows = tables[name]
    index = next(
        i
        for i, r in enumerate(rows)
        if r["target"] == "NCEI-native-duration"
        and r["kind"] == "mean-curvature"
        and r["scenario"] == "era-2014plus"
    )
    del rows[index]
    with pytest.raises(ValueError, match="only reviewed unresolved"):
        report.figures(tables, tmp_path)


@pytest.mark.parametrize("unresolved_orders", [(36,), (36, 47)])
def test_schema4_counts_follow_exact_typed_dispositions(unresolved_orders):
    run = dict(schema_version=4, unresolved_cases=[{"order": n} for n in unresolved_orders])
    expected = dict(
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=55 - len(unresolved_orders),
        unresolved_case_count=len(unresolved_orders),
        actual_sampler_calls=58,
        calls_charged=58,
        calls_started=58,
        retained_failed_calls=3 + len(unresolved_orders),
        max_sampler_call_slots=110,
    )
    assert report.report_counts(run) == expected


@pytest.mark.parametrize("orders", [[], [47], [36, 46], [36, 47, 48], [36, 36], [47, 36]])
def test_schema4_counts_reject_other_missing_patterns(orders):
    with pytest.raises(ValueError):
        report.report_counts(
            dict(schema_version=4, unresolved_cases=[{"order": n} for n in orders])
        )


@pytest.mark.parametrize("unresolved_orders", [(36,), (36, 47)])
def test_schema4_surviving_math_matches_full_original_oracle(unresolved_orders):
    full = views()
    new = [v for v in full if v["role"] == "sensitivity"]
    missing = {new[i]["view_id"] for i in unresolved_orders}
    expected = report.old.sensitivity_tables(full)
    actual = report.sensitivity_tables(
        [v for v in full if v["view_id"] not in missing], unresolved_orders
    )
    for name, rows in expected.items():
        assert actual[name] == [row for row in rows if row["view_id"] not in missing]


def test_schema4_missing_curved_fit_requires_explicit_reviewed_disposition():
    full = views()
    new = [v for v in full if v["role"] == "sensitivity"]
    missing = {new[i]["view_id"] for i in [36, 47]}
    with pytest.raises(ValueError):
        report.sensitivity_tables([v for v in full if v["view_id"] not in missing], (36,))


@pytest.mark.parametrize("exhausted47", [False, True])
def test_schema4_full_metadata_accepts_only_exact_final_branch(tmp_path, monkeypatch, exhausted47):
    gate, completed, _ = fixture(tmp_path, monkeypatch, exhausted47=exhausted47)
    forbid_reads(monkeypatch)
    checked = report.verify_report_sources(tmp_path)
    assert checked["gate"] == gate
    assert len(checked["accepted"]) == (53 if exhausted47 else 54)
    assert len(checked["failures"]) == (5 if exhausted47 else 4)
    assert [x["order"] for x in checked["unresolved"]] == ([36, 47] if exhausted47 else [36])
    slots = report.probe_dispositions(completed["summary"])
    assert len(slots) == 55 and slots[36]["posterior"] is None
    if exhausted47:
        assert slots[47]["posterior"] is None
        assert slots[47]["failed_attempt_receipts"][1]["attempt"] == 2
    else:
        repaired = next(e for e in checked["accepted"] if e["order"] == 47)
        assert repaired["producer"] == "repair47"
        assert repaired["execution_job"]["sampler"]["tune"] == 4000
        assert repaired["execution_job"]["sampler"]["seed"] == 2886157800
        assert repaired["execution_job"]["sampler"]["target_accept"] == 0.999
        assert repaired["worker_spec_gate"] == repaired["execution_gate"] == report.EXECUTION_GATE


def reseal_schema4(root, gate, completed):
    write_json(root / report.COMPLETION_SUMMARY, completed["summary"])
    digest = sha256(root / report.COMPLETION_SUMMARY)
    completed["files"][report.COMPLETION_SUMMARY] = gate["files"][report.COMPLETION_SUMMARY] = (
        digest
    )
    path = report.SCIENTIFIC_REVIEWS["remaining"]
    science = json.loads((root / path).read_text())
    science["files"][report.COMPLETION_SUMMARY] = digest
    write_json(root / path, science)
    gate["files"][path] = sha256(root / path)
    write_json(root / report.GATE, gate)


@pytest.mark.parametrize(
    "mutation",
    [
        "index47-map",
        "repair47-protocol",
        "repair47-role",
        "repair47-authority",
        "tail-authority",
        "retune-first47",
        "lost-case47-outcome",
        "extra-failure",
        "typed-count",
    ],
)
def test_schema4_resealed_corruptions_fail_before_native_reads(tmp_path, monkeypatch, mutation):
    gate, completed, _ = fixture(tmp_path, monkeypatch)
    run = completed["summary"]
    by_order = {e["order"]: e for e in run["accepted"]}
    entry = by_order[47]
    if mutation == "index47-map":
        run["successful_numerical_repair_mapping"][entry["case_id"]]["posterior"] = run["accepted"][
            47
        ]["posterior"]
    elif mutation == "repair47-protocol":
        entry["execution_job"] = copy.deepcopy(entry["execution_job"])
        entry["execution_job"]["sampler"]["tune"] = 2000
    elif mutation == "repair47-role":
        entry["source_role"] = "numerical_protocol"
    elif mutation == "repair47-authority":
        entry["worker_spec_gate"] = report.NUMERICAL_GATE
    elif mutation == "tail-authority":
        by_order[48]["execution_gate"] = report.OLD_EXECUTION_GATE
    elif mutation == "retune-first47":
        run["protocol_amendment"]["execution_jobs"] = copy.deepcopy(
            run["protocol_amendment"]["execution_jobs"]
        )
        run["protocol_amendment"]["execution_jobs"][10]["sampler"]["target_accept"] = 0.999
    elif mutation == "lost-case47-outcome":
        run.pop("case47_outcome")
    elif mutation == "extra-failure":
        run["retained_failures"].append(copy.deepcopy(run["retained_failures"][-1]))
    else:
        run["accepted_logical_fits"] = 53
    reseal_schema4(tmp_path, gate, completed)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.verify_report_sources(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "failed47-as-fit",
        "third47-attempt",
        "repaired47-map",
        "wrong-final-protocol",
        "missing-final-failure",
    ],
)
def test_schema4_exhausted_branch_never_substitutes_failed47(tmp_path, monkeypatch, mutation):
    gate, completed, _ = fixture(tmp_path, monkeypatch, exhausted47=True)
    run = completed["summary"]
    missing = run["unresolved_cases"][1]
    if mutation == "failed47-as-fit":
        run["accepted"].insert(46, copy.deepcopy(run["retained_failures"][-1]))
    elif mutation == "third47-attempt":
        missing["no_third_attempt"] = False
    elif mutation == "repaired47-map":
        run["successful_numerical_repair_mapping"][missing["case_id"]] = {
            "posterior": run["retained_failures"][-1]["posterior"]
        }
    elif mutation == "wrong-final-protocol":
        run["retained_failures"][-1]["execution_job"] = copy.deepcopy(
            run["retained_failures"][-1]["execution_job"]
        )
        run["retained_failures"][-1]["execution_job"]["sampler"]["seed"] += 1
    else:
        run["retained_failures"].pop()
    reseal_schema4(tmp_path, gate, completed)
    forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        report.verify_report_sources(tmp_path)


def test_schema4_qualification_distinguishes_both_numerical_protocols_and_gaps():
    for orders in [[36], [36, 47]]:
        run = {"schema_version": 4, "unresolved_cases": [{"order": n} for n in orders]}
        note, method = report.unresolved_note(run), report.method_note(run)
        assert "favor curvature" in note and "era advantage" in note
        assert "4,000 tuning steps" in method and "target_accept=0.999" in method
        assert "2,000 tuning steps" in method and "target_accept=0.99" in method
        assert "58 sampler calls" in method
        assert f"{55 - len(orders)} usable sensitivity fits" in method


def test_schema4_exhausted_report_keeps67_views55_probes_and_both_gaps(tmp_path, monkeypatch):
    collection_fixture(tmp_path, monkeypatch, exhausted47=True)
    recorded = []
    monkeypatch.setattr(report, "figures", lambda tables, output, missing: recorded.append(missing))
    output = tmp_path / "report"
    report.report(tmp_path, output)
    saved = json.loads((output / "summary.json").read_text())
    assert saved["views"] == 67 and saved["new_fits"] == 53 and saved["retained_failed_calls"] == 5
    assert saved["actual_sampler_calls"] == 58 and len(saved["probe_dispositions"]) == 55
    assert (
        saved["probe_dispositions"][36]["posterior"]
        is saved["probe_dispositions"][47]["posterior"]
        is None
    )
    assert recorded == [(36, 47)]
    assert "Neither mean form has a usable posterior" in (output / "findings.md").read_text()
