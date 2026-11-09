"""Prospective temporary jobs and patched sampling only; no historical data reads."""

# pyright: basic
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_fit as worker
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_development_data import accept_check
from tests.test_arrival_model_development_references import damage_native_metadata, native_metadata
from tests.test_arrival_model_development_references import fixture as reference_fixture


def fixture(
    root,
    monkeypatch,
    *,
    target="NCEI-native-duration",
    kind="mean-curvature",
    variant="base",
    role="check_training",
    new_reference=False,
) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
    key, training, pins = reference_fixture(root, monkeypatch, target, kind)
    freeze = json.loads((root / data.FREEZE).read_text())
    spec = freeze["models"][target][0]
    spec["prior_variant"] = variant
    if variant == "gamma_wider_only":
        reader = data.read_curvature_prior
        monkeypatch.setattr(
            data,
            "read_curvature_prior",
            lambda root, v: {**reader(root, v), "gamma_sd": 0.5 if v == "base" else 0.8},
        )
    if variant in {"joint_wider", "gamma_wider_only"}:
        wider = (
            data.read_curvature_prior(root, variant)
            if kind == "mean-curvature"
            else data.read_prior(root, target, "wider")
        )
        spec["wider_prior_sd"] = {name: wider[name] for name in spec["base_prior_sd"]}
    decision = json.loads((root / freeze["ms5_decision"]).read_text())
    decision["models"] = freeze["models"]
    write_json(root / freeze["ms5_decision"], decision)
    freeze["files"][freeze["ms5_decision"]] = sha256(root / freeze["ms5_decision"])
    write_json(root / data.FREEZE, freeze)
    for name in worker.CONSUMED:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic development worker source")
    files = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    if role == "full_development":
        files = accept_check(root, files)
    job: dict[str, Any] = dict(
        id="dev-pilot-power-0.5",
        order=0,
        role=role,
        model_key=key,
        seed=2946110800,
        training_reference={"kind": "historical"} if role == "check_evaluate" else None,
    )
    jobs = [job]
    if new_reference:
        job = {**job, "role": "check_training", "training_reference": None}
        evaluation = dict(
            id="dev-evaluate",
            order=1,
            role="check_evaluate",
            model_key=key,
            seed=2946111800,
            training_reference={
                "kind": "new_fit",
                "job_id": job["id"],
                "review": str(
                    (worker.case_paths(root, job)[0] / "review-acceptance.json").relative_to(root)
                ),
            },
        )
        jobs = [job, evaluation]
    name = worker.FULL_GATE if role == "full_development" else worker.GATE
    gate = dict(
        status="accepted_frozen_arrival_development_execution",
        independent_checker=True,
        specification_freeze=data.FREEZE,
        specification_freeze_sha256=files[data.FREEZE],
        reserved_outcomes="sealed",
        no_retuning_after_development_check=True,
        crossing_policy="uniform_purge_all_check_sequences",
        resources=worker.resources(),
        max_sampler_call_slots=max(1, sum(j["role"] != "check_evaluate" for j in jobs)),
        jobs=jobs,
        files=files,
    )
    write_json(root / name, gate)
    calls = []
    builder = worker.build_sensitivity_model

    def build(lane, actual_kind, base, actual_variant, *, wider_prior, indices):
        model = builder(
            lane, actual_kind, base, actual_variant, wider_prior=wider_prior, indices=indices
        )
        assert list(model.coords["record"] or []) == [lane.record_ids[int(i)] for i in indices]
        assert {v.name for v in model.free_RVs} == set(
            data._population_spec(lane.target, actual_kind)
        )
        if role != "full_development":
            assert not set(np.asarray(lane.sequences)[indices]) & {data.CROSS_SEQUENCE}
        if actual_variant != "base":
            assert "sensitivity_population_prior_replacement" in model.named_vars
        current.update(lane=lane, kind=actual_kind)
        return model

    current = {}
    monkeypatch.setattr(worker, "build_sensitivity_model", build)

    def sample(**kwargs):
        assert kwargs == dict(
            draws=2000,
            tune=1000,
            chains=4,
            cores=2,
            target_accept=0.95,
            nuts_sampler="nutpie",
            random_seed=job["seed"],
            progressbar=False,
        )
        output, raw = worker.case_paths(root, job)
        assert raw is not None
        assert json.loads((output / "sampling-start.json").read_text()) == job
        assert raw.exists() and raw.stat().st_size == 0
        variables = {}
        for parameter, (_, shape) in data._population_spec(target, kind).items():
            variables[parameter] = (
                (("chain", "draw", "scale_anchor_km"), np.full((4, 2000, 3), 0.4))
                if shape
                else (("chain", "draw"), np.full((4, 2000), 0.4 if parameter == "sigma" else 0.1))
            )
        post = xr.Dataset(
            variables,
            coords={"chain": np.arange(4), "draw": np.arange(2000)},
            attrs={"inference_library": "nutpie"},
        )
        if target == "NCEI-native-duration":
            post = post.assign_coords(scale_anchor_km=[500, 2000, 5000])
        calls.append(kwargs)
        stats = native_metadata(post)
        return xr.DataTree.from_dict({"posterior": post, "sample_stats": stats})

    monkeypatch.setattr(worker.pm, "sample", sample)
    monkeypatch.setattr(
        worker,
        "sampling_diagnostics",
        lambda tree: ({"screen_passed": True}, pd.DataFrame({"r_hat": [1.0]})),
    )
    return jobs, calls, current


