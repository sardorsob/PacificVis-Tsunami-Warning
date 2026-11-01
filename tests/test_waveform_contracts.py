"""Acquisition contracts must be bounded by source identity, time and reservation."""

from __future__ import annotations

import csv
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from scripts.generate_waveform_contracts import generate


def freeze(events: Path) -> Path:
    doc = tomllib.loads(events.read_text())
    ledger: dict[str, Any] = {"events": list(doc["events"].values())}
    digest = hashlib.sha256(
        json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger["selection_sha256"] = digest
    events.write_text(events.read_text().replace(doc["selection_sha256"], digest))
    path = events.with_suffix(".json")
    path.write_text(json.dumps(ledger))
    return path


def inputs(tmp_path: Path) -> dict[str, Any]:
    events = tmp_path / "events.toml"
    events.write_text("""selection_sha256="frozen"
[events.a]
event_id="a"
role="development"
archive_source_id="ntwc-a"
archive_url="https://www.tsunami.gov/previous.events/?p=Event-A"
usgs_time="2011-03-11T05:46:24Z"
attribution_status="single_source_metadata"
region="northwest_pacific"
[events.b]
event_id="b"
role="sealed_evaluation"
archive_source_id="ntwc-b"
archive_url="https://www.tsunami.gov/previous.events/?p=Event-B"
usgs_time="2011-04-01T00:00:00Z"
""")
    census = tmp_path / "census"
    census.mkdir()
    links: list[dict[str, Any]] = []
    captures: list[list[str]] = []
    probes: list[dict[str, Any]] = []
    for day in [69, 70, 71, 72]:
        url = f"https://www.tsunami.gov/previous.events/Event-A/Data/test_A_2011.{day:03}"
        original = url.replace("https:", "http:")
        capture = f"https://web.archive.org/web/20161201000000id_/{original}"
        links.append(
            dict(
                event_id="a",
                role="development",
                source_id="ntwc-a",
                status="safe_archive_link",
                href=url,
                resolved_url=url,
            )
        )
        captures.append(["20161201000000", original, "A" * 32, "10000"])
        text = "Test,_USA 1234567 NOS Continuous 10 20 20110311\n"
        probes.append(
            dict(
                capture_url=capture,
                probe_status="success",
                expected_prefix="Test,_USA",
                prefix_text=text,
                prefix_sha256=hashlib.sha256(text.encode()).hexdigest(),
            )
        )
    (census / "links.json").write_text(json.dumps(links))
    prefix = tmp_path / "prefixes.json"
    prefix.write_text(json.dumps({"requests": probes}))
    raw = tmp_path / "cdx.json"
    payload = json.dumps([["timestamp", "original", "digest", "length"], *captures]).encode()
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    contract = dict.fromkeys(
        [
            "source_class",
            "publisher",
            "expected_content_signature",
            "units",
            "crs",
            "horizontal_datum",
            "vertical_datum",
            "coordinate_order",
            "temporal_semantics",
            "station_metadata",
            "reason",
        ],
        "fixture",
    )
    contract.update(
        source_id="ia-cdx-a",
        availability="approved",
        url="https://web.archive.org/cdx/search/cdx?url=https%3A%2F%2Fwww.tsunami.gov%2Fprevious.events%2FEvent-A%2FData%2F%2A",
        local_path="cdx.json",
        format="JSON",
        expected_prefix="[",
    )
    config = tmp_path / "cdx.toml"
    config.write_text(
        "[assets.a]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in contract.items())
    )
    receipt = tmp_path / "receipts.json"
    receipt.write_text(
        json.dumps(
            [
                dict(
                    source_id="ia-cdx-a",
                    status="downloaded",
                    reason="not applicable",
                    local_path="cdx.json",
                    sha256=digest,
                    bytes=len(payload),
                )
            ]
        )
    )
    return dict(
        events_config=events,
        selection=freeze(events),
        census=census,
        cdx_config=config,
        cdx_receipts=receipt,
        root=tmp_path,
        controls=0,
        prefixes=[prefix],
    )


def test_four_day_exact_links_form_bounded_reproducible_contracts(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    first, second = tmp_path / "one", tmp_path / "two"
    result = generate(**kwargs, output=first, max_contracts=2)
    generate(**kwargs, output=second, max_contracts=2)
    assert result["selected_pairs_count"] == 1
    assert [b["contracts"] for b in result["batches"]] == [2, 2]
    for p in first.iterdir():
        assert p.read_bytes() == (second / p.name).read_bytes()
    doc = tomllib.loads((first / "ia-001.toml").read_text())
    for window in doc["source_windows"].values():
        assert window["start_utc"] == "2011-03-10T00:00:00+00:00"
        assert window["stop_utc"] == "2011-03-14T00:00:00+00:00"
    with pytest.raises(FileExistsError):
        generate(**kwargs, output=first)


def test_pinned_cdx_mode_emits_only_exact_evidence_bound_captures_without_prefix_gets(
    tmp_path: Path,
) -> None:
    kwargs = inputs(tmp_path)
    kwargs["prefixes"] = []
    result = generate(**kwargs, output=tmp_path / "out", use_cdx_digests=True)
    assert result["status"] == "ready" and result["batches"][0]["contracts"] == 4
    assert json.loads((tmp_path / "out/prefix-probes.json").read_text())["requests"] == []
    assets = tomllib.loads((tmp_path / "out/ia-001.toml").read_text())["assets"]
    assert all(
        a["expected_prefix"] == "" and a["expected_cdx_sha1"] == "A" * 32 for a in assets.values()
    )
    assert all(a["cdx_evidence_path"] == "cdx.json" for a in assets.values())
    assert all(
        a["cdx_evidence_sha256"] == hashlib.sha256((tmp_path / "cdx.json").read_bytes()).hexdigest()
        for a in assets.values()
    )


@pytest.mark.parametrize("change", ["reserved_overlap", "compound", "unknown_origin"])
def test_event_origin_guards_produce_explicit_dispositions(tmp_path: Path, change: str) -> None:
    kwargs = inputs(tmp_path)
    p = kwargs["events_config"]
    text = p.read_text()
    if change == "reserved_overlap":
        text = text.replace("2011-04-01T00:00:00Z", "2011-03-12T00:00:00Z")
    elif change == "compound":
        text = text.replace("single_source_metadata", "compound_unresolved")
    else:
        text = text.replace("2011-03-11T05:46:24Z", "unknown")
    p.write_text(text)
    freeze(p)
    result = generate(**kwargs, output=tmp_path / "out")
    assert result["selected_pairs_count"] == 0 and result["batches"] == []
    assert result["event_dispositions"][0]["status"] != "eligible"


def test_missing_prefixes_are_probe_requests_not_waveform_contracts(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    kwargs["prefixes"] = []
    out = tmp_path / "out"
    result = generate(**kwargs, output=out)
    assert result["status"] == "prefixes_required" and result["batches"] == []
    assert len(json.loads((out / "prefix-probes.json").read_text())["requests"]) == 4
    assert len(json.loads((out / "header-probe-suggestions.json").read_text())["requests"]) == 1
    assert result["estimated_transfer_bytes"] == 4 * 131072


def test_over_budget_does_not_publish_fetchable_batches(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    out = tmp_path / "out"
    result = generate(**kwargs, output=out, remaining_bytes=1)
    assert result["status"] == "over_budget" and not list(out.glob("*.toml"))


def test_relative_link_recovery_is_unique_event_scoped_and_explicit(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    path = kwargs["census"] / "links.json"
    rows = json.loads(path.read_text())
    rows[0]["href"] = "test_A_2011.069"
    rows[0]["resolved_url"] = "https://www.tsunami.gov/previous.events/test_A_2011.069"
    path.write_text(json.dumps(rows))
    out = tmp_path / "out"
    generate(**kwargs, output=out)
    entry = json.loads((out / "link-dispositions.json").read_text())[0]
    assert entry["source_href"] == "test_A_2011.069"
    assert entry["link_resolution_rule"] == "unique_event_scoped_cdx_filename"
    assert "/Event-A/Data/" in entry["reconstructed_url"]


@pytest.mark.parametrize("violation", ["reserved", "checksum", "overbroad", "prefix"])
def test_untrusted_identity_or_bytes_never_generate_requests(
    tmp_path: Path, violation: str
) -> None:
    kwargs = inputs(tmp_path)
    if violation == "reserved":
        p = kwargs["events_config"]
        p.write_text(p.read_text().replace('role="development"', 'role="sealed_evaluation"'))
    elif violation == "checksum":
        (tmp_path / "cdx.json").write_text("altered")
    elif violation == "overbroad":
        p = kwargs["cdx_config"]
        p.write_text(p.read_text().replace("Event-A%2FData%2F", ""))
        result = generate(**kwargs, output=tmp_path / "out")
        assert (
            result["batches"] == []
            and result["cdx_dispositions"][0]["status"] == "rejected_overbroad_cdx_scope"
        )
        return
    else:
        p = kwargs["prefixes"][0]
        p.write_text(p.read_text().replace("Test,_USA", "Wrong,_USA", 1))
    with pytest.raises(ValueError):
        generate(**kwargs, output=tmp_path / "out")


def reviewed_site(path: Path, **updates: str) -> Path:
    evidence = json.dumps(
        [
            {
                "event_id": "a",
                "report_id": "a:0:1",
                "physical_site_id": "coops:1234567",
                "headers": [
                    {
                        "source_id": "header-a",
                        "header_station_id": "1234567",
                        "provider": "NOS",
                        "sha256": "a" * 64,
                    }
                ],
            }
        ]
    )
    row = dict(
        event_id="a",
        report_id="a:0:1",
        identity_tier="header_exact",
        provider="CO-OPS",
        provider_station_id="1234567",
        physical_site_id="coops:1234567",
        event_site_identity_verified="True",
        review_status="independently_reviewed",
        source_ids='["header-a"]',
        evidence=evidence,
        identity_evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
    )
    row.update(updates)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def test_only_digest_bound_independent_sites_authorize_coops(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    site = reviewed_site(tmp_path / "sites.csv", review_status="pending_independent_review")
    result = generate(**kwargs, reviewed_sites=site, output=tmp_path / "pending")
    assert result["coops_reviewed_event_site_windows"] == 0
    reviewed_site(site)
    result = generate(**kwargs, reviewed_sites=site, output=tmp_path / "reviewed")
    assert result["coops_reviewed_event_site_windows"] == 1
    coops = tomllib.loads((tmp_path / "reviewed/coops-001.toml").read_text())
    assert len(coops["assets"]) == 2
    assert all(c["expected_prefix"] == "{" for c in coops["assets"].values())
    reviewed_site(site, identity_evidence_sha256="0" * 64)
    with pytest.raises(ValueError, match="evidence"):
        generate(**kwargs, reviewed_sites=site, output=tmp_path / "bad")


def test_source_qualified_sites_never_authorize_coops_even_with_numeric_header_id(
    tmp_path: Path,
) -> None:
    kwargs = inputs(tmp_path)
    site = reviewed_site(tmp_path / "sites.csv", identity_scope="source_qualified_geographic_site")
    result = generate(**kwargs, reviewed_sites=site, output=tmp_path / "out")
    assert result["coops_reviewed_event_site_windows"] == 0
    assert not (tmp_path / "out/coops-001.toml").exists()


def test_control_candidates_exclude_catalog_events_and_uncovered_time(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    kwargs["controls"] = 1
    site = reviewed_site(tmp_path / "sites.csv")
    catalog = tmp_path / "catalog.csv"
    for label, middle in [("quiet", ""), ("event", "2011-02-25T00:00:00Z,middle,earthquake\n")]:
        payload = (
            "time,id,type\n2000-01-01T00:00:00Z,first,earthquake\n"
            + middle
            + "2020-01-01T00:00:00Z,last,earthquake\n"
        ).encode()
        catalog.write_bytes(payload)
        catalog.with_name(catalog.name + ".sha256").write_text(hashlib.sha256(payload).hexdigest())
        generate(**kwargs, reviewed_sites=site, known_catalog=catalog, output=tmp_path / label)
    quiet = tomllib.loads((tmp_path / "quiet/coops-001.toml").read_text())
    event = tomllib.loads((tmp_path / "event/coops-001.toml").read_text())
    assert len(quiet["assets"]) == 4 and len(event["assets"]) == 4
    assert {w["offset_days"] for w in event["source_windows"].values()} == {"0", "-21"}
    log = json.loads((tmp_path / "event/request-dispositions.json").read_text())
    assert any(
        r["request_status"] == "window_overlap" and r["conflicting_event_ids"] == ["middle"]
        for r in log
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_station_id", "7654321"),
        ("source_ids", '["wrong"]'),
        ("report_id", "a:2:3"),
        ("physical_site_id", "coops:7654321"),
    ],
)
def test_reviewed_top_level_fields_are_bound_to_hashed_evidence(
    tmp_path: Path, field: str, value: str
) -> None:
    kwargs = inputs(tmp_path)
    sites = reviewed_site(tmp_path / "sites.csv", **{field: value})
    with pytest.raises(ValueError, match="evidence"):
        generate(**kwargs, reviewed_sites=sites, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("change", ["role", "origin", "ledger"])
def test_frozen_selection_rejects_config_or_ledger_mutation(tmp_path: Path, change: str) -> None:
    kwargs = inputs(tmp_path)
    path = kwargs["selection"] if change == "ledger" else kwargs["events_config"]
    text = path.read_text()
    if change == "role":
        text = text.replace('role="development"', 'role="sealed_evaluation"')
    else:
        text = text.replace("2011-03-11T05:46:24Z", "2011-03-12T05:46:24Z")
    path.write_text(text)
    with pytest.raises(ValueError, match="frozen selection"):
        generate(**kwargs, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_delta_batches_retain_existing_sources_without_duplicate_fetches(tmp_path: Path) -> None:
    kwargs = inputs(tmp_path)
    old = tmp_path / "old"
    generate(**kwargs, output=old)
    current = tmp_path / "new"
    result = generate(**kwargs, output=current, existing_contracts=[old / "ia-001.toml"])
    assert result["batches"] == [] and result["estimated_transfer_bytes"] == 0
    assert len(result["existing_source_ids_retained"]) == 4
    log = json.loads((current / "request-dispositions.json").read_text())
    assert {r["request_status"] for r in log} == {"existing_contract_retained"}
    prior = old / "ia-001.toml"
    prior.write_text(prior.read_text().replace("20161201000000id_", "20170101000000id_"))
    with pytest.raises(ValueError, match="existing source identity/window conflicts"):
        generate(**kwargs, output=tmp_path / "conflict", existing_contracts=[prior])
    assert not (tmp_path / "conflict").exists()


@pytest.mark.parametrize("failure", ["none", "final_url", "checksum", "event", "receipt_ids"])
def test_exact_receipted_capture_reuses_body_without_transfer_or_header_promotion(
    tmp_path: Path, failure: str
) -> None:
    kwargs = inputs(tmp_path)
    first = tmp_path / "initial"
    generate(**kwargs, output=first)
    source = next(iter(tomllib.loads((first / "ia-001.toml").read_text())["assets"].values()))
    source["source_id"] = "header-witness"
    source["local_path"] = "raw/a/test_A_2011.069"
    raw = tmp_path / source["local_path"]
    raw.parent.mkdir(parents=True)
    payload = b"Test,_USA 1234567 NOS Continuous 10 20 20110310\n"
    raw.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    raw.with_name(raw.name + ".sha256").write_text(digest)
    receipt: dict[str, Any] = dict(
        source_id=source["source_id"],
        status="downloaded",
        local_path=source["local_path"],
        final_url=source["url"],
        sha256=digest,
        bytes=len(payload),
    )
    if failure == "final_url":
        receipt["final_url"] = source["url"].replace("20161201000000", "20170101000000")
    elif failure == "checksum":
        receipt["sha256"] = "0" * 64
    elif failure == "event":
        source["local_path"] = "raw/b/test_A_2011.069"
        receipt["local_path"] = source["local_path"]
    elif failure == "receipt_ids":
        receipt["source_id"] = "other"
    config, receipts = tmp_path / "reuse.toml", tmp_path / "reuse.json"
    config.write_text(
        "[assets.header]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in source.items())
    )
    receipts.write_text(json.dumps([receipt]))
    if failure != "none":
        with pytest.raises(ValueError, match="reuse|checksum"):
            generate(
                **kwargs, output=tmp_path / "out", reuse_configs=[config], reuse_receipts=[receipts]
            )
        assert not (tmp_path / "out").exists()
        return
    standard = generate(
        **kwargs, output=tmp_path / "standard-delta",
        existing_contracts=[first / "ia-001.toml"],
        reuse_configs=[config], reuse_receipts=[receipts],
    )
    assert standard["batches"] == []
    assert len(standard["existing_source_ids_retained"]) == 4
    kwargs["prefixes"] = []  # Receipt-verified raw bytes themselves supply the prefix.
    result = generate(
        **kwargs, output=tmp_path / "out", reuse_configs=[config], reuse_receipts=[receipts]
    )
    assert len(result["cached_capture_reuse"]) == 1
    assert result["estimated_transfer_bytes"] == 3 * 131072
    assert result["batches"][0]["contracts"] == 1
    assert result["batches"][0]["estimated_bytes"] == 0
    doc = tomllib.loads((tmp_path / "out/ia-001.toml").read_text())
    (asset,) = doc["assets"].values()
    assert asset["local_path"] == source["local_path"] and asset["source_id"] != "header-witness"
    assert next(iter(doc["source_windows"].values()))["purpose"] == "event_window"
    assert config.read_text().startswith("[assets.header]")  # Original metadata contract unchanged.
    prior = tmp_path / "out/ia-001.toml"
    prior_bytes = prior.read_bytes()
    delta = generate(
        **kwargs, output=tmp_path / "reuse-delta", existing_contracts=[prior],
        reuse_configs=[config], reuse_receipts=[receipts],
    )
    assert delta["batches"] == []
    assert delta["existing_source_ids_retained"] == [asset["source_id"]]
    log = json.loads((tmp_path / "reuse-delta/request-dispositions.json").read_text())
    assert next(row for row in log if row["source_id"] == asset["source_id"])[
        "request_status"
    ] == "existing_contract_retained"
    assert prior.read_bytes() == prior_bytes
    changed = tmp_path / "changed-prior.toml"
    changed.write_text(prior.read_text().replace(source["local_path"], "raw/a/wrong_A_2011.069"))
    with pytest.raises(ValueError, match="existing source identity/window conflicts"):
        generate(
            **kwargs, output=tmp_path / "wrong-path", existing_contracts=[changed],
            reuse_configs=[config], reuse_receipts=[receipts], use_cdx_digests=True,
        )
