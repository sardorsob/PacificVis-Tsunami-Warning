"""Pure Gaussian identities and synthetic provenance; no real data or sampler."""

# pyright: basic
import copy
import json
from typing import Any, cast

import numpy as np
import pytest
from scipy import stats

from analysis.arrival import model_development_score_resolution as r


def test_exact_gaussian_training_evidence_and_predictive_ratio():
    distance = np.array([100.0, 400, 900, 1800, 3000, 7000])
    x = r.design_matrix(distance)
    y = np.sin(np.arange(6)) / 5
    events = np.array(["a", "a", "b", "b", "c", "c"])
    theta = np.array([[0.3, 0.2, 0.1, 0.15]])
    evidence, mean, covariance = r.training_conditional(x, y, events, r.weights(distance), theta)
    prior = np.diag(np.array([0.5, 0.25, 0.5]) ** 2)
    z = (events[:, None] == np.unique(events)[None, :]).astype(float)
    sigma = r.weights(distance) @ theta[0, :3]
    c = np.diag(sigma**2) + theta[0, 3] ** 2 * z @ z.T + x @ prior @ x.T
    np.testing.assert_allclose(
        evidence[0], cast(Any, stats.multivariate_normal.logpdf)(y, cov=c), atol=1e-11
    )
    nd = np.array([200.0, 1500, 6000])
    nx, ny = r.design_matrix(nd), np.array([0.1, -0.2, 0.3])
    native = np.exp(ny) * nd / 12
    value = r.predictive_loglik(nx, ny, native, r.weights(nd), theta, mean, covariance)[0]
    sigma_new = r.weights(nd) @ theta[0, :3]
    cross = x @ prior @ nx.T
    nc = np.diag(sigma_new**2) + theta[0, 3] ** 2 + nx @ prior @ nx.T
    joint = np.block([[c, cross], [cross.T, nc]])
    expected = cast(Any, stats.multivariate_normal.logpdf)(np.r_[y, ny], cov=joint) - evidence[0]
    expected -= np.log(native).sum()
    np.testing.assert_allclose(value, expected, atol=1e-10)


def test_fixed_protocol_is_not_the_failed_pilot_and_has_zero_sampler_calls():
    p = r.protocol()
    assert p["levels"] == [65536, 262144] and p["proposal_df"] == [5, 9]
    assert p["scrambles"] == [2996110800, 2996110900, 2996111000, 2996111100]
    assert p["mcse_max"] == 0.005 and p["weight_concentration_min"] == 100
    assert p["agreement_max"] == 0.0005 and p["replicate_range"].startswith("diagnostic_only")
    assert r.resources()["sampler_call_slots"] == 0 and r.resources()["cores"] == 2
    assert r.resources()["job_max_bytes"] == 32 * 1024**2
    assert r.job_descriptor()["sampler_calls"] == 0


@pytest.mark.parametrize(
    "theta", [[0.3, 0.2, 0.1, 0.15], [0.8, 0.09, 0.07, 0.001], [2.0, 1.0, 0.7, 3.0]]
)
def test_proper_halfnormal_prior_and_four_log_jacobians(theta):
    theta = np.asarray(theta)
    expected = stats.halfnorm.logpdf(theta, scale=0.4).sum() + np.log(theta).sum()
    np.testing.assert_allclose(r.logscale_prior(np.log(theta)[None, :])[0], expected, atol=1e-12)


@pytest.mark.parametrize("bad", [np.nan, np.inf, 0.0, -1.0])
def test_invalid_positive_hyperparameter_rejected(bad):
    theta = np.array([[0.3, 0.2, 0.1, bad]])
    with pytest.raises(ValueError):
        r.training_conditional(
            np.ones((2, 3)), np.zeros(2), np.array(["a", "a"]), np.ones((2, 3)) / 3, theta
        )


def test_prior_overflow_is_retained_as_failure_not_clipped():
    with pytest.raises(FloatingPointError):
        r.logscale_prior(np.full((1, 4), 1000.0))


def test_streamed_log_sums_equal_dense_extreme_weights():
    values = np.array([-100000.0, -1000.0, -900.0, -899.0, -10000.0, -901.0])
    total = r.empty_sum()
    for block in np.array_split(values, 3):
        total = r.update_sum(total, block)
    summary = r.sum_summary(total)
    scaled = np.exp(values - values.max())
    np.testing.assert_allclose(
        summary["concentration"], scaled.sum() ** 2 / (scaled**2).sum(), rtol=1e-10
    )
    np.testing.assert_allclose(
        summary["log_integral"], values.max() + np.log(scaled.mean()), atol=1e-12
    )
    assert total["count"] == len(values)
    with pytest.raises(ValueError):
        r.update_sum(total, np.array([np.nan]))


