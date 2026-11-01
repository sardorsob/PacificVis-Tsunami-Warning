import base64
import hashlib
import io
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from pipeline.acquisition import (
    AcquisitionResult,
    RejectArchiveCaptureRedirects,
    ResponseMetadata,
    SourceContract,
    TransferBudget,
    acquire_all,
    acquire_source,
    download_url,
    load_contracts,
    stream_to_path,
)
from scripts import acquire_tohoku as acquire_script
from scripts.acquire_tohoku import working_tree_status, write_run_evidence


@pytest.mark.parametrize("changed", [False, True])
def test_exact_ia_capture_checks_final_url_before_reading_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    url = "https://web.archive.org/web/20161222045941id_/http://www.tsunami.gov/previous.events/a/test_A_2011.070"
    headers = Message()
    headers["Content-Type"] = "text/plain"
    reads: list[int] = []

    class Response:
        def __init__(self) -> None:
            self.headers = headers
        def __enter__(self) -> "Response":
            return self
        def __exit__(self, *args: object) -> None:
            pass
        def geturl(self) -> str:
            return url.replace("20161222045941", "20170101000000") if changed else url
        def read(self, size: int) -> bytes:
            reads.append(size)
            return b"fixture" if len(reads) == 1 else b""

    class Opener:
        def open(self, requested: str, timeout: float) -> Response:
            assert requested == url
            return Response()

    def factory(handler: object) -> Opener:
        assert isinstance(handler, RejectArchiveCaptureRedirects)
        return Opener()

    monkeypatch.setattr("pipeline.acquisition.build_opener", factory)
    if changed:
        with pytest.raises(ValueError, match="final_url_mismatch"):
            download_url(url, tmp_path / "data", 30)
        assert not reads and not (tmp_path / "data").exists()
    else:
        metadata = download_url(url, tmp_path / "data", 30)
        assert metadata.final_url == url and (tmp_path / "data").read_bytes() == b"fixture"
    with pytest.raises(ValueError, match="redirect_rejected"):
        RejectArchiveCaptureRedirects().redirect_request(
            Request(url), object(), 302, "redirect", {}, "https://example.com/other"
        )


def fixture_fetcher(payload: bytes):
    """Return a fetcher that writes fixture bytes to its requested destination."""

    def fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        del url, timeout_seconds
        destination.write_bytes(payload)
        return ResponseMetadata(content_type="application/json", headers={})

    return fetcher


@pytest.mark.parametrize("payload", [b"\xff\xd8\xfffixture", b"<html>error</html>"])
def test_binary_signature_checks_source_bytes_without_utf8_coercion(
    tmp_path: Path, payload: bytes,
) -> None:
    contract = sample_contract(expected_prefix="hex:ffd8ff")
    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(payload))
    assert result.status == ("downloaded" if payload.startswith(b"\xff\xd8\xff") else "quarantined")
    if result.status == "downloaded":
        assert (tmp_path / contract.local_path).read_bytes() == payload


@pytest.mark.parametrize("prefix", ["hex:", "hex:f", "hex:zz"])
def test_malformed_binary_signature_is_rejected_before_network(
    tmp_path: Path, prefix: str,
) -> None:
    contract = sample_contract(expected_prefix=prefix)
    config = tmp_path / "binary.toml"
    values = {key: str(value) for key, value in asdict(contract).items()}
    config.write_text("[assets.fixture]\n" + "\n".join(
        key + " = " + json.dumps(value) for key, value in values.items()
    ))
    with pytest.raises(ValueError, match="prefix"):
        load_contracts(config)


def test_acquire_source_writes_verified_bytes_atomically(tmp_path: Path) -> None:
    contract = SourceContract(
        source_id="sample",
        source_class="event",
        availability="approved",
        url="https://example.test/sample.json",
        local_path=PurePosixPath("data/raw/sample.json"),
        format="json",
        publisher="fixture",
        expected_content_signature="fixture JSON object",
        expected_prefix="{",
        units="not applicable",
        crs="not applicable",
        horizontal_datum="not applicable",
        vertical_datum="not applicable",
        coordinate_order="not applicable",
        temporal_semantics="not applicable",
        station_metadata="not applicable",
        reason="not applicable",
    )

    payload = (Path(__file__).parent / "fixtures/acquisition/sample.json").read_bytes().rstrip()
    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(payload))

    assert result.status == "downloaded"
    assert result.bytes == 11
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / contract.local_path).read_bytes() == payload
    assert (tmp_path / contract.local_path).with_name("sample.json.sha256").read_text() == (
        f"{result.sha256}\n"
    )
    assert result.content_type == "application/json"
    assert result.headers == {}


