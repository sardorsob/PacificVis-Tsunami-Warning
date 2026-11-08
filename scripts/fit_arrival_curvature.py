"""Supervise one finite exploration mean-curvature fit, retaining every failure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024**2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    job_path, output, store = args.job.resolve(), args.output.resolve(), args.store.resolve()
    if not 1 <= args.max_output_bytes <= 64 * 1024**2:
        raise ValueError("per-file allocation must be1..64MiB")
    if args.worker:
        limit_worker_file_size(args.max_output_bytes)
        from analysis.arrival.model_curvature_fit import fit_exploration_curvature

        fit_exploration_curvature(root, json.loads(job_path.read_text()), output, store)
        return
    if (
        output.exists()
        or output.with_suffix(".log").exists()
        or output.with_suffix(".supervisor.json").exists()
        or store.exists()
        or store.with_name(store.stem + "-augmented.nc").exists()
        or not output.is_relative_to(root)
        or not store.is_relative_to(root)
    ):
        raise ValueError("new project-local attempt paths required")
    from analysis.arrival.model_curvature_fit import CONSUMED, FIT_GATE, verify_fit_gate

    pins = verify_fit_gate(root, json.loads(job_path.read_text()), output, store)
    assert set(CONSUMED) | {FIT_GATE} <= set(pins)
    jobhash = sha256(job_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--job",
                str(job_path),
                "--output",
                str(output),
                "--store",
                str(store),
                "--max-output-bytes",
                str(args.max_output_bytes),
            ],
            output.with_suffix(".log"),
            output.parent / "STOP",
            600,
        )
    except KeyboardInterrupt:
        receipt = {"returncode": 130, "reason": "interrupt"}
    write_json(
        output.with_suffix(".supervisor.json"),
        {**receipt, "job_sha256": jobhash, "source_pins": pins},
    )
    if (
        receipt["returncode"] != 0
        or receipt["reason"] != "worker_exit"
        or sha256(job_path) != jobhash
        or any(sha256(root / p) != expected for p, expected in pins.items())
    ):
        raise SystemExit(1)
    result = json.loads((output / "result.json").read_text())
    if (
        result["job"] != json.loads(job_path.read_text())
        or result["code_and_config"] != pins
        or sha256(store) != result["posterior_sha256"]
    ):
        raise ValueError("fit result identity/hash mismatch")
    if not result["diagnostics"]["screen_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
