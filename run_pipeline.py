"""One command: extract -> validate -> load -> transform -> metrics -> report -> save.

    python run_pipeline.py --month 2026-07
    python run_pipeline.py --since 3
    python run_pipeline.py --month 2026-07 --chaos duplicate_rowid

A FAIL at the validate stage stops the run before anything is loaded or
published (CLAUDE.md rule 8) - outputs/<scope>/ is only written once the
data has passed every structural check. See docs/decision_log.md and
docs/assumptions.md for why each rule fires WARN vs FAIL.
"""

import argparse

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
    calls_glob_for_run,
    get_connection,
    load_scorecard,
    run_transform,
    scorecard_glob_for_run,
    upsert_calls,
)
from pipeline.logging_utils import get_logger
from pipeline.metrics import run_metrics
from pipeline.report import build_dashboard_html
from pipeline.save import save_month_outputs
from pipeline.validate import run_validation


def run(month: str = None, since_days: int = None, chaos_scenario: str = None) -> dict:
    run_id = make_run_id()
    logger = get_logger(run_id)
    scope_label = month if month else f"since_{since_days}d"
    scope_dir = scope_label
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
        action = chaos_module.SCENARIOS[chaos_scenario](run_id, scope_dir)
        logger.warning("[pipeline/chaos:%s] %s", chaos_scenario, action)

    # VALIDATE
    logger.info("[pipeline] stage=VALIDATE")
    is_historical = month is not None
    scope_desc = f"single month {month}" if month else f"trailing {since_days}-day lookback"
    validation_report = run_validation(run_id, logger, scope=scope_desc)

    if validation_report["overall_status"] == "FAIL":
        failed = [c["rule_id"] for c in validation_report["checks"] if c["severity"] == "FAIL"]
        logger.error("[pipeline] FAIL at stage=VALIDATE: %s", failed)
        logger.error("[pipeline] Next action: fix the failing check(s), or re-run without --chaos.")
        logger.error("[pipeline] STOPPED. Nothing loaded or published.")
        raise SystemExit(1)

    # LOAD + TRANSFORM
    logger.info("[pipeline] stage=LOAD")
    con = get_connection()
    upsert_calls(con, calls_glob_for_run(run_id), logger)
    load_scorecard(con, scorecard_glob_for_run(run_id), logger)
    logger.info("[pipeline] stage=TRANSFORM")
    run_transform(con, logger)

    # METRICS
    logger.info("[pipeline] stage=METRICS")
    metrics = run_metrics(con, logger)
    con.close()

    # REPORT + SAVE (atomic, partitioned by scope_label)
    logger.info("[pipeline] stage=REPORT")
    dashboard_html = build_dashboard_html(scope_label, validation_report, metrics)
    logger.info("[pipeline] stage=SAVE")
    out_dir = save_month_outputs(scope_label, validation_report, metrics, dashboard_html, logger)

    logger.info("[pipeline] DONE run_id=%s status=%s -> %s", run_id, validation_report["overall_status"], out_dir)
    return {"run_id": run_id, "validation_report": validation_report, "metrics": metrics, "out_dir": str(out_dir)}


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", metavar="YYYY-MM", help="Run for one calendar month")
    group.add_argument("--since", type=int, metavar="DAYS", help="Incremental run: trailing N-day lookback")
    parser.add_argument("--chaos", choices=sorted(chaos_module.SCENARIOS), default=None,
                         help="Inject a failure scenario after extract, for testing pipeline dependability")
    return parser.parse_args()


def main() -> None:
    args = _cli()
    run(month=args.month, since_days=args.since, chaos_scenario=args.chaos)


if __name__ == "__main__":
    main()
