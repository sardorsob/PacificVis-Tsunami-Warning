"""Bounded two-scale Gaussian normalizers for one held event in a purged sequence."""

# pyright: basic
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_cv import _read_ensemble, verify_bridge_gate
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_event_cubature import event_models, normalized_target
from analysis.arrival.model_exhausted_cubature import verify_exhausted
from analysis.arrival.model_normalizer import PositiveProposal, integrate_positive
from analysis.arrival.model_scaled_cubature import CONSUMED as SCALED_CONSUMED
from analysis.arrival.model_scaled_cubature import retained_tensor
from analysis.arrival.models import read_prior

CONSUMED = sorted(
    set(
        [
            *SCALED_CONSUMED,
            "analysis/arrival/model_exhausted_cubature.py",
            "scripts/run_arrival_model_validation.py",
            "config/arrival-model-contract-v1.toml",
            "analysis/arrival/model_bounded_cubature.py",
            "scripts/resolve_arrival_bounded_score.py",
        ]
    )
)


def reviewed_path(root, spec, path):
    p = checked_path(root, str(path))
    name = str(p.relative_to(root))
    if name not in spec["files"] or sha256(p) != spec["files"][name]:
        raise ValueError("preapproved science artifact identity required before parsing")
    return p


def reviewed_ensemble(root, spec, folder, *args):
    saved = json.loads(reviewed_path(root, spec, folder / "result.json").read_text())
    for p in [
        *(
            folder / name
            for name in [
                "inputs.json",
                "job.json",
                "membership.json",
                "diagnostics.json",
                "sampling-diagnostics.csv",
            ]
        ),
        checked_path(root, saved["posterior"]),
    ]:
        reviewed_path(root, spec, p)
    return _read_ensemble(root, folder, *args)


