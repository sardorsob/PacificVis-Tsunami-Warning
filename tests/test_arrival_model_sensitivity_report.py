"""Synthetic69-view arithmetic and closed-admission report checks; no real fits/outcomes."""

# pyright: basic
from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest

from analysis.arrival import model_sensitivity_report as report
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_sensitivity_design import FORMS, NONPRIOR_SCENARIOS, PRIOR_VARIANTS
from analysis.arrival.model_sensitivity_summary import GRID_KM, summarize_posterior
from tests.test_arrival_model_sensitivity_summary import lane, posterior


def summary(target, kind, *, shift=0.0, training=None, support=(20, 20000)):
    training = training or ["record-a", "record-b", "record-c"]
    positive = target != "T-CAL"

    def quantiles(values):
        return {
            **dict(zip(["q05", "q50", "q95"], values, strict=True)),
            "quantile_valid": True,
            "native_representable": True,
            "nonfinite_values": 0,
            "nonfinite_quantile_values": 0,
        }

    curves, derived = [], []
    for d in GRID_KM:
        within = bool(support[0] <= d <= support[1])
        common = {
            "distance_km": float(d),
            "within_training_distance_range": within,
            "support": "within" if within else "below" if d < support[0] else "above",
        }
        for curve, width in [("population_median", 0.2), ("new_event", 0.8)]:
            logs = [math.log(d / 10) + shift + x for x in [-width, 0, width]]
            values = [math.exp(x) for x in logs] if positive else [shift + x for x in [-10, 0, 10]]
            row = {**common, "curve": curve, **quantiles(values)}
            if positive:
                row.update(dict(zip(["log_q05", "log_q50", "log_q95"], logs, strict=True)))
            curves.append(row)
        derived.append(
            {**common, "quantity": "residual_sd_modeled_response", **quantiles([0.1, 0.2, 0.3])}
        )
        if positive:
            derived.append(
                {
                    **common,
                    "quantity": "population_median_log_distance_elasticity",
                    **quantiles([0.9, 1, 1.1]),
                }
            )
    return {
        "target": target,
        "kind": kind,
        "membership": training,
        "parameters": [
            {
                "parameter": "alpha",
                "anchor_km": None,
                **quantiles([shift - 0.1, shift, shift + 0.1]),
            }
        ],
        "derived": derived,
        "curves": curves,
        "record_intervals": [{"record_id": rid, **quantiles([1, 2, 3])} for rid in training],
        "conditional_ppc": [
            {
                "stratum": "all",
                "scale": "native-minutes",
                "quantile": 0.5,
                "records": len(training),
                "observed": 4,
                "observed_quantile_valid": True,
                **{"replicated_" + k: v for k, v in quantiles([1, 2, 3]).items()},
            }
        ],
        "support": {
            "records": len(training),
            "distance_km_min": support[0],
            "distance_km_max": support[1],
            "event_counts": {"event": len(training)},
            "sequence_counts": {"sequence": len(training)},
            "sites": len(training),
            "matrix_rank": 1,
            "expected_rank": 1,
            "full_rank": True,
        },
        "conditional_predictive_draws": 800,
        "posterior_draws": 8000,
        "nonfinite_values": {},
        "unrepresentable_native_draws": {},
        "native_predictive_means_or_variances_reported": False,
    }


def views():
    result = []

    def add(target, kind, role, variant, scenario, *, shift=0.0, subset=False):
        training = ["record-a", "record-b"] if subset else ["record-a", "record-b", "record-c"]
        result.append(
            {
                "view_id": f"{target}:{kind}:{role}:{variant}:{scenario}",
                "target": target,
                "kind": kind,
                "role": role,
                "prior_variant": variant,
                "scenario": scenario,
                "distance_mode": "publisher_native_km"
                if scenario == "publisher-distance"
                else "geodesic_km",
                "training_record_ids": training,
                "omitted_record_ids": ["record-c"] if subset else [],
                "excluded_record_ids": ["edge-exclusion"],
                "prior_specification": {"variant": variant},
                "summary": summary(
                    target,
                    kind,
                    shift=shift,
                    training=training,
                    support=(100, 5000) if subset else (20, 20000),
                ),
                "provenance": {"new_sampler_calls": 1 if role == "sensitivity" else 0},
            }
        )

    for target, kind in FORMS:
        add(target, kind, "base", "base", "base")
        for variant in PRIOR_VARIANTS:
            add(
                target, kind, "sensitivity", variant, "prior", shift=3 if target == "T-CAL" else 0.1
            )
    add(
        "NCEI-native-duration",
        "mean-curvature",
        "sensitivity",
        "gamma_wider_only",
        "prior",
        shift=0.2,
    )
    for kind in ["distance-scale", "mean-curvature"]:
        for scenario in NONPRIOR_SCENARIOS:
            add(
                "NCEI-native-duration",
                kind,
                "sensitivity",
                "base",
                scenario,
                shift=-0.3,
                subset=scenario != "publisher-distance",
            )
        for name in ["reuse-tohoku", "reuse-chile2010", "reuse-influential2014"]:
            add("NCEI-native-duration", kind, name, "base", name, shift=0.4, subset=True)
    assert len(result) == 69
    return result


