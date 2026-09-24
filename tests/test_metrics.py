"""Hermetic tests for pipeline/metrics.py's reconciliation, M5 gap, scope-month
summary, CSV writer and official-scorecard reader. Pure-Python inputs where
the function allows it; a tiny in-memory DuckDB table otherwise.
"""

import csv
import io

import duckdb
import pytest

from pipeline.metrics import (
    build_scope_month_summary,
    compute_m5_definition_gap,
    get_official_scorecard,
    kpi_monthly_csv,
    latest_month,
    reconcile_m1,
)

PAIR = {"dispatch_clock": "disp_amb", "received_clock": "recv_amb"}
TWIN = {"dispatch_clock": "disp_medic", "received_clock": "recv_medic"}


def m1_row(definition_id: str, month: str, pct, numerator: int = 0, denominator: int = 0) -> dict:
    return {"definition_id": definition_id, "month": month, "numerator": numerator,
            "denominator": denominator, "pct": pct, "excluded_no_arrival": 0}


class TestReconcileM1:
    def test_mean_absolute_gap_over_months_with_both_values(self):
        rows = [m1_row("a", "2026-05", 0.80), m1_row("a", "2026-06", 0.95), m1_row("a", "2026-07", 0.70)]
        official = {"2026-05": 0.90, "2026-06": 0.90}  # 2026-07 has no official actual yet
        assert reconcile_m1(rows, official) == {"a": {"months_compared": 2, "mean_absolute_gap": 0.075}}

    def test_month_with_empty_denominator_is_not_compared(self):
        rows = [m1_row("a", "2026-05", None)]
        assert reconcile_m1(rows, {"2026-05": 0.9}) == {"a": {"months_compared": 0, "mean_absolute_gap": None}}


class TestM5DefinitionGap:
    def test_configured_pair_and_twin_gaps_in_points(self):
        rows = [
            m1_row("disp_amb", "2026-06", 0.90), m1_row("recv_amb", "2026-06", 0.75),
            m1_row("disp_medic", "2026-06", 0.88), m1_row("recv_medic", "2026-06", 0.70),
        ]
        [gap] = compute_m5_definition_gap(rows, {"2026-06": 0.884}, PAIR, TWIN)
        assert gap["clock_gap_points"] == 15.0
        assert gap["best_fit_twin_gap_points"] == 18.0
        assert gap["official_vs_dispatch_gap_points"] == pytest.approx(-1.6)
        assert gap["m1_dispatch_clock_pct"] == 0.90

    def test_missing_side_gives_none_not_a_guess(self):
        rows = [m1_row("disp_amb", "2026-06", 0.90), m1_row("recv_amb", "2026-06", None)]
        [gap] = compute_m5_definition_gap(rows, {}, PAIR, TWIN)
        assert gap["clock_gap_points"] is None
        assert gap["best_fit_twin_gap_points"] is None
        assert gap["official_pct"] is None


class TestLatestMonth:
    def test_picks_latest(self):
        assert latest_month([m1_row("a", "2026-05", 0.9), m1_row("a", "2026-06", 0.9)]) == "2026-06"

    def test_empty_warehouse_is_none(self):
        assert latest_month([]) is None


def make_metrics(official: dict, best: str = "a") -> dict:
    """The subset of run_metrics' output that build_scope_month_summary reads."""
    return {
        "official_scorecard_by_month": official,
        "target_pct": 0.90,
        "target_minutes": 10,
        "m1_reconciliation": {"a": {"months_compared": 1, "mean_absolute_gap": 0.02}},
        "m1_definitions": [{"id": "a", "label": "Def A"}],
        "m1_kpi_monthly": [m1_row("a", "2026-05", 0.85, 85, 100), m1_row("a", "2026-06", 0.92, 92, 100)],
        "m1_best_fitting_definition": best,
        "m2_call_processing_p50_p90": [{"month": "2026-06", "p50_minutes": 1.5}],
        "m3_travel_time_p50_p90": [],
        "m4_hospital_turnaround": [],
        "m5_definition_gap": [],
    }


class TestScopeMonthSummary:
    def test_month_with_official(self):
        summary = build_scope_month_summary(make_metrics({"2026-06": 0.884}), "2026-06")
        [a] = summary["m1_by_definition"]
        assert summary["in_warehouse"] is True
        assert summary["official_pct"] == 0.884
        assert (a["pct"], a["meets_target"], a["gap_to_target_points"]) == (0.92, True, 2.0)
        assert a["gap_to_official_points"] == pytest.approx(3.6)
        assert a["is_best_fit"] is True
        assert summary["m2_call_processing"] == {"month": "2026-06", "p50_minutes": 1.5}
        assert summary["m3_travel_time"] is None

    def test_month_without_official(self):
        summary = build_scope_month_summary(make_metrics({}), "2026-05")
        [a] = summary["m1_by_definition"]
        assert summary["in_warehouse"] is True
        assert summary["official_pct"] is None
        assert a["meets_target"] is False
        assert a["gap_to_official_points"] is None

    def test_month_absent_from_warehouse_is_all_none(self):
        summary = build_scope_month_summary(make_metrics({"2026-06": 0.884}), "2027-01")
        [a] = summary["m1_by_definition"]
        assert summary["in_warehouse"] is False
        assert (a["pct"], a["numerator"], a["meets_target"], a["gap_to_target_points"]) == (None, None, None, None)
        assert summary["m2_call_processing"] is None


class TestKpiMonthlyCsv:
    def test_header_and_none_pct_renders_empty(self):
        text = kpi_monthly_csv([m1_row("a", "2026-06", 0.9, 9, 10), m1_row("a", "2026-07", None)])
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["month", "definition_id", "numerator", "denominator", "pct", "excluded_no_arrival"]
        assert rows[1] == ["2026-06", "a", "9", "10", "0.9", "0"]
        assert rows[2][4] == ""

    def test_empty_input_is_header_only(self):
        assert kpi_monthly_csv([]).strip().count("\n") == 0


class TestOfficialScorecard:
    def test_excludes_sentinel_non_numeric_null_and_other_measures(self):
        """`actual` is VARCHAR in the source; -9999 means "no value reported"."""
        con = duckdb.connect()
        con.execute("CREATE TABLE scorecard_measures (measure_code VARCHAR, calendar_month VARCHAR, actual VARCHAR)")
        con.executemany("INSERT INTO scorecard_measures VALUES (?, ?, ?)", [
            ("973", "2026-05-31T00:00:00.000", "0.9"),
            ("973", "2026-06-30T00:00:00.000", "-9999"),
            ("973", "2026-04-30T00:00:00.000", "n/a"),
            ("973", "2026-03-31T00:00:00.000", None),
            ("974", "2026-02-28T00:00:00.000", "0.5"),
        ])
        assert get_official_scorecard(con, "973") == {"2026-05": 0.9}