def test_write_run_evidence_writes_an_immutable_portable_bundle(tmp_path: Path) -> None:
    config = tmp_path / "tohoku.toml"
    config.write_text("[assets]\n", encoding="utf-8")
    approved = sample_contract()
    blocked = replace(
        approved,
        source_id="blocked",
        availability="blocked",
        local_path=PurePosixPath("not-downloaded"),
        url="https://example.test/blocked",
        reason="source access is blocked",
    )
    results = (
        acquire_source(
            approved,
            tmp_path,
            fetcher=fixture_fetcher(b'{"ok":true}'),
        ),
        acquire_source(blocked, tmp_path),
    )

    run_path = write_run_evidence(
        root=tmp_path,
        run_tag="Initial Rerun!",
        config_path=config,
        contracts=(approved, blocked),
        results=results,
        command="uv run python scripts/acquire_tohoku.py --run-tag Initial Rerun!",
        mode="live",
        lane="story",
        now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
        git_sha=lambda: "be7f766",
        working_tree=lambda: "dirty",
    )

    assert run_path.name == "2011-03-11__0546__initial-rerun__be7f766"
    assert {path.name for path in run_path.iterdir()} == {
        "config.json",
        "inputs.json",
        "meta.json",
        "metrics.json",
        "notes.md",
        "outputs.json",
    }
    assert json.loads((run_path / "meta.json").read_text(encoding="utf-8")) == {
        "command": "uv run python scripts/acquire_tohoku.py --run-tag Initial Rerun!",
        "evidence_disposition": "implementation-under-review",
        "git_sha": "be7f766",
        "lane": "story",
        "mode": "live",
        "run_id": "2011-03-11__0546__initial-rerun__be7f766",
        "timestamp_utc": "2011-03-11T05:46:00Z",
        "working_tree": "dirty",
    }
    inputs = json.loads((run_path / "inputs.json").read_text(encoding="utf-8"))
    assert [(item["source_id"], item["availability"], item["url"]) for item in inputs] == [
        ("blocked", "blocked", "https://example.test/blocked"),
        ("sample", "approved", "https://example.test/sample.json"),
    ]
    outputs = json.loads((run_path / "outputs.json").read_text(encoding="utf-8"))
    assert outputs[0]["source_id"] == "blocked"
    assert outputs[1]["content_type"] == "application/json"
    assert json.loads((run_path / "metrics.json").read_text(encoding="utf-8")) == {
        "bytes_by_status": {"blocked": 0, "downloaded": 11},
        "status_counts": {"blocked": 1, "downloaded": 1},
        "total_bytes": 11,
        "total_contracts": 2,
        "total_outcomes": 2,
    }
    assert "## Decision" in (run_path / "notes.md").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_run_evidence(
            root=tmp_path,
            run_tag="Initial Rerun!",
            config_path=config,
            contracts=(approved, blocked),
            results=results,
            command="test",
            mode="live",
            lane="story",
            now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
            git_sha=lambda: "be7f766",
            working_tree=lambda: "dirty",
        )


def test_write_run_evidence_rejects_an_unknown_lane(tmp_path: Path) -> None:
    config = tmp_path / "tohoku.toml"
    config.write_text("[assets]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported run lane"):
        write_run_evidence(
            root=tmp_path,
            run_tag="bad-lane",
            config_path=config,
            contracts=(),
            results=(),
            command="fixture",
            mode="offline",
            lane=cast(Any, "unknown"),
        )


