"""Synthetic-only repair admission, save-before-assessment and semantic replay."""

# pyright: basic
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pymc as pm
import pytest
import xarray as xr

from analysis.arrival import model_sensitivity_repair as repair
from analysis.arrival.evidence import sha256, write_json


def fixture(root, monkeypatch, failure=None) -> dict[str, Any]:
    original: dict[str, Any] = dict(
        id=repair.ORIGINAL_ID,
        order=34,
        target="NCEI-native-duration",
        kind="distance-scale",
        prior_variant="base",
        seed=2886144800,
        draws=2000,
        tune=1000,
        cores=2,
        distance_mode="source_native",
        omitted_record_ids=["omit"],
        excluded_record_ids=["exclude"],
        support={"min_distance_km": 20, "max_distance_km": 5000},
    )
    jobs: list[dict[str, Any]] = [dict(id=f"original-{i}", order=i) for i in range(55)]
    jobs[34] = original
    for name in repair.CONSUMED:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic source only\n")
    write_json(root / repair.fit.GATE, {"jobs": jobs})
    write_json(root / repair.PLAN, {"jobs": jobs})
    old_pins = {p: sha256(root / p) for p in [*repair.fit.CONSUMED, repair.fit.GATE]}
    admission = dict(gate={"jobs": jobs}, files=old_pins, contract={"synthetic": True})
    accepted, attempts, prefix = [], [], dict(old_pins)
    for i in range(34):
        name = f"old/case-{i}.json"
        write_json(root / name, {"synthetic": i})
        files = {name: sha256(root / name)}
        receipt = f"old/attempt-{i}.json"
        write_json(root / receipt, {"case_id": jobs[i]["id"], "files": files})
        entry: dict[str, Any] = dict(
            case_id=jobs[i]["id"],
            charged_slots=1,
            files=files,
            receipt=receipt,
            receipt_sha256=sha256(root / receipt),
        )
        accepted.append(entry)
        attempts.append(
            {k: v for k, v in entry.items() if k != "files"}
            | dict(outcome="accepted", start_markers=1)
        )
        prefix.update(files)
        prefix[receipt] = entry["receipt_sha256"]
    old_folder = repair.fit.OUTPUT + "/jobs/" + repair.ORIGINAL_ID
    old_raw = repair.fit.STORE + "/" + repair.ORIGINAL_ID + ".nc"
    p = root / old_raw
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"synthetic failed raw; deliberately never parsed")
    old_result = old_folder + "/result.json"
    write_json(
        root / old_result,
        dict(
            job=original,
            status="diagnostic_failure",
            records=147,
            events=11,
            posterior=old_raw,
            posterior_sha256=sha256(p),
            code_and_config=old_pins,
            diagnostics={"divergences": 13},
        ),
    )
    failed_names = [old_raw, old_result]
    for name in [
        "job.json",
        "inputs.json",
        "membership.json",
        "sampling-start.json",
        "diagnostics.json",
        "sampling-diagnostics.csv",
    ]:
        path = old_folder + "/" + name
        write_json(root / path, original if name in {"job.json", "sampling-start.json"} else {})
        failed_names.append(path)
    for suffix in ["-spec.json", ".log", ".supervisor.json"]:
        path = old_folder + suffix
        write_json(root / path, original if suffix == "-spec.json" else {})
        failed_names.append(path)
    failed_files = {name: sha256(root / name) for name in failed_names}
    receipt = old_folder + "/attempt-evidence.json"
    write_json(root / receipt, dict(case_id=repair.ORIGINAL_ID, files=failed_files))
    attempts.append(
        dict(
            case_id=repair.ORIGINAL_ID,
            charged_slots=1,
            receipt=receipt,
            receipt_sha256=sha256(root / receipt),
            start_markers=1,
            outcome="runtime_failure",
        )
    )
    write_json(
        root / repair.BASELINE,
        dict(
            next_case=34,
            calls_charged=35,
            calls_started=35,
            current=None,
            status="sensitivity_needs_review",
            accepted=accepted,
            attempts=attempts,
            plan_sha256=sha256(root / repair.PLAN),
        ),
    )
    review = dict(
        independent_checker=True, confirmation_outcomes_parsed=False, reserved_outcomes="sealed"
    )
    write_json(
        root / repair.PREFIX_REVIEW,
        dict(
            **review,
            status="accepted_sensitivity_thirty_four_case_checkpoint",
            accepted_total_cases=34,
            files=prefix,
        ),
    )
    failure_pins = {
        **prefix,
        **failed_files,
        receipt: sha256(root / receipt),
        repair.PREFIX_REVIEW: sha256(root / repair.PREFIX_REVIEW),
        repair.BASELINE: sha256(root / repair.BASELINE),
    }
    write_json(
        root / repair.FAILURE_REVIEW,
        dict(
            **review,
            status="accepted_sensitivity_same_case_numerical_repair_plan",
            files=failure_pins,
        ),
    )
    job = repair.repair_job(original)
    gate = dict(
        status="accepted_single_sensitivity_numerical_repair",
        **review,
        max_sampler_call_slots=110,
        calls_charged_before=35,
        new_sampler_calls=1,
        failure_review=repair.FAILURE_REVIEW,
        accepted_prefix_review=repair.PREFIX_REVIEW,
        path_bindings=dict(project_root=str(root), output=repair.OUTPUT, store=repair.STORE),
        job=job,
        original_science_gate_sha256=old_pins[repair.fit.GATE],
        original_plan_sha256=sha256(root / repair.PLAN),
        files={str(p.relative_to(root)): sha256(p) for p in root.rglob("*") if p.is_file()},
    )
    write_json(root / repair.GATE, gate)
    calls, loads, summaries = [], [], []
    monkeypatch.setattr(repair.fit, "verify_gate", lambda _: admission)
    lane = SimpleNamespace(
        target="NCEI-native-duration",
        record_ids=[f"r-{i}" for i in range(147)],
        event_ids=[f"e-{i % 11}" for i in range(147)],
        site_ids=[f"s-{i}" for i in range(147)],
        sequences=[f"seq-{i % 11}" for i in range(147)],
        y=np.linspace(1, 147, 147),
        response=np.linspace(-1, 1, 147),
        distance_km=np.linspace(20, 5000, 147),
        reference_minutes=np.full(147, 10.0),
    )
    ids = np.arange(147)
    monkeypatch.setattr(
        repair.fit, "_case_data", lambda *a: loads.append(a[1]) or (lane, ids, {"frozen": True})
    )
    monkeypatch.setattr(repair.fit, "_case_priors", lambda *a: ({"base": 1.0}, None))
    monkeypatch.setattr(
        repair.fit,
        "build_sensitivity_model",
        lambda *a, **kw: pm.Model(coords={"record": lane.record_ids}),
    )

    def sample(**kwargs):
        folder, raw = repair.case_paths(root, job)
        assert json.loads((folder / "sampling-start.json").read_text()) == job
        assert raw.exists() and raw.stat().st_size == 0
        assert kwargs == {k: v for k, v in repair.SAMPLER.items() if k != "seed"} | dict(
            random_seed=original["seed"], progressbar=False
        )
        calls.append(kwargs)
        if failure == "source":
            (root / repair.CONSUMED[0]).write_text("source changed after start")
        if failure == "sample":
            raise RuntimeError("synthetic sampling interruption")
        values: dict[str, Any] = {
            n: (("chain", "draw"), np.full((4, 2000), 0.2)) for n in ["alpha", "beta", "tau_event"]
        }
        values["sigma_anchor"] = (("chain", "draw", "scale_anchor_km"), np.full((4, 2000, 3), 0.3))
        return xr.DataTree.from_dict(
            {
                "posterior": xr.Dataset(
                    values,
                    coords=dict(
                        chain=range(4), draw=range(2000), scale_anchor_km=[500, 2000, 5000]
                    ),
                    attrs={
                        "inference_library": "other" if failure == "backend" else "nutpie",
                        "inference_library_version": "0.16.11",
                        "tuning_steps": 2000,
                    },
                ),
                "sample_stats": xr.Dataset(
                    {"diverging": (("chain", "draw"), np.zeros((4, 2000), dtype=bool))},
                    coords=dict(chain=range(4), draw=range(2000)),
                    attrs={
                        "inference_library": "nutpie",
                        "inference_library_version": "0.16.11",
                        "inference_library_settings": json.dumps(
                            {
                                "sampler": "nuts",
                                "adaptation": "diag",
                                "settings": {
                                    "num_tune": 2000,
                                    "num_draws": 2000,
                                    "num_chains": 4,
                                    "seed": 368973087,
                                    "adapt_options": {
                                        "step_size_settings": {"target_accept": 0.99}
                                    },
                                },
                            }
                        ),
                    },
                ),
            }
        )

    monkeypatch.setattr(repair.fit.pm, "sample", sample)

    def diagnostics(tree):
        raw = root / repair.STORE
        assert raw.stat().st_size > 0
        assert "observed_data" in tree.children
        return dict(
            screen_passed=failure != "diagnostics",
            finite_diagnostics=True,
            divergences=13 if failure == "diagnostics" else 0,
            maxdepth_reached=0,
            max_rhat=1.001,
            min_ess_bulk=1000,
            min_ess_tail=900,
            min_bfmi=0.9,
        ), pd.DataFrame({"r_hat": [1.001], "ess_bulk": [1000], "ess_tail": [900]}, index=["alpha"])

    monkeypatch.setattr(repair.fit, "sampling_diagnostics", diagnostics)
    summary: dict[str, Any] = {
        group: [dict(quantity=group, quantile_valid=True, native_representable=True, median=0.2)]
        for group in ["parameters", "derived", "curves", "record_intervals"]
    }
    summary.update(
        nonfinite_values={},
        unrepresentable_native_draws={},
        conditional_ppc=[
            dict(
                quantity="ppc",
                replicated_quantile_valid=True,
                replicated_native_representable=True,
                observed_quantile_valid=True,
            )
        ],
    )

    def summarize(*args, **kwargs):
        assert (root / repair.STORE).stat().st_size > 0
        assert args[0] is lane and args[1] == original["kind"]
        assert kwargs["seed"] == original["seed"] + 1 and kwargs["draws"] == 800
        np.testing.assert_array_equal(kwargs["indices"], ids)
        summaries.append(kwargs)
        if failure == "summary":
            raise RuntimeError("synthetic summary failure after retained raw")
        return deepcopy(summary)

    monkeypatch.setattr(repair.fit, "summarize_posterior", summarize)
    return dict(
        job=job,
        gate=gate,
        admission=admission,
        calls=calls,
        loads=loads,
        summaries=summaries,
        failed_files=failure_pins,
        lane=lane,
    )


