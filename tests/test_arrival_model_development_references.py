"""Synthetic exact-reference admission/alignment; no historical posteriors or check Y."""

# pyright: basic
import json
import tomllib
from dataclasses import replace
from typing import Any

import numpy as np
import pymc as pm
import pytest
import xarray as xr

from analysis.arrival import model_development_data as data
from analysis.arrival import model_development_references as refs
from analysis.arrival.evidence import sha256, write_json
from tests.test_arrival_model_development_data import fixture as data_fixture


def native_metadata(post):
    """Synthetic original backend metadata; no posterior inference is performed."""
    attrs = {"inference_library": "nutpie", "inference_library_version": "0.16.11"}
    post.attrs.update(**attrs, tuning_steps=1000)
    return xr.Dataset(
        coords={"chain": post.chain.values, "draw": post.draw.values},
        attrs={
            **attrs,
            "inference_library_settings": json.dumps(
                dict(
                    sampler="nuts",
                    settings=dict(
                        num_tune=1000,
                        num_draws=2000,
                        num_chains=4,
                        adapt_options=dict(step_size_settings=dict(target_accept=0.95)),
                    ),
                )
            ),
        },
    )


def damage_native_metadata(post, stats, fault):
    if fault == "backend_note":
        post.attrs.update(inference_library="pymc", note="nutpie is only an unrelated note")
    elif fault == "stats_backend":
        stats.attrs["inference_library"] = "pymc"
    elif fault == "version":
        post.attrs["inference_library_version"] = "wrong"
    elif fault == "settings":
        value = json.loads(stats.attrs["inference_library_settings"])
        value["settings"]["num_tune"] = 0
        value["settings"]["adapt_options"]["step_size_settings"]["target_accept"] = 0.5
        stats.attrs["inference_library_settings"] = json.dumps(value)
    elif fault == "coordinates":
        stats.coords["chain"] = [3, 2, 1, 0]
    elif fault == "tuning":
        post.attrs["tuning_steps"] = 0
    else:
        raise ValueError("unknown synthetic metadata fault")


