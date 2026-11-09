"""Synthetic final47 worker: no native data, genuine sampler or private STATE."""

# pyright: basic
import copy
import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis.arrival import model_sensitivity_repair47 as w
from analysis.arrival.evidence import sha256, write_json


def fixture(root, monkeypatch, failure=None):
    original = dict(
        id=w.ORIGINAL_ID,
        order=47,
        target="NCEI-native-duration",
        kind="mean-curvature",
        scenario="era-2014plus",
        prior_variant="base",
        distance_mode="geodesic_km",
        seed=2886157800,
        training_record_ids=[f"r{i}" for i in range(150)],
        omitted_record_ids=["omitted"],
        excluded_record_ids=["excluded"],
        support={},
    )
    job = w.repair_job(original)
    folder, raw = w.case_paths(root, job)
    for name in [*w.CONSUMED, w.PLAN]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
    files = {name: sha256(root / name) for name in [*w.CONSUMED, w.PLAN]}
    gate = dict(
        status="accepted_sensitivity_case47_repair_and_final_seven_execution",
        independent_checker=True,
        run_id=w.RUN_ID,
        confirmation_outcomes_parsed=False,
        reserved_outcomes="sealed",
        files=files,
    )
    write_json(root / w.GATE, gate)
    pins = {**files, w.GATE: sha256(root / w.GATE)}
    admission = dict(
        gate=gate,
        gate_path=w.GATE,
        files=pins,
        initial_files=pins,
        repair_job=job,
        jobs=[job],
        original_admission={"gate": {"jobs": [{}] * 47 + [original]}},
    )
    monkeypatch.setattr(w, "_authority", lambda root: admission)
    ids = np.arange(150)
    distance = np.linspace(600, 5000, 150)
    lane = SimpleNamespace(
        target=original["target"],
        record_ids=original["training_record_ids"],
        y=np.linspace(10, 100, 150),
        response=np.linspace(-0.2, 0.4, 150),
        distance_km=distance,
        reference_minutes=np.linspace(15, 90, 150),
        event_ids=[f"e{i % 5}" for i in ids],
        sequences=[f"s{i % 5}" for i in ids],
        site_ids=[f"site{i}" for i in ids],
    )

    class Model:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        w,
        "_case",
        lambda root, job, a: (lane, ids, {"synthetic": "source"}, {"gamma_sd": 0.5}, Model()),
    )
    calls = []

    def sample(**kwargs):
        assert json.loads((folder / "sampling-start.json").read_text()) == job
        assert raw.exists() and raw.stat().st_size == 0
        calls.append(kwargs)
        variables: dict[str, Any] = {
            name: (("chain", "draw"), np.full((4, 2000), 0.2))
            for name in ["alpha", "beta", "gamma", "tau_event"]
        }
        variables["sigma_anchor"] = (
            ("chain", "draw", "scale_anchor_km"),
            np.full((4, 2000, 3), 0.4),
        )
        settings: dict[str, Any] = dict(
            sampler="nuts",
            settings=dict(
                num_tune=4000,
                num_draws=2000,
                num_chains=4,
                seed=123,
                adapt_options=dict(step_size_settings=dict(target_accept=0.999)),
            ),
        )
        postattrs = dict(
            inference_library="nutpie", inference_library_version="0.16.11", tuning_steps=4000
        )
        statsattrs = dict(
            inference_library="nutpie",
            inference_library_version="0.16.11",
            inference_library_settings=json.dumps(settings),
        )
        if failure == "tune":
            postattrs["tuning_steps"] = 2000
        if failure == "accept":
            settings["settings"]["adapt_options"]["step_size_settings"]["target_accept"] = 0.99
            statsattrs["inference_library_settings"] = json.dumps(settings)
        if failure == "backend":
            statsattrs["inference_library"] = "pymc"
        if failure == "version":
            postattrs["inference_library_version"] = "wrong"
        if failure == "nonfinite":
            variables["gamma"][1][0, 0] = np.inf
        if failure == "source":
            (root / w.CONSUMED[0]).write_text("source drift")
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    variables,
                    coords=dict(
                        chain=range(4), draw=range(2000), scale_anchor_km=[500, 2000, 5000]
                    ),
                    attrs=postattrs,
                ),
                "sample_stats": xr.Dataset(
                    {"diverging": (("chain", "draw"), np.zeros((4, 2000), bool))},
                    coords=dict(chain=range(4), draw=range(2000)),
                    attrs=statsattrs,
                ),
            }
        )

    monkeypatch.setattr(w.fit.pm, "sample", sample)

    def diagnostics(tree):
        assert raw.stat().st_size > 0
        return dict(
            screen_passed=failure != "diagnostics", divergences=int(failure == "diagnostics")
        ), pd.DataFrame({"r_hat": [1.001]}, index=["alpha"])

    monkeypatch.setattr(w.fit, "sampling_diagnostics", diagnostics)
    summary = {
        group: [
            dict(
                quantity=group,
                q05=-0.1,
                q50=0.2,
                q95=0.4,
                quantile_valid=True,
                native_representable=True,
            )
        ]
        for group in ["parameters", "derived", "curves", "record_intervals"]
    }
    summary["conditional_ppc"] = [
        dict(
            scale="modeled-response", replicated_quantile_valid=True, observed_quantile_valid=True
        ),
        dict(
            scale="native-minutes",
            replicated_quantile_valid=True,
            observed_quantile_valid=True,
            replicated_log_q50=0.1,
        ),
    ]
    if failure == "summary":
        summary["curves"][0]["quantile_valid"] = False

    def summarize(*args, **kwargs):
        assert raw.stat().st_size > 0 and args[0] is lane and args[1] == "mean-curvature"
        assert kwargs["seed"] == 2886157801 and kwargs["draws"] == 800
        return copy.deepcopy(summary)

    monkeypatch.setattr(w.fit, "summarize_posterior", summarize)
    return SimpleNamespace(
        job=job, folder=folder, raw=raw, admission=admission, calls=calls, summary=summary
    )