@pytest.mark.parametrize("df", [5, 9])
def test_exact_normalized_t_proposal_and_nested_sobol_prefix(df):
    from scipy.special import gammaln

    proposal = dict(mean=[-0.8, -1.2, -2.0, -1.8], covariance=(np.eye(4) * 0.05 + 0.002).tolist())
    engine = cast(Any, stats.qmc.Sobol)(5, scramble=True, seed=2996110800)
    chunks = np.concatenate([engine.random(4), engine.random(4)])
    full = cast(Any, stats.qmc.Sobol)(5, scramble=True, seed=2996110800).random_base2(3)
    np.testing.assert_array_equal(chunks, full)
    nodes, logq = r.proposal_nodes(chunks, proposal, df)
    shape = np.array(proposal["covariance"]) * (df - 2) / df
    delta = nodes - np.array(proposal["mean"])
    q = np.einsum("bi,ij,bj->b", delta, np.linalg.inv(shape), delta)
    expected = (
        gammaln((df + 4) / 2)
        - gammaln(df / 2)
        - 2 * np.log(df * np.pi)
        - 0.5 * np.linalg.slogdet(shape)[1]
        - (df + 4) / 2 * np.log1p(q / df)
    )
    np.testing.assert_allclose(logq, expected, atol=1e-12)
    for bad in [0.0, 1.0, np.nan]:
        broken = chunks.copy()
        broken[0, 0] = bad
        with pytest.raises(ValueError):
            r.proposal_nodes(broken, proposal, df)


def original_case() -> dict[str, Any]:
    distance = np.array([100.0, 400, 900, 1800, 3000, 7000])
    nd = np.array([200.0, 1500, 6000])
    ny = np.array([0.1, -0.2, 0.3])
    original = []
    for event in [f"e{i}" for i in range(12)] + [r.data.CROSS_CHECK, r.EVENT]:
        original.append(
            dict(
                event_id=event,
                records=20 if event == r.EVENT else 10,
                score=dict(normalized_event_score=-1.0, precision_passed=event != r.EVENT),
                influence=np.zeros((4, 2000)),
            )
        )
    return dict(
        x=r.design_matrix(distance),
        response=np.sin(np.arange(6)) / 5,
        events=np.array(["a", "a", "b", "b", "c", "c"]),
        w=r.weights(distance),
        new_x=r.design_matrix(nd),
        new_response=ny,
        new_native=np.exp(ny) * nd / 12,
        new_w=r.weights(nd),
        proposal=dict(
            mean=np.log([0.3, 0.2, 0.1, 0.15]).tolist(), covariance=(np.eye(4) * 0.02).tolist()
        ),
        originals=original,
    )


