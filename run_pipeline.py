"""One command: extract -> validate -> load -> transform -> metrics -> report -> save.

    python run_pipeline.py --month 2026-07
    python run_pipeline.py --since 3
    python run_pipeline.py --month 2026-07 --chaos duplicate_rowid

A FAIL at the validate stage stops the run before anything is loaded or
published (CLAUDE.md rule 8) - outputs/<scope>/ is only written once the
data has passed every structural check. See docs/decision_log.md and
docs/assumptions.md for why each rule fires WARN vs FAIL.

The KPI pack headlines one month (metrics scope_month): the --month value, or
for --since the latest received_dttm month present in the pulled window.

--chaos runs are isolated: they load into a throwaway copy of the warehouse
(data/processed/chaos_<run_id>.duckdb, deleted when the run ends) and write
to outputs/_chaos/<scope>/, so a test run can never corrupt real data or a
real KPI pack (docs/review_findings.md A3).
"""

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

from pipeline import chaos as chaos_module
from pipeline.extract import (
    ExtractionIncompleteError,
    extract_calls_month,
    extract_calls_since,
    extract_scorecard,
    get_app_token,
    load_settings,
    make_run_id,
)
from pipeline.load import (
    DB_PATH,
    calls_glob_for_run,
    get_connection,
    latest_month_in_pull,
    load_scorecard,
    run_transform,
    scorecard_glob_for_run,
    upsert_calls,
)
from pipeline.logging_utils import get_logger
from pipeline.metrics import run_metrics
from pipeline.report import build_dashboard_html
from pipeline.save import OUTPUTS_DIR, save_month_outputs
from pipeline.validate import run_validation

CHAOS_OUTPUTS_DIR = OUTPUTS_DIR / "_chaos"


def _chaos_warehouse_copy(run_id: str, logger) -> Path:
    """Copy the production warehouse to a throwaway file for a chaos run to mutate."""
    chaos_db = DB_PATH.parent / f"chaos_{run_id}.duckdb"
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, chaos_db)
    logger.warning("[pipeline/chaos] using throwaway warehouse %s (production warehouse untouched)", chaos_db)
    return chaos_db


def _remove_warehouse_file(db_path: Path, logger) -> None:
    """Delete a throwaway warehouse and its WAL, if present."""
    for path in (db_path, db_path.with_name(db_path.name + ".wal")):
        path.unlink(missing_ok=True)
    logger.info("[pipeline/chaos] removed throwaway warehouse %s", db_path)


def _raw_calls_count(con: duckdb.DuckDBPyConnection) -> int:
    """raw_calls row count, 0 if the table doesn't exist yet."""
    exists = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'raw_calls'").fetchone()[0]
    return con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0] if exists else 0


def _log_late_update_verification(con: duckdb.DuckDBPyConnection, rowid: Optional[str],
                                  rows_before: int, rows_after: int, logger) -> None:
    """Show the late_update demo worked: the amended value is in the warehouse, no row was added for it."""
    amended = con.execute(
        "SELECT available_dttm, data_loaded_at FROM raw_calls WHERE rowid = ?", [rowid]
    ).fetchone()
    logger.warning(
        "[pipeline/chaos:late_update] verify: rowid=%s available_dttm=%s data_loaded_at=%s | "
        "raw_calls rows before=%d after=%d (throwaway warehouse)",
        rowid, amended[0] if amended else None, amended[1] if amended else None, rows_before, rows_after,
    )


