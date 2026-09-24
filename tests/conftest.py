"""Shared, hermetic test fixtures.

Every test runs against tmp_path: no network, no production warehouse
(data/processed/sf_ems.duckdb), no real data/raw run directories other than
*reading* the two committed samples, and no files written to logs/ or
outputs/. Module-level path constants are monkeypatched per test because
each pipeline module binds its own copy at import time.
"""

import json
import logging
import shutil
from pathlib import Path

import pytest

import pipeline.chaos
import pipeline.extract
import pipeline.load
import pipeline.logging_utils
import pipeline.validate

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CALLS_RUN = REPO_ROOT / "data" / "raw" / "calls" / "run_ts=sample_day"
SAMPLE_CALLS_DAY_DIR = SAMPLE_CALLS_RUN / "2026-06-15"
SAMPLE_SCORECARD_RUN = REPO_ROOT / "data" / "raw" / "scorecard" / "run_ts=20260923T163928Z"


@pytest.fixture(autouse=True)
def _no_repo_logs(tmp_path, monkeypatch):
    """get_logger() writes logs/pipeline_<run_id>.log - redirect it for every test."""
    monkeypatch.setattr(pipeline.logging_utils, "LOG_DIR", tmp_path / "logs")


@pytest.fixture
def logger() -> logging.Logger:
    """A plain logger with no file handler (stage functions only need .info/.warning)."""
    return logging.getLogger("tests")


@pytest.fixture
def raw_dir(tmp_path, monkeypatch) -> Path:
    """An empty tmp data/raw, patched into every module that reads RAW_DATA_DIR."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for module in (pipeline.extract, pipeline.validate, pipeline.load, pipeline.chaos):
        monkeypatch.setattr(module, "RAW_DATA_DIR", raw)
    return raw


def make_raw_row(**overrides) -> dict:
    """One raw API row with every column the SQL models read, as the API sends it
    (timestamps and codes as strings). Override only what a test cares about."""
    row = {
        "call_number": "1", "unit_id": "M1", "incident_number": "100",
        "call_type": "Medical Incident", "call_type_group": "Potentially Life-Threatening",
        "received_dttm": "2026-01-01T00:00:00.000", "entry_dttm": "2026-01-01T00:00:30.000",
        "dispatch_dttm": "2026-01-01T00:01:00.000", "response_dttm": "2026-01-01T00:02:00.000",
        "on_scene_dttm": "2026-01-01T00:08:00.000", "transport_dttm": "2026-01-01T00:15:00.000",
        "hospital_dttm": "2026-01-01T00:25:00.000", "available_dttm": "2026-01-01T00:45:00.000",
        "call_final_disposition": "Code 3 Transport", "original_priority": "3", "priority": "3",
        "final_priority": "3", "unit_type": "MEDIC", "als_unit": True,
        "unit_sequence_in_call_dispatch": "1", "battalion": "B01", "station_area": "01",
        "supervisor_district": "1", "neighborhoods_analysis_boundaries": "Mission",
        "rowid": "1-M1", "data_as_of": "2026-01-02T00:00:00.000",
        "data_loaded_at": "2026-01-02T01:00:00.000",
    }
    row.update(overrides)
    return row


def write_page(directory: Path, rows: list[dict], name: str = "page_0000.json") -> Path:
    """Write one raw page exactly as extract.py would save it."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def write_manifest(directory: Path, rows_received: int, complete: bool = True, **extra) -> Path:
    """Write a manifest.json with the fields validate.py and chaos.py read."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    manifest = {"source": "calls", "rows_expected": rows_received, "rows_received": rows_received,
                "pages_written": 1, "complete": complete, **extra}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def copy_sample_calls(raw: Path, run_ts: str, scope_dir: str = "2026-06-15") -> Path:
    """Copy the committed single-day calls sample into <raw>/calls/run_ts=<run_ts>/<scope_dir>/."""
    dest = raw / "calls" / f"run_ts={run_ts}" / scope_dir
    shutil.copytree(SAMPLE_CALLS_DAY_DIR, dest)
    return dest


def copy_sample_scorecard(raw: Path, run_ts: str) -> Path:
    """Copy the committed scorecard pull into <raw>/scorecard/run_ts=<run_ts>/."""
    dest = raw / "scorecard" / f"run_ts={run_ts}"
    shutil.copytree(SAMPLE_SCORECARD_RUN, dest)
    return dest