def process(root, f):
    folder = f.folder
    spec = folder.with_name(folder.name + "-spec.json")
    write_json(spec, f.job)
    folder.with_name(folder.name + ".log").write_text("synthetic successful process")
    write_json(
        folder.with_name(folder.name + ".supervisor.json"),
        dict(
            returncode=0,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec),
            plan_sha256=f.admission["files"][w.PLAN],
            numerical_gate_sha256=f.admission["files"][w.GATE],
            execution_authority_gate_sha256=f.admission["files"][w.GATE],
            invocation_git_sha="a" * 40,
            monitor_failures=[],
        ),
    )


def test_fixed47_protocol_native_paths_and_no_old_gate_authority(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    assert f.job["id"] == "ms5-numerical-protocol-v2-047-attempt-2"
    assert f.job["sampler"] == {**w.PROTOCOL, "seed": 2886157800}
    assert (
        f.raw.parent == tmp_path / "data/processed/models/arrival-sensitivity-numerical-protocol-v2"
    )
    assert w._population is w.kernel._population and w._observed is w.kernel._observed
    bad = copy.deepcopy(f.job)
    bad["sampler"]["target_accept"] = 0.99
    with pytest.raises(ValueError):
        w.case_paths(tmp_path, bad)


def test_complete_save_first_replay_and_dual_new_gate_source(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    result = w.fit_repair(tmp_path, f.job, f.folder, f.raw)
    assert result["status"] == "computed_pending_scientific_review"
    assert len(f.calls) == 1 and f.calls[0] == {
        **{k: v for k, v in f.job["sampler"].items() if k != "seed"},
        "random_seed": 2886157800,
        "progressbar": False,
    }
    assert json.loads((f.folder / "inputs.json").read_text())["files"] == f.admission["files"]
    process(tmp_path, f)
    proof = w.case_artifacts(tmp_path, f.job, f.admission["files"])
    assert len(proof["files"]) == 17 and proof["posterior_sha256"] == sha256(f.raw)
    write_json(proof["manifest"], {"case_id": w.ORIGINAL_ID, "files": proof["files"]})
    accepted = dict(
        case_id=w.ORIGINAL_ID,
        charged_slots=1,
        files=proof["files"],
        receipt=str(proof["manifest"].relative_to(tmp_path)),
        receipt_sha256=sha256(proof["manifest"]),
    )
    assert (
        w.case_artifacts(tmp_path, f.job, f.admission["files"], accepted)["files"] == proof["files"]
    )


@pytest.mark.parametrize(
    "failure",
    ["diagnostics", "tune", "accept", "backend", "version", "nonfinite", "summary", "source"],
)
def test_failure_keeps_raw_and_never_becomes_success(tmp_path, monkeypatch, failure):
    f = fixture(tmp_path, monkeypatch, failure)
    result = w.fit_repair(tmp_path, f.job, f.folder, f.raw)
    assert f.raw.stat().st_size > 0 and result["status"] != "computed_pending_scientific_review"
    assert len(f.calls) == 1 and (f.folder / "result.json").is_file()
    with pytest.raises((ValueError, FileExistsError)):
        w.fit_repair(tmp_path, f.job, f.folder, f.raw)


@pytest.mark.parametrize(
    "change",
    [
        "diagnostics",
        "summary",
        "csv",
        "prior-source",
        "authority",
        "spec-gate",
        "start",
        "unknown-directory",
    ],
)
def test_resealed_or_unlisted_proof_corruption_rejected(tmp_path, monkeypatch, change):
    f = fixture(tmp_path, monkeypatch)
    w.fit_repair(tmp_path, f.job, f.folder, f.raw)
    process(tmp_path, f)
    if change == "diagnostics":
        value = json.loads((f.folder / "diagnostics.json").read_text())
        value["divergences"] = 999
        write_json(f.folder / "diagnostics.json", value)
    elif change == "summary":
        value = json.loads((f.folder / "summary.json").read_text())
        value["parameters"][0]["q50"] = 999
        write_json(f.folder / "summary.json", value)
    elif change == "csv":
        (f.folder / "conditional-ppc.csv").write_text("corrupt")
    elif change == "prior-source":
        value = json.loads((f.folder / "inputs.json").read_text())
        value["base_prior"] = {"gamma_sd": 999}
        write_json(f.folder / "inputs.json", value)
    elif change in ["authority", "spec-gate"]:
        path = f.folder.with_name(f.folder.name + ".supervisor.json")
        value = json.loads(path.read_text())
        value[
            "execution_authority_gate_sha256" if change == "authority" else "numerical_gate_sha256"
        ] = "0" * 64
        write_json(path, value)
    elif change == "start":
        write_json(f.folder / "sampling-start.json", {})
    else:
        (f.folder / "unknown-empty").mkdir()
    with pytest.raises(ValueError):
        w.case_artifacts(tmp_path, f.job, f.admission["files"])


@pytest.mark.parametrize("change", ["missing", "source", "protected", "status"])
def test_preflight_before_authority_or_native_loader(tmp_path, monkeypatch, change):
    f = fixture(tmp_path, monkeypatch)
    if change == "missing":
        (tmp_path / w.GATE).unlink()
    elif change == "source":
        (tmp_path / w.CONSUMED[0]).write_text("drift")
    else:
        value = json.loads((tmp_path / w.GATE).read_text())
        if change == "protected":
            value["confirmation_outcomes_parsed"] = True
        else:
            value["status"] = "accepted_old38_specification"
        write_json(tmp_path / w.GATE, value)
    monkeypatch.setattr(
        w, "_authority", lambda *args: pytest.fail("authority/native parse before source preflight")
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        w.fit_repair(tmp_path, f.job, f.folder, f.raw)
    assert not f.raw.exists() and not f.folder.exists() and not f.calls
