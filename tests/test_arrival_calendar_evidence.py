"""Calendar hypotheses must remain separate from documentary timestamps."""

from datetime import datetime

from analysis.arrival.calendar_evidence import documentary_clock, first_future_clock


def test_documentary_clock_requires_year_and_timezone() -> None:
    assert documentary_clock("September 29, 2009 21:02 UTC arrival time") == (
        "2009-09-29T21:02:00Z"
    )
    assert documentary_clock("arrival time 12:05 27 Feb") == "unknown"
    assert documentary_clock("January 1, 2007 01:00 arrival time") == "unknown"


def test_sensitivity_rollover_cannot_recover_long_travel_or_rounding() -> None:
    origin = datetime.fromisoformat("2020-12-31T23:45:30+00:00")
    assert first_future_clock(origin, 0, 15).isoformat() == "2021-01-01T00:15:00+00:00"
    assert first_future_clock(origin, 23, 45).isoformat() == "2021-01-01T23:45:00+00:00"
    # A true arrival2 days later has the same clock; this rule cannot identify it.
    assert first_future_clock(origin, 0, 15).day != 2
