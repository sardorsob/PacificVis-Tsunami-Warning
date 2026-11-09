"""One prospectively admitted frozen development fit or zero-call check evaluation.

Only the serial Root controller authorizes calls and owns budgets. This worker
retains failed computations, never augments or retunes, and saves raw draws before
any diagnostics. The 19-event set is an already-inspected development check.
"""

# pyright: basic
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pymc as pm
import xarray as xr

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_references as references
from analysis.arrival.evidence import read_rows, sha256, write_json
from analysis.arrival.model_development_predictions import new_event_predictions
from analysis.arrival.model_development_scoring import (
    aggregate_shared_training_events,
    direct_event_score,
    event_loglikelihood,
)
from analysis.arrival.model_sensitivity_fit import CONSUMED as S5_CONSUMED
from analysis.arrival.model_sensitivity_fit import _summary_valid
from analysis.arrival.model_sensitivity_priors import (
    T4_MATCHED_SCALE,
    _population_spec,
    _prior_settings,
    build_sensitivity_model,
)
from analysis.arrival.model_sensitivity_summary import _validated, summarize_posterior
from analysis.arrival.model_validation import sampling_diagnostics
from analysis.arrival.model_validation_report import csv_rows, write_table

GATE = data.ART + "development-design-v1/review-acceptance.json"
FULL_GATE = data.ART + "full-development-design-v1/review-acceptance.json"
CHECK_OUTPUT = data.ART + "development-check-v1"
FULL_OUTPUT = data.ART + "full-development-v1"
STORE = "data/processed/models/arrival-development-v1"
SUCCESS = "computed_pending_scientific_review"
ROLES = {"check_training", "check_evaluate", "full_development"}
FIT_FILES = {
    "job.json",
    "inputs.json",
    "membership.json",
    "result.json",
    "prior-settings.json",
    "sampling-start.json",
    "diagnostics.json",
    "sampling-diagnostics.csv",
}
CONSUMED = tuple(
    sorted(
        set(data.CONSUMED)
        | set(references.CONSUMED)
        | set(S5_CONSUMED)
        | {
            "analysis/arrival/model_development_fit.py",
            "scripts/fit_arrival_development.py",
            "tests/test_arrival_model_development_fit.py",
            "analysis/arrival/model_development_scoring.py",
            "analysis/arrival/model_development_predictions.py",
        }
    )
)


def resources():
    mib = 1024**2
    return dict(
        global_max_bytes=3072 * mib,
        local_max_bytes=2048 * mib,
        cache_max_bytes=256 * mib,
        job_max_bytes=32 * mib,
        file_max_bytes=64 * mib,
        next_invocation_reserve_bytes=608 * mib,
        timeout_seconds=600,
        watcher_seconds=0.1,
        chains=4,
        cores=2,
        draws=2000,
        tune=1000,
    )


def case_paths(root: Path, job: dict[str, Any]) -> tuple[Path, Path | None]:
    if job.get("role") not in ROLES:
        raise ValueError(
            "only frozen training/evaluation/full roles; augmentation is not implemented"
        )
    name = job.get("id")
    if (
        not isinstance(name, str)
        or re.fullmatch(r"dev-[a-z0-9][a-z0-9.-]*", name) is None
        or ".." in name
    ):
        raise ValueError("bounded literal development job ID required")
    base = FULL_OUTPUT if job["role"] == "full_development" else CHECK_OUTPUT
    return root / base / "jobs" / name, None if job[
        "role"
    ] == "check_evaluate" else root / STORE / (name + ".nc")


