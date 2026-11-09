"""Protected future development-check/full-development views of six frozen tables.

This adapter selects no model and performs no evaluation. The already inspected
19-event set remains closed until a reviewed specification freeze; full57 reads
also require the completed frozen check. Reserved events are never an input.
"""

# pyright: basic
from __future__ import annotations

import json
import math
import re
import tomllib
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np

from analysis.arrival.evidence import read_rows, sha256
from analysis.arrival.model_curvature_prior import read_curvature_prior
from analysis.arrival.model_data import (
    CONTRACT,
    CONVENTIONS,
    METADATA,
    SOURCE_MANIFEST,
    SPLIT,
    TARGET_FILES,
    lane_arrays,
)
from analysis.arrival.model_sensitivity_priors import VARIANTS, _population_spec
from analysis.arrival.models import PRIORS, read_prior

ART = "artifacts/models/arrival-timing/"
EDA = "artifacts/eda/arrival-timing/"
FREEZE = ART + "specification-freeze-v1/review-acceptance.json"
MS5_REVIEW = ART + "exploration-sensitivity-report-v1/review-acceptance.json"
CHECK_REVIEW = ART + "development-check-v1/review-acceptance.json"
SCORING = "config/arrival-model-scoring-v1.toml"
LOCK = EDA + "frozen-confirmation-definition.json"
LEDGER = EDA + "file-renames-and-content-checksums.json"
RENAME_VERIFICATION = EDA + "file-renaming-verification.json"
CONFIRMATION_QA = "artifacts/generated/paper-eda-v1/checker/confirmation-acceptance.json"
RENAME_QA = "artifacts/generated/paper-eda-renaming-checker/final-head-acceptance.json"
CHECK_FILES = {
    target: name.replace("/exploration/", "/confirmation/") for target, name in TARGET_FILES.items()
}
CHECK_SHA = dict(
    zip(
        CHECK_FILES.values(),
        [
            "c5b8c7c118d09b846f6594795f6df802c4d4a0d6cea1efff0a7c488b481030fe",
            "e0fa1fe58d9b026f874591a0953ec20600d1ecc71916e0c59cd2bf0b813fa5c0",
            "325900a2c5c758325588c05f3613d3b5e93f3d9419ae054a70e44e0645231e0e",
        ],
        strict=True,
    )
)
CROSS_SEQUENCE = "seq-usp000d3ka"
CROSS_EXPLORATION = "usp000d3mb"
CROSS_CHECK = "usp000d3ka"
COUNTS = {
    "NCEI-native-duration": (1070, 151, 33, 14),
    "T-OBS": (236, 22, 14, 6),
    "T-CAL": (156, 13, 13, 5),
}
OLD_EXCLUSIONS = frozenset(
    [
        "recovery-ncei-564962a202e9e2be:23",
        "recovery-ncei-66bfa3cd99cb7161:198",
        "recovery-ncei-9ffb03a9721a6bc9:23",
        "recovery-ncei-9ffb03a9721a6bc9:41",
        "recovery-ncei-c7a352e5a9628185:30",
        "recovery-ncei-c7a352e5a9628185:56",
    ]
)
CONSUMED = (
    "analysis/arrival/model_development_data.py",
    "tests/test_arrival_model_development_data.py",
    "analysis/arrival/model_data.py",
    "analysis/arrival/evidence.py",
    "analysis/arrival/model_sensitivity_priors.py",
    "analysis/arrival/model_curvature_prior.py",
    "analysis/arrival/model_curvature.py",
    "analysis/arrival/model_scale.py",
    "analysis/arrival/models.py",
    "config/arrival-mean-curvature-v1.toml",
    PRIORS,
    CONTRACT,
    SCORING,
    SPLIT,
    METADATA,
    SOURCE_MANIFEST,
    LOCK,
    LEDGER,
    RENAME_VERIFICATION,
    CONFIRMATION_QA,
    RENAME_QA,
    MS5_REVIEW,
)


