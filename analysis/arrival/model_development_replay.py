"""Read-only G replay with original scientific predicates and diagnostic deltas.

The archived oracle is immutable evidence. Its derived error magnitudes need not
be bit-identical across evaluations; scientific bounds and identity checks do.
Scientific imports remain downstream of the coordinator's startup bootstrap.
"""

# pyright: basic
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, cast

SELF = "analysis/arrival/model_development_replay.py"
TEST = "tests/test_arrival_model_development_replay.py"
CONSUMED = (SELF, TEST)
PROOF_CONTRACT = "original_scientific_checks_diagnostic_recomputation_v2"
POINT_DIAGNOSTICS = (
    "logp_absolute_error",
    "logp_prior_offset_corrected_error",
    "prior_normalizer_offset",
    "prior_offset_drift",
    "gradient_max_absolute_error",
)
ORACLE_KEYS = {
    "passed",
    "points",
    "prior_only_checks",
    "selected_prior_scale_dtypes",
    "normal_log_scale_offset_prediction",
    "normalizer_source",
    "measure",
    "prior_normalizer_scope",
}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _finite(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _validate(oracle: Any, protocol: dict[str, Any]) -> None:
    _require(type(oracle) is dict and set(oracle) == ORACLE_KEYS, "exact oracle schema required")
    _require(oracle["passed"] is True, "original scientific oracle must pass")
    labels = ["truth", *(f"chain-{c}-draw-{d}" for c, d in protocol["oracle_positions"])]
    points = cast(list[dict[str, Any]], oracle["points"])
    prior = cast(list[dict[str, Any]], oracle["prior_only_checks"])
    _require(type(points) is list and len(points) == len(labels), "exact oracle points required")
    _require(type(prior) is list and len(prior) == len(labels) + 1, "exact prior points required")
    for row, label in zip(points, labels, strict=True):
        _require(
            type(row) is dict
            and set(row) == {"point", "passed", *POINT_DIAGNOSTICS}
            and type(row["point"]) is str
            and row["point"] == label
            and row["passed"] is True,
            "exact ordered passing oracle point required",
        )
        _require(
            all(_finite(row[k]) for k in POINT_DIAGNOSTICS), "finite float diagnostics required"
        )
        _require(
            all(row[k] >= 0 for k in POINT_DIAGNOSTICS if k != "prior_normalizer_offset"),
            "absolute error and drift diagnostics must be nonnegative",
        )
    for row, label in zip(prior, ["truth", "fixed_prior_shift", *labels[1:]], strict=True):
        _require(
            type(row) is dict
            and set(row) == {"point", "offset"}
            and type(row["point"]) is str
            and row["point"] == label
            and _finite(row["offset"]),
            "exact finite prior-only diagnostic required",
        )
    offset = prior[0]["offset"]
    _require(
        abs(offset) <= protocol["prior_normalizer_offset_bound"]
        and all(abs(r["offset"] - offset) <= protocol["oracle_logp_atol"] for r in prior),
        "original prior-only bounds must pass",
    )
    _require(
        all(
            r["logp_absolute_error"] <= protocol["oracle_uncorrected_logp_atol"]
            and r["logp_prior_offset_corrected_error"] <= protocol["oracle_logp_atol"]
            and r["prior_offset_drift"] <= protocol["oracle_logp_atol"]
            and abs(r["prior_normalizer_offset"] - offset) <= protocol["oracle_logp_atol"]
            for r in points
        ),
        "original joint/prior diagnostic bounds must pass",
    )
    dtypes = oracle["selected_prior_scale_dtypes"]
    _require(
        type(dtypes) is dict
        and all(
            type(k) is str and type(v) is str and v in {"float32", "float64"}
            for k, v in dtypes.items()
        ),
        "exact dtype metadata required",
    )
    predicted = oracle["normal_log_scale_offset_prediction"]
    _require(
        (_finite(predicted) if dtypes else predicted is None),
        "finite predicted normalizer required",
    )
    _require(
        all(
            type(oracle[k]) is str
            for k in ["normalizer_source", "measure", "prior_normalizer_scope"]
        ),
        "exact oracle scope metadata required",
    )


def compare_diagnostics(saved: Any, fresh: Any, protocol: dict[str, Any]) -> dict[str, Any]:
    """No cross-run tolerance: exact identities, original bounds, explicit deltas.

    The fresh value must come from unchanged G.numerical_oracles, whose passing
    predicate includes the original componentwise gradient np.allclose. A scalar
    maximum-error cutoff would change that predicate and is deliberately absent.
    """
    _validate(saved, protocol)
    _validate(fresh, protocol)
    identity = ORACLE_KEYS - {"points", "prior_only_checks"}
    _require(
        all(type(saved[k]) is type(fresh[k]) and saved[k] == fresh[k] for k in identity),
        "non-diagnostic oracle values must match exactly",
    )
    changes = []
    for section, keys in [("points", POINT_DIAGNOSTICS), ("prior_only_checks", ("offset",))]:
        for i, (old, new) in enumerate(zip(saved[section], fresh[section], strict=True)):
            for key in keys:
                if old[key] != new[key]:
                    changes.append(
                        dict(
                            path=f"{section}[{i}].{key}",
                            saved=old[key],
                            fresh=new[key],
                            absolute_delta=abs(old[key] - new[key]),
                        )
                    )
    return dict(
        proof_contract=PROOF_CONTRACT,
        original_exact_oracle_equal=saved == fresh,
        original_scientific_predicates_passed=True,
        fresh_original_componentwise_gradient_predicate=True,
        cross_run_numeric_tolerance_used=False,
        diagnostic_deltas=changes,
    )


def case_artifacts(root: Path, job, pins, accepted=None) -> dict[str, Any]:
    """Preserve frozen G's complete chain; only derived diagnostic equality differs."""
    root = Path(root)
    for name in CONSUMED:
        path = root / name
        _require(
            path.resolve() == path
            and path.is_file()
            and pins.get(name) == hashlib.sha256(path.read_bytes()).hexdigest(),
            "complete replay source pins required before scientific imports",
        )
    import numpy as np

    from analysis.arrival import model_development_recovery as G

    admission = G.verify_gate(root)
    G.data._require(pins, admission["files"])
    if job not in admission["gate"]["jobs"]:
        raise ValueError("exact prospectively admitted recovery job required")
    output, raw = G.case_paths(root, job)
    manifest_path = str((output / "output-checksums.json").relative_to(root))
    manifest = json.loads(G.data._path(root, manifest_path).read_text())
    required = (
        G.fit.FIT_FILES
        | {"numerical-oracles.json", "summary.json", "truth-quantiles.csv"}
        | {name.replace("_", "-") + ".csv" for name in G.TABLES}
    )
    if not required <= set(manifest):
        raise ValueError("complete recovery artifact inventory required")
    files = {str((output / name).relative_to(root)): digest for name, digest in manifest.items()}
    files.update(
        {
            manifest_path: G.sha256(output / "output-checksums.json"),
            str(raw.relative_to(root)): G.sha256(raw),
        }
    )
    G.data._unchanged(root, files)
    result, inputs, membership = [
        json.loads((output / name).read_text())
        for name in ["result.json", "inputs.json", "membership.json"]
    ]
    target, spec = admission["specs"][job["model_key"]]
    if (
        result.get("status") != G.SUCCESS
        or result.get("job") != job
        or result.get("posterior") != str(raw.relative_to(root))
        or result.get("posterior_sha256") != files[str(raw.relative_to(root))]
        or result.get("confirmation_outcomes_parsed") is not True
        or result.get("reserved_outcomes") != "sealed"
        or result.get("calibration_or_coverage_claim") is not False
        or inputs != dict(files=admission["files"], model_spec=spec, protocol=G.protocol())
        or json.loads((output / "job.json").read_text()) != job
    ):
        raise ValueError("exact frozen recovery result/input/scope binding required")
    views = G.data.load_full_development_lanes(root, admission["files"])
    design = views["combined"][target]
    fake, effects = G.simulate(design, spec["kind"], job["truth"], job["simulator_seed"])
    ids = np.flatnonzero(fake.included)
    if membership != dict(
        training_record_ids=[fake.record_ids[int(i)] for i in ids],
        design_sha256=G._design_sha(design),
        original_membership=views["membership"][target],
        truth=job["truth"],
        event_effect_truth=effects,
    ):
        raise ValueError("full-design identities and seeded synthetic response proof must replay")
    base, wider, settings = G.fit._priors(root, target, spec)
    G.fit._replay_fit(root, output, raw, fake, ids, spec, job, result)
    post = G.fit._read_population(root, raw, fake, ids, spec["kind"])
    model = G.build_sensitivity_model(
        fake, spec["kind"], base, spec["prior_variant"], wider_prior=wider, indices=ids
    )
    oracle = G.numerical_oracles(model, fake, spec["kind"], job["truth"], settings, post)
    comparison = compare_diagnostics(
        json.loads((output / "numerical-oracles.json").read_text()), oracle, G.protocol()
    )
    summary = G.summarize_posterior(
        fake, spec["kind"], post, indices=ids, seed=job["conditional_seed"], draws=800
    )
    if (
        not G._summary_valid(summary)
        or json.loads((output / "summary.json").read_text()) != summary
    ):
        raise ValueError("conditional_seed800-draw recovery summary must replay")
    for name in G.TABLES:
        G.fit._replay_table(output / (name.replace("_", "-") + ".csv"), summary[name])
    G.fit._replay_table(output / "truth-quantiles.csv", G._truth_table(post, job["truth"]))
    if accepted is not None and accepted.get("files") != files:
        raise ValueError("immutable accepted recovery inventory changed")
    G.data._unchanged(root, {**admission["files"], **files, **{n: pins[n] for n in CONSUMED}})
    return dict(
        files=files,
        result=str((output / "result.json").relative_to(root)),
        posterior=str(raw.relative_to(root)),
        posterior_sha256=files[str(raw.relative_to(root))],
        role=job["role"],
        proof_contract=PROOF_CONTRACT,
        original_exact_oracle_equal=comparison["original_exact_oracle_equal"],
        diagnostic_comparison=comparison,
    )
