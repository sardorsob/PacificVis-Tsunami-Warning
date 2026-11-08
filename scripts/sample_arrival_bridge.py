"""Sample one immutable, supervised training/augmented bridge ensemble."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import write_json  # noqa: E402
from analysis.arrival.model_bridge_sampling import sample_ensemble  # noqa: E402
from scripts.run_arrival_model_validation import limit_worker_file_size, supervise  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    p.add_argument("--worker", action="store_true")
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = a.output.resolve()
    if a.worker:
        limit_worker_file_size(64 * 1024**2)
        sample_ensemble(root, json.loads(a.job.read_text()), out, a.store.resolve())
    else:
        if out.exists() or a.store.exists():
            raise ValueError("new ensemble paths required")
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = supervise(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--job",
                str(a.job.resolve()),
                "--output",
                str(out),
                "--store",
                str(a.store.resolve()),
            ],
            out.with_suffix(".log"),
            out.parent / "STOP",
            600,
        )
        write_json(out.with_suffix(".supervisor.json"), receipt)
        if receipt["returncode"] != 0 or receipt["reason"] != "worker_exit":
            raise SystemExit(1)
