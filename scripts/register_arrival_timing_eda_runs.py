"""Log immutable descriptive bundles to the project-local experiment ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.timing_artifact_names import artifact_filename  # noqa: E402


def register(root: Path, bundles: list[Path], receipt: Path) -> None:
    mlflow.set_tracking_uri((root / ".mlflow/mlruns").as_uri())
    cast(Any, mlflow).set_experiment("arrival-paper-eda")
    records: list[dict[str, Any]] = []
    for bundle in bundles:
        meta = json.loads((bundle / artifact_filename("meta.json")).read_text())
        with mlflow.start_run(run_name=f"2026-11-03__{bundle.name}") as active:
            mlflow.log_params(
                {
                    "split": meta["split"],
                    "module": meta["module"],
                    "bootstrap_repeats": 500,
                    "seed": 20261103,
                    "reference_depth_m": 4000,
                    "model_fitted": False,
                }
            )
            mlflow.set_tags(
                {
                    "git_sha": meta["git_sha"],
                    "disposition": "preliminary_descriptive",
                    "code_and_data_refs": (bundle / artifact_filename("inputs.json")).read_text(),
                    "selection": "frozen metadata-only split; no outcome selection",
                }
            )
            for path in bundle.iterdir():
                if path.is_file():
                    mlflow.log_artifact(str(path))
            summary = json.loads((bundle / artifact_filename("summary.json")).read_text())
            for target, metrics in summary.items():
                if isinstance(metrics, dict):
                    for key, value in cast(dict[str, Any], metrics).items():
                        if isinstance(value, (float, int)) and not isinstance(value, bool):
                            mlflow.log_metric(target + "." + key, value)
            records.append({"bundle": str(bundle.relative_to(root)), "run_id": active.info.run_id})
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bundles", nargs="+", type=Path)
    p.add_argument("--receipt", type=Path, required=True)
    args = p.parse_args()
    register(Path(".").resolve(), [p.resolve() for p in args.bundles], args.receipt)
