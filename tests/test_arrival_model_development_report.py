"""Saved-table contracts only; all data, Gates, and raw bytes here are synthetic."""

# pyright: basic
import json
from typing import Any

import pytest

from analysis.arrival import model_development_report as r
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_validation_report import write_table


def fixture(root, monkeypatch) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    for name in r.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
    source = root / "source.txt"
    source.write_text("frozen metadata")
    targets = ["NCEI-native-duration", "T-OBS", "T-CAL"]
    kinds = ["mean-curvature", "event", "pooled"]
    models = {
        target: [
            dict(
                role="selected",
                kind=kind,
                prior_variant="base",
                base_prior_sd={"alpha_sd": 0.5},
                wider_prior_sd=None,
            )
        ]
        for target, kind in zip(targets, kinds, strict=True)
    }
    freeze = dict(models=models, ms5_decision="scientific-decision.json")
    write_json(root / r.data.FREEZE, freeze)
    write_json(root / "scientific-decision.json", freeze)
    for name in [r.fit.GATE, r.fit.FULL_GATE, r.recovery.GATE]:
        write_json(root / name, {"synthetic_execution_gate": name})
    base = {"source.txt": sha256(source), r.data.FREEZE: sha256(root / r.data.FREEZE)}
    specs = {
        f"{target}:{entry[0]['kind']}:selected": (target, entry[0])
        for target, entry in models.items()
    }
    admissions = {}
    jobs = {}
    descriptors = []
    check_files = {}
    settings = dict(family="normal", distribution_scales={"alpha_sd": 0.5})
    monkeypatch.setattr(r.fit, "_priors", lambda *a: ({"alpha_sd": 0.5}, None, settings))
    for role in ["full_development", "check_evaluate"]:
        jobs[role] = [
            dict(
                id=f"dev-{role.replace('_', '-')}-{j}",
                order=j,
                role=role,
                model_key=key,
                seed=50 + j,
                training_reference=None if role == "full_development" else {"kind": "historical"},
            )
            for j, key in enumerate(specs)
        ]
        admissions[role] = dict(gate={"jobs": jobs[role]}, files=base, freeze=freeze, specs=specs)
        phase = "check" if role == "check_evaluate" else "full_development"
        phase_plan = root / r.CONTROL / (phase + "-plan.json")
        write_json(phase_plan, {"jobs": jobs[role], "files": base})
        if role == "check_evaluate":
            check_files[str(phase_plan.relative_to(root))] = sha256(phase_plan)
        for job in jobs[role]:
            target, spec = specs[job["model_key"]]
            folder, raw = r.fit.case_paths(root, job)
            folder.mkdir(parents=True)
            phase = "check" if raw is None else "full_development"
            case_id = "full-" + target
            event_id = "held-" + target
            aggregate = dict(
                status="computed_pending_review",
                precision_passed=True,
                equal_event_score=-0.25,
                mcse_equal_event_score=0.001,
            )
            supplemental = (
                dict(
                    status="not_applicable",
                    events=0,
                    kept_event_ids=[],
                    excluded_event_ids=[r.data.CROSS_CHECK],
                    failed_event_ids=[],
                )
                if target == targets[0]
                else {
                    **aggregate,
                    "kept_event_ids": [event_id],
                    "excluded_event_ids": [],
                    "failed_event_ids": [],
                }
            )
            if target == "T-CAL":
                supplemental = {
                    "status": "needs_numerical_review",
                    "kept_event_ids": [event_id],
                    "excluded_event_ids": [],
                    "failed_event_ids": [],
                    "precision_passed": False,
                }
            result = dict(
                job=job,
                status=r.fit.SUCCESS,
                confirmation_outcomes_parsed=True,
                reserved_outcomes="sealed",
                aggregate=aggregate,
                aggregate_without_crossing_event=supplemental,
            )
            write_json(folder / "job.json", job)
            write_json(
                folder / "inputs.json",
                dict(files=base, model_spec=spec, specification_freeze_sha256=base[r.data.FREEZE]),
            )
            write_json(
                folder / "membership.json",
                dict(
                    training_record_ids=[case_id],
                    counts={"training_purged": 1, "combined_primary": 1},
                ),
            )
            if raw is not None:
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(b"not a NetCDF; hash only")
                write_json(folder / "sampling-start.json", job)
                result.update(
                    posterior=str(raw.relative_to(root)),
                    posterior_sha256=sha256(raw),
                    diagnostics={"screen_passed": True},
                )
                write_json(
                    folder / "prior-settings.json",
                    dict(base_prior={"alpha_sd": 0.5}, wider_prior=None, **settings),
                )
                write_json(folder / "diagnostics.json", result["diagnostics"])
                (folder / "sampling-diagnostics.csv").write_text("parameter,r_hat\nalpha,1\n")
                quant = dict(
                    q05=-0.1, q50=0.0, q95=0.1, quantile_valid=True, native_representable=True
                )
                native = (
                    dict(quant, q05=-8.0, q50=-6.0, q95=-2.0)
                    if target == "T-CAL"
                    else dict(quant, q05=4.0, q50=5.0, q95=6.0)
                )
                ppc = [
                    dict(
                        stratum="all",
                        scale="modeled-response",
                        quantile=0.5,
                        records=1,
                        observed=2.0,
                        replicated_q05=-1.0,
                        replicated_q50=0.0,
                        replicated_q95=1.0,
                        replicated_quantile_valid=True,
                        observed_quantile_valid=True,
                    ),
                    dict(
                        stratum="all",
                        scale="native-minutes",
                        quantile=0.5,
                        records=1,
                        observed=native["q50"],
                        replicated_q05=native["q05"],
                        replicated_q50=native["q50"],
                        replicated_q95=native["q95"],
                        replicated_quantile_valid=True,
                        observed_quantile_valid=True,
                        replicated_log_q50=1.6 if target != "T-CAL" else None,
                    ),
                ]
                summary: dict[str, Any] = dict(
                    target=target,
                    kind=spec["kind"],
                    membership=[case_id],
                    conditional_predictive_draws=800,
                    nonfinite_values={},
                    unrepresentable_native_draws={},
                    parameters=[dict(parameter="alpha", **quant)],
                    derived=[dict(quantity="residual_sd_modeled_response", **quant)],
                    curves=[
                        dict(curve=curve, distance_km=1000.0, support="within", **native)
                        for curve in ["population_median", "new_event"]
                    ],
                    conditional_ppc=ppc,
                    record_intervals=[dict(record_id=case_id, **native)],
                    support=dict(
                        records=1,
                        event_counts={"full-event": 1},
                        distance_km_min=500.0,
                        distance_km_max=5000.0,
                    ),
                    positive_native_moments="no moment claim",
                )
                write_json(folder / "summary.json", summary)
                for key in r.TABLES:
                    write_table(folder / (key.replace("_", "-") + ".csv"), summary[key])
            else:
                write_json(
                    folder / "event-results.json",
                    dict(
                        expected_event_ids=[event_id],
                        events=[dict(event_id=event_id, record_ids=["held-record-" + target])],
                        aggregate=aggregate,
                        aggregate_without_crossing_event=supplemental,
                    ),
                )
                (folder / "direct-score-arrays.npz").write_bytes(b"not NPZ; never parsed")
                write_table(
                    folder / "held-out-record-predictions.csv",
                    [
                        dict(
                            record_id="held-record-" + target,
                            event_id=event_id,
                            distance_support="within",
                            prediction_precision_passed=True,
                            coverage90_numerically_ambiguous=False,
                        )
                    ],
                )
            write_json(folder / "result.json", result)
            manifest = {q.name: sha256(q) for q in folder.iterdir() if q.is_file()}
            write_json(folder / "output-checksums.json", manifest)
            files = {str(q.relative_to(root)): sha256(q) for q in folder.iterdir() if q.is_file()}
            if raw is not None:
                files[str(raw.relative_to(root))] = sha256(raw)
            worker_files = dict(files)
            spec_path, log, process = [
                folder.with_name(folder.name + suffix)
                for suffix in ["-spec.json", ".log", ".supervisor.json"]
            ]
            write_json(spec_path, job)
            log.write_text("synthetic successful process")
            write_json(
                process,
                dict(
                    returncode=0,
                    reason="worker_exit",
                    cost=int(raw is not None),
                    start_markers=int(raw is not None),
                    job_sha256=sha256(spec_path),
                    plan_sha256=sha256(phase_plan),
                    invocation_git_sha="a" * 40,
                    monitor_failures=[],
                ),
            )
            files.update(
                {str(path.relative_to(root)): sha256(path) for path in [spec_path, log, process]}
            )
            receipt = r.CONTROL + f"/attempts/{phase}/{job['id']}.json"
            write_json(
                root / receipt,
                dict(
                    job_id=job["id"],
                    role=role,
                    phase=phase,
                    cost=int(raw is not None),
                    start_markers=int(raw is not None),
                    outcome="accepted",
                    files=files,
                    worker_files=worker_files,
                ),
            )
            if raw is not None:
                descriptors.append(
                    dict(
                        job=job,
                        files=files,
                        result=str((folder / "result.json").relative_to(root)),
                        summary=str((folder / "summary.json").relative_to(root)),
                        receipt=receipt,
                        receipt_sha256=sha256(root / receipt),
                    )
                )
            else:
                check_files.update(files)
                check_files[receipt] = sha256(root / receipt)
    smoke_jobs = [{"id": f"smoke-{j}"} for j in range(6)]

    def smoke_paths(root, job):
        return root / "smoke" / job["id"], root / "smoke" / (job["id"] + ".nc")

    smoke_files = {}
    for job in smoke_jobs:
        folder, raw = smoke_paths(root, job)
        write_json(folder / "result.json", {"synthetic": True})
        raw.write_bytes(b"not NetCDF")
        smoke_files.update(
            {
                str(raw.relative_to(root)): sha256(raw),
                str((folder / "result.json").relative_to(root)): sha256(folder / "result.json"),
            }
        )
    for name, status, files in [
        (r.data.MS5_REVIEW, "accepted_exploration_sensitivity_analysis", base),
        (r.data.CHECK_REVIEW, "accepted_frozen_arrival_development_check", check_files),
        (r.SMOKE_REVIEW, "accepted_frozen_full_development_design_checks", smoke_files),
    ]:
        write_json(
            root / name,
            dict(
                status=status,
                independent_checker=True,
                reserved_outcomes="sealed",
                confirmation_outcomes_parsed=name != r.data.MS5_REVIEW,
                specification_freeze_sha256=base[r.data.FREEZE],
                files=files,
            ),
        )
    ms5_folder = root / r.data.MS5_REVIEW
    ms5_folder = ms5_folder.parent
    amendment = dict(
        protocol=dict(
            draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
        ),
        first_attempt_original_case_ids=[f"case-{i}" for i in range(18)],
    )
    repair_mapping = {"case-34": {"retained": True}, "case-36": {"retained": True}}
    write_json(
        ms5_folder / "summary.json",
        dict(
            views=69,
            accepted_logical_fits=55,
            actual_sampler_calls=57,
            retained_failed_calls=2,
            calls_charged=57,
            numerical_repair_mapping=repair_mapping,
            protocol_amendment=amendment,
            numerical_repair_method=(
                "Same models, priors, masks, cohorts and seeds; numerical settings amended."
            ),
        ),
    )
    write_json(
        ms5_folder / "inputs.json",
        dict(files=base, numerical_repair_mapping=repair_mapping, protocol_amendment=amendment),
    )
    ms5_review = json.loads((root / r.data.MS5_REVIEW).read_text())
    ms5_review["files"].update(
        {
            str(path.relative_to(root)): sha256(path)
            for path in [ms5_folder / "summary.json", ms5_folder / "inputs.json"]
        }
    )
    write_json(root / r.data.MS5_REVIEW, ms5_review)
    monkeypatch.setattr(r.fit, "verify_gate", lambda root, role: admissions[role])
    monkeypatch.setattr(
        r.recovery,
        "verify_gate",
        lambda root: dict(files=base, freeze=freeze, gate={"jobs": smoke_jobs}),
    )
    monkeypatch.setattr(r.recovery, "case_paths", smoke_paths)
    for name in ["load_check_lanes", "load_full_development_lanes"]:
        monkeypatch.setattr(
            r.data, name, lambda *args: (_ for _ in ()).throw(AssertionError("no native loader"))
        )
    monkeypatch.setattr(
        r.fit,
        "case_artifacts",
        lambda *args: (_ for _ in ()).throw(AssertionError("no posterior replay")),
    )
    gate: dict[str, Any] = dict(
        status="accepted_frozen_full_development_fits",
        independent_checker=True,
        confirmation_outcomes_parsed=True,
        development_check_previously_inspected=True,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        specification_freeze=r.data.FREEZE,
        specification_freeze_sha256=base[r.data.FREEZE],
        accepted=descriptors,
    )

    def reseal():
        gate["files"] = {
            str(q.relative_to(root)): sha256(q)
            for q in root.rglob("*")
            if q.is_file() and q != root / r.GATE
        }
        write_json(root / r.GATE, gate)

    reseal()
    return gate, reseal, admissions


