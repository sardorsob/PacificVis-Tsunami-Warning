"""Re-render fixed prior draws with numeric distance ordering; no new simulation."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, read_rows, sha256, write_json  # noqa: E402
from scripts.check_arrival_curvature_prior import VARIANTS, figures  # noqa: E402


def ordered_figures(rows, output):
    rows = sorted(rows, key=lambda r: float(r["distance_km"]))
    for variant in VARIANTS:
        groups = [
            [
                float(r["distance_km"])
                for r in rows
                if r["variant"] == variant and r["quantity"] == quantity
            ]
            for quantity in ["new_event", "conditional_median"]
        ]
        if not groups[0] or groups[0] != groups[1] or len(set(groups[0])) != len(groups[0]):
            raise ValueError("prior plot needs matching unique numeric distance grids")
    figures(rows, output)


def render(root, bundle, output):
    if not bundle.is_relative_to(root) or not output.is_relative_to(root) or output.exists():
        raise ValueError("existing project bundle and new project output required")
    original = json.loads((bundle / "inputs.json").read_text())
    pins = dict(original["files"])
    for name, expected in pins.items():
        if sha256(checked_path(root, name)) != expected:
            raise ValueError("original prior input changed")
    checks = json.loads((bundle / "output-checksums.json").read_text())
    for name, expected in checks.items():
        if sha256(checked_path(bundle, name)) != expected:
            raise ValueError("original prior output changed")
    copied = [*sorted(bundle.glob("*.csv")), bundle / "metrics.json", bundle / "saved-draws.json"]
    for path in [
        *copied,
        bundle / "inputs.json",
        bundle / "output-checksums.json",
        bundle / "findings.md",
    ]:
        pins[str(path.relative_to(root))] = sha256(path)
    pins["scripts/render_arrival_curvature_prior.py"] = sha256(
        root / "scripts/render_arrival_curvature_prior.py"
    )
    rows = read_rows(bundle / "new-event-duration-prior-quantiles.csv")
    output.mkdir(parents=True)
    for path in copied:
        shutil.copyfile(path, output / path.name)
    write_json(
        output / "inputs.json",
        {
            **original,
            "files": pins,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "ancestral_generation_git_sha": original["git_sha"],
            "original_bundle": str(bundle.relative_to(root)),
            "simulation_repeated": False,
            "report_change": "numeric distance ordering before line and area drawing",
        },
    )
    ordered_figures(rows, output)
    findings = (bundle / "findings.md").read_text()
    marker = "| Hypothesis |"
    findings = findings.replace(
        marker,
        "The following multipliers and probabilities are analytic prior quantities. "
        "The diagnostic CSV uses 2,000 finite ancestral draws, so its empirical "
        "fractions can differ.\n\n" + marker,
        1,
    )
    findings = findings[: findings.index("Reproduce:")] + (
        "The original render connected distances in text order. This version sorts "
        "distances numerically; every numerical table and saved ancestral array is "
        "unchanged.\n\nReproduce: `uv run --locked --offline python "
        "scripts/render_arrival_curvature_prior.py --bundle "
        + str(bundle.relative_to(root))
        + " --output <new-project-path>`. Ancestral generation remains reproducible "
        "with the original input manifest and source version.\n"
    )
    (output / "findings.md").write_text(findings)
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    render(project, (project / args.bundle).resolve(), (project / args.output).resolve())