@pytest.mark.parametrize(
    "target,kind",
    [
        ("NCEI-native-duration", "distance-scale"),
        ("NCEI-native-duration", "mean-curvature"),
        *[(t, k) for t in ["T-OBS", "T-CAL"] for k in ["pooled", "distance", "event"]],
    ],
)
def test_all_eight_forms_have_exact_purged_explicit_population_graph(
    tmp_path, monkeypatch, target, kind
):
    jobs, calls, current = fixture(tmp_path, monkeypatch, target=target, kind=kind)
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    assert raw is not None
    result = worker.run_development_job(tmp_path, job, output, raw)
    assert result["status"] == worker.SUCCESS and result["confirmation_outcomes_parsed"] is True
    assert len(calls) == 1
    expected = 1040 if target == "NCEI-native-duration" else 236 if target == "T-OBS" else 156
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as ds:
        assert ds.sizes["record"] == expected
        np.testing.assert_array_equal(
            ds.native_minutes, current["lane"].y[current["lane"].included]
        )
    inventory = worker.case_artifacts(
        tmp_path, job, worker.verify_gate(tmp_path, job["role"])["files"]
    )
    assert inventory["posterior_sha256"] == sha256(raw)


@pytest.mark.parametrize(
    "variant", ["power_0.5", "power_1.5", "t4_matched", "joint_wider", "gamma_wider_only"]
)
def test_frozen_prior_variants_use_existing_builder(tmp_path, monkeypatch, variant):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, variant=variant)
    output, raw = worker.case_paths(tmp_path, jobs[0])
    assert raw is not None
    result = worker.run_development_job(tmp_path, jobs[0], output, raw)
    assert result["status"] == worker.SUCCESS and len(calls) == 1
    settings = json.loads((output / "prior-settings.json").read_text())
    assert settings["family"] == ("t4" if variant == "t4_matched" else "normal")
    if variant == "power_0.5":
        assert settings["distribution_scales"]["alpha_sd"] == 0.5 / np.sqrt(0.5)