def test_saved_report_has_four_deterministic_outputs_signed90_and_no_new_scoring(
    tmp_path, monkeypatch
):
    fixture(tmp_path, monkeypatch)
    r.report(tmp_path, tmp_path / "report-a")
    r.report(tmp_path, tmp_path / "report-b")
    names = {"findings.md", "summary.json", "inputs.json", "output-checksums.json"}
    assert {p.name for p in (tmp_path / "report-a").iterdir()} == names
    assert all(
        (tmp_path / "report-a" / leaf).read_bytes() == (tmp_path / "report-b" / leaf).read_bytes()
        for leaf in names
    )
    text = (tmp_path / "report-a/findings.md").read_text()
    assert "90%" in text and "95%" not in text and "-6 [-8, -2]" in text
    assert "not an independent test" in text and "18 reserved outcomes remain sealed" in text
    summary = json.loads((tmp_path / "report-a/summary.json").read_text())
    assert summary["confirmation_outcomes_parsed"] and not summary["reserved_outcomes_parsed"]
    assert [
        row["checks"][0]["aggregate_without_crossing_event"]["status"] for row in summary["lanes"]
    ] == ["not_applicable", "computed_pending_review", "needs_numerical_review"]
    assert "score/MCSE unavailable" in text
    assert "55 logical fits" in text and "57 sampler calls" in text
    assert "2 retained failed calls" in text and "first attempts of 18" in text
    assert "same-model repairs" in text
    assert "observed UTC minus the reviewed USGS origin" in text
    assert "estimated UTC minus reported observed UTC" in text