def verify_gate(root: Path, role: str):
    if role not in ROLES:
        raise ValueError("augmentation and unknown development roles are not implemented")
    name = FULL_GATE if role == "full_development" else GATE
    gate = json.loads(data._path(root, name).read_text())
    if (
        gate.get("status") != "accepted_frozen_arrival_development_execution"
        or gate.get("independent_checker") is not True
        or gate.get("specification_freeze") != data.FREEZE
        or gate.get("reserved_outcomes") != "sealed"
        or gate.get("no_retuning_after_development_check") is not True
        or gate.get("crossing_policy") != "uniform_purge_all_check_sequences"
        or gate.get("resources") != resources()
        or type(gate.get("max_sampler_call_slots")) is not int
        or gate["max_sampler_call_slots"] < 1
    ):
        raise ValueError("accepted prospective frozen development execution/resources required")
    files = gate.get("files", {})
    if not set(CONSUMED) | {data.FREEZE} <= set(files):
        raise ValueError("full development worker/source closure required before loading")
    pins = {**files, name: sha256(root / name)}
    data._unchanged(root, pins)
    if gate.get("specification_freeze_sha256") != pins[data.FREEZE]:
        raise ValueError("execution gate must bind this exact scientific freeze")
    freeze, _, _, _ = data.verify_development_sources(root, pins, full=role == "full_development")
    specs = {
        f"{target}:{spec['kind']}:{spec['role']}": (target, spec)
        for target, entries in freeze["models"].items()
        for spec in entries
    }
    jobs = gate.get("jobs")
    if not isinstance(jobs, list) or not jobs or len({j.get("id") for j in jobs}) != len(jobs):
        raise ValueError("exact nonempty distinct prospective job list required")
    allowed = (
        {"full_development"} if role == "full_development" else {"check_training", "check_evaluate"}
    )
    for order, job in enumerate(jobs):
        if (
            set(job) != {"id", "order", "role", "model_key", "seed", "training_reference"}
            or type(job["order"]) is not int
            or job["order"] != order
            or job["role"] not in allowed
            or job["model_key"] not in specs
            or type(job["seed"]) is not int
            or not 0 <= job["seed"] < 2**32 - 1
        ):
            raise ValueError("exact ordered frozen role/model/uint32 seed jobs required")
        case_paths(root, job)
        ref = job["training_reference"]
        if job["role"] != "check_evaluate":
            if (
                ref is not None
                or job["role"] == "full_development"
                and specs[job["model_key"]][1]["role"] != "selected"
            ):
                raise ValueError("fit job has no reference; full57 selected specs only")
        elif not isinstance(ref, dict) or (
            ref != {"kind": "historical"}
            and (set(ref) != {"kind", "job_id", "review"} or ref["kind"] != "new_fit")
        ):
            raise ValueError(
                "explicit historical or prospectively named new training reference required"
            )
    if sum(j["role"] != "check_evaluate" for j in jobs) > gate["max_sampler_call_slots"]:
        raise ValueError("prospective calls exceed the Root-reviewed ceiling")
    return dict(gate=gate, files=pins, freeze=freeze, specs=specs)


def _new_paths(root, job, output, store):
    expected = case_paths(root, job)
    if (output, store) != expected:
        raise ValueError("exact canonical role/job output and raw path binding required")
    for path in expected:
        if path is not None and (path.resolve() != path or path.exists()):
            raise ValueError("new nonsymlink development paths required; preserve every attempt")


def _priors(root, target, spec):
    reader = (
        data.read_curvature_prior
        if spec["kind"] == "mean-curvature"
        else lambda r, v: data.read_prior(r, target, v)
    )
    base = reader(root, "base")
    wider = (
        reader(root, spec["prior_variant"] if spec["kind"] == "mean-curvature" else "wider")
        if spec["prior_variant"] in {"joint_wider", "gamma_wider_only"}
        else None
    )
    active = {key for key, _ in _population_spec(target, spec["kind"]).values()}
    if {key: base[key] for key in active} != spec["base_prior_sd"] or (
        None if wider is None else {key: wider[key] for key in active}
    ) != spec["wider_prior_sd"]:
        raise ValueError("complete prior readers must reproduce frozen active SDs")
    family, scales = _prior_settings(spec["kind"], base, spec["prior_variant"], wider)
    expected = dict(spec["base_prior_sd"])
    variant = spec["prior_variant"]
    if variant == "joint_wider":
        expected = dict(spec["wider_prior_sd"])
    elif variant == "gamma_wider_only":
        expected["gamma_sd"] = spec["wider_prior_sd"]["gamma_sd"]
    elif variant.startswith("power_"):
        expected = {
            key: value / np.sqrt(float(variant.split("_")[1])) for key, value in expected.items()
        }
    elif variant == "t4_matched":
        expected = {key: value * T4_MATCHED_SCALE for key, value in expected.items()}
    if expected != {key: scales[key] for key in active}:
        raise ValueError("effective prior distribution scales differ from the frozen specification")
    return base, wider, dict(family=family, distribution_scales=scales)


