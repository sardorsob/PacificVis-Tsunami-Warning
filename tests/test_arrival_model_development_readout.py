"""Private-loader tests use an opaque fake reader and never open outcome files."""

# pyright: basic
import hashlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from analysis.arrival import model_development_readout as adapter

SOURCE = b"""GATE = "original-gate"
CONSUMED = ("original-source.py",)
SENTINEL = "unchanged"
def verify_report_sources(root):
    return (GATE, CONSUMED, SENTINEL)
def report(root, output):
    return (GATE, CONSUMED, root, output)
"""


@pytest.fixture
def reader(tmp_path, monkeypatch):
    path = tmp_path / adapter.READER
    path.parent.mkdir(parents=True)
    path.write_bytes(SOURCE)
    monkeypatch.setattr(adapter, "READER_SHA256", hashlib.sha256(SOURCE).hexdigest())
    return tmp_path, path


def test_private_instance_changes_only_binding_and_strengthens_sources(reader, monkeypatch):
    root, _ = reader
    canonical = ModuleType("analysis.arrival.model_development_completion_report")
    exec(compile(SOURCE, "synthetic", "exec"), canonical.__dict__)
    monkeypatch.setitem(sys.modules, canonical.__name__, canonical)
    private = adapter.load_reader(root)
    assert private is not canonical
    assert sys.modules[canonical.__name__] is canonical
    assert canonical.GATE == "original-gate" and canonical.CONSUMED == ("original-source.py",)
    assert private.GATE == adapter.REPORT_GATE
    assert set(private.CONSUMED) == {"original-source.py", adapter.SELF, adapter.TEST}
    assert private.SENTINEL == canonical.SENTINEL
    assert (
        private.verify_report_sources.__code__.co_code
        == canonical.verify_report_sources.__code__.co_code
    )
    assert private.verify_report_sources(root)[0] == adapter.REPORT_GATE


def test_private_loads_do_not_share_mutable_module_configuration(reader):
    root, _ = reader
    first, second = adapter.load_reader(root), adapter.load_reader(root)
    first.__dict__["GATE"] = "later mutation"
    assert first is not second and second.GATE == adapter.REPORT_GATE


def test_report_delegates_unchanged_reader_function(reader):
    root, _ = reader
    output = root / "never-written"
    result = adapter.report(root, output)
    assert result[0] == adapter.REPORT_GATE and result[-2:] == (root, output)
    assert not output.exists()


@pytest.mark.parametrize("fault", ["changed", "missing", "symlink"])
def test_untrusted_source_never_loads(reader, fault):
    root, path = reader
    if fault == "changed":
        path.write_bytes(SOURCE + b'raise AssertionError("must never execute")\n')
    elif fault == "missing":
        path.unlink()
    else:
        other = root / "alias.py"
        other.write_bytes(SOURCE)
        path.unlink()
        path.symlink_to(other)
    with pytest.raises(ValueError):
        adapter.load_reader(root)


def test_source_drift_after_execution_rejects_private_instance(reader, monkeypatch):
    root, path = reader
    original = adapter._reader_path
    calls = []

    def checked(project):
        if calls:
            path.write_bytes(SOURCE + b"# retained late drift\n")
        calls.append(project)
        return original(project)

    monkeypatch.setattr(adapter, "_reader_path", checked)
    with pytest.raises(ValueError, match="changed"):
        adapter.load_reader(root)
    assert path.read_bytes().endswith(b"# retained late drift\n")


def test_actual_contract_paths_and_trust_anchors():
    assert (
        adapter.READER_SHA256 == "fdb161e7a1b1bacddb4a3a2eee05ba04e03b7ed53c02840a9cb53150758f16be"
    )
    assert (
        adapter.FULL_REVIEW_SHA256
        == "3b7e50e44f41a8adbc4994f600cc30f22cc829a3569c38f75b4b5f01f3232ff9"
    )
    assert adapter.REPORT_GATE.endswith(
        "full-development-analysis-design-v1/review-acceptance.json"
    )
    assert Path(adapter.REPORT_GATE) != Path(adapter.FULL_REVIEW)