@pytest.mark.parametrize(
    "bad",
    [
        "missing-gate",
        "source",
        "freeze",
        "model",
        "incomplete-three",
        "receipt",
        "old-exposure",
        "reserved",
        "missing-closure",
    ],
)
def test_all_metadata_and_receipts_admitted_before_any_table_body(tmp_path, monkeypatch, bad):
    gate, reseal, admissions = fixture(tmp_path, monkeypatch)
    if bad == "missing-gate":
        (tmp_path / r.GATE).unlink()
    elif bad == "source":
        (tmp_path / "source.txt").write_text("drift")
    elif bad == "freeze":
        gate["specification_freeze_sha256"] = "0" * 64
        reseal()
    elif bad == "model":
        gate["accepted"][0]["job"] = {**gate["accepted"][0]["job"], "model_key": "wrong"}
        reseal()
    elif bad == "incomplete-three":
        gate["accepted"].pop()
        reseal()
    elif bad == "old-exposure":
        gate["confirmation_outcomes_parsed"] = False
        reseal()
    elif bad == "reserved":
        gate["reserved_outcomes_parsed"] = True
        reseal()
    elif bad == "missing-closure":
        gate["files"].pop(gate["accepted"][2]["summary"])
        write_json(tmp_path / r.GATE, gate)
    else:
        path = tmp_path / gate["accepted"][0]["receipt"]
        record = json.loads(path.read_text())
        record["job_id"] = "wrong"
        write_json(path, record)
        gate["accepted"][0]["receipt_sha256"] = sha256(path)
        reseal()
    monkeypatch.setattr(
        r,
        "_match_table",
        lambda *args: (_ for _ in ()).throw(AssertionError("table body before admission")),
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("when", ["after-bodies", "after-staging"])
def test_source_drift_never_publishes_output(tmp_path, monkeypatch, when):
    fixture(tmp_path, monkeypatch)
    original = r.data._unchanged
    calls = []

    def checked(root, pins):
        calls.append(pins)
        if (when == "after-bodies" and len(calls) == 3) or (
            when == "after-staging" and len(calls) == 4
        ):
            (tmp_path / "source.txt").write_text("changed during report")
        return original(root, pins)

    monkeypatch.setattr(r.data, "_unchanged", checked)
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_missing_supplemental_result_is_explicit_not_reconstructed(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    bundle = r.verify_report_sources(tmp_path)
    for case in bundle["full"]:
        case["summary"] = json.loads((case["folder"] / "summary.json").read_text())
    for case in bundle["checks"]:
        case["events"] = json.loads((case["folder"] / "event-results.json").read_text())
        case["predictions"] = r.read_rows(case["folder"] / "held-out-record-predictions.csv")
    bundle["checks"][0]["events"].pop("aggregate_without_crossing_event")
    assert (
        r.report_tables(bundle)["lanes"][0]["checks"][0]["aggregate_without_crossing_event"][
            "status"
        ]
        == "unavailable_in_accepted_source"
    )


def reseal_case(root, gate, reseal, job):
    """Re-seal a synthetic producer chain; no accepted raw file is interpreted."""
    folder, raw = r.fit.case_paths(root, job)
    phase = "check" if raw is None else "full_development"
    manifest = {
        q.name: sha256(q)
        for q in folder.iterdir()
        if q.is_file() and q.name != "output-checksums.json"
    }
    write_json(folder / "output-checksums.json", manifest)
    files = {str(q.relative_to(root)): sha256(q) for q in folder.iterdir() if q.is_file()}
    if raw is not None and raw.exists():
        files[str(raw.relative_to(root))] = sha256(raw)
    worker_files = dict(files)
    for suffix in ["-spec.json", ".log", ".supervisor.json"]:
        path = folder.with_name(folder.name + suffix)
        if path.exists():
            files[str(path.relative_to(root))] = sha256(path)
    receipt = r.CONTROL + f"/attempts/{phase}/{job['id']}.json"
    record = json.loads((root / receipt).read_text())
    record.update(files=files, worker_files=worker_files)
    write_json(root / receipt, record)
    if raw is not None:
        descriptor = next(d for d in gate["accepted"] if d["job"] == job)
        descriptor.update(files=files, receipt_sha256=sha256(root / receipt))
    else:
        review = json.loads((root / r.data.CHECK_REVIEW).read_text())
        review["files"] = {
            n: h
            for n, h in review["files"].items()
            if not n.startswith(str(folder.relative_to(root))) and n != receipt
        }
        review["files"].update(files)
        review["files"][receipt] = sha256(root / receipt)
        write_json(root / r.data.CHECK_REVIEW, review)
    reseal()


@pytest.mark.parametrize("missing", ["raw", "sampling-start.json", "spec", "log", "process"])
def test_resealed_missing_required_full_producer_fails_before_tables(
    tmp_path, monkeypatch, missing
):
    gate, reseal, admissions = fixture(tmp_path, monkeypatch)
    job = admissions["full_development"]["gate"]["jobs"][0]
    folder, raw = r.fit.case_paths(tmp_path, job)
    assert raw is not None
    if missing == "raw":
        raw.unlink()
        result = json.loads((folder / "result.json").read_text())
        result["posterior_sha256"] = None
        write_json(folder / "result.json", result)
    elif missing == "sampling-start.json":
        (folder / missing).unlink()
    else:
        suffix = {"spec": "-spec.json", "log": ".log", "process": ".supervisor.json"}[missing]
        folder.with_name(folder.name + suffix).unlink()
    reseal_case(tmp_path, gate, reseal, job)
    monkeypatch.setattr(
        r,
        "_match_table",
        lambda *args: pytest.fail("table body before required producer admission"),
    )
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_explicit_null_supplemental_score_publishes_unavailable_without_reconstruction(
    tmp_path, monkeypatch
):
    gate, reseal, admissions = fixture(tmp_path, monkeypatch)
    job = admissions["check_evaluate"]["gate"]["jobs"][0]
    folder, _ = r.fit.case_paths(tmp_path, job)
    for name in ["event-results.json", "result.json"]:
        content = json.loads((folder / name).read_text())
        content["aggregate_without_crossing_event"] = None
        write_json(folder / name, content)
    reseal_case(tmp_path, gate, reseal, job)
    r.report(tmp_path, tmp_path / "output")
    summary = json.loads((tmp_path / "output/summary.json").read_text())
    assert summary["lanes"][0]["checks"][0]["aggregate_without_crossing_event"] is None
    assert "source-null; score/MCSE unavailable" in (tmp_path / "output/findings.md").read_text()


@pytest.mark.parametrize("bad", ["call-count", "amendment-input", "unreviewed-summary"])
def test_ms5_numerical_history_must_come_from_complete_accepted_metadata(
    tmp_path, monkeypatch, bad
):
    gate, reseal, _ = fixture(tmp_path, monkeypatch)
    review = json.loads((tmp_path / r.data.MS5_REVIEW).read_text())
    summary_name = str((tmp_path / r.data.MS5_REVIEW).parent.relative_to(tmp_path) / "summary.json")
    inputs_name = str((tmp_path / r.data.MS5_REVIEW).parent.relative_to(tmp_path) / "inputs.json")
    if bad == "call-count":
        saved = json.loads((tmp_path / summary_name).read_text())
        saved["actual_sampler_calls"] = saved["calls_charged"] = 58
        write_json(tmp_path / summary_name, saved)
        review["files"][summary_name] = sha256(tmp_path / summary_name)
    elif bad == "amendment-input":
        inputs = json.loads((tmp_path / inputs_name).read_text())
        inputs["protocol_amendment"]["first_attempt_original_case_ids"] = []
        write_json(tmp_path / inputs_name, inputs)
        review["files"][inputs_name] = sha256(tmp_path / inputs_name)
    else:
        review["files"].pop(summary_name)
    write_json(tmp_path / r.data.MS5_REVIEW, review)
    reseal()
    monkeypatch.setattr(r, "_match_table", lambda *args: pytest.fail("table before MS5 provenance"))
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_accepted_ms5_without_numeric_history_does_not_invent_repair_counts(tmp_path, monkeypatch):
    _, reseal, _ = fixture(tmp_path, monkeypatch)
    review = json.loads((tmp_path / r.data.MS5_REVIEW).read_text())
    summary_name = str((tmp_path / r.data.MS5_REVIEW).parent.relative_to(tmp_path) / "summary.json")
    saved = json.loads((tmp_path / summary_name).read_text())
    saved.pop("actual_sampler_calls")
    write_json(tmp_path / summary_name, saved)
    review["files"][summary_name] = sha256(tmp_path / summary_name)
    write_json(tmp_path / r.data.MS5_REVIEW, review)
    reseal()
    r.report(tmp_path, tmp_path / "output")
    text = (tmp_path / "output/findings.md").read_text()
    assert "counts are unavailable in the accepted source" in text
    assert "57 sampler calls" not in text and "2 retained failed calls" not in text


def schema3_fixture(root, monkeypatch):
    gate, reseal, admissions = fixture(root, monkeypatch)
    controller_path = (
        r.data.ART + "exploration-sensitivity-v1/remaining-sensitivities-v1/run-summary.json"
    )
    probes_path = str(
        (root / r.data.MS5_REVIEW).parent.relative_to(root) / "probe-dispositions.json"
    )
    jobs: list[dict[str, Any]] = [
        dict(
            id=f"case-{i}",
            order=i,
            seed=1000 + i,
            target="NCEI-native-duration",
            kind="distance-scale",
            prior_variant="base",
            scenario="era-2014plus" if i == 36 else "synthetic",
        )
        for i in range(55)
    ]
    protocol = dict(
        draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
    )

    def execution(job, attempt):
        return dict(
            id=f"ms5-numerical-protocol-v2-{job['order']:03d}-attempt-{attempt}",
            original_job=job,
            attempt=attempt,
            sampler={**protocol, "seed": job["seed"]},
            order=job["order"],
        )

    failures = [
        dict(
            case_id=jobs[i]["id"],
            order=i,
            attempt=attempt,
            original_job=jobs[i],
            execution_job=jobs[i] if attempt == 1 else execution(jobs[i], 2),
            receipt=f"retained/{i}-{attempt}.json",
            posterior=f"retained/{i}-{attempt}.nc",
        )
        for i, attempt in [(34, 1), (36, 1), (36, 2)]
    ]
    unresolved = [
        dict(
            case_id=jobs[36]["id"],
            order=36,
            original_job=jobs[36],
            status="computationally_unresolved",
            failed_attempts=failures[1:],
            no_third_attempt=True,
            posterior=None,
        )
    ]
    accepted = [
        dict(
            case_id=job["id"],
            order=job["order"],
            original_job=job,
            execution_job=execution(job, 1) if job["order"] >= 37 else job,
            posterior=f"usable/{job['id']}.nc",
        )
        for job in jobs
        if job["order"] != 36
    ]
    probes = [
        dict(
            case_id=job["id"],
            order=job["order"],
            original_job=job,
            status="computationally_unresolved"
            if job["order"] == 36
            else "accepted_scientific_computation",
            posterior=None if job["order"] == 36 else f"usable/{job['id']}.nc",
        )
        for job in jobs
    ]
    counts = dict(
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
    amendment = dict(
        protocol=dict(
            draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie"
        ),
        first_attempt_original_case_ids=[job["id"] for job in jobs[37:]],
        execution_jobs=[execution(job, 1) for job in jobs[37:]],
    )
    mapping = {jobs[34]["id"]: dict(posterior=accepted[34]["posterior"])}
    controller = dict(
        schema_version=3,
        status="sensitivity_program_complete_with_unresolved_case",
        **counts,
        accepted=accepted,
        retained_failures=failures,
        unresolved_cases=unresolved,
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
    )
    write_json(root / controller_path, controller)
    old_inputs = json.loads((root / r.MS5_INPUTS).read_text())
    inputs = dict(
        files={**old_inputs["files"], controller_path: sha256(root / controller_path)},
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
    )
    qualification = (
        "The NCEI linear 2014-onward sensitivity remains computationally unresolved "
        "after two failed attempts. "
        "This gap cannot establish robustness or favor curvature; its 150 observations "
        "remain in other applicable fits."
    )
    saved = dict(
        **counts,
        views=68,
        new_fits=54,
        base_references=8,
        reused_training_posteriors=6,
        unresolved_cases=unresolved,
        probe_dispositions=probes,
        unresolved_comparison=qualification,
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        numerical_repair_method="Same models, priors, masks, cohorts and seeds; no third attempt.",
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        selection="none",
    )
    write_json(root / r.MS5_INPUTS, inputs)
    write_json(root / r.MS5_SUMMARY, saved)
    write_json(root / probes_path, dict(probes=probes, unresolved_cases=unresolved))

    def seal_ms5():
        review = json.loads((root / r.data.MS5_REVIEW).read_text())
        review["files"].update(
            {
                name: sha256(root / name)
                for name in [r.MS5_INPUTS, r.MS5_SUMMARY, controller_path, probes_path]
            }
        )
        write_json(root / r.data.MS5_REVIEW, review)
        reseal()

    seal_ms5()
    return gate, seal_ms5, admissions, controller_path, probes_path


def test_schema3_sensitivity_gap_and_counts_propagate_without_failed_posterior_reads(
    tmp_path, monkeypatch
):
    schema3_fixture(tmp_path, monkeypatch)
    r.report(tmp_path, tmp_path / "output")
    summary = json.loads((tmp_path / "output/summary.json").read_text())
    history = summary["sensitivity_history"]
    assert history["planned_cases"] == history["completed_probes"] == 55
    assert history["accepted_logical_fits"] == 54 and history["unresolved_case_count"] == 1
    assert history["actual_sampler_calls"] == 57 and history["retained_failed_calls"] == 3
    assert set(history["successful_numerical_repair_mapping"]) == {"case-34"}
    assert history["unresolved_cases"][0]["posterior"] is None
    text = (tmp_path / "output/findings.md").read_text()
    assert "54 usable fits" in text and "55 planned probes" in text
    assert "3 retained failed calls" in text and "57 sampler calls" in text
    assert "computationally unresolved" in text and "2014-onward" in text
    assert history["unresolved_comparison"] in text
    assert text.index("computationally unresolved") < text.index("## NCEI-native-duration")
    assert "cannot establish robustness or favor curvature" in text


@pytest.mark.parametrize(
    "bad",
    [
        "call-count",
        "missing-count",
        "extra-repair",
        "missing-repair",
        "qualification",
        "third-attempt",
        "posterior",
        "unresolved-probe",
        "controller-schema",
        "controller-unbound",
    ],
)
def test_resealed_schema3_history_rejects_malformed_metadata_before_tables(
    tmp_path, monkeypatch, bad
):
    _, seal, _, controller_path, probes_path = schema3_fixture(tmp_path, monkeypatch)
    saved = json.loads((tmp_path / r.MS5_SUMMARY).read_text())
    inputs = json.loads((tmp_path / r.MS5_INPUTS).read_text())
    controller = json.loads((tmp_path / controller_path).read_text())
    probes = json.loads((tmp_path / probes_path).read_text())
    if bad == "call-count":
        for value in [saved, controller]:
            value["actual_sampler_calls"] = value["calls_charged"] = 58
    elif bad == "missing-count":
        for value in [saved, controller]:
            value.pop("actual_sampler_calls")
    elif bad in {"extra-repair", "missing-repair"}:
        for value in [saved, inputs, controller]:
            if bad == "extra-repair":
                value["successful_numerical_repair_mapping"]["case-36"] = {
                    "posterior": "retained/36-2.nc"
                }
            else:
                value["successful_numerical_repair_mapping"] = {}
    elif bad == "qualification":
        saved["unresolved_comparison"] = ""
    elif bad in {"third-attempt", "posterior"}:
        for value in [saved, controller, probes]:
            missing = value["unresolved_cases"][0]
            if bad == "third-attempt":
                missing["no_third_attempt"] = False
            else:
                missing["posterior"] = "retained/36-2.nc"
    elif bad == "unresolved-probe":
        saved["probe_dispositions"][36]["status"] = "accepted_scientific_computation"
        probes["probes"][36]["status"] = "accepted_scientific_computation"
    elif bad == "controller-schema":
        controller["schema_version"] = 2
    else:
        inputs["files"].pop(controller_path)
    write_json(tmp_path / controller_path, controller)
    if bad != "controller-unbound":
        inputs["files"][controller_path] = sha256(tmp_path / controller_path)
    write_json(tmp_path / r.MS5_INPUTS, inputs)
    write_json(tmp_path / r.MS5_SUMMARY, saved)
    write_json(tmp_path / probes_path, probes)
    seal()
    monkeypatch.setattr(
        r, "_match_table", lambda *a: pytest.fail("table body before schema3 history admission")
    )
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_legacy_compatibility_requires_complete69_view_source(tmp_path, monkeypatch):
    _, reseal, _ = fixture(tmp_path, monkeypatch)
    saved = json.loads((tmp_path / r.MS5_SUMMARY).read_text())
    saved["views"] = 68
    write_json(tmp_path / r.MS5_SUMMARY, saved)
    review = json.loads((tmp_path / r.data.MS5_REVIEW).read_text())
    review["files"][r.MS5_SUMMARY] = sha256(tmp_path / r.MS5_SUMMARY)
    write_json(tmp_path / r.data.MS5_REVIEW, review)
    reseal()
    monkeypatch.setattr(
        r, "_match_table", lambda *a: pytest.fail("table body before legacy history admission")
    )
    with pytest.raises(ValueError, match="complete69-view"):
        r.report(tmp_path, tmp_path / "output")


def test_schema3_summary_cannot_downgrade_to_legacy_unavailable(tmp_path, monkeypatch):
    _, seal, _, _, _ = schema3_fixture(tmp_path, monkeypatch)
    saved = json.loads((tmp_path / r.MS5_SUMMARY).read_text())
    for key in [
        "successful_numerical_repair_mapping",
        "unresolved_cases",
        "planned_cases",
        "accepted_logical_fits",
    ]:
        saved.pop(key)
    saved["views"] = 69
    write_json(tmp_path / r.MS5_SUMMARY, saved)
    seal()
    monkeypatch.setattr(
        r, "_match_table", lambda *a: pytest.fail("table body before schema3 routing")
    )
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "signal",
    [
        "input-mapping",
        "input-controller",
        "input-probes",
        "review-controller",
        "review-probes",
        "input-version",
        "summary-version",
    ],
)
def test_each_admitted_schema3_signal_blocks_legacy_fallback(tmp_path, signal):
    saved = {"views": 69}
    write_json(tmp_path / "source.json", {"synthetic": "nonempty admitted source"})
    base = {"source.json": sha256(tmp_path / "source.json")}
    inputs: dict[str, Any] = {"files": dict(base)}
    extra = {}
    if signal == "input-mapping":
        inputs["successful_numerical_repair_mapping"] = {}
    elif signal == "input-version":
        inputs["schema_version"] = 3
    elif signal == "summary-version":
        saved["schema_version"] = 3
    else:
        name = r.MS5_CONTROLLER if signal.endswith("controller") else r.MS5_PROBES
        write_json(tmp_path / name, {"synthetic_schema3_binding": True})
        extra[name] = sha256(tmp_path / name)
        if signal.startswith("input"):
            inputs["files"].update(extra)
    write_json(tmp_path / r.MS5_SUMMARY, saved)
    write_json(tmp_path / r.MS5_INPUTS, inputs)
    reviewed = {name: sha256(tmp_path / name) for name in [r.MS5_SUMMARY, r.MS5_INPUTS]}
    reviewed.update(base)
    if signal.startswith("review"):
        reviewed.update(extra)
    write_json(tmp_path / r.data.MS5_REVIEW, {"files": reviewed})
    pins = {**reviewed, **extra, r.data.MS5_REVIEW: sha256(tmp_path / r.data.MS5_REVIEW)}
    with pytest.raises(ValueError, match="schema3"):
        r._sensitivity_history(tmp_path, pins)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tune", 1000),
        ("target_accept", 0.95),
        ("nuts_sampler", "pymc"),
        ("chains", 2),
        ("id", "wrong-id"),
        ("attempt", 2),
        ("order", 38),
        ("controller_only", None),
    ],
)
def test_resealed_execution_jobs_require_full_producer_protocol_and_identity(
    tmp_path, monkeypatch, field, value
):
    _, seal, _, controller_path, _ = schema3_fixture(tmp_path, monkeypatch)
    saved = json.loads((tmp_path / r.MS5_SUMMARY).read_text())
    inputs = json.loads((tmp_path / r.MS5_INPUTS).read_text())
    controller = json.loads((tmp_path / controller_path).read_text())
    if field == "controller_only":
        controller["accepted"][36]["execution_job"]["id"] = "different-producer"
    else:
        for source in [saved, inputs, controller]:
            job = source["protocol_amendment"]["execution_jobs"][0]
            (job if field in {"id", "attempt", "order"} else job["sampler"])[field] = value
        controller["accepted"][36]["execution_job"] = controller["protocol_amendment"][
            "execution_jobs"
        ][0]
    write_json(tmp_path / controller_path, controller)
    inputs["files"][controller_path] = sha256(tmp_path / controller_path)
    write_json(tmp_path / r.MS5_INPUTS, inputs)
    write_json(tmp_path / r.MS5_SUMMARY, saved)
    seal()
    monkeypatch.setattr(
        r, "_match_table", lambda *a: pytest.fail("table body before full execution identity")
    )
    with pytest.raises(ValueError, match="exact18 first-attempt"):
        r.report(tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_schema3_fixture_execution_jobs_match_the_frozen_producer(tmp_path, monkeypatch):
    from analysis.arrival.model_sensitivity_numerical_fit import PROTOCOL, execution_jobs

    _, _, _, controller_path, _ = schema3_fixture(tmp_path, monkeypatch)
    controller = json.loads((tmp_path / controller_path).read_text())
    original = [entry["original_job"] for entry in controller["accepted"][36:]]
    expected = execution_jobs(
        original, "numerical-protocol-v2", {job["id"]: 1 for job in original}, PROTOCOL
    )
    assert controller["protocol_amendment"]["execution_jobs"] == expected
    assert [entry["execution_job"] for entry in controller["accepted"][36:]] == expected


def schema4_fixture(root, monkeypatch, *, exhausted47=False):
    gate, old_seal, admissions, _, probes_path = schema3_fixture(root, monkeypatch)
    jobs = [p["original_job"] for p in json.loads((root / probes_path).read_text())["probes"]]
    jobs[47]["kind"] = "mean-curvature"
    jobs[47]["scenario"] = "era-2014plus"
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

    finish_gate = (
        r.data.ART + "sensitivity-design-v1/finish-sensitivities-v1/review-acceptance.json"
    )
    numerical_gate = (
        r.data.ART + "sensitivity-design-v1/numerical-protocol-v2/review-acceptance.json"
    )
    old_execution_gate = (
        r.data.ART + "sensitivity-design-v1/remaining-sensitivities-v1/review-acceptance.json"
    )
    controller_path = (
        r.data.ART + "exploration-sensitivity-v1/finish-sensitivities-v1/run-summary.json"
    )
    decision_path = (
        r.data.ART
        + "exploration-sensitivity-v1/finish-sensitivities-v1/case47-review-acceptance.json"
    )
    write_json(root / finish_gate, {"synthetic": "authority"})
    repair_job = execution(47, 2)
    tail = [execution(n) for n in range(48, 55)]
    failed = []
    for n, attempt in [(34, 1), (36, 1), (36, 2), (47, 1)] + ([(47, 2)] if exhausted47 else []):
        failed.append(
            dict(
                case_id=jobs[n]["id"],
                order=n,
                attempt=attempt,
                original_job=jobs[n],
                execution_job=execution(n, attempt) if n == 47 or attempt == 2 else jobs[n],
                receipt=f"retained/{n}-{attempt}.json",
                posterior=f"retained/{n}-{attempt}.nc",
            )
        )
    missing_orders = [36, 47] if exhausted47 else [36]
    unresolved = [
        dict(
            case_id=jobs[n]["id"],
            order=n,
            original_job=jobs[n],
            status="computationally_unresolved",
            failed_attempts=[f for f in failed if f["order"] == n],
            no_third_attempt=True,
            posterior=None,
        )
        for n in missing_orders
    ]
    accepted = []
    for job in jobs:
        n = job["order"]
        if n in missing_orders:
            continue
        e = dict(
            case_id=job["id"],
            order=n,
            original_job=job,
            execution_job=repair_job if n == 47 else execution(n) if n >= 37 else job,
            posterior=f"usable/{job['id']}.nc",
            posterior_sha256="a" * 64,
        )
        if n >= 37:
            e.update(
                producer="repair47" if n == 47 else "numerical_protocol",
                source_role="numerical_repair" if n == 47 else "numerical_protocol",
                execution_gate=finish_gate if n >= 47 else old_execution_gate,
                worker_spec_gate=finish_gate if n == 47 else numerical_gate,
            )
        accepted.append(e)
    by_order = {e["order"]: e for e in accepted}
    probes = [
        dict(
            case_id=j["id"],
            order=j["order"],
            original_job=j,
            status="computationally_unresolved"
            if j["order"] in missing_orders
            else "accepted_scientific_computation",
            posterior=None if j["order"] in missing_orders else by_order[j["order"]]["posterior"],
        )
        for j in jobs
    ]
    counts = dict(
        planned_cases=55,
        completed_probes=55,
        accepted_logical_fits=len(accepted),
        unresolved_case_count=len(unresolved),
        actual_sampler_calls=58,
        calls_charged=58,
        calls_started=58,
        retained_failed_calls=len(failed),
        max_sampler_call_slots=110,
    )
    mapping = {
        jobs[n]["id"]: {k: by_order[n][k] for k in ["posterior", "posterior_sha256"]}
        for n in ([34] if exhausted47 else [34, 47])
    }
    amendment = dict(
        protocol=protocol,
        first_attempt_original_case_ids=[j["id"] for j in jobs[37:]],
        execution_jobs=[execution(n) for n in range(37, 55)],
        case47_final_repair=dict(
            execution_job=repair_job,
            protocol=repair_protocol,
            worker_spec_gate=finish_gate,
            worker_spec_gate_sha256=sha256(root / finish_gate),
        ),
        remaining_execution_jobs=tail,
    )
    outcome = "exhausted_unresolved" if exhausted47 else "accepted_repair"
    decision = dict(
        status="accepted_sensitivity_case47_disposition",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        case47_outcome=outcome,
        repair_job=repair_job,
        calls_charged=51,
        calls_started=51,
        execution_authority_gate_sha256=sha256(root / finish_gate),
        repair_spec_gate_sha256=sha256(root / finish_gate),
        files={finish_gate: sha256(root / finish_gate)},
    )
    write_json(root / decision_path, decision)
    common = dict(
        schema_version=4,
        case47_outcome=outcome,
        repair_job=repair_job,
        remaining_jobs=tail,
        case47_disposition_review=decision_path,
        case47_disposition_review_sha256=sha256(root / decision_path),
        successful_numerical_repair_mapping=mapping,
        protocol_amendment=amendment,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
    )
    controller = dict(
        common,
        **counts,
        status="sensitivity_program_complete_with_unresolved_cases",
        accepted=accepted,
        retained_failures=failed,
        unresolved_cases=unresolved,
        completion_attempts=[
            dict(execution_job=j, charged_slots=1, start_markers=1) for j in [repair_job, *tail]
        ],
    )
    write_json(root / controller_path, controller)
    inputs = json.loads((root / r.MS5_INPUTS).read_text())
    inputs.update(common)
    inputs["files"].update(
        {name: sha256(root / name) for name in [controller_path, decision_path, finish_gate]}
    )
    write_json(root / r.MS5_INPUTS, inputs)
    saved = dict(
        common,
        **counts,
        views=len(accepted) + 14,
        new_fits=len(accepted),
        selection="none",
        unresolved_cases=unresolved,
        probe_dispositions=probes,
        unresolved_comparison=(
            "Linear 2014-onward sensitivity is computationally unresolved; "
            "no robustness or curvature advantage follows."
        )
        + (
            " Curved 2014-onward sensitivity is also computationally unresolved."
            if exhausted47
            else ""
        ),
        numerical_repair_method=(
            "Repair34 .99/2000; finalrepair47 .999/4000. Same models, data, priors and seeds."
        ),
    )
    write_json(root / r.MS5_SUMMARY, saved)
    write_json(root / probes_path, dict(probes=probes, unresolved_cases=unresolved))

    def seal():
        inputs = json.loads((root / r.MS5_INPUTS).read_text())
        inputs["files"].update(
            {name: sha256(root / name) for name in [controller_path, decision_path, finish_gate]}
        )
        write_json(root / r.MS5_INPUTS, inputs)
        review = json.loads((root / r.data.MS5_REVIEW).read_text())
        review["files"].update(
            {
                name: sha256(root / name)
                for name in [
                    r.MS5_INPUTS,
                    r.MS5_SUMMARY,
                    controller_path,
                    decision_path,
                    finish_gate,
                    probes_path,
                ]
            }
        )
        write_json(root / r.data.MS5_REVIEW, review)
        old_seal()

    seal()
    return gate, seal, admissions, controller_path, decision_path


@pytest.mark.parametrize("exhausted47", [False, True])
def test_schema4_history_propagates_both_exact_terminal_branches(
    tmp_path, monkeypatch, exhausted47
):
    schema4_fixture(tmp_path, monkeypatch, exhausted47=exhausted47)
    r.report(tmp_path, tmp_path / "report")
    saved = json.loads((tmp_path / "report" / "summary.json").read_text())
    history = saved["sensitivity_history"]
    assert history["source_schema_version"] == 4
    assert history["accepted_logical_fits"] == (53 if exhausted47 else 54)
    assert history["actual_sampler_calls"] == 58 and history["retained_failed_calls"] == (
        5 if exhausted47 else 4
    )
    assert [x["order"] for x in history["unresolved_cases"]] == ([36, 47] if exhausted47 else [36])
    text = (tmp_path / "report" / "findings.md").read_text()
    assert "computationally unresolved" in text and "58 sampler calls" in text


@pytest.mark.parametrize("exhausted47", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        "counts",
        "mapping-index",
        "repair-protocol",
        "tail-protocol",
        "initial47-retuned",
        "wrong-authority",
        "lost-outcome",
        "qualification",
        "no-third",
        "disposition-type",
    ],
)
def test_schema4_resealed_semantic_corruptions_reject_before_tables(
    tmp_path, monkeypatch, exhausted47, bad
):
    _, seal, _, controller_path, decision_path = schema4_fixture(
        tmp_path, monkeypatch, exhausted47=exhausted47
    )
    saved = json.loads((tmp_path / r.MS5_SUMMARY).read_text())
    inputs = json.loads((tmp_path / r.MS5_INPUTS).read_text())
    controller = json.loads((tmp_path / controller_path).read_text())
    decision = json.loads((tmp_path / decision_path).read_text())
    if bad == "counts":
        saved["actual_sampler_calls"] = 57
    elif bad == "mapping-index":
        for value in [saved, inputs, controller]:
            value["successful_numerical_repair_mapping"]["case-47"] = {
                "posterior": controller["accepted"][47]["posterior"],
                "posterior_sha256": "a" * 64,
            }
    elif bad in ["repair-protocol", "tail-protocol", "initial47-retuned"]:
        for value in [saved, inputs, controller]:
            if bad == "repair-protocol":
                value["repair_job"]["sampler"].update(tune=2000, target_accept=0.99)
                value["protocol_amendment"]["case47_final_repair"]["execution_job"][
                    "sampler"
                ].update(tune=2000, target_accept=0.99)
                value["protocol_amendment"]["case47_final_repair"]["protocol"].update(
                    tune=2000, target_accept=0.99
                )
            elif bad == "tail-protocol":
                value["remaining_jobs"][0]["sampler"]["nuts_sampler"] = "pymc"
                value["protocol_amendment"]["remaining_execution_jobs"][0]["sampler"][
                    "nuts_sampler"
                ] = "pymc"
            else:
                value["protocol_amendment"]["execution_jobs"][10]["sampler"].update(
                    tune=4000, target_accept=0.999
                )
        if bad == "repair-protocol":
            for e in controller["accepted"]:
                if e["order"] == 47:
                    e["execution_job"]["sampler"].update(tune=2000, target_accept=0.99)
            for f in controller["retained_failures"]:
                if f["order"] == 47 and f["attempt"] == 2:
                    f["execution_job"]["sampler"].update(tune=2000, target_accept=0.99)
    elif bad == "wrong-authority":
        next(e for e in controller["accepted"] if e["order"] == 48)["execution_gate"] = (
            r.MS5_OLD_EXECUTION_GATE
        )
    elif bad == "lost-outcome":
        saved.pop("case47_outcome")
    elif bad == "qualification":
        saved["unresolved_comparison"] = ""
    elif bad == "no-third":
        saved["unresolved_cases"][0]["no_third_attempt"] = False
    else:
        decision["case47_outcome"] = "accepted_repair" if exhausted47 else "exhausted_unresolved"
    for path, value in [
        (r.MS5_SUMMARY, saved),
        (r.MS5_INPUTS, inputs),
        (controller_path, controller),
        (decision_path, decision),
    ]:
        write_json(tmp_path / path, value)
    seal()
    monkeypatch.setattr(
        r, "_match_table", lambda *a: pytest.fail("table body before schema4 admission")
    )
    with pytest.raises(ValueError):
        r.report(tmp_path, tmp_path / "report")