def _observed(lane, ids, role):
    return xr.Dataset(
        {
            name: ("record", values)
            for name, values in {
                "response": lane.response[ids],
                "native_minutes": lane.y[ids],
                "distance_km": lane.distance_km[ids],
                "reference_minutes": lane.reference_minutes[ids],
                "event_id": np.asarray(lane.event_ids)[ids],
                "sequence": np.asarray(lane.sequences)[ids],
                "site_id": np.asarray(lane.site_ids)[ids],
            }.items()
        },
        coords={"record": [lane.record_ids[int(i)] for i in ids]},
        attrs={"target": lane.target, "role": role},
    )


def _read_population(root, raw, lane, ids, kind):
    with xr.open_dataset(raw, group="observed_data", engine="h5netcdf") as observed:
        expected = _observed(lane, ids, "check_training")
        if (
            observed.record.values.tolist() != expected.record.values.tolist()
            or set(observed.data_vars) != set(expected.data_vars)
            or any(
                not np.array_equal(observed[name].values, expected[name].values)
                for name in expected.data_vars
            )
        ):
            raise ValueError("new training raw must match all literal native/source arrays")
    with xr.open_dataset(raw, group="posterior", engine="h5netcdf") as saved:
        if (
            saved.sizes.get("chain") != 4
            or saved.sizes.get("draw") != 2000
            or "nutpie" not in str(saved.attrs).lower()
        ):
            raise ValueError("original4chain2000draw nutpie posterior required")
        hyper, _ = _validated(lane, kind, saved, ids, 0, 800)
        return saved[list(hyper)].load()


def _training_reference(root, job, lane, admission):
    ref = job["training_reference"]
    if ref["kind"] == "historical":
        post, proof = references.load_frozen_training_reference(
            root, job["model_key"], lane, admission["files"]
        )
        return post, proof, admission["files"]
    parents = [
        j
        for j in admission["gate"]["jobs"]
        if j["id"] == ref["job_id"]
        and j["role"] == "check_training"
        and j["model_key"] == job["model_key"]
    ]
    if len(parents) != 1:
        raise ValueError(
            "new reference must be an exact prospectively declared same-model training job"
        )
    parent = parents[0]
    folder, raw = case_paths(root, parent)
    if raw is None:
        raise ValueError("declared parent must retain a training posterior")
    review_name = str((folder / "review-acceptance.json").relative_to(root))
    if ref["review"] != review_name:
        raise ValueError("literal parent training review path required")
    review = json.loads(data._path(root, review_name).read_text())
    if (
        review.get("status") != "accepted_frozen_development_training_posterior"
        or review.get("independent_checker") is not True
        or review.get("specification_freeze_sha256") != admission["files"][data.FREEZE]
        or review.get("model_key") != job["model_key"]
        or review.get("job_id") != parent["id"]
    ):
        raise ValueError("independently accepted exact new training posterior required")
    added = review.get("files", {})
    if not added or any(
        name in admission["files"] and admission["files"][name] != digest
        for name, digest in added.items()
    ):
        raise ValueError("new training closure conflicts with frozen execution sources")
    data._require(added, admission["files"])
    pins = {**admission["files"], **added, review_name: sha256(root / review_name)}
    data._unchanged(root, pins)
    required = {
        str((folder / name).relative_to(root)) for name in FIT_FILES | {"output-checksums.json"}
    } | {str(raw.relative_to(root))}
    if not required <= set(added):
        raise ValueError("complete accepted new training artifact closure required before NC")
    result = json.loads((folder / "result.json").read_text())
    inputs = json.loads((folder / "inputs.json").read_text())
    membership = json.loads((folder / "membership.json").read_text())
    manifest = json.loads((folder / "output-checksums.json").read_text())
    if not FIT_FILES <= set(manifest):
        raise ValueError("complete accepted parent fit inventory required before NC")
    data._require(
        added, {str((folder / name).relative_to(root)): digest for name, digest in manifest.items()}
    )
    ids = np.flatnonzero(lane.included)
    if (
        result.get("status") != SUCCESS
        or result.get("confirmation_outcomes_parsed") is not True
        or result.get("reserved_outcomes") != "sealed"
        or result.get("job") != parent
        or result.get("posterior") != str(raw.relative_to(root))
        or result.get("posterior_sha256") != pins[str(raw.relative_to(root))]
        or json.loads((folder / "job.json").read_text()) != parent
        or inputs.get("model_spec") != admission["specs"][job["model_key"]][1]
        or not result.get("diagnostics", {}).get("screen_passed")
        or membership.get("training_record_ids") != [lane.record_ids[int(i)] for i in ids]
    ):
        raise ValueError("accepted training result/job/raw/membership identity required")
    if inputs.get("files") != admission["files"]:
        raise ValueError("complete exact recorded execution admission required before NC")
    parent_case = case_artifacts(root, parent, pins)
    data._require(added, parent_case["files"])
    post = _read_population(root, raw, lane, ids, admission["specs"][job["model_key"]][1]["kind"])
    data._unchanged(root, pins)
    return (
        post,
        dict(
            raw=str(raw.relative_to(root)),
            raw_sha256=pins[str(raw.relative_to(root))],
            review=review_name,
            review_sha256=pins[review_name],
        ),
        pins,
    )


