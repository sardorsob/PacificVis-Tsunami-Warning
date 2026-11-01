"""Contract capture-index discovery for frozen development archive directories."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_ntwc_batch import write_identical_or_new  # noqa: E402


def main() -> None:
    """Generate bounded metadata requests without opening reserved waveforms."""
    root = Path(__file__).resolve().parents[1]
    events = tomllib.loads((root / "config/ntwc-archive-batch-v2.toml").read_text())
    template = tomllib.loads((root / "config/station-registry-discovery.toml").read_text())
    old = {a["source_id"]: a for a in template["assets"].values()}
    example = old["ia-cdx-us20003k7a"]
    prior = tomllib.loads((root / "config/ia-cdx-dev.toml").read_text())["assets"]
    reusable = {asset["url"]: asset for asset in prior.values()}
    with (root / "artifacts/generated/ntwc-batch/census-v4/links.csv").open() as handle:
        links = list(csv.DictReader(handle))
    assets: list[dict[str, str]] = []
    for event_id, event in sorted(events["events"].items()):
        if event["role"] != "development":
            continue
        source_id = f"ia-cdx-{event_id}"
        key = parse_qs(urlsplit(str(event["archive_url"])).query)["p"][0]
        event_path = f"/previous.events/{key}/"
        if source_id in old:
            assets.append(old[source_id])
            continue
        prefixes = sorted(
            {
                row["resolved_url"].rsplit("/", 1)[0] + "/"
                for row in links
                if row["event_id"] == event_id
                and row["status"] == "safe_archive_link"
                and row["link_code"] not in {"", "unknown"}
                and unquote(urlsplit(row["resolved_url"]).path).startswith(event_path)
            }
        )
        if not prefixes:
            prefixes = [f"https://www.tsunami.gov/previous.events/{key}/Data/"]
        for prefix in prefixes:
            suffix = (
                "" if len(prefixes) == 1 else "-" + hashlib.sha256(prefix.encode()).hexdigest()[:8]
            )
            query = urlencode(
                {
                    "url": prefix + "*",
                    "output": "json",
                    "filter": "statuscode:200",
                    "collapse": "urlkey",
                    "fl": "timestamp,original,digest,length",
                    "limit": "5000",
                }
            )
            asset = {
                **example,
                "source_id": source_id + suffix,
                "url": "https://web.archive.org/cdx/search/cdx?" + query,
                "local_path": f"data/raw/ia/cdx-v2/{event_id}{suffix}.json",
            }
            assets.append(reusable.get(asset["url"], asset))
    lines = [
        'contract_version = "2026-10-31"',
        'terms = "Internet Archive capture metadata; original publisher attribution retained"',
        "",
    ]
    for asset in assets:
        lines.append(f"[assets.{json.dumps(asset['source_id'])}]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in asset.items())
        lines.append("")
    target = root / "config/ia-cdx-dev-scoped.toml"
    write_identical_or_new(target, "\n".join(lines))
    print(json.dumps({"contracts": len(assets), "development_events": 57, "path": str(target)}))


if __name__ == "__main__":
    main()