@pytest.fixture
def tiny_bundle(tmp_path, monkeypatch):
    cfg = r.protocol()
    cfg.update(
        levels=[4, 8],
        stream_block_size=4,
        arithmetic_batch_size=2,
        mcse_max=1e6,
        weight_concentration_min=1.0,
        agreement_max=1e6,
        aggregate_mcse_max=1e6,
    )
    monkeypatch.setattr(r, "protocol", lambda: copy.deepcopy(cfg))
    pins = {}
    for name in [
        r.GATE,
        r.SELF,
        r.CLI,
        r.TEST,
        r.data.FREEZE,
        r.ORIGINAL + "/held-out-record-predictions.csv",
        r.ORIGINAL + "/event-results.json",
        r.ORIGINAL + "/direct-score-arrays.npz",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("closed source")
        pins[name] = r.sha256(path)
    admission = dict(
        root=tmp_path, files=pins, original_files=dict(pins), original_job={"id": "original-0"}
    )
    monkeypatch.setattr(r, "verify_gate", lambda root: admission)
    monkeypatch.setattr(r, "load_case", lambda root, admission: original_case())
    return tmp_path, admission, cfg


def test_complete_stream_bytes_replay_and_cached_proof_never_integrates(tiny_bundle, monkeypatch):
    root, admission, _ = tiny_bundle
    result = r.run_resolution(root, root / r.CASE_OUTPUT)
    assert result["status"] == r.SUCCESS and result["sampler_calls"] == 0
    assert result["original_predictions"]["unchanged"]
    assert not list((root / r.CASE_OUTPUT).rglob("*.npz"))
    candidate = r.candidate_artifacts(root, admission["files"])
    assert candidate["status"] == r.UNVERIFIED and not candidate["semantics_verified"]
    with pytest.raises(ValueError, match="needs_independent_cold_replay"):
        r.case_artifacts(root, admission["files"])
    cold = r.replay_resolution(root)
    assert cold["passed"]
    write_test_anchors(root, admission, candidate, cold)
    proof = r.case_artifacts(root, admission["files"])
    assert proof["status"] == r.SUCCESS and proof["semantics_verified"]
    before = {p: p.read_bytes() for p in (root / r.CASE_OUTPUT).rglob("*") if p.is_file()}
    monkeypatch.setattr(r, "integrate", lambda *a: pytest.fail("expensive replay in cached proof"))
    assert r.case_artifacts(root, admission["files"], proof) == proof
    assert before == {p: p.read_bytes() for p in before}
    with pytest.raises(ValueError, match="no overwrite"):
        r.run_resolution(root, root / r.CASE_OUTPUT)


def test_timeout_retains_partial_blocks_without_accepted_aggregate(tiny_bundle, monkeypatch):
    root, admission, _ = tiny_bundle
    original = r._resource_check

    def stop(output, started, **kwargs):
        if len(list(output.glob("blocks/*.json"))) >= 2:
            raise TimeoutError("fixed timeout")
        return original(output, started)

    monkeypatch.setattr(r, "_resource_check", stop)
    # Final resource check can propagate the timeout, but terminal evidence must survive.
    with pytest.raises(TimeoutError):
        r.run_resolution(root, root / r.CASE_OUTPUT)
    saved = json.loads((root / r.CASE_OUTPUT / "result.json").read_text())
    assert saved["status"] == r.UNRESOLVED and saved["quadrature_complete"] is False
    assert saved["aggregates"]["primary"] is None and saved["resolved_event_score"] is None
    assert len(list((root / r.CASE_OUTPUT / "blocks").glob("*.json"))) == 2
    monkeypatch.setattr(r, "_resource_check", original)
    candidate = r.candidate_artifacts(root, admission["files"])
    assert candidate["computed_status"] == r.UNRESOLVED and candidate["status"] == r.UNVERIFIED


def test_complete_but_precision_failed_never_supplies_primary_mean(tiny_bundle):
    root, _, cfg = tiny_bundle
    cfg["weight_concentration_min"] = 1e99
    result = r.run_resolution(root, root / r.CASE_OUTPUT)
    assert result["status"] == r.UNRESOLVED and result["quadrature_complete"]
    assert result["resolved_event_score"] is None and result["aggregates"]["primary"] is None
    assert result["diagnostic_estimate"]["selected"]["normalized_score"] is not None
    assert r.replay_resolution(root)["status"] == r.UNRESOLVED


@pytest.mark.parametrize("damage", ["extra", "missing", "changed", "directory", "symlink"])
def test_cached_physical_inventory_and_bytes_are_exact(tiny_bundle, damage):
    root, admission, _ = tiny_bundle
    r.run_resolution(root, root / r.CASE_OUTPUT)
    output = root / r.CASE_OUTPUT
    if damage == "extra":
        (output / "extra.nc").write_bytes(b"preserve")
    elif damage == "missing":
        (output / "precision.json").unlink()
    elif damage == "changed":
        (output / "proposal.json").write_text("{}")
    elif damage == "directory":
        (output / "unexpected").mkdir()
    else:
        (output / "alias").symlink_to(output / "result.json")
    with pytest.raises((ValueError, FileNotFoundError)):
        r.case_artifacts(root, admission["files"])


def test_rolling_sum_does_not_silently_drop_bad_block(tiny_bundle, monkeypatch):
    root, _, _ = tiny_bundle
    original = r.numeric_block
    calls = 0

    def invalid(case, nodes):
        nonlocal calls
        calls += 1
        if calls == 3:
            return np.full(len(nodes), np.nan), np.zeros(len(nodes))
        return original(case, nodes)

    monkeypatch.setattr(r, "numeric_block", invalid)
    result = r.run_resolution(root, root / r.CASE_OUTPUT)
    assert result["status"] == r.UNRESOLVED and not result["quadrature_complete"]
    assert len(list((root / r.CASE_OUTPUT / "blocks").glob("*.json"))) == 1


def test_source_drift_after_last_block_prevents_success(tiny_bundle, monkeypatch):
    root, admission, _ = tiny_bundle
    original = r.integrate

    def drift(*args):
        answer = original(*args)
        (root / r.ORIGINAL / "held-out-record-predictions.csv").write_text("changed")
        return answer

    monkeypatch.setattr(r, "integrate", drift)
    result = r.run_resolution(root, root / r.CASE_OUTPUT)
    assert result["status"] == r.UNRESOLVED and result["aggregates"]["primary"] is None
    with pytest.raises(ValueError):
        r.case_artifacts(root, admission["files"])


def test_shared_covariance_and_conservative_triangle_bound(monkeypatch):
    case = original_case()
    influence = np.tile(np.sin(np.arange(2000) / 3), (4, 1))
    for item in case["originals"]:
        item["influence"] = influence.copy()
    captured = []

    def diagnostics(value):
        captured.append(value.copy())
        return 0.0004, dict(passed=True), []

    monkeypatch.setattr(r, "_diagnostics", diagnostics)
    qmc = dict(
        precision_passed=True, selected=dict(normalized_score=-2.0, replicate_mcse_normalized=0.004)
    )
    result = r.combined_aggregates(case, qmc)
    np.testing.assert_allclose(captured[0], 13 * influence / 10 / 14)
    np.testing.assert_allclose(captured[1], 12 * influence / 10 / 13)
    assert result["primary"]["mcse_triangle_bound"] == 0.0004 + 0.004 / 14
    assert result["without_crossing_event"]["mcse_triangle_bound"] == 0.0004 + 0.004 / 13
    np.testing.assert_allclose(result["primary"]["equal_event_score"], (-13 - 2) / 14)
    qmc["precision_passed"] = False
    assert r.combined_aggregates(case, qmc)["primary"] is None


@pytest.fixture
def gate_fixture(tmp_path, monkeypatch):
    pins = {}

    def put(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else r.encoded(value))
        pins[name] = r.sha256(path)

    names = (
        set(r.CONSUMED)
        | r.ORIGINAL_FILES
        | {
            r.data.FREEZE,
            r.fit.GATE,
            r.FAILURE_REVIEW,
            r.ORIGINAL_ATTEMPT,
            r.ORIGINAL_CLOSURE,
            r.TRAIN,
            r.CHECK,
            r.RAW,
        }
    )
    for name in names:
        put(name, {})
    monkeypatch.setattr(r, "RAW_SHA", pins[r.RAW])
    job = dict(
        id="dev-ncei-mean-curvature-selected-check",
        model_key=r.MODEL_KEY,
        order=0,
        role="check_evaluate",
        seed=2976110800,
        training_reference={"kind": "historical"},
    )
    oldpins = {r.data.FREEZE: pins[r.data.FREEZE], r.fit.GATE: pins[r.fit.GATE]}
    original = dict(
        files=oldpins,
        gate={"jobs": [job]},
        specs={r.MODEL_KEY: ("NCEI-native-duration", r.BASE_SPEC)},
    )
    monkeypatch.setattr(r.fit, "verify_gate", lambda *a: original)
    put(
        r.ORIGINAL + "/inputs.json",
        dict(
            files=oldpins, model_spec=r.BASE_SPEC, specification_freeze_sha256=pins[r.data.FREEZE]
        ),
    )
    manifest = {
        name: pins[r.ORIGINAL + "/" + name] for name in r.WORKER_FILES - {"output-checksums.json"}
    }
    put(r.ORIGINAL + "/output-checksums.json", manifest)
    persistent = {name: pins[name] for name in r.ORIGINAL_FILES}
    released = [
        dict(
            path=r.fit.CHECK_OUTPUT + "/controller/.controller.lock",
            disposition="released_exclusive_lease",
            sha256="a" * 64,
        )
    ]
    closure = dict(
        persistent_original_files=persistent,
        persistent_original_file_count=13,
        released_ephemeral_files=released,
        original_attempt_receipt=r.ORIGINAL_ATTEMPT,
        original_attempt_receipt_sha256=pins[r.ORIGINAL_ATTEMPT],
        sampler_calls_charged=0,
        sampler_calls_started=0,
    )
    put(r.ORIGINAL_CLOSURE, closure)
    failure = dict(
        status="accepted_frozen_development_initial_precision_failure",
        independent_checker=True,
        reserved_outcomes="sealed",
        files={
            **oldpins,
            **persistent,
            r.ORIGINAL_ATTEMPT: pins[r.ORIGINAL_ATTEMPT],
            r.ORIGINAL_CLOSURE: pins[r.ORIGINAL_CLOSURE],
        },
        persistent_original_files=persistent,
        released_ephemeral_files=released,
        job=job,
        new_sampler_calls=0,
        prediction_rows_precision_passed=151,
        usable_event_scores=13,
        precision_failed_event_count=1,
        accepted_check=False,
        completed_check=False,
        full57_outcomes_parsed=False,
        original_attempt_receipt=r.ORIGINAL_ATTEMPT,
        original_attempt_receipt_sha256=pins[r.ORIGINAL_ATTEMPT],
    )
    put(r.FAILURE_REVIEW, failure)
    gate = dict(
        status="accepted_frozen_arrival_development_numerical_resolution_execution",
        independent_checker=True,
        reserved_outcomes="sealed",
        source_role="frozen_check_numerical_resolution",
        protocol=r.protocol(),
        resources=r.resources(),
        job=r.job_descriptor(),
        sampler_calls=0,
        original_job=job,
        files=dict(pins),
    )
    for key, path in [
        ("specification_freeze", r.data.FREEZE),
        ("original_execution_gate", r.fit.GATE),
        ("failure_review", r.FAILURE_REVIEW),
        ("original_raw", r.RAW),
    ]:
        gate[key] = path
        gate[key + "_sha256"] = pins[path]
    put(r.GATE, gate)
    return tmp_path, gate, put, original


def test_complete_prospective_admission_does_not_load_outcomes(gate_fixture, monkeypatch):
    root, _, _, _ = gate_fixture
    monkeypatch.setattr(
        r.xr, "open_dataset", lambda *a, **k: pytest.fail("native opened during admission")
    )
    assert r.verify_gate(root)["original_job"]["order"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "level",
        "seed",
        "df",
        "threshold",
        "resource",
        "sampler",
        "raw",
        "original_job",
        "source",
        "missing_pin",
        "wrong_prior",
        "released_lock",
        "closure_count",
    ],
)
def test_prospective_admission_rejects_changed_contract(gate_fixture, monkeypatch, change):
    root, gate, put, original = gate_fixture
    if change == "level":
        gate["protocol"]["levels"][1] *= 2
    elif change == "seed":
        gate["protocol"]["scrambles"][0] += 1
    elif change == "df":
        gate["protocol"]["proposal_df"] = [7, 9]
    elif change == "threshold":
        gate["protocol"]["agreement_max"] = 0.005
    elif change == "resource":
        gate["resources"]["job_max_bytes"] *= 2
    elif change == "sampler":
        gate["sampler_calls"] = 1
    elif change == "raw":
        gate["original_raw_sha256"] = "0" * 64
    elif change == "original_job":
        gate["original_job"] = {**gate["original_job"], "order": 1}
    elif change == "source":
        (root / r.SELF).write_text("changed")
    elif change == "missing_pin":
        del gate["files"][r.ORIGINAL_ATTEMPT]
    elif change == "wrong_prior":
        original["specs"] = {
            r.MODEL_KEY: ("NCEI-native-duration", dict(r.BASE_SPEC, prior_variant="t4_matched"))
        }
    elif change == "released_lock":
        failure = json.loads((root / r.FAILURE_REVIEW).read_text())
        failure["released_ephemeral_files"][0]["disposition"] = "still_owned"
        put(r.FAILURE_REVIEW, failure)
        gate["files"][r.FAILURE_REVIEW] = r.sha256(root / r.FAILURE_REVIEW)
        gate["failure_review_sha256"] = gate["files"][r.FAILURE_REVIEW]
    else:
        closure = json.loads((root / r.ORIGINAL_CLOSURE).read_text())
        closure["sampler_calls_started"] = 1
        put(r.ORIGINAL_CLOSURE, closure)
        gate["files"][r.ORIGINAL_CLOSURE] = r.sha256(root / r.ORIGINAL_CLOSURE)
    put(r.GATE, gate)
    monkeypatch.setattr(r.xr, "open_dataset", lambda *a, **k: pytest.fail("native opened"))
    with pytest.raises(ValueError):
        r.verify_gate(root)