def _evaluate(root, output, lane, held, spec, post, proof, *, verify=False):
    events: list[dict[str, Any]] = []
    scores, predictions = [], []
    arrays: dict[str, Any] = {}
    expected = sorted(
        {event for event, keep in zip(held.event_ids, held.included, strict=True) if keep}
    )
    support = [
        float(lane.distance_km[lane.included].min()),
        float(lane.distance_km[lane.included].max()),
    ]
    for order, event in enumerate(expected):
        ids = np.flatnonzero(held.included & (np.asarray(held.event_ids) == event))
        entry: dict[str, Any] = dict(
            event_id=event, record_ids=[held.record_ids[int(i)] for i in ids]
        )
        try:
            logl, _ = event_loglikelihood(held, ids, spec["kind"], post)
            arrays[f"event_{order:03d}_native_loglikelihood"] = logl.values
            score = direct_event_score(logl, records=len(ids))
            arrays[f"event_{order:03d}_joint_influence"] = score["joint_influence"].values
            scores.append(score)
            entry["score"] = {
                key: value for key, value in score.items() if key != "joint_influence"
            }
        except (ValueError, FloatingPointError, OverflowError) as error:
            entry["score"] = dict(
                status="needs_numerical_review", error_type=type(error).__name__, error=str(error)
            )
        try:
            rows, metadata = new_event_predictions(
                held, ids, spec["kind"], post, training_distance_range_km=support
            )
            predictions.extend(rows)
            entry["predictions"] = metadata
        except (ValueError, FloatingPointError, OverflowError) as error:
            entry["predictions"] = dict(
                status="needs_numerical_review", error_type=type(error).__name__, error=str(error)
            )
        events.append(entry)
    aggregate: dict[str, Any]
    try:
        aggregate = (
            aggregate_shared_training_events(scores, proof["raw_sha256"])
            if len(scores) == len(expected)
            else dict(
                status="needs_numerical_review",
                events=len(expected),
                numerical_failures=["event_evaluation_failure"],
            )
        )
    except (ValueError, FloatingPointError, OverflowError) as error:
        aggregate = dict(
            status="needs_numerical_review",
            events=len(expected),
            numerical_failures=["aggregate_evaluation_failure"],
            error=str(error),
        )
    if "shared_influence" in aggregate:
        arrays["aggregate_shared_influence"] = aggregate.pop("shared_influence").values
    arrays.update(chain_coordinates=post.chain.values, draw_coordinates=post.draw.values)
    event_results = {"expected_event_ids": expected, "events": events, "aggregate": aggregate}
    if verify:
        if json.loads((output / "event-results.json").read_text()) != event_results:
            raise ValueError("frozen direct-score results must replay from original training draws")
        with np.load(output / "direct-score-arrays.npz", allow_pickle=False) as saved:
            if set(saved.files) != set(arrays) or any(
                not np.array_equal(saved[key], value) for key, value in arrays.items()
            ):
                raise ValueError("labelled direct-score arrays differ from frozen replay")
        expected_rows = {row["record_id"]: row for row in csv_rows(predictions)}
        actual = read_rows(output / "held-out-record-predictions.csv")
        if (
            len(actual) != len(expected_rows)
            or {row["record_id"]: row for row in actual} != expected_rows
        ):
            raise ValueError("original frozen new-event prediction rows must replay")
    else:
        np.savez_compressed(output / "direct-score-arrays.npz", **arrays)
        write_json(output / "event-results.json", event_results)
        if predictions:
            write_table(output / "held-out-record-predictions.csv", predictions)
    passed = (
        aggregate["status"] == "computed_pending_review"
        and len(predictions) == int(held.included.sum())
        and all(e["predictions"]["status"] == "computed_pending_review" for e in events)
    )
    return dict(
        status=SUCCESS if passed else "needs_numerical_review",
        aggregate=aggregate,
        expected_events=len(expected),
        prediction_rows=len(predictions),
        training_reference=proof,
    )


