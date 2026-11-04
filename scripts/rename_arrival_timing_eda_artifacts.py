"""Migrate EDA paths while preserving generation provenance and scientific bytes."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import sha256, write_json  # noqa: E402
from analysis.arrival.timing_artifact_names import (  # noqa: E402
    CODE_FILES,
    EDA_ROOT,
    FROZEN,
    LOCK,
    RESULTS,
    SOURCE_RENAMES,
    artifact_filename,
    migrated_artifact_path,
    rewrite_markdown_links,
)


def record_git_snapshot(root: Path) -> None:
    """Distinguish original Git blobs from accepted worktree bytes before renaming."""
    path = root / EDA_ROOT / "file-renames-and-content-checksums.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    requests = "".join(
        ledger["pre_rename_git_sha"] + ":" + r["old_path"] + "\n" for r in ledger["files"]
    )
    process = subprocess.run(
        ["git", "cat-file", "--batch"], input=requests.encode(), stdout=subprocess.PIPE, check=True
    )
    stream = io.BytesIO(process.stdout)
    differences: list[str] = []
    for row in ledger["files"]:
        header = stream.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("original Git snapshot member missing")
        original = stream.read(int(header[2]))
        assert stream.read(1) == b"\n"
        digest = hashlib.sha256(original).hexdigest()
        row["before_git_blob_sha256"] = digest
        if digest != row["before_sha256"]:
            accepted = (root / row["new_path"]).read_bytes()
            if hashlib.sha256(accepted).hexdigest() != row["before_sha256"] or (
                original.replace(b"\r\n", b"\n") != accepted.replace(b"\r\n", b"\n")
            ):
                raise ValueError("unexplained pre-existing Git/worktree difference")
            row["preexisting_git_difference"] = (
                "Embedded CRLF normalization in historical Git blob; accepted output "
                "manifest binds before_sha256, preserved byte-for-byte at new_path"
            )
            differences.append(row["old_path"])
    ledger["preexisting_git_line_ending_differences"] = differences
    write_json(path, ledger)


def refresh_replay_bindings(root: Path) -> None:
    """Bind the layout adapter separately from unchanged historical execution pins."""
    lock_path = root / LOCK
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["layout_replay_code"] = {p: sha256(root / p) for p in CODE_FILES}
    write_json(lock_path, lock)
    ledger_path = root / EDA_ROOT / "file-renames-and-content-checksums.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for row in ledger["files"]:
        digest = sha256(root / row["new_path"])
        old = Path(row["old_path"])
        mutable = (
            row.get("kind") in {"runtime-code", "test"}
            or old.name == "outputs.json"
            or str(old)
            in {
                "artifacts/eda/paper/freeze-v1/inputs.json",
                "artifacts/eda/paper/confirmation-lock.json",
                "artifacts/eda/paper/README.md",
                "artifacts/eda/paper/report.md",
                "artifacts/eda/paper/figures.md",
            }
        )
        if not mutable and digest != row["before_sha256"]:
            raise ValueError("immutable EDA payload changed: " + row["new_path"])
        row["after_sha256"] = digest
    ledger["layout_replay_code"] = lock["layout_replay_code"]
    write_json(ledger_path, ledger)


def migrate(root: Path) -> None:
    """Refuse collisions, preserve an ignored rollback copy, and move every artifact."""
    old_root = root / "artifacts/eda/paper"
    new_root = root / EDA_ROOT
    if new_root.exists():
        raise FileExistsError("descriptive EDA layout already exists")
    files = sorted(p for p in old_root.rglob("*") if p.is_file())
    files += [root / "config/paper-eda-v1.toml", root / "config/paper-eda-split-v1.toml"]
    files += [root / name for name in SOURCE_RENAMES]
    parent = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    rows: list[dict[str, Any]] = []
    for p in files:
        old = p.relative_to(root)
        new = migrated_artifact_path(old)
        if (root / new).exists():
            raise FileExistsError(new)
        row = {"old_path": str(old), "new_path": str(new), "before_sha256": sha256(p)}
        if str(old) in SOURCE_RENAMES:
            original = subprocess.check_output(["git", "show", parent + ":" + str(old)])
            row["pre_move_worktree_sha256"] = row["before_sha256"]
            row["before_sha256"] = hashlib.sha256(original).hexdigest()
            row["kind"] = "test" if str(old).startswith("tests/") else "runtime-code"
        rows.append(row)
    if len({r["new_path"] for r in rows}) != len(rows):
        raise ValueError("non-bijective EDA rename")
    backup = root / "artifacts/generated/paper-eda-renaming" / parent
    if backup.exists():
        raise FileExistsError(backup)
    backup.mkdir(parents=True)
    shutil.copytree(old_root, backup / "original-artifacts")
    for old in ["paper-eda-v1.toml", "paper-eda-split-v1.toml"]:
        shutil.copyfile(root / "config" / old, backup / old)
    for row in rows:
        old, new = root / row["old_path"], root / row["new_path"]
        if sha256(old) != row.get("pre_move_worktree_sha256", row["before_sha256"]):
            raise ValueError("source changed during rename")
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
    # Only documentation links, path manifests and active replay bindings change content.
    for row in rows:
        new = root / row["new_path"]
        if new.suffix == ".md":
            original = new.read_text(encoding="utf-8")
            updated = rewrite_markdown_links(original, Path(row["old_path"]), Path(row["new_path"]))
            if updated != original:
                new.write_text(updated, encoding="utf-8")
    for directory in sorted(old_root.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.rmdir()
    old_root.rmdir()
    source_manifest = root / FROZEN / "source-file-checksums.json"
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    original_input_sha = sha256(source_manifest)
    for pin in source["files"]:
        pin["path"] = str(migrated_artifact_path(Path(pin["path"])))
        if sha256(root / pin["path"]) != pin["sha256"]:
            raise ValueError("scientific input changed")
    source["pre_rename_manifest_sha256"] = original_input_sha
    write_json(source_manifest, source)
    lock_path = root / LOCK
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    original_lock_sha = sha256(lock_path)
    lock["artifact_root"] = str(root / RESULTS)
    lock["generation_inputs_sha256"] = lock["inputs_sha256"]
    lock["inputs_sha256"] = sha256(source_manifest)
    lock["pre_rename_lock_sha256"] = original_lock_sha
    lock["path_migration_manifest"] = str(EDA_ROOT / "file-renames-and-content-checksums.json")
    lock["generation_metadata_sha256"] = {}
    for metadata in (root / RESULTS).glob("*/*/original-run-metadata.json"):
        meta = json.loads(metadata.read_text(encoding="utf-8"))
        lock["generation_metadata_sha256"][meta["split"] + ":" + meta["module"]] = {
            name: sha256(metadata.parent / name)
            for name in [artifact_filename("meta.json"), artifact_filename("inputs.json")]
        }
    lock["layout_note"] = (
        "code retains original generation pins; layout_replay_code pins the path adapter. "
        "Replay regenerates scientific outputs and retains authentic generation metadata."
    )
    write_json(lock_path, lock)
    for checksums in new_root.rglob("output-file-checksums.json"):
        original = json.loads(checksums.read_text(encoding="utf-8"))
        expected: list[dict[str, str]] = []
        for row in original:
            name = artifact_filename(row["path"])
            if sha256(checksums.parent / name) != row["sha256"]:
                raise ValueError("scientific bundle member changed: " + name)
            expected.append({"path": name, "sha256": row["sha256"]})
        write_json(checksums, sorted(expected, key=lambda r: r["path"]))
    for row in rows:
        row["after_sha256"] = sha256(root / row["new_path"])
    write_json(
        root / EDA_ROOT / "file-renames-and-content-checksums.json",
        {
            "schema_version": "arrival_eda_path_migration_v1",
            "pre_rename_git_sha": parent,
            "scope": "paths, documentation links, checksum manifests and replay adapter only",
            "original_generation_metadata_preserved": True,
            "files": rows,
            "original_input_manifest_sha256": original_input_sha,
            "original_confirmation_lock_sha256": original_lock_sha,
            "rollback_copy": str(backup.relative_to(root)),
        },
    )
    refresh_replay_bindings(root)
    record_git_snapshot(root)
    print(f"Renamed {len(rows)} files; original scientific payloads preserved")


if __name__ == "__main__":
    migrate(Path.cwd())