def test_pooled_ratio_mcse_preserves_num_den_covariance_and_governs_conservatively():
    cfg = r.protocol()
    prefixes = []
    logden = np.log(np.array([0.7, 1.0, 1.2, 1.1])) + 4000
    lognum = logden + np.array([-0.10, -0.12, -0.11, -0.09])
    for df in cfg["proposal_df"]:
        for rep, seed in enumerate(cfg["scrambles"]):
            for n in cfg["levels"]:
                joint = lognum[rep] - logden[rep]
                prefixes.append(
                    dict(
                        df=df,
                        replicate=rep,
                        seed=seed,
                        n=n,
                        training=dict(log_integral=logden[rep], concentration=1000.0),
                        numerator=dict(log_integral=lognum[rep], concentration=1000.0),
                        joint_log_predictive=joint,
                        normalized_score=joint / 20,
                    )
                )
    value = r.summarize_integration(dict(prefixes=prefixes, unique_nodes=2097152))["selected"]
    a = np.exp(lognum - lognum.max())
    a /= a.mean()
    b = np.exp(logden - logden.max())
    b /= b.mean()
    expected = np.std((a - b) / 20, ddof=1) / 2
    np.testing.assert_allclose(value["paired_pooled_ratio_delta_mcse"], expected, atol=1e-13)
    logse = np.std((lognum - logden) / 20, ddof=1) / 2
    assert value["replicate_mcse_normalized"] == max(value["paired_pooled_ratio_delta_mcse"], logse)
    assert value["df"] == 5 and value["n"] == 262144


