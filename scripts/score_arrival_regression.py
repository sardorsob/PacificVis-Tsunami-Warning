"""Compute finite exact-sequence Gaussian baseline scores with a 600-second guardian."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, choices=["NCEI-native-duration", "T-OBS", "T-CAL"])
    p.add_argument("--kind", required=True, choices=["pooled", "distance"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--max-folds", type=int)
    p.add_argument("--worker", action="store_true")
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = a.output.resolve()
    store = a.store.resolve()
    if a.worker:
        limit_worker_file_size(64 * 1024**2)
        from analysis.arrival.model_analytic_baselines import run_analytic_baseline

        gate = root / (
            "artifacts/models/arrival-timing/inference-validation-acceptance-v1.json"
            if a.target == "NCEI-native-duration"
            else f"artifacts/models/arrival-timing/source-validation-report-v1/{a.target}/"
            "review-acceptance.json"
        )
        run_analytic_baseline(root, a.target, a.kind, gate, out, store, max_folds=a.max_folds)
    else:
        if out.exists() or store.exists():
            raise ValueError("new numerical attempt paths required")
        out.parent.mkdir(parents=True, exist_ok=True)
        pins = sha256(Path(__file__))
        args = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--target",
            a.target,
            "--kind",
            a.kind,
            "--output",
            str(out),
            "--store",
            str(store),
        ]
        if a.max_folds is not None:
            args.extend(["--max-folds", str(a.max_folds)])
        try:
            receipt = supervise(args, out.with_suffix(".log"), out.parent / "STOP", 600)
        except KeyboardInterrupt:
            receipt = {"returncode": 130, "reason": "interrupt"}
        write_json(out.with_suffix(".supervisor.json"), {**receipt, "runner_sha256": pins})
        if (
            receipt["returncode"] != 0
            or receipt["reason"] != "worker_exit"
            or sha256(Path(__file__)) != pins
        ):
            raise SystemExit(1)
