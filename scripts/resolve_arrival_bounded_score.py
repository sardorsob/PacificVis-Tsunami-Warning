"""Resolve a failed two-scale event score without new posterior sampling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import write_json  # noqa: E402
from analysis.arrival.model_bounded_cubature import resolve_bounded_event  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--design", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", action="store_true")
    a = p.parse_args()
    root, out = Path(__file__).resolve().parents[1], a.output.resolve()
    if out.exists() or not out.is_relative_to(root):
        raise ValueError("new project-local output required")
    if a.worker:
        limit_worker_file_size(64 * 1024**2)
        resolve_bounded_event(root, a.design.resolve(), a.state.resolve(), out)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--design",
                str(a.design.resolve()),
                "--state",
                str(a.state.resolve()),
                "--output",
                str(out),
            ],
            out.with_suffix(".log"),
            out.parent / "STOP",
            600,
        )
        write_json(out.with_suffix(".supervisor.json"), receipt)
        if receipt["reason"] != "worker_exit" or receipt["returncode"] != 0:
            raise SystemExit(1)
