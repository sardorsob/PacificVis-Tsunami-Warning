"""Freeze accepted exploratory questions and their routes before confirmation."""

from __future__ import annotations

import json
from pathlib import Path

from analysis.arrival.evidence import sha256, write_json, write_rows


def lock(root: Path) -> None:
    out = root / "artifacts/eda/paper/confirmation-lock.json"
    if out.exists():
        raise FileExistsError(out)
    base = root / "artifacts/eda/paper/final-v1"
    modules = [f"C{i}" for i in range(1, 10)] + [f"B{i}" for i in range(1, 12)]
    code = json.loads((base / "exploration-C1/inputs.json").read_text())["code"]
    rows: list[dict[str, str]] = []
    routes: dict[str, dict[str, str]] = {}
    questions = modules[:9]
    for module in modules:
        bundle = base / ("exploration-" + module)
        pins = json.loads((bundle / "inputs.json").read_text())
        if pins["code"] != code or any(sha256(root / p) != h for p, h in code.items()):
            raise ValueError("exploration code drift")
        if not module.startswith("B"):
            continue
        summary = json.loads((bundle / "summary.json").read_text())
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
    write_rows(base / "exploration-branch-registry.csv", rows)
    write_json(
        out,
        {
            "schema_version": "paper_eda_confirmation_lock_v1",
            "code": code,
            "inputs_sha256": sha256(root / "artifacts/eda/paper/freeze-v1/inputs.json"),
            "artifact_root": str(base),
            "questions": questions,
            "routes": routes,
            "replication_rule": ("same direction and within factor 2, or interval overlap; "
                                 "inadequate support tentative"),
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
