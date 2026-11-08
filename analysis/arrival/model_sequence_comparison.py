"""Assemble complete, source-specific sequence comparisons from retained numeric evidence."""

# pyright: basic
from __future__ import annotations

import json
import tomllib

import numpy as np

from analysis.arrival.evidence import checked_path, sha256

CONTINUATION = "artifacts/models/arrival-timing/bridge-sequence-continuation-v2"


def verify_complete_cv(root):
    folder = checked_path(root, CONTINUATION)
    summary = json.loads((folder / "run-summary.json").read_text())
    if (
        summary.get("status") != "computations_complete"
        or summary.get("completed_folds") != 72
        or summary.get("planned_folds") != 72
        or summary.get("logical_completed_folds") != 83
    ):
        raise ValueError("complete frozen sequence computations required before comparisons")
    receipt = folder / "review-acceptance.json"
    if not receipt.is_file():
        raise ValueError("independent complete-CV review required")
    qa = json.loads(receipt.read_text())
    if (
        qa.get("status") != "accepted_all_logical_sequence_computations"
        or not qa.get("independent_checker")
        or qa.get("reserved_outcomes") != "sealed"
        or qa.get("plan_sha256") != sha256(folder / "plan.json")
    ):
        raise ValueError("independent complete-CV evidence identity required")
    required = {
        f"{CONTINUATION}/{name}"
        for name in ["plan.json", "run-summary.json", "reviewed-resolutions.json"]
    }
    if not required <= set(qa.get("files", {})):
        raise ValueError("complete reviewed plan, summary and resolution registry required")
    for p, h in qa["files"].items():
        if sha256(checked_path(root, p)) != h:
            raise ValueError("reviewed CV evidence changed")
    return qa


def _boolean(value):
    if value is True or value == "True":
        return True
    if value is False or value == "False":
        return False
    raise ValueError("resolved boolean prediction metadata required")