@pytest.mark.parametrize("fault", ["backend_note", "original_settings"])
def test_wrong_native_backend_or_protocol_retains_raw_without_certifying_fit(
    tmp_path, monkeypatch, fault
):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    sample = worker.pm.sample

    def wrong_sample(**kwargs):
        tree = sample(**kwargs)
        if fault == "backend_note":
            tree["posterior"].attrs.update(
                inference_library="pymc", note="This unrelated note mentions nutpie"
            )
        else:
            tree["posterior"].attrs["tuning_steps"] = 0
            tree["sample_stats"] = xr.DataTree(
                xr.Dataset(
                    attrs={
                        "inference_library": "nutpie",
                        "inference_library_version": "0.16.11",
                        "inference_library_settings": json.dumps(
                            dict(
                                sampler="nuts",
                                settings=dict(
                                    num_tune=0,
                                    num_draws=2000,
                                    num_chains=4,
                                    adapt_options=dict(step_size_settings=dict(target_accept=0.5)),
                                ),
                            )
                        ),
                    }
                )
            )
        return tree

    monkeypatch.setattr(worker.pm, "sample", wrong_sample)
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    result = worker.run_development_job(tmp_path, job, output, raw)
    assert len(calls) == 1 and raw is not None and raw.stat().st_size > 0
    assert result["status"] == "needs_numerical_review"
    assert result["posterior_sha256"] == sha256(raw)
    assert not (output / "diagnostics.json").exists()
    assert not (output / "summary.json").exists()


@pytest.mark.parametrize("fault", ["backend_note", "settings"])
def test_resealed_raw_metadata_cannot_pass_full_artifact_replay(tmp_path, monkeypatch, fault):
    jobs, _, _ = fixture(tmp_path, monkeypatch)
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    assert raw is not None
    assert worker.run_development_job(tmp_path, job, output, raw)["status"] == worker.SUCCESS
    with xr.open_datatree(raw, engine="h5netcdf") as saved:
        tree = saved.load()
    post, stats = tree["posterior"].to_dataset(), tree["sample_stats"].to_dataset()
    damage_native_metadata(post, stats, fault)
    tree["posterior"], tree["sample_stats"] = xr.DataTree(post), xr.DataTree(stats)
    tree.to_netcdf(raw, engine="h5netcdf")
    tree.close()
    result = json.loads((output / "result.json").read_text())
    result["posterior_sha256"] = sha256(raw)
    write_json(output / "result.json", result)
    worker._manifest(output)
    with pytest.raises(ValueError, match="native nutpie"):
        worker.case_artifacts(tmp_path, job, worker.verify_gate(tmp_path, job["role"])["files"])


@pytest.mark.parametrize("failure", ["status", "resources", "not_listed", "augmentation"])
def test_prospective_gate_failures_precede_loading(tmp_path, monkeypatch, failure):
    jobs, _, _ = fixture(tmp_path, monkeypatch)
    job = jobs[0]
    gate = json.loads((tmp_path / worker.GATE).read_text())
    if failure == "status":
        gate["status"] = "pending"
    elif failure == "resources":
        gate["resources"]["global_max_bytes"] = 2048 * 1024**2
    elif failure == "not_listed":
        job = {**job, "id": "dev-other"}
    else:
        job = {**job, "role": "check_augmented"}
    write_json(tmp_path / worker.GATE, gate)
    monkeypatch.setattr(
        data, "load_check_lanes", lambda *args: pytest.fail("check parsed before gate")
    )
    if failure == "augmentation":
        with pytest.raises(ValueError, match="augmentation"):
            worker.run_development_job(tmp_path, job, tmp_path / "unused")
    else:
        output, raw = worker.case_paths(tmp_path, job)
        with pytest.raises(ValueError):
            worker.run_development_job(tmp_path, job, output, raw)
        assert not output.exists()


def test_raw_is_retained_before_downstream_diagnostic_failure(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker,
        "sampling_diagnostics",
        lambda tree: (_ for _ in ()).throw(ValueError("after raw save")),
    )
    output, raw = worker.case_paths(tmp_path, jobs[0])
    result = worker.run_development_job(tmp_path, jobs[0], output, raw)
    assert result["status"] == "needs_numerical_review" and len(calls) == 1
    assert raw is not None
    assert raw.stat().st_size > 0 and result["posterior_sha256"] == sha256(raw)
    assert (output / "result.json").exists() and (output / "sampling-start.json").exists()
    with pytest.raises(ValueError, match="preserve every attempt"):
        worker.run_development_job(tmp_path, jobs[0], output, raw)