def test_total_job_limit_is_independent_of_per_file_limit(tmp_path, monkeypatch):
    source = r.resources()
    source.update(job_max_bytes=10, file_max_bytes=8)
    monkeypatch.setattr(r, "resources", lambda: source)
    (tmp_path / "a").write_bytes(b"a" * 6)
    (tmp_path / "b").write_bytes(b"b" * 6)
    with pytest.raises(ValueError, match="job/file"):
        r._resource_check(tmp_path, 0, clock=lambda: 1)


@pytest.mark.parametrize("native_value", [0.0, -1.0, np.inf, np.nan])
def test_nonpositive_or_nonfinite_native_cannot_be_transformed(native_value):
    case = original_case()
    native = case["new_native"].copy()
    native[0] = native_value
    theta = np.array([[0.3, 0.2, 0.1, 0.15]])
    _, mean, cov = r.training_conditional(
        case["x"], case["response"], case["events"], case["w"], theta
    )
    with pytest.raises(ValueError, match="held native"):
        r.predictive_loglik(
            case["new_x"], case["new_response"], native, case["new_w"], theta, mean, cov
        )


def coherent_prefixes():
    p = r.protocol()
    return [
        dict(
            df=df,
            replicate=rep,
            seed=seed,
            n=n,
            training=dict(log_integral=-500.0, concentration=1000.0),
            numerator=dict(log_integral=-600.0, concentration=1000.0),
            joint_log_predictive=-100.0,
            normalized_score=-5.0,
        )
        for df in p["proposal_df"]
        for rep, seed in enumerate(p["scrambles"])
        for n in p["levels"]
    ]


