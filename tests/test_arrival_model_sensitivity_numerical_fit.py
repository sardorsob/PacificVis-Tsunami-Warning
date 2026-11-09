"""Synthetic versioned numerical protocols; no original outcomes or sampling."""

# pyright: basic
from copy import deepcopy
from typing import Any, cast

import pytest

from analysis.arrival import model_sensitivity_numerical_fit as worker


def original_jobs() -> list[dict[str, Any]]:
    return [
        dict(
            id=worker.first_repair.ORIGINAL_ID if i == 34 else f"original-{i:03d}",
            order=i,
            target="NCEI-native-duration",
            kind="distance-scale" if i < 44 else "mean-curvature",
            prior_variant="base",
            seed=2886110800 + i * 1000,
            draws=2000,
            tune=1000,
            cores=2,
            distance_mode="geodesic_km",
            training_record_ids=["r0"],
            omitted_record_ids=[],
            excluded_record_ids=[],
            support={"records": 1, "event_counts": {"e": 1}},
        )
        for i in range(55)
    ]


def next_attempts(jobs):
    return {job["id"]: 2 if job["order"] == 36 else 1 for job in jobs[36:]}


def test_exact19_jobs_keep_original_model_mask_seed_and_literal_new_paths(tmp_path):
    originals = original_jobs()
    jobs = worker.execution_jobs(
        originals[36:], "numerical-protocol-v2", next_attempts(originals), worker.PROTOCOL
    )
    assert len(jobs) == 19
    for order, job in enumerate(jobs, 36):
        assert job == dict(
            id=f"ms5-numerical-protocol-v2-{order:03d}-attempt-{2 if order == 36 else 1}",
            original_job=originals[order],
            attempt=2 if order == 36 else 1,
            sampler={**worker.PROTOCOL, "seed": originals[order]["seed"]},
            order=order,
        )
        folder, raw = worker.case_paths(tmp_path, job)
        assert folder == tmp_path / worker.OUTPUT / "jobs" / job["id"]
        assert raw == tmp_path / worker.STORE / (job["id"] + ".nc")
        assert "arrival-sensitivity-v1/" not in str(raw)


@pytest.mark.parametrize(
    "change",
    ["target", "prior", "kind", "draws", "chains", "cores", "tune", "accept", "attempt", "run-id"],
)
def test_unreviewable_model_or_protocol_changes_are_rejected(change):
    originals = original_jobs()
    attempts = next_attempts(originals)
    protocol = dict(worker.PROTOCOL)
    run_id = "numerical-protocol-v2"
    if change in {"target", "prior", "kind"}:
        originals[36][{"target": "target", "prior": "prior_variant", "kind": "kind"}[change]] = {
            "target": "T-CAL",
            "prior": "t4_matched",
            "kind": "pooled",
        }[change]
    elif change == "attempt":
        attempts[originals[36]["id"]] = 3
    elif change == "run-id":
        run_id = "../../original"
    else:
        protocol["target_accept" if change == "accept" else change] = {
            "draws": 1000,
            "chains": 2,
            "cores": 4,
            "tune": 10001,
            "accept": 1.0,
        }[change]
    with pytest.raises(ValueError):
        worker.execution_jobs(originals[36:], run_id, attempts, protocol)


def test_gate_failure_allocates_no_paths_or_sampler_call(tmp_path, monkeypatch):
    originals = original_jobs()
    job = worker.execution_jobs(
        originals[36:], "numerical-protocol-v2", next_attempts(originals), worker.PROTOCOL
    )[0]
    folder, raw = worker.case_paths(tmp_path, job)
    monkeypatch.setattr(worker.fit.pm, "sample", lambda **kw: pytest.fail("no sampler before Gate"))
    with pytest.raises(ValueError):
        worker.fit_case(tmp_path, job, folder, raw)
    assert not folder.exists() and not raw.exists()


