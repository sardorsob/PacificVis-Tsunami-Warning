"""A numerical adapter must prove that the original precision repair is exhausted."""

# pyright: basic
import json

import pytest

from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_exhausted_cubature import verify_exhausted


def fixture(root):
    attempts = []
    for number in [1, 2]:
        p = root / "output/jobs" / f"case-attempt-{number}"
        write_json(
            p / "result.json",
            {
                "job": {"draws": 2000 * number, "tune": 1000 * number, "seed": 42},
                "status": "precision_failure",
                "prediction_precision_passed": True,
                "repairable": True,
            },
        )
        attempts.append(
            {
                "output": str(p),
                "outcome": "diagnostic_or_precision_failure",
                "files": {str(p / "result.json"): sha256(p / "result.json")},
            }
        )
    state = root / "state.json"
    write_json(
        state,
        {
            "status": "needs_review",
            "current": None,
            "attempts": attempts,
            "next_case": 27,
            "sampler_call_slots_used": 96,
        },
    )
    return p, state


def test_valid_exhausted_repair_preserves_both_originals_and_live_state(tmp_path):
    source, state = fixture(tmp_path)
    before = state.read_bytes(), (source / "result.json").read_bytes()
    proof = verify_exhausted(tmp_path, source, state)
    assert proof["next_case"] == 27 and proof["sampler_call_slots_used"] == 96
    assert before == (state.read_bytes(), (source / "result.json").read_bytes())
    assert json.loads((source / "result.json").read_text())["repairable"] is True


@pytest.mark.parametrize("change", ["seed", "draws", "prediction", "hash", "active", "not_stopped"])
def test_unexhausted_unsafe_or_changed_evidence_is_not_waived(tmp_path, change):
    source, state = fixture(tmp_path)
    data = json.loads(state.read_text())
    if change in {"active", "not_stopped"}:
        data["current" if change == "active" else "status"] = "running"
    else:
        p = source / "result.json"
        result = json.loads(p.read_text())
        if change in {"seed", "draws"}:
            result["job"][change] += 1
        elif change == "prediction":
            result["prediction_precision_passed"] = False
        else:
            result["repairable"] = False
        write_json(p, result)
        if change != "hash":
            data["attempts"][-1]["files"][str(p)] = sha256(p)
    write_json(state, data)
    with pytest.raises(ValueError):
        verify_exhausted(tmp_path, source, state)
