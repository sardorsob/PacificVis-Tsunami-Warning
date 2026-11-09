"""Correct one S5 qualification from its closed CSV; preserve exact original bytes.

Run the frozen report generator first. This tool defaults to a read-only preview;
--apply requires the expected original output-checksums.json SHA256 and creates a
separate immutable correction receipt. It never loads native or reserved data.
"""

# pyright: basic
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

REPORT = "artifacts/models/arrival-timing/exploration-sensitivity-report-v1"
EVIDENCE = "artifacts/models/arrival-timing/exploration-sensitivity-qualification-v1"
SELF = "scripts/correct_arrival_sensitivity_qualifications.py"
TEST = "tests/test_correct_arrival_sensitivity_qualifications.py"
MANIFEST = "output-checksums.json"
CSV = "conditional-predictive-checks.csv"
ARTIFACTS = frozenset(
    {
        CSV,
        "findings.md",
        "summary.json",
        "inputs.json",
        "probe-dispositions.json",
        "reference-provenance.json",
        "posterior-parameters.csv",
        "population-median-and-predictive-quantiles.csv",
        "supported-distance-sensitivity-changes.csv",
        "training-cohorts-and-omissions.csv",
        "ncei-data-stress-log-changes.png",
        "ncei-data-stress-log-changes.svg",
        "prior-population-median-curves.png",
        "prior-population-median-curves.svg",
    }
)
OLD_SENTENCE = (
    "The original NCEI linear and curved fits each retained 8/15 conditional "
    "predictive-check misses."
)
QUALIFICATIONS_SHA256 = "13ad1d1bf5fe6e920994f0ea1043d2e28740bdc18a9f6ae48104ff8abd5a5d45"
STRATA = ("all", "under-500km", "500-to-2000km", "2000-to-5000km", "5000km-and-above")
QUANTILES = ("0.05", "0.5", "0.95")
KINDS = ("distance-scale", "mean-curvature")
SCALES = ("modeled-response", "native-minutes")
CHECK_SCOPE = "conditional_fitted_events_in_sample_not_held_out"
CHANGED = ("findings.md", MANIFEST, "summary.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(payload: bytes) -> Any:
    return json.loads(payload, object_pairs_hook=unique_object)


def regular(path: Path) -> bytes:
    require(path.is_file() and path.resolve() == path, "literal regular source file required")
    return path.read_bytes()


def report_bytes(root: Path) -> dict[str, bytes]:
    folder = root / REPORT
    require(folder.is_dir() and folder.resolve() == folder, "literal report directory required")
    require(
        {p.name for p in folder.iterdir()} == ARTIFACTS | {MANIFEST},
        "exact fourteen artifacts plus manifest required",
    )
    return {name: regular(folder / name) for name in sorted(ARTIFACTS | {MANIFEST})}


def base_counts(payload: bytes) -> dict[str, dict[str, dict[str, int]]]:
    reader = csv.DictReader(io.StringIO(payload.decode(), newline=""))
    required = {
        "view_id",
        "target",
        "kind",
        "role",
        "scenario",
        "prior_variant",
        "distance_mode",
        "scale",
        "stratum",
        "quantile",
        "observed_quantile_valid",
        "replicated_quantile_valid",
        "check_scope",
        "observed_outside_replicated_90",
    }
    fields = reader.fieldnames or []
    require(
        len(fields) == len(set(fields)) and required <= set(fields), "exact CSV columns required"
    )
    groups: dict[tuple[str, str], dict[tuple[str, str], bool]] = {
        (kind, scale): {} for kind in KINDS for scale in SCALES
    }
    for row in reader:
        require(
            None not in row and all(value is not None for value in row.values()),
            "malformed CSV row",
        )
        expected_ids = {f"NCEI-native-duration:{kind}:base" for kind in KINDS}
        selected = (row["target"] == "NCEI-native-duration" and row["role"] == "base") or row[
            "view_id"
        ] in expected_ids
        if not selected:
            continue
        kind, scale = row["kind"], row["scale"]
        require(
            (kind, scale) in groups
            and row["target"] == "NCEI-native-duration"
            and row["view_id"] == f"NCEI-native-duration:{kind}:base"
            and row["role"] == row["scenario"] == row["prior_variant"] == "base"
            and row["distance_mode"] == "geodesic_km"
            and row["check_scope"] == CHECK_SCOPE
            and row["observed_quantile_valid"] == row["replicated_quantile_valid"] == "True",
            "literal valid NCEI base-view identities and in-sample scope required",
        )
        key = row["stratum"], row["quantile"]
        require(
            key in {(s, q) for s in STRATA for q in QUANTILES} and key not in groups[kind, scale],
            "duplicate or unknown base quantile check",
        )
        flag = row["observed_outside_replicated_90"]
        require(flag in {"True", "False"}, "explicit observed-outside boolean required")
        groups[kind, scale][key] = flag == "True"
    expected = {(s, q) for s in STRATA for q in QUANTILES}
    require(
        all(set(rows) == expected for rows in groups.values()),
        "each of four NCEI base groups requires exactly fifteen distinct checks",
    )
    return {
        kind: {
            scale: {"misses": sum(groups[kind, scale].values()), "checks": 15} for scale in SCALES
        }
        for kind in KINDS
    }


def wording(counts: dict[str, dict[str, dict[str, int]]]) -> str:
    linear, curved = counts["distance-scale"], counts["mean-curvature"]
    return (
        "In the current NCEI base-report views, observed quantiles fall outside the "
        "conditional replicated 90% interval in "
        f"{linear['modeled-response']['misses']}/15 modeled-response and "
        f"{linear['native-minutes']['misses']}/15 native checks for the linear form, and "
        f"{curved['modeled-response']['misses']}/15 modeled-response and "
        f"{curved['native-minutes']['misses']}/15 native checks for the curved form. "
        "These overlapping in-sample checks do not rank held-out performance."
    )


def correct(root: Path, *, expected_manifest_sha256: str, apply: bool = False) -> dict[str, Any]:
    root = root.resolve()
    require(
        re.fullmatch("[0-9a-f]{64}", expected_manifest_sha256) is not None,
        "explicit original manifest SHA256 required",
    )
    evidence = root / EVIDENCE
    require(
        not evidence.exists() and not evidence.is_symlink() and evidence.resolve() == evidence,
        "new correction evidence directory required; never overwrite receipts",
    )
    before = report_bytes(root)
    require(
        digest(before[MANIFEST]) == expected_manifest_sha256,
        "original manifest differs from the expected closed report",
    )
    manifest = load(before[MANIFEST])
    require(
        isinstance(manifest, dict) and set(manifest) == ARTIFACTS,
        "literal fourteen-file checksum manifest required",
    )
    require(
        all(manifest[name] == digest(before[name]) for name in ARTIFACTS),
        "closed report checksum differs",
    )
    sources = {name: digest(regular(root / name)) for name in [SELF, TEST, f"{REPORT}/{CSV}"]}
    counts = base_counts(before[CSV])
    new_text = wording(counts)
    summary = load(before["summary.json"])
    qualifications = summary.get("qualifications")
    require(
        isinstance(qualifications, list) and all(isinstance(q, str) for q in qualifications),
        "original qualification list required",
    )
    require(
        digest(json.dumps(qualifications, sort_keys=True, separators=(",", ":")).encode())
        == QUALIFICATIONS_SHA256,
        "other original qualifications differ",
    )
    require(
        summary.get("schema_version") == 4
        and summary.get("confirmation_outcomes_parsed") is False
        and summary.get("reserved_outcomes") == "sealed",
        "closed exploration report required",
    )
    findings = before["findings.md"].decode()
    require(
        all(findings.count(q) == 1 for q in qualifications),
        "every original findings qualification must remain exact",
    )
    needle, replacement = OLD_SENTENCE.encode(), new_text.encode()
    require(
        all(before[name].count(needle) == 1 for name in ["findings.md", "summary.json"]),
        "exactly one literal obsolete sentence per target required",
    )
    after = dict(before)
    for name in ["findings.md", "summary.json"]:
        after[name] = before[name].replace(needle, replacement, 1)
    expected_summary = {
        **summary,
        "qualifications": [q.replace(OLD_SENTENCE, new_text, 1) for q in qualifications],
    }
    require(
        load(after["summary.json"]) == expected_summary,
        "summary correction must change only the one qualification",
    )
    after[MANIFEST] = encoded({name: digest(after[name]) for name in sorted(ARTIFACTS)})
    require(
        sorted(name for name in before if before[name] != after[name]) == list(CHANGED),
        "only findings, summary and their manifest may change",
    )
    snapshots = {
        name: {"path": f"{EVIDENCE}/original-{name}", "sha256": digest(before[name])}
        for name in CHANGED
    }
    receipt: dict[str, Any] = dict(
        schema_version=1,
        status="corrected_sensitivity_predictive_check_qualification",
        report_path=REPORT,
        original_manifest_sha256=expected_manifest_sha256,
        before_files={name: digest(payload) for name, payload in before.items()},
        after_files={name: digest(payload) for name, payload in after.items()},
        source_files=sources,
        snapshots=snapshots,
        changed_files=list(CHANGED),
        replacement={"old_sentence": OLD_SENTENCE, "new_text": new_text},
        base_counts=counts,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        numerical_tables_figures_and_other_qualifications_unchanged=True,
        reproduction=[
            "uv run --locked --offline python scripts/summarize_arrival_completed_sensitivities.py "
            f"--output {REPORT}",
            f"shasum -a 256 {REPORT}/{MANIFEST}",
            f"python {SELF} --expected-manifest-sha256 "
            "<reviewed-generated-manifest-sha256> --apply",
        ],
        original_correction_command=(
            f"python {SELF} --expected-manifest-sha256 {expected_manifest_sha256} --apply"
        ),
        reproduction_note=(
            "Generate into a fresh report directory in a restored source checkout. "
            "SVG creation timestamps can change output hashes; review the generated "
            "report and supply its manifest hash. This receipt binds the exact original "
            "and corrected report bytes, rather than promising timestamp-identical figures."
        ),
    )
    # Complete all validation and fresh byte comparisons before creating any evidence.
    require(
        report_bytes(root) == before
        and all(digest(regular(root / p)) == h for p, h in sources.items()),
        "report or correction source changed during preflight",
    )
    if not apply:
        return {**receipt, "applied": False}
    evidence.mkdir()
    for name, snapshot in snapshots.items():
        with (root / snapshot["path"]).open("xb") as stream:
            stream.write(before[name])
    # Publish the manifest last. On interruption originals survive and no final receipt
    # is emitted; an existing evidence directory blocks an unsafe automatic retry.
    for name in ["findings.md", "summary.json", MANIFEST]:
        require(regular(root / REPORT / name) == before[name], "target changed before replacement")
        with tempfile.NamedTemporaryFile(dir=evidence, prefix=".staged-", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(after[name])
        os.replace(staged, root / REPORT / name)
    require(
        report_bytes(root) == after
        and all(digest(regular(root / p)) == h for p, h in sources.items()),
        "corrected report or source readback differs",
    )
    for name, snapshot in snapshots.items():
        require(
            regular(root / snapshot["path"]) == before[name], "original snapshot readback differs"
        )
    with (evidence / "receipt.json").open("xb") as stream:
        stream.write(encoded(receipt))
    require(load(regular(evidence / "receipt.json")) == receipt, "receipt readback differs")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reviewed correction; otherwise preview only.",
    )
    args = parser.parse_args()
    receipt = correct(
        args.root, expected_manifest_sha256=args.expected_manifest_sha256, apply=args.apply
    )
    print(
        json.dumps(
            {
                "applied": args.apply,
                "report_path": REPORT,
                "base_counts": receipt["base_counts"],
                "new_text": receipt["replacement"]["new_text"],
                "receipt": f"{EVIDENCE}/receipt.json" if args.apply else None,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
