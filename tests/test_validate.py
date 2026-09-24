"""Hermetic unit tests for pipeline/validate.py - synthetic in-memory fixtures
only, no network access or real data pull required, so these run in seconds
and don't depend on data.sf.gov being reachable.
"""

import copy
import json
from datetime import datetime, timedelta, timezone

import duckdb
import pandas as pd
import pytest

from pipeline.validate import (
    _severity_for_rate,
    check_freshness,
    check_manifest_completeness,
    check_null_rates,
    check_outliers_p999,
    check_priority_domain,
    check_rowid_uniqueness,
    check_schema,
    check_timestamp_order,
    load_calls_view,
    load_rules,
    parse_interval_field,
    run_validation,
)
from tests.conftest import make_raw_row, write_manifest, write_page

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


def _utc_naive_iso(hours_ago: float) -> str:
    """A naive UTC timestamp string, the way the API sends them."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S")


class TestTimestampOrderSmallSample:
    @staticmethod
    def _rows_with_one_violation(n_ok: int) -> list[dict]:
        bad = dict(BASE_ROW, dispatch_dttm="2026-01-01T00:05:00", response_dttm="2026-01-01T00:01:00")
        return [bad] + [dict(BASE_ROW, rowid=f"ok-{i}", call_number=f"ok-{i}") for i in range(n_ok)]

    @staticmethod
    def _dispatch_response(results):
        return next(r for r in results if r.metric["pair"] == "dispatch_dttm_before_response_dttm")

    def test_high_rate_on_small_sample_is_capped_at_warn(self):
        """1/10 = 10% is far above fail_above (1%), but 10 pairs is below
        min_pairs_for_fail - a 3-day --since pull must not be stopped by noise."""
        result = self._dispatch_response(check_timestamp_order(make_con(self._rows_with_one_violation(9)), RULES))
        assert result.severity == "WARN"
        assert result.metric["capped_small_sample"] is True
        assert "capped at WARN" in result.action

    def test_same_rate_fails_when_min_pairs_is_small(self):
        """The cap is a sample-size guard, not a way to disable the FAIL."""
        rules = copy.deepcopy(RULES)
        rules["timestamp_order_violation_rate"]["min_pairs_for_fail"] = 5
        result = self._dispatch_response(check_timestamp_order(make_con(self._rows_with_one_violation(9)), rules))
        assert result.severity == "FAIL"
        assert result.metric["capped_small_sample"] is False


class TestOutliersP999:
    def test_parse_interval_field_splits_columns(self):
        assert parse_interval_field("received_dttm_to_dispatch_dttm_minutes") == ("received_dttm", "dispatch_dttm")

    @pytest.mark.parametrize("bad_name", ["received_dttm_dispatch_dttm_minutes", "received_dttm_to_dispatch_dttm"])
    def test_badly_named_config_field_raises(self, bad_name):
        with pytest.raises(ValueError, match="must be named"):
            parse_interval_field(bad_name)

    def test_extreme_interval_is_flagged_for_review(self):
        rows = [dict(BASE_ROW, rowid=str(i), call_number=str(i)) for i in range(1000)]
        rows[0]["hospital_dttm"] = "2025-12-31T00:00:00"  # 24h40m before available_dttm
        rules = dict(RULES, outlier_p999_fields=["hospital_dttm_to_available_dttm_minutes"])
        [result] = check_outliers_p999(make_con(rows), rules)
        assert result.severity == "WARN"
        assert result.metric["rows_measured"] == 1000
        assert result.metric["rows_above_p999"] == 1
        assert result.metric["max_minutes"] == pytest.approx(24 * 60 + 40)

    def test_identical_intervals_pass(self):
        rows = [dict(BASE_ROW, rowid=str(i), call_number=str(i)) for i in range(50)]
        rules = dict(RULES, outlier_p999_fields=["received_dttm_to_dispatch_dttm_minutes"])
        [result] = check_outliers_p999(make_con(rows), rules)
        assert result.severity == "PASS"
        assert result.metric["rows_above_p999"] == 0


class TestFreshness:
    def test_empty_table_fails(self, logger):
        """An empty pull must never be published as current."""
        result = check_freshness(make_con([]), RULES, logger)
        assert result.severity == "FAIL"
        assert result.metric["max_received_dttm"] is None

    def test_historical_backfill_passes_as_not_applicable(self, logger):
        result = check_freshness(make_con([BASE_ROW]), RULES, logger)
        assert result.severity == "PASS"
        assert "not applicable" in result.metric["note"]

    def test_recent_pull_freshly_loaded_passes(self, logger):
        row = dict(BASE_ROW, received_dttm=_utc_naive_iso(2), data_loaded_at=_utc_naive_iso(1))
        result = check_freshness(make_con([row]), RULES, logger)
        assert result.severity == "PASS"
        assert result.metric["age_hours"] < 2

    def test_recent_pull_with_stale_data_loaded_at_fails(self, logger):
        """The stale_data chaos scenario: recent calls, but DataSF hasn't reloaded in 100h."""
        row = dict(BASE_ROW, received_dttm=_utc_naive_iso(2), data_loaded_at=_utc_naive_iso(100))
        result = check_freshness(make_con([row]), RULES, logger)
        assert result.severity == "FAIL"
        assert result.metric["age_hours"] >= RULES["freshness"]["max_data_loaded_at_age_hours"]