def fixture(
    root, monkeypatch, target="NCEI-native-duration", kind="mean-curvature", *, raw_fault=None
):
    pins, _ = data_fixture(root, monkeypatch)
    freeze = json.loads((root / data.FREEZE).read_text())
    active = {name for name, _ in data._population_spec(target, kind).values()}
    prior = (
        data.read_curvature_prior(root, "base")
        if kind == "mean-curvature"
        else data.read_prior(root, target, "base")
    )
    freeze["models"][target][0].update(
        kind=kind, base_prior_sd={name: prior[name] for name in active}
    )
    decision = json.loads((root / freeze["ms5_decision"]).read_text())
    decision["models"] = freeze["models"]
    write_json(root / freeze["ms5_decision"], decision)
    for name in refs.CONSUMED:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic frozen reference consumer")
    files = {
        str(p.relative_to(root)): sha256(p)
        for p in root.rglob("*")
        if p.is_file() and str(p.relative_to(root)) != data.FREEZE
    }
    freeze["files"] = files
    write_json(root / data.FREEZE, freeze)
    pins = {**files, data.FREEZE: sha256(root / data.FREEZE)}
    lane = data.load_check_lanes(root, pins)["training_purged"][target]
    ref = refs._reference(target, kind)
    ids = np.flatnonzero(lane.included)
    records = [lane.record_ids[int(i)] for i in ids]
    count = 4000 if raw_fault == "draws" else 2000
    values = np.arange(4 * count).reshape(4, count) / 100000 + 0.1
    variables = {}
    for name, (_, shape) in data._population_spec(target, kind).items():
        variables[name] = (
            (("chain", "draw", "scale_anchor_km"), np.full((4, count, 3), 0.4))
            if shape
            else (("chain", "draw"), values.copy())
        )
    post = xr.Dataset(variables, coords={"chain": np.arange(4), "draw": np.arange(count)})
    if target == "NCEI-native-duration":
        post = post.assign_coords(scale_anchor_km=[500, 2000, 5000])
    post["unused_old_event_effect"] = (("chain", "draw"), np.full((4, count), np.nan))
    stats = native_metadata(post)
    post.attrs["inference_library"] = "wrong-backend" if raw_fault == "backend" else "nutpie"
    if raw_fault and raw_fault.startswith("native_"):
        damage_native_metadata(post, stats, raw_fault.removeprefix("native_"))
    if raw_fault == "nonfinite":
        post["alpha"].values[0, 0] = np.inf
    observed = xr.Dataset(
        {"response": ("record", lane.response[ids])},
        coords={"record": records[::-1] if raw_fault == "order" else records},
    )
    if kind == "mean-curvature":
        observed["native_minutes"] = ("record", lane.y[ids])
    raw = root / ref["raw"]
    raw.parent.mkdir(parents=True, exist_ok=True)
    xr.DataTree.from_dict(
        {"posterior": post, "sample_stats": stats, "observed_data": observed}
    ).to_netcdf(raw, engine="h5netcdf")
    job: dict[str, Any] = dict(
        target=target, kind=kind, seed=ref["seed"], draws=2000, tune=1000, cores=2
    )
    if target == "NCEI-native-duration":
        job.update(prior="base", phase="training", event=None, sequence=data.CROSS_SEQUENCE)
    folder = root / ref["ensemble"]
    write_json(folder / "job.json", job)
    write_json(
        folder / "result.json",
        {
            "job": job,
            "posterior": ref["raw"],
            "posterior_sha256": sha256(raw),
            "records": len(ids),
            "diagnostics": {"screen_passed": True},
        },
    )
    contract = tomllib.loads((root / data.CONTRACT).read_text())
    write_json(
        folder / "inputs.json",
        {
            "files": {data.TARGET_FILES[target]: sha256(root / data.TARGET_FILES[target])},
            "source_files": contract,
        },
    )
    if target == "NCEI-native-duration":
        write_json(folder / "membership.json", {"included": records})
        removed = [
            lane.record_ids[int(i)]
            for i in np.flatnonzero(~lane.included)
            if lane.sequences[int(i)] == data.CROSS_SEQUENCE
        ]
        write_json(
            root / ref["folder"] / "membership.json",
            {"train": records, "test": removed, "sequence": data.CROSS_SEQUENCE},
        )
        files = {
            str(p.relative_to(root)): sha256(p)
            for p in (root / ref["folder"]).rglob("*")
            if p.is_file()
        }
        files[ref["raw"]] = sha256(raw)
        write_json(
            root / ref["review"],
            {"status": ref["review_status"], "independent_checker": ref["checker"], "files": files},
        )
    else:
        write_json(
            folder / "output-checksums.json",
            {name: sha256(folder / name) for name in ["job.json", "result.json", "inputs.json"]},
        )
        report = (root / ref["review"]).parent
        write_json(
            report / "inputs.json",
            {
                ref["raw"]: sha256(raw),
                ref["ensemble"] + "/result.json": sha256(folder / "result.json"),
                ref["ensemble"] + "/output-checksums.json": sha256(
                    folder / "output-checksums.json"
                ),
            },
        )
        write_json(
            report / "output-checksums.json", {"inputs.json": sha256(report / "inputs.json")}
        )
        write_json(
            root / ref["review"],
            {
                "status": ref["review_status"],
                "checker": "/root/ms3_fit_checker",
                "report_manifest_sha256": sha256(report / "output-checksums.json"),
            },
        )
    key = f"{target}:{kind}:selected"
    files = {
        str(p.relative_to(root)): sha256(p)
        for p in root.rglob("*")
        if p.is_file() and str(p.relative_to(root)) != data.FREEZE
    }
    binding = {
        "raw": ref["raw"],
        "review": ref["review"],
        **{name: ref["ensemble"] + "/" + name + ".json" for name in ["job", "inputs", "result"]},
        "membership": ref["ensemble"] + "/membership.json"
        if target == "NCEI-native-duration"
        else None,
        "files": files,
    }
    freeze.update(training_references={key: binding}, files=files)
    write_json(root / data.FREEZE, freeze)
    pins = {**files, data.FREEZE: sha256(root / data.FREEZE)}
    return key, lane, pins


@pytest.mark.parametrize(
    "target,kind",
    [
        ("NCEI-native-duration", "distance-scale"),
        ("NCEI-native-duration", "mean-curvature"),
        *[
            (target, kind)
            for target in ["T-OBS", "T-CAL"]
            for kind in ["pooled", "distance", "event"]
        ],
    ],
)
def test_eight_literal_base_references_preserve_population_and_native_cohorts(
    tmp_path, monkeypatch, target, kind
):
    key, lane, pins = fixture(tmp_path, monkeypatch, target, kind)
    monkeypatch.setattr(pm, "sample", lambda *args, **kwargs: pytest.fail("sampling called"))
    monkeypatch.setattr(
        pm, "sample_prior_predictive", lambda *args, **kwargs: pytest.fail("prior sampling called")
    )
    reader = refs.read_rows

    def exploration_only(path):
        assert str(path).endswith(data.TARGET_FILES[target])
        return reader(path)

    monkeypatch.setattr(refs, "read_rows", exploration_only)
    post, provenance = refs.load_frozen_training_reference(tmp_path, key, lane, pins)
    np.testing.assert_array_equal(post.alpha, np.arange(8000).reshape(4, 2000) / 100000 + 0.1)
    assert "unused_old_event_effect" not in post
    assert len(provenance["training_record_ids"]) == (
        1040 if target == "NCEI-native-duration" else (236 if target == "T-OBS" else 156)
    )
    assert provenance["new_sampler_calls"] == 0 and provenance["scoring_performed"] is False
    assert provenance["raw_sha256"] == pins[provenance["raw"]]
    assert provenance["raw_native_minutes_present"] == (kind == "mean-curvature")
    if target == "T-CAL":
        assert (lane.y < 0).any()