@pytest.mark.parametrize("field", ["training", "numerator"])
@pytest.mark.parametrize("df,n", [(5, 65536), (5, 262144), (9, 65536), (9, 262144)])
def test_concentration_requires_every_scramble_at_both_fixed_levels(field, df, n):
    rows = coherent_prefixes()
    assert r.summarize_integration(dict(prefixes=rows, unique_nodes=2097152))["precision_passed"]
    next(x for x in rows if x["df"] == df and x["n"] == n and x["replicate"] == 2)[field][
        "concentration"
    ] = 99.0
    assert not r.summarize_integration(dict(prefixes=rows, unique_nodes=2097152))[
        "precision_passed"
    ]


def test_proposal_or_refinement_disagreement_cannot_choose_better_proposal():
    rows = coherent_prefixes()
    for x in rows:
        if x["df"] == 5 and x["n"] == 262144:
            x["numerator"]["log_integral"] += 0.02
            x["joint_log_predictive"] += 0.02
            x["normalized_score"] += 0.001
    result = r.summarize_integration(dict(prefixes=rows, unique_nodes=2097152))
    assert not result["precision_passed"]
    assert result["selected"]["df"] == 5 and result["selected"]["n"] == 262144
    assert not all(x["passed"] for x in result["refinement"] + result["cross_proposal"])


