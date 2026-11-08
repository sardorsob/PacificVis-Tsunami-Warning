"""Build protected arrival-model data contracts and record local experiments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.model_data import write_data_bundle  # noqa: E402


def execution_identity(root: Path, code: list[str]) -> dict[str, Any]:
    """Record actual Git state, or identify a hash-pinned source export explicitly."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).splitlines()
    except subprocess.CalledProcessError:
        sha, dirty = "unavailable_non_git_source_export", []
    return {
        "git_sha": sha,
        "dirty_paths": dirty,
        "code_and_environment": {p: sha256(root / p) for p in code},
    }


def register_bundle(root: Path, output: Path) -> None:
    """Resume local registration without rebuilding or overwriting the scientific bundle."""
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    import mlflow

    receipt = output / "mlflow-receipt.json"
    if receipt.exists():
        raise ValueError("bundle already has an MLflow receipt; verify before retrying")
    meta = json.loads((output / "run-metadata.json").read_text(encoding="utf-8"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    mlflow.set_tracking_uri((root / ".mlflow/mlruns").as_uri())
    cast(Any, mlflow).set_experiment("arrival-model")
    fingerprint = sha256(output / "output-checksums.json")
    existing = cast(Any, mlflow).search_runs(
        filter_string=f"tags.bundle_sha256 = '{fingerprint}'", output_format="list"
    )
    if existing:
        if len(existing) != 1 or existing[0].info.status != "FINISHED":
            raise ValueError("ambiguous or unfinished MLflow registration; inspect before retry")
        write_json(receipt, {"run_id": existing[0].info.run_id})
        return
    with mlflow.start_run(run_name="MS-0-exploration-contract") as run:
        mlflow.log_params({"stage": "MS-0", "seed": 20261107, "scientific_fit": False})
        mlflow.set_tags(
            {
                "git_sha": meta["git_sha"],
                "decision": "contract_candidate",
                "bundle_sha256": fingerprint,
                "evidence_policy": "exclude_unresolved_repeat_groups",
            }
        )
        for target, values in metrics.items():
            for key in ["rows", "primary_rows", "events", "sites", "sequences"]:
                mlflow.log_metric(target + "." + key, values[key])
        for path in sorted(output.iterdir()):
            mlflow.log_artifact(str(path))
        run_id = run.info.run_id
    write_json(receipt, {"run_id": run_id})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    data = sub.add_parser("data", help="build the pinned exploration-only contract bundle")
    data.add_argument("--output", type=Path, required=True)
    data.add_argument("--register", action="store_true", help="log to project-local MLflow")
    stack = sub.add_parser("stack", help="verify synthetic sampling and NetCDF roundtrip")
    stack.add_argument("--store", type=Path, required=True)
    stack.add_argument("--receipt", type=Path, required=True)
    registration = sub.add_parser("register", help="resume project-local bundle registration")
    registration.add_argument("--bundle", type=Path, required=True)
    lineage = sub.add_parser("lineage", help="audit native IDs on unresolved repeated edges")
    lineage.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "lineage":
        from analysis.arrival.model_evidence import audit_repeated_edges

        if args.receipt.exists():
            raise ValueError("lineage receipt already exists")
        write_json(args.receipt, audit_repeated_edges(root))
        return
    if args.command == "register":
        register_bundle(root, args.bundle.resolve())
        return
    if args.command == "stack":
        from analysis.arrival.model_stack import smoke_stack

        result = smoke_stack(args.store)
        result["netcdf_sha256"] = sha256(args.store)
        result.update(
            execution_identity(
                root,
                [
                    "scripts/arrival_model.py",
                    "analysis/arrival/model_stack.py",
                    "pyproject.toml",
                    "uv.lock",
                ],
            )
        )
        write_json(args.receipt, result)
        return
    output = args.output.resolve()
    write_data_bundle(root, output)
    meta = {
        **execution_identity(
            root,
            [
                "scripts/arrival_model.py",
                "analysis/arrival/model_data.py",
                "analysis/arrival/evidence.py",
                "pyproject.toml",
                "uv.lock",
            ],
        ),
        "scientific_model_fitted": False,
        "stage": "MS-0",
        "seed": 20261107,
    }
    write_json(output / "run-metadata.json", meta)
    write_json(
        output / "output-checksums.json",
        {
            path.name: sha256(path)
            for path in sorted(output.iterdir())
            if path.name != "output-checksums.json"
        },
    )
    if args.register:
        register_bundle(root, output)
    print(output)


if __name__ == "__main__":
    main()