@pytest.mark.parametrize(
    "signal",
    [
        "saved-key",
        "inputs-key",
        "saved-version",
        "inputs-version",
        "review-controller",
        "inputs-controller",
        "review-decision",
        "inputs-decision",
    ],
)
def test_each_schema4_signal_prevents_legacy_or_schema3_fallback(tmp_path, signal):
    saved: dict[str, Any] = {"views": 69}
    sentinel = tmp_path / "synthetic-source.txt"
    sentinel.write_text("synthetic admitted source")
    inputs: dict[str, Any] = {"files": {"synthetic-source.txt": sha256(sentinel)}}
    if signal == "saved-key":
        saved["case47_outcome"] = "accepted_repair"
    elif signal == "inputs-key":
        inputs["repair_job"] = {}
    elif signal == "saved-version":
        saved["schema_version"] = 4
    elif signal == "inputs-version":
        inputs["schema_version"] = 4
    for path, body in [(r.MS5_SUMMARY, saved), (r.MS5_INPUTS, inputs)]:
        write_json(tmp_path / path, body)
    extra = {}
    if signal.startswith(("review-", "inputs-")) and signal not in ["inputs-key", "inputs-version"]:
        name = (
            r.MS5_FINISH_CONTROLLER if signal.endswith("controller") else r.MS5_FINISH_DISPOSITION
        )
        write_json(tmp_path / name, {"schema4_binding": True})
        extra[name] = sha256(tmp_path / name)
        if signal.startswith("inputs-"):
            inputs["files"].update(extra)
            write_json(tmp_path / r.MS5_INPUTS, inputs)
    pins = {name: sha256(tmp_path / name) for name in [r.MS5_SUMMARY, r.MS5_INPUTS]}
    pins.update(inputs["files"])
    pins.update(extra)
    review = {"files": dict(pins)}
    write_json(tmp_path / r.data.MS5_REVIEW, review)
    pins[r.data.MS5_REVIEW] = sha256(tmp_path / r.data.MS5_REVIEW)
    with pytest.raises(ValueError, match="schema4"):
        r._sensitivity_history(tmp_path, pins)


def test_schema4_fixture_full_execution_shapes_match_real_worker(tmp_path, monkeypatch):
    from analysis.arrival import model_sensitivity_numerical_fit as producer

    _, _, _, path, _ = schema4_fixture(tmp_path, monkeypatch)
    run = json.loads((tmp_path / path).read_text())
    job = run["repair_job"]["original_job"]
    assert (
        run["repair_job"]
        == producer.execution_jobs(
            [job],
            "numerical-protocol-v2",
            {job["id"]: 2},
            {**producer.PROTOCOL, "tune": 4000, "target_accept": 0.999},
        )[0]
    )
    jobs = [e["original_job"] for e in run["remaining_jobs"]]
    assert run["remaining_jobs"] == producer.execution_jobs(
        jobs, "numerical-protocol-v2", {j["id"]: 1 for j in jobs}, dict(producer.PROTOCOL)
    )
