"""Hermetic unit tests for pipeline/validate.py - synthetic in-memory fixtures
only, no network access or real data pull required, so these run in seconds
and don't depend on data.sf.gov being reachable.
"""

import duckdb
import pandas as pd

from pipeline.validate import (
    _severity_for_rate,
    check_null_rates,
    check_priority_domain,
    check_rowid_uniqueness,
    check_schema,
    check_timestamp_order,
    load_rules,
)

RULES = load_rules()
# Union of required_columns and every field the timestamp-order pairs touch -
# validate.py's checks reference columns beyond the "required" set (e.g.
# transport_dttm/hospital_dttm aren't required-present, but check_timestamp_order
# still needs them to exist in the table).
_PAIR_COLUMNS = {c for pair in RULES["timestamp_order_pairs"] for c in pair}
ALL_COLUMNS = list(dict.fromkeys(RULES["required_columns"] + sorted(_PAIR_COLUMNS)))
TIMESTAMP_COLUMNS = {c for c in ALL_COLUMNS if c.endswith("_dttm") or c in ("data_as_of", "data_loaded_at")}

BASE_ROW = {
    "call_number": "1", "unit_id": "M1", "incident_number": "1",
    "received_dttm": "2026-01-01T00:00:00", "entry_dttm": "2026-01-01T00:00:00",
    "dispatch_dttm": "2026-01-01T00:01:00", "response_dttm": "2026-01-01T00:02:00",
    "on_scene_dttm": "2026-01-01T00:08:00", "transport_dttm": "2026-01-01T00:09:00",
    "hospital_dttm": "2026-01-01T00:20:00", "call_final_disposition": "Code 3 Transport",
    "available_dttm": "2026-01-01T00:40:00", "original_priority": "3", "priority": "3",
    "final_priority": "3", "call_type_group": "Potentially Life-Threatening",
    "unit_type": "MEDIC", "rowid": "1-M1", "data_as_of": "2026-01-01T00:40:00",
    "data_loaded_at": "2026-01-01T00:41:00",
}


def make_con(rows: list[dict]) -> duckdb.DuckDBPyConnection:
    """Build an in-memory raw_calls table from row dicts, filling any unspecified
    column with None so tests only need to set what they care about."""
    normalized = [{c: r.get(c) for c in ALL_COLUMNS} for r in rows]
    df = pd.DataFrame(normalized, columns=ALL_COLUMNS)
    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col])
    con = duckdb.connect()
    con.register("df", df)
    con.execute("CREATE TABLE raw_calls AS SELECT * FROM df")
    return con


class TestSeverityForRate:
    def test_below_warn_is_pass(self):
        assert _severity_for_rate(0.01, warn_above=0.05, fail_above=0.40) == "PASS"

    def test_between_warn_and_fail_is_warn(self):
        assert _severity_for_rate(0.10, warn_above=0.05, fail_above=0.40) == "WARN"

    def test_at_or_above_fail_is_fail(self):
        assert _severity_for_rate(0.40, warn_above=0.05, fail_above=0.40) == "FAIL"

    def test_boundary_at_warn_above_is_warn_not_pass(self):
        assert _severity_for_rate(0.05, warn_above=0.05, fail_above=0.40) == "WARN"


class TestSchemaCheck:
    def test_all_columns_present_passes(self):
        con = make_con([BASE_ROW])
        result = check_schema(con, RULES)
        assert result.severity == "PASS"
        assert result.metric["missing"] == []

    def test_missing_column_fails(self):
        con = make_con([BASE_ROW])
        con.execute("ALTER TABLE raw_calls DROP COLUMN on_scene_dttm")
        result = check_schema(con, RULES)
        assert result.severity == "FAIL"
        assert "on_scene_dttm" in result.metric["missing"]


class TestRowidUniqueness:
    def test_unique_rowids_pass(self):
        rows = [dict(BASE_ROW, rowid=f"{i}-M1", call_number=str(i)) for i in range(3)]
        con = make_con(rows)
        result = check_rowid_uniqueness(con)
        assert result.severity == "PASS"
        assert result.metric["duplicate_rows"] == 0

    def test_duplicate_rowid_warns_not_fails(self):
        """CLAUDE.md's chaos spec: duplicate rowid -> WARN + dedupe, not FAIL."""
        rows = [BASE_ROW, dict(BASE_ROW)]
        con = make_con(rows)
        result = check_rowid_uniqueness(con)
        assert result.severity == "WARN"
        assert result.metric["duplicate_rows"] == 1


class TestTimestampOrder:
    def test_in_order_timestamps_pass(self):
        con = make_con([BASE_ROW])
        results = check_timestamp_order(con, RULES)
        assert all(r.severity == "PASS" for r in results)

    def test_out_of_order_timestamp_is_flagged(self):
        bad_row = dict(BASE_ROW, dispatch_dttm="2026-01-01T00:05:00", response_dttm="2026-01-01T00:01:00")
        rows = [bad_row] + [dict(BASE_ROW, rowid=f"ok-{i}", call_number=f"ok-{i}") for i in range(50)]
        con = make_con(rows)
        results = check_timestamp_order(con, RULES)
        dispatch_response = next(r for r in results if r.metric["pair"] == "dispatch_dttm_before_response_dttm")
        assert dispatch_response.metric["violations"] == 1


class TestPriorityDomain:
    def test_known_codes_warn_with_no_unexpected(self):
        """Always WARN by design - the letter/original_priority mapping is unconfirmed
        by any owner regardless of whether the specific codes seen are already known."""
        con = make_con([BASE_ROW])
        result = check_priority_domain(con, RULES)
        assert result.severity == "WARN"
        assert result.metric["unexpected_values"] == {}

    def test_unknown_code_is_flagged_as_unexpected(self):
        con = make_con([dict(BASE_ROW, original_priority="Z")])
        result = check_priority_domain(con, RULES)
        assert "Z" in result.metric["unexpected_values"]


class TestNullRates:
    def test_low_null_rate_passes(self):
        rows = [dict(BASE_ROW, rowid=str(i), call_number=str(i)) for i in range(100)]
        con = make_con(rows)
        results = check_null_rates(con, RULES)
        on_scene_check = next(r for r in results if r.rule_id == "null_rate_on_scene_dttm")
        assert on_scene_check.severity == "PASS"

    def test_high_null_rate_fails(self):
        rows = [dict(BASE_ROW, rowid=str(i), call_number=str(i), on_scene_dttm=None) for i in range(100)]
        con = make_con(rows)
        results = check_null_rates(con, RULES)
        on_scene_check = next(r for r in results if r.rule_id == "null_rate_on_scene_dttm")
        assert on_scene_check.severity == "FAIL"