def test_independent_log_ratio_and_signed_minutes_change_oracles():
    data = views()
    before = copy.deepcopy(data)
    tables = report.sensitivity_tables(data)
    assert data == before
    changes = tables[report.TABLES[2]]
    assert len(changes) == 69 * 9
    positive = next(r for r in changes if r["scenario"] == "prior" and r["target"] == "T-OBS")
    assert positive["median_log_shift"] == pytest.approx(0.1)
    assert positive["native_median_ratio"] == pytest.approx(math.exp(0.1))
    signed = next(r for r in changes if r["scenario"] == "prior" and r["target"] == "T-CAL")
    assert signed["signed_median_shift_minutes"] == 3
    assert signed["native_median_ratio"] is None and signed["median_log_shift"] is None
    base = [r for r in changes if r["role"] == "base"]
    assert all(r["median_log_shift"] == 0 for r in base if r["target"] != "T-CAL")
    assert all(r["signed_median_shift_minutes"] == 0 for r in base if r["target"] == "T-CAL")
    assert all("q05" not in r and "q95" not in r for r in changes)


def test_support_intersection_masks_changes_and_all_exported_curves():
    tables = report.sensitivity_tables(views())
    changes = [r for r in tables[report.TABLES[2]] if r["scenario"] == "coastal-only"]
    assert len(changes) == 18
    for row in changes:
        assert row["common_supported"] == (100 <= row["distance_km"] <= 5000)
        if not row["common_supported"]:
            assert row["median_log_shift"] is row["native_median_ratio"] is None
    assert all(r["within_training_distance_range"] for r in tables[report.TABLES[1]])
    types = {r["curve"]: r["interval_type"] for r in tables[report.TABLES[1]]}
    assert types == {
        "population_median": "90% posterior band for population median",
        "new_event": "90% new-event report predictive quantiles",
    }


def test_population_quantiles_from_real_toy_explicit_posterior_match_numpy():
    toy, post = lane(), posterior(draws=250)
    post["alpha"].values[:] = np.arange(1000).reshape(4, 250) / 1000
    result = summarize_posterior(
        toy, "mean-curvature", post, indices=np.arange(3), seed=2916110800, draws=800
    )
    row = next(
        r
        for r in result["curves"]
        if r["curve"] == "population_median" and r["distance_km"] == 1000
    )
    # At1000km both mean basis terms vanish, and duration reference is1000/VREF.
    from analysis.arrival.model_data import VREF_KM_MIN

    expected_logs = np.quantile(post.alpha.values, [0.05, 0.5, 0.95]) + math.log(1000 / VREF_KM_MIN)
    np.testing.assert_allclose([row["log_q05"], row["log_q50"], row["log_q95"]], expected_logs)
    np.testing.assert_allclose([row["q05"], row["q50"], row["q95"]], np.exp(expected_logs))
    assert result["conditional_predictive_draws"] == 800


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "cohort",
        "membership",
        "support",
        "quantile",
        "native-log",
        "nonfinite",
        "draws",
        "means",
        "missing-base",
    ],
)
def test_malformed_views_rejected(mutation):
    data = views()
    if mutation == "duplicate":
        data[1]["view_id"] = data[0]["view_id"]
    elif mutation == "cohort":
        data[1]["excluded_record_ids"].append("record-a")
    elif mutation == "membership":
        data[1]["summary"]["membership"] = ["other"]
    elif mutation == "support":
        data[1]["summary"]["curves"][0]["within_training_distance_range"] = False
    elif mutation == "quantile":
        data[1]["summary"]["curves"][0]["q05"] = 100000
    elif mutation == "native-log":
        data[1]["summary"]["curves"][0]["log_q50"] += 1
    elif mutation == "nonfinite":
        data[1]["summary"]["nonfinite_values"] = {"replicated": 1}
    elif mutation == "draws":
        data[1]["summary"]["conditional_predictive_draws"] = 799
    elif mutation == "means":
        data[1]["summary"]["native_predictive_means_or_variances_reported"] = True
    else:
        data[0]["role"] = "sensitivity"
    with pytest.raises(ValueError):
        report.sensitivity_tables(data)


