"""Fast graph, prior and train-only likelihood checks; no posterior accuracy claim."""

# pyright: basic
from pathlib import Path

import numpy as np
import pytest

from analysis.arrival.model_data import lane_arrays
from analysis.arrival.models import build_model, read_prior


def tiny_lane(outside_value: str = "100"):
    rows = [
        {
            "record_id": f"r{i}",
            "event_id": event,
            "physical_site_id": "s1",
            "distance_km": str(d),
            "target_minutes": "20" if event == "e2" else outside_value,
            "target": "T-OBS",
        }
        for i, (event, d) in enumerate([("e1", 100), ("e2", 200), ("e3", 500)])
    ]
    return lane_arrays("T-OBS", rows, {"e1": "q1", "e2": "q2", "e3": "q1"}, {"e1", "e2", "e3"})


@pytest.mark.parametrize("parameterization", ["noncentered", "centered", "marginal"])
def test_heldout_mutation_cannot_change_training_likelihood(parameterization: str) -> None:
    prior = read_prior(Path.cwd(), "T-OBS", "base")
    model = build_model(
        tiny_lane(), prior, indices=np.array([1]), parameterization=parameterization
    )
    changed = build_model(
        tiny_lane("90000"), prior, indices=np.array([1]), parameterization=parameterization
    )
    assert model.coords["event"] == ("e2",)
    assert model.coords["record"] == ("r1",)
    if parameterization != "marginal":
        np.testing.assert_array_equal(
            model.rvs_to_values[model["response"]].eval(), tiny_lane().response[[1]]
        )
    assert model.compile_logp()(model.initial_point()) == changed.compile_logp()(
        changed.initial_point()
    )


@pytest.mark.parametrize(
    "kind,has_beta,has_event",
    [
        ("pooled", False, False),
        ("distance", True, False),
        ("event", True, True),
    ],
)
def test_baselines_have_only_their_declared_terms(
    kind: str, has_beta: bool, has_event: bool
) -> None:
    model = build_model(tiny_lane(), read_prior(Path.cwd(), "T-OBS", "base"), kind=kind)
    assert ("beta" in model.named_vars) == has_beta
    assert ("tau_event" in model.named_vars) == has_event
    assert ("z_event" in model.named_vars) == has_event
    assert np.isfinite(model.compile_logp()(model.initial_point()))


def test_invalid_training_subset_rejected() -> None:
    prior = read_prior(Path.cwd(), "T-OBS", "base")
    for indices in [np.array([], dtype=int), np.array([-1]), np.array([3]), np.array([1, 1])]:
        with pytest.raises(ValueError):
            build_model(tiny_lane(), prior, indices=indices)


def test_prior_units_and_alternatives() -> None:
    duration = read_prior(Path.cwd(), "NCEI-native-duration", "base")
    calibration = read_prior(Path.cwd(), "T-CAL", "base")
    wider = read_prior(Path.cwd(), "T-OBS", "wider")
    assert duration["alpha_sd"] == 0.5 and duration["sigma_sd"] == 0.4
    assert calibration["alpha_sd"] == 30
    assert wider["alpha_sd"] > duration["alpha_sd"]


def test_new_event_predictions_match_native_unit_oracle() -> None:
    from analysis.arrival.model_data import VREF_KM_MIN
    from analysis.arrival.model_priors import new_event_predictions

    hyper = {key: np.zeros(10) for key in ["alpha", "beta", "tau_event", "sigma"]}
    distance = np.array([100, 1000, 10000])
    result = new_event_predictions(hyper, distance, "T-OBS", 11)
    np.testing.assert_allclose(result, np.broadcast_to(distance / VREF_KM_MIN, (10, 3)))
    np.testing.assert_array_equal(
        new_event_predictions(hyper, distance, "T-CAL", 11), np.zeros((10, 3))
    )


def test_measurement_and_selection_prior_metadata_cannot_silently_change(tmp_path: Path) -> None:
    path = tmp_path / "config/arrival-model-priors-v1.toml"
    path.parent.mkdir()
    text = Path("config/arrival-model-priors-v1.toml").read_text()
    path.write_text(text.replace("metadata_only_not_accuracy", "plus_minus_one_minute"))
    with pytest.raises(ValueError, match="metadata"):
        read_prior(tmp_path, "T-OBS", "base")


def test_centered_and_noncentered_event_priors_are_equivalent_with_jacobian() -> None:
    prior = read_prior(Path.cwd(), "T-OBS", "base")
    noncentered = build_model(tiny_lane(), prior)
    centered = build_model(tiny_lane(), prior, parameterization="centered")
    z = np.array([-0.5, 0.2, 1.0])
    common = {
        "alpha": 0.1,
        "beta": -0.02,
        "sigma_log__": np.log(0.4),
        "tau_event_log__": np.log(0.3),
    }
    lp_nc = noncentered.compile_logp()({**common, "z_event": z})
    lp_c = centered.compile_logp()({**common, "event_effect": 0.3 * z})
    np.testing.assert_allclose(lp_c, lp_nc - 3 * np.log(0.3), atol=1e-10)


def test_marginal_event_likelihood_and_gradient_match_independent_oracle() -> None:
    from analysis.arrival.model_evaluation import gaussian_event_logpdf

    data = tiny_lane()
    extra = {
        **data.rows[0],
        "record_id": "r4",
        "physical_site_id": "s2",
        "target_minutes": "22",
        "distance_km": "150",
    }
    data = lane_arrays(
        "T-OBS", [*data.rows, extra], {"e1": "q1", "e2": "q2", "e3": "q1"}, {"e1", "e2", "e3"}
    )
    model = build_model(data, read_prior(Path.cwd(), "T-OBS", "base"), parameterization="marginal")
    point = {
        "alpha": 0.1,
        "beta": -0.02,
        "sigma_log__": np.log(0.4),
        "tau_event_log__": np.log(0.3),
    }
    potential = model.compile_logp(vars=[model["event_marginal_likelihood"]])
    expected = 0.0
    for event in sorted(set(data.event_ids)):
        idx = [i for i, e in enumerate(data.event_ids) if e == event]
        expected += gaussian_event_logpdf(data.response[idx], 0.1 - 0.02 * data.x[idx], 0.4, 0.3)
    np.testing.assert_allclose(potential(point), expected, atol=1e-10)
    evaluate = model.compile_logp()
    derivative = model.compile_dlogp()(point)
    expected_gradient = []
    for variable in model.value_vars:
        plus, minus = dict(point), dict(point)
        plus[variable.name] += 1e-5
        minus[variable.name] -= 1e-5
        expected_gradient.append((evaluate(plus) - evaluate(minus)) / (2e-5))
    np.testing.assert_allclose(derivative, expected_gradient, atol=1e-6, rtol=1e-5)
