"""One separately reviewed numerical repair; the original failed bytes stay frozen."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from analysis.arrival import model_sensitivity_fit as fit
from analysis.arrival.evidence import read_rows, sha256, write_json

GATE = (
    "artifacts/models/arrival-timing/sensitivity-design-v1/"
    "numerical-repair-v1/review-acceptance.json"
)
CONTROL = fit.OUTPUT + "/numerical-repair-v1"
BASELINE = CONTROL + "/baseline-state.json"
FAILURE_REVIEW = CONTROL + "/diagnostic-stop-review.json"
PREFIX_REVIEW = fit.OUTPUT + "/batch-034-review-acceptance.json"
REPAIR_ID = "era-pre2007-linear-attempt-2"
ORIGINAL_ID = "ms5-ncei-distance-scale-base-era-pre2007"
OUTPUT = CONTROL + "/jobs/" + REPAIR_ID
STORE = "data/processed/models/arrival-sensitivity-repair-v1/" + REPAIR_ID + ".nc"
PLAN = fit.OUTPUT + "/plan.json"
SAMPLER: dict[str, Any] = dict(
    draws=2000,
    tune=2000,
    chains=4,
    cores=2,
    target_accept=0.99,
    nuts_sampler="nutpie",
    seed=2886144800,
)
NUTPIE_VERSION = "0.16.11"  # Pinned in the reviewed uv.lock.
CONSUMED = [
    "analysis/arrival/model_sensitivity_repair.py",
    "scripts/fit_arrival_sensitivity_repair.py",
    "tests/test_arrival_model_sensitivity_repair.py",
    *fit.CONSUMED,
]
TABLES = ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]


def _path(root, name):
    path = root / name
    if not isinstance(name, str) or Path(name).is_absolute() or path.resolve() != path:
        raise ValueError("literal project-contained nonsymlink repair path required")
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("complete existing repair input required")
    return path


def _unchanged(root, pins):
    if not pins or any(sha256(_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("reviewed repair source or original failed evidence changed")


def repair_job(original: dict[str, Any]) -> dict[str, Any]:
    if (
        original.get("id") != ORIGINAL_ID
        or original.get("order") != 34
        or original.get("target") != "NCEI-native-duration"
        or original.get("kind") != "distance-scale"
        or original.get("prior_variant") != "base"
        or original.get("seed") != SAMPLER["seed"]
    ):
        raise ValueError("only the original prespecified era-pre2007 linear job may be repaired")
    return dict(
        id=REPAIR_ID,
        role="numerical_repair",
        attempt=2,
        original_job=original,
        sampler=dict(SAMPLER),
    )


def case_paths(root: Path, job: dict[str, Any]) -> tuple[Path, Path]:
    if job != repair_job(job.get("original_job", {})):
        raise ValueError("one exact separately reviewed repair job required")
    return root / OUTPUT, root / STORE


def verify_gate(root: Path) -> dict[str, Any]:
    """Hash all admission bytes before any native loader or NetCDF reader."""
    root = root.resolve()
    gate = json.loads(_path(root, GATE).read_text())
    pins = {**gate.get("files", {}), GATE: sha256(_path(root, GATE))}
    if (
        gate.get("status") != "accepted_single_sensitivity_numerical_repair"
        or gate.get("independent_checker") is not True
        or gate.get("confirmation_outcomes_parsed") is not False
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("max_sampler_call_slots") != 110
        or gate.get("calls_charged_before") != 35
        or gate.get("new_sampler_calls") != 1
        or gate.get("path_bindings") != dict(project_root=str(root), output=OUTPUT, store=STORE)
        or gate.get("failure_review") != FAILURE_REVIEW
        or gate.get("accepted_prefix_review") != PREFIX_REVIEW
        or not set(CONSUMED) | {fit.GATE, PLAN, BASELINE, FAILURE_REVIEW, PREFIX_REVIEW}
        <= set(pins)
    ):
        raise ValueError("complete independently reviewed single numerical repair required")
    _unchanged(root, pins)
    original_admission = fit.verify_gate(root)
    if any(pins.get(p) != h for p, h in original_admission["files"].items()):
        raise ValueError("repair must retain the entire unchanged original science admission")
    original = original_admission["gate"]["jobs"][34]
    job = repair_job(original)
    if (
        gate.get("job") != job
        or gate.get("original_science_gate_sha256") != pins[fit.GATE]
        or gate.get("original_plan_sha256") != pins[PLAN]
    ):
        raise ValueError("same original job, science Gate and immutable plan required")
    baseline = json.loads(_path(root, BASELINE).read_text())
    if (
        baseline.get("next_case") != 34
        or baseline.get("calls_charged") != 35
        or baseline.get("calls_started") != 35
        or baseline.get("current") is not None
        or baseline.get("status") != "sensitivity_needs_review"
        or baseline.get("plan_sha256") != pins[PLAN]
        or len(baseline.get("accepted", [])) != 34
        or len(baseline.get("attempts", [])) != 35
    ):
        raise ValueError("immutable conserved34accepted/35charged failed-attempt baseline required")
    proof = {}
    for old, entry, attempt in zip(
        original_admission["gate"]["jobs"][:34],
        baseline["accepted"],
        baseline["attempts"][:34],
        strict=True,
    ):
        if (
            entry.get("case_id") != old["id"]
            or entry.get("charged_slots") != 1
            or attempt.get("outcome") != "accepted"
            or attempt.get("start_markers") != 1
            or any(
                attempt.get(k) != entry.get(k)
                for k in ["case_id", "charged_slots", "receipt", "receipt_sha256"]
            )
        ):
            raise ValueError("unchanged ordered original accepted prefix required")
        proof.update(entry["files"])
        proof[entry["receipt"]] = entry["receipt_sha256"]
        if json.loads(_path(root, entry["receipt"]).read_text()) != {
            "case_id": old["id"],
            "files": entry["files"],
        }:
            raise ValueError("literal original prefix attempt receipt required")
    prefix_proof = dict(proof)
    failed = baseline["attempts"][-1]
    old_folder = fit.OUTPUT + "/jobs/" + ORIGINAL_ID
    if (
        failed.get("case_id") != ORIGINAL_ID
        or failed.get("charged_slots") != 1
        or failed.get("start_markers") != 1
        or failed.get("outcome") == "accepted"
        or failed.get("receipt") != old_folder + "/attempt-evidence.json"
    ):
        raise ValueError("one retained original failed attempt required")
    failure = json.loads(_path(root, failed["receipt"]).read_text())
    old_result = old_folder + "/result.json"
    old_raw = fit.STORE + "/" + ORIGINAL_ID + ".nc"
    old_evidence = {
        *[
            old_folder + "/" + leaf
            for leaf in [
                "job.json",
                "inputs.json",
                "membership.json",
                "sampling-start.json",
                "result.json",
                "diagnostics.json",
                "sampling-diagnostics.csv",
            ]
        ],
        old_raw,
        old_folder + "-spec.json",
        old_folder + ".log",
        old_folder + ".supervisor.json",
    }
    if failure.get("case_id") != ORIGINAL_ID or not old_evidence <= set(failure.get("files", {})):
        raise ValueError("full failed worker/raw/process evidence must remain pinned")
    for name in [
        old_folder + "/job.json",
        old_folder + "/sampling-start.json",
        old_folder + "-spec.json",
    ]:
        if json.loads(_path(root, name).read_text()) != original:
            raise ValueError("literal original failed job/spec/start identity required")
    proof.update(failure["files"])
    proof[failed["receipt"]] = failed["receipt_sha256"]
    if any(pins.get(p) != h for p, h in proof.items()):
        raise ValueError("complete accepted prefix and retained failure closure required")
    result = json.loads(_path(root, old_result).read_text())
    if (
        result.get("job") != original
        or result.get("status") != "diagnostic_failure"
        or result.get("records") != 147
        or result.get("events") != 11
        or result.get("posterior") != old_raw
        or result.get("posterior_sha256") != pins[old_raw]
        or result.get("code_and_config") != original_admission["files"]
    ):
        raise ValueError("unchanged147record/11event original diagnostic failure required")
    for key in ["accepted_prefix_review", "failure_review"]:
        review = json.loads(_path(root, gate[key]).read_text())
        if (
            review.get("independent_checker") is not True
            or review.get("confirmation_outcomes_parsed") is not False
            or review.get("reserved_outcomes") != "sealed"
            or not review.get("files")
            or any(pins.get(p) != h for p, h in review["files"].items())
        ):
            raise ValueError("complete independent review closure required")
        required = (
            {**original_admission["files"], **prefix_proof}
            if key == "accepted_prefix_review"
            else {
                **original_admission["files"],
                **proof,
                PREFIX_REVIEW: pins[PREFIX_REVIEW],
                BASELINE: pins[BASELINE],
            }
        )
        if any(review["files"].get(p) != h for p, h in required.items()):
            raise ValueError("review must cover the exact accepted prefix/failure")
        if (
            key == "failure_review"
            and review.get("status") != "accepted_sensitivity_same_case_numerical_repair_plan"
        ):
            raise ValueError("accepted same-case numerical repair plan required")
        if key == "accepted_prefix_review" and (
            review.get("status") != "accepted_sensitivity_thirty_four_case_checkpoint"
            or review.get("accepted_total_cases") != 34
        ):
            raise ValueError("independently accepted thirty-four-case checkpoint required")
    _unchanged(root, pins)
    return dict(
        gate=gate, files=pins, original_admission=original_admission, original_job=original, job=job
    )


def _new_paths(root, job, output, store):
    if (output, store) != case_paths(root, job):
        raise ValueError("literal separate repair output/raw required")
    for path in [output, store]:
        if path.resolve() != path or path.exists():
            raise ValueError("new nonsymlink repair paths required; no overwrite or retry")


def _sampler_attrs(admission):
    return {
        **{k: v for k, v in SAMPLER.items()},
        "original_case_id": ORIGINAL_ID,
        "repair_case_id": REPAIR_ID,
        "repair_gate_sha256": admission["files"][GATE],
    }


def _posterior_valid(posterior, sample_stats, admission):
    # Read native sampler metadata; the worker's provenance attrs cannot certify it.
    try:
        configuration = json.loads(sample_stats.attrs["inference_library_settings"])
        settings = configuration["settings"]
        native_settings = {
            "sampler": configuration["sampler"],
            "num_tune": settings["num_tune"],
            "num_draws": settings["num_draws"],
            "num_chains": settings["num_chains"],
            "target_accept": settings["adapt_options"]["step_size_settings"]["target_accept"],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("complete original nutpie sampler metadata required") from error
    if (
        any(
            group.attrs.get("inference_library") != "nutpie"
            or group.attrs.get("inference_library_version") != NUTPIE_VERSION
            for group in [posterior, sample_stats]
        )
        or posterior.attrs.get("tuning_steps") != SAMPLER["tune"]
        or any(type(settings[key]) is not int for key in ["num_tune", "num_draws", "num_chains"])
        or native_settings
        != {
            "sampler": "nuts",
            "num_tune": SAMPLER["tune"],
            "num_draws": SAMPLER["draws"],
            "num_chains": SAMPLER["chains"],
            "target_accept": SAMPLER["target_accept"],
        }
        or sample_stats.sizes.get("chain") != SAMPLER["chains"]
        or sample_stats.sizes.get("draw") != SAMPLER["draws"]
    ):
        raise ValueError("original nutpie backend/version and approved sampler settings required")
    if (
        posterior.sizes.get("chain") != 4
        or posterior.sizes.get("draw") != 2000
        or posterior.chain.values.tolist() != list(range(4))
        or posterior.draw.values.tolist() != list(range(2000))
        or set(posterior.data_vars) != {"alpha", "beta", "tau_event", "sigma_anchor"}
        or posterior.scale_anchor_km.values.tolist() != [500, 2000, 5000]
        or any(posterior.attrs.get(k) != v for k, v in _sampler_attrs(admission).items())
    ):
        raise ValueError(
            "exact original explicit population coordinates and approved repair sampler required"
        )
    for name in posterior.data_vars:
        values = posterior[name].values
        expected = (4, 2000, 3) if name == "sigma_anchor" else (4, 2000)
        if (
            values.shape != expected
            or not np.isfinite(values).all()
            or (name in {"tau_event", "sigma_anchor"} and np.any(values <= 0))
        ):
            raise ValueError("finite positive-scale explicit population posterior required")


def _diagnostics_valid(d):
    # The frozen evaluator defines every threshold; repair introduces no new screen.
    return bool(d.get("screen_passed"))


def fit_repair(root: Path, job: dict[str, Any], output: Path, store: Path) -> dict[str, Any]:
    """One approved call; retain raw bytes before any diagnostic or summary."""
    root = root.resolve()
    _new_paths(root, job, output, store)
    admission = verify_gate(root)
    if job != admission["job"]:
        raise ValueError("exact approved repair job required")
    original, pins = admission["original_job"], admission["files"]
    lane, ids, frozen = fit._case_data(root, original, admission["original_admission"])
    if len(ids) != 147 or len({lane.event_ids[int(i)] for i in ids}) != 11:
        raise ValueError("unchanged147records/11events required")
    base, wider = fit._case_priors(root, original)
    model = fit.build_sensitivity_model(
        lane, original["kind"], base, original["prior_variant"], wider_prior=wider, indices=ids
    )
    records = [lane.record_ids[int(i)] for i in ids]
    if list(model.coords.get("record") or []) != records:
        raise ValueError("exact original training record order required")
    _unchanged(root, pins)
    _new_paths(root, job, output, store)
    output.mkdir(parents=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("xb"):
        pass
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        dict(
            files=pins,
            source_files=frozen,
            base_prior=base,
            wider_prior=wider,
            original_job=original,
            comparison_review=fit.COMPARISON_REVIEW,
            confirmation_outcomes_parsed=False,
            reserved_outcomes="sealed",
        ),
    )
    membership = dict(
        training=records,
        omitted=original["omitted_record_ids"],
        excluded=original["excluded_record_ids"],
        target=lane.target,
        distance_mode=original["distance_mode"],
        support=original["support"],
        original_case_id=ORIGINAL_ID,
        prediction_scope="conditional_fitted_events_and_new_event_curves",
    )
    write_json(output / "membership.json", membership)
    result = dict(
        job=job,
        original_job=original,
        posterior=STORE,
        records=len(ids),
        events=11,
        code_and_config=pins,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
    )
    try:
        _unchanged(root, pins)
        write_json(output / "sampling-start.json", job)
        with model:
            tree = fit.pm.sample(
                **{k: v for k, v in SAMPLER.items() if k != "seed"},
                random_seed=SAMPLER["seed"],
                progressbar=False,
            )
        tree["posterior"].attrs.update(_sampler_attrs(admission))
        tree["observed_data"] = xr.DataTree(
            xr.Dataset(
                {
                    "response": (("record",), lane.response[ids]),
                    "native_minutes": (("record",), lane.y[ids]),
                    "distance_km": (("record",), lane.distance_km[ids]),
                    "reference_minutes": (("record",), lane.reference_minutes[ids]),
                    **{
                        name: (("record",), [values[int(i)] for i in ids])
                        for name, values in [
                            ("event_id", lane.event_ids),
                            ("sequence", lane.sequences),
                            ("site_id", lane.site_ids),
                        ]
                    },
                },
                coords={"record": records},
                attrs=dict(target=lane.target, scope="literal_case_training_only"),
            )
        )
        tree.to_netcdf(store, engine="h5netcdf")
        result["posterior_sha256"] = sha256(store)
        posterior = tree["posterior"].to_dataset()
        _posterior_valid(posterior, tree["sample_stats"].to_dataset(), admission)
        diagnostics, table = fit.sampling_diagnostics(tree)
        table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
        write_json(output / "diagnostics.json", diagnostics)
        result["diagnostics"] = diagnostics
        if not _diagnostics_valid(diagnostics):
            result["status"] = "diagnostic_failure"
        else:
            summary = fit.summarize_posterior(
                lane, original["kind"], posterior, indices=ids, seed=original["seed"] + 1, draws=800
            )
            json.dumps(summary, allow_nan=False)
            write_json(output / "summary.json", summary)
            result.update(summary="summary.json", summary_sha256=sha256(output / "summary.json"))
            for group in TABLES:
                fit.write_table(output / (group.replace("_", "-") + ".csv"), summary[group])
            result["status"] = (
                "computed_pending_scientific_review"
                if fit._summary_valid(summary)
                else "summary_nonfinite_failure"
            )
        _unchanged(root, pins)
    except Exception as exc:
        result.update(
            status="sampling_or_evaluation_failure", error_type=type(exc).__name__, error=str(exc)
        )
        if store.stat().st_size:
            result["posterior_sha256"] = sha256(store)
        try:
            _unchanged(root, pins)
        except Exception:
            result["status"] = "source_identity_failure"
    write_json(output / "result.json", result)
    return result


def case_artifacts(
    root: Path, job: dict[str, Any], pins: dict[str, str], accepted=None
) -> dict[str, Any]:
    """Replay raw diagnostics and every seeded summary/CSV before accepting a repair."""
    root = root.resolve()
    admission = verify_gate(root)
    if admission["files"] != pins or admission["job"] != job:
        raise ValueError("identical complete repair admission required")
    original = admission["original_job"]
    lane, ids, frozen = fit._case_data(root, original, admission["original_admission"])
    folder, raw = case_paths(root, job)
    manifest = folder / "attempt-evidence.json"
    spec, log, supervisor = [
        folder.with_name(folder.name + suffix)
        for suffix in ["-spec.json", ".log", ".supervisor.json"]
    ]
    names = [
        "job.json",
        "inputs.json",
        "membership.json",
        "sampling-start.json",
        "result.json",
        "diagnostics.json",
        "sampling-diagnostics.csv",
        "summary.json",
        *[group.replace("_", "-") + ".csv" for group in TABLES],
    ]
    mandatory = [folder / name for name in names] + [raw, spec, log, supervisor]

    def inventory():
        paths = set(mandatory)
        for p in folder.rglob("*"):
            if p.is_symlink() or p.resolve() != p:
                raise ValueError("repair artifacts must remain literal nonsymlink paths")
            if p.is_file() and p != manifest:
                if p not in mandatory:
                    raise ValueError("unlisted repair artifact requires independent review")
                paths.add(p)
        return {
            str(p.relative_to(root)): sha256(_path(root, str(p.relative_to(root)))) for p in paths
        }

    initial = inventory()
    for p in [folder / "job.json", folder / "sampling-start.json", spec]:
        if json.loads(p.read_text()) != job:
            raise ValueError("literal repair job/spec/single start marker required")
    if list(folder.glob("sampling-start*.json")) != [folder / "sampling-start.json"]:
        raise ValueError("exactly one repair sampling start required")
    base, wider = fit._case_priors(root, original)
    expected_inputs = dict(
        files=pins,
        source_files=frozen,
        base_prior=base,
        wider_prior=wider,
        original_job=original,
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
        original_case_id=ORIGINAL_ID,
        prediction_scope="conditional_fitted_events_and_new_event_curves",
    )
    if (
        json.loads((folder / "inputs.json").read_text()) != expected_inputs
        or json.loads((folder / "membership.json").read_text()) != membership
    ):
        raise ValueError("unchanged source/native membership and prior proof required")
    result = json.loads((folder / "result.json").read_text())
    expected_result = dict(
        job=job,
        original_job=original,
        posterior=STORE,
        records=147,
        events=11,
        code_and_config=pins,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        scoring_or_forecast_imputation=False,
        status="computed_pending_scientific_review",
        summary="summary.json",
        summary_sha256=sha256(folder / "summary.json"),
        posterior_sha256=sha256(raw),
    )
    if any(result.get(k) != v for k, v in expected_result.items()):
        raise ValueError("complete source-bound successful repair result required")
    process = json.loads(supervisor.read_text())
    if any(
        process.get(k) != v
        for k, v in dict(
            returncode=0,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec),
            plan_sha256=pins[PLAN],
            repair_gate_sha256=pins[GATE],
        ).items()
    ) or process.get("monitor_failures"):
        raise ValueError("successful separately charged repair process proof required")
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        observed = tree["observed_data"].to_dataset()
        if observed.record.values.tolist() != membership["training"] or observed.attrs != dict(
            target=lane.target, scope="literal_case_training_only"
        ):
            raise ValueError("exact native observed record order/target required")
        for name, values in [
            ("response", lane.response),
            ("native_minutes", lane.y),
            ("distance_km", lane.distance_km),
            ("reference_minutes", lane.reference_minutes),
        ]:
            np.testing.assert_array_equal(observed[name].values, values[ids])
        for name, values in [
            ("event_id", lane.event_ids),
            ("sequence", lane.sequences),
            ("site_id", lane.site_ids),
        ]:
            if observed[name].values.tolist() != [values[int(i)] for i in ids]:
                raise ValueError("exact native event/sequence/site identity required")
        posterior = tree["posterior"].to_dataset()
        _posterior_valid(posterior, tree["sample_stats"].to_dataset(), admission)
        diagnostics, table = fit.sampling_diagnostics(tree)
        if (
            not _diagnostics_valid(diagnostics)
            or diagnostics != result.get("diagnostics")
            or diagnostics != json.loads((folder / "diagnostics.json").read_text())
            or (folder / "sampling-diagnostics.csv").read_text() != table.to_csv(na_rep="unknown")
        ):
            raise ValueError("replayed strict original numerical diagnostic policy required")
        summary = fit.summarize_posterior(
            lane, original["kind"], posterior, indices=ids, seed=original["seed"] + 1, draws=800
        )
    if not fit._summary_valid(summary) or summary != json.loads(
        (folder / "summary.json").read_text()
    ):
        raise ValueError("replayed originalseed+1/800 same-cohort summary required")
    for group in TABLES:
        rows = fit.csv_rows(summary[group])
        columns = list(dict.fromkeys(k for row in rows for k in row))
        expected = [{k: row.get(k, "") for k in columns} for row in rows]
        expected.sort(key=lambda row: tuple(row[k] for k in columns))
        if read_rows(folder / (group.replace("_", "-") + ".csv")) != expected:
            raise ValueError("all repair CSVs must replay from the retained raw posterior")
    files = inventory()
    if files != initial:
        raise ValueError("repair artifacts changed during semantic replay")
    if accepted is not None and (
        accepted.get("case_id") != ORIGINAL_ID
        or accepted.get("charged_slots") != 1
        or accepted.get("files") != files
        or accepted.get("receipt") != str(manifest.relative_to(root))
        or accepted.get("receipt_sha256") != sha256(_path(root, str(manifest.relative_to(root))))
        or json.loads(manifest.read_text()) != {"case_id": ORIGINAL_ID, "files": files}
    ):
        raise ValueError("complete immutable separately charged repair receipt required")
    _unchanged(root, pins)
    return dict(
        files=files, manifest=manifest, result=result, posterior=raw, posterior_sha256=sha256(raw)
    )
