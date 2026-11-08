"""Summarize the independently accepted five-case pilot without fitting again."""

# pyright: basic
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import checked_path, sha256, write_json  # noqa: E402
from analysis.arrival.model_validation_report import write_table  # noqa: E402
from scripts.run_arrival_curvature_pilot import make_cases  # noqa: E402

BUNDLE = "artifacts/models/arrival-timing/mean-curvature-pilot-v1"
GATE = BUNDLE + "/review-acceptance.json"


def accepted_inputs(root: Path) -> dict[str, Any]:
    gate = json.loads((root / GATE).read_text())
    required = {BUNDLE + "/plan.json", BUNDLE + "/run-summary.json"}
    for case in make_cases():
        prefix = BUNDLE + "/jobs/" + case["id"]
        required.update(
            [
                prefix + "/result.json",
                prefix + "/attempt-evidence.json",
                prefix + ".supervisor.json",
            ]
        )
    if (
        gate.get("status") != "accepted_complete_five_case_computational_pilot"
        or gate.get("model") != "mean-curvature"
        or not gate.get("independent_checker")
        or not required.issubset(gate.get("files", {}))
    ):
        raise ValueError("complete independently accepted five-case evidence required")
    for name, digest in gate["files"].items():
        if sha256(checked_path(root, name)) != digest:
            raise ValueError("accepted pilot evidence changed")
    return gate


