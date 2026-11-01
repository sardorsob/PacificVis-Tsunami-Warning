"""Final normalization requires the exact complete, frozen acquisition recipe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_waveform_foundation import build_foundation, prepare
from scripts.continue_waveform_acquisition import batch_record, sha
from tests.test_waveform_continuation import portable_run


def recipe_fixture(tmp_path: Path) -> Path:
    preflight, config, run = portable_run(tmp_path)
    checkpoint = dict(
        provider="all", status="completed", preflight_sha256=sha(tmp_path / preflight),
        batches=[batch_record(tmp_path, preflight, config, run)],
    )
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))
    (tmp_path / "selection.json").write_text("{}")
    (tmp_path / "catalog.csv").write_text("id,time\n")
    common = dict(events="events.toml", selection="selection.json", known_catalog="catalog.csv",
                  preflight=str(preflight))
    lines = ["expected_source_entries=1", "sources=[]"]
    lines += [f"{k}={json.dumps(v)}" for k, v in common.items()]
    lines += ["[[bulk]]", 'provider="all"', 'checkpoint="checkpoint.json"', "[fixed_sha256]"]
    lines += [f"{json.dumps(v)}={json.dumps(sha(tmp_path / v))}" for v in common.values()]
    recipe = tmp_path / "recipe.toml"
    recipe.write_text("\n".join(lines) + "\n")
    return recipe


def test_complete_all_provider_recipe_captures_every_run_evidence_hash(tmp_path: Path) -> None:
    recipe = recipe_fixture(tmp_path)
    result = prepare(recipe, tmp_path)
    assert result["source_entries"] == 1
    assert result["configs"] == [Path("source.toml")]
    for name in ("config.json", "inputs.json", "outputs.json", "metrics.json"):
        path = f"artifacts/logs/runs/fixture/{name}"
        assert result["input_sha256"][path] == sha(tmp_path / path)
    assert result["header_evidence_configs"] == []


@pytest.mark.parametrize("violation", [
    "running", "missing_batch", "duplicate_batch", "wrong_input_url", "wrong_config",
    "missing_outcome", "wrong_status_count", "changed_common", "wrong_source_count",
    "missing_batch_hashes", "partial_batch_hashes", "wrong_total", "nonterminal_outcome",
])
def test_incomplete_or_mutated_recipe_never_publishes_partial_foundation(
    tmp_path: Path, violation: str
) -> None:
    recipe = recipe_fixture(tmp_path)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    if violation == "running":
        checkpoint["status"] = "running"
    elif violation == "missing_batch":
        checkpoint["batches"] = []
    elif violation == "duplicate_batch":
        checkpoint["batches"] *= 2
    elif violation == "wrong_status_count":
        checkpoint["batches"][0]["status_counts"] = dict(cached=1)
    elif violation == "missing_batch_hashes":
        checkpoint["batches"][0].pop("input_sha256")
    elif violation == "partial_batch_hashes":
        checkpoint["batches"][0]["input_sha256"].pop("source.toml")
    elif violation in {"wrong_total", "nonterminal_outcome"}:
        run = Path("artifacts/logs/runs/fixture")
        path = run / "metrics.json"
        metrics = json.loads((tmp_path / path).read_text())
        if violation == "wrong_total":
            metrics["total_contracts"] = 999
        else:
            outcomes = run / "outputs.json"
            rows = json.loads((tmp_path / outcomes).read_text())
            rows[0]["status"] = "running"
            (tmp_path / outcomes).write_text(json.dumps(rows))
            checkpoint["batches"][0]["input_sha256"][str(outcomes)] = sha(tmp_path / outcomes)
            metrics["status_counts"] = dict(running=1)
            checkpoint["batches"][0]["status_counts"] = dict(running=1)
        (tmp_path / path).write_text(json.dumps(metrics))
        checkpoint["batches"][0]["input_sha256"][str(path)] = sha(tmp_path / path)
    elif violation == "changed_common":
        (tmp_path / "catalog.csv").write_text("different")
    elif violation == "wrong_source_count":
        recipe.write_text(recipe.read_text().replace(
            "expected_source_entries=1", "expected_source_entries=2"
        ))
    else:
        run = tmp_path / "artifacts/logs/runs/fixture"
        if violation == "wrong_input_url":
            path = run / "inputs.json"
            rows = json.loads(path.read_text())
            rows[0]["url"] = "https://example.test/wrong"
        elif violation == "wrong_config":
            path = run / "config.json"
            rows = json.loads(path.read_text())
            rows["toml"] += "\n# changed\n"
        else:
            path = run / "outputs.json"
            rows = []
        path.write_text(json.dumps(rows))
    checkpoint_path.write_text(json.dumps(checkpoint))
    output = tmp_path / "foundation"
    with pytest.raises(ValueError):
        build_foundation(recipe, tmp_path, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".waveform-foundation-*"))


def test_existing_foundation_is_never_overwritten(tmp_path: Path) -> None:
    recipe = recipe_fixture(tmp_path)
    output = tmp_path / "foundation"
    output.mkdir()
    (output / "manifest.json").write_text("preserved")
    with pytest.raises(FileExistsError):
        build_foundation(recipe, tmp_path, output)
    assert (output / "manifest.json").read_text() == "preserved"
