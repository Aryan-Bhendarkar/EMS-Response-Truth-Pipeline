"""Pull raw data from DataSF (SODA API) and save it untouched before any parsing.

Two sources: the unit-level dispatch calls (S1, nuek-vuh3) and the official
monthly scorecard (S3, kc49-udxn, measure 973). Every page fetched is written
to data/raw/<source>/run_ts=<timestamp>/page_NNN.json exactly as received, so
later pipeline stages always have an unmodified copy to fall back on.

Completeness is proven, not assumed: before paginating, we ask the API for
count(*) under the same filter, then check the rows actually received match.
A mismatch is a hard failure — see ExtractionIncompleteError.
"""

import argparse
import calendar
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
import yaml
from dotenv import load_dotenv

from pipeline.logging_utils import get_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"


class ExtractionIncompleteError(RuntimeError):
    """Raised when the API's own count(*) doesn't match the rows we received."""


def load_settings() -> dict:
    """Read the non-secret pipeline config (thresholds, URLs, windows)."""
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_app_token() -> Optional[str]:
    """Read the Socrata app token from .env, if one has been configured."""
    load_dotenv(REPO_ROOT / ".env")
    return os.environ.get("SOCRATA_APP_TOKEN") or None


def make_run_id() -> str:
    """A sortable, filesystem-safe timestamp identifying this extract run."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def month_bounds(month: str) -> tuple[str, str]:
    """Return (start, next_month_start) as SoQL-safe date strings for a 'YYYY-MM' month."""
    year, mon = (int(p) for p in month.split("-"))
    start = f"{year:04d}-{mon:02d}-01"
    last_day = calendar.monthrange(year, mon)[1]
    if mon == 12:
        next_start = f"{year + 1:04d}-01-01"
    else:
        next_start = f"{year:04d}-{mon + 1:02d}-01"
    del last_day  # not needed once we have the next month's start
    return start, next_start


def month_range(start_month: str, end_month: str) -> list[str]:
    """Inclusive list of 'YYYY-MM' strings from start_month to end_month."""
    y, m = (int(p) for p in start_month.split("-"))
    end_y, end_m = (int(p) for p in end_month.split("-"))
    months = []
    while (y, m) <= (end_y, end_m):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


@dataclass
class RetryConfig:
    max_retries: int = 5
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    retry_status_codes: tuple = (429, 500, 502, 503, 504)
    timeout_seconds: float = 60.0

    @classmethod
    def from_settings(cls, settings: dict) -> "RetryConfig":
        r = settings["retrieval"]
        return cls(
            max_retries=r["max_retries"],
            backoff_base_seconds=r["backoff_base_seconds"],
            backoff_max_seconds=r["backoff_max_seconds"],
            retry_status_codes=tuple(r["retry_status_codes"]),
            timeout_seconds=r["timeout_seconds"],
        )


@dataclass
class ExtractResult:
    source: str
    run_id: str
    where: str
    rows_expected: int
    rows_received: int
    pages_written: int
    raw_dir: Path
    complete: bool = field(init=False)

    def __post_init__(self):
        self.complete = self.rows_expected == self.rows_received


def _request_with_retry(
    url: str, params: dict, headers: dict, retry_cfg: RetryConfig, logger, context: str
) -> requests.Response:
    """GET with bounded exponential backoff on 429/5xx and connection errors."""
    last_error: Optional[Exception] = None
    for attempt in range(1, retry_cfg.max_retries + 1):
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=retry_cfg.timeout_seconds
            )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            logger.warning(
                "[extract/%s] connection error on attempt %d/%d: %s",
                context, attempt, retry_cfg.max_retries, exc,
            )
        else:
            if response.status_code not in retry_cfg.retry_status_codes:
                response.raise_for_status()
                return response
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            logger.warning(
                "[extract/%s] retryable HTTP %d on attempt %d/%d",
                context, response.status_code, attempt, retry_cfg.max_retries,
            )

        if attempt < retry_cfg.max_retries:
            delay = min(retry_cfg.backoff_base_seconds * (2 ** (attempt - 1)), retry_cfg.backoff_max_seconds)
            time.sleep(delay)

    raise RuntimeError(
        f"[extract/{context}] gave up after {retry_cfg.max_retries} attempts: {last_error}"
    )


def get_count(base_url: str, where: str, headers: dict, retry_cfg: RetryConfig, logger, context: str) -> int:
    """Ask the API for count(*) under the same filter we're about to page through."""
    response = _request_with_retry(
        base_url, {"$select": "count(*)", "$where": where}, headers, retry_cfg, logger, context
    )
    rows = response.json()
    return int(rows[0]["count"]) if rows else 0


