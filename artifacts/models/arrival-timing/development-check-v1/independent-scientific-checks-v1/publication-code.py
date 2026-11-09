"""Authorized final CHECK science publication; no loaders or numerical replay."""

import hashlib
import json
import runpy
from pathlib import Path

ROOT = Path("/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times")
PREPARE = Path("/private/tmp/prepare-ms6-completed-check-review.py")
PREPARE_SHA = "96e908acea8c1e2e170086b86fd9b958c4907daf20541467b0e2167679545724"
PQA = Path("/private/tmp/tsunami-journal-zero-child-apply-runtime-qa.json")
PQA_SHA = "5fad04ca48d13f148e1870c7a6ad18eaf307b7d464ac3cb23cf07a98bab3b094"
CHECK = "artifacts/models/arrival-timing/development-check-v1/"
CONTROL = CHECK + "controller/completion-after-gap-v1/"
CANONICAL = CHECK + "review-acceptance.json"
EVIDENCE = CHECK + "independent-scientific-checks-v1/"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def read(name):
    return json.loads((ROOT / name).read_text())


def publish():
    assert sha(PREPARE) == PREPARE_SHA and sha(PQA) == PQA_SHA
    assert not (ROOT / CANONICAL).exists() and not (ROOT / EVIDENCE).exists()
    prepared = runpy.run_path(str(PREPARE), run_name="metadata_only")["prepare"]()
    review = prepared["prepared_review"]
    files = dict(review["files"])

    def merge(mapping):
        for name, digest in mapping.items():
            assert name not in files or files[name] == digest, name
            files[name] = digest

    p = json.loads(PQA.read_text())
    assert p["independent_checker"] and p["logical_check_slots"] == 6
    assert p["status"] == "independently_verified_zero_child_check_gap_application_metadata"
    assert p["new_worker_processes"] == p["new_allocations"] == p["new_attempt_receipts"] == 0
    assert p["new_sampler_markers"] == p["calls_charged"] == p["calls_started"] == 0
    assert p["original_fifty_three_persistent_files_unchanged"]
    assert p["previous_fifty_seven_archive_proof_pins_unchanged"]
    assert p["all_five_leases_absent"] and p["lossless_archive_preserved"]
    assert p["quota"]["reserve_included_check"] == "passed"
    merge(p["files"])
    summary_path = p["check_summary"]
    assert sha(ROOT / summary_path) == p["check_summary_sha256"]
    summary = read(summary_path)
    assert summary["status"] == "computed_pending_independent_review"
    assert summary["calls_charged"] == summary["calls_started"] == 0
    assert len(summary["accepted_records"]) == 3 and len(summary["attempt_records"]) == 4
    assert len(summary["logical_check_dispositions"]) == 3
    assert summary["jobs"] == read(review["completion_execution_gate"])["jobs"]
    assert summary["authority_gate_sha256"] == files[summary["authority_gate"]]
    assert summary["worker_gate_sha256"] == files[summary["worker_gate"]]
    assert summary["specification_freeze_sha256"] == review["specification_freeze_sha256"]
    slots = review["six_logical_dispositions"]
    assert [r["job_id"] for r in summary["attempt_records"]] == [
        s["original_job"]["id"] for s in slots[2:]
    ]
    assert summary["accepted_records"] == [
        r for r in summary["attempt_records"] if r["outcome"] == "accepted"
    ]
    assert [r["job_id"] for r in summary["accepted_records"]] == [
        slots[i]["original_job"]["id"] for i in (2, 3, 4)
    ]
    assert [r["job_id"] for r in summary["logical_check_dispositions"]] == [
        slots[i]["original_job"]["id"] for i in (0, 1, 5)
    ]
    for record in summary["attempt_records"]:
        assert record["cost"] == record["start_markers"] == 0
        merge(record["files"])
        assert sha(ROOT / record["receipt"]) == record["receipt_sha256"]
        merge({record["receipt"]: record["receipt_sha256"]})
        attempt = read(record["receipt"])
        assert attempt["job_id"] == record["job_id"] and attempt["outcome"] == record["outcome"]
    for logical in summary["logical_check_dispositions"]:
        assert logical["job"] == next(
            s["original_job"] for s in slots if s["original_job"]["id"] == logical["job_id"]
        )
        assert logical["review_sha256"] == files[logical["review"]]
        if "disposition" in logical:
            assert logical["disposition"] == p["typed_disposition"]
            assert (
                sha(ROOT / logical["disposition"])
                == logical["disposition_sha256"]
                == p["typed_disposition_sha256"]
            )
            merge({logical["disposition"]: logical["disposition_sha256"]})
    merge({summary_path: sha(ROOT / summary_path)})
    for name, digest in files.items():
        path = ROOT / name
        assert path.resolve() == path and path.is_file() and sha(path) == digest, name
    inherited = {
        n: h
        for n, h in read(review["specification_freeze"])["files"].items()
        if n.startswith("context/")
    }
    assert len(inherited) == 12
    assert {n: h for n, h in files.items() if n.startswith("context/")} == inherited
    assert not any(
        n.endswith("/development-state.json")
        or n.endswith("/development-completion-state.json")
        or n.endswith("/sensitivity-state.json")
        for n in files
    )
    evidence = ROOT / EVIDENCE
    evidence.mkdir()
    copies = {
        "zero-child-apply-runtime-qa.json": PQA,
        "completed-six-review-preparation.py": PREPARE,
        "publication-code.py": Path(__file__),
    }
    for name, source in copies.items():
        destination = evidence / name
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
        assert sha(destination) == sha(source)
        files[EVIDENCE + name] = sha(destination)
    audit = dict(
        status="independently_verified_six_frozen_check_dispositions",
        independent_checker=True,
        once_only=True,
        numerical_replay_repeated=False,
        cold_numeric_stream_repeated=False,
        live_private_state_parsed=False,
        direct_passes=3,
        accepted_numerical_resolution=1,
        runner_up_gaps=2,
        usable_selected_models=3,
        model_prediction_rows_precision_passed=372,
        distinct_source_records=186,
        event_score_slots_usable=48,
        event_score_slots_total=50,
        primary_aggregate_views_available=4,
        primary_aggregate_views_unavailable=2,
        original_prediction_files_preserved=True,
        original_failed_statuses_preserved=True,
        native_positive_jacobian_subtracted_once=True,
        signed_Tcal_jacobian_zero=True,
        shared_training_influence_combined_before_aggregate_MCSE=True,
        curved_resolution_MCSE_uses_accepted_conservative_sum_not_independence=True,
        scientific_evidence=[
            review["case0_review"],
            review["case1_review"],
            review["last_gap_review"],
        ],
        gap_models=["NCEI-native-duration:distance-scale:runner_up", "T-CAL:pooled:runner_up"],
        all_selected_usable=True,
        no_six_pass_claim=True,
        no_winner_or_equivalence_claim=True,
        accepted_summary=summary_path,
        accepted_summary_sha256=files[summary_path],
        final_runtime_evidence=EVIDENCE + "zero-child-apply-runtime-qa.json",
    )
    with (evidence / "scientific-completion-audit.json").open("xb") as stream:
        stream.write(encode(audit))
    files[EVIDENCE + "scientific-completion-audit.json"] = sha(
        evidence / "scientific-completion-audit.json"
    )
    review.update(
        journal_check_summary=summary_path,
        journal_check_summary_sha256=files[summary_path],
        journal_summary_original_status=summary["status"],
        logical_check_dispositions=summary["logical_check_dispositions"],
        accepted_check_attempts=summary["accepted_records"],
        retained_journal_attempts=summary["attempt_records"],
        zero_child_gap_apply_completed=True,
        new_children_during_gap_apply=0,
        final_runtime_review=EVIDENCE + "zero-child-apply-runtime-qa.json",
        final_runtime_review_sha256=PQA_SHA,
        scientific_completion_audit=EVIDENCE + "scientific-completion-audit.json",
        scientific_completion_audit_sha256=files[EVIDENCE + "scientific-completion-audit.json"],
        original_private_state_hashes_history_only=p["states_conserved"],
        no_live_private_state_file_pins=True,
        files=files,
    )
    for name, digest in files.items():
        assert sha(ROOT / name) == digest, name
    with (ROOT / CANONICAL).open("xb") as stream:
        stream.write(encode(review))
    for name, digest in files.items():
        assert sha(ROOT / name) == digest, name
    assert json.loads((ROOT / CANONICAL).read_text()) == review
    print(
        json.dumps(
            dict(
                review=CANONICAL,
                status=review["status"],
                sha256=sha(ROOT / CANONICAL),
                files=len(files),
                six_slots=6,
                direct_passes=3,
                resolved=1,
                gaps=2,
                sampler_calls=0,
                numerical_replay_repeated=False,
            )
        )
    )


if __name__ == "__main__":
    publish()