def close(root, job):
    folder, _ = repair.case_paths(root, job)
    spec = folder.with_name(folder.name + "-spec.json")
    write_json(spec, job)
    folder.with_name(folder.name + ".log").write_text("synthetic process log\n")
    write_json(
        folder.with_name(folder.name + ".supervisor.json"),
        dict(
            returncode=0,
            reason="worker_exit",
            charged_slots=1,
            start_markers=1,
            job_sha256=sha256(spec),
            plan_sha256=sha256(root / repair.PLAN),
            repair_gate_sha256=sha256(root / repair.GATE),
            monitor_failures=[],
        ),
    )


def run(root, fixture):
    return repair.fit_repair(root, fixture["job"], *repair.case_paths(root, fixture["job"]))


def test_success_same_model_one_call_raw_before_assessment_and_complete_replay(
    tmp_path, monkeypatch
):
    f = fixture(tmp_path, monkeypatch)
    original = dict(f["failed_files"])
    result = run(tmp_path, f)
    assert result["status"] == "computed_pending_scientific_review"
    assert result["original_job"] == f["job"]["original_job"]
    assert len(f["calls"]) == 1 and len(f["summaries"]) == 1
    assert {p: sha256(tmp_path / p) for p in original} == original
    close(tmp_path, f["job"])
    pins = repair.verify_gate(tmp_path)["files"]
    proof = repair.case_artifacts(tmp_path, f["job"], pins)
    assert len(proof["files"]) == 17
    assert len(f["calls"]) == 1 and len(f["summaries"]) == 2
    write_json(proof["manifest"], dict(case_id=repair.ORIGINAL_ID, files=proof["files"]))
    accepted = dict(
        case_id=repair.ORIGINAL_ID,
        charged_slots=1,
        files=proof["files"],
        receipt=str(proof["manifest"].relative_to(tmp_path)),
        receipt_sha256=sha256(proof["manifest"]),
    )
    assert repair.case_artifacts(tmp_path, f["job"], pins, accepted)["files"] == proof["files"]
    with pytest.raises(ValueError, match="no overwrite"):
        run(tmp_path, f)


