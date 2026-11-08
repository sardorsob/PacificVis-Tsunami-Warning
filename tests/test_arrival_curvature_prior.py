"""Declared prior alternatives differ only in their named parameters."""

from pathlib import Path

import pytest

from analysis.arrival.model_curvature_prior import CONFIG, read_curvature_prior


def test_curvature_variants_do_not_silently_widen_other_parameters() -> None:
    root = Path(__file__).resolve().parents[1]
    base = read_curvature_prior(root, "base")
    gamma = read_curvature_prior(root, "gamma_wider_only")
    joint = read_curvature_prior(root, "joint_wider")
    assert base["gamma_sd"] == 0.5 and gamma["gamma_sd"] == joint["gamma_sd"] == 0.8
    assert {k: v for k, v in base.items() if k != "gamma_sd"} == {
        k: v for k, v in gamma.items() if k != "gamma_sd"
    }
    assert joint["tau_sd"] == joint["sigma_sd"] == 0.6
    assert base["tau_sd"] == base["sigma_sd"] == 0.4
    with pytest.raises(ValueError):
        read_curvature_prior(root, "unlisted")


def test_curvature_prior_refuses_changed_inherited_prior_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for name in [CONFIG, "config/arrival-model-priors-v1.toml"]:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((root / name).read_bytes())
    read_curvature_prior(tmp_path, "base")
    with (tmp_path / "config/arrival-model-priors-v1.toml").open("a") as stream:
        stream.write("\n# changed\n")
    with pytest.raises(ValueError, match="changed"):
        read_curvature_prior(tmp_path, "base")


def test_prior_hash_check_cannot_be_redirected_to_another_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    destination = tmp_path / CONFIG
    destination.parent.mkdir(parents=True)
    destination.write_text(
        (root / CONFIG)
        .read_text()
        .replace(
            'base_priors = "config/arrival-model-priors-v1.toml"',
            'base_priors = "other-prior.toml"',
        )
    )
    with pytest.raises(ValueError, match="changed"):
        read_curvature_prior(tmp_path, "base")
