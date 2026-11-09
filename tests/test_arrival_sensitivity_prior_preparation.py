"""Synthetic receipt closure/direct ancestral checks; no actual outcomes or sampler."""

# pyright: basic
import json
import tomllib

import numpy as np
import pytest

from analysis.arrival.evidence import read_rows, sha256, write_json
from scripts import prepare_arrival_sensitivity_priors as prep
from tests.test_arrival_model_sensitivity_inputs import fixture as input_fixture


def fixture(root, monkeypatch):
    lanes, _, _, _, _ = input_fixture(root)
    for name in prep.CONSUMED:
        path = root / name
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic current runtime")
    source = root / "reviewed-source"
    source.write_text("closed synthetic comparison source")
    cv = {
        "status": "accepted_all_curvature_sequence_computations",
        "independent_checker": True,
        "confirmation_outcomes_parsed": False,
        "reserved_outcomes": "sealed",
        "files": {"reviewed-source": sha256(source)},
    }
    write_json(root / prep.CV_REVIEW, cv)
    write_json(
        root / prep.COMPARISON_REVIEW,
        {
            "status": "accepted_curvature_sequence_predictive_comparison",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {**cv["files"], prep.CV_REVIEW: sha256(root / prep.CV_REVIEW)},
        },
    )
    contract = tomllib.loads((root / prep.source_io.CONTRACT).read_text())
    events = []
    real_preflight = prep.source_io.verify_sensitivity_inputs

    def preflight(*args):
        events.append("source_preflight")
        return real_preflight(*args)

    monkeypatch.setattr(prep.source_io, "verify_sensitivity_inputs", preflight)
    monkeypatch.setattr(
        prep, "load_lanes", lambda *a: events.append("native_load") or (lanes, contract)
    )
    base = {"alpha_sd": 0.5, "beta_sd": 0.25, "tau_sd": 0.4, "sigma_sd": 0.4}
    monkeypatch.setattr(
        prep,
        "read_prior",
        lambda root, target, variant: {
            key: value * (2 if variant == "wider" else 1) for key, value in base.items()
        },
    )
    monkeypatch.setattr(
        prep,
        "read_curvature_prior",
        lambda root, variant: {
            **{key: value * (2 if variant == "joint_wider" else 1) for key, value in base.items()},
            "gamma_sd": 0.8 if variant == "joint_wider" else 0.5,
        },
    )
    return lanes, events


def test_exact41_configurations_have_unique_order_seeds_and_declared_forms():
    configs = prep.prior_configurations()
    assert (
        len(configs) == len({(c["target"], c["kind"], c["prior_variant"]) for c in configs}) == 41
    )
    assert [(c["target"], c["kind"]) for c in configs[:8]] == list(prep.FORMS)
    assert all(c["prior_variant"] == "base" for c in configs[:8])
    assert [c["seed"] for c in configs] == [2896110800 + 1000 * j for j in range(41)]
    assert all(c["draws"] == 2000 and c["prediction_seed"] == c["seed"] + 1 for c in configs)
    assert configs[-1]["prior_variant"] == "gamma_wider_only"


@pytest.mark.parametrize(
    "change",
    [
        "missing_comparison",
        "pending_comparison",
        "missing_cv_file",
        "pending_cv",
        "source_drift",
        "census_closure",
    ],
)
def test_unaccepted_or_incomplete_sources_block_every_native_loader(tmp_path, monkeypatch, change):
    fixture(tmp_path, monkeypatch)
    path = tmp_path / prep.COMPARISON_REVIEW
    review = json.loads(path.read_text())
    if change == "missing_comparison":
        path.unlink()
    elif change == "pending_comparison":
        review["status"] = "pending"
        write_json(path, review)
    elif change == "missing_cv_file":
        review["files"].pop("reviewed-source")
        write_json(path, review)
    elif change == "pending_cv":
        cv = json.loads((tmp_path / prep.CV_REVIEW).read_text())
        cv["status"] = "pending"
        write_json(tmp_path / prep.CV_REVIEW, cv)
        review["files"][prep.CV_REVIEW] = sha256(tmp_path / prep.CV_REVIEW)
        write_json(path, review)
    elif change == "source_drift":
        (tmp_path / "reviewed-source").write_text("changed")
    else:
        inputs = json.loads((tmp_path / prep.source_io.CENSUS_INPUTS).read_text())
        inputs["files"].pop(next(iter(inputs["files"])))
        write_json(tmp_path / prep.source_io.CENSUS_INPUTS, inputs)
    monkeypatch.setattr(prep, "load_lanes", lambda *a: pytest.fail("native outcomes opened"))
    with pytest.raises(ValueError):
        prep.prepare(tmp_path, tmp_path / "prior-bundle")
    assert not (tmp_path / "prior-bundle").exists()


