"""Real, synthetic-only proof of the pinned Bayesian APIs and serialization."""

# pyright: basic
from importlib.metadata import version
from pathlib import Path


def test_exact_bayesian_stack() -> None:
    for package, expected in {
        "pymc": "6.4.0",
        "arviz": "1.3.0",
        "nutpie": "0.16.11",
        "preliz": "0.28.0",
    }.items():
        assert version(package) == expected


def test_synthetic_nutpie_datatree_roundtrip(tmp_path: Path) -> None:
    from analysis.arrival.model_stack import smoke_stack

    evidence = smoke_stack(tmp_path / "synthetic.nc")
    assert evidence["backend"] == "nutpie"
    assert evidence["finite_log_likelihood"] and evidence["save_reload_equal"]
    assert evidence["divergences"] == 0
