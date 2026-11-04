"""Freeze development metadata split before descriptive outcomes are examined."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.arrival.evidence import Row, read_rows, sha256, write_json, write_rows  # noqa: E402
from analysis.arrival.timing_data_and_descriptive_statistics import FORCED, draw_split  # noqa: E402


def freeze(root: Path) -> None:
    out = root / "artifacts/eda/arrival-timing/frozen-inputs"
    split_path = root / "config/arrival-timing-exploration-confirmation-split.toml"
    if out.exists() or split_path.exists():
        raise FileExistsError("EDA split already frozen")
    config_path = root / "config/ntwc-archive-batch-v2.toml"
    events = tomllib.loads(config_path.read_text())["events"]
    dev = {e for e, v in events.items() if v["role"] == "development"}
    # Whitelist only metadata; never access source_reports or source_pair_values.
    catalog_path = root / "data/processed/multi-event/foundation-v2/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    metadata: list[Row] = []
    for e in catalog["entries"]:
        if e["event_id"] not in dev:
            continue
        m = e["selection_metadata"]
        year = int(events[e["event_id"]]["usgs_time"][:4])
        metadata.append(
            {
                "event_id": e["event_id"],
                "region": events[e["event_id"]]["region"],
                "era": "pre2007" if year < 2007 else "2007-2013" if year < 2014 else "2014plus",
                "longitude": m.get("usgs_longitude", "unknown"),
                "latitude": m.get("usgs_latitude", "unknown"),
                "magnitude": m.get("usgs_mag", "unknown"),
                "depth": m.get("usgs_depth", "unknown"),
                "origin_utc": events[e["event_id"]]["usgs_time"],
                "mechanism": m.get("mechanism_class", "unknown"),
                "sequence_group": events[e["event_id"]].get("sequence_group", "unknown"),
            }
        )
    assert {e["event_id"] for e in metadata} == dev and len(dev) == 57
    split = draw_split(metadata, 20261103)
    assert len(split["exploration"]) == 38 and len(split["confirmation"]) == 19
    out.mkdir(parents=True)
    write_rows(out / "development-event-metadata.csv", metadata)
    text = Path(root / "context/PAPER_EDA_LOG.md").read_text()
    registry = text.split("## Branch registry", 1)[1].split("## Attempt record format", 1)[0]
    (out / "registered-analysis-questions.md").write_text("## Branch registry" + registry)
    split_path.write_text(
        "seed = 20261103\nmetadata_only = true\nforced_exploration = "
        + json.dumps(list(FORCED))
        + "\nexploration = "
        + json.dumps(split["exploration"])
        + "\nconfirmation = "
        + json.dumps(split["confirmation"])
        + "\n"
    )
    paths = [
        out / "development-event-metadata.csv",
        out / "registered-analysis-questions.md",
        split_path,
        config_path,
        root / "config/arrival-timing-eda-settings.toml",
    ]
    base = root / "data/processed/arrival-evidence/foundation-v1"
    names = [
        "T-OBS",
        "T-CAL",
        "NCEI-native-duration",
        "sites",
        "observations",
        "site_links",
        "lineage",
        "lineage_members",
        "opportunities",
        "waveform_coverage",
    ]
    paths.extend(base / f"{name}.csv.gz" for name in names)
    paths.append(base / "manifest.json")
    for p in [
        "artifacts/generated/ntwc-batch/data-completion-v1/design/t-obs.csv",
        "artifacts/generated/ntwc-batch/data-completion-v1/design/t-cal.csv",
        "data/processed/arrival-evidence/source-process-v1/report_availability.csv.gz",
        "data/processed/ncei-arrivals/foundation-v1/observations.csv.gz",
        "data/processed/arrival-evidence/source-process-v1/ncei_definition_candidates.csv.gz",
        "data/processed/arrival-waveforms/foundation-v5/manifest.json",
    ]:
        paths.append(root / p)
    paths.extend(
        p
        for p in (root / "data/processed/arrival-evidence/documentary-v1").iterdir()
        if p.is_file()
    )
    for event in sorted(dev):
        paths.extend(
            root / f"data/processed/arrival-corpus/foundation-v6/{event}/{n}.csv.gz"
            for n in ["arrival_report", "event"]
        )
    # Accepted consolidated tables contain development rows only; metadata files
    # may describe reserved roles but no reserved outcomes are input.
    counts: list[Row] = []
    for target in ["T-OBS", "NCEI-native-duration", "T-CAL"]:
        rows = read_rows(base / f"{target}.csv.gz")
        assert all(r["event_id"] in dev for r in rows)
        for name, ids in split.items():
            own = [r for r in rows if r["event_id"] in ids]
            counts.append(
                {
                    "target": target,
                    "split": name,
                    "rows": str(len(own)),
                    "events": str(len({r["event_id"] for r in own})),
                    "sites": str(len({r["physical_site_id"] for r in own})),
                }
            )
    write_rows(out / "response-record-event-station-counts.csv", counts)
    write_json(
        out / "source-file-checksums.json",
        {
            "schema_version": "paper_eda_inputs_v1",
            "root": str(root),
            "files": [
                {"path": str(p.relative_to(root)), "sha256": sha256(p)} for p in sorted(set(paths))
            ],
            "events": {k: events[k] for k in sorted(dev)},
            "catalog_container_sha256": sha256(catalog_path),
            "catalog_fields": "whitelisted development metadata only; outcome members never used",
            "low_power_t_obs_confirmation": next(
                int(r["events"]) < 5
                for r in counts
                if r["target"] == "T-OBS" and r["split"] == "confirmation"
            ),
        },
    )
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    freeze(Path(".").resolve())