def test_working_tree_status_ignores_only_generated_run_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []

    def fake_check_output(command: list[str], **kwargs: object) -> str:
        del kwargs
        observed.extend(command)
        return ""

    monkeypatch.setattr("scripts.acquire_tohoku.subprocess.check_output", fake_check_output)

    assert working_tree_status(tmp_path) == "clean"
    assert observed == [
        "git",
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)artifacts/logs/runs/**",
    ]


def test_read_ioc_api_key_rejects_malformed_values_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(acquire_script, "read_ioc_api_key")
    loader = acquire_script.read_ioc_api_key
    malformed = "not-a-valid-secret"

    def malformed_key(*args: object, **kwargs: object) -> str:
        del args, kwargs
        return malformed

    monkeypatch.setattr(
        "scripts.acquire_tohoku.subprocess.check_output",
        malformed_key,
    )

    with pytest.raises(ValueError) as error:
        loader()

    assert malformed not in str(error.value)
    assert "128 hexadecimal" in str(error.value)


def test_ioc_keychain_fetcher_routes_the_secret_only_to_the_exact_ioc_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(acquire_script, "ioc_keychain_fetcher")
    factory = acquire_script.ioc_keychain_fetcher
    loaded = 0
    routed: list[tuple[str, str | None]] = []

    def load_key() -> str:
        nonlocal loaded
        loaded += 1
        return "a" * 128

    def ordinary(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        del destination, timeout_seconds
        routed.append((url, None))
        return ResponseMetadata(content_type="application/json", headers={})

    def authenticated(
        url: str, destination: Path, timeout_seconds: float, api_key: str
    ) -> ResponseMetadata:
        del destination, timeout_seconds
        routed.append((url, api_key))
        return ResponseMetadata(content_type="application/json", headers={})

    monkeypatch.setattr(acquire_script, "read_ioc_api_key", load_key)
    monkeypatch.setattr(acquire_script, "download_url", ordinary)
    monkeypatch.setattr(acquire_script, "download_ioc_url", authenticated)
    fetcher = factory()

    fetcher("https://example.test/data", tmp_path / "ordinary", 30)
    fetcher(
        "https://api.ioc-sealevelmonitoring.org/v2/research/data",
        tmp_path / "ioc-a",
        30,
    )
    fetcher(
        "https://api.ioc-sealevelmonitoring.org/v2/catalog/ioc/valp",
        tmp_path / "ioc-b",
        30,
    )
    fetcher("https://api.ioc-sealevelmonitoring.org.evil.test/data", tmp_path / "evil", 30)

    assert loaded == 1
    assert routed == [
        ("https://example.test/data", None),
        ("https://api.ioc-sealevelmonitoring.org/v2/research/data", "a" * 128),
        ("https://api.ioc-sealevelmonitoring.org/v2/catalog/ioc/valp", "a" * 128),
        ("https://api.ioc-sealevelmonitoring.org.evil.test/data", None),
    ]


def test_download_ioc_url_uses_header_auth_and_rejects_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(acquire_script, "download_ioc_url")
    assert hasattr(acquire_script, "RejectAuthenticatedRedirects")
    observed: dict[str, object] = {}
    headers = Message()
    headers["Content-Type"] = "application/json"

    class Response:
        status = 200

        def __init__(self) -> None:
            self.headers = headers
            self._reads = [b'{"data":[]}', b""]

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, size: int) -> bytes:
            del size
            return self._reads.pop(0)

    class Opener:
        def open(self, request: object, timeout: float) -> Response:
            observed["request"] = request
            observed["timeout"] = timeout
            return Response()

    def fake_build_opener(handler: object) -> Opener:
        observed["handler"] = handler
        return Opener()

    monkeypatch.setattr(acquire_script, "build_opener", fake_build_opener)
    destination = tmp_path / "valp.json"
    metadata = acquire_script.download_ioc_url(
        "https://api.ioc-sealevelmonitoring.org/v2/research/data",
        destination,
        30,
        "a" * 128,
    )

    request = observed["request"]
    assert isinstance(request, Request)
    assert request.get_header("X-api-key") == "a" * 128
    assert request.get_header("Accept") == "application/json"
    assert isinstance(observed["handler"], acquire_script.RejectAuthenticatedRedirects)
    assert observed["timeout"] == 30
    assert destination.read_bytes() == b'{"data":[]}'
    assert metadata.content_type == "application/json"

    with pytest.raises(HTTPError, match="redirect refused"):
        acquire_script.RejectAuthenticatedRedirects().redirect_request(
            request, None, 302, "redirect refused", headers, "https://evil.test"
        )


def test_write_run_evidence_keeps_only_safe_response_header_values(tmp_path: Path) -> None:
    config = tmp_path / "tohoku.toml"
    config.write_text("[assets]\n", encoding="utf-8")
    contract = sample_contract()
    result = replace(
        acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}')),
        headers={
            "Authentication-Info": "secret-info",
            "Content-Type": "application/json",
            "ETag": "public-version",
            "X-Auth-Token": "secret-token",
            "X-Unrecognized": "not-implicitly-safe",
        },
    )

    run_path = write_run_evidence(
        root=tmp_path,
        run_tag="header-redaction",
        config_path=config,
        contracts=(contract,),
        results=(result,),
        command="test",
        mode="fixture",
        now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
        git_sha=lambda: "be7f766",
        working_tree=lambda: "clean",
    )

    output = json.loads((run_path / "outputs.json").read_text(encoding="utf-8"))[0]
    assert output["headers"] == {
        "Authentication-Info": "[redacted]",
        "Content-Type": "application/json",
        "ETag": "public-version",
        "X-Auth-Token": "[redacted]",
        "X-Unrecognized": "[redacted]",
    }


def test_write_run_evidence_rejects_duplicate_or_mismatched_source_ids(tmp_path: Path) -> None:
    config = tmp_path / "tohoku.toml"
    config.write_text("[assets]\n", encoding="utf-8")
    contract = sample_contract()
    result = AcquisitionResult(
        source_id="sample",
        status="downloaded",
        local_path=contract.local_path,
        bytes=11,
        sha256="a" * 64,
        reason="not applicable",
    )
    variants = (
        ((contract, contract), (result,), "duplicate contract source_id"),
        ((contract,), (result, result), "duplicate result source_id"),
        ((contract,), (replace(result, source_id="other"),), "source ID sets differ"),
    )

    for contracts, results, message in variants:
        with pytest.raises(ValueError, match=message):
            write_run_evidence(
                root=tmp_path,
                run_tag="invalid",
                config_path=config,
                contracts=contracts,
                results=results,
                command="test",
                mode="fixture",
                now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
                git_sha=lambda: "be7f766",
                working_tree=lambda: "clean",
            )
    assert not (tmp_path / "artifacts/logs/runs").exists()


def test_write_run_evidence_cleans_failed_temp_bundle_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "missing.toml"
    contract = sample_contract()
    result = AcquisitionResult(
        source_id="sample",
        status="downloaded",
        local_path=contract.local_path,
        bytes=11,
        sha256="a" * 64,
        reason="not applicable",
    )
    run_path = tmp_path / "artifacts/logs/runs/2011-03-11__0546__retry__be7f766"

    def write_bundle() -> Path:
        return write_run_evidence(
            root=tmp_path,
            run_tag="retry",
            config_path=config,
            contracts=(contract,),
            results=(result,),
            command="test",
            mode="fixture",
            now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
            git_sha=lambda: "be7f766",
            working_tree=lambda: "clean",
        )

    with pytest.raises(FileNotFoundError):
        write_bundle()
    assert not run_path.exists()

    config.write_text("[assets]\n", encoding="utf-8")
    original_write_json = acquire_script._write_json  # pyright: ignore[reportPrivateUsage]

    def fail_outputs(path: Path, value: object) -> None:
        if path.name == "outputs.json":
            raise OSError("injected write failure")
        original_write_json(path, value)

    monkeypatch.setattr(acquire_script, "_write_json", fail_outputs)
    with pytest.raises(OSError, match="injected write failure"):
        write_bundle()
    assert not run_path.exists()
    runs = run_path.parent
    assert not any(
        path.name.startswith(".2011-03-11__0546__retry__be7f766.") for path in runs.iterdir()
    )

    monkeypatch.setattr(acquire_script, "_write_json", original_write_json)
    assert write_bundle() == run_path


def test_write_run_evidence_respects_an_exclusive_writer_lock(tmp_path: Path) -> None:
    config = tmp_path / "tohoku.toml"
    config.write_text("[assets]\n", encoding="utf-8")
    contract = sample_contract()
    result = AcquisitionResult(
        source_id="sample",
        status="downloaded",
        local_path=contract.local_path,
        bytes=11,
        sha256="a" * 64,
        reason="not applicable",
    )
    runs = tmp_path / "artifacts/logs/runs"
    runs.mkdir(parents=True)
    lock = runs / ".2011-03-11__0546__locked__be7f766.lock"
    lock.write_text("another writer", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_run_evidence(
            root=tmp_path,
            run_tag="locked",
            config_path=config,
            contracts=(contract,),
            results=(result,),
            command="test",
            mode="fixture",
            now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
            git_sha=lambda: "be7f766",
            working_tree=lambda: "clean",
        )

    assert lock.read_text(encoding="utf-8") == "another writer"
    assert not (runs / "2011-03-11__0546__locked__be7f766").exists()


def test_main_records_the_supplied_programmatic_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = sample_contract()
    result = AcquisitionResult(
        source_id="sample",
        status="cached",
        local_path=contract.local_path,
        bytes=11,
        sha256="a" * 64,
        reason="verified immutable cache",
    )
    observed: dict[str, str] = {}

    def fake_load_contracts(path: Path) -> tuple[SourceContract, ...]:
        del path
        return (contract,)

    def fake_acquire_all(*args: object, **kwargs: object) -> tuple[AcquisitionResult, ...]:
        del args, kwargs
        return (result,)

    monkeypatch.setattr(acquire_script, "load_contracts", fake_load_contracts)
    monkeypatch.setattr(acquire_script, "acquire_all", fake_acquire_all)

    def capture_evidence(**kwargs: object) -> Path:
        observed["command"] = str(kwargs["command"])
        return tmp_path / "run"

    monkeypatch.setattr(acquire_script, "write_run_evidence", capture_evidence)
    config = tmp_path / "config with spaces.toml"
    argv = [
        "--config",
        str(config),
        "--root",
        str(tmp_path),
        "--run-tag",
        "Tag With Space",
        "--offline",
    ]

    assert acquire_script.main(argv) == 0
    assert observed["command"] == (
        "uv run python scripts/acquire_tohoku.py --config "
        f"'{config}' --root {tmp_path} --run-tag 'Tag With Space' --offline"
    )


def test_acquire_source_reuses_a_verified_cache_without_fetching(tmp_path: Path) -> None:
    contract = SourceContract(
        source_id="sample",
        source_class="event",
        availability="approved",
        url="https://example.test/sample.json",
        local_path=PurePosixPath("data/raw/sample.json"),
        format="json",
        publisher="fixture",
        expected_content_signature="fixture JSON object",
        expected_prefix="{",
        units="not applicable",
        crs="not applicable",
        horizontal_datum="not applicable",
        vertical_datum="not applicable",
        coordinate_order="not applicable",
        temporal_semantics="not applicable",
        station_metadata="not applicable",
        reason="not applicable",
    )
    payload = b'{"ok":true}'
    acquire_source(contract, tmp_path, fetcher=fixture_fetcher(payload))

    def unfetched(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        del url, destination, timeout_seconds
        raise AssertionError("cache reuse must not fetch")

    result = acquire_source(contract, tmp_path, fetcher=unfetched)

    assert result.status == "cached"
    assert result.sha256 == hashlib.sha256(payload).hexdigest()


def test_acquire_source_quarantines_an_invalid_existing_file(tmp_path: Path) -> None:
    contract = SourceContract(
        source_id="sample",
        source_class="event",
        availability="approved",
        url="https://example.test/sample.json",
        local_path=PurePosixPath("data/raw/sample.json"),
        format="json",
        publisher="fixture",
        expected_content_signature="fixture JSON object",
        expected_prefix="{",
        units="not applicable",
        crs="not applicable",
        horizontal_datum="not applicable",
        vertical_datum="not applicable",
        coordinate_order="not applicable",
        temporal_semantics="not applicable",
        station_metadata="not applicable",
        reason="not applicable",
    )
    target = tmp_path / contract.local_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unexpected")

    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert result.status == "quarantined"
    assert result.reason == "missing_checksum_record"
    assert target.read_bytes() == b"unexpected"


def test_acquire_all_isolates_a_transient_source_failure_in_source_id_order(tmp_path: Path) -> None:
    contracts = (
        SourceContract(
            source_id="z-fails",
            source_class="event",
            availability="approved",
            url="https://example.test/fails",
            local_path=PurePosixPath("data/raw/fails.json"),
            format="json",
            publisher="fixture",
            expected_content_signature="fixture JSON object",
            expected_prefix="{",
            units="not applicable",
            crs="not applicable",
            horizontal_datum="not applicable",
            vertical_datum="not applicable",
            coordinate_order="not applicable",
            temporal_semantics="not applicable",
            station_metadata="not applicable",
            reason="not applicable",
        ),
        SourceContract(
            source_id="a-downloads",
            source_class="event",
            availability="approved",
            url="https://example.test/downloads",
            local_path=PurePosixPath("data/raw/downloads.json"),
            format="json",
            publisher="fixture",
            expected_content_signature="fixture JSON object",
            expected_prefix="{",
            units="not applicable",
            crs="not applicable",
            horizontal_datum="not applicable",
            vertical_datum="not applicable",
            coordinate_order="not applicable",
            temporal_semantics="not applicable",
            station_metadata="not applicable",
            reason="not applicable",
        ),
    )

    def fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        del timeout_seconds
        if url.endswith("fails"):
            raise URLError("temporary outage")
        destination.write_bytes(b'{"ok":true}')
        return ResponseMetadata(content_type="application/json", headers={})

    results = acquire_all(contracts, tmp_path, fetcher=fetcher)

    assert [result.source_id for result in results] == ["a-downloads", "z-fails"]
    assert [result.status for result in results] == ["downloaded", "quarantined"]


def test_acquire_source_never_fetches_a_blocked_contract(tmp_path: Path) -> None:
    contract = SourceContract(
        source_id="blocked",
        source_class="event",
        availability="blocked",
        url="https://example.test/blocked",
        local_path=PurePosixPath("not-downloaded"),
        format="unknown",
        publisher="fixture",
        expected_content_signature="unknown",
        expected_prefix="not applicable",
        units="unknown",
        crs="unknown",
        horizontal_datum="unknown",
        vertical_datum="unknown",
        coordinate_order="unknown",
        temporal_semantics="unknown",
        station_metadata="not applicable",
        reason="source access is blocked",
    )

    def must_not_fetch(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        del url, destination, timeout_seconds
        raise AssertionError("blocked contracts must never fetch")

    result = acquire_source(contract, tmp_path, fetcher=must_not_fetch)

    assert result.status == "blocked"
    assert result.reason == "source access is blocked"


def test_load_contracts_preserves_the_approved_source_contract_fields() -> None:
    contracts = load_contracts(Path("config/tohoku-data-proof.toml"))

    event = next(
        contract for contract in contracts if contract.source_id == "usgs-tohoku-origin-csv"
    )
    blocked = next(contract for contract in contracts if contract.availability == "blocked")

    assert len(contracts) == 18
    assert event.expected_content_signature.startswith("One CSV row")
    assert event.expected_prefix == "time,latitude,longitude,depth"
    assert event.crs == "WGS84 horizontal coordinates"
    assert event.temporal_semantics == "origin timestamp is UTC; record update is source metadata"
    assert event.station_metadata == "not applicable"
    assert event.reason == "not applicable"
    assert blocked.reason != "not applicable"
    valparaiso = next(
        contract
        for contract in contracts
        if contract.source_id == "ioc-valparaiso-rad-20110311to20110314"
    )
    assert valparaiso.availability == "approved"
    assert valparaiso.format == "IOC SLSMF v2 research JSON"
    assert "includesensors%5B%5D=rad" in valparaiso.url
    assert "filter_exceeded_neighbours=false" in valparaiso.url


def test_acquire_source_limits_the_prefix_identity_check_to_a_leading_window(
    tmp_path: Path,
) -> None:
    contract = SourceContract(
        source_id="sample",
        source_class="event",
        availability="approved",
        url="https://example.test/sample.json",
        local_path=PurePosixPath("data/raw/sample.json"),
        format="json",
        publisher="fixture",
        expected_content_signature="fixture JSON object",
        expected_prefix="{",
        units="not applicable",
        crs="not applicable",
        horizontal_datum="not applicable",
        vertical_datum="not applicable",
        coordinate_order="not applicable",
        temporal_semantics="not applicable",
        station_metadata="not applicable",
        reason="not applicable",
    )

    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b" " * 65_536 + b"{}"))

    assert result.status == "quarantined"
    assert result.reason == "content_signature_mismatch"


def sample_contract(**changes: str | PurePosixPath) -> SourceContract:
    """Build a valid compact contract for focused acquisition tests."""
    contract = SourceContract(
        source_id="sample", source_class="event", availability="approved",
        url="https://example.test/sample.json", local_path=PurePosixPath("data/raw/sample.json"),
        format="json", publisher="fixture", expected_content_signature="fixture JSON object",
        expected_prefix="{", units="not applicable", crs="not applicable",
        horizontal_datum="not applicable", vertical_datum="not applicable",
        coordinate_order="not applicable", temporal_semantics="not applicable",
        station_metadata="not applicable", reason="not applicable",
    )
    return replace(contract, **changes)


def cdx_contract(tmp_path: Path, payload: bytes) -> SourceContract:
    original = "http://www.tsunami.gov/previous.events/Event-A/Data/exam_A_2011.070"
    digest = base64.b32encode(hashlib.sha1(payload, usedforsecurity=False).digest()).decode()
    evidence = tmp_path / "cdx.json"
    evidence.write_text(json.dumps([
        ["timestamp", "original", "digest", "statuscode"],
        ["20161201000000", original, digest, "200"],
    ]))
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    evidence.with_name("cdx.json.sha256").write_text(evidence_sha)
    return sample_contract(
        url="https://web.archive.org/web/20161201000000id_/" + original,
        expected_prefix="", expected_cdx_sha1=digest,
        cdx_evidence_path="cdx.json", cdx_evidence_sha256=evidence_sha,
    )


def test_pinned_cdx_bytes_and_cache_are_rechecked_and_recorded(tmp_path: Path) -> None:
    payload = b"268.958344 1.668000\n"
    contract = cdx_contract(tmp_path, payload)

    def fetch(url: str, path: Path, timeout: float) -> ResponseMetadata:
        path.write_bytes(payload)
        return ResponseMetadata("text/plain", {}, final_url=url)

    result = acquire_source(contract, tmp_path, fetcher=fetch)
    assert result.status == "downloaded" and result.verified_cdx_sha1 == contract.expected_cdx_sha1
    assert acquire_source(contract, tmp_path, fetcher=fetch).status == "cached"
    raw = tmp_path / contract.local_path
    raw.write_bytes(b"different bytes but valid SHA256 sidecar\n")
    raw.with_name(raw.name + ".sha256").write_text(hashlib.sha256(raw.read_bytes()).hexdigest())
    conflict = acquire_source(contract, tmp_path, fetcher=fetch)
    assert conflict.status == "quarantined" and conflict.reason == "cdx_content_digest_mismatch"
    assert raw.read_bytes() == b"different bytes but valid SHA256 sidecar\n"


def test_pinned_cdx_run_receipt_retains_complete_contract_and_verification(tmp_path: Path) -> None:
    payload = b"268.958344 1.668000\n"
    contract = cdx_contract(tmp_path, payload)
    config = tmp_path / "source.toml"
    fields = {k: str(v) for k, v in asdict(contract).items()}
    config.write_text("[assets.a]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in fields.items()))

    def fetch(url: str, path: Path, timeout: float) -> ResponseMetadata:
        path.write_bytes(payload)
        return ResponseMetadata("text/plain", {}, final_url=url)

    result = acquire_source(contract, tmp_path, fetcher=fetch)
    run_path = write_run_evidence(
        root=tmp_path, run_tag="cdx-proof", config_path=config, contracts=(contract,),
        results=(result,), command="test", mode="fixture",
        now_utc=lambda: datetime(2011, 3, 11, 5, 46, tzinfo=UTC),
        git_sha=lambda: "be7f766", working_tree=lambda: "clean",
    )
    recorded = json.loads((run_path / "inputs.json").read_text())
    output = json.loads((run_path / "outputs.json").read_text())[0]
    assert recorded[0]["expected_cdx_sha1"] == contract.expected_cdx_sha1
    assert recorded[0]["cdx_evidence_path"] == contract.cdx_evidence_path
    assert recorded[0]["cdx_evidence_sha256"] == contract.cdx_evidence_sha256
    assert output["verified_cdx_sha1"] == contract.expected_cdx_sha1
    assert output["final_url"] == contract.url


@pytest.mark.parametrize(
    "failure", ["body", "html", "html_type", "final_url", "evidence", "missing_row"]
)
def test_pinned_cdx_mismatch_soft404_and_unproven_capture_never_publish(
    tmp_path: Path, failure: str
) -> None:
    payload = b"<html>Not found</html>" if failure == "html" else b"268.958344 1.668000\n"
    contract = cdx_contract(tmp_path, payload)
    calls: list[str] = []
    if failure == "evidence":
        (tmp_path / "cdx.json").write_text("[]")
    elif failure == "missing_row":
        contract = replace(contract, expected_cdx_sha1="A" * 32)

    def fetch(url: str, path: Path, timeout: float) -> ResponseMetadata:
        calls.append(url)
        path.write_bytes(b"wrong body" if failure == "body" else payload)
        return ResponseMetadata(
            "text/html" if failure == "html_type" else "text/plain", {},
            final_url=(url.replace("20161201000000", "20170101000000")
                       if failure == "final_url" else url),
        )

    result = acquire_source(contract, tmp_path, fetcher=fetch)
    assert result.status == "quarantined" and not result.verified_cdx_sha1
    assert not (tmp_path / contract.local_path).exists()
    assert not list(tmp_path.rglob(".sample.json.*"))
    if failure in {"evidence", "missing_row"}:
        assert calls == []


@pytest.mark.parametrize(
    "failure", ["none", "host", "original_host", "capture_mode", "digest", "evidence_path"]
)
def test_only_exact_ntwc_archive_captures_can_use_blank_prefix_with_cdx_proof(
    tmp_path: Path, failure: str
) -> None:
    contract = cdx_contract(tmp_path, b"source bytes")
    fields = {k: str(v) for k, v in asdict(contract).items()}
    if failure == "host":
        fields["url"] = fields["url"].replace("web.archive.org", "example.test")
    elif failure == "original_host":
        fields["url"] = fields["url"].replace("www.tsunami.gov", "example.test")
    elif failure == "capture_mode":
        fields["url"] = fields["url"].replace("id_/", "/")
    elif failure == "digest":
        fields["expected_cdx_sha1"] = "missing"
    elif failure == "evidence_path":
        fields["cdx_evidence_path"] = "../cdx.json"
    config = tmp_path / "source.toml"
    config.write_text("[assets.a]\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in fields.items()))
    if failure == "none":
        assert load_contracts(config) == (contract,)
    else:
        with pytest.raises(ValueError, match="CDX"):
            load_contracts(config)


def test_acquire_source_quarantines_tampered_bytes_with_a_stale_checksum(tmp_path: Path) -> None:
    contract = sample_contract()
    acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))
    (tmp_path / contract.local_path).write_bytes(b'{"ok":false}')

    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert result.status == "quarantined"
    assert result.reason == "checksum_record_mismatch"


def test_acquire_source_does_not_clobber_a_race_created_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = sample_contract()
    target = tmp_path / contract.local_path
    import pipeline.acquisition as acquisition

    real_link = acquisition.os.link

    def race_link(source: str | Path, destination: str | Path, *args: object) -> None:
        if Path(destination) == target:
            target.write_bytes(b"race-winner")
            raise FileExistsError
        real_link(source, destination, *args)

    monkeypatch.setattr(acquisition.os, "link", race_link)
    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert result.status == "quarantined"
    assert target.read_bytes() == b"race-winner"


def test_acquire_all_isolates_a_malformed_local_parent(tmp_path: Path) -> None:
    bad = sample_contract(source_id="bad", local_path=PurePosixPath("blocked-parent/child.json"))
    good = sample_contract(source_id="good", local_path=PurePosixPath("data/good.json"))
    (tmp_path / "blocked-parent").write_text("not a directory", encoding="utf-8")

    results = acquire_all((bad, good), tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert [result.status for result in results] == ["quarantined", "downloaded"]


def test_acquire_source_quarantines_a_symlink_destination_outside_root(tmp_path: Path) -> None:
    contract = sample_contract(local_path=PurePosixPath("data/sample.json"))
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "data").symlink_to(outside, target_is_directory=True)

    result = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert result.status == "quarantined"
    assert result.reason == "destination_outside_root"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('source_id = "usgs-tohoku-origin-csv"', 'source_id = ""', "blank fields"),
        (
            'expected_prefix = "time,latitude,longitude,depth"',
            'expected_prefix = " "',
            "blank fields",
        ),
        (
            'local_path = "data/raw/usgs/official20110311054624120_30.csv"',
            'local_path = "."',
            "safe relative",
        ),
        (
            'source_id = "ncei-ttt-tohoku-layer17-metadata"',
            'source_id = "usgs-tohoku-origin-csv"',
            "duplicate source_id",
        ),
        (
            'local_path = "data/raw/ncei/ttt_contours_2011_tohoku_layer17.metadata.json"',
            'local_path = "data/raw/usgs/official20110311054624120_30.csv"',
            "namespace collision",
        ),
    ],
)
def test_load_contracts_rejects_invalid_contract_values(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    config = tmp_path / "invalid.toml"
    config.write_text(
        Path("config/tohoku-data-proof.toml").read_text(encoding="utf-8").replace(old, new, 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_contracts(config)


@pytest.mark.parametrize(("code", "attempts"), [(408, 2), (429, 2), (500, 2), (404, 1)])
def test_acquire_source_retries_only_transient_http_errors(
    tmp_path: Path, code: int, attempts: int
) -> None:
    calls = 0

    def fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        nonlocal calls
        del url, timeout_seconds
        calls += 1
        if calls == 1:
            raise HTTPError("https://example.test", code, "error", Message(), None)
        destination.write_bytes(b'{"ok":true}')
        return ResponseMetadata(content_type="application/json", headers={})

    result = acquire_source(sample_contract(), tmp_path, fetcher=fetcher)

    assert calls == attempts
    assert result.status == ("downloaded" if code != 404 else "quarantined")


def test_acquire_all_isolates_a_non_utf8_checksum_record(tmp_path: Path) -> None:
    bad = sample_contract(source_id="bad", local_path=PurePosixPath("data/bad.json"))
    good = sample_contract(source_id="good", local_path=PurePosixPath("data/good.json"))
    acquire_source(bad, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))
    (tmp_path / "data/bad.json.sha256").write_bytes(b"\xff")

    results = acquire_all((bad, good), tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert [result.status for result in results] == ["quarantined", "downloaded"]
    assert results[0].reason == "invalid_checksum_record"


def test_acquire_source_rolls_back_its_sidecar_after_raw_publication_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = sample_contract()
    import pipeline.acquisition as acquisition

    real_link = acquisition.os.link

    def fail_raw_link(source: str | Path, destination: str | Path, *args: object) -> None:
        if Path(destination) == tmp_path / contract.local_path:
            raise OSError("injected raw publication failure")
        real_link(source, destination, *args)

    monkeypatch.setattr(acquisition.os, "link", fail_raw_link)
    failed = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert failed.status == "quarantined"
    assert not (tmp_path / contract.local_path).exists()
    assert not (tmp_path / "data/raw/sample.json.sha256").exists()
    monkeypatch.setattr(acquisition.os, "link", real_link)
    recovered = acquire_source(contract, tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))
    assert recovered.status == "downloaded"


def test_load_contracts_rejects_raw_sidecar_namespace_collision(tmp_path: Path) -> None:
    config = tmp_path / "collision.toml"
    source = Path("config/tohoku-data-proof.toml").read_text(encoding="utf-8")
    config.write_text(
        source.replace(
            'local_path = "data/raw/ncei/ttt_contours_2011_tohoku_layer17.metadata.json"',
            'local_path = "data/raw/usgs/official20110311054624120_30.csv.sha256"',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="namespace collision"):
        load_contracts(config)


def test_acquire_all_retries_and_isolates_incomplete_http_reads(tmp_path: Path) -> None:
    bad = sample_contract(source_id="bad", local_path=PurePosixPath("data/bad.json"))
    good = sample_contract(source_id="good", local_path=PurePosixPath("data/good.json"))
    bad_calls = 0

    def fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        nonlocal bad_calls
        del timeout_seconds
        if destination.name.startswith(".bad.json"):
            bad_calls += 1
            raise IncompleteRead(b"partial", 10)
        destination.write_bytes(b'{"ok":true}')
        return ResponseMetadata(content_type="application/json", headers={})

    results = acquire_all((bad, good), tmp_path, fetcher=fetcher)

    assert bad_calls == 3
    assert [result.status for result in results] == ["quarantined", "downloaded"]


def test_load_contracts_rejects_a_nul_local_path(tmp_path: Path) -> None:
    config = tmp_path / "nul-path.toml"
    source = Path("config/tohoku-data-proof.toml").read_text(encoding="utf-8")
    config.write_text(
        source.replace(
            'local_path = "data/raw/usgs/official20110311054624120_30.csv"',
            'local_path = "data/raw/\\u0000payload.csv"',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="NUL byte"):
        load_contracts(config)


def test_acquire_all_defensively_isolates_a_nul_path(tmp_path: Path) -> None:
    bad = sample_contract(source_id="bad", local_path=PurePosixPath("data/\x00bad.json"))
    good = sample_contract(source_id="good", local_path=PurePosixPath("data/good.json"))

    results = acquire_all((bad, good), tmp_path, fetcher=fixture_fetcher(b'{"ok":true}'))

    assert [result.status for result in results] == ["quarantined", "downloaded"]


def test_request_spacing_includes_retries_but_not_cached_or_blocked_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pipeline.acquisition as acquisition

    clock = [0.0]
    starts: list[float] = []

    def sleep(delay: float) -> None:
        clock[0] += delay

    monkeypatch.setattr(acquisition.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(acquisition.time, "sleep", sleep)
    cached = sample_contract(source_id="a", local_path=PurePosixPath("data/a"))
    blocked = sample_contract(source_id="b", availability="blocked")
    wanted = sample_contract(source_id="c", local_path=PurePosixPath("data/c"))
    acquire_source(cached, tmp_path, fixture_fetcher(b"{}"))

    def fetch(url: str, destination: Path, timeout: float) -> ResponseMetadata:
        starts.append(clock[0])
        clock[0] += 0.25
        if len(starts) == 1:
            raise HTTPError(url, 503, "retry", Message(), None)
        return fixture_fetcher(b"{}")(url, destination, timeout)

    results = acquire_all((wanted, blocked, cached), tmp_path, fetch, min_interval=1)
    assert starts == [0, 1]
    assert [result.status for result in results] == ["cached", "blocked", "downloaded"]


@pytest.mark.parametrize("code", [403, 429, 503])
def test_provider_guard_counts_responses_including_retries_and_retains_skipped_receipts(
    code: int, tmp_path: Path
) -> None:
    calls: list[str] = []
    contracts = [
        sample_contract(source_id=str(i), url=f"https://example.test/{i}",
                        local_path=PurePosixPath(f"data/{i}"))
        for i in range(5)
    ]
    other = sample_contract(source_id="z", url="https://other.test/data",
                            local_path=PurePosixPath("data/z"))

    def fetch(url: str, destination: Path, timeout: float) -> ResponseMetadata:
        calls.append(url)
        if "example.test" in url:
            raise HTTPError(url, code, "provider error", Message(), None)
        return fixture_fetcher(b"{}")(url, destination, timeout)

    results = acquire_all((*contracts, other), tmp_path, fetch,
                          max_consecutive_provider_errors=3)
    assert sum("example.test" in url for url in calls) == 3
    assert len(results) == 6 and results[-1].status == "downloaded"
    assert sum(result.status == "skipped" for result in results) == (2 if code == 403 else 4)
    assert any(f"HTTP {code}" in result.reason for result in results)


def test_successful_response_resets_only_its_provider_error_sequence(tmp_path: Path) -> None:
    contracts = [sample_contract(source_id=str(i), url=f"https://example.test/{i}",
                                 local_path=PurePosixPath(f"data/{i}")) for i in range(5)]

    def fetch(url: str, destination: Path, timeout: float) -> ResponseMetadata:
        if url.endswith("/2"):
            return fixture_fetcher(b"{}")(url, destination, timeout)
        raise HTTPError(url, 403, "denied", Message(), None)

    results = acquire_all(contracts, tmp_path, fetch, max_consecutive_provider_errors=3)
    assert [r.status for r in results] == ["quarantined", "quarantined", "downloaded",
                                           "quarantined", "quarantined"]


def test_contract_limit_preserves_one_ordered_receipt_for_every_contract(tmp_path: Path) -> None:
    contracts = [sample_contract(source_id=str(i), local_path=PurePosixPath(f"data/{i}"))
                 for i in range(4)]
    results = acquire_all(contracts[::-1], tmp_path, fixture_fetcher(b"{}"), max_contracts=2)
    assert [r.source_id for r in results] == ["0", "1", "2", "3"]
    assert [r.status for r in results] == ["downloaded", "downloaded", "skipped", "skipped"]
    assert [r.reason for r in results[2:]] == ["max_contracts", "max_contracts"]


@pytest.mark.parametrize("declared_length", [None, "1000000"])
def test_stream_cap_never_reads_entire_oversized_body_or_publishes_partial_object(
    declared_length: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pipeline.acquisition as acquisition

    reads: list[int] = []

    class Response(io.BytesIO):
        headers = Message()

        def geturl(self) -> str:
            return "https://example.test/sample.json"

        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            reads.append(size)
            return super().read(size)

    response = Response(b"{" + b"x" * 999999)
    response.headers["Content-Type"] = "application/json"
    if declared_length:
        response.headers["Content-Length"] = declared_length
    def open_response(*args: object, **kwargs: object) -> Response:
        return response

    monkeypatch.setattr(acquisition, "urlopen", open_response)
    budget = TransferBudget(max_object_bytes=17)
    result, = acquire_all((sample_contract(),), tmp_path, budget=budget)
    assert result.status == "quarantined" and result.reason == "max_object_bytes"
    assert reads == [17] and budget.received_bytes == result.bytes == 17
    assert not list(tmp_path.rglob("*sample.json*"))


def test_total_stream_budget_counts_failed_attempts_and_skips_remaining_uncached_work(
    tmp_path: Path,
) -> None:
    budget = TransferBudget(max_total_bytes=5)
    contracts = [sample_contract(source_id=str(i), url=f"https://example.test/{i}",
                                 local_path=PurePosixPath(f"data/{i}")) for i in range(4)]
    acquire_source(contracts[3], tmp_path, fixture_fetcher(b"{}"))
    attempts = 0

    def fetch(url: str, destination: Path, timeout: float) -> ResponseMetadata:
        nonlocal attempts
        del timeout
        attempts += 1
        if attempts == 1:
            stream = io.BytesIO(b"{")

            def interrupted(size: int) -> bytes:
                if stream.tell():
                    raise URLError("interrupted after one byte")
                return stream.read(size)

            stream_to_path(interrupted, destination, budget=budget)
        else:
            payload = b"{}" if url.endswith("/0") else b'{"oversized":true}'
            stream_to_path(io.BytesIO(payload).read, destination, budget=budget,
                           content_length=str(len(payload)))
        return ResponseMetadata("application/json", {})

    results = acquire_all(contracts, tmp_path, fetch, budget=budget)
    assert [r.status for r in results] == ["downloaded", "quarantined", "skipped", "cached"]
    assert budget.received_bytes == 5 and attempts == 3
    assert results[1].reason == results[2].reason == "max_total_bytes"
    assert (tmp_path / contracts[0].local_path).read_bytes() == b"{}"
    assert not (tmp_path / contracts[1].local_path).exists()


def test_exact_cap_with_declared_length_is_usable(tmp_path: Path) -> None:
    budget = TransferBudget(max_total_bytes=2, max_object_bytes=2)
    path = tmp_path / "body"
    stream_to_path(io.BytesIO(b"{}").read, path, budget=budget, content_length="2")
    assert path.read_bytes() == b"{}" and budget.received_bytes == 2


def test_declared_incomplete_response_is_not_treated_as_complete(tmp_path: Path) -> None:
    budget = TransferBudget(max_total_bytes=20)
    with pytest.raises(IncompleteRead):
        stream_to_path(io.BytesIO(b"{}").read, tmp_path / "partial", budget=budget,
                       content_length="5")
    assert budget.received_bytes == 2


@pytest.mark.parametrize("option,value", [
    ("min_interval", -1), ("min_interval", float("nan")),
    ("max_contracts", 0), ("max_consecutive_provider_errors", 0),
])
def test_invalid_run_limits_fail_before_fetching(option: str, value: float, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        acquire_all((sample_contract(),), tmp_path, **{option: value})  # type: ignore[arg-type]
    assert not list(tmp_path.iterdir())


def test_cli_budget_does_not_load_ioc_key_for_public_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pipeline.acquisition as acquisition

    class Response(io.BytesIO):
        headers = Message()

        def geturl(self) -> str:
            return "https://example.test/sample.json"

    response = Response(b"{}")
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Length"] = "2"
    def open_response(*args: object, **kwargs: object) -> Response:
        return response

    def load_fixture(_: Path) -> tuple[SourceContract, ...]:
        return (sample_contract(),)

    monkeypatch.setattr(acquisition, "urlopen", open_response)
    monkeypatch.setattr(acquire_script, "load_contracts", load_fixture)
    monkeypatch.setattr(acquire_script, "read_ioc_api_key",
                        lambda: pytest.fail("public request must not read credentials"))
    captured: dict[str, Any] = {}

    def evidence(**kwargs: Any) -> Path:
        captured.update(kwargs)
        return tmp_path / "run"

    monkeypatch.setattr(acquire_script, "write_run_evidence", evidence)
    assert acquire_script.main([
        "--root", str(tmp_path), "--min-interval", "1", "--max-contracts", "200",
        "--max-total-bytes", "20", "--max-object-bytes", "10",
        "--max-consecutive-provider-errors", "3",
    ]) == 0
    assert captured["results"][0].status == "downloaded"
    assert captured["transfer_budget"].received_bytes == 2


def test_run_evidence_distinguishes_new_transfer_budget_from_cached_bytes(tmp_path: Path) -> None:
    config = tmp_path / "contract.toml"
    config.write_text("[assets]\n", encoding="utf-8")
    contract = sample_contract()
    result = acquire_source(contract, tmp_path, fixture_fetcher(b"{}"))
    budget = TransferBudget(max_total_bytes=20, max_object_bytes=10)
    budget.received_bytes = 3
    path = write_run_evidence(
        root=tmp_path, run_tag="budget", config_path=config, contracts=(contract,),
        results=(result,), command="fixture", mode="live", transfer_budget=budget,
        git_sha=lambda: "fixture", working_tree=lambda: "dirty",
    )
    metrics = json.loads((path / "metrics.json").read_text())
    assert metrics["total_bytes"] == 2
    assert metrics["transfer_budget"]["received_response_bytes"] == 3