def paginate_and_save(
    base_url: str,
    where: str,
    order_field: str,
    headers: dict,
    retry_cfg: RetryConfig,
    page_size: int,
    raw_dir: Path,
    logger,
    context: str,
) -> tuple[int, int]:
    """Page through the API with $limit/$offset, saving each page untouched.

    Returns (rows_received, pages_written). Pages are saved before any parsing
    so a later stage can always re-derive from the exact bytes the API sent.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    offset = 0
    page_num = 0
    rows_received = 0

    while True:
        params = {
            "$where": where,
            "$order": order_field,
            "$limit": page_size,
            "$offset": offset,
        }
        response = _request_with_retry(base_url, params, headers, retry_cfg, logger, context)
        page_rows = response.json()

        page_path = raw_dir / f"page_{page_num:04d}.json"
        page_path.write_text(response.text, encoding="utf-8")

        n = len(page_rows)
        rows_received += n
        page_num += 1
        logger.info("[extract/%s] page %d: %d rows (offset %d)", context, page_num, n, offset)

        if n < page_size:
            break
        offset += page_size

    return rows_received, page_num


def _write_manifest(raw_dir: Path, manifest: dict) -> None:
    (raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def extract_calls_month(month: str, run_id: str, settings: dict, token: Optional[str], logger) -> ExtractResult:
    """Pull every unit-response row for one calendar month and prove completeness."""
    cfg = settings["sources"]["calls"]
    retry_cfg = RetryConfig.from_settings(settings)
    headers = {"X-App-Token": token} if token else {}

    start, next_start = month_bounds(month)
    where = f"{cfg['timestamp_field']} >= '{start}' AND {cfg['timestamp_field']} < '{next_start}'"
    context = f"calls/{month}"

    logger.info("[%s] requesting count(*) for %s", context, where)
    rows_expected = get_count(cfg["base_url"], where, headers, retry_cfg, logger, context)

    raw_dir = RAW_DATA_DIR / "calls" / f"run_ts={run_id}" / month
    rows_received, pages_written = paginate_and_save(
        cfg["base_url"], where, cfg["order_field"], headers, retry_cfg,
        settings["retrieval"]["page_size"], raw_dir, logger, context,
    )

    result = ExtractResult(
        source="calls", run_id=run_id, where=where,
        rows_expected=rows_expected, rows_received=rows_received,
        pages_written=pages_written, raw_dir=raw_dir,
    )
    _write_manifest(raw_dir, {
        "source": "calls", "month": month, "run_id": run_id, "where": where,
        "rows_expected": rows_expected, "rows_received": rows_received,
        "pages_written": pages_written, "complete": result.complete,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

    if not result.complete:
        raise ExtractionIncompleteError(
            f"[extract/{context}] FAIL: API reported {rows_expected} rows but pagination "
            f"received {rows_received}. Next action: re-run this month; if the gap persists, "
            f"check for pagination limits or API-side filtering changes before trusting this data."
        )
    logger.info("[%s] PASS: %d/%d rows received across %d pages", context, rows_received, rows_expected, pages_written)
    return result


def extract_calls_since(days: int, run_id: str, settings: dict, token: Optional[str], logger) -> ExtractResult:
    """Re-pull a trailing N-day window to catch late-arriving updates (brief Q7).

    This does not by itself deduplicate against previously loaded rows — that
    happens at load time via upsert-by-rowid. This just guarantees we have a
    fresh raw copy of every row DataSF currently reports for the window.
    """
    cfg = settings["sources"]["calls"]
    retry_cfg = RetryConfig.from_settings(settings)
    headers = {"X-App-Token": token} if token else {}

    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    where = f"{cfg['timestamp_field']} >= '{since_date}'"
    context = f"calls/since_{days}d"

    rows_expected = get_count(cfg["base_url"], where, headers, retry_cfg, logger, context)
    raw_dir = RAW_DATA_DIR / "calls" / f"run_ts={run_id}" / f"since_{days}d"
    rows_received, pages_written = paginate_and_save(
        cfg["base_url"], where, cfg["order_field"], headers, retry_cfg,
        settings["retrieval"]["page_size"], raw_dir, logger, context,
    )

    result = ExtractResult(
        source="calls", run_id=run_id, where=where,
        rows_expected=rows_expected, rows_received=rows_received,
        pages_written=pages_written, raw_dir=raw_dir,
    )
    _write_manifest(raw_dir, {
        "source": "calls", "lookback_days": days, "run_id": run_id, "where": where,
        "rows_expected": rows_expected, "rows_received": rows_received,
        "pages_written": pages_written, "complete": result.complete,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

    if not result.complete:
        raise ExtractionIncompleteError(
            f"[extract/{context}] FAIL: API reported {rows_expected} rows but pagination "
            f"received {rows_received}. Next action: re-run the incremental pull."
        )
    logger.info("[%s] PASS: %d/%d rows received", context, rows_received, rows_expected)
    return result


def extract_scorecard(run_id: str, settings: dict, token: Optional[str], logger) -> ExtractResult:
    """Pull the full history of the official scorecard measure (small dataset, no window needed)."""
    cfg = settings["sources"]["scorecard"]
    retry_cfg = RetryConfig.from_settings(settings)
    headers = {"X-App-Token": token} if token else {}

    where = f"measure_code = '{cfg['measure_code']}'"
    context = "scorecard"

    rows_expected = get_count(cfg["base_url"], where, headers, retry_cfg, logger, context)
    raw_dir = RAW_DATA_DIR / "scorecard" / f"run_ts={run_id}"
    rows_received, pages_written = paginate_and_save(
        cfg["base_url"], where, cfg["order_field"], headers, retry_cfg,
        settings["retrieval"]["page_size"], raw_dir, logger, context,
    )

    result = ExtractResult(
        source="scorecard", run_id=run_id, where=where,
        rows_expected=rows_expected, rows_received=rows_received,
        pages_written=pages_written, raw_dir=raw_dir,
    )
    _write_manifest(raw_dir, {
        "source": "scorecard", "measure_code": cfg["measure_code"], "run_id": run_id, "where": where,
        "rows_expected": rows_expected, "rows_received": rows_received,
        "pages_written": pages_written, "complete": result.complete,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

    if not result.complete:
        raise ExtractionIncompleteError(
            f"[extract/{context}] FAIL: API reported {rows_expected} rows but pagination "
            f"received {rows_received}. Next action: re-run the scorecard pull."
        )
    logger.info("[%s] PASS: %d/%d rows received", context, rows_received, rows_expected)
    return result


def extract_calls_month_csv(month: str, run_id: str, settings: dict, token: Optional[str], logger) -> ExtractResult:
    """Pull one month of calls via the CSV export format instead of JSON.

    This is the second retrieval mode (File/CSV, per the assignment rubric),
    deliberately scoped to one month rather than the full 7.44M-row bulk
    history export (data/raw/calls only needs the 12-month analysis window;
    downloading a decade of irrelevant rows would contradict the brief's own
    "scope to 12 months" sizing decision — see docs/decision_log.md). Row
    counts are compared against the JSON pull for the same month in
    docs/decision_log.md as a completeness cross-check between two
    independently-implemented retrieval paths.
    """
    cfg = settings["sources"]["calls"]
    retry_cfg = RetryConfig.from_settings(settings)
    headers = {"X-App-Token": token} if token else {}
    csv_url = cfg["base_url"].replace(".json", ".csv")

    start, next_start = month_bounds(month)
    where = f"{cfg['timestamp_field']} >= '{start}' AND {cfg['timestamp_field']} < '{next_start}'"
    context = f"calls_csv/{month}"

    rows_expected = get_count(cfg["base_url"], where, headers, retry_cfg, logger, context)

    raw_dir = RAW_DATA_DIR / "calls_csv" / f"run_ts={run_id}" / month
    raw_dir.mkdir(parents=True, exist_ok=True)
    page_size = settings["retrieval"]["page_size"]
    offset = 0
    page_num = 0
    rows_received = 0

    while True:
        params = {"$where": where, "$order": cfg["order_field"], "$limit": page_size, "$offset": offset}
        response = _request_with_retry(csv_url, params, headers, retry_cfg, logger, context)
        page_path = raw_dir / f"page_{page_num:04d}.csv"
        page_path.write_text(response.text, encoding="utf-8")

        n = max(response.text.count("\n") - 1, 0)  # data rows = lines minus header
        rows_received += n
        page_num += 1
        logger.info("[extract/%s] page %d: %d rows (offset %d)", context, page_num, n, offset)

        if n < page_size:
            break
        offset += page_size

    result = ExtractResult(
        source="calls_csv", run_id=run_id, where=where,
        rows_expected=rows_expected, rows_received=rows_received,
        pages_written=page_num, raw_dir=raw_dir,
    )
    _write_manifest(raw_dir, {
        "source": "calls_csv", "month": month, "run_id": run_id, "where": where,
        "rows_expected": rows_expected, "rows_received": rows_received,
        "pages_written": page_num, "complete": result.complete,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

    if not result.complete:
        raise ExtractionIncompleteError(
            f"[extract/{context}] FAIL: API reported {rows_expected} rows but the CSV pull "
            f"received {rows_received}. Next action: re-run this month's CSV pull."
        )
    logger.info("[%s] PASS: %d/%d rows received across %d pages", context, rows_received, rows_expected, page_num)
    return result


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract raw SF EMS data from DataSF.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", help="Pull one month of calls, e.g. 2026-07")
    group.add_argument("--backfill", action="store_true", help="Pull the full backfill window from config/settings.yaml")
    group.add_argument("--since", type=int, metavar="DAYS", help="Pull a trailing N-day window of calls")
    group.add_argument("--scorecard", action="store_true", help="Pull the official scorecard measure history")
    group.add_argument("--csv-month", metavar="YYYY-MM", help="Pull one month of calls via the CSV export format (retrieval-mode cross-check)")
    return parser.parse_args()


def main() -> None:
    args = _cli()
    settings = load_settings()
    token = get_app_token()
    run_id = make_run_id()
    logger = get_logger(run_id)

    logger.info("[extract] run_id=%s app_token=%s", run_id, "set" if token else "not set (anonymous rate limit)")

    try:
        if args.month:
            extract_calls_month(args.month, run_id, settings, token, logger)
        elif args.backfill:
            months = month_range(settings["backfill"]["start_month"], settings["backfill"]["end_month"])
            logger.info("[extract/backfill] %d months: %s .. %s", len(months), months[0], months[-1])
            for month in months:
                extract_calls_month(month, run_id, settings, token, logger)
        elif args.since:
            extract_calls_since(args.since, run_id, settings, token, logger)
        elif args.scorecard:
            extract_scorecard(run_id, settings, token, logger)
        elif args.csv_month:
            extract_calls_month_csv(args.csv_month, run_id, settings, token, logger)
    except ExtractionIncompleteError as exc:
        logger.error(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
