"""The repeated-edge disposition must be traceable to native source identities."""

from pathlib import Path

from analysis.arrival.model_evidence import audit_repeated_edges


def test_native_ids_and_values_are_retained_without_independence_claim() -> None:
    root = Path(__file__).resolve().parents[1]
    receipt = audit_repeated_edges(root)
    rows = receipt["records"]
    assert {row["native_source_id"] for row in rows} == {
        "11043",
        "11064",
        "25577",
        "25607",
        "19050",
        "37909",
    }
    assert len({(row["event_id"], row["site_id"]) for row in rows}) == 3
    assert all(row["ancestry"] == "unknown" and not row["included_primary"] for row in rows)
