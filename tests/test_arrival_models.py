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


def test_heldout_mutation_cannot_change_training_likelihood() -> None:
    prior = read_prior(Path.cwd(), "T-OBS", "base")
    model = build_model(tiny_lane(), prior, indices=np.array([1]))
    changed = build_model(tiny_lane("90000"), prior, indices=np.array([1]))
    assert model.coords["event"] == ("e2",)
    assert model.coords["record"] == ("r1",)
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
