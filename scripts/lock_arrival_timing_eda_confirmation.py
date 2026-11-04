"""Freeze accepted exploratory questions and their routes before confirmation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import sha256, write_json, write_rows  # noqa: E402
from analysis.arrival.timing_artifact_names import (  # noqa: E402
    artifact_filename,
    question_directory,
    result_path,
)


def lock(root: Path) -> None:
    out = root / "artifacts/eda/arrival-timing/frozen-confirmation-definition.json"
    if out.exists():
        raise FileExistsError(out)
    base = root / "artifacts/eda/arrival-timing/results"
    modules = [f"C{i}" for i in range(1, 10)] + [f"B{i}" for i in range(1, 12)]
    code = json.loads(
        (
            question_directory(base, "exploration", "C1") / artifact_filename("inputs.json")
        ).read_text()
    )["code"]
    rows: list[dict[str, str]] = []
    routes: dict[str, dict[str, str]] = {}
    questions = modules[:9]
    for module in modules:
        bundle = question_directory(base, "exploration", module)
        pins = json.loads((bundle / artifact_filename("inputs.json")).read_text())
        if pins["code"] != code or any(sha256(root / p) != h for p, h in code.items()):
            raise ValueError("exploration code drift")
        if not module.startswith("B"):
            continue
        summary = json.loads((bundle / artifact_filename("summary.json")).read_text())
        routes[module] = {}
        for target, result in summary.items():
            route = result["detail"].get("selected_route", "fixed_registered_screen")
            routes[module][target] = route
            rows.append(
                {
                    "branch": module,
                    "target": target,
                    "route": route,
                    "triggered": str(result["triggered"]),
                    "scalar": str(result["scalar"]),
                    "status": result["status"],
                }
            )
        if any(result["triggered"] for result in summary.values()):
            questions.append(module)
    write_rows(result_path(base, "exploration-branch-registry.csv"), rows)
    write_json(
        out,
        {
            "schema_version": "paper_eda_confirmation_lock_v1",
            "code": code,
            "inputs_sha256": sha256(
                root / "artifacts/eda/arrival-timing/frozen-inputs/source-file-checksums.json"
            ),
            "artifact_root": str(base),
            "questions": questions,
            "routes": routes,
            "replication_rule": (
                "same direction and within factor 2, or interval overlap; "
                "inadequate support tentative"
            ),
            "limits": [
                "archive-event split; one physical sequence crosses halves",
                "no blindness claim; small confirmation targets",
                "zero direct cross-family links; source contrasts confounded",
                "degenerate median-polish bootstrap ratios do not confirm group structure",
            ],
        },
    )
    print(out)


if __name__ == "__main__":
    lock(Path.cwd())
