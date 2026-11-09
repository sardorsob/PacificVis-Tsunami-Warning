"""Synthetic reference closures and literal population alignment; no real outcomes."""

# pyright: basic
import json

import numpy as np
import pytest
import xarray as xr

from analysis.arrival import model_sensitivity_references as refs
from analysis.arrival.evidence import sha256, write_json
from analysis.arrival.model_data import lane_arrays


def fixture(root, *, wrong_job=False, wrong_membership=False, wrong_raw_claim=False, draws=2000):
    lanes = {}
    for target, count, events in [
        ("NCEI-native-duration", 1064, 33),
        ("T-OBS", 236, 14),
        ("T-CAL", 156, 13),
    ]:
        rows, sequences = [], {}
        for i in range(count):
            event = f"event-{i % events}"
            sequence = f"seq-{event}"
            if target == "NCEI-native-duration":
                if i < 271:
                    event, sequence = "tohoku", "seq-official20110311054624120_30"
                elif i < 409:
                    event, sequence = "chile", "seq-official20100227063411530_30"
                elif i < 413:
                    event, sequence = "lata" if i == 412 else "influence", "seq-usc000phx5"
                else:
                    event = f"event-{i % 29}"
                    sequence = f"seq-{event}"
            sequences[event] = sequence
            rows.append(
                dict(
                    record_id=f"{target}-{i:04d}",
                    event_id=event,
                    physical_site_id=f"site-{i}",
                    distance_km=str(100 + i * 10),
                    target_minutes=str((-1 if i % 2 else 1) * 20 if target == "T-CAL" else 20),
                    target=target,
                )
            )
        lanes[target] = lane_arrays(target, rows, sequences, set(sequences))
    for name in refs.CONSUMED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic reference consumer")
    (root / "native.csv").write_text("synthetic native source; never parsed by admission")
    contract = {"inputs": {"native.csv": sha256(root / "native.csv")}}
    registry = refs.descriptors()
    for ref in registry:
        lane = lanes[ref["target"]]
        indices = np.flatnonzero(lane.included)
        if ref["role"] != "base":
            indices = indices[np.asarray(lane.sequences)[indices] != ref["deleted_sequence"]]
        ids = [lane.record_ids[int(i)] for i in indices]
        job = dict(
            target=ref["target"], kind=ref["kind"], seed=ref["seed"], draws=2000, tune=1000, cores=2
        )
        if ref["role"] != "base":
            job.update(prior="base", phase="training", event=None, sequence=ref["deleted_sequence"])
        if wrong_job and ref is registry[0]:
            job["kind"] = "event"
        if ref["target"] == "NCEI-native-duration":
            names = ["alpha", "beta", "tau_event"] + (
                ["gamma"] if ref["kind"] == "mean-curvature" else []
            )
        else:
            names = ["alpha", "sigma"] + ([] if ref["kind"] == "pooled" else ["beta"])
            if ref["kind"] == "event":
                names.append("tau_event")
        aligned = np.arange(4 * draws).reshape(4, draws) / 100000 + 0.1
        post = xr.Dataset(
            {name: (("chain", "draw"), aligned) for name in names},
            coords={"chain": np.arange(4), "draw": np.arange(draws)},
        )
        if ref["target"] == "NCEI-native-duration":
            post["sigma_anchor"] = xr.DataArray(
                np.full((4, draws, 3), 0.4),
                dims=("chain", "draw", "scale_anchor_km"),
                coords={"scale_anchor_km": [500, 2000, 5000]},
            )
        post["ignored_old_derived"] = xr.DataArray(
            np.full((4, draws), np.nan), dims=("chain", "draw")
        )
        observed = xr.Dataset(
            {
                "response": ("record", lane.response[indices]),
                "native_minutes": ("record", lane.y[indices]),
            },
            coords={"record": ids},
        )
        raw = root / ref["raw"]
        raw.parent.mkdir(parents=True, exist_ok=True)
        xr.DataTree.from_dict({"posterior": post, "observed_data": observed}).to_netcdf(
            raw, engine="h5netcdf"
        )
        result = dict(
            job=job,
            posterior=ref["raw"],
            posterior_sha256=sha256(raw),
            records=len(ids),
            diagnostics={"screen_passed": True},
            status="computed_pending_scientific_review",
            events=ref.get("events"),
        )
        if wrong_raw_claim and ref is registry[0]:
            result["posterior_sha256"] = "0" * 64
        folder = root / ref["ensemble"]
        write_json(folder / "job.json", job)
        write_json(folder / "result.json", result)
        write_json(
            folder / "inputs.json",
            {"files": {"native.csv": sha256(root / "native.csv")}, "source_files": contract},
        )
        if ref["role"] == "base":
            write_json(
                folder / "output-checksums.json",
                {
                    name: sha256(folder / name)
                    for name in ["inputs.json", "job.json", "result.json"]
                },
            )
        else:
            held = np.flatnonzero(
                lane.included & (np.asarray(lane.sequences) == ref["deleted_sequence"])
            )
            membership = {
                "train": ids,
                "test": [lane.record_ids[int(i)] for i in held],
                "sequence": ref["deleted_sequence"],
            }
            if wrong_membership and ref["role"] == "reuse-influential2014":
                membership["train"] = ids[::-1]
            write_json(root / ref["folder"] / "membership.json", membership)
            write_json(folder / "membership.json", {"included": membership["train"]})
    # Legacy report acceptance binds its manifest, which binds the source map.
    for review in sorted({r["review"] for r in registry}):
        subset = [r for r in registry if r["review"] == review]
        doc = {"status": subset[0]["review_status"]}
        if subset[0]["kind"] == "mean-curvature" or subset[0]["role"] != "base":
            doc["independent_checker"] = (
                True if subset[0]["kind"] == "mean-curvature" else "/root/ms3_fit_checker"
            )
            paths = []
            for r in subset:
                paths.extend(
                    [
                        r["raw"],
                        *[
                            r["ensemble"] + "/" + name
                            for name in ["result.json", "job.json", "inputs.json"]
                        ],
                    ]
                )
                if r["role"] != "base":
                    paths.extend(
                        [r["folder"] + "/membership.json", r["ensemble"] + "/membership.json"]
                    )
            doc["files"] = {name: sha256(root / name) for name in paths}
        else:
            doc["posterior_checker" if subset[0]["kind"] == "distance-scale" else "checker"] = (
                "/root/ms3_fit_checker"
            )
            folder = (root / review).parent
            paths = [
                name
                for r in subset
                for name in [
                    r["raw"],
                    r["folder"] + "/result.json",
                    r["folder"] + "/output-checksums.json",
                ]
            ]
            write_json(folder / "inputs.json", {name: sha256(root / name) for name in paths})
            write_json(
                folder / "output-checksums.json", {"inputs.json": sha256(folder / "inputs.json")}
            )
            doc["manifest_sha256"] = sha256(folder / "output-checksums.json")
        write_json(root / review, doc)
    write_json(
        root / refs.CV,
        {
            "status": "accepted_all_curvature_sequence_computations",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {"native.csv": sha256(root / "native.csv")},
        },
    )
    write_json(
        root / refs.COMPARISON,
        {
            "status": "accepted_curvature_sequence_predictive_comparison",
            "independent_checker": True,
            "confirmation_outcomes_parsed": False,
            "reserved_outcomes": "sealed",
            "files": {refs.CV: sha256(root / refs.CV)},
        },
    )
    pins = {str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()}
    return lanes, pins


