"""Acquire approved source contracts into an immutable local raw-data cache."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import tempfile
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.client import HTTPException, IncompleteRead
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


@dataclass(frozen=True, slots=True)
class SourceContract:
    """Source identity and acquisition requirements from the TOML contract."""

    source_id: str
    source_class: str
    availability: str
    url: str
    local_path: PurePosixPath
    format: str
    publisher: str
    expected_content_signature: str
    expected_prefix: str
    units: str
    crs: str
    horizontal_datum: str
    vertical_datum: str
    coordinate_order: str
    temporal_semantics: str
    station_metadata: str
    reason: str
    expected_cdx_sha1: str = ""
    cdx_evidence_path: str = ""
    cdx_evidence_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ResponseMetadata:
    """Response metadata retained by callers that write run evidence."""

    content_type: str
    headers: dict[str, str]
    final_url: str = "not-recorded"


def _empty_headers() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """Outcome for exactly one source contract."""

    source_id: str
    status: str
    local_path: PurePosixPath
    bytes: int
    sha256: str
    reason: str
    content_type: str = "not-downloaded"
    headers: dict[str, str] = field(default_factory=_empty_headers)
    final_url: str = "not-recorded"
    verified_cdx_sha1: str = ""


class RejectArchiveCaptureRedirects(HTTPRedirectHandler):
    """An exact raw capture must not be substituted through a redirect."""

    def redirect_request(  # type: ignore[override]
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> Request | None:
        raise ValueError("exact_archive_capture_redirect_rejected")


Fetcher = Callable[[str, Path, float], ResponseMetadata]
MAX_FETCH_ATTEMPTS = 3
PREFIX_WINDOW_BYTES = 64 * 1024
CONTRACT_FIELDS: tuple[str, ...] = (
    "source_id",
    "source_class",
    "availability",
    "url",
    "local_path",
    "format",
    "publisher",
    "expected_content_signature",
    "expected_prefix",
    "units",
    "crs",
    "horizontal_datum",
    "vertical_datum",
    "coordinate_order",
    "temporal_semantics",
    "station_metadata",
    "reason",
)


class ContractError(ValueError):
    """Raised when a source-contract TOML file violates the acquisition contract."""


def _cdx_capture_identity(url: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"https://web\.archive\.org/web/(\d{14})id_/(https?://www\.tsunami\.gov/previous\.events/[^?#]+)",
        url,
    )
    if match is None:
        raise ContractError("CDX identity requires an exact IA capture of the NTWC archive")
    original = match[2]
    decoded = unquote(urlparse(original).path)
    if ".." in decoded.split("/") or "\\" in decoded or "%" in decoded or any(
        ord(c) < 32 for c in decoded
    ):
        raise ContractError("unsafe CDX original URL")
    return match[1], original


def _validate_cdx_fields(digest: str, evidence_path: str, evidence_sha: str, url: str) -> None:
    if not any((digest, evidence_path, evidence_sha)):
        return
    path = PurePosixPath(evidence_path)
    if (
        not re.fullmatch(r"[A-Z2-7]{32}", digest)
        or not re.fullmatch(r"[a-f0-9]{64}", evidence_sha)
        or not evidence_path
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or "\\" in evidence_path
        or "\x00" in evidence_path
    ):
        raise ContractError("invalid pinned CDX digest/evidence fields")
    _cdx_capture_identity(url)


def verify_cdx_evidence(contract: SourceContract, root: Path) -> None:
    """Verify the pinned local CDX row before acquiring or consuming its exact capture."""
    _validate_cdx_fields(
        contract.expected_cdx_sha1, contract.cdx_evidence_path,
        contract.cdx_evidence_sha256, contract.url,
    )
    if not contract.expected_cdx_sha1:
        return
    path = root / contract.cdx_evidence_path
    sidecar = _checksum_path(path)
    if not all(p.resolve().is_relative_to(root.resolve()) for p in (path, sidecar)):
        raise ContractError("CDX evidence path escapes root")
    raw = path.read_bytes()
    if (hashlib.sha256(raw).hexdigest() != contract.cdx_evidence_sha256
            or sidecar.read_text().strip() != contract.cdx_evidence_sha256):
        raise ContractError("CDX evidence checksum mismatch")
    payload: object = json.loads(raw)
    if not isinstance(payload, list):
        raise ContractError("unknown CDX evidence schema")
    objects = cast(list[object], payload)
    if not objects or any(
        not isinstance(row, list)
        or any(not isinstance(cell, str) for cell in cast(list[object], row))
        for row in objects
    ):
        raise ContractError("unknown CDX evidence schema")
    rows = cast(list[list[str]], objects)
    if (not {"timestamp", "original", "digest"} <= set(rows[0])
            or len(set(rows[0])) != len(rows[0])
            or any(len(row) != len(rows[0]) for row in rows[1:])):
        raise ContractError("unknown CDX evidence schema")
    timestamp, original = _cdx_capture_identity(contract.url)
    for values in rows[1:]:
        row = dict(zip(rows[0], values, strict=True))
        if (row.get("timestamp") == timestamp and row.get("original") == original
                and row.get("digest") == contract.expected_cdx_sha1
                and row.get("statuscode", "200") == "200"):
            return
    raise ContractError("exact capture/digest absent from CDX evidence")


class AcquisitionStopped(ValueError):
    """A configured run guard stopped a request before publication."""

    def __init__(self, reason: str, *, attempted: bool = False, size: int = 0) -> None:
        super().__init__(reason)
        self.attempted = attempted
        self.size = size


@dataclass(slots=True)
class TransferBudget:
    """Bound new response-body bytes, including failed attempts, but not cached bytes."""

    max_total_bytes: int | None = None
    max_object_bytes: int | None = None
    received_bytes: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        for value in (self.max_total_bytes, self.max_object_bytes):
            if value is not None and value <= 0:
                raise ValueError("byte limits must be positive")

    def remaining(self, object_bytes: int) -> tuple[int, str]:
        """Return a bounded read size and the first exhausted budget's reason."""
        limits = [(1024 * 1024, "")]
        if self.max_total_bytes is not None:
            limits.append((self.max_total_bytes - self.received_bytes, "max_total_bytes"))
        if self.max_object_bytes is not None:
            limits.append((self.max_object_bytes - object_bytes, "max_object_bytes"))
        return min(limits, key=lambda item: item[0])


