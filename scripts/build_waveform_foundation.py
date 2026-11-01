"""Build an immutable waveform foundation only from a complete, pinned acquisition recipe."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import sys
import tempfile
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import load_contracts  # noqa: E402
from scripts.normalize_audit_waveforms import build  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(recipe: Path, root: Path) -> dict[str, Any]:
    """Resolve terminal checkpoints without downloading or publishing partial output."""
    root = root.resolve()
    recipe = recipe.resolve()
    document = tomllib.loads(recipe.read_text())
    hashes: dict[str, str] = {str(recipe.relative_to(root)): _sha(recipe)}

    def path(value: str, expected: str | None = None) -> Path:
        candidate = Path(value)
        if candidate.is_absolute() or not (root / candidate).resolve().is_relative_to(root):
            raise ValueError("recipe input path escapes project")
        digest = _sha(root / candidate)
        if expected is not None and digest != expected:
            raise ValueError(f"recipe input checksum mismatch: {value}")
        hashes[value] = digest
        return candidate

    fixed = document["fixed_sha256"]
    for value, digest in fixed.items():
        path(value, digest)
    common = {
        key: path(document[key], fixed[document[key]])
        for key in ("events", "selection", "known_catalog")
    }
    preflight_path = path(document["preflight"], fixed[document["preflight"]])
    preflight = json.loads((root / preflight_path).read_text())
    configs: list[Path] = []
    receipts: list[Path] = []
    headers: list[Path] = []
    for source in document["sources"]:
        config = path(source["config"], fixed[source["config"]])
        receipt = path(source["receipts"], fixed[source["receipts"]])
        if source["purpose"] not in {"source_samples", "header_evidence"}:
            raise ValueError("unknown recipe source purpose")
        configs.append(config)
        receipts.append(receipt)
        if source["purpose"] == "header_evidence":
            headers.append(config)

    providers: set[str] = set()
    for bulk in document["bulk"]:
        provider = bulk["provider"]
        if provider in providers or provider not in {"ia", "coops", "all"}:
            raise ValueError("duplicate or unknown bulk provider")
        providers.add(provider)
        checkpoint_path = path(bulk["checkpoint"])
        checkpoint = json.loads((root / checkpoint_path).read_text())
        if checkpoint["status"] not in {"completed", "completed_with_unavailable_requests"}:
            raise ValueError(f"acquisition is not terminal: {provider}/{checkpoint['status']}")
        if checkpoint["provider"] != provider or checkpoint["preflight_sha256"] != _sha(
            root / preflight_path
        ):
            raise ValueError("bulk checkpoint/preflight identity mismatch")
        expected = {
            str(preflight_path.parent / b["path"]): b
            for b in preflight["batches"]
            if provider == "all" or b["path"].startswith(provider + "-")
        }
        actual = {b["config"]: b for b in checkpoint["batches"]}
        if len(actual) != len(checkpoint["batches"]) or set(actual) != set(expected):
            raise ValueError("bulk checkpoint omits or duplicates a preflight batch")
        for name, batch in sorted(actual.items()):
            config = path(name, expected[name]["sha256"])
            run = Path(batch["run"])
            if not run.is_relative_to(Path("artifacts/logs/runs")) or ".." in run.parts:
                raise ValueError("bulk receipt is outside run evidence")
            required_hashes = {name} | {
                str(run / item)
                for item in ("config.json", "inputs.json", "outputs.json", "metrics.json")
            }
            batch_hashes = batch.get("input_sha256", {})
            if set(batch_hashes) != required_hashes:
                raise ValueError("bulk checkpoint lacks complete captured-input hashes")
            for value, digest in batch_hashes.items():
                path(value, digest)
            receipt = path(str(run / "outputs.json"))
            inputs = path(str(run / "inputs.json"))
            metrics_path = path(str(run / "metrics.json"))
            captured_config = json.loads((root / path(str(run / "config.json"))).read_text())
            if (
                captured_config["sha256"] != expected[name]["sha256"]
                or hashlib.sha256(captured_config["toml"].encode()).hexdigest()
                != expected[name]["sha256"]
            ):
                raise ValueError("bulk captured config differs from pinned preflight")
            outcomes = json.loads((root / receipt).read_text())
            contracts = load_contracts(root / config)
            captured = json.loads((root / inputs).read_text())
            captured_by_id = {c["source_id"]: c for c in captured}
            if len(contracts) != expected[name]["contracts"] or len(captured_by_id) != len(
                captured
            ):
                raise ValueError("bulk contract count or captured input identity differs")
            if set(captured_by_id) != {c.source_id for c in contracts}:
                raise ValueError("bulk captured inputs differ from approved contract")
            for contract in contracts:
                identity = dict(
                    url=contract.url,
                    local_path=str(contract.local_path),
                    expected_prefix=contract.expected_prefix,
                )
                if contract.expected_cdx_sha1:
                    identity.update(
                        expected_cdx_sha1=contract.expected_cdx_sha1,
                        cdx_evidence_path=contract.cdx_evidence_path,
                        cdx_evidence_sha256=contract.cdx_evidence_sha256,
                    )
                if any(captured_by_id[contract.source_id].get(k) != v for k, v in identity.items()):
                    raise ValueError("bulk captured source identity differs from contract")
            counts = dict(Counter(o["status"] for o in outcomes))
            metrics = json.loads((root / metrics_path).read_text())
            if (
                counts != batch["status_counts"]
                or counts != metrics["status_counts"]
                or metrics["total_contracts"] != len(contracts)
                or not set(counts) <= {"cached", "downloaded", "quarantined", "skipped", "blocked"}
            ):
                raise ValueError("bulk status accounting differs from receipt")
            configs.append(config)
            receipts.append(receipt)
    expected_providers = {b["path"].split("-", 1)[0] for b in preflight["batches"]}
    if providers != {"all"} and providers != expected_providers:
        raise ValueError("recipe omits a preflight provider")

    source_ids: set[str] = set()
    for config, receipt in zip(configs, receipts, strict=True):
        contracts = load_contracts(root / config)
        outcomes = json.loads((root / receipt).read_text())
        ids = {c.source_id for c in contracts}
        if (
            source_ids & ids
            or len(outcomes) != len(ids)
            or {o["source_id"] for o in outcomes} != ids
        ):
            raise ValueError("source attempt identities are duplicated or incomplete")
        source_ids.update(ids)
    if len(source_ids) != document["expected_source_entries"]:
        raise ValueError("final source count differs from frozen recipe")
    history: list[dict[str, Any]] = []
    for run_value in document.get("historical_runs", []):
        run = Path(run_value)
        before = path(str(run / "inputs.json"), fixed[str(run / "inputs.json")])
        after = path(str(run / "outputs.json"), fixed[str(run / "outputs.json")])
        inputs = json.loads((root / before).read_text())
        outcomes = json.loads((root / after).read_text())
        ids = {o["source_id"] for o in outcomes}
        if len(ids) != len(outcomes) or ids != {i["source_id"] for i in inputs}:
            raise ValueError("historical attempt accounting differs")
        history.append(
            dict(
                run=run_value,
                attempts=len(outcomes),
                status_counts=dict(Counter(o["status"] for o in outcomes)),
                source_ids=sorted(ids),
                use="historical_attempts_only_not_additional_sample_sources",
            )
        )
    return dict(
        configs=configs,
        receipts=receipts,
        header_evidence_configs=headers,
        **common,
        input_sha256=hashes,
        source_entries=len(source_ids),
        history=history,
    )


def build_foundation(recipe: Path, root: Path, output: Path) -> dict[str, Any]:
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(output)
    prepared = prepare(recipe, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".waveform-foundation-", dir=output.parent))
    try:
        with contextlib.chdir(root):
            summary = build(
                prepared["configs"],
                prepared["receipts"],
                prepared["events"],
                root,
                stage / "data",
                selection=prepared["selection"],
                known_catalog=prepared["known_catalog"],
                retain_unparsed=True,
                header_evidence_configs=prepared["header_evidence_configs"],
            )
        if len(summary["sources"]) != prepared["source_entries"]:
            raise ValueError("normalized source accounting differs from complete recipe")
        evidence = dict(
            recipe=str(recipe.resolve().relative_to(root)),
            input_sha256=prepared["input_sha256"],
            source_entries=prepared["source_entries"],
            historical_runs=prepared["history"],
            processing_status_counts=dict(
                Counter(s["processing_status"] for s in summary["sources"])
            ),
            purpose_counts=dict(Counter(s["purpose"] for s in summary["sources"])),
            source_rows=summary["source_rows"],
        )
        for value, digest in prepared["input_sha256"].items():
            if _sha(root / value) != digest:
                raise ValueError("recipe input changed during normalization")
        (stage / "data/reproduction.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        )
        if output.exists():
            raise FileExistsError(output)
        (stage / "data").rename(output)
    finally:
        shutil.rmtree(stage)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_only:
            ready = prepare(args.recipe, args.root)
            print(json.dumps(dict(status="ready", source_entries=ready["source_entries"])))
        elif args.output is None:
            parser.error("--output is required unless --check-only")
        else:
            result = build_foundation(args.recipe, args.root, args.output)
            print(json.dumps({k: result[k] for k in ("source_entries", "source_rows")}))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Waveform foundation not built: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