def test_exact_cohort_ids_and_ppc_count_arithmetic():
    tables = report.sensitivity_tables(views())
    cohorts = tables[report.TABLES[4]]
    assert len(cohorts) == 69 and sum(r["new_sampler_calls"] for r in cohorts) == 55
    subset = next(r for r in cohorts if r["scenario"] == "omit-triage")
    assert json.loads(subset["training_record_ids"]) == ["record-a", "record-b"]
    assert json.loads(subset["omitted_record_ids"]) == ["record-c"]
    assert json.loads(subset["excluded_record_ids"]) == ["edge-exclusion"]
    ppc = tables[report.TABLES[3]]
    assert len(ppc) == 69 and all(r["observed_outside_replicated_90"] for r in ppc)
    text = report.findings(tables, {"calls_charged": 55})
    assert all(
        phrase in text
        for phrase in [
            "T-OBS is reported observed UTC minus the reviewed USGS origin",
            "positive reported travel duration",
            "T-CAL is reported estimated UTC minus reported observed UTC",
            "signed archive discrepancy, distinct from travel duration",
            "Positive T-CAL means the estimate was later than the observation",
            "negative T-CAL means the estimate was earlier",
            "source observation and forecast calendar contexts",
        ]
    )
    for phrase in [
        "8/15",
        "1,125-minute",
        "800",
        "Normal residual likelihood",
        "infinite",
        "T-CAL lineage is unknown",
        "19-event",
        "18 reserved",
        "in-sample",
        "interval overlap",
        "autocorrelation",
        "not expert facts",
        "1/2/5-km",
    ]:
        assert phrase in text
    assert "69 observed quantile checks" in text and "110-call ceiling" in text
    assert report.SCENARIO_LABELS["reuse-influential2014"].startswith("Omit SW Pacific 2014")


