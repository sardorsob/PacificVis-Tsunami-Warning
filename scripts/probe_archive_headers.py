"""Read bounded prefixes of approved exact Internet Archive station captures."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.acquisition import RejectArchiveCaptureRedirects  # noqa: E402

open_capture = build_opener(RejectArchiveCaptureRedirects()).open


def main() -> None:
    """Record every attempt, never request full station files or change headers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    requests = json.loads(args.input.read_text(encoding="utf-8"))["requests"]
    if len(requests) > 200:
        raise ValueError("at most 200 prefix requests per tranche")
    for item in requests:
        if item["role"] != "development" or not re.fullmatch(
            r"https://web\.archive\.org/web/\d{14}id_/https?://www\.tsunami\.gov/previous\.events/.+",
            item["capture_url"],
        ):
            raise ValueError("request outside approved source and development scope")
    results: list[dict[str, Any]] = []
    errors = 0
    if args.output.exists():
        old = json.loads(args.output.read_text(encoding="utf-8"))
        if old["suggestions_sha256"] != digest:
            raise ValueError("cannot resume changed inputs")
        results = old["requests"]
        errors = old.get("consecutive_provider_errors", 0)
    completed = {item["capture_url"] for item in results}
    last_start = 0.0
    for item in requests:
        if item["capture_url"] in completed:
            continue
        result = {**item, "retrieved_at": datetime.now(UTC).isoformat()}
        if errors >= 3:
            result.update(probe_status="skipped_provider_guard", bytes_read=0)
        else:
            time.sleep(max(0.0, 4.0 - (time.monotonic() - last_start)))
            last_start = time.monotonic()
            try:
                with open_capture(item["capture_url"], timeout=30) as response:
                    result["response_url"] = response.geturl()
                    if response.geturl() != item["capture_url"]:
                        raise ValueError("capture response redirected; identity review required")
                    prefix = response.read(256)
                result.update(
                    bytes_read=len(prefix),
                    prefix_base64=base64.b64encode(prefix).decode(),
                    prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                )
                text = prefix.decode("utf-8")
                result["prefix_text"] = text
                token = text.split()[0]
                if text.lstrip().startswith("<") or len(text.splitlines()) < 4:
                    raise ValueError("not a station-record prefix")
                result.update(probe_status="success", expected_prefix=token)
                errors = 0
            except (HTTPError, URLError, ValueError, TimeoutError, OSError, IndexError) as error:
                result.update(probe_status="failed", reason=str(error))
                if isinstance(error, HTTPError):
                    result["http_status"] = error.code
                    errors = errors + 1 if error.code in {403, 429} or error.code >= 500 else 0
                elif isinstance(error, (URLError, TimeoutError, OSError)):
                    errors += 1
                else:
                    errors = 0
        results.append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "suggestions_sha256": digest,
                    "read_bytes_per_object": 256,
                    "consecutive_provider_errors": errors,
                    "requests": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{len(results)}/{len(requests)} {result['probe_status']}", flush=True)


if __name__ == "__main__":
    main()
