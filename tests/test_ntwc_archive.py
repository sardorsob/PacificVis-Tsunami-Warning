"""Raw archival cells must survive parsing without becoming derived arrivals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.ntwc_archive import (
    ArchiveError,
    arrival_value_flags,
    inventory,
    link_identity,
    link_status,
    parse_archive,
)
from scripts.inventory_ntwc_pilot import main

ARCHIVE_URL = "https://www.tsunami.gov/previous.events/?p=fixture"
HEADERS = [
    "Tide gage/<br>Measurement Location",
    "Estimated Arrival Time<br>[UTC (J.Day)]",
    "Observed Arrival time<br>[UTC (J.Day)]",
    "Peak amplitude<br>(above sea level in cm)",
    "Time of Peak Amplitude Measurement<br>[UTC (J.Day)]",
    "Model Forecast Amplitude<br>(above sea level in cm)",
    "Initial motion", "Sample Interval<br>(min)",
    "Data File<br>(Julian Day Starts<br>at 0000 UTC)",
]


def page(body: str, *, headers: list[str] | None = None) -> str:
    cells = "".join(f"<th><b>{item}</b></th>" for item in (headers or HEADERS))
    return f"<!doctype html><html><table><tr>{cells}</tr>{body}</table></html>"


def source_row(values: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{item}</td>" for item in values) + "</tr>"


def example_row() -> str:
    return source_row([
        '<a href="plot.png">Hilo &amp; Island</a>', "1344 (70)", "?", "128",
        "1428 (70)", "&nbsp;", "up", "15 sec",
        '<a href="/previous.events/fixture/hilo.070">070</a>, '
        '<a href="https://outside.example/data">071</a>',
    ])


def test_preserves_nested_markup_entities_raw_links_missing_tokens_and_order() -> None:
    raw = example_row()
    result = parse_archive(page(raw), ARCHIVE_URL)
    assert result["status"] == "inventoried"
    table = result["arrival_tables"][0]
    assert table["header_family"] == "estimated_observed_utc_jday"
    assert table["accepted_source_rows"] == 1
    record = result["rows"][0]
    assert record["raw_html"] == raw
    assert record["fields"]["location"] == "Hilo & Island"
    assert record["fields"]["observed_arrival"] == "?"
    assert record["fields"]["sample_interval"] == "15 sec"
    assert record["cell_states"][2] == "source_missing_token"
    assert record["cell_states"][5] == "blank"
    assert record["cells"][5]["raw_html"] == "<td>&nbsp;</td>"
    assert [link["status"] for link in result["links"]] == [
        "safe_archive_link", "rejected_unsafe_url"]
    assert result["links"][0]["href"] == "/previous.events/fixture/hilo.070"
    assert table["header_cells"][1]["text"] == "Estimated Arrival Time\n[UTC (J.Day)]"


def test_computed_gmt_family_and_old_eight_column_header() -> None:
    headers = [item.replace("Estimated", "Computed").replace("UTC", "GMT")
               for index, item in enumerate(HEADERS) if index != 5]
    result = parse_archive(page(source_row(["Adak", "1 (2)", "?", "4", "5 (6)",
                                           "down", "1", ""]), headers=headers), ARCHIVE_URL)
    assert result["arrival_tables"][0]["header_family"] == "computed_observed_gmt_jday"
    assert result["rows"][0]["status"] == "accepted_source_row"


def test_maule_legacy_initial_arrival_header_preserves_different_column_order() -> None:
    headers = ["Tide gage", "Peak amplitude (above sea level in cm)",
               "Observed Initial Arrival time (UTC)", "Computed Initial Arrival time (UTC)",
               "Initial motion", "Sample Interval (min)",
               "Data File (Julian Day Starts at&nbsp; 0000 UTC)"]
    result = parse_archive(page(source_row(["Adak", "4", "?", "1 (2)", "up", "1", ""]),
                                headers=headers), ARCHIVE_URL)
    assert result["arrival_tables"][0]["header_family"] == "computed_observed_utc"
    assert result["rows"][0]["fields"]["observed_arrival"] == "?"
    assert result["rows"][0]["fields"]["estimated_arrival"] == "1 (2)"


def test_legacy_eta_family_does_not_relabel_peak_to_trough_as_amplitude() -> None:
    headers = ["Tide gage site", "Wave height (cm p-t)", "Arrival time (UTC)",
               "ETA (UTC)", "Initial motion", "Sample Interval (min)", "Data File"]
    result = parse_archive(page(source_row(["Adak", "4", "?", "1 (2)", "up", "1", ""]),
                                headers=headers), ARCHIVE_URL)
    assert result["arrival_tables"][0]["header_family"] == "arrival_eta_utc"
    fields = result["rows"][0]["fields"]
    assert fields["wave_height_peak_to_trough"] == "4"
    assert fields["arrival_as_labeled"] == "?"
    assert "peak_amplitude" not in fields and "observed_arrival" not in fields


def test_rowspan_continuation_is_not_silently_aligned() -> None:
    spanning = example_row().replace("<td>", '<td rowspan="2">', 1)
    result = parse_archive(page(spanning + example_row() + example_row()), ARCHIVE_URL)
    assert [row["status"] for row in result["rows"]] == [
        "rejected_spanning_row", "rejected_spanning_row", "accepted_source_row"]


def test_unclosed_table_is_rejected_with_all_source_cells_retained() -> None:
    result = parse_archive(page(example_row()).replace("</table>", ""), ARCHIVE_URL)
    assert result["arrival_tables"][0]["status"] == "rejected_unknown_header"
    assert result["arrival_tables"][0]["parser_issues"] == ["unclosed_table"]
    assert result["rows"][0]["cells"][0]["text"] == "Hilo & Island"


def test_all_rows_accounted_for_empty_missing_spans_and_short_rows() -> None:
    spanning = source_row(["Hilo"] * 9).replace("<td>", '<td rowspan="2">', 1)
    body = example_row() + source_row([""] * 9) + source_row(["Short", "?"]) + spanning
    result = parse_archive(page(body), ARCHIVE_URL)
    table = result["arrival_tables"][0]
    assert table["source_rows"] == 5
    assert table["rows_after_header"] == 4
    assert table["accepted_source_rows"] + table["blank_rows"] + table["rejected_rows"] == 4
    assert [row["status"] for row in result["rows"]] == [
        "accepted_source_row", "blank_row", "rejected_cell_count", "rejected_spanning_row"]
    assert result["rows"][2]["cells"][1]["text"] == "?"
    assert result["rows"][3]["cells"][0]["attributes"] == [("rowspan", "2")]


@pytest.mark.parametrize("replacement", ["Mystery field", "Observed Arrival time [PST (J.Day)]"])
def test_unknown_shape_is_rejected_without_mapping_values(replacement: str) -> None:
    headers = HEADERS.copy()
    headers[7 if replacement == "Mystery field" else 2] = replacement
    result = parse_archive(page(example_row(), headers=headers), ARCHIVE_URL)
    assert result["arrival_tables"][0]["header_family"] == "unknown"
    assert result["rows"][0]["status"] == "rejected_unknown_header"
    assert result["rows"][0]["fields"] == {}
    assert result["links"] == []


def test_error_page_does_not_look_like_success() -> None:
    result = parse_archive("<html>Service unavailable</html>", ARCHIVE_URL)
    assert result["status"] == "rejected_no_arrival_table"
    assert result["rows"] == []


@pytest.mark.parametrize("href", [
    "http://www.tsunami.gov/previous.events/a", "//evil.example/previous.events/a",
    "https://www.tsunami.gov.evil.example/previous.events/a", "javascript:alert(1)",
    "/previous.events/%2e%2e/secret", "/previous.events/%252e%252e/secret",
    "/previous.events/a\\..\\b", "/previous.events/%00file", "",
    "https://name:pass@www.tsunami.gov/previous.events/a", "/other/file",
    "https://www.tsunami.gov:443/previous.events/a", "/previous.events/a#anchor",
])
def test_unsafe_links_remain_rejected(href: str) -> None:
    assert link_status(href, ARCHIVE_URL)[0] == "rejected_unsafe_url"


def test_sealed_page_emits_no_arrival_cells_headers_or_links() -> None:
    result = parse_archive(page(example_row()), ARCHIVE_URL, sealed=True)
    serialized = json.dumps(result)
    assert result["rows"] == [] and result["links"] == []
    assert result["arrival_tables"][0]["accepted_source_rows"] == 1
    assert result["arrival_tables"][0]["header_family"] == "estimated_observed_utc_jday"
    assert result["arrival_tables"][0]["rows_with_estimate_value"] == 1
    assert result["arrival_tables"][0]["rows_with_observed_value"] == 0
    assert result["arrival_tables"][0]["rows_with_both_values"] == 0
    for secret in ("1344", "Hilo", "hilo.070", "header_cells", "<td>"):
        assert secret not in serialized


@pytest.mark.parametrize("missing", [
    "none", "NONE", "(?)", "???", "? (037)", "??? 5/3", "?\xa0\r\n5/4", "(?) (JD 070)",
])
def test_presence_recognizes_source_missing_tokens_without_changing_raw_text(missing: str) -> None:
    row = source_row(["Site", "1344 (70)", missing, "1", "1", "1", "up", "1", ""])
    result = parse_archive(page(row), ARCHIVE_URL)
    assert result["rows"][0]["fields"]["observed_arrival"] == missing
    assert result["rows"][0]["cell_states"][2] == "source_missing_token"
    assert result["arrival_tables"][0]["rows_with_both_values"] == 0


@pytest.mark.parametrize("present", ["~1245 (037)", "1012 ? (037)", "0", "approx 0335 06/15"])
def test_qualified_source_values_are_present_but_not_parsed(present: str) -> None:
    flags = arrival_value_flags({"estimated_arrival": "0100", "observed_arrival": present})
    assert flags["both_values"]


def test_legacy_presence_does_not_assert_explicit_observed_semantics() -> None:
    flags = arrival_value_flags({"eta_as_labeled": "0100", "arrival_as_labeled": "0200"})
    assert flags["estimate_and_arrival_as_labeled_values"]
    assert not flags["both_values"] and not flags["observed_value"]


@pytest.mark.parametrize("name,code,sensor,day,year", [
    ("hilo_A_2011.070", "hilo", "A", "070", "2011"),
    ("hiloA2006.319", "hilo", "A", "319", "2006"),
    ("sitk174-01.dat", "sitk", "unknown", "174", "01"),
    ("cres-06-15-2005.dat", "cres", "unknown", "unknown", "2005"),
    ("aren.260", "aren", "unknown", "260", "unknown"),
])
def test_link_identity_preserves_filename_tokens_without_claiming_sites(
    name: str, code: str, sensor: str, day: str, year: str
) -> None:
    identity = link_identity("https://www.tsunami.gov/previous.events/Data/" + name)
    assert [identity[f"link_{key}"] for key in ("code", "sensor", "day", "year")] == [
        code, sensor, day, year]


@pytest.mark.parametrize("name", ["Hilo.txt", "site_A_2011.000", "site_A_2011.999", "", "odd.dat"])
def test_unknown_filename_does_not_invent_a_code(name: str) -> None:
    assert link_identity(name)["link_code"] == "unknown"


def write_contract(tmp_path: Path, *, role: str = "development") -> tuple[Path, Path]:
    raw = tmp_path / "data/raw/fixture.html"
    raw.parent.mkdir(parents=True)
    payload = page(example_row()).encode()
    raw.write_bytes(payload)
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n",
                                                  encoding="utf-8")
    config = tmp_path / "contract.toml"
    config.write_text(f'''
[events.fixture]
event_id = "fixture-id"
archive_source_id = "fixture-source"
role = "{role}"
archive_url = "{ARCHIVE_URL}"

[assets.fixture]
availability = "approved"
reason = "test only"
source_id = "fixture-source"
source_class = "archive page"
url = "{ARCHIVE_URL}"
local_path = "data/raw/fixture.html"
format = "HTML"
publisher = "fixture"
expected_content_signature = "fixture table"
expected_prefix = "<"
units = "source-specific"
crs = "unknown"
horizontal_datum = "unknown"
vertical_datum = "unknown"
coordinate_order = "unknown"
temporal_semantics = "source strings only"
station_metadata = "source location label only"
''', encoding="utf-8")
    return config, raw


def test_inventory_verifies_checksum_and_never_overwrites(tmp_path: Path) -> None:
    config, _ = write_contract(tmp_path)
    out = tmp_path / "result"
    counts = inventory(config, tmp_path, out)
    assert counts == {"events": 1, "development_rows": 1, "development_links": 2}
    assert sorted(item.name for item in out.iterdir()) == [
        "census.csv", "census.json", "links.csv", "links.json", "rows.csv", "rows.json"]
    with pytest.raises(FileExistsError):
        inventory(config, tmp_path, out)
    second = tmp_path / "second"
    inventory(config, tmp_path, second)
    assert all(path.read_bytes() == (second / path.name).read_bytes() for path in out.iterdir())


def test_checksum_mismatch_does_not_publish_output(tmp_path: Path) -> None:
    config, raw = write_contract(tmp_path)
    raw.write_text("changed", encoding="utf-8")
    with pytest.raises(ArchiveError, match="checksum mismatch"):
        inventory(config, tmp_path, tmp_path / "result")
    assert not (tmp_path / "result").exists()


def test_inventory_sealed_masking_and_cli(tmp_path: Path, capsys: Any) -> None:
    config, _ = write_contract(tmp_path, role="sealed_evaluation")
    out = tmp_path / "result"
    assert main(["--config", str(config), "--root", str(tmp_path), "--output", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["development_rows"] == 0
    for path in out.iterdir():
        assert "1344" not in path.read_text(encoding="utf-8")
        assert "hilo.070" not in path.read_text(encoding="utf-8")


def test_source_symlink_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    config, raw = write_contract(root)
    outside = tmp_path / "outside.html"
    raw.rename(outside)
    raw.symlink_to(outside)
    with pytest.raises(ArchiveError, match="outside root"):
        inventory(config, root, root / "result")