def _manifest(output):
    write_json(
        output / "output-checksums.json",
        {
            path.name: sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
            and path.name not in {"output-checksums.json", "review-acceptance.json"}
        },
    )


def _replay_table(path, rows):
    expected = csv_rows(rows)
    columns = list(dict.fromkeys(key for row in expected for key in row))
    expected = [{key: row.get(key, "") for key in columns} for row in expected]
    expected = sorted(expected, key=lambda row: tuple(row.get(key, "") for key in columns))
    if read_rows(path) != expected:
        raise ValueError(
            f"deterministic posterior summary CSV differs from raw replay: {path.name}"
        )


def _replay_fit(root, output, raw, lane, ids, spec, job, result):
    base, wider, settings = _priors(root, lane.target, spec)
    if json.loads((output / "prior-settings.json").read_text()) != dict(
        base_prior=base, wider_prior=wider, **settings
    ):
        raise ValueError("frozen complete prior settings must replay")
    if json.loads((output / "sampling-start.json").read_text()) != job:
        raise ValueError("literal original sampling-start job required")
    post = _read_population(root, raw, lane, ids, spec["kind"])
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        diagnostics, table = sampling_diagnostics(tree)
    if (
        diagnostics.get("screen_passed") is not True
        or result.get("diagnostics") != diagnostics
        or json.loads((output / "diagnostics.json").read_text()) != diagnostics
    ):
        raise ValueError("sampling diagnostics must replay from retained raw data")
    if (output / "sampling-diagnostics.csv").read_text() != table.to_csv(na_rep="unknown"):
        raise ValueError("sampling diagnostic CSV must replay from retained raw data")
    if job["role"] == "full_development":
        summary = summarize_posterior(
            lane, spec["kind"], post, indices=ids, seed=job["seed"] + 1, draws=800
        )
        if (
            not _summary_valid(summary)
            or json.loads((output / "summary.json").read_text()) != summary
        ):
            raise ValueError("seeded800-draw full posterior summary must replay from raw data")
        for name in ["parameters", "derived", "curves", "conditional_ppc", "record_intervals"]:
            _replay_table(output / (name.replace("_", "-") + ".csv"), summary[name])