def normalize_predictions(rows, target):
    if target not in {"NCEI-native-duration", "T-OBS", "T-CAL"} or not rows:
        raise ValueError("known nonempty source-specific prediction set required")
    result = []
    for r in rows:
        if r.get("target", target) != target:
            raise ValueError("prediction target mismatch")
        if "prediction_precision_passed" in r and not _boolean(r["prediction_precision_passed"]):
            raise ValueError("failed predictive numerical precision cannot enter comparison")
        try:
            values = {
                key: float(r[key])
                for key in ["distance_km", "pit", "q05", "q25", "q50", "q75", "q95"]
            }
            values["observed_native_minutes"] = float(
                r.get("observed_native_minutes", r.get("observed_minutes"))
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("resolved native prediction columns required") from exc
        if not np.isfinite(list(values.values())).all():
            raise ValueError("finite native predictions required")
        ambiguity = r.get("coverage90_numerically_ambiguous")
        result.append(
            {
                **{key: r[key] for key in ["record_id", "event_id", "sequence"]},
                "target": target,
                **values,
                "seen_site": _boolean(r.get("seen_site", r.get("seen_site_in_training"))),
                "prediction_precision_passed": True if "prediction_precision_passed" in r else None,
                "coverage90_numerically_ambiguous": None
                if ambiguity in {None, "", "unknown"}
                else _boolean(ambiguity),
            }
        )
    return result


def collect_models(root):
    """Return the ten frozen source/model views only after independent full-CV QA."""
    import hashlib

    from analysis.arrival.evidence import read_rows
    from analysis.arrival.model_data import CONTRACT, load_lanes, sequence_folds
    from analysis.arrival.model_scoring import aggregate_score
    from analysis.arrival.model_sequence_report import validate_predictions

    complete = verify_complete_cv(root)
    pins = {
        str(
            (checked_path(root, CONTINUATION) / "review-acceptance.json").relative_to(root)
        ): sha256(checked_path(root, CONTINUATION) / "review-acceptance.json")
    }
    pins.update(complete["files"])

    def reviewed_path(path):
        p = checked_path(root, str(path))
        name = str(p.relative_to(root))
        if name not in complete["files"] or sha256(p) != complete["files"][name]:
            raise ValueError("every consumed science artifact must be in complete-CV review")
        pins[name] = complete["files"][name]
        return p

    def read(path):
        return json.loads(reviewed_path(path).read_text())

    def table(path):
        return read_rows(reviewed_path(path))

    def checked_review(path, status):
        qa = read(path)
        if (
            qa.get("status") != status
            or qa.get("reserved_outcomes") != "sealed"
            or not qa.get("independent_checker")
        ):
            raise ValueError("source-specific independent acceptance required")
        for p, h in qa.get("files", {}).items():
            if sha256(checked_path(root, p)) != h:
                raise ValueError("accepted source evidence changed")
            pins[p] = h
        return qa

    preflight = tomllib.loads(reviewed_path(CONTRACT).read_text())
    if any(complete["files"].get(p) != h for p, h in preflight["inputs"].items()):
        raise ValueError("all frozen outcome inputs must be reviewed before parsing")
    lanes, contract = load_lanes(root)
    if any(complete["files"].get(p) != h for p, h in contract["inputs"].items()):
        raise ValueError("frozen native inputs must be covered by complete-CV review")
    pins.update(contract["inputs"])
    cohorts = {
        target: hashlib.sha256(
            json.dumps(
                {
                    "target": target,
                    "contract": contract,
                    "primary_record_ids": sorted(np.array(lane.record_ids)[lane.included].tolist()),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        for target, lane in lanes.items()
    }
    models = {}
    for target in lanes:
        for kind in ["pooled", "distance"]:
            folder = checked_path(
                root,
                f"artifacts/models/arrival-timing/analytic-gaussian-baselines-v1/{target}/{kind}",
            )
            qa = checked_review(
                folder / "review-acceptance.json", "accepted_numerical_source_specific_comparator"
            )
            manifest = folder / "output-checksums.json"
            if qa["manifest_sha256"] != sha256(manifest):
                raise ValueError("analytic manifest changed")
            for name, h in read(manifest).items():
                path = checked_path(root, str(folder / name))
                if sha256(path) != h:
                    raise ValueError("analytic output changed")
                pins[str(path.relative_to(root))] = h
            summary = read(folder / "summary.json")
            if not all(
                summary[k] for k in ["complete", "eligible_for_comparison", "precision_passed"]
            ):
                raise ValueError("incomplete analytic comparator")
            events = table(folder / "event-joint-scores.csv")
            predictions = normalize_predictions(
                table(folder / "held-out-record-predictions.csv"), target
            )
            models[(target, kind)] = {
                "events": events,
                "predictions": predictions,
                "summary": summary,
                "folds": [],
            }
    parent = checked_path(root, "artifacts/models/arrival-timing/bridge-sequence-validation-v1")
    first_cases = read(parent / "plan.json")["cases"]
    previous = checked_path(root, "artifacts/models/arrival-timing/bridge-sequence-continuation-v1")
    previous_cases = read(previous / "plan.json")["cases"]
    current = checked_path(root, CONTINUATION)
    current_cases = read(current / "plan.json")["cases"]
    registry = read(current / "reviewed-resolutions.json")
    for record in registry.values():
        if sha256(checked_path(root, record["path"])) != record["sha256"]:
            raise ValueError("reviewed resolution registry changed")
    for target in lanes:
        for kind in ["event", "distance-scale"] if target == "NCEI-native-duration" else ["event"]:
            models[(target, kind)] = {"events": [], "predictions": [], "folds": []}

    def choose(folder, case):
        options = []
        for number in [1, 2]:
            p = folder / "jobs" / f"{case['id']}-attempt-{number}"
            if not (p / "result.json").exists():
                continue
            value = read(p / "result.json")
            expected = {**case["job"], **({"draws": 4000, "tune": 2000} if number == 2 else {})}
            if value["job"] != expected:
                raise ValueError("fold job identity changed")
            if (
                value["status"] == "computed_pending_review"
                and value["score_precision_passed"]
                and value["prediction_precision_passed"]
            ):
                options.append((p, value))
        if len(options) != 1:
            raise ValueError("exactly one accepted direct fold required")
        return options[0]

    def add(case, source, *, resolved=None, tohoku=None):
        original = read(source / "result.json")
        target, kind = case["job"]["target"], case["job"]["kind"]
        if any(
            original["job"][k] != case["job"][k] for k in case["job"] if k not in {"draws", "tune"}
        ):
            raise ValueError("source fold target/job changed")
        if not original["prediction_precision_passed"]:
            raise ValueError("failed predictive precision cannot be replaced by score integration")
        if resolved:
            qa = checked_review(resolved, "accepted_same_model_fold_resolution")
            if qa["case_id"] != case["id"]:
                raise ValueError("resolution case mismatch")
            value = read(qa["derived_result"])
            if value["source_result"] != str((source / "result.json").relative_to(root)) or value[
                "source_result_sha256"
            ] != sha256(source / "result.json"):
                raise ValueError("resolved source identity changed")
            pred = source / "held-out-record-predictions.csv"
            if value["training_only_predictions"] != str(pred.relative_to(root)) or value[
                "training_only_predictions_sha256"
            ] != sha256(pred):
                raise ValueError("resolved predictions changed")
            events, fold = value["events"], value["fold_score"]
        elif tohoku:
            checked_review(
                tohoku / "review-acceptance.json", "accepted_primary_score_and_independent_repeat"
            )
            value = read(tohoku / "primary-path-result.json")
            if not value["precision_passed"] or len(original["events"]) != 1:
                raise ValueError("accepted single-event Tohoku path required")
            native = original["events"][0]
            events = [
                {
                    **{k: native[k] for k in ["event_id", "sequence", "records"]},
                    **{
                        k: value[k]
                        for k in [
                            "joint_log_predictive",
                            "normalized_event_score",
                            "normalized_mcse",
                            "precision_passed",
                        ]
                    },
                    "monte_carlo_used": True,
                }
            ]
            fold = {
                "events": 1,
                "equal_event_score": value["normalized_event_score"],
                "mcse_equal_event_score": value["normalized_mcse"],
                "event_precision_passed": True,
            }
        else:
            if (
                original["status"] != "computed_pending_review"
                or not original["score_precision_passed"]
            ):
                raise ValueError("unresolved fold cannot enter comparisons")
            events, fold = original["events"], original["fold_score"]
        model = models[(target, kind)]
        model["events"] += events
        model["folds"].append(fold)
        model["predictions"] += normalize_predictions(
            table(source / "held-out-record-predictions.csv"), target
        )

    source, _ = choose(parent, first_cases[0])
    add(first_cases[0], source)
    source = parent / "jobs" / f"{first_cases[1]['id']}-attempt-1"
    add(
        first_cases[1],
        source,
        tohoku=checked_path(
            root, "artifacts/models/arrival-timing/tohoku-joint-score-integration-v1"
        ),
    )
    for case in previous_cases[:8]:
        source, _ = choose(previous, case)
        add(case, source)
    case = previous_cases[8]
    source = previous / "jobs" / f"{case['id']}-attempt-1"
    add(
        case,
        source,
        resolved=checked_path(
            root,
            "artifacts/models/arrival-timing/event-score-cubature-v1/NCEI-native-duration-event-fold-06/review-acceptance.json",
        ),
    )
    for case in current_cases:
        if case["id"] in registry:
            qa = read(registry[case["id"]]["path"])
            value = read(qa["derived_result"])
            source = checked_path(root, value["source_result"]).parent
            add(case, source, resolved=checked_path(root, registry[case["id"]]["path"]))
        else:
            source, _ = choose(current, case)
            add(case, source)
    for (target, kind), model in models.items():
        lane = lanes[target]
        validate_predictions(lane, model["predictions"])
        events = model["events"]
        expected = {}
        for i in np.flatnonzero(lane.included):
            expected.setdefault(lane.event_ids[i], []).append(lane.record_ids[i])
        if len(events) != len(expected) or {e["event_id"] for e in events} != set(expected):
            raise ValueError("complete distinct eligible event scores required")
        normalized = []
        for e in events:
            n = len(expected[e["event_id"]])
            seq = {
                lane.sequences[i]
                for i in np.flatnonzero(lane.included)
                if lane.event_ids[i] == e["event_id"]
            }
            if (
                float(e["records"]) != n
                or {e["sequence"]} != seq
                or _boolean(e["precision_passed"]) is not True
                or not np.isfinite(
                    [float(e["joint_log_predictive"]), float(e["normalized_event_score"])]
                ).all()
                or not np.isclose(
                    float(e["joint_log_predictive"]) / n,
                    float(e["normalized_event_score"]),
                    atol=1e-10,
                    rtol=0,
                )
            ):
                raise ValueError("native event score membership, measure or precision changed")
            normalized.append(
                {
                    "event_id": e["event_id"],
                    "sequence": e["sequence"],
                    "records": n,
                    "joint_log_predictive": float(e["joint_log_predictive"]),
                    "normalized_event_score": float(e["normalized_event_score"]),
                    "precision_passed": True,
                    "target": target,
                    "cohort_sha256": cohorts[target],
                    "record_membership_sha256": hashlib.sha256(
                        json.dumps(sorted(expected[e["event_id"]]), separators=(",", ":")).encode()
                    ).hexdigest(),
                    "normalized_mcse": float(e["normalized_mcse"])
                    if e.get("normalized_mcse") not in {None, "not_applicable"}
                    else None,
                    "normalized_deterministic_error": float(
                        e.get(
                            "normalized_numerical_error_estimate",
                            e.get("numerical_error_estimate_per_record", 0.0),
                        )
                    ),
                }
            )
        model["events"] = normalized
        if model["folds"]:
            summary = aggregate_score(model["folds"], max_mcse=0.002)
            if not summary["precision_passed"] or summary["sequence_refits"] != len(
                sequence_folds(lane)
            ):
                raise ValueError("global Monte Carlo precision or fold conservation failed")
            error = sum(
                f["events"] * f.get("mean_deterministic_error_estimate", 0.0)
                for f in model["folds"]
            ) / len(events)
            summary.update(
                monte_carlo_standard_error=summary["mcse_equal_event_score"],
                mean_numerical_error_estimate=error,
                monte_carlo_used=any(f.get("monte_carlo_used", True) for f in model["folds"]),
            )
            model["summary"] = summary
        if not np.isclose(
            model["summary"]["equal_event_score"],
            np.mean([e["normalized_event_score"] for e in normalized]),
            atol=1e-10,
            rtol=0,
        ):
            raise ValueError("equal-event weighting changed")
        model["summary"].update(
            target=target,
            kind=kind,
            records=int(lane.included.sum()),
            events=len(events),
            row_weighted_joint_score=sum(e["joint_log_predictive"] for e in normalized)
            / lane.included.sum(),
            cohort_sha256=cohorts[target],
        )
    if any(sha256(checked_path(root, p)) != h for p, h in pins.items()):
        raise ValueError("comparison input drift")
    return models, pins