@pytest.mark.parametrize("change", ["id", "seed", "original-model", "extra-key"])
def test_case_paths_never_redirect_or_masquerade_as_original(tmp_path, change):
    originals = original_jobs()
    job = deepcopy(
        worker.execution_jobs(
            originals[36:], "numerical-protocol-v2", next_attempts(originals), worker.PROTOCOL
        )[0]
    )
    if change == "id":
        job["id"] = "original-036"
    elif change == "seed":
        job["sampler"]["seed"] += 1
    elif change == "original-model":
        job["original_job"]["prior_variant"] = "power_0.5"
    else:
        job["output"] = "original-output"
    with pytest.raises(ValueError):
        worker.case_paths(tmp_path, job)


def gate_fixture(
    root, monkeypatch
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    import hashlib
    import json
    from collections import Counter
    from types import SimpleNamespace

    from analysis.arrival.evidence import sha256, write_json

    originals = original_jobs()
    for name in worker.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic reviewed source")
    write_json(root / worker.fit.GATE, {"jobs": originals})
    old_pins = {n: sha256(root / n) for n in [*worker.fit.CONSUMED, worker.fit.GATE]}
    original = dict(gate={"jobs": originals}, files=old_pins, contract={"synthetic": True})
    monkeypatch.setattr(worker.fit, "verify_gate", lambda root: original)
    write_json(
        root / worker.PLAN,
        dict(jobs=originals, files=old_pins, gate_sha256=old_pins[worker.fit.GATE]),
    )
    prefix = []
    for order, job in enumerate(originals[:36]):
        repaired = order == 34
        folder = (
            worker.first_repair.OUTPUT if repaired else worker.fit.OUTPUT + "/jobs/" + job["id"]
        )
        raw = worker.first_repair.STORE if repaired else worker.fit.STORE + "/" + job["id"] + ".nc"
        path = root / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic accepted raw; never parsed in admission")
        files = {raw: sha256(path)}
        receipt = folder + "/attempt-evidence.json"
        write_json(root / receipt, {"case_id": job["id"], "files": files})
        prefix.append(
            dict(
                order=order,
                case_id=job["id"],
                charged_slots=1,
                producer="repair_v1" if repaired else "original",
                source_role="numerical_repair" if repaired else "original",
                original_job=job,
                execution_job=worker.first_repair.repair_job(job) if repaired else job,
                posterior=raw,
                posterior_sha256=files[raw],
                files=files,
                receipt=receipt,
                receipt_sha256=sha256(root / receipt),
            )
        )
    failures = []
    for order in [34, 36]:
        job = originals[order]
        folder = root / worker.fit.OUTPUT / "jobs" / job["id"]
        raw = root / worker.fit.STORE / (job["id"] + ".nc")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"retained failed raw")
        for leaf in worker.LEAVES:
            write_json(folder / leaf, job if leaf in ["job.json", "sampling-start.json"] else {})
        write_json(
            folder / "result.json",
            dict(
                job=job,
                status="diagnostic_failure",
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
            ),
        )
        for suffix in ["-spec.json", ".log", ".supervisor.json"]:
            write_json(folder.with_name(folder.name + suffix), {})
        if order == 36:
            write_json(folder / "completion-failure.json", {"retained": True})
        physical = {
            str(p.relative_to(root)): sha256(p)
            for p in [
                *folder.rglob("*"),
                raw,
                *(
                    folder.with_name(folder.name + s)
                    for s in ["-spec.json", ".log", ".supervisor.json"]
                ),
            ]
            if p.is_file()
        }
        receipt = (
            str((folder / "attempt-evidence.json").relative_to(root))
            if order == 34
            else f"old-completion/attempt-{order}.json"
        )
        broad = {**physical, **prefix[0]["files"]}
        write_json(root / receipt, {"case_id": job["id"], "files": broad})
        if order == 34:
            physical[receipt] = sha256(root / receipt)
        files = {**broad, **physical, receipt: sha256(root / receipt)}
        failures.append(
            dict(
                case_id=job["id"],
                order=order,
                original_job=job,
                execution_job=job,
                attempt=1,
                charged_slots=1,
                start_markers=1,
                outcome="needs_review",
                files=files,
                physical_files=physical,
                receipt=receipt,
                receipt_sha256=sha256(root / receipt),
                posterior=str(raw.relative_to(root)),
                posterior_sha256=sha256(raw),
            )
        )

    def project(e):
        return {k: e[k] for k in ["case_id", "charged_slots", "files", "receipt", "receipt_sha256"]}

    attempts = [
        {k: e[k] for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]}
        | dict(outcome="accepted", start_markers=1)
        for e in prefix[:34]
    ]
    attempts.append(
        {
            k: failures[0][k]
            for k in [
                "case_id",
                "charged_slots",
                "receipt",
                "receipt_sha256",
                "outcome",
                "start_markers",
            ]
        }
    )
    extension = []
    for i, e in enumerate([prefix[34], prefix[35], failures[1]]):
        extension.append(
            dict(
                case_id=e["case_id"],
                execution_job=e["execution_job"],
                charged_slots=1,
                start_markers=1,
                outcome="accepted" if i < 2 else "needs_review",
            )
        )
    baseline = dict(
        calls_charged=38,
        calls_started=38,
        next_case=34,
        current=None,
        plan_sha256=sha256(root / worker.PLAN),
        accepted=[project(e) for e in prefix[:34]],
        attempts=attempts,
        completion_v1=dict(
            repair=project(prefix[34]),
            accepted_remaining=[project(prefix[35])],
            next_original_order=36,
            attempts=extension,
        ),
    )
    base = worker.OUTPUT
    state_name = base + "/baseline-state.json"
    registry_name = base + "/baseline-registry.json"
    review_name = base + "/baseline-review.json"
    write_json(root / state_name, baseline)
    pins = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    historical = dict(Counter(e["case_id"] for e in [*prefix, *failures]))
    registry = dict(
        status="frozen_partial_sensitivity_history",
        schema_version=2,
        run_id=worker.RUN_ID,
        baseline_state=state_name,
        baseline_state_sha256=pins[state_name],
        original_plan=worker.PLAN,
        original_plan_sha256=pins[worker.PLAN],
        original_science_gate=worker.fit.GATE,
        original_science_gate_sha256=pins[worker.fit.GATE],
        accepted_prefix=prefix,
        failed_attempts=failures,
        historical_attempts_by_original_case=historical,
        calls_charged=38,
        calls_started=38,
        logical_cases_completed=36,
        start_original_order=36,
        max_sampler_call_slots=110,
        files=pins,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
    )
    write_json(root / registry_name, registry)
    pins = {**pins, registry_name: sha256(root / registry_name)}
    resources = {"synthetic": True}
    proof = {"synthetic_reviewed_proof_contract": True}
    bindings = dict(
        project_root=str(root),
        state=str(root / "context/runs/arrival-model-fitting-v1/sensitivity-state.json"),
        output=worker.OUTPUT,
        store=worker.STORE,
    )

    def digest(x):
        return hashlib.sha256(
            json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    review = dict(
        status="accepted_sensitivity_remaining_numerical_protocol_plan",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        baseline_registry=registry_name,
        baseline_registry_sha256=pins[registry_name],
        original_plan_sha256=pins[worker.PLAN],
        proof_contract=proof,
        accepted_prefix_sha256=digest(prefix),
        failed_attempts_sha256=digest(failures),
        historical_attempts_by_original_case=historical,
        logical_cases_completed=36,
        start_original_order=36,
        calls_charged=38,
        calls_started=38,
        protocol=worker.PROTOCOL,
        approved_original_jobs=originals[36:],
        files=pins,
    )
    write_json(root / review_name, review)
    pins = {**pins, review_name: sha256(root / review_name)}
    gate = dict(
        status="accepted_sensitivity_remaining_numerical_protocol",
        independent_checker=True,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        run_id=worker.RUN_ID,
        files=pins,
        resources=resources,
        path_bindings=bindings,
        proof_contract=proof,
        original_plan_sha256=pins[worker.PLAN],
        original_science_gate_sha256=pins[worker.fit.GATE],
        baseline_state=state_name,
        baseline_state_sha256=pins[state_name],
        baseline_registry=registry_name,
        baseline_registry_sha256=pins[registry_name],
        baseline_review=review_name,
        baseline_review_sha256=pins[review_name],
        historical_attempts_by_original_case=historical,
        calls_before=38,
        started_before=38,
        start_original_order=36,
        protocol=worker.PROTOCOL,
        attempts_by_original_case=next_attempts(originals),
        jobs=worker.execution_jobs(
            originals[36:], worker.RUN_ID, next_attempts(originals), worker.PROTOCOL
        ),
    )
    write_json(root / worker.GATE, gate)
    runtime = SimpleNamespace(
        resources=lambda: resources,
        bindings=lambda root, run_id: bindings,
        proof_contract=lambda: proof,
        c=SimpleNamespace(r=SimpleNamespace(parent_roots=lambda root: [])),
    )
    original_import = worker.importlib.import_module
    monkeypatch.setattr(
        worker.importlib,
        "import_module",
        lambda name: (
            runtime
            if name == "scripts.run_arrival_sensitivity_numerical"
            else original_import(name)
        ),
    )
    return gate, registry, review, baseline


def test_complete_gate_is_metadata_only_reconciles38_and_retained_broad_receipts(
    tmp_path, monkeypatch
):
    gate_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.fit, "_case_data", lambda *a: pytest.fail("native data before admission")
    )
    a = worker.verify_gate(tmp_path)
    assert (
        len(a["jobs"]) == 19 and len(a["accepted_prefix"]) == 36 and len(a["failed_attempts"]) == 2
    )
    assert a["baseline"]["calls_charged"] == 38
    assert len(a["failed_attempts"][0]["files"]) > len(a["failed_attempts"][0]["physical_files"])