def admission_fixture(root, monkeypatch):
    source = "source.py"
    (root / source).write_text("synthetic source")
    for name in report.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source helper")
    write_json(root / report.fit.GATE, {"status": "synthetic base gate"})
    original_pins = {p: sha256(root / p) for p in [source, *report.CONSUMED, report.fit.GATE]}
    jobs = [{"id": f"case-power-0.5-{i:02d}", "order": i} for i in range(55)]
    admission = {"files": original_pins, "gate": {"jobs": jobs}, "contract": {}}
    monkeypatch.setattr(report.fit, "verify_gate", lambda root: admission)
    monkeypatch.setattr(report.refs, "verify_reference_sources", lambda root, pins: None)
    write_json(
        root / report.PLAN,
        {"jobs": jobs, "files": original_pins, "gate_sha256": original_pins[report.fit.GATE]},
    )
    write_json(
        root / report.RUN_SUMMARY,
        {
            "status": "sensitivity_computations_complete",
            "next_case": 55,
            "planned_cases": 55,
            "calls_charged": 55,
            "calls_started": 55,
            "max_sampler_call_slots": 110,
            "monitor_failures": [],
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    accepted = []
    pins = {**original_pins, **{p: sha256(root / p) for p in [report.PLAN, report.RUN_SUMMARY]}}
    for job in jobs:
        folder = report.fit.OUTPUT + "/jobs/" + job["id"]
        names = [
            folder + "/" + name
            for name in [
                "job.json",
                "inputs.json",
                "membership.json",
                "sampling-start.json",
                "result.json",
                "diagnostics.json",
                "sampling-diagnostics.csv",
                "summary.json",
                "parameters.csv",
                "derived.csv",
                "curves.csv",
                "conditional-ppc.csv",
                "record-intervals.csv",
            ]
        ]
        names += [folder + suffix for suffix in ["-spec.json", ".log", ".supervisor.json"]]
        names += [report.fit.STORE + "/" + job["id"] + ".nc"]
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic evidence, must never be parsed in admission")
        files = {name: sha256(root / name) for name in names}
        receipt = folder + "/attempt-evidence.json"
        write_json(root / receipt, {"case_id": job["id"], "files": files})
        accepted.append(
            {
                "case_id": job["id"],
                "charged_slots": 1,
                "files": files,
                "receipt": receipt,
                "receipt_sha256": sha256(root / receipt),
            }
        )
        pins.update({**files, receipt: sha256(root / receipt)})
    gate = {
        "status": "accepted_all_exploration_sensitivity_computations",
        "independent_checker": True,
        "files": pins,
        "accepted": accepted,
        "reference_summary": report.REFERENCE_SUMMARY,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
    }
    write_json(root / report.GATE, gate)
    return gate, admission


def reseal(root, gate, name):
    gate["files"][name] = sha256(root / name)
    write_json(root / report.GATE, gate)


def test_admission_is_metadata_only_closes55_before_any_loader(tmp_path, monkeypatch):
    gate, _ = admission_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        report, "load_lanes", lambda *a: pytest.fail("native loader before admission")
    )
    monkeypatch.setattr(report.fit, "case_artifacts", lambda *a, **k: pytest.fail("NetCDF read"))
    monkeypatch.setattr(report, "summarize_posterior", lambda *a, **k: pytest.fail("metric read"))
    result = report.verify_report_sources(tmp_path)
    assert len(result["jobs"]) == 55 and result["gate"] == gate
    assert result["run_summary"]["calls_charged"] == 55  # 110is a ceiling, not a target.


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-gate",
        "not-independent",
        "prior-recipe",
        "missing-raw",
        "missing-receipt",
        "wrong-receipt",
        "swapped-order",
        "changed-source",
        "changed-plan",
        "incomplete",
        "overspent",
        "repair",
        "symlink",
    ],
)
def test_gate_first_and_complete_proof_requirements(tmp_path, monkeypatch, mutation):
    gate, _ = admission_fixture(tmp_path, monkeypatch)
    if mutation == "missing-gate":
        (tmp_path / report.GATE).unlink()
    elif mutation == "not-independent":
        gate["independent_checker"] = False
    elif mutation == "prior-recipe":
        gate["reference_summary"] = {**report.REFERENCE_SUMMARY, "draws": 801}
    elif mutation == "missing-raw":
        name = report.fit.STORE + "/" + gate["accepted"][-1]["case_id"] + ".nc"
        gate["files"].pop(name)
    elif mutation == "missing-receipt":
        gate["files"].pop(gate["accepted"][-1]["receipt"])
    elif mutation == "wrong-receipt":
        gate["accepted"][0]["receipt_sha256"] = "0" * 64
    elif mutation == "swapped-order":
        gate["accepted"][0], gate["accepted"][1] = gate["accepted"][1], gate["accepted"][0]
    elif mutation == "changed-source":
        (tmp_path / "source.py").write_text("changed source")
    elif mutation == "changed-plan":
        plan = json.loads((tmp_path / report.PLAN).read_text())
        plan["jobs"].reverse()
        write_json(tmp_path / report.PLAN, plan)
        reseal(tmp_path, gate, report.PLAN)
    elif mutation in {"incomplete", "overspent", "repair"}:
        summary = json.loads((tmp_path / report.RUN_SUMMARY).read_text())
        summary.update(
            calls_charged=111 if mutation == "overspent" else 56,
            calls_started=111 if mutation == "overspent" else 56,
        )
        if mutation == "incomplete":
            summary["next_case"] = 54
        write_json(tmp_path / report.RUN_SUMMARY, summary)
        reseal(tmp_path, gate, report.RUN_SUMMARY)
    else:
        path = tmp_path / "source.py"
        alternate = tmp_path / "alternate.py"
        alternate.write_text(path.read_text())
        path.unlink()
        path.symlink_to(alternate)
    if mutation != "missing-gate":
        write_json(tmp_path / report.GATE, gate)
    monkeypatch.setattr(report, "load_lanes", lambda *a: pytest.fail("native loader before gate"))
    monkeypatch.setattr(
        report.fit, "case_artifacts", lambda *a, **k: pytest.fail("NetCDF before gate")
    )
    with pytest.raises(ValueError):
        report.collect_views(tmp_path)


