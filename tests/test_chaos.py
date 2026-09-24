"""Hermetic tests for pipeline/chaos.py: each scenario mutates a tmp raw page
exactly as its docstring claims, so a --chaos run tests the check it names.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.chaos import SCENARIOS, first_row_rowid
from tests.conftest import make_raw_row, write_manifest, write_page

RUN_TS, SCOPE = "chaos_run", "2026-06"


@pytest.fixture
def pull(raw_dir):
    """A 4-row raw page + matching manifest under the tmp RAW_DATA_DIR."""
    scope_dir = raw_dir / "calls" / f"run_ts={RUN_TS}" / SCOPE
    rows = [make_raw_row(rowid=f"{i}-M1", call_number=str(i)) for i in range(4)]
    write_page(scope_dir, rows)
    write_manifest(scope_dir, rows_received=4, month=SCOPE)
    return scope_dir


def page_rows(scope_dir) -> list[dict]:
    return json.loads((scope_dir / "page_0000.json").read_text())


def manifest(scope_dir) -> dict:
    return json.loads((scope_dir / "manifest.json").read_text())


class TestChaosScenarios:
    def test_every_scenario_is_registered(self):
        assert set(SCENARIOS) == {"missing_column", "duplicate_rowid", "stale_data",
                                  "truncated_pagination", "late_update"}

    def test_missing_column_drops_on_scene_from_every_row(self, pull):
        SCENARIOS["missing_column"](RUN_TS, SCOPE)
        assert all("on_scene_dttm" not in r for r in page_rows(pull))

    def test_duplicate_rowid_bumps_manifest_to_match(self, pull):
        """Isolates rowid_uniqueness: manifest and disk still agree (5 == 5)."""
        SCENARIOS["duplicate_rowid"](RUN_TS, SCOPE)
        rows = page_rows(pull)
        assert len(rows) == 5
        assert rows[-1] == rows[0]
        assert manifest(pull)["rows_received"] == 5

    def test_truncated_pagination_leaves_manifest_unchanged(self, pull):
        """Disk now disagrees with the manifest - that disagreement is the thing under test."""
        SCENARIOS["truncated_pagination"](RUN_TS, SCOPE)
        assert len(page_rows(pull)) == 2
        assert manifest(pull)["rows_received"] == 4

    def test_stale_data_sets_every_data_loaded_at_100h_ago(self, pull):
        SCENARIOS["stale_data"](RUN_TS, SCOPE)
        loaded = {r["data_loaded_at"] for r in page_rows(pull)}
        assert len(loaded) == 1
        stale = datetime.strptime(loaded.pop(), "%Y-%m-%dT%H:%M:%S.000").replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - stale
        assert timedelta(hours=99) < age < timedelta(hours=101)

    def test_late_update_amends_only_the_first_row(self, pull):
        before = page_rows(pull)
        SCENARIOS["late_update"](RUN_TS, SCOPE)
        after = page_rows(pull)
        assert after[0]["available_dttm"] == after[0]["data_loaded_at"] != before[0]["data_loaded_at"]
        assert after[1:] == before[1:]
        assert first_row_rowid(RUN_TS, SCOPE) == "0-M1"

    def test_missing_page_raises_clear_error(self, raw_dir):
        with pytest.raises(FileNotFoundError, match="no raw pages found"):
            SCENARIOS["missing_column"](RUN_TS, "no-such-scope")
