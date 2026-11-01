"""Documentary recovery must not manufacture dates or original products."""

import pytest

from analysis.arrival.documentary_recovery import extract_forecasts, observation_day
from scripts.build_documentary_recovery import Cells


def test_local_forecasts_preserve_issue_rollover_and_version() -> None:
    text = """TSUNAMI MESSAGE NUMBER 3
302 PM PDT TUE SEP 29 2009
SANTA BARBARA-CA 2103 PDT SEP 29  SAN FRANCISCO-CA 2125 PDT SEP 29
TIME - TIME OF MEASUREMENT
APIA WEST SAMOA 1832UTC 0.70M
"""
    rows = extract_forecasts(text, "dev", "src")
    assert len(rows) == 2
    assert rows[0]["arrival_utc"] == "2009-09-30T04:03:00Z"
    assert rows[0]["issue_utc"] == "2009-09-29T22:02:00Z"
    assert rows[0]["message_version"] == "3"
    assert rows[0]["parent_table_replacement_allowed"] == "False"
    assert all(r["kind"] == "estimated_initial_arrival" for r in rows)


def test_different_versions_remain_different_products() -> None:
    a = "TSUNAMI MESSAGE NUMBER 3\n302 PM PDT TUE SEP 29 2009\nLA JOLLA-CA 2107 PDT SEP 29"
    b = "TSUNAMI MESSAGE NUMBER 4\n414 PM PDT TUE SEP 29 2009\nLA JOLLA-CA 2116 PDT SEP 29"
    rows = extract_forecasts(a + "\n" + b, "dev", "src")
    assert len({r["product_id"] for r in rows}) == 2
    assert {r["arrival_utc"] for r in rows} == {
        "2009-09-30T04:07:00Z", "2009-09-30T04:16:00Z"
    }


def test_cross_month_does_not_guess_year_and_invalid_clock_rejects() -> None:
    text = "TSUNAMI MESSAGE NUMBER 1\n1100 PM PST THU DEC 31 2009\nLA JOLLA-CA 0100 PST JAN 1"
    assert extract_forecasts(text, "dev", "src")[0]["arrival_utc"] == "unknown"
    with pytest.raises(ValueError):
        extract_forecasts(text.replace("0100", "2560"), "dev", "src")


def test_ptwc_forecast_points_are_not_observing_deployments() -> None:
    text = """TSUNAMI BULLETIN NUMBER 001
PACIFIC TSUNAMI WARNING CENTER/NOAA/NWS
ISSUED AT 1804Z 29 SEP 2009
AMERICAN SAMOA   PAGO PAGO          14.3S 170.7W    1759Z 29 SEP
                 APIA              13.8S 171.8W    1810Z 29 SEP
"""
    rows = extract_forecasts(text, "dev", "src")
    assert len(rows) == 2
    assert rows[0]["station_label"] == "PAGO PAGO"
    assert rows[0]["available_before_predicted_arrival"] == "False"
    assert rows[0]["deployment_identity"] == "unknown"


def test_observation_calendar_requires_clock_duration_agreement() -> None:
    assert observation_day("2006-11-15", "11:14", "16:55", "5:41") == (
        "2006-11-15T16:55:00Z"
    )
    assert observation_day("2006-11-15", "11:14", "?", "?") == "unknown"
    with pytest.raises(ValueError, match="disagree"):
        observation_day("2006-11-15", "11:14", "16:55", "4:41")


def test_wrong_event_response_never_recovers_a_historical_forecast() -> None:
    text = """TSUNAMI MESSAGE NUMBER 1
1232 AM AKST TUE JAN 23 2018
TIME - 0931 UTC JAN 23 2018
KODIAK-AK 0145 AKST JAN 23
"""
    assert not extract_forecasts(text, "old", "src", reference_origin="2010-02-27T06:34:14Z")
    rows = extract_forecasts(text, "dev", "src", reference_origin="2018-01-23T09:31:40Z")
    assert rows[0]["native_origin_utc"] == "2018-01-23T09:31:00Z"


def test_malformed_original_table_does_not_duplicate_or_merge_cells() -> None:
    parser = Cells()
    parser.feed("<tr><td>La Push</td><td>0433</td></tr></tr>"
                "<td>Arena Cove</td><td>0436</td></tr>")
    assert parser.rows == [["La Push", "0433"], ["Arena Cove", "0436"]]


def test_successor_forecast_section_excludes_measurement_table() -> None:
    text = """PUBLIC TSUNAMI MESSAGE NUMBER 10
1243 AM PDT THU SEP 17 2015
2254 UTC SEP 16 2015
FORECASTS OF TSUNAMI ACTIVITY
NEWPORT BEACH    0446 PDT SEP 17
OBSERVATIONS OF TSUNAMI ACTIVITY
LOS ANGELES     0430 PDT SEP 17
"""
    rows = extract_forecasts(text, "dev", "src")
    assert len(rows) == 1
    assert rows[0]["kind"] == "forecast_start_of_tsunami"
