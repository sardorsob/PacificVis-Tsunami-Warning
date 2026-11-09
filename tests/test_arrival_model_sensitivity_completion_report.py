"""Synthetic completed55/actual56 provenance; no native records, NetCDF or sampling."""

# pyright: basic
from __future__ import annotations

import copy
import json
from typing import Any

import numpy as np
import pytest

from analysis.arrival import model_sensitivity_completion_report as report
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_sensitivity_report import views


def fixture(root, monkeypatch) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    old, repair, completion = report.old, report.repair, report.completion
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
    job = repair.repair_job(jobs[34])
    write_json(
        root / old.PLAN,
        {"jobs": jobs, "files": original_pins, "gate_sha256": original_pins[old.fit.GATE]},
    )
    accepted = []
    for original, view in zip(jobs, new, strict=True):
        is_repair = original["order"] == 34
        folder = repair.OUTPUT if is_repair else old.fit.OUTPUT + "/jobs/" + original["id"]
        raw = repair.STORE if is_repair else old.fit.STORE + "/" + original["id"] + ".nc"
        names = [folder + "/" + n for n in report.CASE_FILES]
        names += [folder + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"]] + [raw]
        for name in names:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synthetic evidence; no body parsing in admission")
        write_json(root / folder / "summary.json", view["summary"])
        prior = dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
        if original["kind"] == "mean-curvature":
            prior["gamma_sd"] = 0.4
        write_json(
            root / folder / "inputs.json",
            {
                "base_prior": prior,
                "wider_prior": {k: v * 2 for k, v in prior.items()}
                if original["prior_variant"] == "joint_wider"
                else None,
            },
        )
        files = {name: sha256(root / name) for name in names}
        receipt = folder + "/attempt-evidence.json"
        write_json(root / receipt, {"case_id": original["id"], "files": files})
        accepted.append(
            dict(
                order=original["order"],
                case_id=original["id"],
                source_role="numerical_repair" if is_repair else "original",
                original_job=original,
                execution_job=job if is_repair else original,
                posterior=raw,
                posterior_sha256=files[raw],
                charged_slots=1,
                files=files,
                receipt=receipt,
                receipt_sha256=sha256(root / receipt),
            )
        )
    failed_folder = old.fit.OUTPUT + "/jobs/" + repair.ORIGINAL_ID
    failed_raw = old.fit.STORE + "/" + repair.ORIGINAL_ID + ".nc"
    p = root / failed_raw
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("retained failed raw: never accepted")
    write_json(
        root / failed_folder / "result.json",
        {
            "job": jobs[34],
            "status": "diagnostic_failure",
            "posterior": failed_raw,
            "posterior_sha256": sha256(p),
        },
    )
    failed_files = {
        name: sha256(root / name) for name in [failed_raw, failed_folder + "/result.json"]
    }
    failed_receipt = failed_folder + "/attempt-evidence.json"
    write_json(root / failed_receipt, {"case_id": repair.ORIGINAL_ID, "files": failed_files})
    failed = dict(
        case_id=repair.ORIGINAL_ID,
        charged_slots=1,
        start_markers=1,
        outcome="needs_review",
        receipt=failed_receipt,
        receipt_sha256=sha256(root / failed_receipt),
    )
    baseline = dict(
        next_case=34,
        calls_charged=35,
        calls_started=35,
        accepted=accepted[:34],
        attempts=[*([{}] * 34), failed],
    )
    for name in [completion.GATE, repair.GATE, completion.REPAIR_REVIEW]:
        write_json(root / name, {"status": "synthetic prerequisite"})
    write_json(root / completion.BASELINE, baseline)
    pins = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    mapping = {
        repair.ORIGINAL_ID: dict(
            repair_job=job,
            repair_gate_sha256=pins[repair.GATE],
            repair_review_sha256=pins[completion.REPAIR_REVIEW],
            failed_attempt_receipt_sha256=failed["receipt_sha256"],
            original_baseline_sha256=pins[completion.BASELINE],
            posterior=repair.STORE,
            posterior_sha256=accepted[34]["posterior_sha256"],
        )
    }
    summary = dict(
        status="sensitivity_computations_complete",
        logical_cases=55,
        actual_sampler_calls=56,
        calls_charged=56,
        calls_started=56,
        max_sampler_call_slots=110,
        monitor_failures=[],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        original_plan=old.PLAN,
        original_plan_sha256=pins[old.PLAN],
        original_baseline=completion.BASELINE,
        original_baseline_sha256=pins[completion.BASELINE],
        completion_gate=completion.GATE,
        completion_gate_sha256=pins[completion.GATE],
        repair_gate=repair.GATE,
        repair_gate_sha256=pins[repair.GATE],
        repair_review=completion.REPAIR_REVIEW,
        repair_review_sha256=pins[completion.REPAIR_REVIEW],
        numerical_repair_mapping=mapping,
        accepted=accepted,
        files=pins,
    )
    write_json(root / completion.COMPLETION_SUMMARY, summary)
    pins = {**pins, completion.COMPLETION_SUMMARY: sha256(root / completion.COMPLETION_SUMMARY)}
    admission = dict(files=original_pins, gate={"jobs": jobs}, contract={"source": "fixed"})
    repair_admission = dict(
        files={**original_pins, repair.GATE: pins[repair.GATE]},
        original_admission=admission,
        original_job=jobs[34],
        job=job,
    )
    checked = dict(
        files=pins, summary=summary, jobs=jobs, baseline=baseline, repair_admission=repair_admission
    )
    monkeypatch.setattr(completion, "verify_completion_sources", lambda root: checked)
    monkeypatch.setattr(old.refs, "verify_reference_sources", lambda *a: None)
    gate = dict(
        status="accepted_all_exploration_sensitivity_computations",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        reference_summary=old.REFERENCE_SUMMARY,
        accepted=accepted,
        numerical_repair_mapping=mapping,
        files=pins,
    )
    write_json(root / report.GATE, gate)
    return gate, checked, new


def forbid_reads(monkeypatch):
    monkeypatch.setattr(
        report.old, "load_lanes", lambda *a: pytest.fail("native read before admission")
    )
    monkeypatch.setattr(
        report.old.fit,
        "case_artifacts",
        lambda *a, **k: pytest.fail("original NetCDF read before admission"),
    )
    monkeypatch.setattr(
        report.repair,
        "case_artifacts",
        lambda *a, **k: pytest.fail("repair NetCDF read before admission"),
    )


def test_metadata_admission_preserves55_logical56_actual_and_failed_raw(tmp_path, monkeypatch):
    gate, _, _ = fixture(tmp_path, monkeypatch)
    forbid_reads(monkeypatch)
    result = report.verify_report_sources(tmp_path)
    assert result["gate"] == gate and len(result["accepted"]) == 55
    assert result["run_summary"]["actual_sampler_calls"] == 56


@pytest.mark.parametrize(
    "mutation",
    [
        "mapping",
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
    ],
)
def test_all_provenance_failures_precede_body_reads(tmp_path, monkeypatch, mutation):
    gate, checked, _ = fixture(tmp_path, monkeypatch)
    if mutation == "mapping":
        checked["summary"]["numerical_repair_mapping"][report.repair.ORIGINAL_ID]["posterior"] = (
            checked["accepted"][0]["posterior"] if "accepted" in checked else "wrong.nc"
        )
    elif mutation == "missing-failed-raw":
        gate["files"].pop(report.old.fit.STORE + "/" + report.repair.ORIGINAL_ID + ".nc")
    elif mutation == "counter":
        checked["summary"]["actual_sampler_calls"] = 55
    elif mutation in {"order", "role", "repair-path", "repair-job"}:
        entry = checked["summary"]["accepted"][34]
        if mutation == "order":
            entry["order"] = 35
        elif mutation == "role":
            entry["source_role"] = "original"
        elif mutation == "repair-path":
            entry["posterior"] = report.old.fit.STORE + "/" + report.repair.ORIGINAL_ID + ".nc"
        else:
            entry["execution_job"] = entry["original_job"]
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
    else:
        gate["files"][report.completion.r.STATE] = "0" * 64
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

    def original(root, job, pins, accepted=None):
        assert accepted is not None
        assert job["order"] != 34
        assert pins == checked["repair_admission"]["original_admission"]["files"]
        assert accepted["execution_job"] == job
        original_calls.append(job["id"])
        return accepted["files"], root / accepted["receipt"]

    def repaired(root, job, pins, accepted=None):
        assert accepted is not None
        assert job == checked["repair_admission"]["job"]
        assert pins == checked["repair_admission"]["files"]
        repair_calls.append(job)
        return dict(files=accepted["files"], manifest=root / accepted["receipt"])

    monkeypatch.setattr(report.old.fit, "case_artifacts", original)
    monkeypatch.setattr(report.repair, "case_artifacts", repaired)
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


def test_exact54_original_one_repair_and_original69_view_reference_recipe(tmp_path, monkeypatch):
    _, checked, new, originals, repairs, historical, simulated = collection_fixture(
        tmp_path, monkeypatch
    )
    result, provenance, pins, run = report.collect_views(tmp_path)
    assert len(originals) == 54 and len(repairs) == 1
    assert originals == [j["id"] for j in checked["jobs"] if j["order"] != 34]
    assert len(result) == 69 and len(provenance) == 14
    assert historical == [d["key"] for d in report.old.refs.descriptors()]
    assert simulated == [(2916110800 + 1000 * i, 800) for i in range(14)]
    assert [v["view_id"] for v in result[:55]] == [j["id"] for j in checked["jobs"]]
    assert [v["summary"] for v in result[:55]] == [v["summary"] for v in new]
    repaired = result[34]
    assert repaired["scenario"] == "era-pre2007" and repaired["prior_variant"] == "base"
    assert repaired["provenance"]["prediction_seed"] == 2886144801
    assert repaired["provenance"]["execution_job"]["sampler"]["tune"] == 2000
    assert repaired["provenance"]["execution_job"]["sampler"]["target_accept"] == 0.99
    assert repaired["provenance"]["posterior"] == report.repair.STORE
    assert sum(v["provenance"].get("new_sampler_calls", 0) for v in result) == 55
    assert run["actual_sampler_calls"] == 56 and pins[report.GATE] == sha256(tmp_path / report.GATE)


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
    write_json(tmp_path / report.completion.COMPLETION_SUMMARY, checked["summary"])
    gate["files"][report.completion.COMPLETION_SUMMARY] = sha256(
        tmp_path / report.completion.COMPLETION_SUMMARY
    )
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
    assert summary["actual_sampler_calls"] == summary["calls_charged"] == 56
    assert summary["retained_failed_calls"] == 1 and summary["selection"] == "none"
    assert tuple(summary["qualifications"]) == report.old.QUALIFICATIONS
    assert len(figure_calls) == 1 and set(figure_calls[0]) == set(report.TABLES)
    text = (output / "findings.md").read_text()
    assert "scripts/summarize_arrival_completed_sensitivities.py" in text
    assert "scripts/summarize_arrival_sensitivities.py" not in text
    assert "2,000 tuning draws" in text and "target_accept=0.99" in text
    assert "failed diagnostics" in text and "summary is not used" in text
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
    assert checked["run_summary"]["actual_sampler_calls"] == 56
