"""Pure review-payload assembly after an independently checked closed run.

This helper never loads data, integrates, publishes reviews or accesses STATE.
Callers first perform the closed-job procedure and one explicit cold replay.
"""
from __future__ import annotations
import argparse
import json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cold_review(m, admission, candidate, replay, independent, process_proof, extra_files):
    """Build the first acyclic cold review; no science-review forward pin."""
    expected = dict(passed=True, blocks=512, unique_nodes=2097152, sampler_calls=0)
    require({k: replay.get(k) for k in expected} == expected, "complete one-time fixed replay required")
    require(replay.get("files") == candidate["files"], "replay must cover exact candidate bytes")
    require(candidate.get("status") == m.UNVERIFIED and candidate.get("semantics_verified") is False,
            "candidate must remain unverified before independent review")
    require(candidate.get("computed_status") in {m.SUCCESS, m.UNRESOLVED}, "typed computed result required")
    require(independent.get("passed") is True, "independent numeric checks must all pass")
    require(process_proof.get("closed") is True and process_proof.get("sampler_calls_charged") == 0
            and process_proof.get("sampler_calls_started") == 0,
            "independently verified closed zero-call process proof required")
    files = {**admission["files"], **candidate["files"], **extra_files, **process_proof["files"]}
    for scope in [admission["files"], candidate["files"], extra_files, process_proof["files"]]:
        require(all(files[p] == h for p, h in scope.items()), "conflicting review source identity")
    require(m.COLD_REVIEW not in files and m.REVIEW not in files, "no self or forward science-review pin")
    return dict(
        schema_version=1, status=m.COLD_REVIEW_STATUS, independent_checker=True,
        checker="/root/sumatra_path_oracles", source_role="frozen_check_numerical_resolution",
        job=m.job_descriptor(), original_job=admission["original_job"], execution_gate=m.GATE,
        execution_gate_sha256=admission["files"][m.GATE], protocol_sha256=m.fingerprint(m.protocol()),
        worker_sources={p: admission["files"][p] for p in [m.SELF, m.CLI, m.TEST]},
        candidate_files=candidate["files"], computed_status=candidate["computed_status"],
        full_stream_replay=expected, independent_checks=independent, process_proof=process_proof,
        sampler_calls=0, confirmation_outcomes_parsed=True, development_check_previously_inspected=True,
        reserved_outcomes="sealed", reserved_outcomes_parsed=False, new_full57_outcomes_parsed=False,
        original_failure_status_unchanged=True, accepted_completed_development_check=False,
        no_model_or_prior_retuning=True, no_observation_change=True, files=files,
    )


def science_review(m, admission, candidate, cold, cold_sha256, *, unresolved_disposition=None):
    """Build SCI only AFTER the cold review is exclusively published and hashed."""
    require(isinstance(cold_sha256, str) and len(cold_sha256) == 64
            and all(c in "0123456789abcdef" for c in cold_sha256), "exact published cold-review SHA required")
    require(cold.get("status") == m.COLD_REVIEW_STATUS and cold.get("independent_checker") is True,
            "independently accepted cold review required")
    resolved = candidate["computed_status"] == m.SUCCESS
    require(resolved or isinstance(unresolved_disposition, dict)
            and unresolved_disposition.get("independent_checker") is True
            and unresolved_disposition.get("accepted_unresolved_gap") is True,
            "precision failure needs a separately reviewed unresolved disposition; no automatic skip")
    prediction = m.ORIGINAL + "/held-out-record-predictions.csv"
    result = m.CASE_OUTPUT + "/result.json"
    files = {**cold["files"], m.COLD_REVIEW: cold_sha256}
    if unresolved_disposition is not None:
        for p, h in unresolved_disposition["files"].items():
            require(p not in files or files[p] == h, "unresolved disposition source conflict")
            files[p] = h
    require(m.REVIEW not in files, "science review must not pin itself")
    return dict(
        schema_version=1, status=m.REVIEW_STATUS, independent_checker=True,
        checker="/root/sumatra_path_oracles", original_job=admission["original_job"],
        original_state_sha256=m.ORIGINAL_STATE_SHA,
        specification_freeze_sha256=admission["files"][m.data.FREEZE],
        case0_outcome="accepted_resolution" if resolved else "accepted_unresolved_gap",
        primary_aggregate_available=resolved, resolved_result=result if resolved else None,
        resolved_result_sha256=candidate["files"][result] if resolved else None,
        prediction_file=prediction, prediction_sha256=admission["files"][prediction],
        original_failed_computation_retained=True, original_failure_not_relabelled=True,
        accepted_completed_development_check=False, no_model_rejection=True,
        no_model_or_prior_retuning=True, no_observation_change=True, sampler_calls=0,
        confirmation_outcomes_parsed=True, development_check_previously_inspected=True,
        reserved_outcomes="sealed", reserved_outcomes_parsed=False, new_full57_outcomes_parsed=False,
        unresolved_disposition=unresolved_disposition, files=files,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true", help="print the finite closed-run QA sequence")
    args = parser.parse_args()
    if args.describe:
        print(json.dumps([
            "Wait for Root closed production notice; independently verify public supervisor/receipt, cost0/start0, source/runtime and exact physical inventory without reading STATE.",
            "Verify numerical Gate and candidate bytes before reading only the authorized NCEI1040/151 and81cb training reference.",
            "Verify training-only proposal from original8000 theta; independent dense training/predictive Gaussian, native Jacobian and normalized t densities at three fixed persisted probes: df5/rep0/first0/offset0;df5/rep2/first131072/offset4095;df9/rep3/first258048/offset4095.",
            "Call replay_resolution exactly ONCE:512 blocks,2097152 unique nodes; compare every block/probe/prefix/proposal/precision/aggregate/result and fresh full sources.",
            "Independently recompute both paired-pooled ratio delta and replicate logratioSE, governingMAX; allHden&Hnum at both levels; fixedDF5 primary, DF9 corroboration/refinement; range diagnostic only.",
            "Sum original13 shared influences before MCSE, add selectedQMCSE/14 conservatively; crossing subset likewise/13. Supplement-only failure cannot fail good primary, and good supplement cannot rescue primary.",
            "Verify original151 prediction pointer and all old13 score identities unchanged; unresolved precision remains explicit, no failed score promotion.",
            "Fresh complete SHA/inventory recheck, exclusively publish cold review with no forward/self pins; publish typedSCI only for resolved precision or separately approvedUgap; verify trusted case_artifacts afterward.",
        ], indent=2))


if __name__ == "__main__":
    main()