@pytest.mark.parametrize(
    "fault", ["nonbase", "absent", "cohort", "augmented", "closure", "wrong_prior"]
)
def test_wrong_prior_cohort_or_source_proof_never_opens_netcdf(tmp_path, monkeypatch, fault):
    key, lane, pins = fixture(tmp_path, monkeypatch)
    freeze = json.loads((tmp_path / data.FREEZE).read_text())
    expected = (
        refs.RequiresNewFrozenTrainingFit
        if fault in {"nonbase", "absent", "cohort"}
        else ValueError
    )
    if fault == "nonbase":
        freeze["models"][lane.target][0]["prior_variant"] = "power_0.5"
        decision = json.loads((tmp_path / freeze["ms5_decision"]).read_text())
        decision["models"] = freeze["models"]
        write_json(tmp_path / freeze["ms5_decision"], decision)
        digest = sha256(tmp_path / freeze["ms5_decision"])
        freeze["files"][freeze["ms5_decision"]] = digest
        pins[freeze["ms5_decision"]] = digest
    elif fault == "absent":
        freeze.pop("training_references")
    elif fault == "cohort":
        lane = replace(
            lane, included=np.array([rid not in data.OLD_EXCLUSIONS for rid in lane.record_ids])
        )
    elif fault == "augmented":
        freeze["training_references"][key]["raw"] = "data/processed/models/later-augmented.nc"
    elif fault == "wrong_prior":
        freeze["models"][lane.target][0]["base_prior_sd"]["gamma_sd"] = 99
    elif fault == "closure":
        pins.pop(next(name for name in pins if name.endswith("output-file-checksums.json")))
    write_json(tmp_path / data.FREEZE, freeze)
    pins[data.FREEZE] = sha256(tmp_path / data.FREEZE)
    monkeypatch.setattr(
        refs.xr,
        "open_dataset",
        lambda *args, **kwargs: pytest.fail("NetCDF opened before admission"),
    )
    with pytest.raises(expected):
        refs.load_frozen_training_reference(tmp_path, key, lane, pins)


@pytest.mark.parametrize(
    "raw_fault",
    ["draws", "backend", "nonfinite", "order"]
    + [
        "native_" + fault
        for fault in [
            "backend_note",
            "stats_backend",
            "version",
            "settings",
            "coordinates",
            "tuning",
        ]
    ],
)
def test_original_draws_backend_finiteness_and_native_order_required(
    tmp_path, monkeypatch, raw_fault
):
    key, lane, pins = fixture(tmp_path, monkeypatch, raw_fault=raw_fault)
    with pytest.raises(ValueError):
        refs.load_frozen_training_reference(tmp_path, key, lane, pins)


def test_source_drift_during_posterior_read_rejected(tmp_path, monkeypatch):
    key, lane, pins = fixture(tmp_path, monkeypatch)
    open_dataset = refs.xr.open_dataset

    def open_and_change(*args, **kwargs):
        ds = open_dataset(*args, **kwargs)
        if kwargs["group"] == "posterior":
            (tmp_path / data.TARGET_FILES[lane.target]).write_text(
                "changed while reading posterior"
            )
        return ds

    monkeypatch.setattr(refs.xr, "open_dataset", open_and_change)
    with pytest.raises(ValueError, match="SHA changed"):
        refs.load_frozen_training_reference(tmp_path, key, lane, pins)


@pytest.mark.parametrize("target", ["T-OBS", "T-CAL"])
def test_ntwc_full_reference_requires_literal_entire_training_cohort(tmp_path, monkeypatch, target):
    key, lane, pins = fixture(tmp_path, monkeypatch, target, "event")
    mask = lane.included.copy()
    mask[0] = False
    monkeypatch.setattr(
        refs.xr, "open_dataset", lambda *args, **kwargs: pytest.fail("wrong-cohort NetCDF opened")
    )
    with pytest.raises(refs.RequiresNewFrozenTrainingFit, match="exact frozen training cohort"):
        refs.load_frozen_training_reference(tmp_path, key, replace(lane, included=mask), pins)