def test_reference_prerequisite_checked_before_case_netCDF(tmp_path, monkeypatch):
    admission_fixture(tmp_path, monkeypatch)

    def missing_reference(*args):
        raise ValueError("missing reference closure")

    monkeypatch.setattr(report.refs, "verify_reference_sources", missing_reference)
    monkeypatch.setattr(report.fit, "case_artifacts", lambda *a, **k: pytest.fail("early NetCDF"))
    with pytest.raises(ValueError, match="reference closure"):
        report.collect_views(tmp_path)


def test_report_gate_failure_allocates_no_output(tmp_path):
    output = tmp_path / "new-report"
    with pytest.raises(ValueError):
        report.report(tmp_path, output)
    assert not output.exists()


def test_end_drift_never_seals_output_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("original")
    pins = {"source.py": sha256(source)}
    monkeypatch.setattr(
        report, "collect_views", lambda root: (views(), [], pins, {"calls_charged": 55})
    )

    def drift(*args):
        source.write_text("changed after plots")

    monkeypatch.setattr(report, "figures", drift)
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="SHA changed"):
        report.report(tmp_path, output)
    assert (output / "findings.md").is_file()
    assert not (output / "output-checksums.json").exists()


def test_synthetic_figures_render_only_two_png_svg_families(tmp_path):
    tables = report.sensitivity_tables(views())
    report.figures(tables, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {
        "prior-population-median-curves.png",
        "prior-population-median-curves.svg",
        "ncei-data-stress-log-changes.png",
        "ncei-data-stress-log-changes.svg",
    }
    assert all(p.stat().st_size > 5000 for p in tmp_path.iterdir())


def test_overflowing_ratio_keeps_finite_log_shift_without_clipping():
    data = views()
    for view in data:
        if view["target"] == "T-CAL":
            continue
        for row in view["summary"]["curves"]:
            center = -690 if view["role"] == "base" else 690
            for key, delta in [("q05", -0.1), ("q50", 0), ("q95", 0.1)]:
                row["log_" + key] = center + delta
                row[key] = math.exp(center + delta)
    tables = report.sensitivity_tables(data)
    row = next(
        r for r in tables[report.TABLES[2]] if r["target"] == "T-OBS" and r["role"] == "sensitivity"
    )
    assert row["median_log_shift"] == 1380
    assert row["native_median_ratio"] is None
    assert row["native_ratio_representable"] is False


def test_count_reconciliation_rejects_bad_event_bookkeeping():
    data = views()
    data[1]["summary"]["support"]["event_counts"] = {"event": 99}
    with pytest.raises(ValueError, match="count reconciliation"):
        report.sensitivity_tables(data)


def test_collection_reuses_new_summaries_and_freezes_reference_seed_order(tmp_path, monkeypatch):
    all_views = views()
    new = [v for v in all_views if v["role"] == "sensitivity"]
    jobs, accepted, pins = [], [], {}
    for order, view in enumerate(new):
        job = {
            **{k: v for k, v in view.items() if k not in {"summary", "provenance"}},
            "id": f"case-{order}",
            "seed": 2886110800 + 1000 * order,
        }
        jobs.append(job)
        folder = tmp_path / report.fit.OUTPUT / "jobs" / job["id"]
        write_json(folder / "summary.json", view["summary"])
        write_json(folder / "inputs.json", {"base_prior": {"alpha_sd": 1}, "wider_prior": None})
        receipt = folder / "attempt-evidence.json"
        write_json(receipt, {"case_id": job["id"]})
        files = {str(p.relative_to(tmp_path)): sha256(p) for p in folder.iterdir()}
        pins.update(files)
        accepted.append(
            {
                "receipt": str(receipt.relative_to(tmp_path)),
                "receipt_sha256": sha256(receipt),
                "files": files,
            }
        )
    admission = {"files": {"original-pins": "bound"}, "contract": {"source": "same"}}
    checked = {
        "files": pins,
        "jobs": jobs,
        "accepted": accepted,
        "admission": admission,
        "run_summary": {"calls_charged": 55},
    }
    monkeypatch.setattr(report, "verify_report_sources", lambda root: checked)
    replayed = []

    def replay(root, job, original_pins, accepted=None):
        assert original_pins == admission["files"]
        replayed.append(job["id"])
        assert accepted is not None
        return accepted["files"], root / accepted["receipt"]

    monkeypatch.setattr(report.fit, "case_artifacts", replay)
    from analysis.arrival.model_data import lane_arrays

    lanes = {}
    for target in {t for t, k in FORMS}:
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
    monkeypatch.setattr(report, "load_lanes", lambda root: (lanes, admission["contract"]))
    registry = report.refs.descriptors()
    loaded, simulated = [], []

    def historical(root, key, actual_lanes, actual_pins):
        assert actual_lanes is lanes and actual_pins is pins
        ref = next(d for d in registry if d["key"] == key)
        loaded.append(key)
        return lanes[ref["target"]], ref["kind"], np.arange(3), object(), {"key": key}

    monkeypatch.setattr(report.refs, "load_reference", historical)

    def simulate(lane, kind, posterior, *, indices, seed, draws):
        simulated.append((seed, draws))
        return summary(lane.target, kind)

    monkeypatch.setattr(report, "summarize_posterior", simulate)
    monkeypatch.setattr(report, "_priors", lambda *a, **k: {"variant": "synthetic"})
    result, provenance, source_pins, run = report.collect_views(tmp_path)
    assert len(result) == 69 and len(provenance) == 14 and len(replayed) == 55
    assert loaded == [d["key"] for d in registry]
    assert simulated == [(2916110800 + 1000 * i, 800) for i in range(14)]
    assert [v["summary"] for v in result[:55]] == [v["summary"] for v in new]
    assert source_pins is pins and run["calls_charged"] == 55


def test_synthetic_report_manifest_is_reproducible_and_does_not_overwrite(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("fixed synthetic source")
    pins = {"source.py": sha256(source)}
    monkeypatch.setattr(
        report, "collect_views", lambda root: (views(), [], pins, {"calls_charged": 55})
    )
    monkeypatch.setattr(report, "figures", lambda *a: None)  # Rendering has a separate smoke test.
    output = tmp_path / "synthetic-report"
    report.report(tmp_path, output)
    manifest = json.loads((output / "output-checksums.json").read_text())
    assert all(sha256(output / name) == digest for name, digest in manifest.items())
    assert set(manifest) == {
        *(name + ".csv" for name in report.TABLES),
        "inputs.json",
        "summary.json",
        "reference-provenance.json",
        "findings.md",
    }
    assert json.loads((output / "summary.json").read_text())["views"] == 69
    snapshot = (output / "output-checksums.json").read_bytes()
    with pytest.raises(ValueError, match="new nonsymlink"):
        report.report(tmp_path, output)
    assert (output / "output-checksums.json").read_bytes() == snapshot


def test_prior_descriptions_follow_actual_form_and_scale_not_student_sd(tmp_path):
    base = {"alpha_sd": 1.0, "beta_sd": 2.0, "sigma_sd": 0.4, "tau_sd": 0.2}
    for target, kind in FORMS:
        prior = {**base, **({"gamma_sd": 0.5} if kind == "mean-curvature" else {})}
        result = report._priors(tmp_path, target, kind, "t4_matched", {"base_prior": prior})
        actual = result["population_priors"]
        assert set(actual) == (
            {"alpha", "sigma"}
            if kind == "pooled"
            else {"alpha", "beta", "sigma"}
            if kind == "distance"
            else {"alpha", "beta", "tau_event", "sigma"}
            if kind == "event"
            else {"alpha", "beta", "tau_event", "sigma_anchor"}
            if kind == "distance-scale"
            else {"alpha", "beta", "gamma", "tau_event", "sigma_anchor"}
        )
        assert actual["alpha"]["scale"] == pytest.approx(0.7059257108562306)
        assert actual["alpha"]["distribution"] == "StudentT4"
        assert actual["alpha"]["scale_is_sd"] is False
        scale = actual.get("sigma", actual.get("sigma_anchor"))
        assert scale["distribution"] == "HalfStudentT4"
    power = report._priors(tmp_path, "T-OBS", "pooled", "power_0.5", {"base_prior": base})
    assert power["population_priors"]["alpha"]["scale"] == pytest.approx(math.sqrt(2))
