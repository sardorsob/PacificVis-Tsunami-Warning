"""Scientific invariants for the shared contour export."""

from copy import deepcopy
from typing import Any

import pytest

from scripts.normalize_development_contours import validated_features


def fixture() -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {"OBJECTID": 7, "HOURS": 2},
                "geometry": {"type": "LineString", "coordinates": [[179, 20], [-179, 21]]},
            }
        ],
    }


def test_preserves_antimeridian_and_documented_precision() -> None:
    payload = fixture()
    payload["features"][0]["geometry"]["coordinates"].append([180 + 1e-10, 22])
    before = deepcopy(payload)
    features, counts = validated_features(payload)
    assert features == before["features"]
    assert counts["boundary_precision_vertices"] == 1
    assert counts["antimeridian_segments"] == 2


@pytest.mark.parametrize("failure", ["truncated", "duplicate", "latitude", "negative_hours"])
def test_rejects_invalid_or_incomplete_data(failure: str) -> None:
    payload = fixture()
    if failure == "truncated":
        payload["exceededTransferLimit"] = True
    elif failure == "duplicate":
        payload["features"].append(deepcopy(payload["features"][0]))
    elif failure == "latitude":
        payload["features"][0]["geometry"]["coordinates"][0][1] = 120
    else:
        payload["features"][0]["properties"]["HOURS"] = -1
    with pytest.raises(ValueError):
        validated_features(payload)
