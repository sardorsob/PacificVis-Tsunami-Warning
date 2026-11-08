"""Reporting cannot reopen saved values behind an empty acceptance claim."""

import json
from pathlib import Path

import pytest

from scripts.summarize_arrival_curvature_pilot import GATE, accepted_inputs


def test_empty_accepted_pilot_proof_is_rejected(tmp_path: Path) -> None:
    gate = tmp_path / GATE
    gate.parent.mkdir(parents=True)
    gate.write_text(
        json.dumps(
            {
                "status": "accepted_complete_five_case_computational_pilot",
                "model": "mean-curvature",
                "independent_checker": True,
                "files": {},
            }
        )
    )
    with pytest.raises(ValueError, match="complete independently accepted"):
        accepted_inputs(tmp_path)