def run_development_job(root: Path, job: dict[str, Any], output: Path, store: Path | None = None):
    root = root.resolve()
    _new_paths(root, job, output, store)
    admission = verify_gate(root, job["role"])
    if job not in admission["gate"]["jobs"]:
        raise ValueError("job must match an exact prospective execution entry")
    target, spec = admission["specs"][job["model_key"]]
    pins = admission["files"]
    output.mkdir(parents=True)
    write_json(output / "job.json", job)
    write_json(
        output / "inputs.json",
        dict(files=pins, specification_freeze_sha256=pins[data.FREEZE], model_spec=spec),
    )
    result: dict[str, Any] = dict(
        job=job,
        status="worker_failure",
        confirmation_outcomes_parsed=None,
        reserved_outcomes="sealed",
        sampler_call_started=False,
        scoring_performed=False,
    )
    raw_saved = False
    try:
        views = (
            data.load_full_development_lanes(root, pins)
            if job["role"] == "full_development"
            else data.load_check_lanes(root, pins)
        )
        result["confirmation_outcomes_parsed"] = True
        lane = (
            views["combined"][target]
            if job["role"] == "full_development"
            else views["training_purged"][target]
        )
        ids = np.flatnonzero(lane.included)
        write_json(
            output / "membership.json",
            {
                **views["membership"][target],
                "training_record_ids": [lane.record_ids[int(i)] for i in ids],
                "model_key": job["model_key"],
            },
        )
        if job["role"] == "check_evaluate":
            post, proof, pins = _training_reference(root, job, lane, admission)
            result.update(
                _evaluate(root, output, lane, views["check"][target], spec, post, proof),
                scoring_performed=True,
            )
        else:
            if store is None:
                raise ValueError("fit role requires its canonical raw store")
            base, wider, settings = _priors(root, target, spec)
            write_json(
                output / "prior-settings.json", dict(base_prior=base, wider_prior=wider, **settings)
            )
            model = build_sensitivity_model(
                lane, spec["kind"], base, spec["prior_variant"], wider_prior=wider, indices=ids
            )
            if list(model.coords.get("record") or []) != [lane.record_ids[int(i)] for i in ids]:
                raise ValueError(
                    "model graph must contain only literal designated training records"
                )
            data._unchanged(root, pins)
            store.parent.mkdir(parents=True, exist_ok=True)
            with store.open("xb"):
                pass
            write_json(output / "sampling-start.json", job)
            result["sampler_call_started"] = True
            with model:
                tree = pm.sample(
                    draws=2000,
                    tune=1000,
                    chains=4,
                    cores=2,
                    target_accept=0.95,
                    nuts_sampler="nutpie",
                    random_seed=job["seed"],
                    progressbar=False,
                )
            tree["observed_data"] = xr.DataTree(_observed(lane, ids, job["role"]))
            tree.to_netcdf(store, engine="h5netcdf")
            raw_saved = True
            result.update(posterior=str(store.relative_to(root)), posterior_sha256=sha256(store))
            diagnostics, table = sampling_diagnostics(tree)
            table.to_csv(output / "sampling-diagnostics.csv", na_rep="unknown")
            write_json(output / "diagnostics.json", diagnostics)
            result["diagnostics"] = diagnostics
            post = tree["posterior"].to_dataset()
            _validated(lane, spec["kind"], post, ids, 0, 800)
            numeric = (
                diagnostics.get("screen_passed") is True
                and post.sizes.get("chain") == 4
                and post.sizes.get("draw") == 2000
                and "nutpie" in str(post.attrs).lower()
            )
            result["status"] = SUCCESS if numeric else "needs_numerical_review"
            if numeric and job["role"] == "full_development":
                summary = summarize_posterior(
                    lane, spec["kind"], post, indices=ids, seed=job["seed"] + 1, draws=800
                )
                json.dumps(summary, allow_nan=False)
                write_json(output / "summary.json", summary)
                for name in [
                    "parameters",
                    "derived",
                    "curves",
                    "conditional_ppc",
                    "record_intervals",
                ]:
                    write_table(output / (name.replace("_", "-") + ".csv"), summary[name])
                if not _summary_valid(summary):
                    result["status"] = "needs_numerical_review"
            tree.close()
        data._unchanged(root, pins)
    except Exception as error:
        result.update(status="worker_failure", error_type=type(error).__name__, error=str(error))
        if raw_saved and isinstance(error, (ValueError, FloatingPointError, OverflowError)):
            result["status"] = "needs_numerical_review"
        if store is not None and store.exists() and store.stat().st_size:
            result.update(posterior=str(store.relative_to(root)), posterior_sha256=sha256(store))
        try:
            data._unchanged(root, pins)
        except Exception:
            result["status"] = "source_identity_failure"
    write_json(output / "result.json", result)
    _manifest(output)
    return result


