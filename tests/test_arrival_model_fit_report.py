"""Conditional predictive criticism uses matched observations and never silently ranks models."""

import pytest

from analysis.arrival.model_fit_report import matched_predictive_checks


def row(observed: float) -> dict[str, str]:
    return {
        "stratum": "under-500km",
        "scale": "modeled-response",
        "quantile": "0.5",
        "records": "10",
        "observed": str(observed),
        "replicated_q05": "0.0",
        "replicated_q50": "0.5",
        "replicated_q95": "1.0",
    }


def test_predictive_bands_are_checks_not_parameter_intervals() -> None:
    rows = matched_predictive_checks({"pooled": [row(1.1)], "distance": [row(1.1)]})
    assert len(rows) == 2 and all(r["observed_outside_replicated_central90"] for r in rows)
    with pytest.raises(ValueError, match="observation"):
        matched_predictive_checks({"pooled": [row(1.1)], "distance": [row(1.2)]})
