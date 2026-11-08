"""Bounded development-only Gaussian normalizer prototype on an already fitted sequence."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_collapsed import CollapsedGaussian  # noqa: E402
from analysis.arrival.model_cv import verify_prediction_gate  # noqa: E402
from analysis.arrival.model_data import load_lanes, sequence_folds  # noqa: E402
from analysis.arrival.model_normalizer import PositiveProposal, integrate_positive  # noqa: E402
from analysis.arrival.model_scale import scale_weights  # noqa: E402
from analysis.arrival.models import read_prior  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402


def pilot(root: Path, fit: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("new development output required")
    source = json.loads((fit / "result.json").read_text())
    job = source["job"]
    if (
        job["target"] != "NCEI-native-duration"
        or job["kind"] not in ["event", "distance-scale"]
        or not source["diagnostics"]["screen_passed"]
    ):
        raise ValueError("clean already fitted primary-source sequence required")
    verify_prediction_gate(root, root / job["gate"], job["target"], job["kind"])
    for p, h in source["code_and_config"].items():
        if sha256(root / p) != h:
            raise ValueError("source fit identities changed")
    posterior = root / source["posterior"]
    if sha256(posterior) != source["posterior_sha256"]:
        raise ValueError("source posterior changed")
    lane = load_lanes(root)[0][job["target"]]
    fold = next(f for f in sequence_folds(lane) if f.sequence_id == job["sequence"])
    if len({lane.event_ids[int(i)] for i in fold.test}) != 1:
        raise ValueError("prototype is single held-event only")
    prior = read_prior(root, lane.target, "base")
    coefficient_sd = np.array([prior["alpha_sd"], prior["beta_sd"]])
    variable = job["kind"] == "distance-scale"
    with xr.open_dataset(posterior, group="posterior", engine="h5netcdf") as ds:
        s = ds.sigma_anchor.values.reshape(-1, 3) if variable else ds.sigma.values.reshape(-1, 1)
        draws = np.c_[s, ds.tau_event.values.reshape(-1)]
    scales = np.array([prior["sigma_sd"]] * (3 if variable else 1) + [prior["tau_sd"]])
    normalized = draws / scales
    proposal = PositiveProposal(np.median(normalized, axis=0), normalized.std(axis=0, ddof=1))
    x = np.c_[np.ones(len(lane.rows)), lane.x]
    w = scale_weights(lane.distance_km) if variable else np.ones((len(lane.rows), 1))
    events = np.array(lane.event_ids)
    train = CollapsedGaussian(
        lane.response[fold.train], x[fold.train], events[fold.train], w[fold.train], coefficient_sd
    )
    both = np.r_[fold.train, fold.test]
    combined = CollapsedGaussian(
        lane.response[both], x[both], events[both], w[both], coefficient_sd
    )
    dimension = len(scales)
    constant = dimension * 0.5 * math.log(2 / math.pi)

    def target(model):
        return lambda a: (
            np.asarray(model.evaluate(a * scales)) + constant - 0.5 * np.sum(a * a, axis=1)
        )

    def direct(a):
        raw = a * scales
        return (
            np.asarray(train.evaluate(raw))
            + constant
            - 0.5 * np.sum(a * a, axis=1)
            + train.new_event_logpdf(raw, lane.response[fold.test], x[fold.test], w[fold.test])
        )

    output.mkdir(parents=True)
    consumed = [
        "analysis/arrival/model_collapsed.py",
        "analysis/arrival/model_normalizer.py",
        "analysis/arrival/model_data.py",
        "analysis/arrival/model_scale.py",
        "analysis/arrival/models.py",
        "scripts/pilot_arrival_normalizer.py",
        "config/arrival-model-priors-v1.toml",
        "pyproject.toml",
        "uv.lock",
    ]
    pins = {p: sha256(root / p) for p in consumed}
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "source_result": str((fit / "result.json").relative_to(root)),
            "source_result_sha256": sha256(fit / "result.json"),
            "proposal_location": proposal.location.tolist(),
            "proposal_scale": proposal.scale.tolist(),
            "training_records": len(fold.train),
            "heldout_records": len(fold.test),
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
        },
    )
    tolerance = 1e-6 if variable else 1e-7
    cap = 2000000 if variable else 1000000
    results = {}
    started = time.monotonic()
    try:
        for label, model in [("training", train), ("augmented", combined)]:
            results[label] = integrate_positive(
                target(model), proposal, relative_tolerance=tolerance, max_points=cap
            )
            write_json(output / (label + ".json"), results[label])
            print(label, results[label], flush=True)
        results["conditional"] = integrate_positive(
            direct, proposal, relative_tolerance=tolerance, max_points=cap
        )
        write_json(output / "conditional.json", results["conditional"])
        print("conditional", results["conditional"], flush=True)
        wider = PositiveProposal(proposal.location, proposal.scale * 1.5)
        for label, model in [("training_refined", train), ("augmented_refined", combined)]:
            results[label] = integrate_positive(
                target(model), wider, relative_tolerance=tolerance / 10, max_points=cap, shift=1.0
            )
            write_json(output / (label + ".json"), results[label])
            print(label, results[label], flush=True)
        score = results["augmented"]["log_evidence"] - results["training"]["log_evidence"]
        repeated = (
            results["augmented_refined"]["log_evidence"]
            - results["training_refined"]["log_evidence"]
        )
        agreement = abs(
            results["conditional"]["log_evidence"] - results["augmented"]["log_evidence"]
        )
        jac = float(np.log(lane.y[fold.test]).sum())
        write_json(
            output / "result.json",
            {
                "status": "development_prototype_pending_review",
                "joint_native_score": score - jac,
                "normalized_event_score": (score - jac) / len(fold.test),
                "independent_conditional_agreement": agreement,
                "proposal_refinement_difference": abs(repeated - score),
                "elapsed_seconds": time.monotonic() - started,
                "source_kind": job["kind"],
                "sequence": fold.sequence_id,
                "reserved_outcomes": "sealed",
                "finite_budget_only_no_full_CV_promotion": True,
            },
        )
    except Exception as exc:
        write_json(
            output / "failure.json",
            {
                "error": str(exc),
                "elapsed_seconds": time.monotonic() - started,
                "completed_integrals": list(results),
            },
        )
        raise
    if any(sha256(root / p) != h for p, h in pins.items()):
        raise ValueError("prototype source changed")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", action="store_true")
    a = p.parse_args()
    out = a.output.resolve()
    root = Path(__file__).resolve().parents[1]
    if a.worker:
        limit_worker_file_size(64 * 1024**2)
        pilot(root, a.fit.resolve(), out)
    else:
        if out.exists():
            raise ValueError("new prototype path required")
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--fit",
                str(a.fit.resolve()),
                "--output",
                str(out),
            ],
            out.with_suffix(".log"),
            out.parent / "STOP",
            600,
        )
        write_json(out.with_suffix(".supervisor.json"), receipt)
        if receipt["returncode"] != 0 or receipt["reason"] != "worker_exit":
            raise SystemExit(1)