def _path(root, name):
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or Path(name).as_posix() != name
        or any(part in {".", ".."} for part in name.split("/"))
    ):
        raise ValueError("literal project-relative development source path required")
    path = root.resolve() / name
    if path.resolve() != path or not path.is_file():
        raise ValueError("existing nonsymlink project-local source required")
    return path


def _unchanged(root, pins):
    if not isinstance(pins, dict) or not pins:
        raise ValueError("complete frozen development source pins required")
    for name, digest in pins.items():
        if (
            not isinstance(digest, str)
            or re.fullmatch("[0-9a-f]{64}", digest) is None
            or sha256(_path(root, name)) != digest
        ):
            raise ValueError("development source SHA changed")


def _require(pins, refs):
    if (
        not isinstance(refs, dict)
        or not refs
        or any(pins.get(name) != digest for name, digest in refs.items())
    ):
        raise ValueError("complete transitive development source closure required")


def _json(root, pins, name):
    if name not in pins:
        raise ValueError("required frozen development metadata pin missing")
    value = json.loads(_path(root, name).read_text())
    if not isinstance(value, dict):
        raise ValueError("frozen development metadata object required")
    return value


def _models(root, models):
    if not isinstance(models, dict) or set(models) != set(TARGET_FILES):
        raise ValueError("selected model for each of three separate targets required")
    for target, specs in models.items():
        if not isinstance(specs, list) or not 1 <= len(specs) <= 2:
            raise ValueError("one selected and at most one runner-up per source required")
        identities = []
        for j, spec in enumerate(specs):
            if (
                not isinstance(spec, dict)
                or set(spec) != {"role", "kind", "prior_variant", "base_prior_sd", "wider_prior_sd"}
                or spec["role"] != ("selected" if j == 0 else "runner_up")
            ):
                raise ValueError("selected-first exact frozen model specification required")
            kind, variant = spec["kind"], spec["prior_variant"]
            active = {sd for sd, _ in _population_spec(target, kind).values()}
            if (
                variant not in VARIANTS
                or variant == "gamma_wider_only"
                and kind != "mean-curvature"
            ):
                raise ValueError("reviewed source-specific prior variant required")
            base = (
                read_curvature_prior(root, "base")
                if kind == "mean-curvature"
                else read_prior(root, target, "base")
            )
            wider = None
            if variant in {"joint_wider", "gamma_wider_only"}:
                wider = (
                    read_curvature_prior(root, variant)
                    if kind == "mean-curvature"
                    else read_prior(root, target, "wider")
                )
            for field, expected in [("base_prior_sd", base), ("wider_prior_sd", wider)]:
                actual = spec[field]
                if expected is None:
                    if actual is not None:
                        raise ValueError("unused wider prior must be null")
                elif (
                    not isinstance(actual, dict)
                    or set(actual) != active
                    or any(
                        type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                        for value in actual.values()
                    )
                    or actual != {key: expected[key] for key in active}
                ):
                    raise ValueError(
                        "proper active prior SD keys/values must match pinned prior readers"
                    )
            identities.append((kind, variant))
        if len(set(identities)) != len(specs):
            raise ValueError("distinct frozen selected/runner-up specifications required")


