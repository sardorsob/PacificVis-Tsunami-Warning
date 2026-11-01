from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import record_ntwc_foundation_final as writer


def receipt(root: Path, name: str, rows: list[dict[str, Any]], transfer: int | None) -> Path:
    run = root / "artifacts/logs/runs" / name
    run.mkdir(parents=True)
    values: dict[str, Any] = {
        "meta.json": {"lane": "paper"},
        "config.json": {"toml": "[assets]\n", "sha256": hashlib.sha256(b"[assets]\n").hexdigest()},
        "inputs.json": [{"source_id": r["source_id"], "local_path": r["local_path"]} for r in rows],
        "outputs.json": rows,
        "metrics.json": {
            "status_counts": dict(Counter(r["status"] for r in rows)),
            "total_contracts": len(rows),
            "total_outcomes": len(rows),
        },
    }
    if transfer is not None:
        values["metrics.json"]["transfer_budget"] = {"received_response_bytes": transfer}
    for filename, value in values.items():
        writer.save_json(run / filename, value)
    return run


def raw(root: Path, name: str, source_id: str, status: str) -> dict[str, Any]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"same bytes")
    digest = writer.sha(path)
    path.with_name(path.name + ".sha256").write_text(digest)
    return dict(source_id=source_id, local_path=name, status=status, bytes=10, sha256=digest)


def test_duplicate_snapshots_and_download_traffic_have_distinct_accounting(tmp_path: Path) -> None:
    row = raw(tmp_path, "raw/a", "a", "downloaded")
    receipt(tmp_path, "a", [row], None)
    receipt(tmp_path, "b", [dict(row, status="cached")], 0)
    second = raw(tmp_path, "raw/b", "b", "downloaded")
    rejected = dict(
        source_id="c",
        local_path="raw/absent",
        status="quarantined",
        bytes=30,
        sha256="not-downloaded",
    )
    receipt(tmp_path, "c", [second, rejected], 40)
    result = writer.acquisition_inventory(tmp_path, Path("artifacts/logs/runs"))
    metrics = result["metrics"]
    assert metrics["contract_outcomes"] == 4
    assert metrics["raw_unique_path_hash_objects"] == 2
    assert metrics["raw_unique_path_bytes"] == 20
    assert metrics["raw_distinct_content_hashes"] == 1
    assert metrics["raw_distinct_content_bytes"] == 10
    assert metrics["instrumented_response_body_bytes"] == 40
    assert metrics["legacy_retained_download_bytes_lower_bound"] == 10
    assert metrics["known_response_body_bytes_lower_bound"] == 50
    assert metrics["never_retained_source_ids"] == 1
    assert metrics["uninstrumented_transfer_run_count"] == 1


@pytest.mark.parametrize("mutation", ["raw", "sidecar", "total", "ids", "nonterminal"])
def test_bad_raw_or_nonterminal_receipts_are_rejected(tmp_path: Path, mutation: str) -> None:
    row = raw(tmp_path, "raw/a", "a", "downloaded")
    run = receipt(tmp_path, "a", [row], 10)
    if mutation == "raw":
        (tmp_path / "raw/a").write_bytes(b"changed")
    elif mutation == "sidecar":
        (tmp_path / "raw/a.sha256").write_text("incorrect")
    elif mutation == "total":
        value = writer.read(run / "metrics.json")
        value["total_contracts"] = 999
        writer.save_json(run / "metrics.json", value)
    elif mutation == "ids":
        writer.save_json(run / "inputs.json", [])
    else:
        row["status"] = "running"
        writer.save_json(run / "outputs.json", [row])
    with pytest.raises(ValueError):
        writer.acquisition_inventory(tmp_path, Path("artifacts/logs/runs"))


def test_legacy_quarantined_bytes_are_not_invented_as_network_transfer(tmp_path: Path) -> None:
    row = dict(
        source_id="a",
        local_path="raw/absent",
        status="quarantined",
        bytes=30,
        sha256="not-downloaded",
    )
    receipt(tmp_path, "a", [row], None)
    result = writer.acquisition_inventory(tmp_path, Path("artifacts/logs/runs"))["metrics"]
    assert result["legacy_quarantined_outcome_bytes_not_transfer_total"] == 30
    assert result["known_response_body_bytes_lower_bound"] == 0


def test_running_checkpoint_blocks_before_final_artifacts_or_mlflow(tmp_path: Path) -> None:
    writer.save_json(tmp_path / "checkpoint.json", {"status": "running"})
    with pytest.raises(ValueError, match="not terminal"):
        writer.prepare(argparse.Namespace(root=tmp_path, checkpoint=Path("checkpoint.json")))
    assert not (tmp_path / "artifacts").exists()


def test_package_manifest_cannot_escape_or_silently_ignore_bad_hash(tmp_path: Path) -> None:
    directory = tmp_path / "package"
    directory.mkdir()
    (tmp_path / "outside").write_text("outside")
    writer.save_json(
        directory / "manifest.json",
        {"output_sha256": {"../outside": writer.sha(tmp_path / "outside")}},
    )
    with pytest.raises(ValueError, match="escapes package"):
        writer.package(tmp_path, directory, "manifest.json")
    writer.save_json(directory / "manifest.json", {"output_sha256": {"data": "bad"}})
    (directory / "data").write_text("source")
    with pytest.raises(ValueError, match="checksum"):
        writer.package(tmp_path, directory, "manifest.json")


