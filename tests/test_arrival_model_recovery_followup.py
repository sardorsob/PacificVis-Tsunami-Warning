"""Independent follow-up identities and explicit pooled descriptive estimates."""

import pytest

from analysis.arrival.model_recovery_followup import compare_cohorts


def test_independent_cohorts_are_retained_and_pooled_without_replacement() -> None:
    row = {
        "case_id": "001",
        "parameter": "sigma",
        "scenario": "combined",
        "seed": 1,
        "mean": 0.6,
        "truth": 0.6,
        "q05": 0.5,
        "q95": 0.7,
        "covered90": True,
        "zero_variance_boundary": False,
    }
    table = compare_cohorts([row], [{**row, "seed": 101, "covered90": False}], {"sigma": 1.0})
    assert [r["datasets"] for r in table] == [1, 1, 2]
    assert table[-1]["coverage90"] == 0.5
    with pytest.raises(ValueError, match="reuses"):
        compare_cohorts([row], [row], {"sigma": 1.0})
    with pytest.raises(ValueError, match="truth"):
        compare_cohorts([row], [{**row, "seed": 101, "truth": 0.7}], {"sigma": 1.0})