def _producer_sources(root, pins):
    """Close both historical generation and accepted renamed artifact identities."""
    lock = _json(root, pins, LOCK)
    ledger = _json(root, pins, LEDGER)
    qa = _json(root, pins, RENAME_QA)
    old_qa = _json(root, pins, CONFIRMATION_QA)
    verification = _json(root, pins, RENAME_VERIFICATION)
    if (
        qa.get("status") != "ACCEPTED exact main HEAD landing of descriptive EDA migration"
        or old_qa.get("status")
        != "ACCEPTED locked confirmation artifacts with scientific limitations"
        or verification.get("status")
        != "ACCEPTED descriptive artifact/source migration at verified worktree version"
    ):
        raise ValueError("accepted historical confirmation and rename QA required")
    bindings = qa.get("bindings", {})
    if (
        bindings.get("ledger_sha256") != pins[LEDGER]
        or bindings.get("lock_sha256") != pins[LOCK]
        or bindings.get("file_renaming_verification_sha256") != pins[RENAME_VERIFICATION]
    ):
        raise ValueError("accepted rename QA must bind the actual ledger/lock/verification")
    if (
        old_qa.get("lock_sha256") != ledger.get("original_confirmation_lock_sha256")
        or lock.get("pre_rename_lock_sha256") != old_qa["lock_sha256"]
        or lock.get("path_migration_manifest") != LEDGER
        or ledger.get("original_generation_metadata_preserved") is not True
    ):
        raise ValueError("historical generation-to-migration acceptance chain required")
    manifest = _json(root, pins, SOURCE_MANIFEST)
    if (
        lock.get("inputs_sha256") != pins[SOURCE_MANIFEST]
        or lock.get("generation_inputs_sha256") != ledger.get("original_input_manifest_sha256")
        or manifest.get("pre_rename_manifest_sha256") != ledger["original_input_manifest_sha256"]
    ):
        raise ValueError("same original and current frozen input manifests required")
    _require(pins, {row["path"]: row["sha256"] for row in manifest.get("files", [])})
    _require(pins, lock.get("layout_replay_code"))
    entries = ledger.get("files", [])
    old = {row["old_path"]: row for row in entries}
    new = {row["new_path"]: row for row in entries}
    if len(old) != len(entries) or len(new) != len(entries):
        raise ValueError("unique accepted path-migration entries required")
    for name, digest in lock.get("code", {}).items():
        if name in old:
            row = old[name]
            if row["before_sha256"] != digest or pins.get(row["new_path"]) != row["after_sha256"]:
                raise ValueError("historical producer code identity changed")
        elif pins.get(name) != digest:
            raise ValueError("unchanged historical producer code pin required")
    for folder in sorted(
        {str(Path(name).parent) for name in [*TARGET_FILES.values(), *CHECK_FILES.values()]}
    ):
        module = "C8" if folder.endswith("estimated-minus-observed-timing-distributions") else "C1"
        split = "confirmation" if "/confirmation/" in folder else "exploration"
        output_name = folder + "/output-file-checksums.json"
        if output_name not in pins:
            raise ValueError("producer output checksum closure required")
        outputs = json.loads(_path(root, output_name).read_text())
        if not isinstance(outputs, list) or not outputs:
            raise ValueError("literal producer output manifest required")
        output_refs = {folder + "/" + row["path"]: row["sha256"] for row in outputs}
        if len(output_refs) != len(outputs):
            raise ValueError("unique producer output entries required")
        _require(pins, output_refs)
        for name in [output_name, *output_refs]:
            if name not in new or new[name]["after_sha256"] != pins[name]:
                raise ValueError("consumed producer outputs must match accepted migration ledger")
        generation_name, metadata_name = [
            folder + "/" + name
            for name in ["generation-input-and-code-checksums.json", "original-run-metadata.json"]
        ]
        generation, metadata = _json(root, pins, generation_name), _json(root, pins, metadata_name)
        expected = lock.get("generation_metadata_sha256", {}).get(split + ":" + module, {})
        if (
            expected
            != {
                "generation-input-and-code-checksums.json": pins[generation_name],
                "original-run-metadata.json": pins[metadata_name],
            }
            or generation.get("code") != lock.get("code")
            or generation.get("frozen_input_manifest_sha256")
            != ledger["original_input_manifest_sha256"]
            or metadata.get("split") != split
            or metadata.get("module") != module
        ):
            raise ValueError("same accepted literal producer generation metadata required")
    _require(pins, CHECK_SHA)


