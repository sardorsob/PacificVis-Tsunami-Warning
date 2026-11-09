"""Versioned numerical execution of unchanged, prospectively reviewed NCEI cases."""

# pyright: basic
from __future__ import annotations

import hashlib
import importlib
import json
import re
import stat
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival import model_sensitivity_fit as fit
from analysis.arrival import model_sensitivity_repair as first_repair
from analysis.arrival import model_sensitivity_report as source
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_sensitivity_priors import _population_spec

DESIGN = str(Path(fit.GATE).parent)
RUN_ID = "numerical-protocol-v2"
GATE = DESIGN + "/" + RUN_ID + "/review-acceptance.json"
OUTPUT = fit.OUTPUT + "/" + RUN_ID
STORE = "data/processed/models/arrival-sensitivity-" + RUN_ID
PLAN = fit.OUTPUT + "/plan.json"
PROTOCOL = dict(draws=2000, tune=2000, chains=4, cores=2, target_accept=0.99, nuts_sampler="nutpie")
NUTPIE_VERSION = "0.16.11"
TABLES = ("parameters", "derived", "curves", "conditional_ppc", "record_intervals")
LEAVES = (
    "job.json",
    "inputs.json",
    "membership.json",
    "sampling-start.json",
    "result.json",
    "diagnostics.json",
    "sampling-diagnostics.csv",
)
CONSUMED = tuple(
    sorted(
        set(fit.CONSUMED)
        | set(first_repair.CONSUMED)
        | {
            "analysis/arrival/model_sensitivity_report.py",
            "analysis/arrival/model_sensitivity_numerical_fit.py",
            "scripts/fit_arrival_sensitivity_numerical.py",
            "tests/test_arrival_model_sensitivity_numerical_fit.py",
            "scripts/run_arrival_sensitivity_numerical.py",
            "tests/test_run_arrival_sensitivity_numerical.py",
        }
    )
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _run_id(value):
    match = (
        re.fullmatch(r"numerical-protocol-v([1-9][0-9]*)", value)
        if isinstance(value, str)
        else None
    )
    _require(
        match is not None and int(match[1]) >= 2,
        "literal reviewed numerical protocol version required",
    )
    return value


def _protocol(value):
    _require(
        isinstance(value, dict) and set(value) == set(PROTOCOL),
        "complete numerical protocol required",
    )
    _require(
        all(type(value[k]) is int and value[k] == PROTOCOL[k] for k in ["draws", "chains", "cores"])
        and type(value["tune"]) is int
        and 2000 <= value["tune"] <= 10000
        and type(value["target_accept"]) in {int, float}
        and 0.99 <= value["target_accept"] < 1
        and value["nuts_sampler"] == "nutpie",
        "bounded same-model numerical protocol required",
    )
    return value


def execution_jobs(original_jobs, run_id, attempts_by_original_case, protocol):
    _run_id(run_id)
    _protocol(protocol)
    _require(
        isinstance(original_jobs, list)
        and original_jobs
        and isinstance(attempts_by_original_case, dict)
        and set(attempts_by_original_case) == {j["id"] for j in original_jobs},
        "exact original-case attempt map required",
    )
    jobs = []
    for original in original_jobs:
        order, attempt = original.get("order"), attempts_by_original_case[original["id"]]
        _require(
            type(order) is int
            and 36 <= order < 55
            and type(attempt) is int
            and attempt in {1, 2}
            and original.get("target") == "NCEI-native-duration"
            and original.get("kind") in {"distance-scale", "mean-curvature"}
            and original.get("prior_variant") == "base"
            and type(original.get("seed")) is int,
            "only literal base-prior NCEI cases with at most two attempts required",
        )
        jobs.append(
            dict(
                id=f"ms5-{run_id}-{order:03d}-attempt-{attempt}",
                original_job=original,
                attempt=attempt,
                sampler={**protocol, "seed": original["seed"]},
                order=order,
            )
        )
    _require(len({j["id"] for j in jobs}) == len(jobs), "distinct numerical jobs required")
    return jobs


def case_paths(root, job, admission=None):
    match = re.fullmatch(
        r"ms5-(numerical-protocol-v[1-9][0-9]*)-[0-9]{3}-attempt-[12]", job.get("id", "")
    )
    _require(match is not None, "literal separate numerical case ID required")
    assert match is not None
    run_id = _run_id(match[1])
    sampler = job.get("sampler", {})
    protocol = {k: v for k, v in sampler.items() if k != "seed"}
    expected = execution_jobs(
        [job.get("original_job", {})],
        run_id,
        {job.get("original_job", {}).get("id"): job.get("attempt")},
        protocol,
    )[0]
    _require(
        job == expected
        and (
            admission is None or job in admission["jobs"] and run_id == admission["gate"]["run_id"]
        ),
        "exact admitted numerical execution descriptor required",
    )
    return root / fit.OUTPUT / run_id / "jobs" / job["id"], root / (
        "data/processed/models/arrival-sensitivity-" + run_id
    ) / (job["id"] + ".nc")


def _inventory(root, folder, raw):
    _require(
        folder.resolve() == folder and folder.is_dir(),
        "literal nonsymlink numerical output directory required",
    )
    allowed = {
        folder / name
        for name in [*LEAVES, "summary.json", *[g.replace("_", "-") + ".csv" for g in TABLES]]
    }
    manifest = folder / "attempt-evidence.json"
    names = set()
    for path in folder.rglob("*"):
        _require(
            path.parent == folder
            and path.resolve() == path
            and stat.S_ISREG(path.lstat().st_mode)
            and path in allowed | {manifest},
            "flat complete numerical inventory requires only literal regular producer files",
        )
        if path != manifest:
            names.add(path)
    names |= {
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    }
    return {
        str(p.relative_to(root)): sha256(source._path(root, str(p.relative_to(root))))
        for p in names
    }


def verify_gate(root, gate_path=GATE):
    """Verify the complete frozen history and code before any native/NC loader."""
    root = root.resolve()
    _require(isinstance(gate_path, str), "project-relative Gate path required")
    run_id = _run_id(Path(gate_path).parent.name)
    _require(
        gate_path == f"{DESIGN}/{run_id}/review-acceptance.json",
        "canonical reviewed Gate path required",
    )
    gate = json.loads(source._path(root, gate_path).read_text())
    base = fit.OUTPUT + "/" + run_id
    state_name, registry_name, review_name = [
        base + "/" + n
        for n in ["baseline-state.json", "baseline-registry.json", "baseline-review.json"]
    ]
    required = set(CONSUMED) | {fit.GATE, PLAN, state_name, registry_name, review_name}
    _require(
        gate.get("status") == "accepted_sensitivity_remaining_numerical_protocol"
        and gate.get("independent_checker") is True
        and gate.get("run_id") == run_id
        and gate.get("confirmation_outcomes_parsed") is False
        and gate.get("reserved_outcomes") == "sealed"
        and required <= set(gate.get("files", {}))
        and "context/runs/arrival-model-fitting-v1/sensitivity-state.json"
        not in gate.get("files", {}),
        "complete independent numerical execution Gate required",
    )
    pins = {**gate["files"], gate_path: sha256(root / gate_path)}
    source._unchanged(root, pins)
    runtime = importlib.import_module("scripts.run_arrival_sensitivity_numerical")
    _require(
        gate.get("resources") == runtime.resources()
        and gate.get("path_bindings") == runtime.bindings(root, run_id)
        and gate.get("proof_contract") == runtime.proof_contract(),
        "same reviewed runtime resources/bindings/proofs required",
    )
    original = fit.verify_gate(root)
    source._require(pins, original["files"])
    original_jobs = original["gate"]["jobs"]
    plan = source._read(root, pins, PLAN)
    _require(
        plan.get("jobs") == original_jobs
        and plan.get("files") == original["files"]
        and gate.get("original_plan_sha256") == pins[PLAN]
        and gate.get("original_science_gate_sha256") == pins[fit.GATE],
        "unchanged original science and55-job plan required",
    )
    baseline: Any
    registry: Any
    review: Any
    baseline, registry, review = [
        source._read(root, pins, n) for n in [state_name, registry_name, review_name]
    ]
    for field, name in [
        ("baseline_state", state_name),
        ("baseline_registry", registry_name),
        ("baseline_review", review_name),
    ]:
        _require(
            gate.get(field) == name and gate.get(field + "_sha256") == pins[name],
            "literal immutable baseline/review binding required",
        )
    _require(
        registry.get("status") == "frozen_partial_sensitivity_history"
        and registry.get("schema_version") == 2
        and registry.get("run_id") == run_id
        and registry.get("baseline_state") == state_name
        and registry.get("baseline_state_sha256") == pins[state_name]
        and registry.get("original_plan") == PLAN
        and registry.get("original_plan_sha256") == pins[PLAN]
        and registry.get("original_science_gate") == fit.GATE
        and registry.get("original_science_gate_sha256") == pins[fit.GATE]
        and registry.get("confirmation_outcomes_parsed") is False
        and registry.get("reserved_outcomes") == "sealed",
        "complete frozen history registry required",
    )
    source._require(pins, registry.get("files"))
    source._require(pins, review.get("files"))
    source._require(
        review["files"],
        {**registry["files"], registry_name: pins[registry_name], state_name: pins[state_name]},
    )
    _require(
        review.get("status") == "accepted_sensitivity_remaining_numerical_protocol_plan"
        and review.get("independent_checker") is True
        and review.get("confirmation_outcomes_parsed") is False
        and review.get("reserved_outcomes") == "sealed",
        "independent baseline scientific review required",
    )
    for field, expected in {
        "baseline_registry": registry_name,
        "baseline_registry_sha256": pins[registry_name],
        "original_plan_sha256": pins[PLAN],
        "proof_contract": gate["proof_contract"],
    }.items():
        _require(
            review.get(field) == expected,
            "baseline review must bind this exact history and protocol",
        )
    prefix, failures, historical = [
        registry.get(k)
        for k in ["accepted_prefix", "failed_attempts", "historical_attempts_by_original_case"]
    ]
    _require(
        isinstance(prefix, list)
        and len(prefix) == 36
        and isinstance(failures, list)
        and len(failures) == 2
        and registry.get("calls_charged")
        == registry.get("calls_started")
        == baseline.get("calls_charged")
        == baseline.get("calls_started")
        == 38
        and registry.get("logical_cases_completed") == registry.get("start_original_order") == 36
        and registry.get("max_sampler_call_slots") == 110,
        "exact36 accepted/two failed/38 charged baseline required",
    )
    for field, value in {
        "historical_attempts_by_original_case": historical,
        "calls_before": 38,
        "started_before": 38,
        "start_original_order": 36,
    }.items():
        _require(
            gate.get(field) == value,
            "same reviewed history and inclusive call accounting required",
        )

    def compact_sha(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    for field, value in {
        "accepted_prefix_sha256": compact_sha(prefix),
        "failed_attempts_sha256": compact_sha(failures),
        "historical_attempts_by_original_case": historical,
        "logical_cases_completed": 36,
        "start_original_order": 36,
        "calls_charged": 38,
        "calls_started": 38,
        "protocol": gate.get("protocol"),
        "approved_original_jobs": original_jobs[36:],
    }.items():
        _require(
            review.get(field) == value,
            "baseline plan must bind exact history digests and remaining original jobs",
        )
    for i, entry in enumerate(prefix):
        job = original_jobs[i]
        repaired = i == 34
        folder = first_repair.OUTPUT if repaired else fit.OUTPUT + "/jobs/" + job["id"]
        raw = first_repair.STORE if repaired else fit.STORE + "/" + job["id"] + ".nc"
        _require(
            entry.get("order") == i
            and entry.get("case_id") == job["id"]
            and entry.get("original_job") == job
            and entry.get("producer") == ("repair_v1" if repaired else "original")
            and entry.get("source_role") == ("numerical_repair" if repaired else "original")
            and entry.get("execution_job") == (first_repair.repair_job(job) if repaired else job)
            and entry.get("posterior") == raw
            and entry.get("posterior_sha256") == pins.get(raw)
            and entry.get("charged_slots") == 1
            and entry.get("receipt") == folder + "/attempt-evidence.json"
            and entry.get("receipt_sha256") == pins.get(entry["receipt"]),
            "literal ordered accepted prefix producer/raw proof required",
        )
        source._require(pins, entry.get("files"))
        _require(
            source._read(root, pins, entry["receipt"])
            == {"case_id": job["id"], "files": entry["files"]},
            "original accepted receipt inventory required",
        )
    _require(
        [e.get("order") for e in failures] == [34, 36],
        "both original failures retained in order required",
    )
    for entry in failures:
        job = original_jobs[entry["order"]]
        folder = root / fit.OUTPUT / "jobs" / job["id"]
        raw = root / fit.STORE / (job["id"] + ".nc")
        _require(
            entry.get("case_id") == job["id"]
            and entry.get("original_job") == entry.get("execution_job") == job
            and entry.get("attempt")
            == entry.get("charged_slots")
            == entry.get("start_markers")
            == 1
            and entry.get("outcome") != "accepted"
            and entry.get("posterior") == str(raw.relative_to(root))
            and entry.get("posterior_sha256") == pins.get(str(raw.relative_to(root)))
            and entry.get("receipt_sha256") == pins.get(entry.get("receipt")),
            "literal original failed attempts required",
        )
        source._require(pins, entry.get("files"))
        source._require(pins, entry.get("physical_files"))
        actual = {
            str(p.relative_to(root)): sha256(source._path(root, str(p.relative_to(root))))
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
        _require(
            actual == entry["physical_files"],
            "complete failed physical inventory differs from broad receipt closure",
        )
        result = source._read(root, pins, str((folder / "result.json").relative_to(root)))
        _require(
            result.get("job") == job
            and result.get("status") == "diagnostic_failure"
            and result.get("posterior") == str(raw.relative_to(root))
            and result.get("posterior_sha256") == pins[str(raw.relative_to(root))],
            "retained diagnostic failures must never become accepted cases",
        )
    derived = dict(Counter(e["case_id"] for e in [*prefix, *failures]))
    _require(
        historical == derived
        and sum(derived.values()) == 38
        and set(derived) == {j["id"] for j in original_jobs[:37]},
        "full historical attempt map must reconcile all38 calls",
    )
    fields = ["case_id", "charged_slots", "files", "receipt", "receipt_sha256"]

    def project(entry):
        return {k: entry[k] for k in fields}

    legacy, extension = baseline.get("accepted", []), baseline.get("completion_v1", {})
    _require(
        len(legacy) == 34
        and len(baseline.get("attempts", [])) == 35
        and legacy == [project(e) for e in prefix[:34]]
        and baseline.get("next_case") == 34
        and baseline.get("current") is None
        and baseline.get("plan_sha256") == pins[PLAN]
        and extension.get("repair") == project(prefix[34])
        and extension.get("accepted_remaining") == [project(prefix[35])]
        and extension.get("next_original_order") == 36
        and len(extension.get("attempts", [])) == 3,
        "original and first-completion histories must remain unchanged",
    )
    for entry, attempt in zip(prefix[:34], baseline["attempts"][:34], strict=True):
        _require(
            all(
                attempt.get(k) == entry[k]
                for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]
            )
            and attempt.get("start_markers") == 1
            and attempt.get("outcome") == "accepted",
            "original successful attempt accounting required",
        )
    original_failure = baseline["attempts"][-1]
    _require(
        all(
            original_failure.get(k) == failures[0][k]
            for k in ["case_id", "charged_slots", "receipt", "receipt_sha256", "start_markers"]
        )
        and original_failure.get("outcome") != "accepted",
        "original failed attempt must remain distinct",
    )
    for index, attempt in enumerate(extension["attempts"]):
        entry = prefix[34 + index] if index < 2 else failures[1]
        _require(
            attempt.get("case_id") == entry["case_id"]
            and attempt.get("execution_job") == entry["execution_job"]
            and attempt.get("charged_slots") == attempt.get("start_markers") == 1
            and (attempt.get("outcome") == "accepted") == (index < 2),
            "partial completion attempts must preserve exact costs and jobs",
        )
    protocol = _protocol(gate.get("protocol"))
    _require(
        gate_path != GATE or protocol == PROTOCOL, "current v2 protocol is exactly2000tune/0.99"
    )
    attempts = gate.get("attempts_by_original_case")
    _require(
        isinstance(attempts, dict)
        and attempts == {j["id"]: derived.get(j["id"], 0) + 1 for j in original_jobs[36:]},
        "next attempt must follow retained history without resetting counters",
    )
    jobs = execution_jobs(original_jobs[36:], run_id, attempts, protocol)
    _require(gate.get("jobs") == jobs, "exact prospectively reviewed remaining19 jobs required")
    source._unchanged(root, pins)
    return dict(
        gate=gate,
        gate_path=gate_path,
        files=pins,
        original_admission=original,
        original_jobs=original_jobs,
        baseline=baseline,
        accepted_prefix=prefix,
        failed_attempts=failures,
        jobs=jobs,
        parents=runtime.c.r.parent_roots(root),
    )


def _case(root, job, admission):
    _require(job in admission["jobs"], "one exact admitted numerical job required")
    original = job["original_job"]
    lane, ids, frozen = fit._case_data(root, original, admission["original_admission"])
    base, wider = fit._case_priors(root, original)
    _require(wider is None, "base priors only; no numerical prior alteration")
    model = fit.build_sensitivity_model(lane, original["kind"], base, "base", indices=ids)
    _require(
        list(model.coords.get("record") or []) == [lane.record_ids[int(i)] for i in ids]
        and {v.name for v in model.free_RVs}
        == set(_population_spec(lane.target, original["kind"])),
        "exact explicit population/training graph required",
    )
    return lane, ids, frozen, base, model


def _observed(lane, ids):
    return xr.Dataset(
        {
            name: (("record",), values[ids])
            for name, values in [
                ("response", lane.response),
                ("native_minutes", lane.y),
                ("distance_km", lane.distance_km),
                ("reference_minutes", lane.reference_minutes),
            ]
        }
        | {
            name: (("record",), [values[int(i)] for i in ids])
            for name, values in [
                ("event_id", lane.event_ids),
                ("sequence", lane.sequences),
                ("site_id", lane.site_ids),
            ]
        },
        coords={"record": [lane.record_ids[int(i)] for i in ids]},
        attrs={"target": lane.target, "scope": "literal_case_training_only"},
    )


def _population(tree, job):
    post, stats = tree["posterior"].to_dataset(), tree["sample_stats"].to_dataset()
    sampler = job["sampler"]
    try:
        config = json.loads(stats.attrs["inference_library_settings"])
        settings = config["settings"]
        actual = {
            "sampler": config["sampler"],
            "tune": settings["num_tune"],
            "draws": settings["num_draws"],
            "chains": settings["num_chains"],
            "target_accept": settings["adapt_options"]["step_size_settings"]["target_accept"],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("original native nutpie settings required") from error
    _require(
        all(
            g.attrs.get("inference_library") == "nutpie"
            and g.attrs.get("inference_library_version") == NUTPIE_VERSION
            for g in [post, stats]
        )
        and type(post.attrs.get("tuning_steps")) in {int, np.int64, np.int32}
        and all(type(actual[k]) is int for k in ["tune", "draws", "chains"])
        and post.attrs.get("tuning_steps") == sampler["tune"]
        and actual
        == {
            "sampler": "nuts",
            **{k: sampler[k] for k in ["tune", "draws", "chains", "target_accept"]},
        }
        and all(
            post.sizes.get(k) == stats.sizes.get(k) == sampler[n]
            for k, n in [("chain", "chains"), ("draw", "draws")]
        )
        and post.chain.values.tolist() == list(range(4))
        and post.draw.values.tolist() == list(range(2000)),
        "genuine backend/version/protocol dimensions required",
    )
    spec = _population_spec("NCEI-native-duration", job["original_job"]["kind"])
    _require(
        set(post.data_vars) == set(spec)
        and post.scale_anchor_km.values.tolist() == [500, 2000, 5000],
        "literal six/seven explicit population variables required",
    )
    for name, (_, shape) in spec.items():
        value = post[name]
        expected = ("chain", "draw", "scale_anchor_km") if shape else ("chain", "draw")
        _require(
            value.dims == expected
            and value.dtype.kind in "iuf"
            and np.isfinite(value.values).all()
            and (name not in {"tau_event", "sigma_anchor"} or (value.values > 0).all()),
            "finite explicit real population and positive scales required",
        )
    return post


def _metadata(job, admission, lane, ids, frozen, base):
    original = job["original_job"]
    inputs = dict(
        files=admission["files"],
        source_files=frozen,
        base_prior=base,
        wider_prior=None,
        original_job=original,
        run_id=admission["gate"]["run_id"],
        source_gate=admission["gate_path"],
        comparison_review=fit.COMPARISON_REVIEW,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
    )
    membership = dict(
        training=[lane.record_ids[int(i)] for i in ids],
        omitted=original["omitted_record_ids"],
        excluded=original["excluded_record_ids"],
        target=lane.target,
        distance_mode=original["distance_mode"],
        support=original["support"],
        original_case_id=original["id"],
        prediction_scope="conditional_fitted_events_and_new_event_curves",
    )
    return inputs, membership


def fit_case(
    root: Path, job: dict[str, Any], output: Path, store: Path, gate_path: str = GATE
) -> dict[str, Any]:
    root = root.resolve()
    admission = verify_gate(root, gate_path)
    _require(
        (output, store) == case_paths(root, job, admission)
        and all(not p.exists() and p.resolve() == p for p in [output, store]),
        "new literal numerical paths required; never overwrite/retry",
    )
    lane, ids, frozen, base, model = _case(root, job, admission)
    inputs, membership = _metadata(job, admission, lane, ids, frozen, base)
    source._unchanged(root, admission["files"])
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("xb"):
        pass
    for name, value in [
        ("job.json", job),
        ("inputs.json", inputs),
        ("membership.json", membership),
    ]:
        write_json(output / name, value)
    result: dict[str, Any] = dict(
        job=job,
        original_job=job["original_job"],
        posterior=str(store.relative_to(root)),
        records=len(ids),
        events=len(set(np.asarray(lane.event_ids)[ids])),
        code_and_config=admission["files"],
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
    )
    try:
        write_json(output / "sampling-start.json", job)
        with model:
            tree = fit.pm.sample(
                **{k: v for k, v in job["sampler"].items() if k != "seed"},
                random_seed=job["sampler"]["seed"],
                progressbar=False,
            )
        tree["observed_data"] = xr.DataTree(_observed(lane, ids))
        tree.to_netcdf(store, engine="h5netcdf")
        result["posterior_sha256"] = sha256(store)
        post = _population(tree, job)
        diagnostics, table = fit.sampling_diagnostics(tree)
        write_json(output / "diagnostics.json", diagnostics)
        table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
        result["diagnostics"] = diagnostics
        result["status"] = "diagnostic_failure"
        if diagnostics.get("screen_passed") is True:
            summary = fit.summarize_posterior(
                lane,
                job["original_job"]["kind"],
                post,
                indices=ids,
                seed=job["original_job"]["seed"] + 1,
                draws=800,
            )
            write_json(output / "summary.json", summary)
            for group in TABLES:
                fit.write_table(output / (group.replace("_", "-") + ".csv"), summary[group])
            result.update(
                summary="summary.json",
                summary_sha256=sha256(output / "summary.json"),
                status="computed_pending_scientific_review"
                if fit._summary_valid(summary)
                else "summary_nonfinite_failure",
            )
        tree.close()
        source._unchanged(root, admission["files"])
    except Exception as error:
        result.update(
            status="sampling_or_evaluation_failure",
            error_type=type(error).__name__,
            error=str(error),
        )
        if store.exists() and store.stat().st_size:
            result["posterior_sha256"] = sha256(store)
    write_json(output / "result.json", result)
    return result


def case_artifacts(root, job, pins, accepted=None, gate_path=GATE) -> dict[str, Any]:
    root = root.resolve()
    admission = verify_gate(root, gate_path)
    _require(pins == admission["files"], "identical full numerical admission required")
    lane, ids, frozen, base, _ = _case(root, job, admission)
    folder, raw = case_paths(root, job, admission)
    manifest = folder / "attempt-evidence.json"
    mandatory = {
        folder / n
        for n in [*LEAVES, "summary.json", *[g.replace("_", "-") + ".csv" for g in TABLES]]
    } | {
        raw,
        *(folder.with_name(folder.name + s) for s in ["-spec.json", ".log", ".supervisor.json"]),
    }
    _require(
        all(p.is_file() and p.resolve() == p for p in mandatory),
        "complete literal numerical worker/raw/process evidence required",
    )
    initial = _inventory(root, folder, raw)
    _require(
        set(initial) == {str(p.relative_to(root)) for p in mandatory},
        "no unknown numerical files allowed",
    )
    for p in [
        folder / "job.json",
        folder / "sampling-start.json",
        folder.with_name(folder.name + "-spec.json"),
    ]:
        _require(json.loads(p.read_text()) == job, "exact execution/start/spec required")
    inputs, membership = _metadata(job, admission, lane, ids, frozen, base)
    _require(
        json.loads((folder / "inputs.json").read_text()) == inputs
        and json.loads((folder / "membership.json").read_text()) == membership,
        "unchanged original input/cohort proof required",
    )
    result = json.loads((folder / "result.json").read_text())
    process = json.loads(folder.with_name(folder.name + ".supervisor.json").read_text())
    expected = dict(
        job=job,
        original_job=job["original_job"],
        posterior=str(raw.relative_to(root)),
        posterior_sha256=sha256(raw),
        records=len(ids),
        events=len(set(np.asarray(lane.event_ids)[ids])),
        code_and_config=pins,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
        status="computed_pending_scientific_review",
        summary="summary.json",
        summary_sha256=sha256(folder / "summary.json"),
    )
    _require(
        all(result.get(k) == v for k, v in expected.items()),
        "successful exact original-model result/raw/summary binding required",
    )
    expected_process = dict(
        returncode=0,
        reason="worker_exit",
        charged_slots=1,
        start_markers=1,
        job_sha256=sha256(folder.with_name(folder.name + "-spec.json")),
        plan_sha256=pins[PLAN],
        numerical_gate_sha256=pins[gate_path],
    )
    _require(
        all(process.get(k) == v for k, v in expected_process.items())
        and not process.get("monitor_failures")
        and re.fullmatch(r"[0-9a-f]{40}", process.get("invocation_git_sha", "")) is not None,
        "single successful source-bound numerical process required",
    )
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        actual = tree["observed_data"].to_dataset()
        expected_obs = _observed(lane, ids)
        _require(
            actual.identical(expected_obs),
            "literal observed identities and native numeric arrays required",
        )
        post = _population(tree, job)
        diagnostics, table = fit.sampling_diagnostics(tree)
        _require(
            diagnostics.get("screen_passed") is True
            and diagnostics
            == result.get("diagnostics")
            == json.loads((folder / "diagnostics.json").read_text())
            and (folder / "sampling-diagnostics.csv").read_text() == table.to_csv(na_rep="unknown"),
            "complete raw diagnostics must replay",
        )
        summary = fit.summarize_posterior(
            lane,
            job["original_job"]["kind"],
            post,
            indices=ids,
            seed=job["original_job"]["seed"] + 1,
            draws=800,
        )
    _require(
        fit._summary_valid(summary)
        and summary == json.loads((folder / "summary.json").read_text()),
        "original seed+1/800 summary must replay",
    )
    for group in TABLES:
        rows = fit.csv_rows(summary[group])
        columns = list(dict.fromkeys(k for row in rows for k in row))
        expected_rows = sorted(
            [{k: row.get(k, "") for k in columns} for row in rows],
            key=lambda row: tuple(row[k] for k in columns),
        )
        _require(
            fit.read_rows(folder / (group.replace("_", "-") + ".csv")) == expected_rows,
            "all five summary CSVs must replay",
        )
    _require(_inventory(root, folder, raw) == initial, "numerical artifacts changed during replay")
    if accepted is not None:
        _require(
            accepted.get("case_id") == job["original_job"]["id"]
            and accepted.get("charged_slots") == 1
            and accepted.get("files") == initial
            and accepted.get("receipt") == str(manifest.relative_to(root))
            and accepted.get("receipt_sha256")
            == sha256(source._path(root, str(manifest.relative_to(root))))
            and json.loads(manifest.read_text())
            == {"case_id": job["original_job"]["id"], "files": initial},
            "complete immutable accepted numerical receipt required",
        )
    source._unchanged(root, pins)
    return dict(
        files=initial, manifest=manifest, result=result, posterior=raw, posterior_sha256=sha256(raw)
    )