class TestManifestCompleteness:
    @staticmethod
    def _check(run_ts: str = "r1"):
        con = duckdb.connect()
        load_calls_view(con, run_ts)
        return check_manifest_completeness(run_ts, con)

    def test_manifest_matching_disk_passes(self, raw_dir):
        month_dir = raw_dir / "calls" / "run_ts=r1" / "2026-06"
        write_page(month_dir, [make_raw_row(rowid=f"{i}-M1") for i in range(3)])
        write_manifest(month_dir, rows_received=3, month="2026-06")
        result = self._check()
        assert result.severity == "PASS"
        assert result.metric["actual_rows_on_disk"] == 3

    def test_manifest_disagreeing_with_disk_fails(self, raw_dir):
        """truncated_pagination: extract claimed 5 rows, only 3 are readable on disk."""
        month_dir = raw_dir / "calls" / "run_ts=r1" / "2026-06"
        write_page(month_dir, [make_raw_row(rowid=f"{i}-M1") for i in range(3)])
        write_manifest(month_dir, rows_received=5, month="2026-06")
        result = self._check()
        assert result.severity == "FAIL"
        assert (result.metric["manifest_total_rows"], result.metric["actual_rows_on_disk"]) == (5, 3)

    def test_manifest_flagged_incomplete_fails_even_if_counts_match(self, raw_dir):
        month_dir = raw_dir / "calls" / "run_ts=r1" / "2026-06"
        write_page(month_dir, [make_raw_row()])
        write_manifest(month_dir, rows_received=1, complete=False, month="2026-06")
        result = self._check()
        assert result.severity == "FAIL"
        assert result.metric["months_flagged_incomplete_at_extract"] == ["2026-06"]


class TestRunValidationSchemaShortCircuit:
    def test_missing_required_column_fails_cleanly_without_crashing(self, raw_dir, logger):
        """Every later check queries named columns; after a schema FAIL they must be
        skipped (the run still FAILs), not crash on an unbound column."""
        month_dir = raw_dir / "calls" / "run_ts=r1" / "2026-06"
        rows = [make_raw_row(rowid=f"{i}-M1") for i in range(3)]
        for r in rows:
            r.pop("on_scene_dttm")
        write_page(month_dir, rows)
        write_manifest(month_dir, rows_received=3, month="2026-06")

        report = run_validation("r1", logger, scope="test")
        assert report["overall_status"] == "FAIL"
        assert [c["rule_id"] for c in report["checks"]] == ["manifest_completeness", "schema_required_columns"]
        assert report["checks"][1]["metric"]["missing"] == ["on_scene_dttm"]
        assert report["profile"]["unit_rows"] == 3
        assert "skipped" in report["profile"]["note"]
        json.dumps(report, default=str)  # must stay serialisable for write_report
