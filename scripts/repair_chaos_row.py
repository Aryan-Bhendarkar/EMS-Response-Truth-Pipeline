"""One-off repair for docs/review_findings.md A3: a `--chaos late_update` run
(before chaos runs were isolated) wrote a fake available_dttm / data_loaded_at
into the production warehouse for one rowid. Because the fake data_loaded_at
is newer than the real one, a normal reload can never overwrite it (the upsert
only accepts rows at least as new) - so the row is deleted first, then the
month is re-upserted from the original, untouched backfill raw pages and the
SQL models are rebuilt.

    python scripts/repair_chaos_row.py
    python scripts/repair_chaos_row.py --rowid 260320014-B01 --run-ts 20260923T163957Z --month 2026-02

Safe to re-run: the re-upsert is idempotent (every other row of the month is
either identical or already newer in the warehouse, and is left as is).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.load import RAW_DATA_DIR, get_connection, run_transform, upsert_calls  # noqa: E402
from pipeline.logging_utils import get_logger  # noqa: E402


def describe_row(con, rowid: str) -> str:
    """One-line view of the row being repaired plus the warehouse row count."""
    row = con.execute(
        "SELECT available_dttm, data_loaded_at FROM raw_calls WHERE rowid = ?", [rowid]
    ).fetchone()
    total = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    return f"rowid={rowid} available_dttm={row[0] if row else None} data_loaded_at={row[1] if row else None} raw_calls_rows={total}"


def repair(rowid: str, run_ts: str, month: str, logger) -> None:
    """Delete rowid, re-upsert `month` from the raw pages of backfill `run_ts`, rebuild models."""
    glob_pattern = str(RAW_DATA_DIR / "calls" / f"run_ts={run_ts}" / month / "page_*.json")
    con = get_connection()
    try:
        logger.info("[repair] before: %s", describe_row(con, rowid))
        con.execute("DELETE FROM raw_calls WHERE rowid = ?", [rowid])
        logger.info("[repair] deleted rowid=%s; re-upserting %s", rowid, glob_pattern)
        upsert_calls(con, glob_pattern, logger)
        run_transform(con, logger)
        logger.info("[repair] after:  %s", describe_row(con, rowid))
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rowid", default="260320014-B01", help="rowid the chaos run overwrote")
    parser.add_argument("--run-ts", default="20260923T163957Z", help="original backfill run_ts holding the real row")
    parser.add_argument("--month", default="2026-02", help="month folder of that backfill containing the row")
    args = parser.parse_args()
    repair(args.rowid, args.run_ts, args.month, get_logger("repair_chaos_row"))


if __name__ == "__main__":
    main()
