"""Persist conservative source budgets for serial, resumable acquisition pilots."""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from http.client import IncompleteRead
from pathlib import Path
from time import sleep, time
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pipeline.acquisition import (
    AcquisitionStopped,
    Fetcher,
    ResponseMetadata,
    TransferBudget,
    stream_to_path,
)


class RejectRedirects(HTTPRedirectHandler):
    """A pilot URL must be separately contracted rather than followed implicitly."""

    def redirect_request(  # type: ignore[override]
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise HTTPError(req.full_url, code, "unapproved redirect", headers, fp)


def _open(url: str, timeout: float) -> Any:
    return build_opener(RejectRedirects()).open(url, timeout=timeout)


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Commit accounting before transport; never leave a partially written ledger."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(state, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path: Path) -> Generator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def guarded_fetcher(
    state: Path,
    allowed_urls: frozenset[str],
    budget: TransferBudget,
    *,
    min_interval: float = 1.0,
    max_requests: int = 60,
    max_provider_errors: int = 3,
    max_attempts_per_url: int = 3,
) -> Fetcher:
    """Create a fetcher whose counters cannot reset between batches or retries.

    A pre-read byte reservation remains spent after an uncertain crash/read
    failure. This may conservatively stop a pilot early; it cannot grant more
    bytes after restarting it. Scientific downloads are serial under a file lock.
    """
    if budget.max_total_bytes is None or budget.max_object_bytes is None:
        raise ValueError("persistent acquisition requires total and object byte limits")
    if not allowed_urls or len(allowed_urls) > 20 or any(
        urlsplit(url).scheme != "https" or not urlsplit(url).hostname or urlsplit(url).username
        or urlsplit(url).password for url in allowed_urls
    ):
        raise ValueError("pilot requires at most20 exact public HTTPS contracts")
    if not math.isfinite(min_interval) or min_interval < 0 or min(
        max_requests, max_provider_errors, max_attempts_per_url
    ) <= 0:
        raise ValueError("invalid persistent limits")
    limits: dict[str, Any] = {
        "allowed_urls": sorted(allowed_urls), "max_total_bytes": budget.max_total_bytes,
        "max_object_bytes": budget.max_object_bytes, "min_interval": min_interval,
        "max_requests": max_requests, "max_provider_errors": max_provider_errors,
        "max_attempts_per_url": max_attempts_per_url,
    }
    with _lock(state):
        if state.exists():
            saved = json.loads(state.read_text(encoding="utf-8"))
            if saved.get("schema_version") != "source_control_v1" or saved["limits"] != limits:
                raise ValueError("persistent source limits changed; cannot reset ledger")
        else:
            save_state(state, {"schema_version": "source_control_v1", "limits": limits,
                          "requests": 0, "spent_bytes": 0, "urls": {}, "providers": {}})

    def fetch(url: str, destination: Path, timeout: float) -> ResponseMetadata:
        if url not in allowed_urls:
            raise AcquisitionStopped("unapproved exact URL")
        with _lock(state):
            saved = cast(dict[str, Any], json.loads(state.read_text(encoding="utf-8")))
            if saved["limits"] != limits:
                raise ValueError("persistent source limits changed during acquisition")
            provider_name = str(urlsplit(url).hostname)
            provider = saved["providers"].setdefault(provider_name, {"errors": 0, "last": None})
            if provider.get("in_flight", False):
                raise AcquisitionStopped("unsettled prior provider request; review required")
            if provider["errors"] >= max_provider_errors:
                raise AcquisitionStopped("persistent provider_error_limit")
            if (saved["requests"] >= max_requests
                    or saved["urls"].get(url, 0) >= max_attempts_per_url):
                raise AcquisitionStopped("persistent request/attempt limit")
            if saved["spent_bytes"] >= limits["max_total_bytes"]:
                raise AcquisitionStopped("persistent max_total_bytes")
            spacing = max(min_interval, 4.0 if provider_name == "web.archive.org" else 0.0)
            if provider["last"] is not None:
                delay = float(provider["last"]) + spacing - time()
                if delay > spacing + 10:
                    raise AcquisitionStopped("clock moved backwards; review source spacing")
                if delay > 0:
                    sleep(delay)
            saved["requests"] += 1
            saved["urls"][url] = saved["urls"].get(url, 0) + 1
            provider["last"] = time()
            provider["in_flight"] = True
            save_state(state, saved)
            response_budget = TransferBudget(limits["max_total_bytes"] - saved["spent_bytes"],
                                             limits["max_object_bytes"])

            def guarded_read(read: Callable[[int], bytes], size: int) -> bytes:
                saved["spent_bytes"] += size
                save_state(state, saved)
                try:
                    chunk = read(size)
                except IncompleteRead as error:
                    budget.received_bytes += len(error.partial)
                    raise
                budget.received_bytes += len(chunk)
                saved["spent_bytes"] -= size - len(chunk)
                save_state(state, saved)
                return chunk

            try:
                with _open(url, timeout) as response:
                    if response.geturl() != url:
                        raise AcquisitionStopped("unapproved final URL", attempted=True)
                    stream_to_path(lambda size: guarded_read(response.read, size), destination,
                                   budget=response_budget,
                                   content_length=response.headers.get("Content-Length"))
                    result = ResponseMetadata(content_type=response.headers.get_content_type(),
                                              headers=dict(response.headers.items()), final_url=url)
            except HTTPError as error:
                provider["errors"] = provider["errors"] + 1 if (
                    error.code in {403, 429} or 500 <= error.code < 600
                ) else 0
                provider["in_flight"] = False
                save_state(state, saved)
                raise
            provider["errors"] = 0
            provider["in_flight"] = False
            save_state(state, saved)
            return result

    return fetch