@pytest.mark.parametrize(
    "change",
    [
        "counter",
        "history",
        "next-attempt",
        "prefix-digest",
        "failed-raw",
        "broad-ref",
        "physical-ref",
        "protocol",
        "jobs",
        "source",
        "baseline-history",
    ],
)
def test_any_provenance_or_review_failure_precedes_native_read(tmp_path, monkeypatch, change):
    from analysis.arrival.evidence import write_json

    gate, registry, review, baseline = gate_fixture(tmp_path, monkeypatch)
    if change == "counter":
        gate["calls_before"] = 37
    elif change == "history":
        gate["historical_attempts_by_original_case"] = {}
    elif change == "next-attempt":
        gate["attempts_by_original_case"][original_jobs()[36]["id"]] = 1
    elif change == "prefix-digest":
        review["accepted_prefix_sha256"] = "0" * 64
    elif change == "failed-raw":
        gate["files"].pop(registry["failed_attempts"][0]["posterior"])
    elif change == "broad-ref":
        gate["files"].pop(next(iter(registry["accepted_prefix"][0]["files"])))
    elif change == "physical-ref":
        (tmp_path / registry["failed_attempts"][0]["posterior"]).write_bytes(b"changed")
    elif change == "protocol":
        gate["protocol"] = {**worker.PROTOCOL, "target_accept": 0.995}
    elif change == "jobs":
        gate["jobs"][0]["sampler"]["seed"] += 1
    elif change == "source":
        (tmp_path / worker.CONSUMED[0]).write_text("changed")
    else:
        baseline["accepted"] = []
    if change == "prefix-digest":
        write_json(tmp_path / gate["baseline_review"], review)
        gate["files"][gate["baseline_review"]] = worker.sha256(tmp_path / gate["baseline_review"])
        gate["baseline_review_sha256"] = gate["files"][gate["baseline_review"]]
    if change == "baseline-history":
        write_json(tmp_path / gate["baseline_state"], baseline)
    write_json(tmp_path / worker.GATE, gate)
    monkeypatch.setattr(
        worker.fit, "_case_data", lambda *a: pytest.fail("native read before complete Gate")
    )
    with pytest.raises(ValueError):
        worker.verify_gate(tmp_path)