@pytest.mark.parametrize(
    "change",
    [
        "missing_gate",
        "source",
        "sampler",
        "output",
        "ceiling",
        "baseline",
        "failure_review",
        "prefix_review",
        "closure",
        "failed_raw",
    ],
)
def test_gate_rejection_precedes_native_load_and_sampling(tmp_path, monkeypatch, change):
    f = fixture(tmp_path, monkeypatch)
    gate = f["gate"]
    if change == "missing_gate":
        (tmp_path / repair.GATE).unlink()
    elif change == "source":
        (tmp_path / repair.CONSUMED[0]).write_text("drift")
    elif change == "sampler":
        gate["job"]["sampler"]["target_accept"] = 0.95
    elif change == "output":
        gate["path_bindings"]["output"] += "-other"
    elif change == "ceiling":
        gate["max_sampler_call_slots"] = 111
    elif change == "closure":
        gate["files"].pop(repair.fit.CONSUMED[-1])
    elif change == "failed_raw":
        (tmp_path / repair.fit.STORE / (repair.ORIGINAL_ID + ".nc")).write_bytes(b"changed")
    else:
        path = {
            "baseline": repair.BASELINE,
            "failure_review": repair.FAILURE_REVIEW,
            "prefix_review": repair.PREFIX_REVIEW,
        }[change]
        value = json.loads((tmp_path / path).read_text())
        value["calls_charged" if change == "baseline" else "status"] = (
            34 if change == "baseline" else "pending"
        )
        write_json(tmp_path / path, value)
        gate["files"][path] = sha256(tmp_path / path)
    if change != "missing_gate":
        write_json(tmp_path / repair.GATE, gate)
    with pytest.raises((ValueError, FileNotFoundError)):
        run(tmp_path, f)
    assert not f["loads"] and not f["calls"]
    assert not (tmp_path / repair.OUTPUT).exists()


