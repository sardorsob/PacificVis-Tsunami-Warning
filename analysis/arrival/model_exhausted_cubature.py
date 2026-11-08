"""Bounded two-scale Gaussian normalizers for one held event in a purged sequence."""

# pyright: basic
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from analysis.arrival.evidence import checked_path, sha256, write_json
from analysis.arrival.model_bridge_cv import _read_ensemble, verify_bridge_gate
from analysis.arrival.model_data import load_lanes, sequence_folds
from analysis.arrival.model_event_cubature import CONSUMED as ORIGINAL_CONSUMED
from analysis.arrival.model_event_cubature import event_models, normalized_target, tensor_integral
from analysis.arrival.model_normalizer import PositiveProposal, integrate_positive
from analysis.arrival.models import read_prior

CONSUMED = [
    *ORIGINAL_CONSUMED,
    "analysis/arrival/model_exhausted_cubature.py",
    "scripts/resolve_arrival_exhausted_score.py",
]


def verify_exhausted(root, source, state_path):
    """Admit only the exact stopped second attempt, never silently waive a repair."""
    source, state_path = source.resolve(), state_path.resolve()
    if not source.is_relative_to(root) or not state_path.is_relative_to(root):
        raise ValueError("project-local stopped evidence required")
    if (source.parent.parent / ".controller.lock").exists():
        raise ValueError("inactive sampler controller required")
    state = json.loads(state_path.read_text())
    attempts = state.get("attempts", [])
    if (
        state.get("status") != "needs_review"
        or state.get("current") is not None
        or len(attempts) < 2
    ):
        raise ValueError("inactive stopped checkpoint with both attempts required")
    first, second = attempts[-2:]
    if Path(second["output"]).resolve() != source or not source.name.endswith("-attempt-2"):
        raise ValueError("exact stopped second attempt required")
    results = []
    for attempt in [first, second]:
        folder = checked_path(root, attempt["output"])
        if attempt["outcome"] not in {"precision_failure", "diagnostic_or_precision_failure"}:
            raise ValueError("retained failed attempts required")
        for p, h in attempt["files"].items():
            if sha256(checked_path(root, p)) != h:
                raise ValueError("stopped attempt evidence changed")
        if str(folder / "result.json") not in attempt["files"]:
            raise ValueError("original result checksum required")
        value = json.loads((folder / "result.json").read_text())
        if value["status"] != "precision_failure" or not value["prediction_precision_passed"]:
            raise ValueError("clean prediction numerical-score failures required")
        results.append(value)
    a, b = [r["job"] for r in results]
    if (a["draws"], a["tune"], b["draws"], b["tune"]) != (2000, 1000, 4000, 2000) or {
        k: v for k, v in a.items() if k not in {"draws", "tune"}
    } != {k: v for k, v in b.items() if k not in {"draws", "tune"}}:
        raise ValueError("same-job same-seed single allowed precision repair required")
    if Path(first["output"]).name != source.name.removesuffix("2") + "1":
        raise ValueError("paired original attempts required")
    return {
        "state_sha256_at_resolution": sha256(state_path),
        "next_case": state["next_case"],
        "sampler_call_slots_used": state["sampler_call_slots_used"],
        "first_result": str((Path(first["output"]) / "result.json").relative_to(root)),
        "first_result_sha256": sha256(Path(first["output"]) / "result.json"),
        "second_result_sha256": sha256(source / "result.json"),
        "scope": "immutable snapshot of exhausted repair; live checkpoint is not pinned",
    }


def resolve_exhausted_event(root: Path, source: Path, event: str, output: Path, state_path: Path):
    if output.exists() or not output.is_relative_to(root) or not source.is_relative_to(root):
        raise ValueError("new project-local numerical resolution required")
    proof = verify_exhausted(root, source, state_path)
    result = json.loads((source / "result.json").read_text())
    job = result["job"]
    if (
        job["kind"] != "event"
        or job.get("prior") != "base"
        or result["status"] != "precision_failure"
        or not result["prediction_precision_passed"]
    ):
        raise ValueError("clean-prediction failed base-event bridge required")
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
    for k, phase, selected, ids in [
        (0, "training", None, fold.train),
        (events.index(event) + 1, "augmented", event, np.sort(np.r_[fold.train, held])),
    ]:
        folder = source / "ensembles" / f"{k:02d}-{phase}"
        ensemble_job = {**job, "phase": phase, "event": selected, "seed": job["seed"] + k}
        saved, _, values = _read_ensemble(root, folder, ensemble_job, lane, ids, frozen)
        if not saved["diagnostics"]["screen_passed"]:
            raise ValueError("clean original source ensemble required")
        z = values.reshape(-1, 2) / scales
        proposals.append(PositiveProposal(np.median(z, axis=0), np.std(z, axis=0, ddof=1)))
        for p in [folder / "result.json", folder / "inputs.json", root / saved["posterior"]]:
            pins[str(p.relative_to(root))] = sha256(p)
    output.mkdir(parents=True)
    write_json(output / "exhausted-repair-evidence.json", proof)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "exhausted_repair": proof,
            "source_files": frozen,
            "job": job,
            "event_id": event,
            "training_records": len(fold.train),
            "held_sequence_records": len(fold.test),
            "held_event_records": len(held),
            "new_sampler_calls": 0,
            "adaptive_integrals": 5,
            "max_points_per_integral": 1000000,
            "relative_tolerances": [1e-7, 1e-8],
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
                relative_tolerance=1e-8 if refined else 1e-7,
                max_points=1000000,
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
        conditional, proposals[1], relative_tolerance=1e-7, max_points=1000000
    )
    write_json(output / "conditional.json", values["conditional"])
    reference = PositiveProposal(
        (proposals[0].location + proposals[1].location) / 2,
        2 * np.maximum(proposals[0].scale, proposals[1].scale),
    )
    tensor = {
        str(n): [tensor_integral(target, reference, n) for target in targets] for n in [512, 768]
    }
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
