"""Bounded header discovery must preserve capture identity and provider guards."""

import io
import json
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from scripts import probe_archive_headers as probe


def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int = 1) -> Path:
    source, output = tmp_path / "input.json", tmp_path / "output.json"
    rows = [
        {
            "role": "development",
            "capture_url": (
                f"https://web.archive.org/web/20161221151535id_/http://www.tsunami.gov/previous.events/e/s{i}"
            ),
        }
        for i in range(count)
    ]
    source.write_text(json.dumps({"requests": rows}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["probe", "--input", str(source), "--output", str(output)])

    def no_sleep(seconds: float) -> None:
        assert seconds >= 0

    monkeypatch.setattr(probe.time, "sleep", no_sleep)
    return output


def test_provider_guard_retains_attempts_and_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = setup(monkeypatch, tmp_path, 4)
    calls: list[str] = []

    def fail(url: str, **_: Any) -> None:
        calls.append(url)
        raise HTTPError(url, 503, "unavailable", Message(), None)

    monkeypatch.setattr(probe, "open_capture", fail)
    probe.main()
    result = json.loads(output.read_text())
    assert len(calls) == 3
    assert result["consecutive_provider_errors"] == 3
    assert result["requests"][-1]["probe_status"] == "skipped_provider_guard"
    probe.main()
    assert len(calls) == 3


@pytest.mark.parametrize("redirect", [False, True])
def test_bounded_prefix_and_redirect_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    redirect: bool,
) -> None:
    output = setup(monkeypatch, tmp_path)
    reads: list[int] = []

    class Response(io.BytesIO):
        url: str

        def geturl(self) -> str:
            return self.url + ("changed" if redirect else "")

        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            reads.append(size)
            return super().read(size)

    def fetch(url: str, **_: Any) -> Response:
        response = Response(b"station\nline2\nline3\nline4\n" + b"x" * 1000)
        response.url = url
        return response

    monkeypatch.setattr(probe, "open_capture", fetch)
    probe.main()
    result = json.loads(output.read_text())["requests"][0]
    assert reads == ([] if redirect else [256])
    assert result["probe_status"] == ("failed" if redirect else "success")
