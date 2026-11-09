"""Synthetic report correction QA; no model outputs or native data are loaded."""

# pyright: basic
from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path

import pytest

from scripts import correct_arrival_sensitivity_qualifications as m


def original_qualifications():
    source = Path(__file__).parents[1] / "analysis/arrival/model_sensitivity_report.py"
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "QUALIFICATIONS" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError("frozen qualification source missing")


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def csv_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


@pytest.fixture
def report(tmp_path):
    folder = tmp_path / m.REPORT
    folder.mkdir(parents=True)
    for name in m.ARTIFACTS:
        (folder / name).write_bytes(("unchanged " + name + "\n").encode())
    qualifications = original_qualifications()
    (folder / "findings.md").write_text(
        "# Findings\n\n" + "\n\n".join(qualifications) + "\n\nExact table: 3.14159\n"
    )
    (folder / "summary.json").write_bytes(
        encode(
            dict(
                qualifications=qualifications,
                sentinel={"exact": 3.14159},
                schema_version=4,
                confirmation_outcomes_parsed=False,
                reserved_outcomes="sealed",
            )
        )
    )
    rows = []
    counts = {
        "distance-scale": {"modeled-response": 11, "native-minutes": 10},
        "mean-curvature": {"modeled-response": 8, "native-minutes": 9},
    }
    for kind in counts:
        for scale in counts[kind]:
            for index, (stratum, quantile) in enumerate(
                (s, q) for s in m.STRATA for q in m.QUANTILES
            ):
                rows.append(
                    dict(
                        view_id=f"NCEI-native-duration:{kind}:base",
                        target="NCEI-native-duration",
                        kind=kind,
                        role="base",
                        scenario="base",
                        prior_variant="base",
                        distance_mode="geodesic_km",
                        scale=scale,
                        stratum=stratum,
                        quantile=quantile,
                        observed_quantile_valid="True",
                        replicated_quantile_valid="True",
                        check_scope=m.CHECK_SCOPE,
                        observed_outside_replicated_90=str(index < counts[kind][scale]),
                    )
                )
    (folder / m.CSV).write_bytes(csv_bytes(rows))
    for name in [m.SELF, m.TEST]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"closed tool source\n")
    refresh(folder)
    return tmp_path, folder, rows


def refresh(folder):
    (folder / m.MANIFEST).write_bytes(
        encode({name: m.digest((folder / name).read_bytes()) for name in m.ARTIFACTS})
    )
    return m.digest((folder / m.MANIFEST).read_bytes())


