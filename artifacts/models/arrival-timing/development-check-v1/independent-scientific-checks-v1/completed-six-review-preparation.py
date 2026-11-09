"""Prepare a TEMP scientific-review packet; never publish or execute a job."""

import hashlib
import json
from pathlib import Path

ROOT = Path("/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times")
BASE = "artifacts/models/arrival-timing/"
CHECK = BASE + "development-check-v1/"
CONTROL = CHECK + "controller/completion-after-gap-v1/"
FREEZE = BASE + "specification-freeze-v1/review-acceptance.json"
WORKER = BASE + "development-design-v1/review-acceptance.json"
AUTHORITY = BASE + "development-design-v1/completion-after-gap-v1/check/review-acceptance.json"
CASE0 = BASE + "development-score-resolution-v1/review-acceptance.json"
CASE1 = BASE + "development-check-diagnostics-v1/case-001/review-acceptance.json"
CASE5 = CONTROL + "reviews/check/dev-tcal-pooled-runner-up-check/review-acceptance.json"
OUTPUT = Path("/private/tmp/tsunami-completed-six-check-review-PREPARED.json")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(name):
    return json.loads((ROOT / name).read_text())


def prepare():
    # Metadata only. No source module imports, loaders, NetCDF or scientific replay.
    gate = read(WORKER)
    authority = read(AUTHORITY)
    gap = read(CASE5)
    freeze = read(FREEZE)
    assert len(gate["jobs"]) == 6 and len(authority["jobs"]) == 4
    assert gap["status"] == "accepted_frozen_development_check_numerical_gap"
    assert sha(ROOT / CASE5) == "93feb587f8c581e2d5dfe809a59b66dc3fad885d388632d98298c2507f4dc946"
    assert sha(ROOT / FREEZE) == "b1de266480cb5dd31f18a34c4aef59d42866ed4f2a24b85a68b04d2045d22fce"
    assert sha(ROOT / WORKER) == "7e2738fab3044b8c5e6dd78d3a260cb4f84f3c25fabfd355b384c281be0b1b6f"
    files = dict(gap["files"])
    for name in [CASE0, CASE1, CASE5, FREEZE, WORKER, AUTHORITY]:
        value = read(name)
        for path, digest in value.get("files", {}).items():
            assert path not in files or files[path] == digest, path
            files[path] = digest
        digest = sha(ROOT / name)
        assert name not in files or files[name] == digest, name
        files[name] = digest
    assert all(files.get(p) == h for p, h in freeze["files"].items())
    assert {p: h for p, h in files.items() if p.startswith("context/")} == {
        p: h for p, h in freeze["files"].items() if p.startswith("context/")
    }
    assert len([p for p in files if p.startswith("context/")]) == 12
    assert not any(
        p.endswith("/failures/check/" + j["id"] + ".json")
        for p in files
        for j in authority["jobs"][:-1]
    )
    slots = []
    for index, job in enumerate(gate["jobs"]):
        outcome = (
            "accepted_resolution"
            if index == 0
            else "accepted_unresolved_gap"
            if index in (1, 5)
            else "accepted_direct_check"
        )
        folder = CHECK + "jobs/" + job["id"] + "/"
        slot = dict(
            order=index,
            original_job=job,
            outcome=outcome,
            primary_aggregate_available=index not in (1, 5),
            without_crossing_aggregate_available=index not in (1, 5),
            original_result=folder + "result.json",
            original_result_sha256=files[folder + "result.json"],
            prediction_file=folder + "held-out-record-predictions.csv",
            prediction_sha256=files[folder + "held-out-record-predictions.csv"],
            prediction_rows_precision_passed=[151, 151, 22, 22, 13, 13][index],
            original_worker_result_status=(
                "needs_numerical_review"
                if index in (0, 1, 5)
                else "computed_pending_scientific_review"
            ),
        )
        if index in (0, 1, 5):
            review_path = {0: CASE0, 1: CASE1, 5: CASE5}[index]
            slot.update(
                scientific_disposition=review_path, scientific_disposition_sha256=files[review_path]
            )
        else:
            receipt = CONTROL + "attempts/check/" + job["id"] + ".json"
            assert read(receipt)["outcome"] == "accepted"
            slot.update(attempt=receipt, attempt_sha256=files[receipt])
        slots.append(slot)
    review = dict(
        schema_version=1,
        status="accepted_frozen_arrival_development_check",
        independent_checker=True,
        checker="/root/sumatra_path_oracles",
        completed_once=True,
        no_retuning=True,
        confirmation_outcomes_parsed=True,
        development_check_previously_inspected=True,
        reserved_outcomes="sealed",
        reserved_outcomes_parsed=False,
        specification_freeze=FREEZE,
        specification_freeze_sha256=files[FREEZE],
        calls_charged=0,
        calls_started=0,
        completed_logical_check_slots=6,
        directly_accepted_checks=3,
        numerically_resolved_selected_checks=1,
        explicitly_unresolved_runner_up_checks=2,
        all_selected_checks_usable=True,
        all_six_checks_passed=False,
        six_logical_dispositions=slots,
        prediction_rows_precision_passed=372,
        distinct_source_check_records=186,
        source_record_counts={"NCEI-native-duration": 151, "T-OBS": 22, "T-CAL": 13},
        aggregate_views_available_models=4,
        aggregate_views_unavailable_models=2,
        case0_review=CASE0,
        case0_review_sha256=files[CASE0],
        case1_review=CASE1,
        case1_review_sha256=files[CASE1],
        last_gap_review=CASE5,
        last_gap_review_sha256=files[CASE5],
        original_execution_gate=WORKER,
        original_execution_gate_sha256=files[WORKER],
        completion_execution_gate=AUTHORITY,
        completion_execution_gate_sha256=files[AUTHORITY],
        qualifications=[
            "The 19-event check was previously inspected during EDA and is development evidence, "
            "not an independent test.",
            "Original failed results remain failed. Curved NCEI has its separately accepted "
            "zero-MCMC numerical resolution.",
            "Both aggregate views for the NCEI linear and Tcal pooled alternatives are "
            "unavailable; marginal predictions remain usable.",
            "No threshold changes, model or prior retuning, failed-score promotion, winner, "
            "equivalence or model-rejection claim.",
            "No cross-source score pooling or physical, causal, warning-time or operational "
            "validation claim.",
            "This review closes CHECK dispositions only and does not authorize G6 or "
            "full-development fits.",
        ],
        files=files,
    )
    return dict(
        status="TEMP_PREPARATION_ONLY_NOT_PUBLISHED_OR_ADMISSIBLE",
        canonical_path=CHECK + "review-acceptance.json",
        prepared_review=review,
        prerequisites_before_publication=[
            "Root CLOSED zero-child apply notice; exact journal check-summary "
            "and last disposition.",
            "P independent final process/inventory/quota/lease/source/counter proof.",
            "Copy final proof into approved public evidence location and close every new file.",
            "Verify exact summary partition: three accepted records, four attempts, "
            "three dispositions and six original slots.",
            "Fresh complete closure hash and no live private STATE/new context pins; "
            "exclusive publication only.",
        ],
        scientific_replay_repeated=False,
        cold_stream_repeated=False,
    )


if __name__ == "__main__":
    packet = prepare()
    with OUTPUT.open("xb") as stream:
        stream.write(
            (json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        )
    print(
        json.dumps(
            {
                "draft": str(OUTPUT),
                "sha256": sha(OUTPUT),
                "source_files": len(packet["prepared_review"]["files"]),
                "public_write": False,
                "numerical_replay": False,
            }
        )
    )
