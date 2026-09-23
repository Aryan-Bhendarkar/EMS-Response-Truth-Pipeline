"""One-off helper: pull a single day of calls data as a small, committable raw sample.

The real backfill (pipeline/extract.py --backfill) pulls by month and is
gitignored because it's fully reproducible and too large to commit. This
script exists only to produce a small, representative raw sample for
reviewers - see docs/decision_log.md.
"""

from datetime import datetime, timezone

from pipeline.extract import (
    RAW_DATA_DIR,
    RetryConfig,
    _write_manifest,
    get_app_token,
    get_count,
    load_settings,
    paginate_and_save,
)
from pipeline.logging_utils import get_logger

DAY = "2026-06-15"
NEXT_DAY = "2026-06-16"


def main() -> None:
    settings = load_settings()
    token = get_app_token()
    logger = get_logger("sample_day")
    cfg = settings["sources"]["calls"]
    retry_cfg = RetryConfig.from_settings(settings)
    headers = {"X-App-Token": token} if token else {}
    where = f"received_dttm >= '{DAY}' AND received_dttm < '{NEXT_DAY}'"
    context = "calls/sample_day"

    rows_expected = get_count(cfg["base_url"], where, headers, retry_cfg, logger, context)
    raw_dir = RAW_DATA_DIR / "calls" / "run_ts=sample_day" / DAY
    rows_received, pages = paginate_and_save(
        cfg["base_url"], where, cfg["order_field"], headers, retry_cfg,
        settings["retrieval"]["page_size"], raw_dir, logger, context,
    )
    _write_manifest(raw_dir, {
        "source": "calls", "day": DAY, "run_id": "sample_day", "where": where,
        "rows_expected": rows_expected, "rows_received": rows_received,
        "pages_written": pages, "complete": rows_expected == rows_received,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "note": "Small single-day sample committed to git for review; the real "
                "backfill pulls by month and is gitignored (docs/decision_log.md)",
    })
    print(f"DONE expected={rows_expected} received={rows_received}")


if __name__ == "__main__":
    main()
