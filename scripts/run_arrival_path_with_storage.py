"""Apply the frozen path runner one node at a time, accounting for prior external stores."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256  # noqa: E402


def audit_storage(root, spec, store):
    """Enforce the same global cap over original and independently resolved raw stores."""
    snapshot = checked_path(root, spec["previous_resolutions_snapshot"])
    if spec["files"].get(str(snapshot.relative_to(root))) != sha256(snapshot):
        raise ValueError("immutable previous-resolution snapshot required")
    records = json.loads(snapshot.read_text())
    live_registry = checked_path(root, spec["parent_output"]) / "reviewed-resolutions.json"
    if json.loads(live_registry.read_text()) != records:
        raise ValueError("live parent numerical registry changed")
    extra = []
    for record in records.values():
        receipt = checked_path(root, record["path"])
        if (
            spec["files"].get(record["path"]) != record["sha256"]
            or sha256(receipt) != record["sha256"]
        ):
            raise ValueError("pinned previous numerical acceptance required")
        qa = json.loads(receipt.read_text())
        if qa["status"] != "accepted_same_model_fold_resolution" or not qa["independent_checker"]:
            raise ValueError("accepted previous numerical stores required")
        for name in qa["additional_raw_stores"]:
            folder = checked_path(root, name)
            prefix = str(folder.relative_to(root)) + "/"
            expected = {p: h for p, h in qa["files"].items() if p.startswith(prefix)}
            actual = {str(p.relative_to(root)) for p in folder.rglob("*") if p.is_file()}
            if not folder.is_dir() or not expected or actual != set(expected):
                raise ValueError("complete pinned previous external raw store required")
            for p, h in expected.items():
                if sha256(checked_path(root, p)) != h:
                    raise ValueError("previous external posterior changed")
            extra.append(folder)
    folders = [store, *[checked_path(root, p) for p in spec["prior_raw_stores"]], *extra]
    if len(folders) != len(set(folders)) or any(
        a.is_relative_to(b) or b.is_relative_to(a)
        for j, a in enumerate(folders)
        for b in folders[j + 1 :]
    ):
        raise ValueError("disjoint global raw stores required")
    size = checked_path(root, spec["external_endpoint"]).stat().st_size + sum(
        p.stat().st_size for folder in folders for p in folder.rglob("*") if p.is_file()
    )
    if size + 3 * 64 * 1024**2 > spec["max_raw_bytes"]:
        raise ValueError("global raw storage budget exhausted before next path node")
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["design", "output", "store", "state"]:
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--max-cases", type=int, default=32)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    design, output, store, state = [
        checked_path(root, str(getattr(args, n))) for n in ["design", "output", "store", "state"]
    ]
    if not 1 <= args.max_cases <= 32:
        raise ValueError("bounded invocation of at most thirty-two nodes required")
    spec = json.loads(design.read_text())
    own = str(Path(__file__).resolve().relative_to(root))
    if spec["files"].get(own) != sha256(Path(__file__).resolve()):
        raise ValueError("reviewed storage guardian source required")
    for _ in range(args.max_cases):
        if state.exists():
            saved = json.loads(state.read_text())
            if saved["status"] == "computations_complete":
                return
            if (
                saved["status"] not in {"invocation_limit", "prepared"}
                or saved["current"] is not None
            ):
                raise ValueError("stopped or unfinished path needs independent reconciliation")
        audit_storage(root, spec, store)
        command = [
            sys.executable,
            str(root / "scripts/run_arrival_sequence_path.py"),
            "--design",
            str(design),
            "--output",
            str(output),
            "--store",
            str(store),
            "--state",
            str(state),
            "--max-cases",
            "1",
        ]
        if state.exists():
            command.append("--resume")
        # The child has a 600s process-group guardian and an absolute32-call ceiling.
        subprocess.run(command, check=True, cwd=root)
        saved = json.loads(state.read_text())
        if saved["status"] not in {"invocation_limit", "computations_complete"}:
            raise ValueError("path stopped; retain evidence and request scientific review")


if __name__ == "__main__":
    main()