def validate_manifest(root, manifest):
    spec = json.loads(checked_path(root, str(manifest)).read_text())
    if (
        spec.get("schema_version") != "arrival_bounded_event_cubature_v1"
        or spec.get("status") != "accepted_for_bounded_event_cubature"
        or not spec.get("independent_checker")
        or any(
            not isinstance(spec.get(k), str) or not spec[k] or spec[k] == "unknown"
            for k in ["case_id", "event_id"]
        )
        or spec.get("reserved_outcomes") != "sealed"
        or spec.get("target") not in {"NCEI-native-duration", "T-OBS", "T-CAL"}
        or type(spec.get("records")) is not int
        or spec["records"] < 1
        or spec.get("admission_profile") not in {"inputs_only_first_cap", "exhausted_first_cap"}
        or spec.get("max_points_per_integral") != 2000000
        or spec.get("new_sampler_calls") != 0
        or spec.get("adaptive_integrals") != 5
        or spec.get("prior_failed_point_ceiling") != 1000000
        or spec.get("retained_tensor_points") != 1703936
        or spec.get("cumulative_point_ceiling") != 12703936
        or spec.get("final_score_tolerance_per_record") != 1e-6
        or not set(CONSUMED) <= set(spec.get("files", {}))
    ):
        raise ValueError("independently accepted fixed normalizer manifest required")
    for p, h in spec["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("normalizer design source changed")
    for name in ["source_fold", "failed_calculation", "retained_tensor", "output"]:
        checked_path(root, spec[name])
    source_name = Path(spec["source_fold"]).name
    if not source_name.startswith(spec["case_id"] + "-attempt-") or source_name.rsplit(
        "-attempt-", 1
    )[1] not in {"1", "2"}:
        raise ValueError("fixed source case/attempt identity required")
    expected_rtol = min(1e-5, spec["records"] * 1e-6 / 4)
    if any(
        not isinstance(spec.get(key), (int, float))
        or not math.isclose(spec[key], value, rel_tol=1e-12, abs_tol=0)
        for key, value in [("primary_rtol", expected_rtol), ("refined_rtol", expected_rtol / 2)]
    ):
        raise ValueError("record-count numerical error allocation must match policy")
    source = checked_path(root, spec["source_fold"])
    failed = checked_path(root, spec["failed_calculation"])
    required = [
        *(
            source / name
            for name in [
                "result.json",
                "inputs.json",
                "membership.json",
                "held-out-record-predictions.csv",
            ]
        ),
        failed / "inputs.json",
        failed.with_suffix(".log"),
        failed.with_suffix(".supervisor.json"),
        checked_path(root, spec["retained_tensor"]),
    ]
    if spec["admission_profile"] == "exhausted_first_cap":
        required.append(failed / "exhausted-repair-evidence.json")
    for p in required:
        reviewed_path(root, spec, p)
    return spec


def verify_first_cap(root, failed, source, event, state_path, profile):
    failed, source = [checked_path(root, str(p)) for p in [failed, source]]
    result = json.loads((source / "result.json").read_text())
    inputs = json.loads((failed / "inputs.json").read_text())
    stopped = json.loads(checked_path(root, str(state_path)).read_text())
    if (
        stopped["status"] != "needs_review"
        or stopped["current"] is not None
        or Path(stopped["attempts"][-1]["output"]).resolve() != source
    ):
        raise ValueError("exact inactive stopped source required")
    expected = {"inputs.json"}
    proof = None
    if profile == "exhausted_first_cap":
        expected.add("exhausted-repair-evidence.json")
        proof = verify_exhausted(root, source, state_path)
        historical = json.loads((failed / "exhausted-repair-evidence.json").read_text())
        keys = set(proof) - {"state_sha256_at_resolution"}
        if (
            not result["repairable"]
            or inputs.get("exhausted_repair") != historical
            or any(historical.get(k) != proof[k] for k in keys)
        ):
            raise ValueError("same retained exhausted source proof required")
    elif profile != "inputs_only_first_cap" or result["repairable"]:
        raise ValueError("matching first-cap admission profile required")
    supervisor = json.loads(failed.with_suffix(".supervisor.json").read_text())
    source_name = str((source / "result.json").relative_to(root))
    if (
        {p.name for p in failed.iterdir()} != expected
        or inputs["job"] != result["job"]
        or inputs["event_id"] != event
        or inputs["max_points_per_integral"] != 1000000
        or inputs["files"].get(source_name) != sha256(source / "result.json")
        or supervisor["reason"] != "worker_exit"
        or supervisor["returncode"] != 1
        or "ValueError: cubature point ceiling reached"
        not in failed.with_suffix(".log").read_text()
    ):
        raise ValueError("retained first-integral point-cap failure required")
    for p, h in inputs["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("old failed source changed")
    paths = [
        *(failed / name for name in expected),
        failed.with_suffix(".log"),
        failed.with_suffix(".supervisor.json"),
    ]
    return {str(p.relative_to(root)): sha256(p) for p in paths}, proof


def resolve_bounded_event(root: Path, manifest: Path, state_path: Path, output: Path):
    root, manifest, state_path, output = [p.resolve() for p in [root, manifest, state_path, output]]
    spec = validate_manifest(root, manifest)
    source = checked_path(root, spec["source_fold"])
    failed = checked_path(root, spec["failed_calculation"])
    tensor_path = checked_path(root, spec["retained_tensor"])
    event = spec["event_id"]
    if output != checked_path(root, spec["output"]):
        raise ValueError("fixed reviewed output required")
    if output.exists() or not output.is_relative_to(root) or not source.is_relative_to(root):
        raise ValueError("new project-local numerical resolution required")
    stopped = json.loads(state_path.read_text())
    count = 2 if spec["admission_profile"] == "exhausted_first_cap" else 1
    for attempt in stopped["attempts"][-count:]:
        for path in attempt["files"]:
            reviewed_path(root, spec, path)
    failure_pins, proof = verify_first_cap(
        root, failed, source, event, state_path, spec["admission_profile"]
    )
    tensor_path = checked_path(root, str(tensor_path))
    retained = json.loads(reviewed_path(root, spec, tensor_path).read_text())
    result = json.loads(reviewed_path(root, spec, source / "result.json").read_text())
    job = result["job"]
    if (
        job["kind"] != "event"
        or job.get("prior") != "base"
        or result["status"] != "precision_failure"
        or not result["prediction_precision_passed"]
    ):
        raise ValueError("clean-prediction failed base-event bridge required")
    for name in [job["gate"], job["bridge_gate"]]:
        reviewed_path(root, spec, name)
    verify_bridge_gate(root, root / job["bridge_gate"], job["target"], "event")
    lanes, frozen = load_lanes(root)
    lane = lanes[job["target"]]
    fold = next(f for f in sequence_folds(lane) if f.sequence_id == job["sequence"])
    events = sorted({lane.event_ids[int(i)] for i in fold.test})
    old = next(e for e in result["events"] if e["event_id"] == event)
    if old["precision_passed"]:
        raise ValueError("designated unresolved event score required")
    prior = read_prior(root, lane.target, "base")
    train, aug, held = event_models(lane, fold, event, [prior["alpha_sd"], prior["beta_sd"]])
    scales = np.array([prior["sigma_sd"], prior["tau_sd"]])
    pins = {p: sha256(root / p) for p in [*CONSUMED, job["gate"], job["bridge_gate"]]}
    pins[str((source / "result.json").relative_to(root))] = sha256(source / "result.json")
    proposals = []
    source_posteriors = {}
    for k, phase, selected, ids in [
        (0, "training", None, fold.train),
        (events.index(event) + 1, "augmented", event, np.sort(np.r_[fold.train, held])),
    ]:
        folder = source / "ensembles" / f"{k:02d}-{phase}"
        ensemble_job = {**job, "phase": phase, "event": selected, "seed": job["seed"] + k}
        saved, _, values = reviewed_ensemble(root, spec, folder, ensemble_job, lane, ids, frozen)
        if not saved["diagnostics"]["screen_passed"]:
            raise ValueError("clean original source ensemble required")
        source_posteriors[saved["posterior"]] = sha256(root / saved["posterior"])
        z = values.reshape(-1, 2) / scales
        proposals.append(PositiveProposal(np.median(z, axis=0), np.std(z, axis=0, ddof=1)))
        for p in [folder / "result.json", folder / "inputs.json", root / saved["posterior"]]:
            pins[str(p.relative_to(root))] = sha256(p)
    reference = PositiveProposal(
        (proposals[0].location + proposals[1].location) / 2,
        2 * np.maximum(proposals[0].scale, proposals[1].scale),
    )
    tensor = retained_tensor(reference, retained, source_posteriors)
    if len(held) != spec["records"] or job["target"] != spec["target"]:
        raise ValueError("reviewed native target/count required")
    rtol = min(1e-5, len(held) * 1e-6 / 4)
    pins.update(spec["files"])
    pins[str(manifest.relative_to(root))] = sha256(manifest)
    pins.update(failure_pins)
    pins[str(tensor_path.relative_to(root))] = sha256(tensor_path)
    output.mkdir(parents=True)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "admission_profile": spec["admission_profile"],
            "current_exhaustion_snapshot": proof,
            "source_files": frozen,
            "job": job,
            "event_id": event,
            "training_records": len(fold.train),
            "held_sequence_records": len(fold.test),
            "held_event_records": len(held),
            "new_sampler_calls": 0,
            "adaptive_integrals": 5,
            "max_points_per_integral": 2000000,
            "prior_failed_adaptive_point_ceiling": 1000000,
            "new_adaptive_point_ceiling": 10000000,
            "retained_tensor_point_evaluations": 1703936,
            "cumulative_point_ceiling": "12703936_plus_scaling_centers",
            "retained_tensor": str(tensor_path.relative_to(root)),
            "relative_tolerances": [rtol, rtol / 2],
            "tensor_nodes": [512, 768],
            "score_designation": "primary_cubature_ratio_before_refinements",
            "tolerance_nats_per_record": 1e-6,
        },
    )
    targets = [normalized_target(m, scales) for m in [train, aug]]
    values = {}
    for j, label in enumerate(["training", "augmented"]):
        for refined in [False, True]:
            name = label + ("-refined" if refined else "")
            proposal = PositiveProposal(
                proposals[j].location, proposals[j].scale * (1.5 if refined else 1)
            )
            values[name] = integrate_positive(
                targets[j],
                proposal,
                relative_tolerance=rtol / 2 if refined else rtol,
                max_points=2000000,
                shift=1.0 if refined else 0.0,
            )
            write_json(output / (name + ".json"), values[name])
            print(name, values[name]["points"], flush=True)
    design = np.c_[np.ones(len(lane.rows)), lane.x]

    def conditional(z):
        return targets[0](z) + train.new_event_logpdf(
            z * scales, lane.response[held], design[held], np.ones((len(held), 1))
        )

    values["conditional"] = integrate_positive(
        conditional, proposals[1], relative_tolerance=rtol, max_points=2000000
    )
    write_json(output / "conditional.json", values["conditional"])
    write_json(
        output / "tensor-integrals.json",
        {
            "log_normalizers": tensor,
            "proposal_location": reference.location.tolist(),
            "proposal_scale": reference.scale.tolist(),
        },
    )
    primary = values["augmented"]["log_evidence"] - values["training"]["log_evidence"]
    refined = (
        values["augmented-refined"]["log_evidence"] - values["training-refined"]["log_evidence"]
    )
    error = sum(values[k]["relative_error_estimate"] for k in ["training", "augmented"])
    differences = [
        abs(refined - primary),
        abs(values["conditional"]["log_evidence"] - values["augmented"]["log_evidence"]),
        *[abs(v[1] - v[0] - primary) for v in tensor.values()],
    ]
    jac = 0.0 if lane.target == "T-CAL" else float(np.log(lane.y[held]).sum())
    passed = max([error, *differences]) / len(held) <= 1e-6
    write_json(
        output / "result.json",
        {
            "event_id": event,
            "sequence": fold.sequence_id,
            "target": lane.target,
            "kind": "event",
            "records": len(held),
            "joint_log_predictive": primary - jac,
            "normalized_event_score": (primary - jac) / len(held),
            "precision_passed": bool(passed),
            "numerical_error_estimate_per_record": error / len(held),
            "max_refinement_agreement_nats_per_record": max(differences) / len(held),
            "independent_conditional_raw_difference": differences[1],
            "monte_carlo_used": False,
            "normalized_mcse": "not_applicable",
            "error_scope": (
                "routine_estimates_refinement_and_independent_tensor_checks_not_rigorous_bound"
            ),
            "native_jacobian_subtracted_once": jac,
            "new_sampler_calls": 0,
            "status": "computed_pending_independent_review" if passed else "precision_failure",
            "reserved_outcomes": "sealed",
        },
    )
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("numerical resolution source changed")
