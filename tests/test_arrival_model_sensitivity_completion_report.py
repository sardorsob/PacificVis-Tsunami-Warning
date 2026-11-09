"""Synthetic schema2 report admission; no native data, NetCDF, sampling or Gates."""

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


def fixture(root, monkeypatch) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    old, repair, numerical = report.old, report.repair, report.numerical_api()
    for name in report.CONSUMED:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic consumed source")
    write_json(root / old.fit.GATE, {"status": "synthetic original Gate"})
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
    repair_job = repair.repair_job(jobs[34])
    execution_jobs = numerical.execution_jobs(
        jobs[36:],
        "numerical-protocol-v2",
        {j["id"]: 2 if j["order"] == 36 else 1 for j in jobs[36:]},
        dict(numerical.PROTOCOL),
    )
    write_json(
        root / old.PLAN,
        {"jobs": jobs, "files": original_pins, "gate_sha256": original_pins[old.fit.GATE]},
    )
    accepted = []
    for original, view in zip(jobs, new, strict=True):
        order = original["order"]
        producer = (
            "repair_v1" if order == 34 else "numerical_protocol" if order >= 36 else "original"
        )
        execution = (
            repair_job if order == 34 else execution_jobs[order - 36] if order >= 36 else original
        )
        if producer == "repair_v1":
            folder, raw = root / repair.OUTPUT, root / repair.STORE
        elif producer == "numerical_protocol":
            folder, raw = numerical.case_paths(root, execution)
        else:
            folder, raw = (
                root / old.fit.OUTPUT / "jobs" / original["id"],
                root / old.fit.STORE / (original["id"] + ".nc"),
            )
        paths = (
            [folder / n for n in report.CASE_FILES]
            + [raw]
            + [
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ]
        )
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic evidence; no admission body parse")
        write_json(folder / "summary.json", view["summary"])
        prior = dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
        if original["kind"] == "mean-curvature":
            prior["gamma_sd"] = 0.4
        write_json(
            folder / "inputs.json",
            {
                "base_prior": prior,
                "wider_prior": {k: v * 2 for k, v in prior.items()}
                if original["prior_variant"] == "joint_wider"
                else None,
            },
        )
        files = {str(path.relative_to(root)): sha256(path) for path in paths}
        receipt = folder / "attempt-evidence.json"
        write_json(receipt, {"case_id": original["id"], "files": files})
        entry = dict(
            order=order,
            case_id=original["id"],
            producer=producer,
            source_role=(
                "numerical_repair"
                if order in {34, 36}
                else "numerical_protocol"
                if order >= 37
                else "original"
            ),
            original_job=original,
            execution_job=execution,
            posterior=str(raw.relative_to(root)),
            posterior_sha256=sha256(raw),
            charged_slots=1,
            files=files,
            receipt=str(receipt.relative_to(root)),
            receipt_sha256=sha256(receipt),
        )
        if order >= 36:
            entry.update(run_id="numerical-protocol-v2", execution_gate=report.NUMERICAL_GATE)
        accepted.append(entry)
    failures = []
    for order in [34, 36]:
        job = jobs[order]
        folder = root / old.fit.OUTPUT / "jobs" / job["id"]
        raw = root / old.fit.STORE / (job["id"] + ".nc")
        paths = (
            [
                folder / n
                for n in [
                    "job.json",
                    "inputs.json",
                    "membership.json",
                    "sampling-start.json",
                    "result.json",
                    "diagnostics.json",
                    "sampling-diagnostics.csv",
                ]
            ]
            + [raw]
            + [
                folder.with_name(folder.name + s)
                for s in ["-spec.json", ".log", ".supervisor.json"]
            ]
        )
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("retained failed physical evidence")
        write_json(
            folder / "result.json",
            dict(
                job=job,
                status="diagnostic_failure",
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
            ),
        )
        files = {str(path.relative_to(root)): sha256(path) for path in paths}
        receipt = folder / "attempt-evidence.json"
        write_json(receipt, {"case_id": job["id"], "files": files})
        failures.append(
            dict(
                order=order,
                case_id=job["id"],
                original_job=job,
                execution_job=job,
                attempt=1,
                charged_slots=1,
                start_markers=1,
                outcome="needs_review",
                files=files,
                receipt=str(receipt.relative_to(root)),
                receipt_sha256=sha256(receipt),
                physical_files={**files, str(receipt.relative_to(root)): sha256(receipt)},
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
            )
        )
    prerequisites = {
        "original_plan": old.PLAN,
        "gate_path": report.NUMERICAL_GATE,
        "baseline_state": report.NUMERICAL_OUTPUT + "/baseline-state.json",
        "baseline_registry": report.NUMERICAL_OUTPUT + "/baseline-registry.json",
        "baseline_review": report.SCIENTIFIC_REVIEWS["baseline_v2"],
        "pilot_review": report.NUMERICAL_OUTPUT + "/pilot-review-acceptance.json",
    }
    for name in prerequisites.values():
        if not (root / name).exists():
            write_json(root / name, {"synthetic": "prerequisite"})
    for label, path in report.SCIENTIFIC_REVIEWS.items():
        if label == "numerical_v2":
            continue
        write_json(
            root / path,
            dict(
                status=report.SCIENCE_STATUSES[label],
                independent_checker=True,
                confirmation_outcomes_parsed=False,
                reserved_outcomes="sealed",
                files=original_pins,
            ),
        )
    pins = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    original_admission = dict(
        files=original_pins, gate={"jobs": jobs}, contract={"source": "fixed"}
    )
    admission = dict(
        files=dict(pins),
        original_admission=original_admission,
        original_jobs=jobs,
        accepted_prefix=accepted[:36],
        failed_attempts=failures,
        jobs=execution_jobs,
        gate={"protocol": dict(numerical.PROTOCOL), "run_id": "numerical-protocol-v2"},
    )
    mapping = {
        jobs[i]["id"]: dict(
            posterior=accepted[i]["posterior"], posterior_sha256=accepted[i]["posterior_sha256"]
        )
        for i in [34, 36]
    }
    protocol = dict(
        protocol=dict(numerical.PROTOCOL),
        first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
        execution_jobs=execution_jobs,
    )
    summary = dict(
        schema_version=2,
        run_id="numerical-protocol-v2",
        status="sensitivity_computations_complete",
        logical_cases=55,
        actual_sampler_calls=57,
        calls_charged=57,
        calls_started=57,
        max_sampler_call_slots=110,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        accepted=accepted,
        retained_failures=failures,
        numerical_repair_mapping=mapping,
        protocol_amendment=protocol,
        completion_attempts=[{"synthetic": i} for i in range(19)],
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
        status=report.SCIENCE_STATUSES["numerical_v2"],
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=dict(pins),
        execution_jobs=execution_jobs,
        logical_cases=55,
        actual_sampler_calls=57,
        calls_charged=57,
        calls_started=57,
    )
    path = report.SCIENTIFIC_REVIEWS["numerical_v2"]
    write_json(root / path, science)
    pins = {**completed["files"], path: sha256(root / path)}
    gate = dict(
        status="accepted_all_exploration_sensitivity_computations",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        reference_summary=old.REFERENCE_SUMMARY,
        report_proof_contract=report.REPORT_PROOF_CONTRACT,
        scientific_reviews=report.SCIENTIFIC_REVIEWS,
        accepted=accepted,
        retained_failures=failures,
        numerical_repair_mapping=mapping,
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


def test_metadata_admission_preserves55_logical57_actual_two_failed_raw(tmp_path, monkeypatch):
    gate, _, _ = fixture(tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    checked = report.verify_report_sources(tmp_path)
    assert checked["gate"] == gate and len(checked["accepted"]) == 55
    assert checked["run_summary"]["actual_sampler_calls"] == 57


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
        "repair-as-first-attempt",
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
        "repair-as-first-attempt",
    }:
        entry = checked["summary"]["accepted"][36]
        field, value = {
            "order": ("order", 35),
            "role": ("source_role", "original"),
            "repair-as-first-attempt": ("source_role", "numerical_protocol"),
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
        gate["files"].pop(report.SCIENTIFIC_REVIEWS["numerical_v2"])
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


def collection_fixture(root, monkeypatch):
    gate, checked, new = fixture(root, monkeypatch)
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


def test_exact35_original_one_repair19_numerical_without_cold_replay_and69_views(
    tmp_path, monkeypatch
):
    _, checked, new, originals, repairs, historical, simulated = collection_fixture(
        tmp_path, monkeypatch
    )
    result, provenance, pins, run = report.collect_views(tmp_path)
    assert originals == repairs == []
    assert len(result) == 69 and len(provenance) == 14
    assert [
        sum(v["provenance"].get("source_role") == role for v in result[:55])
        for role in ["original", "numerical_repair", "numerical_protocol"]
    ] == [35, 2, 18]
    assert historical == [d["key"] for d in report.old.refs.descriptors()]
    assert simulated == [(2916110800 + 1000 * i, 800) for i in range(14)]
    assert [v["view_id"] for v in result[:55]] == [
        j["id"] for j in checked["admission"]["original_jobs"]
    ]
    assert [v["summary"] for v in result[:55]] == [v["summary"] for v in new]
    repaired = result[34]
    assert repaired["scenario"] == "era-pre2007" and repaired["prior_variant"] == "base"
    assert repaired["provenance"]["prediction_seed"] == 2886144801
    assert repaired["provenance"]["execution_job"]["sampler"]["tune"] == 2000
    assert repaired["provenance"]["execution_job"]["sampler"]["target_accept"] == 0.99
    assert repaired["provenance"]["posterior"] == report.repair.STORE
    assert sum(v["provenance"].get("new_sampler_calls", 0) for v in result) == 55
    assert run["actual_sampler_calls"] == 57 and pins[report.GATE] == sha256(tmp_path / report.GATE)


@pytest.mark.parametrize("mutation", ["mapping", "counter", "role", "repair-summary-fallback"])
def test_resealed_corruptions_are_not_accepted_by_matching_hashes(tmp_path, monkeypatch, mutation):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    if mutation == "mapping":
        checked["summary"]["numerical_repair_mapping"][report.repair.ORIGINAL_ID]["posterior"] = (
            checked["summary"]["accepted"][0]["posterior"]
        )
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

    def figures(tables, output):
        figure_calls.append(tables)
        for name in ["prior-population-median-curves", "ncei-data-stress-log-changes"]:
            for ext in ["png", "svg"]:
                (output / f"{name}.{ext}").write_text("synthetic plotting artifact")

    monkeypatch.setattr(report.old, "figures", figures)
    output = tmp_path / "report"
    report.report(tmp_path, output)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["views"] == 69 and summary["accepted_logical_fits"] == 55
    assert summary["actual_sampler_calls"] == summary["calls_charged"] == 57
    assert summary["retained_failed_calls"] == 2 and summary["selection"] == "none"
    assert tuple(summary["qualifications"]) == report.old.QUALIFICATIONS
    assert len(figure_calls) == 1 and set(figure_calls[0]) == set(report.TABLES)
    text = (output / "findings.md").read_text()
    assert "scripts/summarize_arrival_completed_sensitivities.py" in text
    assert "scripts/summarize_arrival_sensitivities.py" not in text
    assert "2,000 tuning draws" in text and "target_accept=0.99" in text
    assert "failed diagnostics" in text and "neither failed summary is used" in text
    manifest = json.loads((output / "output-checksums.json").read_text())
    assert len(manifest) == 13 and all(sha256(output / n) == h for n, h in manifest.items())
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError, match="new nonsymlink"):
        report.report(tmp_path, output)
    assert json.loads((output / "output-checksums.json").read_text()) == before


def test_end_drift_leaves_no_output_acceptance_manifest(tmp_path, monkeypatch):
    _, _, _, _, _, _, _ = collection_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        report.old,
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
    assert checked["run_summary"]["actual_sampler_calls"] == 57


@pytest.mark.parametrize("mutation", ["counter", "missing-new-raw"])
def test_underlying_numerical_science_is_required_even_with_resealed_final_gate(
    tmp_path, monkeypatch, mutation
):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    name = report.SCIENTIFIC_REVIEWS["numerical_v2"]
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
        report.old, "figures", lambda *a: (folder / "unexpected.txt").write_text("late file")
    )
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="physical inventory changed"):
        report.report(tmp_path, output)
    assert output.exists() and not (output / "output-checksums.json").exists()
