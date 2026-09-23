"""Load raw JSON into a persistent DuckDB warehouse and run the SQL models.

Idempotent by design (CLAUDE.md rule 7): calls are upserted by `rowid`, and an
incoming row only overwrites an existing one if its `data_loaded_at` is at
least as new - so loading the same raw pull twice, or loading two overlapping
pulls in any order, converges to the same warehouse state. The scorecard
table is small and always represents "the latest published values," so it's
fully replaced on every load rather than upserted.
"""

import argparse
from pathlib import Path

import duckdb

from pipeline.logging_utils import get_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "processed" / "sf_ems.duckdb"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
TRANSFORM_DIR = REPO_ROOT / "pipeline" / "transform"


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def upsert_calls(con: duckdb.DuckDBPyConnection, glob_pattern: str, logger) -> int:
    """Upsert every row matching glob_pattern into raw_calls, keyed on rowid."""
    if not _table_exists(con, "raw_calls"):
        con.execute(
            f"CREATE TABLE raw_calls AS "
            f"SELECT * FROM read_json_auto('{glob_pattern}', union_by_name=true) WHERE 1=0"
        )
        con.execute("CREATE UNIQUE INDEX raw_calls_rowid_idx ON raw_calls(rowid)")
        logger.info("[load/calls] created raw_calls table")

    columns = [row[0] for row in con.execute("DESCRIBE raw_calls").fetchall()]
    non_key_cols = [c for c in columns if c != "rowid"]
    col_list = ", ".join(f'"{c}"' for c in columns)
    set_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in non_key_cols)

    before = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    con.execute(f"""
        INSERT INTO raw_calls ({col_list})
        SELECT {col_list} FROM read_json_auto('{glob_pattern}', union_by_name=true)
        ON CONFLICT (rowid) DO UPDATE SET {set_clause}
        WHERE excluded.data_loaded_at >= raw_calls.data_loaded_at
    """)
    after = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    logger.info("[load/calls] upserted from %s: %d -> %d rows (net +%d)", glob_pattern, before, after, after - before)
    return after


def load_scorecard(con: duckdb.DuckDBPyConnection, glob_pattern: str, logger) -> int:
    """Full-replace the scorecard table - it's small and always reflects the latest published state."""
    con.execute(
        f"CREATE OR REPLACE TABLE scorecard_measures AS "
        f"SELECT * FROM read_json_auto('{glob_pattern}', union_by_name=true)"
    )
    n = con.execute("SELECT COUNT(*) FROM scorecard_measures").fetchone()[0]
    logger.info("[load/scorecard] loaded %d rows from %s", n, glob_pattern)
    return n


def run_transform(con: duckdb.DuckDBPyConnection, logger) -> None:
    """Run every SQL model in pipeline/transform/, in filename order (010_, 020_, ...)."""
    for sql_file in sorted(TRANSFORM_DIR.glob("*.sql")):
        sql = sql_file.read_text(encoding="utf-8")
        con.execute(sql)
        row_count = con.execute(f"SELECT COUNT(*) FROM {sql_file.stem.split('_', 1)[1]}").fetchone()[0]
        logger.info("[transform/%s] %d rows", sql_file.stem, row_count)


def calls_glob_for_run(run_ts: str) -> str:
    return str(RAW_DATA_DIR / "calls" / f"run_ts={run_ts}" / "*" / "page_*.json")


def scorecard_glob_for_run(run_ts: str) -> str:
    return str(RAW_DATA_DIR / "scorecard" / f"run_ts={run_ts}" / "page_*.json")


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load raw data into DuckDB and run the SQL models.")
    parser.add_argument("--calls-run-ts", required=True, help="run_ts under data/raw/calls/ to load")
    parser.add_argument("--scorecard-run-ts", required=True, help="run_ts under data/raw/scorecard/ to load")
    return parser.parse_args()


def main() -> None:
    args = _cli()
    logger = get_logger(f"load_{args.calls_run_ts}")
    con = get_connection()
    upsert_calls(con, calls_glob_for_run(args.calls_run_ts), logger)
    load_scorecard(con, scorecard_glob_for_run(args.scorecard_run_ts), logger)
    run_transform(con, logger)
    con.close()
    logger.info("[load] done. warehouse: %s", DB_PATH)


if __name__ == "__main__":
    main()