def test_full_mode_requires_completed_check_and_preserves_800_summary_budget(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, role="full_development")
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    gate = json.loads((tmp_path / worker.FULL_GATE).read_text())
    saved = gate["files"].pop(data.CHECK_REVIEW)
    write_json(tmp_path / worker.FULL_GATE, gate)
    with pytest.raises(ValueError):
        worker.run_development_job(tmp_path, job, output, raw)
    assert calls == [] and not output.exists()
    gate["files"][data.CHECK_REVIEW] = saved
    write_json(tmp_path / worker.FULL_GATE, gate)

    def summary(lane, kind, post, *, indices, seed, draws):
        assert draws == 800 and len(indices) == 1215
        return {
            name: [{"synthetic": 1}]
            for name in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]
        }

    monkeypatch.setattr(worker, "summarize_posterior", summary)
    monkeypatch.setattr(worker, "_summary_valid", lambda value: True)
    result = worker.run_development_job(tmp_path, job, output, raw)
    assert result["status"] == worker.SUCCESS and len(calls) == 1


def test_direct_failure_keeps_all_events_arrays_predictions_and_zero_calls(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, role="check_evaluate")

    def predictions(lane, ids, kind, post, *, training_distance_range_km):
        return [
            {"record_id": lane.record_ids[int(i)], "event_id": lane.event_ids[int(i)]} for i in ids
        ], {"status": "computed_pending_review"}

    monkeypatch.setattr(worker, "new_event_predictions", predictions)
    output, raw = worker.case_paths(tmp_path, jobs[0])
    result = worker.run_development_job(tmp_path, jobs[0], output, raw)
    assert calls == [] and raw is None and result["status"] == "needs_numerical_review"
    saved = json.loads((output / "event-results.json").read_text())
    assert len(saved["events"]) == len(saved["expected_event_ids"]) == 14
    assert result["prediction_rows"] == 151
    with np.load(output / "direct-score-arrays.npz") as arrays:
        assert len([name for name in arrays.files if name.endswith("native_loglikelihood")]) == 14