def sampling_fixture(root, monkeypatch, order=36, failure=None) -> dict[str, Any]:
    import json
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd
    import xarray as xr

    gate_fixture(root, monkeypatch)
    admission = worker.verify_gate(root)
    monkeypatch.setattr(worker, "verify_gate", lambda *a, **kw: admission)
    job = admission["jobs"][order - 36]
    folder, raw = worker.case_paths(root, job)
    lane = SimpleNamespace(
        target="NCEI-native-duration",
        record_ids=["r0", "r1", "r2"],
        event_ids=["e0", "e0", "e1"],
        site_ids=["s0", "s1", "s2"],
        sequences=["seq0", "seq0", "seq1"],
        y=np.array([10.0, 20.0, 30.0]),
        response=np.array([-0.1, 0.2, 0.3]),
        distance_km=np.array([500.0, 2000.0, 5000.0]),
        reference_minutes=np.array([5.0, 20.0, 50.0]),
        x=np.array([-1.0, 0.0, 1.0]),
        included=np.ones(3, dtype=bool),
        rows=[{}, {}, {}],
    )
    ids = np.array([0, 2])
    monkeypatch.setattr(worker.fit, "_case_data", lambda *a: (lane, ids, {"synthetic": True}))
    prior = dict(alpha_sd=0.5, beta_sd=0.25, tau_sd=0.4, sigma_sd=0.4)
    if job["original_job"]["kind"] == "mean-curvature":
        prior["gamma_sd"] = 0.4
    monkeypatch.setattr(worker.fit, "_case_priors", lambda *a: (prior, None))
    calls, summaries = [], []

    def sample(**kwargs):
        assert kwargs == {k: v for k, v in job["sampler"].items() if k != "seed"} | dict(
            random_seed=job["original_job"]["seed"], progressbar=False
        )
        assert raw.exists() and raw.stat().st_size == 0
        assert json.loads((folder / "sampling-start.json").read_text()) == job
        calls.append(kwargs)
        if failure == "sample":
            raise RuntimeError("synthetic interruption")
        values: dict[str, Any] = {
            name: (("chain", "draw"), np.full((4, 2000), 0.2))
            for name in worker._population_spec(lane.target, job["original_job"]["kind"])
            if name != "sigma_anchor"
        }
        values["sigma_anchor"] = (("chain", "draw", "scale_anchor_km"), np.full((4, 2000, 3), 0.3))
        settings: dict[str, Any] = dict(
            sampler="nuts",
            settings=dict(
                num_tune=2000,
                num_draws=2000,
                num_chains=4,
                seed=123456,
                adapt_options=dict(step_size_settings=dict(target_accept=0.99)),
            ),
        )
        attrs = dict(inference_library="nutpie", inference_library_version="0.16.11")
        posterior_attrs: dict[str, Any] = dict(attrs, tuning_steps=2000)
        stats_attrs: dict[str, Any] = dict(attrs, inference_library_settings=json.dumps(settings))
        if failure == "tune":
            posterior_attrs.update(tuning_steps=1000, repair_tune=2000)
        elif failure == "accept":
            settings["settings"]["adapt_options"]["step_size_settings"]["target_accept"] = 0.95
            stats_attrs.update(
                inference_library_settings=json.dumps(settings), repair_target_accept=0.99
            )
        elif failure == "backend":
            stats_attrs.update(inference_library="pymc", unrelated_note="nutpie")
        elif failure == "version":
            posterior_attrs["inference_library_version"] = "other"
        elif failure == "missing-settings":
            stats_attrs.pop("inference_library_settings")
        elif failure == "malformed-settings":
            stats_attrs["inference_library_settings"] = "{"
        elif failure == "source":
            (root / worker.CONSUMED[0]).write_text("source drift after invocation")
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    values,
                    coords=dict(
                        chain=range(4), draw=range(2000), scale_anchor_km=[500, 2000, 5000]
                    ),
                    attrs=posterior_attrs,
                ),
                "sample_stats": xr.Dataset(
                    {"diverging": (("chain", "draw"), np.zeros((4, 2000), bool))},
                    coords=dict(chain=range(4), draw=range(2000)),
                    attrs=stats_attrs,
                ),
            }
        )

    monkeypatch.setattr(worker.fit.pm, "sample", sample)

    def diagnostics(tree):
        assert raw.stat().st_size > 0
        return dict(
            screen_passed=failure != "diagnostics", divergences=1 if failure == "diagnostics" else 0
        ), pd.DataFrame({"r_hat": [1.001]}, index=["alpha"])

    monkeypatch.setattr(worker.fit, "sampling_diagnostics", diagnostics)
    summary: dict[str, Any] = {
        g: [dict(quantity=g, quantile_valid=True, native_representable=True, median=0.2)]
        for g in ["parameters", "derived", "curves", "record_intervals"]
    }
    summary["conditional_ppc"] = [
        dict(
            quantity="ppc",
            replicated_quantile_valid=True,
            replicated_native_representable=True,
            observed_quantile_valid=True,
        )
    ]

    def summarize(*args, **kw):
        assert raw.stat().st_size > 0
        assert args[0] is lane and args[1] == job["original_job"]["kind"]
        assert kw["seed"] == job["original_job"]["seed"] + 1 and kw["draws"] == 800
        np.testing.assert_array_equal(kw["indices"], ids)
        summaries.append(kw)
        return deepcopy(summary)

    monkeypatch.setattr(worker.fit, "summarize_posterior", summarize)
    return dict(
        admission=admission, job=job, folder=folder, raw=raw, calls=calls, summaries=summaries
    )


