"""Rank lines retain integer ordering and a discrete finite reference."""

# pyright: basic
import numpy as np
import pytest

from analysis.arrival.evidence import write_json
from scripts.render_arrival_curvature_calibration import QUANTITIES, rank_lines, render


def test_numeric_rank_lines_are_order_invariant_and_use_discrete_reference():
    rows = [
        {"case_id": f"sbc-{j:03d}", "parameter": name, "rank": str(j)}
        for name in QUANTITIES
        for j in range(100)
    ]
    grid, lines = rank_lines(rows[::-1])
    np.testing.assert_array_equal(grid, np.arange(101))
    np.testing.assert_allclose(
        lines[0]["difference"], np.r_[np.arange(1, 101) / 100, 1] - (grid + 1) / 101
    )
    assert lines[0]["difference"][-1] == 0
    assert lines[0]["halfwidth"] == pytest.approx(np.sqrt(np.log(840) / 200))
    assert [r["parameter"] for r in lines] == sorted(r["parameter"] for r in lines)
    with pytest.raises(ValueError, match="100 independent"):
        rank_lines(rows[:-1])


def test_plot_rejects_disjoint_dataset_identities_and_unplanned_quantities():
    rows = [
        {"case_id": f"sbc-{j:03d}", "parameter": name, "rank": j}
        for name in QUANTITIES
        for j in range(100)
    ]
    rows[0]["case_id"] = "different-cohort"
    with pytest.raises(ValueError, match="100 independent"):
        rank_lines(rows)
    rows[0]["case_id"] = "sbc-000"
    for row in rows:
        if row["parameter"] == "alpha":
            row["parameter"] = "unplanned"
    with pytest.raises(ValueError, match="exact twelve scalar"):
        rank_lines(rows)


def test_plot_rejects_omitted_science_checksums_before_parsing_csv(tmp_path):
    source = tmp_path / "report"
    write_json(source / "output-checksums.json", {})
    with pytest.raises(ValueError, match="report-science checksum"):
        render(tmp_path, source, tmp_path / "plot")
    write_json(source / "output-checksums.json", {"../estimates-by-dataset.csv": "0" * 64})
    with pytest.raises(ValueError, match="contained"):
        render(tmp_path, source, tmp_path / "plot")