def test_new_training_reference_needs_independent_parent_review(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(
        tmp_path, monkeypatch, target="T-CAL", kind="event", new_reference=True
    )
    parent, evaluation = jobs
    output, raw = worker.case_paths(tmp_path, parent)
    assert raw is not None
    assert worker.run_development_job(tmp_path, parent, output, raw)["status"] == worker.SUCCESS
    admitted = worker.verify_gate(tmp_path, parent["role"])
    views = data.load_check_lanes(tmp_path, admitted["files"])
    with pytest.raises(ValueError):
        worker._training_reference(
            tmp_path, evaluation, views["training_purged"]["T-CAL"], admitted
        )
    inventory = worker.case_artifacts(tmp_path, parent, admitted["files"])
    review = dict(
        status="accepted_frozen_development_training_posterior",
        independent_checker=True,
        specification_freeze_sha256=admitted["files"][data.FREEZE],
        model_key=parent["model_key"],
        job_id=parent["id"],
        files={**admitted["files"], **inventory["files"]},
    )
    write_json(output / "review-acceptance.json", review)
    post, proof, _ = worker._training_reference(
        tmp_path, evaluation, views["training_purged"]["T-CAL"], admitted
    )
    assert post.sizes["draw"] == 2000 and proof["raw_sha256"] == sha256(raw)
    assert len(calls) == 1
    output, no_raw = worker.case_paths(tmp_path, evaluation)
    result = worker.run_development_job(tmp_path, evaluation, output, no_raw)
    assert result["status"] == worker.SUCCESS and len(calls) == 1
    inventory = worker.case_artifacts(tmp_path, evaluation, admitted["files"])
    assert inventory["posterior"] is None


def test_effective_prior_mismatch_blocks_sampling(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, variant="gamma_wider_only")
    original = worker._prior_settings

    def mismatched(*args):
        family, scales = original(*args)
        return family, {**scales, "gamma_sd": 99}

    monkeypatch.setattr(worker, "_prior_settings", mismatched)
    output, raw = worker.case_paths(tmp_path, jobs[0])
    result = worker.run_development_job(tmp_path, jobs[0], output, raw)
    assert result["status"] == "worker_failure" and calls == []
    assert "effective prior" in result["error"]


@pytest.mark.parametrize("corruption", ["prior_settings", "diagnostic_csv", "inputs_closure"])
def test_resealed_fit_semantic_corruptions_are_rejected(tmp_path, monkeypatch, corruption):
    jobs, calls, _ = fixture(tmp_path, monkeypatch)
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    assert worker.run_development_job(tmp_path, job, output, raw)["status"] == worker.SUCCESS
    admission = worker.verify_gate(tmp_path, job["role"])
    if corruption == "prior_settings":
        value = json.loads((output / "prior-settings.json").read_text())
        value["family"] = "not-the-sampled-family"
        value["distribution_scales"]["gamma_sd"] = 999
        write_json(output / "prior-settings.json", value)
    elif corruption == "diagnostic_csv":
        (output / "sampling-diagnostics.csv").write_text("r_hat\n99\n")
    else:
        value = json.loads((output / "inputs.json").read_text())
        value["files"] = dict(list(value["files"].items())[:1])
        write_json(output / "inputs.json", value)
        monkeypatch.setattr(
            worker.xr,
            "open_dataset",
            lambda *a, **k: pytest.fail("truncated source proof opened NC"),
        )
    worker._manifest(output)
    with pytest.raises(ValueError):
        worker.case_artifacts(tmp_path, job, admission["files"])
    assert len(calls) == 1


@pytest.mark.parametrize(
    "corruption",
    ["summary", "parameters", "derived", "curves", "conditional_ppc", "record_intervals"],
)
def test_full_seeded_summary_and_every_csv_replay_from_raw(tmp_path, monkeypatch, corruption):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, role="full_development")
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)

    def summary(lane, kind, post, *, indices, seed, draws):
        assert seed == job["seed"] + 1 and draws == 800 and len(indices) == 1215
        value = float(post.alpha.values[0, 0])
        return {
            name: [{"parameter": "alpha", "q05": value, "q50": value, "q95": value}]
            for name in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]
        }

    monkeypatch.setattr(worker, "summarize_posterior", summary)
    monkeypatch.setattr(worker, "_summary_valid", lambda value: True)
    assert worker.run_development_job(tmp_path, job, output, raw)["status"] == worker.SUCCESS
    admission = worker.verify_gate(tmp_path, job["role"])
    worker.case_artifacts(tmp_path, job, admission["files"])
    if corruption == "summary":
        value = json.loads((output / "summary.json").read_text())
        value["parameters"][0].update(q05=99, q50=99, q95=99)
        write_json(output / "summary.json", value)
    else:
        path = output / (corruption.replace("_", "-") + ".csv")
        path.write_text(path.read_text().replace("0.1", "99"))
    worker._manifest(output)
    with pytest.raises(ValueError, match="summary.*replay|CSV differs"):
        worker.case_artifacts(tmp_path, job, admission["files"])
    assert len(calls) == 1