def test_fixed_fourteen_original_references_and_synthetic_population_alignment(tmp_path):
    lanes, pins = fixture(tmp_path)
    registry = refs.descriptors()
    assert len(registry) == len({r["key"] for r in registry}) == 14
    assert sum(r["role"] == "base" for r in registry) == 8
    assert all(r["new_sampler_calls"] == 0 for r in registry)
    assert all(
        r.get("deleted_sequence") == "seq-usc000phx5"
        for r in registry
        if r["role"] == "reuse-influential2014"
    )
    refs.verify_reference_sources(tmp_path, pins)
    for ref in registry:
        lane, kind, ids, post, provenance = refs.load_reference(tmp_path, ref["key"], lanes, pins)
        assert len(ids) == ref["records"] == lane.included.sum()
        assert kind == ref["kind"] and post.sizes["draw"] == 2000
        assert "ignored_old_derived" not in post
        np.testing.assert_array_equal(post.alpha, np.arange(8000).reshape(4, 2000) / 100000 + 0.1)
        assert provenance["posterior_sha256"] == pins[ref["raw"]]
        if ref["role"] != "base":
            assert ref["deleted_sequence"] not in set(np.asarray(lane.sequences)[ids])
    registry[0]["raw"] = "changed"
    assert refs.descriptors()[0]["raw"] != "changed"