def write_test_anchors(root, admission, candidate, replay) -> tuple[dict[str, Any], dict[str, Any]]:
    closure = {**admission["files"], **candidate["files"]}
    cold = dict(
        status=r.COLD_REVIEW_STATUS,
        independent_checker=True,
        sampler_calls=0,
        reserved_outcomes="sealed",
        source_role="frozen_check_numerical_resolution",
        job=r.job_descriptor(),
        original_job=admission["original_job"],
        execution_gate=r.GATE,
        execution_gate_sha256=admission["files"][r.GATE],
        protocol_sha256=r.fingerprint(r.protocol()),
        worker_sources={p: admission["files"][p] for p in [r.SELF, r.CLI, r.TEST]},
        candidate_files=candidate["files"],
        computed_status=candidate["computed_status"],
        files=closure,
        full_stream_replay={
            k: replay[k] for k in ["passed", "blocks", "unique_nodes", "sampler_calls"]
        },
    )
    r._new_json(root / r.COLD_REVIEW, cold)
    resolved = candidate["computed_status"] == r.SUCCESS
    result = r.CASE_OUTPUT + "/result.json"
    prediction = r.ORIGINAL + "/held-out-record-predictions.csv"
    science = dict(
        status=r.REVIEW_STATUS,
        independent_checker=True,
        original_job=admission["original_job"],
        original_state_sha256=r.ORIGINAL_STATE_SHA,
        specification_freeze_sha256=admission["files"][r.data.FREEZE],
        case0_outcome="accepted_resolution" if resolved else "accepted_unresolved_gap",
        primary_aggregate_available=resolved,
        resolved_result=result if resolved else None,
        resolved_result_sha256=candidate["files"][result] if resolved else None,
        prediction_file=prediction,
        prediction_sha256=admission["files"][prediction],
        files={**closure, r.COLD_REVIEW: r.sha256(root / r.COLD_REVIEW)},
    )
    r._new_json(root / r.REVIEW, science)
    return cold, science


def reseal_candidate(output):
    manifest = json.loads((output / "output-checksums.json").read_text())
    for name in manifest:
        manifest[name] = r.sha256(output / name)
    (output / "output-checksums.json").write_bytes(r.encoded(manifest))


@pytest.mark.parametrize("damage", ["aggregate_score", "aggregate_mcse", "proposal", "probes"])
def test_resealed_candidate_is_unverified_and_cold_replay_rejects_false_semantics(
    tiny_bundle, damage
):
    root, admission, _ = tiny_bundle
    r.run_resolution(root, root / r.CASE_OUTPUT)
    output = root / r.CASE_OUTPUT
    if damage.startswith("aggregate"):
        aggregate = json.loads((output / "aggregate-diagnostics.json").read_text())
        key = "equal_event_score" if damage == "aggregate_score" else "mcse_triangle_bound"
        aggregate["primary"][key] = 99.0 if damage == "aggregate_score" else 0.0
        (output / "aggregate-diagnostics.json").write_bytes(r.encoded(aggregate))
        result = json.loads((output / "result.json").read_text())
        result["aggregates"] = aggregate
        (output / "result.json").write_bytes(r.encoded(result))
    elif damage == "proposal":
        proposal = json.loads((output / "proposal.json").read_text())
        proposal["mean"] = [999.0] * 4
        (output / "proposal.json").write_bytes(r.encoded(proposal))
    else:
        path = next((output / "blocks").glob("*.json"))
        block = json.loads(path.read_text())
        block["probes"][0]["training_logweight"] = 999.0
        path.write_bytes(r.encoded(block))
    reseal_candidate(output)
    candidate = r.candidate_artifacts(root, admission["files"])
    assert candidate["status"] == r.UNVERIFIED and not candidate["semantics_verified"]
    with pytest.raises(ValueError, match="needs_independent_cold_replay"):
        r.case_artifacts(root, admission["files"])
    with pytest.raises(ValueError):
        r.replay_resolution(root)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_cold",
        "missing_science",
        "cold_status",
        "cold_independent",
        "wrong_sources",
        "wrong_candidate",
        "missing_candidate_pin",
        "wrong_replay_count",
        "wrong_outcome",
        "wrong_state",
        "wrong_result",
        "wrong_prediction",
        "cycle",
    ],
)
def test_trusted_proof_requires_two_exact_acyclic_independent_anchors(tiny_bundle, damage):
    root, admission, _ = tiny_bundle
    r.run_resolution(root, root / r.CASE_OUTPUT)
    candidate = r.candidate_artifacts(root, admission["files"])
    replay = r.replay_resolution(root)
    cold, science = write_test_anchors(root, admission, candidate, replay)
    if damage == "missing_cold":
        (root / r.COLD_REVIEW).unlink()
    elif damage == "missing_science":
        (root / r.REVIEW).unlink()
    else:
        if damage == "cold_status":
            cold["status"] = "computed_pending_scientific_review"
        elif damage == "cold_independent":
            cold["independent_checker"] = False
        elif damage == "wrong_sources":
            cold["worker_sources"][r.SELF] = "a" * 64
        elif damage == "wrong_candidate":
            cold["candidate_files"] = {}
        elif damage == "missing_candidate_pin":
            del cold["files"][r.CASE_OUTPUT + "/proposal.json"]
        elif damage == "wrong_replay_count":
            cold["full_stream_replay"]["unique_nodes"] += 1
        elif damage == "wrong_outcome":
            science["case0_outcome"] = "accepted_unresolved_gap"
        elif damage == "wrong_state":
            science["original_state_sha256"] = "a" * 64
        elif damage == "wrong_result":
            science["resolved_result_sha256"] = "a" * 64
        elif damage == "wrong_prediction":
            science["prediction_sha256"] = "a" * 64
        else:
            cold["files"][r.REVIEW] = r.sha256(root / r.REVIEW)
        (root / r.COLD_REVIEW).write_bytes(r.encoded(cold))
        science["files"][r.COLD_REVIEW] = r.sha256(root / r.COLD_REVIEW)
        (root / r.REVIEW).write_bytes(r.encoded(science))
    with pytest.raises(ValueError):
        r.case_artifacts(root, admission["files"])