def close_process(root, f):
    from analysis.arrival.evidence import sha256, write_json

    folder, job = f["folder"], f["job"]
    spec = folder.with_name(folder.name + "-spec.json")
    write_json(spec, job)
    folder.with_name(folder.name + ".log").write_text("synthetic log")
    write_json(
        folder.with_name(folder.name + ".supervisor.json"),
        dict(
            returncode=0,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec),
            plan_sha256=f["admission"]["files"][worker.PLAN],
            numerical_gate_sha256=f["admission"]["files"][worker.GATE],
            invocation_git_sha="a" * 40,
            monitor_failures=[],
        ),
    )


@pytest.mark.parametrize("order", [36, 44])
def test_linear_and_curved_save_first_exact_sampler_and_complete_semantic_replay(
    tmp_path, monkeypatch, order
):
    from analysis.arrival.evidence import sha256, write_json

    f = sampling_fixture(tmp_path, monkeypatch, order)
    result = worker.fit_case(tmp_path, f["job"], f["folder"], f["raw"])
    assert result["status"] == "computed_pending_scientific_review", result
    assert len(f["calls"]) == len(f["summaries"]) == 1
    close_process(tmp_path, f)
    proof = worker.case_artifacts(tmp_path, f["job"], f["admission"]["files"])
    assert len(proof["files"]) == 17 and len(f["summaries"]) == 2
    write_json(
        proof["manifest"], dict(case_id=f["job"]["original_job"]["id"], files=proof["files"])
    )
    accepted = dict(
        case_id=f["job"]["original_job"]["id"],
        charged_slots=1,
        files=proof["files"],
        receipt=str(proof["manifest"].relative_to(tmp_path)),
        receipt_sha256=sha256(proof["manifest"]),
    )
    assert (
        worker.case_artifacts(tmp_path, f["job"], f["admission"]["files"], accepted)["files"]
        == proof["files"]
    )
    with pytest.raises(ValueError, match="never overwrite"):
        worker.fit_case(tmp_path, f["job"], f["folder"], f["raw"])