@pytest.mark.parametrize("corruption", ["source_closure", "mandatory_inventory"])
def test_new_training_review_must_close_complete_parent_before_nc(
    tmp_path, monkeypatch, corruption
):
    jobs, calls, _ = fixture(
        tmp_path, monkeypatch, target="T-CAL", kind="event", new_reference=True
    )
    parent, evaluation = jobs
    output, raw = worker.case_paths(tmp_path, parent)
    assert raw is not None
    assert worker.run_development_job(tmp_path, parent, output, raw)["status"] == worker.SUCCESS
    admission = worker.verify_gate(tmp_path, parent["role"])
    views = data.load_check_lanes(tmp_path, admission["files"])
    minimal = ["job.json", "inputs.json", "membership.json", "result.json"]
    write_json(output / "output-checksums.json", {name: sha256(output / name) for name in minimal})
    partial = {
        str((output / name).relative_to(tmp_path)): sha256(output / name)
        for name in minimal + ["output-checksums.json"]
    }
    partial[str(raw.relative_to(tmp_path))] = sha256(raw)
    proof = partial if corruption == "source_closure" else {**admission["files"], **partial}
    write_json(
        output / "review-acceptance.json",
        dict(
            status="accepted_frozen_development_training_posterior",
            independent_checker=True,
            specification_freeze_sha256=admission["files"][data.FREEZE],
            model_key=parent["model_key"],
            job_id=parent["id"],
            files=proof,
        ),
    )
    monkeypatch.setattr(
        worker.xr, "open_dataset", lambda *a, **k: pytest.fail("incomplete parent proof opened NC")
    )
    monkeypatch.setattr(
        worker.xr, "open_datatree", lambda *a, **k: pytest.fail("incomplete parent proof opened NC")
    )
    with pytest.raises(ValueError):
        worker._training_reference(
            tmp_path, evaluation, views["training_purged"]["T-CAL"], admission
        )
    assert len(calls) == 1


def test_real_positive_full_summary_mixed_ppc_csv_replays(tmp_path, monkeypatch):
    jobs, calls, _ = fixture(tmp_path, monkeypatch, role="full_development")
    job = jobs[0]
    output, raw = worker.case_paths(tmp_path, job)
    result = worker.run_development_job(tmp_path, job, output, raw)
    assert result["status"] == worker.SUCCESS and len(calls) == 1
    summary = json.loads((output / "summary.json").read_text())
    ppc = summary["conditional_ppc"]
    assert {row["scale"] for row in ppc} >= {"modeled-response", "native-minutes"}
    assert len({tuple(sorted(row)) for row in ppc}) > 1
    admission = worker.verify_gate(tmp_path, job["role"])
    inventory = worker.case_artifacts(tmp_path, job, admission["files"])
    assert inventory["posterior_sha256"] == result["posterior_sha256"]


def crossing_evaluation_fixture(
    monkeypatch,
    events,
    *,
    failed_event=None,
    precision_failed=False,
    supplement_precision_failure=False,
):
    from analysis.arrival import model_development_scoring as scoring
    from analysis.arrival.model_data import lane_arrays
    from tests.test_arrival_model_development_scoring import labelled

    rows = [
        dict(
            record_id=f"r-{i}",
            event_id=event,
            physical_site_id=f"site-{i}",
            target="T-CAL",
            target_minutes=str(i - 1),
            distance_km=str(100 + 20 * i),
        )
        for i, event in enumerate(events)
    ]
    held = lane_arrays("T-CAL", rows, {e: f"seq-{e}" for e in events}, set(events))
    values = np.random.default_rng(772).normal(
        -20, 0.3 if supplement_precision_failure else 0.05, (4, 2000)
    )
    if supplement_precision_failure:
        # Equal empirical chain normalizers isolate the supplementary precision rule.
        rng = np.random.default_rng(994)
        values = np.stack([rng.permutation(values[0]) for _ in range(4)])
    likelihoods = {
        event: labelled(
            (-values - 40)
            if event == data.CROSS_CHECK and supplement_precision_failure
            else values + (5 if event == data.CROSS_CHECK else -3 if event == "kept-b" else 0),
            event=event,
            target="T-CAL",
        )
        for event in events
    }
    scores = {e: scoring.direct_event_score(value, 1) for e, value in likelihoods.items()}

    def likelihood(lane, ids, kind, post):
        event = lane.event_ids[int(ids[0])]
        if event == failed_event and not precision_failed:
            raise ValueError("synthetic failed event likelihood")
        return likelihoods[event], {}

    direct = worker.direct_event_score

    def score(logl, records):
        result = direct(logl, records)
        if logl.attrs["event_id"] == failed_event and precision_failed:
            result.update(
                precision_passed=False,
                status="needs_numerical_review",
                numerical_failures=["synthetic_event_precision_failure"],
            )
        return result

    def predictions(lane, ids, kind, post, *, training_distance_range_km):
        return [
            {"record_id": lane.record_ids[int(i)], "event_id": lane.event_ids[int(i)]} for i in ids
        ], {"status": "computed_pending_review"}

    monkeypatch.setattr(worker, "event_loglikelihood", likelihood)
    monkeypatch.setattr(worker, "direct_event_score", score)
    monkeypatch.setattr(worker, "new_event_predictions", predictions)
    post = xr.Dataset(coords={"chain": ["a", "b", "c", "d"], "draw": np.arange(2000)})
    args = (held, held, {"kind": "event"}, post, {"raw_sha256": "f" * 64})
    return args, scores