@pytest.mark.parametrize("failure", ["sample", "backend", "diagnostics", "summary"])
def test_failed_repair_retains_one_start_and_raw_without_retry(tmp_path, monkeypatch, failure):
    f = fixture(tmp_path, monkeypatch, failure)
    before = {p: sha256(tmp_path / p) for p in f["failed_files"]}
    result = run(tmp_path, f)
    assert result["status"] != "computed_pending_scientific_review"
    assert len(f["calls"]) == 1
    folder, raw = repair.case_paths(tmp_path, f["job"])
    assert len(list(folder.glob("sampling-start*.json"))) == 1
    assert raw.exists() and (raw.stat().st_size > 0) == (failure != "sample")
    assert {p: sha256(tmp_path / p) for p in before} == before
    assert json.loads((folder / "result.json").read_text()) == result
    assert not (folder / "summary.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        "native",
        "record",
        "event",
        "tuning",
        "backend",
        "chain",
        "anchor",
        "diagnostics_csv",
        "summary_csv",
        "input",
        "supervisor",
        "unknown",
        "symlink",
    ],
)
def test_replay_rejects_resealed_semantic_or_inventory_changes(tmp_path, monkeypatch, change):
    f = fixture(tmp_path, monkeypatch)
    assert run(tmp_path, f)["status"] == "computed_pending_scientific_review"
    close(tmp_path, f["job"])
    folder, raw = repair.case_paths(tmp_path, f["job"])
    if change in {"native", "record", "event", "tuning", "backend", "chain", "anchor"}:
        with xr.open_datatree(raw, engine="h5netcdf") as source:
            tree = source.load().copy(deep=True)
        if change == "native":
            tree["observed_data"].to_dataset()["native_minutes"].values[0] += 1
        elif change == "record":
            tree["observed_data"] = xr.DataTree(
                tree["observed_data"]
                .to_dataset()
                .assign_coords(record=list(reversed(f["lane"].record_ids)))
            )
        elif change == "event":
            tree["observed_data"].to_dataset()["event_id"].values[0] = "e-x"
        elif change in {"tuning", "backend"}:
            tree["posterior"].attrs["tune" if change == "tuning" else "inference_library"] = (
                1000 if change == "tuning" else "other"
            )
        else:
            ds = tree["posterior"].to_dataset()
            ds = ds.assign_coords(
                {"chain": [4, 5, 6, 7]}
                if change == "chain"
                else {"scale_anchor_km": [500, 2000, 6000]}
            )
            tree["posterior"] = xr.DataTree(ds)
        tree.to_netcdf(raw, engine="h5netcdf")
        result = json.loads((folder / "result.json").read_text())
        result["posterior_sha256"] = sha256(raw)
        write_json(folder / "result.json", result)
    elif change == "diagnostics_csv":
        (folder / "sampling-diagnostics.csv").write_text("wrong\n")
    elif change == "summary_csv":
        (folder / "curves.csv").write_text("wrong\n")
    elif change == "unknown":
        (folder / "unlisted").write_text("extra")
    elif change == "symlink":
        (folder / "extra").symlink_to(raw)
    else:
        path = (
            folder / "inputs.json"
            if change == "input"
            else folder.with_name(folder.name + ".supervisor.json")
        )
        value = json.loads(path.read_text())
        value["base_prior" if change == "input" else "repair_gate_sha256"] = "forged"
        write_json(path, value)
    with pytest.raises((ValueError, AssertionError)):
        repair.case_artifacts(tmp_path, f["job"], repair.verify_gate(tmp_path)["files"])