@pytest.mark.parametrize(
    "failure",
    [
        "sample",
        "tune",
        "accept",
        "backend",
        "version",
        "missing-settings",
        "malformed-settings",
        "diagnostics",
        "source",
    ],
)
def test_failure_retains_raw_and_genuine_attrs_cannot_be_masked(tmp_path, monkeypatch, failure):
    f = sampling_fixture(tmp_path, monkeypatch, failure=failure)
    result = worker.fit_case(tmp_path, f["job"], f["folder"], f["raw"])
    assert result["status"] != "computed_pending_scientific_review"
    assert len(f["calls"]) == 1
    assert f["raw"].exists() and (f["raw"].stat().st_size > 0) == (failure != "sample")
    if failure != "source":
        assert not (f["folder"] / "summary.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        "native",
        "record",
        "event",
        "tuning",
        "backend",
        "diagnostics-csv",
        "summary-csv",
        "inputs",
        "supervisor",
        "unknown",
    ],
)
def test_artifact_verification_rejects_resealed_semantic_corruption(tmp_path, monkeypatch, change):
    import json

    import xarray as xr

    from analysis.arrival.evidence import sha256, write_json

    f = sampling_fixture(tmp_path, monkeypatch)
    assert (
        worker.fit_case(tmp_path, f["job"], f["folder"], f["raw"])["status"]
        == "computed_pending_scientific_review"
    )
    close_process(tmp_path, f)
    folder = f["folder"]
    if change in {"native", "record", "event", "tuning", "backend"}:
        with xr.open_datatree(f["raw"], engine="h5netcdf") as loaded:
            tree = cast(Any, loaded.load().copy(deep=True))
        if change == "native":
            tree["observed_data"]["native_minutes"].values[0] += 1
        elif change == "record":
            tree["observed_data"] = xr.DataTree(
                tree["observed_data"].to_dataset().assign_coords(record=["wrong", "r2"])
            )
        elif change == "event":
            tree["observed_data"]["event_id"].values[0] = "wrong"
        elif change == "tuning":
            tree["posterior"].attrs["tuning_steps"] = 1000
        else:
            tree["sample_stats"].attrs.update(inference_library="pymc", unrelated_note="nutpie")
        tree.to_netcdf(f["raw"], engine="h5netcdf")
        result = json.loads((folder / "result.json").read_text())
        result["posterior_sha256"] = sha256(f["raw"])
        write_json(folder / "result.json", result)
    elif change in {"diagnostics-csv", "summary-csv"}:
        (
            folder / ("sampling-diagnostics.csv" if change == "diagnostics-csv" else "curves.csv")
        ).write_text("wrong")
    elif change == "inputs":
        write_json(folder / "inputs.json", {})
    elif change == "unknown":
        (folder / "extra.json").write_text("unexpected")
    else:
        write_json(folder.with_name(folder.name + ".supervisor.json"), {})
    with pytest.raises(ValueError):
        worker.case_artifacts(tmp_path, f["job"], f["admission"]["files"])