def stream_to_path(
    read: Callable[[int], bytes],
    destination: Path,
    *,
    budget: TransferBudget | None = None,
    content_length: str | None = None,
) -> None:
    """Stream without exceeding a cap; reject capped unknown-length bodies conservatively.

    A declared Content-Length permits an exactly-at-limit complete body. Without
    that declaration, reaching the cap is quarantined rather than reading an
    extra byte to probe EOF. No partial response is published by acquire_source.
    """
    expected = int(content_length) if content_length and content_length.isdecimal() else None
    object_bytes = 0
    with destination.open("wb") as target:
        while True:
            size, reason = budget.remaining(object_bytes) if budget else (1024 * 1024, "")
            if size <= 0:
                if expected is not None and object_bytes == expected:
                    return
                raise AcquisitionStopped(reason, attempted=True, size=object_bytes)
            try:
                chunk = read(size)
            except IncompleteRead as error:
                if budget:
                    budget.received_bytes += len(error.partial)
                raise
            if not chunk:
                if expected is not None and object_bytes != expected:
                    raise IncompleteRead(b"", expected - object_bytes)
                return
            object_bytes += len(chunk)
            if budget:
                budget.received_bytes += len(chunk)
            if len(chunk) > size:
                raise AcquisitionStopped("response_exceeded_requested_read", attempted=True,
                                         size=object_bytes)
            target.write(chunk)


