"""Build the reader report and tables from immutable descriptive EDA bundles."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.arrival.evidence import read_rows, write_json, write_rows  # noqa: E402
from analysis.arrival.timing_artifact_names import (  # noqa: E402
    EDA_ROOT,
    artifact_filename,
    question_directory,
    result_path,
    rewrite_markdown_links,
)
from analysis.arrival.timing_data_and_descriptive_statistics import number  # noqa: E402


def read(base: Path, split: str, module: str) -> dict[str, Any]:
    return json.loads(
        (question_directory(base, split, module) / artifact_filename("summary.json")).read_text()
    )


def fmt(value: Any) -> str:
    v = number(value)
    return f"{v:.4g}" if math.isfinite(v) else "unknown"


def replication(
    branch: str, explore: dict[str, Any], confirm: dict[str, Any], support_note: str = ""
) -> str:
    """Apply the frozen descriptive rule; unidentified support never confirms."""
    if not explore["triggered"]:
        return "unresolved: exploration untriggered or unidentifiable"
    a, b = number(explore["scalar"]), number(confirm.get("scalar"))
    if not math.isfinite(a) or not math.isfinite(b):
        return "tentative: confirmation unidentifiable"
    if support_note:
        return "tentative: " + support_note
    if branch == "B3" and not (
        explore["detail"].get("two_key_bootstrap_stability")
        and confirm["detail"].get("two_key_bootstrap_stability")
    ):
        return "tentative: bootstrap stability failed"
    if a * b < 0:
        return "contradicted: opposite direction"
    if a * b > 0 and 0.5 <= abs(b / a) <= 2:
        return "confirmed descriptive screen"
    if branch == "B6":
        x = explore["detail"].get("selected_contrast", {})
        y = confirm["detail"].get("selected_contrast", {})
        lo = max(number(x.get("ci_low")), number(y.get("ci_low")))
        hi = min(number(x.get("ci_high")), number(y.get("ci_high")))
        if math.isfinite(lo) and math.isfinite(hi) and lo <= hi:
            return "confirmed descriptive screen: interval overlap"
    return "tentative: magnitude did not replicate"


def report(root: Path) -> None:
    base = root / "artifacts/eda/arrival-timing/results"
    lock = json.loads((base.parent / "frozen-confirmation-definition.json").read_text())
    if any(not question_directory(base, "confirmation", m).is_dir() for m in lock["questions"]):
        raise ValueError("confirmation questions incomplete")
    counts: list[dict[str, Any]] = []
    scales: list[dict[str, Any]] = []
    for split in ["exploration", "confirmation"]:
        shape = read(base, split, "C2") | read(base, split, "C8")
        design = read(base, split, "C9")
        for target in ["T-OBS", "NCEI-native-duration", "T-CAL"]:
            s, d = shape[target], design[target]
            counts.append(
                {
                    "split": split,
                    "target": target,
                    **{
                        k: d[k]
                        for k in [
                            "rows",
                            "events",
                            "sites",
                            "components",
                            "additive_design_rank",
                            "inverse_simpson_events",
                            "top3_row_share",
                            "sites_at_least_2_events",
                            "sites_at_least_3_events",
                            "sites_at_least_5_events",
                        ]
                    },
                    **{k: s[k] for k in ["median", "mad", "q10", "q90"]},
                }
            )
            if split == "exploration":
                scales.append(
                    {
                        "target": target,
                        "units": "minutes",
                        **{k: s[k] for k in ["q10", "median", "q90", "mad"]},
                        "use": "descriptive observable scales only; not selected priors",
                    }
                )
    write_rows(result_path(base, "target-summary.csv"), counts)
    write_rows(result_path(base, "exploration-observable-scales.csv"), scales)
    comparisons: list[dict[str, Any]] = []
    for i in range(1, 12):
        module = f"B{i}"
        exploration = read(base, "exploration", module)
        confirmation = read(base, "confirmation", module) if module in lock["questions"] else {}
        for target, x in exploration.items():
            y = confirmation.get(target, {})
            support_note = ""
            if module in ["B1", "B9"]:
                profile = read(base, "confirmation", "C3")[target]
                if min(profile["near"]["finite_n"], profile["far"]["finite_n"]) < 5:
                    support_note = "fewer than five confirmation records in a distance group"
            elif module == "B10":
                trends = read_rows(
                    result_path(base, "confirmation-B10/T-CAL-within-event-distance.csv")
                )
                if sum(math.isfinite(number(r["rho"])) for r in trends) < 3:
                    support_note = "only two usable event-level confirmation trends"
            elif module == "B6" and y and not y["triggered"]:
                support_note = "confirmation contrast interval/threshold inconclusive"
            comparisons.append(
                {
                    "branch": module,
                    "target": target,
                    "route": lock["routes"][module][target],
                    "exploration_scalar": x["scalar"],
                    "confirmation_scalar": y.get("scalar", "unknown"),
                    "status": replication(module, x, y, support_note),
                    "units": {
                        "B1": "log ratio",
                        "B2": "proportion",
                        "B3": "MAD ratio",
                        "B4": "MAD ratio",
                        "B5": "MAD ratio",
                        "B6": "minutes",
                        "B7": "availability spread proportion",
                        "B8": "relative change",
                        "B9": "log ratio",
                        "B10": "rank correlation",
                        "B11": "minutes",
                    }[module],
                    "interpretation": "descriptive screen only; limits in report",
                }
            )
    write_rows(
        result_path(base, "branch-replication.csv"),
        [{k: str(v) for k, v in r.items()} for r in comparisons],
    )
    write_json(result_path(base, "branch-replication.json"), comparisons)
    lines = [
        "# Preliminary arrival-timing EDA",
        "",
        "This analysis describes what the accepted arrival evidence can support before "
        "Bayesian modeling. It preserves separate NTWC reported durations, NCEI native "
        "travel durations, and signed estimated-minus-observed timing differences. "
        "No records were repaired or removed, and no likelihood, prior or model was "
        "fitted or selected.",
        "",
        "The NCEI near-field departure from a fixed depth reference repeats in "
        "confirmation, as does stronger dispersion across distance groups. Exact-UTC "
        "availability remains uneven across source eras. Station-effect stability, "
        "cross-source identity/ancestry and the missingness mechanism remain unresolved. "
        "The signed forecast comparison has median −15.5 min in exploration and "
        "−13 min in confirmation; its distance-trend evidence is too sparse to confirm.",
        "",
        "## Read the targets separately",
        "",
        "**T-OBS** is reported observed UTC minus a reviewed USGS reference origin. "
        "**NCEI-native-duration** preserves the source's explicit positive travel duration "
        "without reconstructing missing arrival dates. **T-CAL** is estimated UTC minus "
        "observed UTC, in minutes: a negative value means the published estimate precedes "
        "the reported observation. None is public alert lead time or an independently "
        "validated physical onset.",
        "",
        "| Target | Split | Records | Events | Sites | Median (min) | MAD (min) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {r['target']} | {r['split']} | {r['rows']} | {r['events']} | {r['sites']} | "
        f"{fmt(r['median'])} | {fmt(r['mad'])} |"
        for r in counts
    )
    lines.extend(
        [
            "",
            "MAD is the unscaled median absolute deviation. See [all target summaries]"
            "(final-v1/target-summary.csv) and the [exploration-only observable scales]"
            "(final-v1/exploration-observable-scales.csv) for q10/q50/q90 values.",
            "",
            "## Design and uncertainty",
            "",
            "The metadata-only, region-by-era split assigns 38 development archive entries to "
            "exploration and 19 to confirmation, with seed 20261103. Tōhoku 2011 and Chile 2010 "
            "are forced to exploration. Sparse strata may occur in one half only. The 18 reserved "
            "event outcomes remain unopened. Prior metadata exposure is disclosed; no "
            "blindness is claimed.",
            "",
            "One physical sequence crosses the archive-entry split: usp000d3ka (confirmation) "
            "and usp000d3mb (exploration). These halves therefore do not establish independent "
            "physical-sequence confirmation. Later evaluation needs event/sequence grouping. "
            "Small confirmation targets limit every replicated screen below.",
            "",
            "Methods are descriptive: robust summaries, fixed distance bins, normal-reference "
            "QQ diagnostics, component-relative median polish, rank correlations and 500 event "
            "bootstrap resamples. The bootstrap resamples events, not independent rows. Its "
            "intervals are descriptive, not multiplicity-adjusted hypothesis tests. No p-values "
            "or posterior probabilities are reported.",
            "",
            "## Distance and timing structure",
            "",
            "The fixed diagnostic uses c = sqrt(g × 4000 m), t_ref = geodesic distance / c, "
            "and r₀ = ln(reported duration / t_ref). The band uses fixed depths 2000–6000 m. "
            "WGS84 geodesics are a stated approximation where original source datums are unknown. "
            "This straight-path, constant-depth reference is not a validated propagation forecast.",
            "",
            "| Family | Exploration near−far median r₀ | Confirmation near−far median r₀ |",
            "| --- | ---: | ---: |",
        ]
    )
    for target in ["T-OBS", "NCEI-native-duration"]:
        vals = [read(base, split, "C3")[target] for split in ["exploration", "confirmation"]]
        differences = [number(v["near"]["median"]) - number(v["far"]["median"]) for v in vals]
        lines.append(f"| {target} | {fmt(differences[0])} | {fmt(differences[1])} |")
    lines.extend(
        [
            "",
            "![Reported T-OBS duration versus distance and a fixed depth reference]"
            "(final-v1/exploration-C3/T-OBS-physics.png)",
            "",
            "Near-field departures mix source extent, bathymetry/path, reporting and onset "
            "definitions. They motivate separate near-field and distance-scale candidates, "
            "not exclusions. Native NCEI distance numbers are retained for comparison, but "
            "their units were not verified in the frozen evidence, so no kilometre equivalence "
            "or physical ratio is asserted. No shoreline proxy was acquired.",
            "",
            "The 0.045-minute NTWC duration at Lottin Point is 2.7 seconds: the displayed "
            "16:38 clock minus reviewed 16:37:57.300 origin. The arithmetic matches the raw "
            "source. Minute display does not establish minute accuracy or a physical onset. "
            "It remains flagged and retained. All 150 exploration tail flags were traced to "
            "original source values; no proven transcription error was found. One NCEI/JMA "
            "first-wave definition comparison remains unapproved, and 148 other causes "
            "remain unresolved. QQ curvature does not select a heavy-tail likelihood.",
            "All 26 confirmation NCEI tail flags also match their original native "
            "duration fields. Their specific causes remain unknown; they were retained.",
            "",
            "## Groups, provenance and availability",
            "",
            "NTWC's primary physical-site median polish has zero residual MAD; the NCEI "
            "primary component has site/residual MAD ratio 3.323 and event/residual ratio "
            "4.225 in exploration. Only 250/500 physical-site and 261/500 bounded-2-km "
            "NCEI bootstrap ratios are finite. These conditional ratios are unstable; "
            "they do not identify variance components. Bootstrap resampling may disconnect "
            "the design. Components have separate origins, and changing the largest "
            "component under deletion limits effect comparisons.",
            "",
            "![NCEI component-relative event effects with the largest event departures labeled]"
            "(final-v1/exploration-C4/NCEI-native-duration-event-effects.png)",
            "",
            "In the frozen confirmation T-OBS event-effect figure, an optional "
            "right-edge ID annotation is clipped. The two plotted component-0 "
            "events are usp000hr97 (+0.0767355) and usp000jr83 (−0.0767355) on the "
            "log-ratio scale; their full IDs and values are preserved in the "
            "[figure CSV](final-v1/confirmation-C4/T-OBS-event-effects.csv). "
            "The frozen image and numerical output were preserved unchanged.",
            "",
            "No direct cross-family shared geographic-ID comparison is available in either half. "
            "The posthoc P1 sensitivity uses existing same-name bounded-2-km keys and "
            "does not approve identities, deployments, common onsets, ancestry or independence. "
            "Its 56 exploration comparisons have median NTWC−NCEI difference −0.147 min "
            "(event-bootstrap interval −0.183 to +0.452): 48 below one minute in absolute "
            "difference, three from one to under five, and five at least five. Maximum "
            "coordinate separation is 1.248 km. Close agreement can reflect copying or "
            "definitions; it does not establish independent measurements.",
            "Confirmation P1 contains zero co-location comparisons, so the 56-row "
            "exploration sensitivity cannot be confirmed in the second half.",
            "",
            "![Unapproved same-name bounded-2-km duration comparisons]"
            "(final-v1/exploration-C5/posthoc-P1-differences.png)",
            "",
            "The NCEI coastal−DART within-event duration contrast is an unmatched comparison: "
            "coastal and deep-ocean gauges occupy different distances and settings. Its "
            "202.5-minute exploration contrast is not an estimated source bias. Site "
            "inventory providers are geographic metadata; actual arrival-pick provenance "
            "remains unknown. Original NTWC-report origin ancestry is also unresolved. "
            "Seventy-five separate documentary-product origin comparisons are not a "
            "substitute for that ancestry.",
            "",
            "| Split | Retained reports | Accepted rows | Structural rows | Exact "
            "observed UTC | Source-absent observed value | Numeric peak among "
            "source-absent |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for split in ["exploration", "confirmation"]:
        s = read(base, split, "C6")
        lines.append(
            f"| {split} | "
            + " | ".join(
                str(s[k])
                for k in [
                    "retained",
                    "accepted",
                    "structural",
                    "exact_observed",
                    "absent_observed",
                    "absent_observed_with_peak",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "![Exact observation availability by source era]"
            "(final-v1/exploration-C6/availability-era.png)",
            "",
            "Exact-UTC availability uses accepted source rows as its denominator; it is "
            "not an operating-station census or non-detection rate. Source-absent values "
            "are distinct from unresolved calendar/qualifier cases. Numeric peak presence "
            "differs from nonempty text or a dash. Peak-size comparisons stay within "
            "event/table/header scope with unknown native units. Era/format and event "
            "composition are confounded. MCAR, MAR and MNAR remain unidentified; the EDA "
            "does not extend the four documented individual missing-observation reasons.",
            "",
            "LOEO tables retain every event deletion for pooled r₀ median/MAD, near−far "
            "contrast, component-effect MADs and selected C5 group contrasts. Very large "
            "relative changes can come from nearly zero contrast baselines. Consult the "
            "absolute changes and missing-contrast counts; they are not enormous physical "
            "shifts. This is not an exhaustive test of every possible C5 statistic.",
            "",
            "## Signed forecast comparisons",
            "",
            "T-CAL is a separate signed target. Exploration contains 156 comparisons from "
            "13 events, with median −15.5 minutes, MAD 13.5, q10 −51 and q90 +3.5; "
            "125/156 are negative. The median within-event distance-rank correlation "
            "is −0.453. Era is constant within an event, so it cannot identify a separate "
            "within-event era effect. Confirmation uses the same frozen question.",
            "",
            "![Signed estimated-minus-observed differences by distance]"
            "(final-v1/exploration-C8/T-CAL-distance.png)",
            "",
            "## Frozen branch results",
            "",
            "Each selected question was rerun once with the frozen code/config and its "
            "exploratory route. A descriptive screen repeats when direction matches and "
            "magnitude lies within a factor of two, or its saved intervals overlap. "
            "Opposite signs are contradicted; insufficient support stays tentative. "
            "The table's confirmed labels concern the screen only, not causality, "
            "measurement validity, a likelihood, or independent-sequence generalization. "
            "B3 additionally requires the registered bootstrap stability. B11 was "
            "unidentifiable and did not trigger a confirmation branch; C5 was still rerun.",
            "",
            "The T-OBS confirmation near-field group has one record, so B1/B9 remain "
            "tentative under the minimum-five-record screen. T-CAL has only two finite "
            "event-level confirmation trends, so B10 remains tentative. These support "
            "qualifications do not change any frozen question, scalar or threshold. "
            "B1/B9 reuse the same near−far contrast and are not independent confirmations.",
            "",
            "| Branch | Target | Exploration scalar | Confirmation scalar | Disposition |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    lines.extend(
        f"| {r['branch']} | {r['target']} | {fmt(r['exploration_scalar'])} | "
        f"{fmt(r['confirmation_scalar'])} | {r['status']} |"
        for r in comparisons
    )
    lines.extend(
        [
            "",
            "See [routes and replication CSV](final-v1/branch-replication.csv) and "
            "the original [frozen branch registry](freeze-v1/branch-registry.md). "
            "Scalars have branch-specific units in the CSV and must not be compared across rows. "
            "B5/B7/B8 are nonnegative dispersion/availability/influence screens; repeating "
            "their magnitude does not establish the same ordered covariate effect or driver.",
            "",
            "## Repeated-site and holdout support",
            "",
            "| Target / split | Components | Structural rank | Sites in ≥2 / ≥3 / ≥5 events | "
            "Inverse-Simpson event concentration | Top-three event row share |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for r in counts:
        repeated = " / ".join(str(r[f"sites_at_least_{n}_events"]) for n in [2, 3, 5])
        lines.append(
            f"| {r['target']} / {r['split']} | {r['components']} | "
            f"{r['additive_design_rank']} | {repeated} | "
            f"{fmt(r['inverse_simpson_events'])} | {fmt(r['top3_row_share'])} |"
        )
    lines.extend(
        [
            "",
            "Structural additive rank is events + sites − connected components, "
            "not proof of stable variance estimation. Inverse-Simpson concentration "
            "describes event imbalance; it is not posterior effective sample size "
            "or a count of independent earthquakes. C9 retains every LOEO and LOSO "
            "support table, including whether held-out records use sites seen elsewhere.",
            "",
            "## Decision memo for later modeling",
            "",
            "These are candidate directions for T-PB-03; no model or prior is selected. "
            "Confirmation is small and not independent by physical sequence. A repeated "
            "screen can motivate a later comparison without validating the proposed model.",
            "",
            "| Decision | T-OBS | NCEI native duration | T-CAL |",
            "| --- | --- | --- | --- |",
            "| Estimand | **Confirmed:** reported UTC minus reviewed origin; physical "
            "onset unresolved | **Confirmed:** native positive reported duration; "
            "date/onset unresolved | **Confirmed:** signed E−O, not alert lead time |",
            "| Likelihood shape | **Tentative:** compare positive log-scale and robust"
            " observation-layer candidates; source-sensitive tails retained | "
            "**Tentative:** compare positive log-scale/robust candidates separately "
            "from NTWC | **Tentative:** compare signed symmetric/heavy-tail "
            "candidates; no positive-only likelihood |",
            "| Group structure | **Unresolved:** zero residual MAD and "
            "sparse/disconnected cells prevent stable variance claims | **Tentative:**"
            " event/site candidates, with unstable bootstrap ratios disclosed | "
            "**Tentative:** event and repeated-site support must constrain complexity "
            "|",
            "| Covariate form | **Tentative:** fixed-reference offset plus limited "
            "distance/near-field alternatives | **Tentative:** distance/near-field and"
            " coastal/DART sensitivity; no causal family offset | **Tentative:** "
            "within-event distance trend; era confounded with event |",
            "| Observation layer | **Confirmed need:** retain clock/origin/definition "
            "uncertainty; accuracy unknown | **Confirmed need:** retain native "
            "duration/definition/precision provenance | **Confirmed need:** preserve "
            "forecast/observation definition and product-version uncertainty |",
            "| Missingness | **Unresolved:** selection/availability sensitivity, not a"
            " learned causal mechanism | **Unresolved:** target eligibility is not a "
            "sensor-operating census | **Unresolved:** complete pairs select reports; "
            "no fabricated forecasts |",
            "| Holdouts | **Tentative:** event/sequence grouping; inspect seen/unseen "
            "site support | **Tentative:** event/sequence and site holdouts from C9; "
            "no pooled source independence | **Tentative:** only 18 contributing "
            "events overall; nested event/sequence evaluation |",
            "| Prior-predictive scales | **Tentative:** exploration q10/median/q90/MAD"
            " in saved CSV, not priors | **Tentative:** separate exploration "
            "native-duration scales, not priors | **Tentative:** signed exploration "
            "scales, not priors |",
            "| Open questions | **Unresolved:** original report ancestry, source "
            "datum, physical onset | **Unresolved:** lineage, common target, native "
            "distance units | **Unresolved:** forecast issuance/version and actionable"
            " lead time |",
            "",
            "## Artifacts and reproduction",
            "",
            "The [figure and table index](figures.md) links every retained PNG/SVG/CSV "
            "set. Each question bundle includes meta/config/seeds/inputs/outputs/metrics/notes, "
            "a summary, a detailed Markdown report and checksums. The earlier checkpoint "
            "is preserved in preliminary-checkpoint/; results/ contains the consistent analysis.",
            "",
            "Inputs: [148 pinned files](freeze-v1/inputs.json), "
            "[development metadata](freeze-v1/development-metadata.csv), "
            "[split and counts](freeze-v1/target-counts.csv), "
            "[confirmation code/route lock](confirmation-lock.json). "
            "The underlying public-source snapshots are kept outside Git; obtain the "
            "accepted data release and verify its pins before replay. Source inventories "
            "and provenance are described in [the data guide](../../../docs/data/multi-event.md) "
            "and [source-process report](../../../docs/data/source-process.md).",
            "",
            "Use the pinned environment and repository root. Question bundles refuse "
            "overwrites. For an existing confirmation question, use a new scratch output "
            "with `--replay`; it requires the lock and byte-identical canonical outputs:",
            "",
            "```bash",
            "MPLCONFIGDIR=/private/tmp/tsunami-paper-mpl .venv/bin/python "
            "scripts/run_arrival_timing_eda.py \\",
            "  --split confirmation --module C3 --replay \\",
            "  --output artifacts/generated/arrival-timing-replay/distance-reference-confirmation",
            ".venv/bin/python -m scripts.build_arrival_timing_eda_report",
            "```",
            "",
            "Replaying is verification, not another adaptive look or an opportunity "
            "to change the question. Local MLflow records mirror the portable bundles. "
            "No primary timestamps, identities, pairs, reserved outcomes or fitted-model "
            "contracts were changed by this EDA.",
        ]
    )
    reader_text = rewrite_markdown_links(
        "\n".join(lines) + "\n",
        Path("artifacts/eda/paper/report.md"),
        EDA_ROOT / "arrival-timing-findings.md",
    )
    (base.parent / "arrival-timing-findings.md").write_text(reader_text)
    gallery = [
        "# Preliminary EDA figures and tables",
        "",
        "All figures are preliminary descriptive results. Each row supplies the "
        "underlying plotted data and a vector version. Read the "
        "[report](arrival-timing-findings.md) "
        "for target definitions, units, uncertainty and limits.",
        "",
        "| Split / question | Figure / alt description | Data | Vector |",
        "| --- | --- | --- | --- |",
    ]
    for png in sorted(base.glob("*/*/*.png")):
        rel = png.relative_to(base.parent)
        gallery.append(
            f"| {png.parent.parent.name} / {png.parent.name.replace('-', ' ')} | "
            f"[{png.stem.replace('-', ' ')}]({rel}) | "
            f"[CSV]({rel.with_suffix('.csv')}) | [SVG]({rel.with_suffix('.svg')}) |"
        )
    gallery.extend(
        [
            "",
            "The frozen confirmation NTWC event-effects image clips an optional "
            "right-edge ID annotation. The component-0 values are usp000hr97 "
            "(+0.0767355) and usp000jr83 (−0.0767355). Full IDs/values are in its "
            "CSV; the frozen image and numerical results were preserved.",
        ]
    )
    (base.parent / "figure-and-table-index.md").write_text("\n".join(gallery) + "\n")
    print(base.parent / "arrival-timing-findings.md")


if __name__ == "__main__":
    report(Path.cwd())
