"""Consolidate final, independently accepted paper evidence into a portable/local MLflow run.

No acquisition or artifact rebuilding is performed. --check-only never creates a run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

TERMINAL = {"downloaded", "cached", "quarantined", "skipped", "blocked"}
RETAINED = {"downloaded", "cached"}
PACKAGE_FILES = {
    "crosswalk": "connectivity.json",
    "design": "summary.json",
    "corpus": "summary.json",
    "waves": "manifest.json",
    "catalog": "manifest.json",
    "audit": "manifest.json",
    "comparison": "manifest.json",
    "diagnostics": "manifest.json",
}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inside(root: Path, value: str | Path) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"input escapes project: {value}")
    return path


def fingerprint(root: Path, path: Path) -> dict[str, Any]:
    return dict(path=str(path.relative_to(root)), sha256=sha(path), bytes=path.stat().st_size)


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def verify_map(root: Path, mapping: dict[str, str], base: Path | None = None) -> None:
    for value, expected in mapping.items():
        path = inside(root, (base / value) if base is not None else value)
        if base is not None and not path.is_relative_to(base):
            raise ValueError(f"manifest output escapes package: {value}")
        if sha(path) != expected:
            raise ValueError(f"manifest checksum mismatch: {path}")


def package(
    root: Path,
    directory: Path,
    primary: str,
    aliases: dict[str, Path] | None = None,
) -> dict[str, Any]:
    directory = inside(root, directory)
    manifest = read(directory / primary)
    resolved_inputs = {
        str((aliases or {}).get(key, Path(key))): digest
        for key, digest in manifest.get("input_sha256", {}).items()
    }
    for name in ("contract_sha256", "header_receipt_sha256"):
        for path, digest in manifest.get(name, {}).items():
            if path in resolved_inputs and resolved_inputs[path] != digest:
                raise ValueError(f"contradictory input fingerprint: {path}")
            resolved_inputs[path] = digest
    verify_map(root, resolved_inputs)
    verify_map(root, manifest.get("output_sha256", {}), directory)
    # Waveform outputs use per-source hashes rather than one top-level output map.
    for source in manifest.get("sources", []):
        if source.get("output_path"):
            verify_map(root, {source["output_path"]: source["output_sha256"]}, directory)
    files: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"package symlink is not immutable local evidence: {path}")
        if path.is_file():
            files.append(fingerprint(root, path))
    if not files:
        raise ValueError(f"empty final package: {directory}")
    return dict(
        directory=str(directory.relative_to(root)),
        primary=primary,
        manifest=manifest,
        files=files,
        verified_input_sha256=resolved_inputs,
    )


def semantic_inputs(args: argparse.Namespace) -> dict[str, Path]:
    return dict(
        config=args.events,
        events_config=args.events,
        rows=args.census / "rows.json",
        links=args.census / "links.json",
        census=args.census / "census.json",
        annotations=args.annotations,
        crosswalk=args.crosswalk / "unique_report_crosswalk.csv",
        time_context=args.time_context,
    )


def verify_acceptance(root: Path, review: dict[str, Any], required: set[str]) -> None:
    if (
        review.get("status", "").casefold() != "pass"
        or not review.get("reviewer")
        or not review.get("checks")
    ):
        raise ValueError("final independent acceptance record is incomplete")
    expected = review.get("artifact_sha256", {})
    if not required <= set(expected):
        raise ValueError("final independent acceptance does not bind every required artifact")
    verify_map(root, expected)


def verify_foundation_membership(
    root: Path, reproduction: dict[str, Any], source_entries: int
) -> None:
    """Recheck finite preflight membership, not merely a checkpoint status flag."""
    sys.path.insert(0, str(root))
    from scripts.build_waveform_foundation import prepare as prepare_foundation

    complete = prepare_foundation(inside(root, reproduction["recipe"]), root)
    if (
        complete["input_sha256"] != reproduction["input_sha256"]
        or complete["source_entries"] != source_entries
    ):
        raise ValueError("final waveforms differ from complete pinned recipe membership")


def acquisition_inventory(root: Path, run_parent: Path) -> dict[str, Any]:
    """All completed lane=paper acquisition runs; every status is a contract outcome."""
    runs: list[dict[str, Any]] = []
    objects: dict[str, dict[str, Any]] = {}
    outcomes: Counter[str] = Counter()
    unique_ids: set[str] = set()
    successful_ids: set[str] = set()
    exact_response_bytes = legacy_downloaded_bytes = legacy_quarantined_bytes = 0
    uninstrumented: list[str] = []
    excluded: list[str] = []
    for run in sorted(inside(root, run_parent).iterdir()):
        if not run.is_dir() or run.name.startswith(".") or not (run / "meta.json").exists():
            continue
        meta = read(run / "meta.json")
        if meta.get("lane") != "paper":
            continue
        payload = read(run / "outputs.json")
        if not isinstance(payload, list):
            excluded.append(str(run.relative_to(root)))
            continue
        items = cast(list[Any], payload)
        if any(not isinstance(x, dict) or "source_id" not in x for x in items):
            excluded.append(str(run.relative_to(root)))
            continue
        after = cast(list[dict[str, Any]], items)
        before = read(run / "inputs.json")
        config, metrics = read(run / "config.json"), read(run / "metrics.json")
        if hashlib.sha256(config["toml"].encode()).hexdigest() != config["sha256"]:
            raise ValueError(f"captured configuration digest differs: {run}")
        input_ids = [s["source_id"] for s in before]
        output_ids = [s["source_id"] for s in after]
        if (
            len(set(input_ids)) != len(input_ids)
            or len(set(output_ids)) != len(output_ids)
            or set(input_ids) != set(output_ids)
        ):
            raise ValueError(f"acquisition source accounting differs: {run}")
        counts = Counter(s["status"] for s in after)
        if (
            not set(counts) <= TERMINAL
            or dict(counts) != metrics["status_counts"]
            or metrics["total_contracts"] != len(after)
            or metrics["total_outcomes"] != len(after)
        ):
            raise ValueError(f"acquisition is not a complete terminal receipt: {run}")
        by_id = {s["source_id"]: s for s in before}
        outcomes.update(counts)
        unique_ids.update(input_ids)
        for source in after:
            if source["local_path"] != by_id[source["source_id"]]["local_path"]:
                raise ValueError(f"source path differs from captured input: {run}")
            if source["status"] not in RETAINED:
                continue
            successful_ids.add(source["source_id"])
            raw = inside(root, source["local_path"])
            relative = str(raw.relative_to(root))
            if relative not in objects:
                item = fingerprint(root, raw)
                sidecar = raw.with_name(raw.name + ".sha256")
                if sidecar.read_text().strip() != item["sha256"]:
                    raise ValueError(f"raw sidecar mismatch: {raw}")
                objects[relative] = {**item, "source_ids": [], "runs": []}
            item = objects[relative]
            if item["sha256"] != source["sha256"] or item["bytes"] != source["bytes"]:
                raise ValueError(f"raw object differs across receipts: {raw}")
            item["source_ids"].append(source["source_id"])
            item["runs"].append(str(run.relative_to(root)))
        transfer = metrics.get("transfer_budget")
        if transfer is not None:
            amount = transfer["received_response_bytes"]
            if not isinstance(amount, int) or amount < 0:
                raise ValueError(f"invalid transfer byte metric: {run}")
            exact_response_bytes += amount
        else:
            uninstrumented.append(str(run.relative_to(root)))
            legacy_downloaded_bytes += sum(s["bytes"] for s in after if s["status"] == "downloaded")
            legacy_quarantined_bytes += sum(
                s["bytes"] for s in after if s["status"] == "quarantined"
            )
        runs.append(
            dict(
                run=str(run.relative_to(root)),
                status_counts=dict(counts),
                contract_outcomes=len(after),
                transfer_budget=transfer,
                evidence=[
                    fingerprint(root, run / name)
                    for name in (
                        "meta.json",
                        "config.json",
                        "inputs.json",
                        "outputs.json",
                        "metrics.json",
                    )
                ],
            )
        )
    if not runs:
        raise ValueError("no completed lane=paper acquisition receipts")
    distinct_content: dict[str, int] = {}
    for item in objects.values():
        item["source_ids"] = sorted(set(item["source_ids"]))
        item["runs"] = sorted(set(item["runs"]))
        if item["sha256"] in distinct_content and distinct_content[item["sha256"]] != item["bytes"]:
            raise ValueError("one content hash has contradictory sizes")
        distinct_content[item["sha256"]] = item["bytes"]
    return dict(
        runs=runs,
        raw_objects=[objects[k] for k in sorted(objects)],
        excluded_non_acquisition_paper_runs=excluded,
        uninstrumented_transfer_runs=uninstrumented,
        metrics=dict(
            paper_acquisition_runs=len(runs),
            contract_outcomes=sum(outcomes.values()),
            unique_source_ids=len(unique_ids),
            ever_retained_source_ids=len(successful_ids),
            never_retained_source_ids=len(unique_ids - successful_ids),
            raw_unique_path_hash_objects=len(objects),
            raw_unique_path_bytes=sum(x["bytes"] for x in objects.values()),
            raw_distinct_content_hashes=len(distinct_content),
            raw_distinct_content_bytes=sum(distinct_content.values()),
            instrumented_response_body_bytes=exact_response_bytes,
            legacy_retained_download_bytes_lower_bound=legacy_downloaded_bytes,
            known_response_body_bytes_lower_bound=exact_response_bytes + legacy_downloaded_bytes,
            legacy_quarantined_outcome_bytes_not_transfer_total=legacy_quarantined_bytes,
            uninstrumented_transfer_run_count=len(uninstrumented),
            **{f"outcomes_{k}": v for k, v in sorted(outcomes.items())},
        ),
        definitions={
            "scope": "All completed lane=paper acquisition receipts, "
            "including historical/cached attempts.",
            "contract_outcomes": "One terminal outcome per source per run; "
            "not HTTP request count or independent measurements.",
            "raw_unique_path_hash_objects": "Verified retained local paths and SHA256; "
            "copies at distinct paths count separately.",
            "raw_distinct_content_hashes": "Deduplicated byte content across those retained paths.",
            "instrumented_response_body_bytes": "Exact recorded response bodies, including failed "
            "attempts; excludes cached objects and HTTP headers.",
            "known_response_body_bytes_lower_bound": "Instrumented body bytes plus successful "
            "retained downloads from legacy runs lacking transfer metrics.",
            "legacy_quarantined_outcome_bytes_not_transfer_total": "May include rejected downloads "
            "or conflicting cached objects; never added to the transfer estimate.",
            "network_total": "Unknown for legacy uninstrumented runs; prefix probes "
            "and other non-acquisition requests excluded.",
        },
    )


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    checkpoint = inside(root, args.checkpoint)
    state = read(checkpoint)
    if state["status"] not in {"completed", "completed_with_unavailable_requests"} or state.get(
        "unattempted_batches"
    ):
        raise ValueError("bulk acquisition is not terminal and complete")
    if not state["decision"]["gate_passed"]:
        raise ValueError("final acquisition acceptance gate did not pass")
    aliases = semantic_inputs(args)
    packages = {
        name: package(
            root,
            getattr(args, name),
            primary,
            aliases if name in {"crosswalk", "design", "corpus"} else None,
        )
        for name, primary in PACKAGE_FILES.items()
    }
    waves = inside(root, args.waves)
    reproduction = read(waves / "reproduction.json")
    verify_map(root, reproduction["input_sha256"])
    if reproduction["input_sha256"].get(str(checkpoint.relative_to(root))) != sha(checkpoint):
        raise ValueError("final waveforms do not bind this terminal acquisition checkpoint")
    verify_foundation_membership(root, reproduction, len(packages["waves"]["manifest"]["sources"]))
    code_gate = inside(root, args.code_gate)
    code = read(code_gate)
    if code.get("status", "").casefold() != "pass" or not code.get("code_sha256"):
        raise ValueError("code gate is not a recorded pass with fingerprints")
    verify_map(root, code["code_sha256"])
    required = {entry["path"] for value in packages.values() for entry in value["files"]}
    provenance = inside(root, args.provenance)
    recipe = inside(root, reproduction["recipe"])
    required.update(
        str(path.relative_to(root)) for path in (provenance, code_gate, checkpoint, recipe)
    )
    acceptance = inside(root, args.acceptance)
    review = read(acceptance)
    verify_acceptance(root, review, required)
    acquisitions = acquisition_inventory(root, args.runs)
    # Reproduce the final paper ledger without writing it or changing the story ledger.
    sys.path.insert(0, str(root))
    from pipeline.provenance import validate_manifest
    from scripts.build_paper_manifest import build

    validate_manifest(provenance)
    with provenance.open(newline="") as stream:
        actual = list(csv.DictReader(stream))
    rebuilt = build(root, [root / r["run"] for r in acquisitions["runs"]])
    if actual != rebuilt:
        raise ValueError("final paper provenance differs from complete lane=paper receipts")
    file_records: dict[str, dict[str, Any]] = {}
    for value in packages.values():
        for entry in value["files"]:
            file_records[entry["path"]] = entry
        for path in value["verified_input_sha256"]:
            entry = fingerprint(root, inside(root, path))
            file_records[entry["path"]] = entry
    for path in {*reproduction["input_sha256"], *code["code_sha256"]}:
        entry = fingerprint(root, inside(root, path))
        file_records[entry["path"]] = entry
    for path in [checkpoint, code_gate, provenance, acceptance]:
        entry = fingerprint(root, path)
        file_records[entry["path"]] = entry
    for run in acquisitions["runs"]:
        for entry in run["evidence"]:
            file_records[entry["path"]] = entry
    metrics = {f"acquisition.{k}": v for k, v in acquisitions["metrics"].items()}
    for name, value in packages.items():
        for key, number in value["manifest"].items():
            if (
                isinstance(number, (int, float))
                and not isinstance(number, bool)
                and math.isfinite(number)
            ):
                metrics[f"{name}.{key}"] = number
    waveform_sources = packages["waves"]["manifest"]["sources"]
    metrics["waves.source_entries"] = len(waveform_sources)
    for label in ("processing_status", "purpose"):
        for value, count in Counter(s[label] for s in waveform_sources).items():
            metrics[f"waves.{label}.{value}"] = count
    metrics["waves.duplicate_timestamp_excess_retained"] = sum(
        s.get("duplicate_timestamp_excess", 0) for s in waveform_sources
    )
    metrics["waves.blank_value_rows_retained"] = sum(
        s.get("value_states", {}).get("blank", 0) for s in waveform_sources
    )
    metrics["provenance.source_records"] = len(actual)
    for key in ("python_tests_passed", "frontend_tests_previously_passed"):
        if key in code:
            metrics[f"code_gate.{key}"] = code[key]
    return dict(
        packages=packages,
        acquisitions=acquisitions,
        metrics=metrics,
        files=[file_records[k] for k in sorted(file_records)],
        checks=dict(
            package_inputs_and_outputs="verified",
            waveform_terminal_checkpoint="verified",
            current_code_gate_fingerprints="verified",
            paper_manifest_reproduction="exact",
            independent_acceptance=fingerprint(root, acceptance),
            independent_reviewer=review["reviewer"],
            declared_independent_checks=review["checks"],
        ),
    )


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def publish(args: argparse.Namespace, evidence: dict[str, Any]) -> dict[str, Any]:
    root = args.root.resolve()
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
    now = datetime.now(UTC)
    run_id = now.strftime("%Y-%m-%d__%H%M%S") + "__ntwc-foundation-final__" + git_sha[:7]
    destination = root / "artifacts/logs/runs" / run_id
    if destination.exists():
        raise FileExistsError(destination)
    stage = Path(tempfile.mkdtemp(prefix=".final-foundation-", dir=destination.parent))
    meta = dict(
        run_id=run_id,
        timestamp_utc=now.isoformat(),
        git_sha=git_sha,
        working_tree="dirty" if dirty else "clean",
        lane="paper-data-foundation",
        status="independently_accepted_descriptive_foundation",
        mlflow_status="not_attempted",
        command=[sys.executable, *sys.argv],
        boundaries="No physical-onset validation or model fit is implied; waveform rows "
        "are retained source records, not independent measurements.",
    )
    try:
        save_json(stage / "meta.json", meta)
        save_json(stage / "inputs.json", evidence["files"])
        save_json(
            stage / "outputs.json",
            {
                name: {k: value[k] for k in ("directory", "primary", "files")}
                for name, value in evidence["packages"].items()
            },
        )
        save_json(stage / "metrics.json", evidence["metrics"])
        save_json(stage / "acquisition-inventory.json", evidence["acquisitions"])
        save_json(stage / "verification.json", evidence["checks"])
        save_json(stage / "config.json", {k: str(v) for k, v in vars(args).items()})
        shutil.copyfile(__file__, stage / "record_evidence.py")
        for entry in [*evidence["files"], *evidence["acquisitions"]["raw_objects"]]:
            path = inside(root, entry["path"])
            if sha(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
                raise ValueError("evidence changed during consolidation")
        if not args.no_mlflow:
            try:
                os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
                os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "true")
                import mlflow

                mlflow.set_tracking_uri((root / ".mlflow/mlruns").as_uri())
                mlflow.set_experiment(args.experiment)  # pyright: ignore[reportUnknownMemberType]
                with mlflow.start_run(
                    run_name=run_id,
                    tags={
                        "git_sha": git_sha,
                        "lane": "paper-data-foundation",
                        "portable_run_bundle": str(destination.relative_to(root)),
                        "evidence_disposition": "independently_accepted_descriptive_foundation",
                    },
                ) as run:
                    meta.update(mlflow_status="logged", mlflow_run_id=run.info.run_id)
                    save_json(stage / "meta.json", meta)
                    mlflow.log_params(
                        {
                            "physical_onsets_validated": False,
                            "model_fit_performed": False,
                            "raw_accounting": "distinct_path_sha256_and_distinct_content_sha256",
                            "transfer_accounting": "instrumented_exact_and_legacy_lower_bound",
                            "independent_acceptance_sha256": evidence["checks"][
                                "independent_acceptance"
                            ]["sha256"],
                        }
                    )
                    mlflow.log_metrics(evidence["metrics"])
                    for name, value in evidence["packages"].items():
                        folder = (
                            "frozen" if name in {"audit", "comparison", "diagnostics"} else "final"
                        )
                        directory = root / value["directory"]
                        for filename in {
                            value["primary"],
                            "summary.json",
                            "reproduction.json",
                            "protocol.json",
                        }:
                            if (directory / filename).exists():
                                mlflow.log_artifact(
                                    str(directory / filename), artifact_path=f"{folder}/{name}"
                                )
                    for name in ("provenance", "code_gate", "acceptance", "checkpoint"):
                        mlflow.log_artifact(
                            str(inside(root, getattr(args, name))), artifact_path=f"checks/{name}"
                        )
                    mlflow.log_artifacts(str(stage), artifact_path="portable-run")
            except Exception as error:
                meta.update(
                    mlflow_status="failed_portable_evidence_retained", mlflow_error=str(error)
                )
                save_json(stage / "meta.json", meta)
        else:
            meta["mlflow_status"] = "explicitly_disabled_portable_only"
            save_json(stage / "meta.json", meta)
        if destination.exists():
            raise FileExistsError(destination)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return dict(bundle=str(destination.relative_to(root)), **meta)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--runs", type=Path, default=Path("artifacts/logs/runs"))
    parser.add_argument("--events", type=Path, default=Path("config/ntwc-archive-batch-v2.toml"))
    parser.add_argument(
        "--census", type=Path, default=Path("artifacts/generated/ntwc-batch/census-v4")
    )
    parser.add_argument(
        "--annotations", type=Path, default=Path("config/ntwc-event-annotations-v2.csv")
    )
    parser.add_argument(
        "--time-context", type=Path, default=Path("config/ntwc-reported-clock-context-v1.csv")
    )
    for name in [*PACKAGE_FILES, "provenance", "code-gate", "acceptance", "checkpoint"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--experiment", default="ntwc-arrival-foundation")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    evidence = prepare(args)
    if args.check_only:
        print(
            json.dumps(
                dict(status="ready_no_run_created", metrics=evidence["metrics"]), sort_keys=True
            )
        )
        return 0
    result = publish(args, evidence)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["mlflow_status"] == "failed_portable_evidence_retained" else 0


if __name__ == "__main__":
    raise SystemExit(main())
