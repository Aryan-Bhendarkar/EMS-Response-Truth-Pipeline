"""Hermetic end-to-end tests over the committed samples (review finding C4):
data/raw/calls/run_ts=sample_day/2026-06-15/ (945 unit rows, one day) and
data/raw/scorecard/run_ts=20260923T163928Z/ (measure 973 history).

Both are copied into a tmp RAW_DATA_DIR, then driven through
validate -> load -> transform -> metrics -> report -> save with a tmp DuckDB
file and tmp outputs dir. No network, and the production warehouse is never
opened.

The sample validates as WARN, not PASS - on purpose: priority_domain is always
WARN (unconfirmed mapping), and a single day shows the known null-rate,
timestamp-order and p99.9-outlier WARNs. The test pins "no FAIL" plus the
exact set of FAIL-capable checks that must pass, rather than a brittle list
of every WARN.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import run_pipeline
from pipeline.load import (
    calls_glob_for_run,
    get_connection,
    load_scorecard,
    run_transform,
    scorecard_glob_for_run,
    upsert_calls,
)
from pipeline.metrics import run_metrics
from pipeline.report import build_dashboard_html
from pipeline.save import save_month_outputs
from pipeline.validate import run_validation
from tests.conftest import (
    SAMPLE_CALLS_DAY_DIR,
    copy_sample_calls,
    copy_sample_scorecard,
    make_raw_row,
    write_manifest,
    write_page,
)

CALLS_RUN, SCORECARD_RUN = "sample_day", "sample_scorecard"
OFFICIAL_2026_06 = 0.884  # measure 973, calendar_month 2026-06-30, in the committed scorecard page
TIMESTAMP_FIELDS = ("received_dttm", "entry_dttm", "dispatch_dttm", "response_dttm", "on_scene_dttm",
                    "transport_dttm", "hospital_dttm", "available_dttm", "data_as_of", "data_loaded_at")
API_FORMAT = "%Y-%m-%dT%H:%M:%S.000"


def pull_loaded_hours_ago(hours: float, n: int = 5) -> list[dict]:
    """n valid raw rows whose whole lifecycle is shifted so DataSF loaded them `hours` ago.

    Only the offset from now matters, so the result is stable within one test
    (rounded to the hour to keep repeated calls identical)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    template = make_raw_row()
    shift = (now - timedelta(hours=hours)) - datetime.strptime(template["data_loaded_at"], API_FORMAT)
    rows = []
    for i in range(n):
        row = make_raw_row(rowid=f"{i}-M1", call_number=str(i))
        for f in TIMESTAMP_FIELDS:
            row[f] = (datetime.strptime(row[f], API_FORMAT) + shift).strftime(API_FORMAT)
        rows.append(row)
    return rows


def sample_distinct_calls() -> int:
    rows = json.loads((SAMPLE_CALLS_DAY_DIR / "page_0000.json").read_text(encoding="utf-8"))
    return len({r["call_number"] for r in rows})


@pytest.fixture
def sample_raw(raw_dir):
    """Committed samples copied into the tmp RAW_DATA_DIR."""
    copy_sample_calls(raw_dir, CALLS_RUN)
    copy_sample_scorecard(raw_dir, SCORECARD_RUN)
    return raw_dir


def load_and_measure(db_path, logger) -> tuple:
    """LOAD + TRANSFORM + METRICS for the sample into db_path; returns (metrics, fct_call rows)."""
    con = get_connection(db_path)
    upsert_calls(con, calls_glob_for_run(CALLS_RUN), logger)
    load_scorecard(con, scorecard_glob_for_run(SCORECARD_RUN), logger)
    run_transform(con, logger)
    n_calls = con.execute("SELECT COUNT(*) FROM fct_call").fetchone()[0]
    metrics = run_metrics(con, logger, scope_month="2026-06")
    con.close()
    return metrics, n_calls


class TestStageByStage:
    def test_sample_flows_through_every_stage(self, sample_raw, tmp_path, logger):
        report = run_validation(CALLS_RUN, logger, scope="committed sample day")
        severities = {c["rule_id"]: c["severity"] for c in report["checks"]}
        assert report["overall_status"] == "WARN"
        assert "FAIL" not in severities.values()
        for must_pass in ("manifest_completeness", "schema_required_columns", "rowid_uniqueness", "freshness"):
            assert severities[must_pass] == "PASS", must_pass

        metrics, n_calls = load_and_measure(tmp_path / "wh.duckdb", logger)
        assert n_calls == sample_distinct_calls() == 469
        summary = metrics["scope_month_summary"]
        assert summary["in_warehouse"] is True
        assert summary["official_pct"] == OFFICIAL_2026_06
        assert metrics["m1_best_fitting_definition"] is not None

        html = build_dashboard_html("2026-06", report, metrics)
        out = save_month_outputs("2026-06", report, metrics, html, logger, outputs_dir=tmp_path / "outputs")
        assert (out / "dashboard.html").exists()
        assert "88.4%" in (out / "dashboard.html").read_text(encoding="utf-8")
        saved = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        assert saved["scope_month_summary"]["official_pct"] == OFFICIAL_2026_06

    def test_loading_the_sample_twice_gives_identical_metrics(self, sample_raw, tmp_path, logger):
        """Idempotency (CLAUDE.md rule 7): re-running a period converges to the same numbers."""
        db = tmp_path / "wh.duckdb"
        first, n_first = load_and_measure(db, logger)
        second, n_second = load_and_measure(db, logger)
        assert n_first == n_second
        con = get_connection(db)
        assert con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0] == 945
        con.close()
        assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)


