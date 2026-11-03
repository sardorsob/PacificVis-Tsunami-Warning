# pyright: reportUnknownMemberType=false
"""Static accessible preliminary EDA figures, always accompanied by their CSV."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def draw(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    kind: str,
    x: str,
    y: str,
    title: str,
    xlabel: str,
    ylabel: str,
    split: str,
) -> None:
    """One-panel diagnostic with explicit units, split, n and provenance."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "svg.hashsalt": "paper-eda-v1",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    xx = np.array([float(r[x]) for r in rows])
    yy = np.array([float(r[y]) for r in rows])
    valid = np.isfinite(xx) & np.isfinite(yy)
    xx, yy = xx[valid], yy[valid]
    if kind in {"scatter", "physics"}:
        ax.scatter(xx, yy, s=13, color="#176B91", alpha=1.0, edgecolor="none")
    elif kind == "line":
        ax.plot(xx, yy, "o-", color="#176B91", markersize=4)
    elif kind == "bar":
        width = (
            float(rows[0]["bin_right"] - rows[0]["bin_left"]) * 0.9
            if rows and "bin_left" in rows[0]
            else 0.8
        )
        ax.bar(xx, yy, color="#176B91", width=width)
        ax.set_ylim(bottom=0)
    if kind == "physics" and len(xx):
        from analysis.arrival.eda import VREF

        d = np.geomspace(max(0.1, float(min(xx))), float(max(xx)), 100)
        ax.plot(d, d / VREF / 60, color="#333333", label="Fixed 4,000 m reference")
        ax.fill_between(
            d,
            d / VREF / 60 / np.sqrt(1.5),
            d / VREF / 60 * np.sqrt(2),
            color="#bbbbbb",
            zorder=0,
            alpha=0.4,
            label="2,000–6,000 m depth band",
        )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.legend(fontsize=9)
    if kind == "line" and rows and "ci_low" in rows[0]:
        ax.vlines(
            xx,
            [float(r["ci_low"]) for r in rows if np.isfinite(float(r[y]))],
            [float(r["ci_high"]) for r in rows if np.isfinite(float(r[y]))],
            color="#176B91",
        )
    if not len(xx):
        ax.text(
            0.5,
            0.5,
            "Insufficient comparable data",
            transform=ax.transAxes,
            ha="center",
            va="center",
        )
    ax.set(xlabel=xlabel, ylabel=ylabel)
    if kind not in {"bar", "physics"}:
        ax.axhline(0, color="#777777", linewidth=0.7)
    ax.grid(axis="y", color="#dddddd", linewidth=0.5)
    fig.suptitle(title, x=0.13, ha="left", fontsize=14)
    if rows and "ci_low" in rows[0]:
        detail = f"{sum(int(r['rows']) for r in rows)} records; {len(xx)} bins"
    elif rows and "bin_left" in rows[0]:
        detail = f"{int(sum(yy))} records in {len(xx)} bins"
    elif kind == "bar":
        detail = f"{int(sum(yy))} records; {len(xx)} groups"
    else:
        detail = f"n={len(xx)} plotted records"
    ax.set_title(f"Preliminary · {split} · {detail}", loc="left", fontsize=10)
    fig.text(
        0.13,
        0.02,
        "Sources: frozen NTWC / NCEI evidence; WGS84 distance diagnostic.\n"
        + (
            "95% event-bootstrap intervals, 500 resamples. CSV supplied."
            if rows and "ci_low" in rows[0]
            else "Families remain separate; no fitted model. CSV supplied with each figure."
        ),
        fontsize=8,
    )
    fig.subplots_adjust(top=0.82, bottom=0.2, left=0.13, right=0.97)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=150)
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