@pytest.mark.parametrize("damage", ["source", "candidate", "late_cold_review"])
def test_fresh_bytes_after_review_are_mandatory_without_reintegration(
    tiny_bundle, monkeypatch, damage
):
    root, admission, _ = tiny_bundle
    r.run_resolution(root, root / r.CASE_OUTPUT)
    candidate = r.candidate_artifacts(root, admission["files"])
    replay = r.replay_resolution(root)
    write_test_anchors(root, admission, candidate, replay)
    proof = r.case_artifacts(root, admission["files"])
    monkeypatch.setattr(r, "integrate", lambda *a: pytest.fail("cached proof reintegrated"))
    if damage == "source":
        (root / r.SELF).write_text("changed source")
    elif damage == "candidate":
        proposal = json.loads((root / r.CASE_OUTPUT / "proposal.json").read_text())
        proposal["mean"] = [999.0] * 4
        (root / r.CASE_OUTPUT / "proposal.json").write_bytes(r.encoded(proposal))
        reseal_candidate(root / r.CASE_OUTPUT)
    else:
        with (root / r.COLD_REVIEW).open("ab") as stream:
            stream.write(b" ")
    with pytest.raises(ValueError):
        r.case_artifacts(root, admission["files"], proof)


def test_supplement_only_failure_preserves_primary_result(tiny_bundle, monkeypatch):
    root, admission, _ = tiny_bundle
    calls = 0

    def diagnostics(value):
        nonlocal calls
        calls += 1
        return ((0.0001 if calls % 2 else 0.1), dict(passed=True), [])

    monkeypatch.setattr(r, "_diagnostics", diagnostics)
    case = original_case()
    resolution = dict(
        precision_passed=True,
        selected=dict(normalized_score=-2.0, replicate_mcse_normalized=0.0001),
    )
    # Restore the prospective aggregate criterion in the reduced stream fixture.
    tiny_bundle[2]["aggregate_mcse_max"] = 0.002
    aggregates = r.combined_aggregates(case, resolution)
    assert aggregates["available"] and not aggregates["supplement_available"]
    assert aggregates["primary"]["status"] == r.SUCCESS
    assert aggregates["without_crossing_event"]["status"] == r.UNRESOLVED
    assert aggregates["without_crossing_event"]["equal_event_score"] is None
    result = r._result(admission, resolution, aggregates)
    assert result["status"] == r.SUCCESS and result["aggregates"]["primary"] is not None


def test_primary_failure_cannot_be_rescued_by_good_supplement(tiny_bundle, monkeypatch):
    calls = 0

    def diagnostics(value):
        nonlocal calls
        calls += 1
        return ((0.1 if calls == 1 else 0.0001), dict(passed=True), [])

    monkeypatch.setattr(r, "_diagnostics", diagnostics)
    tiny_bundle[2]["aggregate_mcse_max"] = 0.002
    value = r.combined_aggregates(
        original_case(),
        dict(
            precision_passed=True,
            selected=dict(normalized_score=-2.0, replicate_mcse_normalized=0.0001),
        ),
    )
    assert not value["available"] and value["primary"] is None


def test_independently_reviewed_unresolved_complete_stream_is_not_promoted(tiny_bundle):
    root, admission, cfg = tiny_bundle
    cfg["weight_concentration_min"] = 1e99
    r.run_resolution(root, root / r.CASE_OUTPUT)
    candidate = r.candidate_artifacts(root, admission["files"])
    replay = r.replay_resolution(root)
    write_test_anchors(root, admission, candidate, replay)
    proof = r.case_artifacts(root, admission["files"])
    assert proof["semantics_verified"] and proof["status"] == r.UNRESOLVED