@pytest.mark.parametrize(
    "failure",
    [
        "missing_pin",
        "raw_sha",
        "wrong_raw_claim",
        "wrong_job",
        "legacy_schema",
        "comparison",
        "closure",
        "symlink",
    ],
)
def test_rejects_bad_admission_before_any_netcdf_parse(tmp_path, monkeypatch, failure):
    _, pins = fixture(
        tmp_path, wrong_job=failure == "wrong_job", wrong_raw_claim=failure == "wrong_raw_claim"
    )
    ref = refs.descriptors()[0]
    if failure == "missing_pin":
        pins.pop(ref["ensemble"] + "/inputs.json")
    elif failure == "raw_sha":
        pins[ref["raw"]] = "0" * 64
    elif failure in {"legacy_schema", "comparison"}:
        name = ref["review"] if failure == "legacy_schema" else refs.COMPARISON
        doc = json.loads((tmp_path / name).read_text())
        doc["posterior_checker" if failure == "legacy_schema" else "status"] = (
            True if failure == "legacy_schema" else "pending"
        )
        write_json(tmp_path / name, doc)
        pins[name] = sha256(tmp_path / name)
    elif failure == "closure":
        pins.pop("native.csv")
    elif failure == "symlink":
        original = tmp_path / ref["raw"]
        moved = original.with_name("moved.nc")
        original.rename(moved)
        original.symlink_to(moved)
    monkeypatch.setattr(
        refs.xr, "open_dataset", lambda *a, **k: pytest.fail("NetCDF opened before admission")
    )
    with pytest.raises(ValueError):
        refs.verify_reference_sources(tmp_path, pins)


def test_whole_sequence_order_and_original_draw_count_are_required(tmp_path):
    lanes, pins = fixture(tmp_path, wrong_membership=True)
    ref = next(r for r in refs.descriptors() if r["role"] == "reuse-influential2014")
    with pytest.raises(ValueError, match="ordered canonical"):
        refs.load_reference(tmp_path, ref["key"], lanes, pins)
    other = tmp_path / "other"
    other.mkdir()
    lanes, pins = fixture(other, draws=4000)
    with pytest.raises(ValueError, match="original four-chain2000draw"):
        refs.load_reference(other, refs.descriptors()[0]["key"], lanes, pins)


def test_source_change_during_read_is_rejected(tmp_path, monkeypatch):
    lanes, pins = fixture(tmp_path)
    original = refs.xr.open_dataset
    count = []

    def open_and_change(*args, **kwargs):
        result = original(*args, **kwargs)
        count.append(kwargs["group"])
        if kwargs["group"] == "posterior":
            (tmp_path / "native.csv").write_text("changed after admission")
        return result

    monkeypatch.setattr(refs.xr, "open_dataset", open_and_change)
    with pytest.raises(ValueError, match="SHA changed"):
        refs.load_reference(tmp_path, refs.descriptors()[0]["key"], lanes, pins)
    assert count == ["observed_data", "posterior"]