def test_replay_checks_final_source_identity_and_manifest_original_id(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    run(tmp_path, f)
    close(tmp_path, f["job"])
    pins = repair.verify_gate(tmp_path)["files"]
    proof = repair.case_artifacts(tmp_path, f["job"], pins)
    write_json(proof["manifest"], dict(case_id=repair.REPAIR_ID, files=proof["files"]))
    entry = dict(
        case_id=repair.ORIGINAL_ID,
        charged_slots=1,
        files=proof["files"],
        receipt=str(proof["manifest"].relative_to(tmp_path)),
        receipt_sha256=sha256(proof["manifest"]),
    )
    with pytest.raises(ValueError, match="immutable"):
        repair.case_artifacts(tmp_path, f["job"], pins, entry)
    original = repair.fit.summarize_posterior

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / repair.CONSUMED[0]).write_text("changed during replay")
        return result

    monkeypatch.setattr(repair.fit, "summarize_posterior", changed)
    with pytest.raises(ValueError, match="changed"):
        repair.case_artifacts(tmp_path, f["job"], pins)


def test_source_change_after_start_retains_raw_and_failed_original(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch, "source")
    original_raw = tmp_path / repair.fit.STORE / (repair.ORIGINAL_ID + ".nc")
    original_sha = sha256(original_raw)
    result = run(tmp_path, f)
    assert result["status"] == "source_identity_failure"
    assert len(f["calls"]) == 1 and (tmp_path / repair.STORE).stat().st_size > 0
    assert sha256(original_raw) == original_sha


@pytest.mark.parametrize("cap", [0, 64 * 1024**2 + 1])
def test_cli_rejects_file_cap_before_any_admission(monkeypatch, cap):
    from scripts import fit_arrival_sensitivity_repair as cli

    monkeypatch.setattr(
        "sys.argv",
        [
            "repair",
            "--job",
            "unused",
            "--output",
            "unused",
            "--store",
            "unused",
            "--max-output-bytes",
            str(cap),
        ],
    )
    monkeypatch.setattr(
        cli, "limit_worker_file_size", lambda *_: pytest.fail("invalid cap reached limiter")
    )
    with pytest.raises(ValueError, match="1..64MiB"):
        cli.main()