def load_contracts(path: Path) -> tuple[SourceContract, ...]:
    """Load and validate every exact source contract from a TOML file."""
    try:
        document = cast(dict[str, object], tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ContractError(f"could not read {path}: {error}") from error

    raw_assets = document.get("assets")
    if not isinstance(raw_assets, dict):
        raise ContractError("missing [assets] tables")
    assets = cast(dict[str, object], raw_assets)
    contracts: list[SourceContract] = []
    source_ids: set[str] = set()
    approved_paths: list[PurePosixPath] = []
    for name, raw_values in assets.items():
        if not isinstance(raw_values, dict):
            raise ContractError(f"asset {name!r} must be a TOML table")
        asset = cast(dict[str, object], raw_values)
        values: dict[str, object | None] = {
            field: asset.get(field) for field in CONTRACT_FIELDS
        }
        missing = [field for field, value in values.items() if not isinstance(value, str)]
        if missing:
            raise ContractError(f"asset {name!r} missing string fields: {', '.join(missing)}")
        strings = {field: value for field, value in values.items() if isinstance(value, str)}
        optional = {
            key: asset.get(key, "")
            for key in ("expected_cdx_sha1", "cdx_evidence_path", "cdx_evidence_sha256")
        }
        if not all(isinstance(value, str) for value in optional.values()):
            raise ContractError("pinned CDX fields must be strings")
        cdx = cast(dict[str, str], optional)
        _validate_cdx_fields(cdx["expected_cdx_sha1"], cdx["cdx_evidence_path"],
                             cdx["cdx_evidence_sha256"], strings["url"])
        blank = [field for field, value in strings.items() if not value.strip()
                 and not (field == "expected_prefix" and cdx["expected_cdx_sha1"])]
        if blank:
            raise ContractError(f"asset {name!r} has blank fields: {', '.join(blank)}")
        try:
            _prefix_bytes(strings["expected_prefix"])
        except ValueError as error:
            raise ContractError(f"asset {name!r} has invalid expected_prefix") from error
        availability = strings["availability"]
        if availability not in {"approved", "blocked"}:
            raise ContractError(f"asset {name!r} has unsupported availability {availability!r}")
        local_path_value = strings["local_path"]
        local_path = PurePosixPath(local_path_value)
        if "\x00" in local_path_value:
            raise ContractError(f"asset {name!r} local_path contains a NUL byte")
        if availability == "blocked" and local_path_value != "not-downloaded":
            raise ContractError(f"blocked asset {name!r} must use local_path 'not-downloaded'")
        if availability == "approved" and (
            local_path_value == "not-downloaded"
            or local_path.is_absolute()
            or local_path == PurePosixPath(".")
            or ".." in local_path.parts
            or "\\" in local_path_value
        ):
            raise ContractError(f"approved asset {name!r} needs a safe relative local_path")
        if strings["source_id"] in source_ids:
            raise ContractError(f"duplicate source_id {strings['source_id']!r}")
        source_ids.add(strings["source_id"])
        if availability == "approved":
            if not strings["expected_prefix"].strip() and not cdx["expected_cdx_sha1"]:
                raise ContractError(f"approved asset {name!r} needs a nonblank expected_prefix")
            for candidate in (local_path, local_path.with_name(f"{local_path.name}.sha256")):
                for existing in approved_paths:
                    if (
                        candidate == existing
                        or candidate in existing.parents
                        or existing in candidate.parents
                    ):
                        raise ContractError(
                            f"approved path namespace collision {candidate.as_posix()!r}"
                        )
            approved_paths.extend((local_path, local_path.with_name(f"{local_path.name}.sha256")))
        parsed_url = urlparse(strings["url"])
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ContractError(f"asset {name!r} needs an absolute HTTPS url")
        contracts.append(
            SourceContract(
                source_id=strings["source_id"],
                source_class=strings["source_class"],
                availability=availability,
                url=strings["url"],
                local_path=local_path,
                format=strings["format"],
                publisher=strings["publisher"],
                expected_content_signature=strings["expected_content_signature"],
                expected_prefix=strings["expected_prefix"],
                units=strings["units"],
                crs=strings["crs"],
                horizontal_datum=strings["horizontal_datum"],
                vertical_datum=strings["vertical_datum"],
                coordinate_order=strings["coordinate_order"],
                temporal_semantics=strings["temporal_semantics"],
                station_metadata=strings["station_metadata"],
                reason=strings["reason"],
                **cdx,
            )
        )
    return tuple(sorted(contracts, key=lambda contract: contract.source_id))


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _prefix_bytes(prefix: str) -> bytes:
    if prefix.startswith("hex:"):
        encoded = prefix.removeprefix("hex:")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", encoded):
            raise ValueError("invalid binary expected_prefix")
        return bytes.fromhex(encoded)
    return prefix.encode("utf-8")


def _matches_prefix(path: Path, expected_prefix: str) -> bool:
    with path.open("rb") as source:
        leading = source.read(PREFIX_WINDOW_BYTES)
    return (leading if expected_prefix.startswith("hex:") else leading.lstrip()).startswith(
        _prefix_bytes(expected_prefix)
    )


def _content_error(path: Path, contract: SourceContract) -> str | None:
    if contract.expected_cdx_sha1:
        digest = hashlib.sha1(usedforsecurity=False)
        with path.open("rb") as source:
            leading = source.read(PREFIX_WINDOW_BYTES)
            if re.search(rb"<!doctype\s+html|<html(?:\s|>)", leading, flags=re.IGNORECASE):
                return "html_response_instead_of_ntwc_record"
            digest.update(leading)
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if base64.b32encode(digest.digest()).decode() != contract.expected_cdx_sha1:
            return "cdx_content_digest_mismatch"
    if contract.expected_prefix and not _matches_prefix(path, contract.expected_prefix):
        return "content_signature_mismatch"
    return None


def _checksum_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.name}.sha256")


