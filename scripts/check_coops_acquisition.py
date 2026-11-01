"""Check cached CO-OPS bytes, station lineage and UTC grids without picking arrivals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tomllib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.acquisition import SourceContract, load_contracts  # noqa: E402


def check_payload(contract: SourceContract, payload: dict[str, Any]) -> dict[str, object]:
    """Retain missing values and count missing/duplicate timestamps on the requested grid."""
    if "error" in payload:
        raise ValueError(f"provider error is not an observation: {contract.source_id}")
    url = urlsplit(contract.url)
    if contract.source_class == "current station registry":
        station_id = Path(url.path).stem
        stations = cast(list[dict[str, Any]], payload["stations"])
        if len(stations) != 1 or str(stations[0]["id"]) != station_id:
            raise ValueError("registry station mismatch")
        return {"station_id": station_id}
    query = parse_qs(url.query)
    station_id, product = query["station"][0], query["product"][0]
    if query["time_zone"] != ["gmt"] or query["units"] != ["metric"]:
        raise ValueError("unsupported time basis or units")
    if product not in {"predictions", "one_minute_water_level", "water_level"}:
        raise ValueError("unsupported product")
    if product == "predictions" and query.get("interval") != ["1"]:
        raise ValueError("unsupported prediction interval")
    if product != "predictions" and str(payload["metadata"]["id"]) != station_id:
        raise ValueError("observation station mismatch")
    rows = cast(
        list[dict[str, Any]], payload["predictions" if product == "predictions" else "data"]
    )
    start = datetime.strptime(query["begin_date"][0], "%Y%m%d")
    stop = datetime.strptime(query["end_date"][0], "%Y%m%d") + timedelta(days=1)
    cadence = 6 if product == "water_level" else 1
    expected = {
        start + timedelta(minutes=i)
        for i in range(0, int((stop - start).total_seconds() / 60), cadence)
    }
    times = [datetime.strptime(str(row["t"]), "%Y-%m-%d %H:%M") for row in rows]
    if not set(times) <= expected:
        raise ValueError("timestamp outside requested UTC grid")
    invalid = 0
    for row in rows:
        try:
            valid = math.isfinite(float(row["v"]))
        except (ValueError, TypeError):
            valid = False
        invalid += int(not valid)
    return {
        "station_id": station_id,
        "product": product,
        "rows": len(rows),
        "expected_timestamps": len(expected),
        "missing_timestamps": len(expected - set(times)),
        "duplicate_timestamps": len(times) - len(set(times)),
        "blank_or_nonfinite_values": invalid,
        "quality_codes": dict(Counter(str(row.get("q", "not_provided")) for row in rows)),
        "cadence_minutes": cadence,
    }


def verify(config: Path, receipts: Path, events_config: Path, root: Path) -> dict[str, object]:
    """Verify exact contract/receipt correspondence and frozen development-event windows."""
    contracts = load_contracts(config)
    outputs = cast(list[dict[str, Any]], json.loads(receipts.read_text()))
    by_id = {str(row["source_id"]): row for row in outputs}
    if len(by_id) != len(outputs) or set(by_id) != {c.source_id for c in contracts}:
        raise ValueError("receipt/contract IDs differ or are duplicated")
    events = cast(dict[str, dict[str, Any]], tomllib.loads(events_config.read_text())["events"])
    results: list[dict[str, object]] = []
    for contract in contracts:
        receipt = by_id[contract.source_id]
        if str(contract.local_path) != receipt["local_path"]:
            raise ValueError("receipt path mismatch")
        path = root / contract.local_path
        if contract.source_class != "current station registry":
            event = events[path.parent.name]
            if event["role"] != "development":
                raise ValueError("waveform contract includes a reserved event")
            day = datetime.fromisoformat(str(event["usgs_time"])).date()
            query = parse_qs(urlsplit(contract.url).query)
            if query["begin_date"] != [(day - timedelta(days=1)).strftime("%Y%m%d")] or query[
                "end_date"
            ] != [(day + timedelta(days=2)).strftime("%Y%m%d")]:
                raise ValueError("window differs from frozen event-origin rule")
        entry: dict[str, object] = {
            "source_id": contract.source_id,
            "status": receipt["status"],
            "reason": receipt["reason"],
            "source_class": contract.source_class,
        }
        if receipt["status"] in {"downloaded", "cached"}:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            sidecar = path.with_name(path.name + ".sha256").read_text().strip()
            if digest != sidecar or digest != receipt["sha256"] or len(raw) != receipt["bytes"]:
                raise ValueError(f"checksum/size mismatch: {contract.source_id}")
            decoded: object = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("CO-OPS response must be a JSON object")
            payload = cast(dict[str, Any], decoded)
            if "error" in payload:
                if any(key in payload for key in ("data", "predictions", "stations")):
                    raise ValueError("provider response mixes an error and data")
                # A valid cached API error documents availability, not observations.
                entry.update(payload_status="provider_error", provider_error=payload["error"])
            else:
                entry.update(check_payload(contract, payload))
        elif path.exists():
            raise ValueError("failed receipt unexpectedly has a cached target")
        results.append(entry)
    return {
        "method": "Verify digests/JSON/station ID/time window and timestamp grid; "
        "retain blanks/quality flags; no onset or value correction",
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.config, args.receipts, args.events, args.root)
    if args.output.exists():
        if json.loads(args.output.read_text()) != result:
            raise ValueError("refusing to replace a different audit")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    count = len(cast(list[dict[str, object]], result["results"]))
    print(json.dumps({"contracts_verified": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