def corrupt_original_sampler_metadata(tree, change):
    post, stats = tree["posterior"], tree["sample_stats"]
    if change == "warmup1000":
        post.attrs["tuning_steps"] = 1000
    elif change == "target095":
        settings = json.loads(stats.attrs["inference_library_settings"])
        settings["settings"]["adapt_options"]["step_size_settings"]["target_accept"] = 0.95
        stats.attrs["inference_library_settings"] = json.dumps(settings)
    elif change == "backend-note":
        post.attrs["inference_library"] = "pymc"
        post.attrs["unrelated_note"] = "nutpie was considered"
    elif change == "version":
        post.attrs["inference_library_version"] = "other-version"
    elif change == "stats-version":
        stats.attrs["inference_library_version"] = "other-version"
    elif change == "stats-backend":
        stats.attrs["inference_library"] = "pymc"
    elif change == "missing-tuning":
        post.attrs.pop("tuning_steps")
    elif change == "missing-version":
        stats.attrs.pop("inference_library_version")
    elif change == "missing-settings":
        stats.attrs.pop("inference_library_settings")
    elif change == "malformed-settings":
        stats.attrs["inference_library_settings"] = "not JSON"
    else:
        settings = json.loads(stats.attrs["inference_library_settings"])
        if change == "sampler":
            settings["sampler"] = "other"
        else:
            settings["settings"][change] = 1
        stats.attrs["inference_library_settings"] = json.dumps(settings)


@pytest.mark.parametrize("change", ["warmup1000", "target095", "backend-note"])
def test_worker_added_attributes_cannot_mask_original_sampler_mismatch(
    tmp_path, monkeypatch, change
):
    f = fixture(tmp_path, monkeypatch)
    sample = repair.fit.pm.sample

    def invalid(**kwargs):
        tree = sample(**kwargs)
        corrupt_original_sampler_metadata(tree, change)
        return tree

    monkeypatch.setattr(repair.fit.pm, "sample", invalid)
    result = run(tmp_path, f)
    assert result["status"] == "sampling_or_evaluation_failure"
    assert len(f["calls"]) == 1 and f["summaries"] == []
    raw = tmp_path / repair.STORE
    assert result["posterior_sha256"] == sha256(raw) and raw.stat().st_size > 0
    with xr.open_datatree(raw, engine="h5netcdf") as tree:
        assert tree["posterior"].attrs["tune"] == 2000
        assert tree["posterior"].attrs["target_accept"] == 0.99
        if change == "warmup1000":
            assert tree["posterior"].attrs["tuning_steps"] == 1000


@pytest.mark.parametrize("change", ["warmup1000", "target095", "backend-note"])
def test_replay_rejects_resealed_original_sampler_mismatch(tmp_path, monkeypatch, change):
    f = fixture(tmp_path, monkeypatch)
    assert run(tmp_path, f)["status"] == "computed_pending_scientific_review"
    close(tmp_path, f["job"])
    folder, raw = repair.case_paths(tmp_path, f["job"])
    with xr.open_datatree(raw, engine="h5netcdf") as source:
        tree = source.load().copy(deep=True)
    corrupt_original_sampler_metadata(tree, change)
    tree.to_netcdf(raw, engine="h5netcdf")
    result = json.loads((folder / "result.json").read_text())
    result["posterior_sha256"] = sha256(raw)
    write_json(folder / "result.json", result)
    with pytest.raises(ValueError, match="sampler"):
        repair.case_artifacts(tmp_path, f["job"], repair.verify_gate(tmp_path)["files"])


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "stats-version",
        "stats-backend",
        "missing-tuning",
        "missing-version",
        "missing-settings",
        "malformed-settings",
        "sampler",
        "num_tune",
        "num_draws",
        "num_chains",
    ],
)
def test_missing_or_inconsistent_original_sampler_metadata_is_not_certified(
    tmp_path, monkeypatch, change
):
    f = fixture(tmp_path, monkeypatch)
    sample = repair.fit.pm.sample

    def invalid(**kwargs):
        tree = sample(**kwargs)
        corrupt_original_sampler_metadata(tree, change)
        return tree

    monkeypatch.setattr(repair.fit.pm, "sample", invalid)
    result = run(tmp_path, f)
    assert result["status"] == "sampling_or_evaluation_failure"
    assert len(f["calls"]) == 1 and f["summaries"] == []
    assert result["posterior_sha256"] == sha256(tmp_path / repair.STORE)