def test_valid_admission_closes_all_sources_without_parsing_csv_or_raw(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(prep.source_io, "read_rows", lambda *a: pytest.fail("CSV/raw parsed"))
    pins = prep.admit_sources(tmp_path)
    assert set(prep.CONSUMED) <= set(pins)
    assert set(prep.source_io.required_sensitivity_paths()) <= set(pins)
    nested = json.loads((tmp_path / prep.source_io.CENSUS_INPUTS).read_text())["files"]
    assert len(nested) == 50 and all(pins[name] == digest for name, digest in nested.items())


def test_prepare_uses_only_direct_ancestral_draws_and_preserves_55jobs_6reuse(
    tmp_path, monkeypatch
):
    _, events = fixture(tmp_path, monkeypatch)
    import pymc as pm

    monkeypatch.setattr(pm, "sample", lambda *a, **kw: pytest.fail("MCMC called"))
    monkeypatch.setattr(
        pm, "sample_prior_predictive", lambda *a, **kw: pytest.fail("Potentials ignored")
    )
    draw_calls, prediction_calls = [], []
    real_population, real_predictions = (
        prep.population_prior_draws,
        prep.prior_predictive_log_or_native,
    )

    def population(*a, **kw):
        draw_calls.append((a[:2], kw["draws"], kw["seed"]))
        return real_population(*a, **kw)

    def predictions(*a, **kw):
        prediction_calls.append((a[:2], kw["seed"]))
        return real_predictions(*a, **kw)

    monkeypatch.setattr(prep, "population_prior_draws", population)
    monkeypatch.setattr(prep, "prior_predictive_log_or_native", predictions)
    output = tmp_path / "prior-bundle"
    summary = prep.prepare(tmp_path, output)
    assert events.index("source_preflight") < events.index("native_load")
    assert len(draw_calls) == len(prediction_calls) == 41
    assert [call[2] for call in draw_calls] == [c["seed"] for c in prep.prior_configurations()]
    assert all(call[1] == 2000 for call in draw_calls)
    manifest = json.loads((output / "case-manifest.json").read_text())
    assert len(manifest["jobs"]) == len(manifest["cases"]) == 55
    assert len(manifest["reuse_training_posteriors"]) == 6
    assert manifest["prior_fits"] == 33 and manifest["nonprior_fits"] == 22
    assert [c["seed"] for c in manifest["jobs"]] == [2886110800 + 1000 * j for j in range(55)]
    assert not manifest["fit_authorized"] and not manifest["prior_predictions_reviewed"]
    assert summary["status"] == "computed_pending_prior_predictive_review"
    assert summary["sampler_calls"] == 0 and summary["total_ancestral_draws"] == 82000
    inputs = json.loads((output / "inputs.json").read_text())
    assert all(sha256(tmp_path / name) == digest for name, digest in inputs["files"].items())
    checksums = json.loads((output / "output-checksums.json").read_text())
    assert all(sha256(output / name) == digest for name, digest in checksums.items())
    rows = read_rows(output / "new-event-prior-quantiles.csv")
    assert any(
        row["target"] == "T-CAL" and row["space"] == "native-minutes" and float(row["q05"]) < 0
        for row in rows
    )
    for row in rows:
        if (
            row["space"] == "native-minutes"
            and row["target"] != "T-CAL"
            and row["native_representable"] == "True"
        ):
            assert float(row["q50"]) == pytest.approx(np.exp(float(row["log_q50"])))
    json.dumps(summary, allow_nan=False)
    with pytest.raises(ValueError, match="new nonsymlink"):
        prep.prepare(tmp_path, output)


def test_overflow_is_reported_in_log_space_without_finite_draw_filtering(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    real_population = prep.population_prior_draws

    def extreme_population(*a, **kw):
        result = real_population(*a, **kw)
        result["alpha"][:] = 1000.0
        return result

    monkeypatch.setattr(prep, "population_prior_draws", extreme_population)
    output = tmp_path / "extreme-priors"
    summary = prep.prepare(tmp_path, output)
    assert any(c["unrepresentable_native_values"] > 0 for c in summary["checks"])
    rows = read_rows(output / "new-event-prior-quantiles.csv")
    positive = [
        row for row in rows if row["target"] == "T-OBS" and row["space"] == "native-minutes"
    ]
    assert all(row["q50"] == "" and row["native_representable"] == "False" for row in positive)
    assert all(float(row["log_q50"]) > 900 for row in positive)
    json.dumps(summary, allow_nan=False)


def test_source_change_during_output_preserves_failure_and_never_authorizes_fit(
    tmp_path, monkeypatch
):
    fixture(tmp_path, monkeypatch)
    real_write = prep.write_table

    def drift(path, rows):
        real_write(path, rows)
        (tmp_path / "reviewed-source").write_text("changed while writing derived output")

    monkeypatch.setattr(prep, "write_table", drift)
    output = tmp_path / "prior-bundle"
    with pytest.raises(ValueError, match="identity changed"):
        prep.prepare(tmp_path, output)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "prior_preparation_failure" and not summary["fit_authorized"]


def test_symlink_output_is_rejected_before_admission(tmp_path, monkeypatch):
    output = tmp_path / "linked"
    output.symlink_to(tmp_path / "uncreated")
    monkeypatch.setattr(prep, "admit_sources", lambda *a: pytest.fail("admission ran"))
    with pytest.raises(ValueError, match="nonsymlink"):
        prep.prepare(tmp_path, output)


def test_parent_traversal_cannot_write_outside_project_before_admission(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    output = root / ".." / "escaped"
    monkeypatch.setattr(prep, "admit_sources", lambda *a: pytest.fail("admission ran"))
    with pytest.raises(ValueError, match="project-local"):
        prep.prepare(root, output)
    assert not (tmp_path / "escaped").exists()
