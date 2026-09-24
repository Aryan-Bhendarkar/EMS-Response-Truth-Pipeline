"""Hermetic tests for pipeline/report.py: the dashboard must render (never
raise) when a value is missing, show "n/a" instead of guessing, and
html-escape any text that came from data or config.
"""

from pipeline.metrics import build_scope_month_summary
from pipeline.report import build_dashboard_html

VALIDATION = {"overall_status": "WARN", "checks": [
    {"rule_id": "priority_domain", "severity": "WARN", "action": "Continue."},
]}


def make_metrics(scope_month: str = "2026-06", official: dict | None = None, best: str | None = "a",
                 label: str = "Def A") -> dict:
    """A small but complete metrics dict, shaped like run_metrics' output."""
    metrics = {
        "scope_month": scope_month,
        "target_pct": 0.90,
        "target_minutes": 10,
        "official_scorecard_by_month": official if official is not None else {"2026-06": 0.884},
        "m1_definitions": [{"id": "a", "label": label}],
        "m1_kpi_monthly": [{"definition_id": "a", "month": "2026-06", "numerator": 85, "denominator": 100,
                            "pct": 0.85, "excluded_no_arrival": 3}],
        "m1_reconciliation": {"a": {"months_compared": 1 if best else 0,
                                    "mean_absolute_gap": 0.034 if best else None}},
        "m1_best_fitting_definition": best,
        "m2_call_processing_p50_p90": [{"month": "2026-06", "p50_minutes": 1.4, "p90_minutes": 3.0, "n": 100}],
        "m3_travel_time_p50_p90": [{"month": "2026-06", "p50_minutes": 7.4, "p90_minutes": 17.4, "n": 90}],
        "m4_hospital_turnaround": [{"month": "2026-06", "n_transports": 50, "n_over_standard": 10,
                                    "pct_over_standard": 0.2, "p50_minutes": 20.0, "p90_minutes": 45.0,
                                    "ambulance_hours_lost": 12.0}],
        "m4_standard": {"turnaround_minutes": 30},
        "m5_definition_gap": [],
    }
    metrics["scope_month_summary"] = build_scope_month_summary(metrics, scope_month)
    return metrics


class TestDashboardRendering:
    def test_happy_path_shows_headline_values(self):
        html = build_dashboard_html("2026-06", VALIDATION, make_metrics())
        assert html.startswith("<!DOCTYPE html>")
        assert "85.0%" in html and "88.4%" in html
        assert "below by 5.0 pts" in html

    def test_official_missing_renders_na_and_explains(self):
        html = build_dashboard_html("2026-06", VALIDATION, make_metrics(official={}))
        assert "n/a" in html
        assert "No official scorecard actual is published for 2026-06" in html

    def test_best_fit_missing_renders_na(self):
        """No official months at all -> reconcile finds no best fit -> headline is n/a."""
        html = build_dashboard_html("2026-06", VALIDATION, make_metrics(official={}, best=None))
        assert "n/a" in html
        assert "&#9733; best fit" not in html  # no row is starred when nothing reconciled

    def test_scope_month_absent_from_warehouse(self):
        html = build_dashboard_html("2027-01", VALIDATION, make_metrics(scope_month="2027-01"))
        assert "No call data for 2027-01 is in the warehouse" in html
        assert "n/a" in html

    def test_metrics_without_scope_summary_falls_back_to_latest_month(self):
        """An older metrics.json predates scope_month_summary - it must still render."""
        metrics = make_metrics()
        del metrics["scope_month_summary"], metrics["scope_month"]
        assert "headline month 2026-06" in build_dashboard_html("2026-06", VALIDATION, metrics)

    def test_labels_from_config_are_html_escaped(self):
        html = build_dashboard_html("<b>x</b>", VALIDATION, make_metrics(label="<script>alert(1)</script>"))
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html
