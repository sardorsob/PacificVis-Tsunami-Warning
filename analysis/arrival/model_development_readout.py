"""Isolate the frozen saved-table reader behind a reviewed readout-only Gate."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ART = "artifacts/models/arrival-timing/"
REPORT_GATE = ART + "full-development-analysis-design-v1/review-acceptance.json"
READER = "analysis/arrival/model_development_completion_report.py"
READER_SHA256 = "fdb161e7a1b1bacddb4a3a2eee05ba04e03b7ed53c02840a9cb53150758f16be"
FULL_REVIEW = ART + "full-development-v1/review-acceptance.json"
FULL_REVIEW_SHA256 = "3b7e50e44f41a8adbc4994f600cc30f22cc829a3569c38f75b4b5f01f3232ff9"
SELF = "analysis/arrival/model_development_readout.py"
TEST = "tests/test_arrival_model_development_readout.py"


def _reader_path(root: Path) -> Path:
    path = Path(root).resolve() / READER
    if path.resolve() != path or not path.is_file():
        raise ValueError("literal frozen reader source required")
    if hashlib.sha256(path.read_bytes()).hexdigest() != READER_SHA256:
        raise ValueError("frozen reader source changed")
    return path


def load_reader(root: Path) -> ModuleType:
    """Load fresh private globals; change only its Gate and stronger source closure."""
    path = _reader_path(root)
    spec = importlib.util.spec_from_file_location("_arrival_development_saved_table_readout", path)
    if spec is None or spec.loader is None:
        raise ValueError("frozen reader loader unavailable")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    _reader_path(root)
    reader.__dict__["GATE"] = REPORT_GATE
    reader.__dict__["CONSUMED"] = tuple(sorted(set(reader.CONSUMED) | {SELF, TEST}))
    return reader


def report(root: Path, output: Path):
    return load_reader(root).report(root, output)
