"""Hermetic unit tests for pipeline/metrics.py's KPI definition logic and
config/kpi_definitions.yaml's structure - synthetic in-memory fixtures only.
"""

import duckdb
import pandas as pd

from pipeline.metrics import (
    UNIT_SCOPE_COLUMN,
    _priority_predicate,
    compute_m1_definition_monthly,
    load_kpi_definitions,
)

KPI_DEFS = load_kpi_definitions()

FCT_CALL_COLUMNS = [
    "call_number", "received_dttm", "dispatch_dttm", "original_priority", "final_priority",
    "call_type_group", "first_medic_on_scene_dttm", "first_ambulance_on_scene_dttm",
    "first_any_unit_on_scene_dttm",
]
TIMESTAMP_COLUMNS = {
    "received_dttm", "dispatch_dttm", "first_medic_on_scene_dttm",
    "first_ambulance_on_scene_dttm", "first_any_unit_on_scene_dttm",
}

DEFINITION = {
    "id": "test_def", "clock_start_field": "dispatch_dttm",
    "priority_field": "original_priority", "priority_values": ["3"], "unit_scope": "medic_only",
}


def make_fct_call_con(rows: list[dict]) -> duckdb.DuckDBPyConnection:
    """Build an in-memory fct_call table. Timestamp-like columns are parsed to
    real datetimes (pd.to_datetime) - the production fct_call has TIMESTAMP
    columns (cast in stg_unit_response.sql), and leaving these as plain
    strings would make DuckDB infer VARCHAR, which breaks date_diff() the
    same way a schema mismatch would in production."""
    normalized = [{c: r.get(c) for c in FCT_CALL_COLUMNS} for r in rows]
    df = pd.DataFrame(normalized, columns=FCT_CALL_COLUMNS)
    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col])
    con = duckdb.connect()
    con.register("df", df)
    con.execute("CREATE TABLE fct_call AS SELECT * FROM df")
    return con


class TestKpiDefinitionsConfig:
    def test_every_definition_has_required_fields(self):
        for d in KPI_DEFS["m1_candidate_definitions"]:
            for field in ("id", "label", "clock_start_field", "priority_field",
                          "priority_values", "unit_scope", "owner", "confirmed_by_owner"):
                assert field in d, f"{d.get('id')} missing {field}"

    def test_every_unit_scope_is_a_known_column(self):
        for d in KPI_DEFS["m1_candidate_definitions"]:
            assert d["unit_scope"] in UNIT_SCOPE_COLUMN

    def test_no_definition_is_pre_confirmed(self):
        """docs/assumptions.md: nothing is confirmed by a real EMS Agency owner yet.
        This test exists so nobody flips the flag without also updating the docs."""
        for d in KPI_DEFS["m1_candidate_definitions"]:
            assert d["confirmed_by_owner"] is False

    def test_definition_ids_are_unique(self):
        ids = [d["id"] for d in KPI_DEFS["m1_candidate_definitions"]]
        assert len(ids) == len(set(ids))


class TestPriorityPredicate:
    def test_builds_valid_in_clause(self):
        definition = {"priority_field": "original_priority", "priority_values": ["3", "E"]}
        assert _priority_predicate(definition) == "original_priority IN ('3', 'E')"


class TestComputeM1:
    def test_within_target_counts_as_numerator(self):
        rows = [{
            "call_number": "1", "received_dttm": "2026-01-01T00:00:00",
            "dispatch_dttm": "2026-01-01T00:00:00", "original_priority": "3",
            "first_medic_on_scene_dttm": "2026-01-01T00:09:00",
        }]
        con = make_fct_call_con(rows)
        result = compute_m1_definition_monthly(con, DEFINITION, target_minutes=10)
        assert result[0]["numerator"] == 1
        assert result[0]["denominator"] == 1
        assert result[0]["pct"] == 1.0

    def test_beyond_target_excluded_from_numerator_not_denominator(self):
        rows = [{
            "call_number": "1", "received_dttm": "2026-01-01T00:00:00",
            "dispatch_dttm": "2026-01-01T00:00:00", "original_priority": "3",
            "first_medic_on_scene_dttm": "2026-01-01T00:11:00",
        }]
        con = make_fct_call_con(rows)
        result = compute_m1_definition_monthly(con, DEFINITION, target_minutes=10)
        assert result[0]["numerator"] == 0
        assert result[0]["denominator"] == 1

    def test_no_arrival_excluded_from_denominator(self):
        """The core M1 modeling rule (docs/assumptions.md 5b): a call with no
        recorded on-scene arrival is excluded from the ratio entirely, not
        counted as an automatic miss."""
        rows = [{
            "call_number": "1", "received_dttm": "2026-01-01T00:00:00",
            "dispatch_dttm": "2026-01-01T00:00:00", "original_priority": "3",
            "first_medic_on_scene_dttm": None,
        }]
        con = make_fct_call_con(rows)
        result = compute_m1_definition_monthly(con, DEFINITION, target_minutes=10)
        assert result[0]["denominator"] == 0
        assert result[0]["excluded_no_arrival"] == 1
        assert result[0]["pct"] is None

    def test_priority_filter_excludes_non_matching_calls(self):
        rows = [{
            "call_number": "1", "received_dttm": "2026-01-01T00:00:00",
            "dispatch_dttm": "2026-01-01T00:00:00", "original_priority": "2",
            "first_medic_on_scene_dttm": "2026-01-01T00:05:00",
        }]
        con = make_fct_call_con(rows)
        result = compute_m1_definition_monthly(con, DEFINITION, target_minutes=10)
        assert result[0]["denominator"] == 0

    def test_unit_scope_selects_correct_column(self):
        """A call with only an ENGINE arriving should count under any_unit but not medic_only."""
        rows = [{
            "call_number": "1", "received_dttm": "2026-01-01T00:00:00",
            "dispatch_dttm": "2026-01-01T00:00:00", "original_priority": "3",
            "first_medic_on_scene_dttm": None,
            "first_any_unit_on_scene_dttm": "2026-01-01T00:03:00",
        }]
        con = make_fct_call_con(rows)
        medic_only_result = compute_m1_definition_monthly(con, dict(DEFINITION, unit_scope="medic_only"), target_minutes=10)
        any_unit_result = compute_m1_definition_monthly(con, dict(DEFINITION, unit_scope="any_unit"), target_minutes=10)
        assert medic_only_result[0]["denominator"] == 0
        assert any_unit_result[0]["denominator"] == 1
        assert any_unit_result[0]["numerator"] == 1
