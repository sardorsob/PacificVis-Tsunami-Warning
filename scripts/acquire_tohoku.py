"""Acquire the approved Tohoku source contracts and record one portable run result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import (  # noqa: E402
    AcquisitionResult,
    ContractError,
    Fetcher,
    ResponseMetadata,
    SourceContract,
    TransferBudget,
    acquire_all,
    download_url,
    load_contracts,
    stream_to_path,
)
from pipeline.acquisition_control import guarded_fetcher  # noqa: E402

SAFE_RESPONSE_HEADER_NAMES = frozenset(
    {
        "accept-ranges",
        "cache-control",
        "content-length",
        "content-type",
        "date",
        "etag",
        "expires",
        "last-modified",
        "transfer-encoding",
        "vary",
    }
)
IOC_API_HOST = "api.ioc-sealevelmonitoring.org"
IOC_KEYCHAIN_ACCOUNT = "tsunami-warning-times"
IOC_KEYCHAIN_SERVICE = "org.ioc-sealevelmonitoring.api"
IOC_API_KEY_PATTERN = re.compile(r"[0-9a-fA-F]{128}\Z")


class RejectAuthenticatedRedirects(HTTPRedirectHandler):
    """Prevent an authenticated request from forwarding its API key."""

    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        raise HTTPError(newurl, code, msg, headers, fp)  # type: ignore[arg-type]


def read_ioc_api_key() -> str:
    """Read and validate the IOC credential from the project Keychain entry."""
    try:
        api_key = subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-a",
                IOC_KEYCHAIN_ACCOUNT,
                "-s",
                IOC_KEYCHAIN_SERVICE,
                "-w",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("IOC API key is unavailable from macOS Keychain") from error
    if IOC_API_KEY_PATTERN.fullmatch(api_key) is None:
        raise ValueError("IOC API key must contain exactly 128 hexadecimal characters")
    return api_key


def _is_exact_ioc_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == IOC_API_HOST
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
    )


def download_ioc_url(
    url: str, destination: Path, timeout_seconds: float, api_key: str,
    *, budget: TransferBudget | None = None,
) -> ResponseMetadata:
    """Download one IOC API response without exposing or forwarding its key."""
    if not _is_exact_ioc_url(url):
        raise ValueError("authenticated IOC URL must use the exact approved HTTPS host")
    if IOC_API_KEY_PATTERN.fullmatch(api_key) is None:
        raise ValueError("IOC API key must contain exactly 128 hexadecimal characters")
    request = Request(url, headers={"X-API-KEY": api_key, "Accept": "application/json"})
    opener = build_opener(RejectAuthenticatedRedirects())
    with opener.open(request, timeout=timeout_seconds) as response:
        stream_to_path(response.read, destination, budget=budget,
                       content_length=response.headers.get("Content-Length"))
        return ResponseMetadata(
            content_type=response.headers.get_content_type(),
            headers=dict(response.headers.items()),
        )


def ioc_keychain_fetcher(*, budget: TransferBudget | None = None) -> Fetcher:
    """Return a fetcher that adds the Keychain key only for the exact IOC host."""
    api_key: str | None = None

    def fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
        nonlocal api_key
        if not _is_exact_ioc_url(url):
            if budget is not None:
                return download_url(url, destination, timeout_seconds, budget=budget)
            return download_url(url, destination, timeout_seconds)
        if api_key is None:
            api_key = read_ioc_api_key()
        if budget is not None:
            return download_ioc_url(url, destination, timeout_seconds, api_key, budget=budget)
        return download_ioc_url(url, destination, timeout_seconds, api_key)

    return fetcher


def offline_fetcher(url: str, destination: Path, timeout_seconds: float) -> ResponseMetadata:
    """Prevent a CLI offline run from accessing the network."""
    del url, destination, timeout_seconds
    raise URLError("offline mode")


def sanitize_run_tag(run_tag: str) -> str:
    """Return a filesystem-safe lowercase run-tag component."""
    return re.sub(r"[^a-z0-9]+", "-", run_tag.casefold()).strip("-")


def utc_now() -> datetime:
    """Return the current UTC timestamp; separated for deterministic tests."""
    return datetime.now(UTC)


def git_short_sha(root: Path) -> str:
    """Return the checked-out Git short SHA, or an explicit unavailable value."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def working_tree_status(root: Path) -> str:
    """Return code/config tree state while ignoring prior generated run bundles."""
    try:
        output = subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude)artifacts/logs/runs/**",
            ],
            cwd=root,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return "dirty" if output else "clean"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _contract_record(contract: SourceContract) -> dict[str, str]:
    record = {
        "availability": contract.availability,
        "coordinate_order": contract.coordinate_order,
        "crs": contract.crs,
        "expected_content_signature": contract.expected_content_signature,
        "expected_prefix": contract.expected_prefix,
        "format": contract.format,
        "horizontal_datum": contract.horizontal_datum,
        "local_path": contract.local_path.as_posix(),
        "publisher": contract.publisher,
        "reason": contract.reason,
        "source_class": contract.source_class,
        "source_id": contract.source_id,
        "station_metadata": contract.station_metadata,
        "temporal_semantics": contract.temporal_semantics,
        "units": contract.units,
        "url": contract.url,
        "vertical_datum": contract.vertical_datum,
    }
    if contract.expected_cdx_sha1:
        record.update(
            expected_cdx_sha1=contract.expected_cdx_sha1,
            cdx_evidence_path=contract.cdx_evidence_path,
            cdx_evidence_sha256=contract.cdx_evidence_sha256,
        )
    return record


def _safe_response_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: value if name.casefold() in SAFE_RESPONSE_HEADER_NAMES else "[redacted]"
        for name, value in sorted(headers.items())
    }


def _result_record(result: AcquisitionResult) -> dict[str, object]:
    record: dict[str, object] = {
        "bytes": result.bytes,
        "content_type": result.content_type,
        "headers": _safe_response_headers(result.headers),
        "final_url": result.final_url,
        "local_path": result.local_path.as_posix(),
        "reason": result.reason,
        "sha256": result.sha256,
        "source_id": result.source_id,
        "status": result.status,
    }
    if result.verified_cdx_sha1:
        record["verified_cdx_sha1"] = result.verified_cdx_sha1
    return record


def _validate_evidence_ids(
    contracts: Sequence[SourceContract], results: Sequence[AcquisitionResult]
) -> None:
    contract_ids = [contract.source_id for contract in contracts]
    result_ids = [result.source_id for result in results]
    for label, identifiers in (("contract", contract_ids), ("result", result_ids)):
        duplicates = sorted(
            identifier for identifier, count in Counter(identifiers).items() if count > 1
        )
        if duplicates:
            raise ValueError(f"duplicate {label} source_id: {', '.join(duplicates)}")
    if set(contract_ids) != set(result_ids):
        raise ValueError("contract and result source ID sets differ")


def write_run_evidence(
    *,
    root: Path,
    run_tag: str,
    config_path: Path,
    contracts: Sequence[SourceContract],
    results: Sequence[AcquisitionResult],
    command: str,
    mode: str,
    lane: Literal["shared", "paper", "story"] = "shared",
    now_utc: Callable[[], datetime] = utc_now,
    git_sha: Callable[[], str] | None = None,
    working_tree: Callable[[], str] | None = None,
    transfer_budget: TransferBudget | None = None,
) -> Path:
    """Write one immutable portable bundle without copying raw scientific data."""
    if lane not in {"shared", "paper", "story"}:
        raise ValueError(f"unsupported run lane {lane!r}")
    safe_tag = sanitize_run_tag(run_tag)
    if not safe_tag:
        raise ValueError("--run-tag must include at least one letter or number")
    timestamp = now_utc().astimezone(UTC).replace(second=0, microsecond=0)
    revision = git_sha() if git_sha is not None else git_short_sha(root)
    tree_status = working_tree() if working_tree is not None else working_tree_status(root)
    evidence_disposition = {
        "clean": "ready-for-review",
        "dirty": "implementation-under-review",
    }.get(tree_status, "working-tree-unknown")
    run_id = f"{timestamp:%Y-%m-%d__%H%M}__{safe_tag}__{revision}"
    run_path = root / "artifacts/logs/runs" / run_id
    _validate_evidence_ids(contracts, results)
    config_bytes = config_path.read_bytes()
    ordered_contracts = sorted(contracts, key=lambda contract: contract.source_id)
    ordered_results = sorted(results, key=lambda result: result.source_id)
    status_counts = Counter(result.status for result in ordered_results)
    bytes_by_status = {
        status: sum(result.bytes for result in ordered_results if result.status == status)
        for status in sorted(status_counts)
    }
    metrics: dict[str, object] = {
        "bytes_by_status": bytes_by_status,
        "status_counts": dict(sorted(status_counts.items())),
        "total_bytes": sum(result.bytes for result in ordered_results),
        "total_contracts": len(ordered_contracts),
        "total_outcomes": len(ordered_results),
    }
    if transfer_budget is not None:
        metrics["transfer_budget"] = {
            "max_total_bytes": transfer_budget.max_total_bytes,
            "max_object_bytes": transfer_budget.max_object_bytes,
            "received_response_bytes": transfer_budget.received_bytes,
            "scope": "new response bodies including failed attempts; excludes cached objects",
        }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = run_path.parent / f".{run_id}.lock"
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary_path: Path | None = None
    try:
        if run_path.exists():
            raise FileExistsError(run_path)
        temporary_path = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=run_path.parent))
        _write_json(
            temporary_path / "meta.json",
            {
                "command": command,
                "evidence_disposition": evidence_disposition,
                "git_sha": revision,
                "lane": lane,
                "mode": mode,
                "run_id": run_id,
                "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "working_tree": tree_status,
            },
        )
        _write_json(
            temporary_path / "config.json",
            {
                "path": config_path.as_posix(),
                "sha256": hashlib.sha256(config_bytes).hexdigest(),
                "toml": config_bytes.decode("utf-8"),
            },
        )
        _write_json(
            temporary_path / "inputs.json",
            [_contract_record(contract) for contract in ordered_contracts],
        )
        _write_json(
            temporary_path / "outputs.json",
            [_result_record(result) for result in ordered_results],
        )
        _write_json(
            temporary_path / "metrics.json",
            metrics,
        )
        (temporary_path / "notes.md").write_text(
            "# Acquisition run notes\n\n"
            "## Decision\n\n"
            "Only contracts marked `approved` were eligible for retrieval; blocked contracts "
            "were recorded without network access.\n\n"
            "## Limitations\n\n"
            "Source-specific limits, missingness, datum, CRS, and temporal-semantics "
            "constraints remain in `inputs.json`; cached assets have no new response headers.\n",
            encoding="utf-8",
        )
        if run_path.exists():
            raise FileExistsError(run_path)
        os.rename(temporary_path, run_path)
    except BaseException:
        if temporary_path is not None:
            shutil.rmtree(temporary_path, ignore_errors=True)
        raise
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)
    return run_path


def main(argv: list[str] | None = None) -> int:
    """Run the source-independent acquisition command."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/tohoku-data-proof.toml"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-tag", default="acquisition")
    parser.add_argument("--lane", choices=("shared", "paper", "story"), default="shared")
    parser.add_argument("--offline", action="store_true", help="do not access the network")
    parser.add_argument("--control-state", type=Path,
                        help="persist exact-URL pilot budgets; requires both byte limits")
    parser.add_argument("--min-interval", type=float, default=0,
                        help="minimum seconds between request starts, including retries")
    parser.add_argument("--max-contracts", type=int,
                        help="process at most this many contracts; retain skipped receipts")
    parser.add_argument("--max-total-bytes", type=int,
                        help="cap new response-body bytes across all requests and retries")
    parser.add_argument("--max-object-bytes", type=int,
                        help="cap each streamed response body before publication")
    parser.add_argument("--max-consecutive-provider-errors", type=int,
                        help="stop a host after this many consecutive 403/429/5xx responses")
    args = parser.parse_args(effective_argv)
    if not sanitize_run_tag(args.run_tag):
        parser.error("--run-tag must include at least one letter or number")

    try:
        contracts = load_contracts(args.config)
    except ContractError as error:
        parser.error(str(error))

    try:
        budget = TransferBudget(args.max_total_bytes, args.max_object_bytes) if (
            args.max_total_bytes is not None or args.max_object_bytes is not None
        ) else None
        fetcher: Fetcher = offline_fetcher if args.offline else ioc_keychain_fetcher(budget=budget)
        if args.control_state is not None:
            if args.offline or budget is None:
                raise ValueError("persistent source control requires a live, byte-capped pilot")
            state = args.control_state.resolve()
            if not state.is_relative_to(args.root.resolve()):
                raise ValueError("control state must be inside the acquisition root")
            fetcher = guarded_fetcher(state, frozenset(item.url for item in contracts), budget,
                                      min_interval=max(1.0, args.min_interval))
        results = acquire_all(
            contracts, args.root, fetcher=fetcher, min_interval=args.min_interval,
            max_contracts=args.max_contracts,
            max_consecutive_provider_errors=args.max_consecutive_provider_errors, budget=budget,
        )
    except ValueError as error:
        parser.error(str(error))
    command = shlex.join(
        ["uv", "run", "python", "scripts/acquire_tohoku.py", *effective_argv]
    )
    try:
        evidence_path = write_run_evidence(
            root=args.root,
            run_tag=args.run_tag,
            config_path=args.config,
            contracts=contracts,
            results=results,
            command=command,
            mode="offline" if args.offline else "live",
            lane=args.lane,
            transfer_budget=budget,
        )
    except (OSError, ValueError, UnicodeDecodeError) as error:
        parser.error(f"could not write run evidence: {error}")
    usable = sum(result.status in {"downloaded", "cached"} for result in results)
    print(f"Wrote {len(results)} acquisition outcome(s) to {evidence_path}")
    if usable == 0:
        print("No usable approved assets were available.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
