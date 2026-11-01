"""Source limits survive retries, crashes and independent acquisition batches."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from pipeline import acquisition_control as control
from pipeline.acquisition import AcquisitionStopped, TransferBudget

URL = "https://www.ngdc.noaa.gov/hazel/record/1"


class Response(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["Content-Length"] = str(len(payload))

    def geturl(self) -> str:
        return URL


def test_provider_stop_and_url_attempts_survive_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fail(url: str, timeout: float) -> Any:
        calls.append(url)
        raise HTTPError(url, 503, "provider failure", Message(), None)

    monkeypatch.setattr(control, "_open", fail)
    state = tmp_path / "state.json"
    for _ in range(3):
        fetch = control.guarded_fetcher(state, frozenset({URL}), TransferBudget(100, 20),
                                       min_interval=0)
        with pytest.raises(HTTPError):
            fetch(URL, tmp_path / "body", 1)
    fetch = control.guarded_fetcher(state, frozenset({URL}), TransferBudget(100, 20),
                                   min_interval=0)
    with pytest.raises(AcquisitionStopped):
        fetch(URL, tmp_path / "body", 1)
    assert len(calls) == 3
    assert json.loads(state.read_text())["requests"] == 3


def test_persisted_bytes_and_exact_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reply(url: str, timeout: float) -> Response:
        return Response(b"12345")

    monkeypatch.setattr(control, "_open", reply)
    state = tmp_path / "state.json"
    fetch = control.guarded_fetcher(state, frozenset({URL}), TransferBudget(8, 5), min_interval=0)
    fetch(URL, tmp_path / "first", 1)
    assert json.loads(state.read_text())["spent_bytes"] == 5
    fetch = control.guarded_fetcher(state, frozenset({URL}), TransferBudget(8, 5), min_interval=0)
    with pytest.raises(AcquisitionStopped):
        fetch(URL, tmp_path / "second", 1)
    assert json.loads(state.read_text())["spent_bytes"] == 8
    with pytest.raises(AcquisitionStopped, match="unapproved"):
        fetch(URL + "/other", tmp_path / "third", 1)


def test_redirect_is_rejected_before_following() -> None:
    handler = control.RejectRedirects()
    from urllib.request import Request

    with pytest.raises(HTTPError):
        handler.redirect_request(Request(URL), None, 302, "redirect", Message(),
                                 "https://unapproved.example/record")


def test_crash_reservation_and_limits_cannot_be_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(Response):
        def read(self, size: int | None = -1) -> bytes:
            raise OSError("lost connection after uncertain read")

    def broken(url: str, timeout: float) -> Broken:
        return Broken(b"12345")

    monkeypatch.setattr(control, "_open", broken)
    path = tmp_path / "state.json"
    fetch = control.guarded_fetcher(path, frozenset({URL}), TransferBudget(20, 5), min_interval=0)
    with pytest.raises(OSError):
        fetch(URL, tmp_path / "body", 1)
    assert json.loads(path.read_text())["spent_bytes"] == 5
    with pytest.raises(ValueError, match="limits"):
        control.guarded_fetcher(path, frozenset({URL}), TransferBudget(200, 50), min_interval=0)


def test_cross_batch_spacing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    waits: list[float] = []
    monkeypatch.setattr(control, "time", lambda: clock[0])
    def wait(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    def reply(url: str, timeout: float) -> Response:
        return Response(b"1")

    monkeypatch.setattr(control, "sleep", wait)
    monkeypatch.setattr(control, "_open", reply)
    path = tmp_path / "state.json"
    for index in range(2):
        fetch = control.guarded_fetcher(path, frozenset({URL}), TransferBudget(20, 5),
                                       min_interval=1)
        fetch(URL, tmp_path / str(index), 1)
    assert waits == [1.0]


def test_crash_before_response_commit_blocks_every_provider_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    path = tmp_path / "state.json"
    urls = frozenset({URL, URL + "/next"})
    save: Callable[[Path, dict[str, Any]], None] = control.save_state

    def crash_after_response(target: Path, state: dict[str, Any]) -> None:
        provider = state["providers"].get("www.ngdc.noaa.gov", {})
        if provider.get("errors") == 3 and not provider.get("in_flight"):
            raise OSError("crash before recording third provider response")
        save(target, state)

    def fail(url: str, timeout: float) -> Any:
        calls.append(url)
        raise HTTPError(url, 503, "provider failure", Message(), None)

    monkeypatch.setattr(control, "_open", fail)
    monkeypatch.setattr(control, "save_state", crash_after_response)
    fetch = control.guarded_fetcher(path, urls, TransferBudget(100, 20), min_interval=0)
    for _ in range(2):
        with pytest.raises(HTTPError):
            fetch(URL, tmp_path / "body", 1)
    with pytest.raises(OSError):
        fetch(URL, tmp_path / "body", 1)
    monkeypatch.setattr(control, "save_state", save)
    fetch = control.guarded_fetcher(path, urls, TransferBudget(100, 20), min_interval=0)
    with pytest.raises(AcquisitionStopped, match="unsettled"):
        fetch(URL + "/next", tmp_path / "body", 1)
    assert calls == [URL] * 3