@pytest.mark.parametrize("role", ["crosswalk", "design", "corpus"])
def test_real_semantic_input_schemas_resolve_and_verify(tmp_path: Path, role: str) -> None:
    args = argparse.Namespace(
        events=Path("events.toml"),
        census=Path("census"),
        annotations=Path("annotations.csv"),
        crosswalk=Path("crosswalk"),
        time_context=Path("time-context.csv"),
    )
    aliases = writer.semantic_inputs(args)
    fields = {
        "crosswalk": ["events_config", "rows", "links"],
        "design": ["annotations", "census", "config", "crosswalk", "links", "rows"],
        "corpus": ["census", "config", "crosswalk", "rows", "time_context"],
    }[role]
    for path in aliases.values():
        source = tmp_path / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(str(path))
    directory = tmp_path / "package"
    directory.mkdir()
    primary = writer.PACKAGE_FILES[role]
    writer.save_json(
        directory / primary,
        {
            "input_sha256": {key: writer.sha(tmp_path / aliases[key]) for key in fields},
            "contract_sha256": {"events.toml": writer.sha(tmp_path / "events.toml")},
        },
    )
    result = writer.package(tmp_path, directory, primary, aliases)
    assert "events.toml" in result["verified_input_sha256"]
    assert set(result["verified_input_sha256"]) == {str(aliases[k]) for k in fields}
    (tmp_path / "events.toml").write_text("mutated")
    with pytest.raises(ValueError, match="checksum"):
        writer.package(tmp_path, directory, primary, aliases)


def test_acceptance_binds_every_package_member_including_unlisted_outputs(tmp_path: Path) -> None:
    for name in ("connectivity.json", "pull_list.csv"):
        (tmp_path / name).write_text(name)
    required = {"connectivity.json", "pull_list.csv"}
    review: dict[str, Any] = dict(
        status="pass",
        reviewer="independent",
        checks=["replayed all files"],
        artifact_sha256={"connectivity.json": writer.sha(tmp_path / "connectivity.json")},
    )
    with pytest.raises(ValueError, match="every required"):
        writer.verify_acceptance(tmp_path, review, required)
    review["artifact_sha256"]["pull_list.csv"] = writer.sha(tmp_path / "pull_list.csv")
    writer.verify_acceptance(tmp_path, review, required)
    (tmp_path / "pull_list.csv").write_text("mutated after acceptance")
    with pytest.raises(ValueError, match="checksum"):
        writer.verify_acceptance(tmp_path, review, required)


def test_completed_flag_cannot_replace_complete_pinned_batch_membership(tmp_path: Path) -> None:
    from scripts.build_waveform_foundation import prepare
    from tests.test_waveform_foundation import recipe_fixture

    recipe = recipe_fixture(tmp_path)
    result = prepare(recipe, tmp_path)
    reproduction: dict[str, Any] = dict(recipe="recipe.toml", input_sha256=result["input_sha256"])
    writer.verify_foundation_membership(tmp_path, reproduction, 1)
    checkpoint = writer.read(tmp_path / "checkpoint.json")
    checkpoint["batches"] = []
    writer.save_json(tmp_path / "checkpoint.json", checkpoint)
    # Even repinning the forged completed checkpoint cannot hide absent preflight batches.
    reproduction["input_sha256"]["checkpoint.json"] = writer.sha(tmp_path / "checkpoint.json")
    with pytest.raises(ValueError):
        writer.verify_foundation_membership(tmp_path, reproduction, 1)


def test_mlflow_manifest_names_are_separated_and_portable_bundle_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts/logs/runs").mkdir(parents=True)
    packages: dict[str, Any] = {}
    for name in ("waves", "catalog", "audit", "comparison", "diagnostics"):
        directory = tmp_path / name
        directory.mkdir()
        writer.save_json(directory / "manifest.json", {"role": name})
        packages[name] = dict(directory=name, primary="manifest.json", files=[])
    checks = ["provenance", "code_gate", "acceptance", "checkpoint"]
    for name in checks:
        writer.save_json(tmp_path / (name + ".json"), {})
    logged: list[tuple[str, str]] = []

    def log_artifact(path: str, artifact_path: str) -> None:
        logged.append((Path(path).name, artifact_path))

    def no_op(*args: Any, **kwargs: Any) -> None:
        pass

    @contextmanager
    def start(*args: Any, **kwargs: Any):
        yield SimpleNamespace(info=SimpleNamespace(run_id="fixture"))

    fake = SimpleNamespace(
        set_tracking_uri=no_op,
        set_experiment=no_op,
        start_run=start,
        log_params=no_op,
        log_metrics=no_op,
        log_artifact=log_artifact,
        log_artifacts=no_op,
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake)

    def command(args: list[str], **kwargs: Any) -> str:
        return "c4d5044" if "rev-parse" in args else "dirty"

    monkeypatch.setattr(writer.subprocess, "check_output", command)
    args = argparse.Namespace(
        root=tmp_path,
        no_mlflow=False,
        experiment="fixture",
        **{n: Path(n + ".json") for n in checks},
    )
    evidence = dict(
        packages=packages,
        files=[],
        metrics={},
        acquisitions={"raw_objects": []},
        checks={"independent_acceptance": {"sha256": "fixture"}},
    )
    result = writer.publish(args, evidence)
    assert result["mlflow_status"] == "logged"
    targets = [folder for filename, folder in logged if filename == "manifest.json"]
    assert len(targets) == len(set(targets)) == 5
    assert "final/waves" in targets and "frozen/audit" in targets
    assert (tmp_path / result["bundle"] / "record_evidence.py").is_file()
