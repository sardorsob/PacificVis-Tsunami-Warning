"""CSV lexical ordering must not determine the geometry of a scientific line."""

# pyright: basic
from pathlib import Path

import matplotlib.figure
import numpy as np
import pytest

from scripts.render_arrival_curvature_prior import VARIANTS, ordered_figures


def rows():
    return [
        {
            "variant": variant,
            "quantity": quantity,
            "distance_km": str(d),
            "q05_minutes": str(d / 50),
            "q50_minutes": str(d / 10),
            "q95_minutes": str(d / 2),
        }
        for variant in VARIANTS
        for quantity in ["new_event", "conditional_median"]
        for d in [100, 1000, 20, 500]
    ]


def test_actual_matplotlib_lines_use_numeric_distance_order(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        matplotlib.figure.Figure, "savefig", lambda self, *a, **k: captured.append(self)
    )
    ordered_figures(rows(), tmp_path)
    assert captured
    for ax in captured[0].axes:
        for line in ax.lines:
            np.testing.assert_array_equal(line.get_xdata(), [20, 100, 500, 1000])


def test_mismatching_prior_grids_cannot_be_drawn(tmp_path: Path):
    with pytest.raises(ValueError, match="matching unique"):
        ordered_figures(rows()[:-1], tmp_path)