def case_artifacts(root: Path, job, pins, accepted=None) -> dict[str, Any]:
    """Read-only closed inventory for independent review/controller accounting."""
    admission = verify_gate(root, job["role"])
    data._require(pins, admission["files"])
    if job not in admission["gate"]["jobs"]:
        raise ValueError("exact prospectively declared job required")
    output, raw = case_paths(root, job)
    names = json.loads(
        data._path(root, str((output / "output-checksums.json").relative_to(root))).read_text()
    )
    required = {"job.json", "inputs.json", "membership.json", "result.json"}
    required |= (
        {"event-results.json", "direct-score-arrays.npz", "held-out-record-predictions.csv"}
        if raw is None
        else {
            "prior-settings.json",
            "sampling-start.json",
            "diagnostics.json",
            "sampling-diagnostics.csv",
        }
    )
    if job["role"] == "full_development":
        required |= {
            "summary.json",
            "parameters.csv",
            "derived.csv",
            "curves.csv",
            "conditional-ppc.csv",
            "record-intervals.csv",
        }
    if not required <= set(names):
        raise ValueError("complete role-specific result artifacts required")
    files = {str((output / name).relative_to(root)): digest for name, digest in names.items()}
    files[str((output / "output-checksums.json").relative_to(root))] = sha256(
        output / "output-checksums.json"
    )
    data._unchanged(root, files)
    result = json.loads((output / "result.json").read_text())
    inputs = json.loads((output / "inputs.json").read_text())
    if inputs.get("files") != admission["files"]:
        raise ValueError("complete exact recorded execution admission required")
    spec = admission["specs"][job["model_key"]][1]
    if (
        inputs.get("model_spec") != spec
        or inputs.get("specification_freeze_sha256") != admission["files"][data.FREEZE]
    ):
        raise ValueError("same frozen model/input provenance required")
    if (
        result.get("job") != job
        or result.get("status") != SUCCESS
        or result.get("confirmation_outcomes_parsed") is not True
        or result.get("reserved_outcomes") != "sealed"
        or json.loads((output / "job.json").read_text()) != job
    ):
        raise ValueError("successful frozen job/source-scope identity required")
    if raw is not None:
        if (
            result.get("posterior") != str(raw.relative_to(root))
            or result.get("posterior_sha256") != sha256(raw)
            or result.get("diagnostics", {}).get("screen_passed") is not True
        ):
            raise ValueError("complete retained raw posterior/diagnostics required")
        files[str(raw.relative_to(root))] = sha256(raw)
        views = (
            data.load_full_development_lanes(root, pins)
            if job["role"] == "full_development"
            else data.load_check_lanes(root, pins)
        )
        target = admission["specs"][job["model_key"]][0]
        lane = (
            views["combined"][target]
            if job["role"] == "full_development"
            else views["training_purged"][target]
        )
        ids = np.flatnonzero(lane.included)
        membership = json.loads((output / "membership.json").read_text())
        if (
            membership.get("training_record_ids") != [lane.record_ids[int(i)] for i in ids]
            or json.loads((output / "diagnostics.json").read_text()) != result["diagnostics"]
        ):
            raise ValueError("literal native membership and diagnostic metadata required")
        _replay_fit(root, output, raw, lane, ids, spec, job, result)
    else:
        views = data.load_check_lanes(root, pins)
        target = admission["specs"][job["model_key"]][0]
        lane = views["training_purged"][target]
        post, proof, source_pins = _training_reference(root, job, lane, admission)
        replay = _evaluate(
            root, output, lane, views["check"][target], spec, post, proof, verify=True
        )
        if any(result.get(key) != value for key, value in replay.items()):
            raise ValueError("successful evaluation/source-reference result must replay")
        data._unchanged(root, source_pins)
    if accepted is not None and accepted.get("files") != files:
        raise ValueError("immutable accepted artifact inventory changed")
    data._unchanged(root, {**admission["files"], **files})
    return dict(
        files=files,
        result=str((output / "result.json").relative_to(root)),
        posterior=result.get("posterior"),
        posterior_sha256=result.get("posterior_sha256"),
        role=job["role"],
    )