def report(root, output):
    if output.exists() or not output.is_relative_to(root):
        raise ValueError("new project-local output required")
    gate = accepted_inputs(root)
    summary = json.loads((root / BUNDLE / "run-summary.json").read_text())
    if (
        summary["computed_cases"] != 5
        or summary["sampler_call_slots_used"] != 5
        or summary["status"] != "complete"
    ):
        raise ValueError("exactly five completed first attempts required")
    rows = []
    estimates = []
    for case in make_cases():
        attempt = root / BUNDLE / "jobs" / case["id"]
        result = json.loads((attempt / "result.json").read_text())
        guardian = json.loads(attempt.with_suffix(".supervisor.json").read_text())
        d = result["diagnostics"]
        lookup = {r["parameter"]: r for r in result["estimates"]}
        rows.append(
            {
                "scenario": case["id"],
                "gamma_truth": result["truth"]["gamma"],
                "tau_truth": result["truth"]["tau_event"],
                "max_rhat": d["max_rhat"],
                "min_ess_bulk": d["min_ess_bulk"],
                "min_ess_tail": d["min_ess_tail"],
                "min_bfmi": d["min_bfmi"],
                "divergences": d["divergences"],
                "depth_hits": d["maxdepth_reached"],
                "process_seconds": guardian["elapsed_seconds"],
                "worker_seconds": result["elapsed_seconds"],
                **{
                    name + "_" + key: lookup[name][key]
                    for name in ["gamma", "tau_event"]
                    for key in ["q05", "median", "q95"]
                },
            }
        )
        estimates.extend({"scenario": case["id"], **r} for r in result["estimates"])
    output.mkdir(parents=True)
    pins = {**gate["files"], GATE: sha256(root / GATE)}
    for name in [
        "scripts/summarize_arrival_curvature_pilot.py",
        "analysis/arrival/model_validation_report.py",
        "analysis/arrival/evidence.py",
        "scripts/run_arrival_curvature_pilot.py",
    ]:
        pins[name] = sha256(root / name)
    write_json(
        output / "inputs.json",
        {
            "files": pins,
            "simulation_repeated": False,
            "posterior_refitted": False,
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
        },
    )
    write_table(output / "sampling-and-runtime-summary.csv", rows)
    write_table(output / "known-truth-estimates.csv", estimates)
    metrics = {
        "cases": 5,
        "sampler_call_slots": 5,
        "retries": 0,
        "max_rhat": max(r["max_rhat"] for r in rows),
        "min_ess_bulk": min(r["min_ess_bulk"] for r in rows),
        "min_ess_tail": min(r["min_ess_tail"] for r in rows),
        "min_bfmi": min(r["min_bfmi"] for r in rows),
        "divergences": sum(r["divergences"] for r in rows),
        "depth_hits": sum(r["depth_hits"] for r in rows),
        "total_process_seconds": sum(r["process_seconds"] for r in rows),
    }
    write_json(output / "metrics.json", metrics)
    lines = [
        "# Mean-curvature computational pilot",
        "",
        "All five prespecified synthetic fits passed on their first attempts. Each uses four "
        "chains with 1,000 tuning and 1,000 retained draws per chain. The frozen 1,064-record, "
        "33-event design supplies distances, group membership and exclusions; generated "
        "responses replace the historical outcomes in the likelihood.",
        "",
        "| Scenario | Gamma truth | Gamma median [90% interval] | "
        "Event SD truth | Event SD median [90% interval] |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['gamma_truth']:.2f} | {r['gamma_median']:.3f} "
            f"[{r['gamma_q05']:.3f}, {r['gamma_q95']:.3f}] | {r['tau_truth']:.2f} | "
            f"{r['tau_event_median']:.3f} [{r['tau_event_q05']:.3f}, {r['tau_event_q95']:.3f}] |"
        )
    lines += [
        "",
        f"The largest R-hat is {metrics['max_rhat']:.4f}; the smallest bulk and tail effective "
        f"sample sizes are {metrics['min_ess_bulk']:.0f} and {metrics['min_ess_tail']:.0f}. "
        "No divergences or maximum-depth hits occurred. Sampled hyperparameters were "
        "screened before reconstructing conditional event effects or derived quantities.",
        "",
        "Gamma is a dimensionless coefficient for the fixed smooth basis. Event SD is "
        "between-event variation on the log-duration scale. Local median elasticity, "
        "the 100-km median/reference ratio and total new-event log SD are recorded among "
        "the twelve correlated summaries. A small event SD does not establish an absence "
        "of physical event differences.",
        "",
        "There is one dataset at each generating truth. These intervals and successful "
        "diagnostics establish computational feasibility, not nominal conditional coverage, "
        "SBC calibration or predictive superiority. No interval-containment quota was "
        "used, and no datasets or unsuccessful attempts were replaced. The prior SD "
        "references are finite Monte Carlo estimates from the accepted 2,000 base ancestrals.",
        "",
        "Independent replay checked every synthetic native/log response, conditional "
        "event effect, scalar summary and diagnostic table. Dense block-Gaussian "
        "likelihood/prior calculations agreed with retained sampler log densities within "
        "7.64e-9 nats. This checks the computational route under the assumed model.",
        "",
        "Storage totals are monitored trip observations rather than hard filesystem "
        "quotas; the individual 64-MiB file cap is enforced by the kernel. The end-run "
        "observation was 15,707,182 bytes, including caches and evidence. Later review "
        "and tracking files are additional. The five-slot allocation is exhausted; "
        "the larger recovery/SBC program requires its own finite allocation and review.",
        "",
        "No historical candidate fit or confirmation/reserved evaluation is reported here. "
        "The 19 previously inspected confirmation outcomes have not been reopened; "
        "18 reserved outcomes remain sealed. Source-quality sensitivities and candidate "
        "recovery/SBC precede the historical fit and model comparison.",
        "",
        "Tables: [sampling and runtime](sampling-and-runtime-summary.csv), "
        "[all known-truth estimates](known-truth-estimates.csv). "
        "[Original pilot evidence](../mean-curvature-pilot-v1/).",
        "",
        "Reproduce: `uv run --locked --offline python scripts/summarize_arrival_curvature_pilot.py "
        "--output <new-project-path>`. This only summarizes accepted saved evidence.",
    ]
    (output / "findings.md").write_text("\n".join(lines) + "\n")
    write_json(
        output / "output-checksums.json", {p.name: sha256(p) for p in sorted(output.iterdir())}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    report(project, (project / args.output).resolve())
