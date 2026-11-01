"""Structural quality does not validate physical onset or manufacture passed QC."""

from analysis.arrival.waveform_quality import audit_rows, strip_rows


def test_cadence_gaps_units_and_missing_qc_preserved() -> None:
    rows = [
        dict(
            timestamp_utc=f"2000-01-01T00:{m}:00Z",
            timestamp_state="reported_utc",
            numeric_value=str(v),
            value_state="finite_numeric",
            units=u,
            qc_state="not_provided",
        )
        for m, v, u in [("00", 1, "m"), ("01", 2, "m"), ("10", 3, "cm"), ("10", 4, "cm")]
    ]
    result = audit_rows(rows, 60)
    assert result["conflicting_duplicate_timestamps"] == "1"
    assert result["gaps_over_1_5_declared_cadence"] == "1"
    assert result["units_json"] == '["cm", "m"]'
    assert result["qc_passed"] == "unknown"
    assert result["physical_onset_validated"] == "False"


def test_packet_cannot_depend_on_report_or_eta_fields() -> None:
    row = {"timestamp_utc": "2000-01-01T00:00:00Z", "raw_value": "1", "units": "m"}
    assert strip_rows([row]) == strip_rows(
        [{**row, "report_id": "secret", "eta": "later", "observed_utc": "arrival"}]
    )