def run(month: Optional[str] = None, since_days: Optional[int] = None, chaos_scenario: Optional[str] = None) -> dict:
    """Run every stage for one scope and publish outputs/<scope>/ (or outputs/_chaos/<scope>/).

    Exactly one of month (YYYY-MM) or since_days must be given. chaos_scenario
    names a pipeline.chaos.SCENARIOS entry to inject after extract. Raises
    SystemExit(1) on an incomplete extract or a FAIL-level validation check,
    before anything is loaded or published. Returns run_id, validation_report,
    metrics and out_dir.
    """
    run_id = make_run_id()
    logger = get_logger(run_id)
    scope_label = month if month else f"since_{since_days}d"
    logger.info("[pipeline] START run_id=%s scope=%s chaos=%s", run_id, scope_label, chaos_scenario or "none")

    settings = load_settings()
    token = get_app_token()

    # EXTRACT
    logger.info("[pipeline] stage=EXTRACT")
    try:
        if month:
            extract_calls_month(month, run_id, settings, token, logger)
        else:
            extract_calls_since(since_days, run_id, settings, token, logger)
        extract_scorecard(run_id, settings, token, logger)
    except ExtractionIncompleteError as exc:
        logger.error("[pipeline] FAIL at stage=EXTRACT: %s", exc)
        logger.error("[pipeline] STOPPED. Nothing loaded or published.")
        raise SystemExit(1)

    # CHAOS (test-only: mutates the raw files just written, before validation sees them)
    if chaos_scenario:
        action = chaos_module.SCENARIOS[chaos_scenario](run_id, scope_label)
        logger.warning("[pipeline/chaos:%s] %s", chaos_scenario, action)

    # VALIDATE
    logger.info("[pipeline] stage=VALIDATE")
    scope_desc = f"single month {month}" if month else f"trailing {since_days}-day lookback"
    validation_report = run_validation(run_id, logger, scope=scope_desc, incremental=since_days is not None)

    if validation_report["overall_status"] == "FAIL":
        failed = [c["rule_id"] for c in validation_report["checks"] if c["severity"] == "FAIL"]
        logger.error("[pipeline] FAIL at stage=VALIDATE: %s", failed)
        logger.error("[pipeline] Next action: fix the failing check(s), or re-run without --chaos.")
        logger.error("[pipeline] STOPPED. Nothing loaded or published.")
        raise SystemExit(1)

    db_path = _chaos_warehouse_copy(run_id, logger) if chaos_scenario else DB_PATH
    outputs_dir = CHAOS_OUTPUTS_DIR if chaos_scenario else OUTPUTS_DIR
    con = None
    try:
        # LOAD + TRANSFORM
        logger.info("[pipeline] stage=LOAD")
        con = get_connection(db_path)
        calls_glob = calls_glob_for_run(run_id)
        rows_before = _raw_calls_count(con)
        rows_after = upsert_calls(con, calls_glob, logger)
        if chaos_scenario == "late_update":
            _log_late_update_verification(con, chaos_module.first_row_rowid(run_id, scope_label),
                                          rows_before, rows_after, logger)
        load_scorecard(con, scorecard_glob_for_run(run_id), logger)
        logger.info("[pipeline] stage=TRANSFORM")
        run_transform(con, logger)

        # METRICS - headline month: --month, or the newest month the --since pull contains
        logger.info("[pipeline] stage=METRICS")
        scope_month = month or latest_month_in_pull(con, calls_glob) or datetime.now(timezone.utc).strftime("%Y-%m")
        metrics = run_metrics(con, logger, scope_month=scope_month)
        con.close()

        # REPORT + SAVE (atomic, partitioned by scope_label)
        logger.info("[pipeline] stage=REPORT")
        dashboard_html = build_dashboard_html(scope_label, validation_report, metrics)
        logger.info("[pipeline] stage=SAVE")
        out_dir = save_month_outputs(scope_label, validation_report, metrics, dashboard_html, logger,
                                     outputs_dir=outputs_dir)
    finally:
        # The throwaway warehouse goes whether the run passed or crashed - it must be
        # closed first, or the file can't be deleted cleanly.
        if con is not None:
            con.close()
        if chaos_scenario:
            _remove_warehouse_file(db_path, logger)

    logger.info("[pipeline] DONE run_id=%s status=%s -> %s", run_id, validation_report["overall_status"], out_dir)
    return {"run_id": run_id, "validation_report": validation_report, "metrics": metrics, "out_dir": str(out_dir)}


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", metavar="YYYY-MM", help="Run for one calendar month")
    group.add_argument("--since", type=int, metavar="DAYS", help="Incremental run: trailing N-day lookback")
    parser.add_argument("--chaos", choices=sorted(chaos_module.SCENARIOS), default=None,
                         help="Inject a failure scenario after extract (isolated warehouse copy + outputs/_chaos/)")
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args = _cli()
    run(month=args.month, since_days=args.since, chaos_scenario=args.chaos)


if __name__ == "__main__":
    main()