def _matches_checksum_record(destination: Path, digest: str) -> bool:
    recorded = _checksum_path(destination).read_text(encoding="utf-8").strip()
    return recorded == digest


def _unlink_if_owned(path: Path, temporary_path: Path | None) -> None:
    if temporary_path is not None:
        try:
            if path.exists() and path.samefile(temporary_path):
                path.unlink()
        except OSError:
            pass


def _result(
    contract: SourceContract,
    status: str,
    size: int,
    digest: str,
    reason: str,
    response_metadata: ResponseMetadata | None = None,
) -> AcquisitionResult:
    return AcquisitionResult(
        source_id=contract.source_id,
        status=status,
        local_path=contract.local_path,
        bytes=size,
        sha256=digest,
        reason=reason,
        content_type=(
            response_metadata.content_type if response_metadata is not None else "not-downloaded"
        ),
        headers=response_metadata.headers if response_metadata is not None else {},
        final_url=response_metadata.final_url if response_metadata is not None else "not-recorded",
        verified_cdx_sha1=contract.expected_cdx_sha1 if status in {"downloaded", "cached"} else "",
    )


def download_url(
    url: str, destination: Path, timeout_seconds: float, *, budget: TransferBudget | None = None
) -> ResponseMetadata:
    """Stream one HTTPS response to a caller-owned temporary destination."""
    parsed = urlparse(url)
    exact_capture = parsed.hostname == "web.archive.org" and re.match(
        r"/web/\d{14}id_/", parsed.path
    )
    opener = build_opener(RejectArchiveCaptureRedirects()).open if exact_capture else urlopen
    with opener(url, timeout=timeout_seconds) as response:  # noqa: S310 - contracts are HTTPS.
        final_url = response.geturl()
        if exact_capture and final_url != url:
            raise ValueError("exact_archive_capture_final_url_mismatch")
        stream_to_path(response.read, destination, budget=budget,
                       content_length=response.headers.get("Content-Length"))
        return ResponseMetadata(
            content_type=response.headers.get_content_type(),
            headers=dict(response.headers.items()),
            final_url=final_url,
        )


def _fetch_with_retries(
    fetcher: Fetcher, url: str, destination: Path, timeout_seconds: float
) -> ResponseMetadata:
    for attempt in range(MAX_FETCH_ATTEMPTS):
        try:
            return fetcher(url, destination, timeout_seconds)
        except HTTPError as error:
            if error.code not in {408, 429} and not 500 <= error.code < 600:
                raise
            if attempt == MAX_FETCH_ATTEMPTS - 1:
                raise
        except (TimeoutError, URLError):
            if attempt == MAX_FETCH_ATTEMPTS - 1:
                raise
        except HTTPException:
            if attempt == MAX_FETCH_ATTEMPTS - 1:
                raise
    raise AssertionError("bounded fetch loop must return or raise")