@pytest.fixture
def driven_pipeline(raw_dir, tmp_path, monkeypatch, logger):
    """run_pipeline.run with extract replaced by 'copy the committed sample',
    and every path it writes to pointed at tmp_path. Records every DB path opened."""
    paths = {
        "db": tmp_path / "processed" / "sf_ems.duckdb",
        "outputs": tmp_path / "outputs",
        "chaos_outputs": tmp_path / "outputs" / "_chaos",
        "opened": [],
        "since_loaded_hours_ago": 1,
    }
    run_ids = iter(f"e2e_run_{i}" for i in range(100))

    def fake_calls_month(month, run_id, settings, token, log):
        copy_sample_calls(raw_dir, run_id, scope_dir=month)

    def fake_calls_since(days, run_id, settings, token, log):
        """A --since pull of 5 synthetic rows; the test sets how recently DataSF loaded them."""
        rows = pull_loaded_hours_ago(paths["since_loaded_hours_ago"])
        scope_dir = raw_dir / "calls" / f"run_ts={run_id}" / f"since_{days}d"
        write_page(scope_dir, rows)
        write_manifest(scope_dir, rows_received=len(rows), lookback_days=days)

    def fake_scorecard(run_id, settings, token, log):
        copy_sample_scorecard(raw_dir, run_id)

    def spy_get_connection(db_path):
        paths["opened"].append(db_path)
        return get_connection(db_path)

    monkeypatch.setattr(run_pipeline, "extract_calls_month", fake_calls_month)
    monkeypatch.setattr(run_pipeline, "extract_calls_since", fake_calls_since)
    monkeypatch.setattr(run_pipeline, "extract_scorecard", fake_scorecard)
    monkeypatch.setattr(run_pipeline, "get_app_token", lambda: None)
    monkeypatch.setattr(run_pipeline, "make_run_id", lambda: next(run_ids))
    monkeypatch.setattr(run_pipeline, "get_logger", lambda run_id: logger)
    monkeypatch.setattr(run_pipeline, "get_connection", spy_get_connection)
    monkeypatch.setattr(run_pipeline, "DB_PATH", paths["db"])
    monkeypatch.setattr(run_pipeline, "OUTPUTS_DIR", paths["outputs"])
    monkeypatch.setattr(run_pipeline, "CHAOS_OUTPUTS_DIR", paths["chaos_outputs"])
    return paths


class TestRunPipeline:
    def test_month_run_publishes_kpi_pack(self, driven_pipeline):
        result = run_pipeline.run(month="2026-06")
        out = driven_pipeline["outputs"] / "2026-06"
        assert result["out_dir"] == str(out)
        assert sorted(p.name for p in out.iterdir()) == [
            "dashboard.html", "kpi_monthly.csv", "metrics.json", "validation_report.json"]
        assert result["metrics"]["scope_month_summary"]["official_pct"] == OFFICIAL_2026_06
        assert driven_pipeline["opened"] == [driven_pipeline["db"]]

    def test_since_run_headlines_latest_month_in_pull(self, driven_pipeline):
        """A fresh --since pull (DataSF loaded it 1h ago) passes freshness and publishes."""
        result = run_pipeline.run(since_days=3)
        latest_received = max(r["received_dttm"] for r in pull_loaded_hours_ago(1))
        assert result["metrics"]["scope_month"] == latest_received[:7]
        freshness = next(c for c in result["validation_report"]["checks"] if c["rule_id"] == "freshness")
        assert freshness["severity"] == "PASS" and "age_hours" in freshness["metric"]
        assert (driven_pipeline["outputs"] / "since_3d" / "dashboard.html").exists()

    def test_since_run_of_stalled_source_fails_freshness(self, driven_pipeline):
        driven_pipeline["since_loaded_hours_ago"] = 59  # DataSF last loaded ~2.5 days ago
        with pytest.raises(SystemExit):
            run_pipeline.run(since_days=3)
        assert not driven_pipeline["outputs"].exists()

    def test_chaos_missing_column_stops_before_load_and_publishes_nothing(self, driven_pipeline):
        with pytest.raises(SystemExit) as exc:
            run_pipeline.run(month="2026-06", chaos_scenario="missing_column")
        assert exc.value.code == 1
        assert not driven_pipeline["outputs"].exists()
        assert driven_pipeline["opened"] == []  # no warehouse, production or throwaway, was opened
        assert not driven_pipeline["db"].parent.exists()

    def test_chaos_late_update_uses_throwaway_warehouse(self, driven_pipeline):
        """A passing chaos run loads into chaos_<run_id>.duckdb, deletes it after,
        and publishes under outputs/_chaos/ - never the real pack or warehouse."""
        result = run_pipeline.run(month="2026-06", chaos_scenario="late_update")
        [opened] = driven_pipeline["opened"]
        assert opened.name == f"chaos_{result['run_id']}.duckdb"
        assert not opened.exists()
        assert not driven_pipeline["db"].exists()
        assert result["out_dir"] == str(driven_pipeline["chaos_outputs"] / "2026-06")
        assert not (driven_pipeline["outputs"] / "2026-06").exists()