def test_crossing_diagnostic_keeps_shared_covariance_and_primary_outputs(tmp_path, monkeypatch):
    import math

    from analysis.arrival.model_development_scoring import aggregate_shared_training_events

    args, scores = crossing_evaluation_fixture(monkeypatch, ["kept-a", data.CROSS_CHECK, "kept-b"])
    expected_all = aggregate_shared_training_events([scores[e] for e in sorted(scores)], "f" * 64)
    expected_kept = aggregate_shared_training_events(
        [scores[e] for e in ["kept-a", "kept-b"]], "f" * 64
    )
    all_influence = expected_all.pop("shared_influence").values
    kept_influence = expected_kept.pop("shared_influence").values
    result = worker._evaluate(tmp_path, tmp_path, *args)
    saved = json.loads((tmp_path / "event-results.json").read_text())
    assert result["status"] == worker.SUCCESS and saved["aggregate"] == expected_all
    diagnostic = saved["aggregate_without_crossing_event"]
    assert diagnostic["kept_event_ids"] == ["kept-a", "kept-b"]
    assert diagnostic["excluded_event_ids"] == [data.CROSS_CHECK]
    assert {k: diagnostic[k] for k in expected_kept} == expected_kept
    assert (
        diagnostic["mcse_equal_event_score"]
        > math.hypot(*(scores[e]["normalized_mcse"] for e in ["kept-a", "kept-b"])) / 2 * 1.3
    )
    assert diagnostic["equal_event_score"] != saved["aggregate"]["equal_event_score"]
    with np.load(tmp_path / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        np.testing.assert_array_equal(arrays["aggregate_shared_influence"], all_influence)
        np.testing.assert_array_equal(
            arrays["aggregate_without_crossing_shared_influence"], kept_influence
        )
        for order, event in enumerate(sorted(scores)):
            np.testing.assert_array_equal(
                arrays[f"event_{order:03d}_joint_influence"],
                scores[event]["joint_influence"].values,
            )
    assert result == worker._evaluate(tmp_path, tmp_path, *args, verify=True)
    assert result["prediction_rows"] == 3
    assert result["aggregate_without_crossing_event"] == diagnostic


@pytest.mark.parametrize("events", [["kept-a", "kept-b"], [data.CROSS_CHECK]])
def test_crossing_absent_or_no_kept_event_is_explicit(tmp_path, monkeypatch, events):
    args, _ = crossing_evaluation_fixture(monkeypatch, events)
    result = worker._evaluate(tmp_path, tmp_path, *args)
    diagnostic = result["aggregate_without_crossing_event"]
    assert result["status"] == worker.SUCCESS
    with np.load(tmp_path / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        if data.CROSS_CHECK not in events:
            assert diagnostic["excluded_event_ids"] == []
            assert diagnostic["kept_event_ids"] == sorted(events)
            assert {k: diagnostic[k] for k in result["aggregate"]} == result["aggregate"]
            np.testing.assert_array_equal(
                arrays["aggregate_shared_influence"],
                arrays["aggregate_without_crossing_shared_influence"],
            )
        else:
            assert diagnostic["status"] == "not_applicable" and diagnostic["events"] == 0
            assert diagnostic["kept_event_ids"] == [] and diagnostic["excluded_event_ids"] == [
                data.CROSS_CHECK
            ]
            assert (
                "mcse_equal_event_score" not in diagnostic and "equal_event_score" not in diagnostic
            )
            assert "aggregate_without_crossing_shared_influence" not in arrays.files


@pytest.mark.parametrize("precision_failed", [False, True])
def test_failed_kept_score_never_shifts_event_identity_or_hides_failure(
    tmp_path, monkeypatch, precision_failed
):
    args, _ = crossing_evaluation_fixture(
        monkeypatch,
        ["kept-a", "kept-b", data.CROSS_CHECK],
        failed_event="kept-a",
        precision_failed=precision_failed,
    )
    result = worker._evaluate(tmp_path, tmp_path, *args)
    diagnostic = result["aggregate_without_crossing_event"]
    assert result["status"] == "needs_numerical_review"
    assert diagnostic["status"] == "needs_numerical_review" and diagnostic["events"] == 2
    assert diagnostic["kept_event_ids"] == ["kept-a", "kept-b"]
    assert diagnostic["failed_event_ids"] == ["kept-a"]
    with np.load(tmp_path / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        assert "aggregate_without_crossing_shared_influence" not in arrays.files
    assert result == worker._evaluate(tmp_path, tmp_path, *args, verify=True)


def test_failed_crossing_score_does_not_block_supplement_or_rescue_primary(tmp_path, monkeypatch):
    args, _ = crossing_evaluation_fixture(
        monkeypatch, ["kept-a", "kept-b", data.CROSS_CHECK], failed_event=data.CROSS_CHECK
    )
    result = worker._evaluate(tmp_path, tmp_path, *args)
    assert result["status"] == "needs_numerical_review"
    assert result["aggregate_without_crossing_event"]["status"] == "computed_pending_review"
    assert result["aggregate_without_crossing_event"]["failed_event_ids"] == []
    with np.load(tmp_path / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        assert "aggregate_without_crossing_shared_influence" in arrays.files


@pytest.mark.parametrize("corruption", ["metadata", "influence"])
def test_crossing_supplement_metadata_and_influence_replay_exactly(
    tmp_path, monkeypatch, corruption
):
    args, _ = crossing_evaluation_fixture(monkeypatch, ["kept-a", "kept-b", data.CROSS_CHECK])
    worker._evaluate(tmp_path, tmp_path, *args)
    if corruption == "metadata":
        path = tmp_path / "event-results.json"
        result = json.loads(path.read_text())
        result["aggregate_without_crossing_event"]["kept_event_ids"] = [data.CROSS_CHECK]
        write_json(path, result)
    else:
        path = tmp_path / "direct-score-arrays.npz"
        with np.load(path, allow_pickle=False) as old:
            arrays = {key: old[key].copy() for key in old.files}
        arrays["aggregate_without_crossing_shared_influence"][0, 0] += 1
        np.savez_compressed(path, **arrays)
    with pytest.raises(ValueError, match="replay|arrays"):
        worker._evaluate(tmp_path, tmp_path, *args, verify=True)


def test_supplement_precision_failure_does_not_change_primary_pass_rule(tmp_path, monkeypatch):
    args, _ = crossing_evaluation_fixture(
        monkeypatch, ["kept-a", "kept-b", data.CROSS_CHECK], supplement_precision_failure=True
    )
    result = worker._evaluate(tmp_path, tmp_path, *args)
    assert result["status"] == worker.SUCCESS
    diagnostic = result["aggregate_without_crossing_event"]
    assert diagnostic["status"] == "needs_numerical_review"
    assert "aggregate_mcse" in diagnostic["numerical_failures"]
    assert diagnostic["failed_event_ids"] == []
    with np.load(tmp_path / "direct-score-arrays.npz", allow_pickle=False) as arrays:
        assert "aggregate_shared_influence" in arrays.files
        assert "aggregate_without_crossing_shared_influence" not in arrays.files