@pytest.mark.parametrize(
    "entry",
    [
        "nested-manifest",
        "empty-directory",
        "directory-symlink",
        "file-symlink",
        "canonical-manifest-symlink",
        "fifo",
        "raw-symlink",
    ],
)
@pytest.mark.parametrize("late", [False, True])
def test_inventory_rejects_every_unlisted_entry_at_start_and_end(
    tmp_path, monkeypatch, entry, late
):
    import os

    f = sampling_fixture(tmp_path, monkeypatch)
    assert (
        worker.fit_case(tmp_path, f["job"], f["folder"], f["raw"])["status"]
        == "computed_pending_scientific_review"
    )
    close_process(tmp_path, f)
    folder = f["folder"]
    added = folder / "unlisted"

    def inject():
        nonlocal added
        if entry == "nested-manifest":
            added.mkdir()
            added = added / "attempt-evidence.json"
            added.write_text("retain this hidden partial")
        elif entry == "empty-directory":
            added.mkdir()
        elif entry == "directory-symlink":
            added.symlink_to(tmp_path / "analysis", target_is_directory=True)
        elif entry in {"file-symlink", "canonical-manifest-symlink"}:
            if entry == "canonical-manifest-symlink":
                added = folder / "attempt-evidence.json"
            added.symlink_to(folder / "result.json")
        elif entry == "fifo":
            os.mkfifo(added)
        else:
            added = f["raw"]
            alias = added.with_suffix(".retained.nc")
            added.rename(alias)
            added.symlink_to(alias)

    if late:
        summarize = worker.fit.summarize_posterior

        def during_replay(*args, **kwargs):
            value = summarize(*args, **kwargs)
            inject()
            return value

        monkeypatch.setattr(worker.fit, "summarize_posterior", during_replay)
    else:
        inject()
    with pytest.raises(ValueError):
        worker.case_artifacts(tmp_path, f["job"], f["admission"]["files"])
    assert added.exists() or added.is_symlink()
    if entry == "nested-manifest":
        assert added.read_text() == "retain this hidden partial"