def verify_development_sources(root: Path, pins: dict[str, str], *, full: bool = False):
    """Return admitted metadata only; no native table body is parsed here."""
    if type(full) is not bool:
        raise ValueError("explicit check/full mode required")
    _unchanged(root, pins)
    if not set(CONSUMED) | {FREEZE, *TARGET_FILES.values(), *CHECK_FILES.values()} <= set(pins):
        raise ValueError("complete specification/source prerequisites required")
    freeze = _json(root, pins, FREEZE)
    if (
        freeze.get("status") != "accepted_arrival_model_specification_freeze"
        or freeze.get("independent_checker") is not True
        or freeze.get("confirmation_outcomes_parsed") is not False
        or freeze.get("reserved_outcomes") != "sealed"
        or freeze.get("no_retuning_after_development_check") is not True
        or freeze.get("ms5_report_review") != MS5_REVIEW
        or freeze.get("observation_contract") != CONTRACT
        or freeze.get("scoring_contract") != SCORING
        or freeze.get("distance_mode") != "geodesic_km"
        or freeze.get("crossing_policy") != "uniform_purge_all_check_sequences"
    ):
        raise ValueError(
            "accepted frozen source-specific specification required before any check Y"
        )
    _require(pins, freeze.get("files"))
    required = set(CONSUMED) | set(TARGET_FILES.values()) | set(CHECK_FILES.values())
    if not required <= set(freeze["files"]):
        raise ValueError("freeze must bind every consumed source and consumer")
    review = _json(root, pins, MS5_REVIEW)
    if (
        review.get("status") != "accepted_exploration_sensitivity_analysis"
        or review.get("independent_checker") is not True
        or review.get("confirmation_outcomes_parsed") is not False
        or review.get("reserved_outcomes") != "sealed"
    ):
        raise ValueError("accepted final exploration sensitivity report required")
    _require(freeze["files"], review.get("files"))
    seeds = freeze.get("seeds")
    if (
        not isinstance(seeds, dict)
        or set(seeds) != {"check", "full_development"}
        or any(type(value) is not int or not 0 <= value < 2**32 for value in seeds.values())
    ):
        raise ValueError("frozen uint32 check/full-development seeds required")
    _models(root, freeze.get("models"))
    decision_path = freeze.get("ms5_decision")
    if decision_path not in freeze["files"]:
        raise ValueError("literal independently frozen scientific decision must be pinned")
    decision = _json(root, pins, decision_path)
    for field in ["models", "distance_mode", "observation_contract", "scoring_contract", "seeds"]:
        if decision.get(field) != freeze[field]:
            raise ValueError("scientific decision must equal the frozen specification")
    if full:
        review = _json(root, pins, CHECK_REVIEW)
        if (
            review.get("status") != "accepted_frozen_arrival_development_check"
            or review.get("independent_checker") is not True
            or review.get("completed_once") is not True
            or review.get("no_retuning") is not True
            or review.get("confirmation_outcomes_parsed") is not True
            or review.get("reserved_outcomes") != "sealed"
            or review.get("specification_freeze") != FREEZE
            or review.get("specification_freeze_sha256") != pins[FREEZE]
        ):
            raise ValueError("accepted completed frozen one-check receipt required before full57")
        _require(pins, review.get("files"))
        if review["files"].get(FREEZE) != pins[FREEZE] or any(
            review["files"].get(name) != digest for name, digest in freeze["files"].items()
        ):
            raise ValueError("completed check must preserve the entire frozen source closure")
    contract = tomllib.loads(_path(root, CONTRACT).read_text())
    if any(contract.get(key) != value for key, value in CONVENTIONS.items()):
        raise ValueError("unchanged native observation/transform contract required")
    _require(freeze["files"], contract.get("inputs"))
    scoring = tomllib.loads(_path(root, SCORING).read_text())
    if (
        scoring.get("schema_version") != "arrival_model_scoring_v1"
        or scoring.get("primary")
        != "equal_event_mean_normalized_joint_native_minute_log_predictive_density"
        or scoring.get("validation_unit") != "leave_whole_sequence_out_refits"
    ):
        raise ValueError("unchanged native-minute event scoring contract required")
    _producer_sources(root, freeze["files"])
    split = tomllib.loads(_path(root, SPLIT).read_text())
    roles = {role: set(split[role]) for role in ["exploration", "confirmation"]}
    if (
        len(split["exploration"]) != 38
        or len(roles["exploration"]) != 38
        or len(split["confirmation"]) != 19
        or len(roles["confirmation"]) != 19
        or roles["exploration"] & roles["confirmation"]
    ):
        raise ValueError("exact disjoint38/19 frozen event roles required")
    metadata = read_rows(_path(root, METADATA))
    ids = [row["event_id"] for row in metadata]
    if (
        len(ids) != 57
        or len(set(ids)) != 57
        or set(ids) != roles["exploration"] | roles["confirmation"]
    ):
        raise ValueError("exact57 outcome-free development metadata identities required")
    sequences = {row["event_id"]: row["sequence_group"] for row in metadata}
    seq = {role: {sequences[event] for event in events} for role, events in roles.items()}
    if (
        len(seq["exploration"]) != 33
        or len(seq["confirmation"]) != 19
        or len(set(sequences.values())) != 51
        or seq["exploration"] & seq["confirmation"] != {CROSS_SEQUENCE}
        or {event for event in ids if sequences[event] == CROSS_SEQUENCE}
        != {CROSS_EXPLORATION, CROSS_CHECK}
        or CROSS_EXPLORATION not in roles["exploration"]
        or CROSS_CHECK not in roles["confirmation"]
    ):
        raise ValueError("exact single approved crossing sequence and51-sequence metadata required")
    _unchanged(root, pins)
    return freeze, contract, roles, sequences