def inventory(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_exact_three_file_correction_preserves_all_other_bytes_and_originals(report):
    root, folder, _ = report
    before = inventory(root)
    expected = m.digest((folder / m.MANIFEST).read_bytes())
    preview = m.correct(root, expected_manifest_sha256=expected)
    assert inventory(root) == before and preview["applied"] is False
    receipt = m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert receipt["status"] == "corrected_sensitivity_predictive_check_qualification"
    assert receipt["base_counts"]["distance-scale"] == {
        "modeled-response": {"misses": 11, "checks": 15},
        "native-minutes": {"misses": 10, "checks": 15},
    }
    assert receipt["changed_files"] == ["findings.md", "output-checksums.json", "summary.json"]
    assert (
        set(receipt["before_files"])
        == set(receipt["after_files"])
        == set(m.ARTIFACTS) | {m.MANIFEST}
    )
    text = receipt["replacement"]["new_text"]
    assert "11/15 modeled-response and 10/15 native" in text
    assert "8/15 modeled-response and 9/15 native" in text
    assert "These overlapping in-sample checks do not rank held-out performance." in text
    for name in m.ARTIFACTS:
        original = before[f"{m.REPORT}/{name}"]
        actual = (folder / name).read_bytes()
        assert actual == (
            original.replace(m.OLD_SENTENCE.encode(), text.encode(), 1)
            if name in {"findings.md", "summary.json"}
            else original
        )
    for name, snapshot in receipt["snapshots"].items():
        assert (root / snapshot["path"]).read_bytes() == before[f"{m.REPORT}/{name}"]
        assert snapshot["sha256"] == receipt["before_files"][name]
    assert receipt["source_files"][f"{m.REPORT}/{m.CSV}"] == receipt["before_files"][m.CSV]
    assert (
        receipt["confirmation_outcomes_parsed"] is False
        and receipt["reserved_outcomes"] == "sealed"
    )
    assert json.loads((root / m.EVIDENCE / "receipt.json").read_text()) == receipt
    saved = inventory(root)
    with pytest.raises(ValueError):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert inventory(root) == saved


def test_counts_are_derived_instead_of_fixed_to_actual_values(report):
    root, folder, rows = report
    for row in rows:
        if row["kind"] == "distance-scale" and row["scale"] == "modeled-response":
            row["observed_outside_replicated_90"] = "False"
    (folder / m.CSV).write_bytes(csv_bytes(rows))
    expected = refresh(folder)
    result = m.correct(root, expected_manifest_sha256=expected)
    assert result["base_counts"]["distance-scale"]["modeled-response"]["misses"] == 0
    assert "0/15 modeled-response" in result["replacement"]["new_text"]


@pytest.mark.parametrize(
    "change",
    [
        "wrong-expected",
        "changed-payload",
        "extra-file",
        "extra-directory",
        "symlink",
        "manifest-key",
        "manifest-value",
        "missing-tool",
        "existing-evidence",
    ],
)
def test_inventory_and_source_drift_reject_before_any_write(report, change):
    root, folder, _ = report
    expected = m.digest((folder / m.MANIFEST).read_bytes())
    if change == "wrong-expected":
        expected = "0" * 64
    elif change == "changed-payload":
        (folder / "posterior-parameters.csv").write_bytes(b"drift")
    elif change == "extra-file":
        (folder / "unlisted.txt").write_bytes(b"preserve")
    elif change == "extra-directory":
        (folder / "extra").mkdir()
    elif change == "symlink":
        p = folder / "posterior-parameters.csv"
        p.unlink()
        p.symlink_to(folder / m.CSV)
    elif change.startswith("manifest-"):
        value = json.loads((folder / m.MANIFEST).read_text())
        if change == "manifest-key":
            value["unlisted.txt"] = "0" * 64
        else:
            value[m.CSV] = "0" * 64
        (folder / m.MANIFEST).write_bytes(encode(value))
        expected = m.digest((folder / m.MANIFEST).read_bytes())
    elif change == "missing-tool":
        (root / m.SELF).unlink()
    else:
        (root / m.EVIDENCE).mkdir()
    before = inventory(root)
    with pytest.raises(ValueError):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert inventory(root) == before


@pytest.mark.parametrize(
    "change",
    [
        "missing-group",
        "duplicate-row",
        "wrong-scale",
        "wrong-identity",
        "wrong-scope",
        "invalid-flag",
        "invalid-quantile",
        "invalid-validity",
    ],
)
def test_base_groups_are_exact_and_complete_before_any_write(report, change):
    root, folder, rows = report
    if change == "missing-group":
        rows = [
            r
            for r in rows
            if not (r["kind"] == "mean-curvature" and r["scale"] == "native-minutes")
        ]
    elif change == "duplicate-row":
        rows.append(dict(rows[0]))
    else:
        field, value = {
            "wrong-scale": ("scale", "other"),
            "wrong-identity": ("view_id", "other"),
            "wrong-scope": ("check_scope", "held-out"),
            "invalid-flag": ("observed_outside_replicated_90", "unknown"),
            "invalid-quantile": ("quantile", "0.1"),
            "invalid-validity": ("replicated_quantile_valid", "False"),
        }[change]
        rows[0][field] = value
    (folder / m.CSV).write_bytes(csv_bytes(rows))
    expected = refresh(folder)
    before = inventory(root)
    with pytest.raises(ValueError):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert inventory(root) == before and not (root / m.EVIDENCE).exists()


@pytest.mark.parametrize(
    "change",
    [
        "missing-sentence",
        "duplicate-sentence",
        "other-summary-qualification",
        "other-findings-qualification",
        "summary-outside-qualification",
    ],
)
def test_only_literal_qualification_change_is_admitted(report, change):
    root, folder, _ = report
    if change in {"missing-sentence", "duplicate-sentence", "other-findings-qualification"}:
        p = folder / "findings.md"
        text = p.read_text()
        if change == "missing-sentence":
            text = text.replace(m.OLD_SENTENCE, "")
        elif change == "duplicate-sentence":
            text += "\n" + m.OLD_SENTENCE
        else:
            text = text.replace("Priors are analyst choices", "Priors are established facts")
        p.write_text(text)
    else:
        p = folder / "summary.json"
        value = json.loads(p.read_text())
        if change == "other-summary-qualification":
            value["qualifications"][0] += " changed"
        else:
            value["extra"] = m.OLD_SENTENCE
        p.write_bytes(encode(value))
    expected = refresh(folder)
    before = inventory(root)
    with pytest.raises(ValueError):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert inventory(root) == before and not (root / m.EVIDENCE).exists()


def test_interruption_retains_originals_and_never_publishes_completed_receipt(report, monkeypatch):
    root, folder, _ = report
    original = {name: (folder / name).read_bytes() for name in m.CHANGED}
    expected = m.digest(original[m.MANIFEST])
    replace = m.os.replace
    calls = []

    def interrupted(source, destination):
        calls.append(destination.name)
        if len(calls) == 2:
            raise OSError("interrupted before second target replacement")
        replace(source, destination)

    monkeypatch.setattr(m.os, "replace", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert not (root / m.EVIDENCE / "receipt.json").exists()
    for name, payload in original.items():
        assert (root / m.EVIDENCE / ("original-" + name)).read_bytes() == payload
    assert (folder / "summary.json").read_bytes() == original["summary.json"]
    assert (folder / m.MANIFEST).read_bytes() == original[m.MANIFEST]
    saved = inventory(root)
    with pytest.raises(ValueError, match="never overwrite"):
        m.correct(root, expected_manifest_sha256=expected, apply=True)
    assert inventory(root) == saved
