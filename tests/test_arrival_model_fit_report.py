"""Conditional predictive criticism uses matched observations and never silently ranks models."""

import numpy as np
import pytest

from analysis.arrival.model_fit_report import event_effect_summary, matched_predictive_checks


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


def test_signed_minute_effects_are_never_exponentiated_as_duration_ratios() -> None:
    signed = event_effect_summary(np.array([-1000.0, 0.0, 1000.0]), "T-CAL")
    assert signed["units"] == "minutes" and signed["minute_effect_q50"] == 0
    assert signed["minute_effect_q95"] == pytest.approx(900)
    assert not any("factor" in key or "log_effect" in key for key in signed)
    duration = event_effect_summary(np.array([-1.0, 0.0, 1.0]), "T-OBS")
    assert duration["median_duration_factor_q50"] == 1
    assert duration["median_duration_factor_q95"] == pytest.approx(np.exp(0.9))