def acquire_source(
    contract: SourceContract,
    root: Path,
    fetcher: Fetcher = download_url,
    timeout_seconds: float = 30.0,
) -> AcquisitionResult:
    """Acquire one approved contract without replacing a conflicting raw file."""
    if contract.availability == "blocked":
        return _result(contract, "blocked", 0, "not-downloaded", contract.reason)
    temporary_path: Path | None = None
    checksum_temporary_path: Path | None = None
    destination: Path | None = None
    published_sidecar = False
    published_raw = False
    try:
        root_resolved = root.resolve()
        verify_cdx_evidence(contract, root_resolved)
        destination = root_resolved / contract.local_path
        if not destination.resolve(strict=False).is_relative_to(root_resolved):
            return _result(contract, "quarantined", 0, "not-downloaded", "destination_outside_root")
        if destination.exists():
            size, digest = _sha256(destination)
            if not _checksum_path(destination).exists():
                return _result(contract, "quarantined", size, digest, "missing_checksum_record")
            if not _matches_checksum_record(destination, digest):
                return _result(contract, "quarantined", size, digest, "checksum_record_mismatch")
            content_error = _content_error(destination, contract)
            if size and content_error is None:
                return _result(contract, "cached", size, digest, "not applicable")
            return _result(contract, "quarantined", size, digest,
                           content_error if contract.expected_cdx_sha1 and content_error
                           else "existing_checksum_conflict")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        response_metadata = _fetch_with_retries(
            fetcher, contract.url, temporary_path, timeout_seconds
        )
        if contract.expected_cdx_sha1 and response_metadata.final_url != contract.url:
            raise ValueError("exact_archive_capture_final_url_mismatch")
        size, digest = _sha256(temporary_path)
        if not size:
            return _result(contract, "quarantined", 0, "not-downloaded", "empty_response")
        content_error = _content_error(temporary_path, contract)
        if contract.expected_cdx_sha1 and "text/html" in response_metadata.content_type.lower():
            content_error = "html_response_instead_of_ntwc_record"
        if content_error:
            return _result(
                contract, "quarantined", size, digest, content_error,
                response_metadata if contract.expected_cdx_sha1 else None,
            )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{destination.name}.sha256.",
            dir=destination.parent, delete=False
        ) as checksum_temporary:
            checksum_temporary.write(f"{digest}\n")
            checksum_temporary_path = Path(checksum_temporary.name)
        checksum_path = _checksum_path(destination)
        os.link(checksum_temporary_path, checksum_path)
        published_sidecar = True
        os.link(temporary_path, destination)
        published_raw = True
        return _result(
            contract,
            "downloaded",
            size,
            digest,
            "not applicable",
            response_metadata,
        )
    except AcquisitionStopped as error:
        return _result(contract, "quarantined" if error.attempted else "skipped",
                       error.size, "not-downloaded", str(error))
    except UnicodeDecodeError:
        return _result(contract, "quarantined", 0, "not-downloaded", "invalid_checksum_record")
    except (HTTPError, HTTPException, OSError, URLError, ValueError) as error:
        return _result(
            contract, "quarantined", 0, "not-downloaded", f"local_or_download_error: {error}"
        )
    finally:
        if published_sidecar and not published_raw and destination is not None:
            _unlink_if_owned(_checksum_path(destination), checksum_temporary_path)
        for path in (temporary_path, checksum_temporary_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def acquire_all(
    contracts: Sequence[SourceContract],
    root: Path,
    fetcher: Fetcher = download_url,
    *,
    min_interval: float = 0,
    max_contracts: int | None = None,
    max_consecutive_provider_errors: int | None = None,
    budget: TransferBudget | None = None,
) -> tuple[AcquisitionResult, ...]:
    """Acquire in source-ID order, retaining explicit outcomes when optional guards stop work.

    Custom fetchers must pass the same budget to stream_to_path; the built-in
    public downloader does so automatically. Retries count as provider requests.
    """
    if not math.isfinite(min_interval) or min_interval < 0:
        raise ValueError("min_interval must be finite and nonnegative")
    for limit in (max_contracts, max_consecutive_provider_errors):
        if limit is not None and limit <= 0:
            raise ValueError("contract and provider-error limits must be positive")
    last_request: float | None = None
    errors: dict[str, int] = {}
    stopped: set[str] = set()

    def controlled_fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        nonlocal last_request
        provider = urlparse(url).hostname or "unknown"
        if provider in stopped:
            raise AcquisitionStopped(f"provider_error_limit: {provider}")
        if budget and budget.max_total_bytes is not None:
            if budget.received_bytes >= budget.max_total_bytes:
                raise AcquisitionStopped("max_total_bytes")
        if min_interval and last_request is not None:
            time.sleep(max(0, min_interval - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        try:
            if fetcher is download_url and budget is not None:
                result = download_url(url, destination, timeout_seconds, budget=budget)
            else:
                result = fetcher(url, destination, timeout_seconds)
        except HTTPError as error:
            if error.code in {403, 429} or 500 <= error.code < 600:
                errors[provider] = errors.get(provider, 0) + 1
                if (max_consecutive_provider_errors is not None
                        and errors[provider] >= max_consecutive_provider_errors):
                    stopped.add(provider)
                    raise AcquisitionStopped(
                        f"provider_error_limit: {provider}; HTTP {error.code}", attempted=True
                    ) from error
            else:
                errors[provider] = 0
            raise
        errors[provider] = 0
        return result

    results: list[AcquisitionResult] = []
    for index, contract in enumerate(sorted(contracts, key=lambda item: item.source_id)):
        if max_contracts is not None and index >= max_contracts:
            results.append(_result(contract, "skipped", 0, "not-downloaded", "max_contracts"))
        else:
            results.append(acquire_source(contract, root, controlled_fetcher))
    return tuple(results)
