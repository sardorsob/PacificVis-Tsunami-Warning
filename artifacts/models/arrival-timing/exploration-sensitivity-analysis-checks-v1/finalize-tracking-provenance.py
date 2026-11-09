"""Bind completed pending registration before first consumption of the analysis review."""

import hashlib
import json
from pathlib import Path

BASE = "artifacts/models/arrival-timing/"
REVIEW = BASE + "exploration-sensitivity-report-v1/review-acceptance.json"
AUDIT = BASE + "exploration-sensitivity-analysis-checks-v1/"
ORIGINAL = AUDIT + "pre-tracking-review.json"
PENDING = BASE + "exploration-sensitivity-v1/mlflow-receipt.json"
SELF = AUDIT + "finalize-tracking-provenance.py"
BEFORE_SHA = "d5f76663c1918831bac2243ba5f25853db18239dc6a8abf928db8783ca62752f"
PENDING_SHA = "0e093bcb0f63f3a630517a0080c040057931a3487a1e40a3c05986842bb808b5"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path.cwd().resolve()
    original = (root / REVIEW).read_bytes()
    assert hashlib.sha256(original).hexdigest() == BEFORE_SHA
    assert sha(root / PENDING) == PENDING_SHA
    review = json.loads(original)
    receipt = json.loads((root / PENDING).read_bytes())
    assert review["status"] == "accepted_exploration_sensitivity_analysis"
    assert review["independent_checker"] is True
    assert receipt["decision"] == "computed_pending_independent_sensitivity_review"
    assert len(receipt["children"]) == receipt["actual_sampler_calls"] == 58
    assert receipt["accepted_logical_fits"] == 54 and receipt["unresolved_case_count"] == 1
    for name, digest in review["files"].items():
        assert (root / name).resolve() == root / name and sha(root / name) == digest, name
    assert PENDING not in review["files"] and not (root / ORIGINAL).exists()
    with (root / ORIGINAL).open("xb") as stream:
        stream.write(original)
    review["pre_tracking_analysis_review"] = dict(path=ORIGINAL, sha256=BEFORE_SHA)
    review["tracking_registration"] = dict(
        path=PENDING,
        sha256=PENDING_SHA,
        parent=receipt["parent"]["run_id"],
        children=58,
        retained_failed_attempts=4,
        client_readback="PASS",
        decision="pending_tracking_only_no_scientific_reclassification",
    )
    review["files"].update(
        {ORIGINAL: BEFORE_SHA, PENDING: PENDING_SHA, SELF: sha(root / SELF)}
    )
    temporary = root / (REVIEW + ".temporary")
    with temporary.open("x") as stream:
        stream.write(json.dumps(review, sort_keys=True, indent=2, allow_nan=False) + "\n")
    assert sha(root / REVIEW) == BEFORE_SHA and sha(root / PENDING) == PENDING_SHA
    temporary.replace(root / REVIEW)
    for name, digest in review["files"].items():
        assert sha(root / name) == digest, name
    print(json.dumps(dict(review_sha256=sha(root / REVIEW), pins=len(review["files"]))))


if __name__ == "__main__":
    main()
