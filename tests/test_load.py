"""Hermetic tests for pipeline/load.py - upsert idempotency, late-arriving
updates and in-batch dedupe (CLAUDE.md rule 7), plus the priority map and the
SQL transform chain, all on tiny raw pages written to tmp_path.
"""

import duckdb
import pytest

from pipeline.load import load_priority_map, run_transform, upsert_calls
from tests.conftest import make_raw_row, write_page


def glob_for(directory) -> str:
    return str(directory / "page_*.json")


def available_for(con: duckdb.DuckDBPyConnection, rowid: str) -> str:
    """available_dttm as 'YYYY-MM-DD HH:MM:SS' - raw_calls keeps the API's text, so cast to compare."""
    value = con.execute(
        "SELECT CAST(available_dttm AS TIMESTAMP) FROM raw_calls WHERE rowid = ?", [rowid]
    ).fetchone()[0]
    return str(value)


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


class TestUpsertIdempotency:
    def test_loading_the_same_pages_twice_gives_the_same_rows(self, con, tmp_path, logger):
        pull = tmp_path / "pull"
        write_page(pull, [make_raw_row(rowid=f"{i}-M1", call_number=str(i)) for i in range(3)])

        first = upsert_calls(con, glob_for(pull), logger)
        snapshot = con.execute("SELECT * FROM raw_calls ORDER BY rowid").fetchall()
        second = upsert_calls(con, glob_for(pull), logger)

        assert first == second == 3
        assert con.execute("SELECT * FROM raw_calls ORDER BY rowid").fetchall() == snapshot

    def test_overlapping_pull_adds_only_new_rowids(self, con, tmp_path, logger):
        write_page(tmp_path / "a", [make_raw_row(rowid="1-M1"), make_raw_row(rowid="2-M1")])
        write_page(tmp_path / "b", [make_raw_row(rowid="2-M1"), make_raw_row(rowid="3-M1")])
        upsert_calls(con, glob_for(tmp_path / "a"), logger)
        assert upsert_calls(con, glob_for(tmp_path / "b"), logger) == 3


class TestLateUpdate:
    ROWID = "1-M1"

    def _load(self, con, directory, logger, loaded_at: str, available: str) -> None:
        write_page(directory, [make_raw_row(rowid=self.ROWID, data_loaded_at=loaded_at, available_dttm=available)])
        upsert_calls(con, glob_for(directory), logger)

    def test_newer_data_loaded_at_overwrites(self, con, tmp_path, logger):
        self._load(con, tmp_path / "v1", logger, "2026-01-02T01:00:00.000", "2026-01-01T00:45:00.000")
        self._load(con, tmp_path / "v2", logger, "2026-01-05T01:00:00.000", "2026-01-01T00:50:00.000")
        assert available_for(con, self.ROWID).startswith("2026-01-01 00:50:00")
        assert con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0] == 1

    def test_older_data_loaded_at_does_not_overwrite(self, con, tmp_path, logger):
        """Loading an old pull after a new one must not roll a correction back."""
        self._load(con, tmp_path / "v2", logger, "2026-01-05T01:00:00.000", "2026-01-01T00:50:00.000")
        self._load(con, tmp_path / "v1", logger, "2026-01-02T01:00:00.000", "2026-01-01T00:45:00.000")
        assert available_for(con, self.ROWID).startswith("2026-01-01 00:50:00")


class TestInBatchDuplicates:
    @pytest.mark.parametrize("newest_first", [True, False])
    def test_duplicate_rowid_in_one_batch_keeps_latest(self, con, tmp_path, logger, newest_first):
        """duplicate_rowid chaos: without the QUALIFY, DuckDB keeps an arbitrary copy
        (verified: the OLDER one) - order within the page must not matter."""
        old = make_raw_row(data_loaded_at="2026-01-02T01:00:00.000", available_dttm="2026-01-01T00:45:00.000")
        new = make_raw_row(data_loaded_at="2026-01-05T01:00:00.000", available_dttm="2026-01-01T00:50:00.000")
        write_page(tmp_path / "p", [new, old] if newest_first else [old, new])

        assert upsert_calls(con, glob_for(tmp_path / "p"), logger) == 1
        assert available_for(con, "1-M1").startswith("2026-01-01 00:50:00")


class TestSchemaDriftBetweenPulls:
    def test_later_pull_missing_an_optional_column_still_loads(self, con, tmp_path, logger):
        write_page(tmp_path / "first", [make_raw_row(rowid="1-M1", box="6651")])
        upsert_calls(con, glob_for(tmp_path / "first"), logger)
        write_page(tmp_path / "later", [make_raw_row(rowid="2-M1")])  # no row has `box`
        assert upsert_calls(con, glob_for(tmp_path / "later"), logger) == 2


class TestPriorityMap:
    def test_every_configured_code_is_loaded(self, con, logger):
        n = load_priority_map(con, logger)
        assert n == con.execute("SELECT COUNT(*) FROM dim_priority_map").fetchone()[0] == 10

    def test_only_codes_2_and_3_are_confirmed(self, con, logger):
        """Only 2/3 have a primary source (dataset metadata); every letter code is unconfirmed."""
        load_priority_map(con, logger)
        confirmed = con.execute("SELECT code FROM dim_priority_map WHERE confirmed_by_owner ORDER BY code").fetchall()
        assert [c for (c,) in confirmed] == ["2", "3"]

    def test_blank_code_is_stored_as_empty_string(self, con, logger):
        load_priority_map(con, logger)
        assert con.execute("SELECT COUNT(*) FROM dim_priority_map WHERE code = ''").fetchone()[0] == 1


class TestRunTransform:
    def test_builds_staging_and_fact_tables(self, con, tmp_path, logger):
        rows = [
            make_raw_row(call_number="1", unit_id="M1", rowid="1-M1", unit_type="MEDIC"),
            make_raw_row(call_number="1", unit_id="E1", rowid="1-E1", unit_type="ENGINE",
                         on_scene_dttm="2026-01-01T00:04:00.000", transport_dttm=None,
                         hospital_dttm=None, unit_sequence_in_call_dispatch="2"),
            make_raw_row(call_number="2", unit_id="M2", rowid="2-M2", original_priority=""),
        ]
        write_page(tmp_path / "p", rows)
        upsert_calls(con, glob_for(tmp_path / "p"), logger)
        run_transform(con, logger)

        assert con.execute("SELECT COUNT(*) FROM stg_unit_response").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM fct_call").fetchone()[0] == 2
        first_medic, first_any, n_units = con.execute(
            "SELECT first_medic_on_scene_dttm, first_any_unit_on_scene_dttm, n_units FROM fct_call WHERE call_number = '1'"
        ).fetchone()
        assert (str(first_medic), str(first_any), n_units) == ("2026-01-01 00:08:00", "2026-01-01 00:04:00", 2)
        # Blank priority is NULLed in staging, so it joins to dim_priority_map via COALESCE(.., '').
        assert con.execute("SELECT original_priority FROM stg_unit_response WHERE rowid = '2-M2'").fetchone()[0] is None
        # fct_unit_event: every non-null lifecycle timestamp is one event row (8 + 6 + 8).
        assert con.execute("SELECT COUNT(*) FROM fct_unit_event").fetchone()[0] == 22