def _load(root, pins, *, full):
    freeze, contract, roles, sequences = verify_development_sources(root, pins, full=full)
    exploration, check, combined, purged, membership = {}, {}, {}, {}, {}
    check_sequences = {sequences[event] for event in roles["confirmation"]}
    for target in TARGET_FILES:
        original = read_rows(_path(root, TARGET_FILES[target]))
        held = read_rows(_path(root, CHECK_FILES[target]))
        ne, nc, ee, ec = COUNTS[target]
        if (
            len(original) != ne
            or len(held) != nc
            or len({row["event_id"] for row in original}) != ee
            or len({row["event_id"] for row in held}) != ec
        ):
            raise ValueError("literal accepted per-source pre-exclusion counts required")
        for rows, role in [(original, "exploration"), (held, "confirmation")]:
            if any(row["event_id"] not in roles[role] for row in rows):
                raise ValueError("native row outside its frozen source role")
        held_edges = Counter((row["event_id"], row["physical_site_id"]) for row in held)
        ambiguous_check = sorted(
            row["record_id"]
            for row in held
            if held_edges[row["event_id"], row["physical_site_id"]] > 1
        )
        if ambiguous_check:
            raise ValueError(
                f"unapproved ambiguous check event/site IDs: new={ambiguous_check}; "
                "disposition=requires_review_before_fit"
            )
        old_edges = Counter((row["event_id"], row["physical_site_id"]) for row in original)
        legacy_repeated = sorted(
            row["record_id"]
            for row in original
            if old_edges[row["event_id"], row["physical_site_id"]] > 1
        )
        exploration[target] = lane_arrays(target, original, sequences, roles["exploration"])
        check[target] = lane_arrays(target, held, sequences, roles["confirmation"])
        if set(exploration[target].record_ids) & set(check[target].record_ids):
            raise ValueError("record ID crosses disjoint native source roles")
        combined[target] = lane_arrays(
            target, original + held, sequences, roles["exploration"] | roles["confirmation"]
        )
        excluded = {
            rid
            for rid, ok in zip(combined[target].record_ids, combined[target].included, strict=True)
            if not ok
        }
        expected = OLD_EXCLUSIONS if target == "NCEI-native-duration" else frozenset()
        if excluded != expected:
            unexpected = sorted(excluded - expected)
            missing = sorted(expected - excluded)
            raise ValueError(
                f"unapproved ambiguous event/site exclusion IDs: new={unexpected}; "
                f"missing_old={missing}"
            )
        if set(contract["lanes"][target]["excluded_ids"]) != expected:
            raise ValueError("original approved exclusion identity changed")
        lane = exploration[target]
        mask = lane.included & ~np.isin(lane.sequences, sorted(check_sequences))
        if not mask.any() or target == "NCEI-native-duration" and int(mask.sum()) != 1040:
            raise ValueError("reviewed uniform crossing-sequence purge required")
        purged[target] = replace(lane, included=mask)
        membership[target] = {
            "exploration_pre_ids": list(lane.record_ids),
            "exploration_primary_ids": [
                rid for rid, keep in zip(lane.record_ids, lane.included, strict=True) if keep
            ],
            "training_purged_ids": [
                rid for rid, keep in zip(lane.record_ids, mask, strict=True) if keep
            ],
            "purged_primary_ids": [
                rid
                for rid, keep, retained in zip(lane.record_ids, lane.included, mask, strict=True)
                if keep and not retained
            ],
            "check_pre_ids": list(check[target].record_ids),
            "check_primary_ids": [
                rid
                for rid, keep in zip(check[target].record_ids, check[target].included, strict=True)
                if keep
            ],
            "combined_pre_ids": list(combined[target].record_ids),
            "combined_primary_ids": [
                rid
                for rid, keep in zip(
                    combined[target].record_ids, combined[target].included, strict=True
                )
                if keep
            ],
            "excluded_ids": sorted(excluded),
            "excluded_disposition": "unresolved_repeated_event_site_excluded_as_group",
            "legacy_exploration_repeated_edge_ids": legacy_repeated,
            "legacy_repeated_edge_disposition": (
                "original_NCEI_exclusions_preserved"
                if target == "NCEI-native-duration"
                else "existing_exploration_rows_preserved_no_independence_claim"
            ),
            "counts": {
                "exploration_pre": ne,
                "exploration_primary": int(lane.included.sum()),
                "check_pre": nc,
                "check_primary": int(check[target].included.sum()),
                "combined_pre": ne + nc,
                "training_purged": int(mask.sum()),
                "combined_primary": int(combined[target].included.sum()),
                "combined_eligible_events": len(set(combined[target].event_ids)),
            },
        }
        if set(combined[target].record_ids) != set(lane.record_ids) | set(check[target].record_ids):
            raise ValueError("literal full-development cohort union required")
    _unchanged(root, pins)
    provenance = {
        "specification_freeze": FREEZE,
        "specification_freeze_sha256": pins[FREEZE],
        "mode": "full_development" if full else "frozen_development_check",
        "files": dict(pins),
        "development_events": 57,
        "check_events": 19,
        "metadata_sequences": 51,
        "crossing_sequence": CROSS_SEQUENCE,
        "crossing_training_event": CROSS_EXPLORATION,
        "crossing_check_event": CROSS_CHECK,
        "distance_mode": "geodesic_km",
        "reserved_outcomes": "sealed",
        "evaluation_performed": False,
        "interpretation": "previously_EDA_inspected_development_check_not_independent_test",
    }
    return ({"combined": combined} if full else {"training_purged": purged, "check": check}) | {
        "membership": membership,
        "provenance": provenance,
        "specification": freeze,
    }


def load_check_lanes(root: Path, pins: dict[str, str]):
    """Read the admitted frozen check and uniformly purged exploration views."""
    return _load(root.resolve(), pins, full=False)


def load_full_development_lanes(root: Path, pins: dict[str, str]):
    """Restore all eligible development rows only after accepted frozen evaluation."""
    return _load(root.resolve(), pins, full=True)
